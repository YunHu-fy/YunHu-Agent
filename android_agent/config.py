"""Validated, non-secret application configuration. Execution authority is per task."""
from __future__ import annotations

import copy
import json
import os
import re
import threading
import urllib.parse
from pathlib import Path
from typing import Any

BLACKLIST_SEMANTICS = (
    "Case-sensitive matching against the complete POSIX script: plain entries and "
    "substring:TEXT match a literal substring; glob:PATTERN uses fnmatchcase on the "
    "entire script (* matches newlines). This is a user deny list, not a shell sandbox. "
    "It remains enforced in full access mode."
)
DEFAULT_SETTINGS: dict[str, Any] = {
    "model_base_url": "http://127.0.0.1:1234/v1", "model_name": "",
    "model_enabled": False, "cloud_consent": False, "local_model_active": False, "disclaimer_accepted": False,
    "blacklist": [], "command_timeout_seconds": 120, "task_timeout_seconds": 3600,
    "output_cap_bytes": 262144, "max_rounds": 40, "default_runtime": "system",
    "local_cpu_acceleration_enabled": False, "local_gpu_acceleration_enabled": False, "local_npu_acceleration_enabled": False,
    "anima_low_memory_enabled": False, "local_model_threads": 4, "local_model_context": 4096, "mcp_enabled": False,
    "update_manifest_url": "", "auto_check_updates": False,
    "state_refresh_seconds": 5, "background_locks": False, "log_retention_days": 7,
    "ui_theme": "system", "ui_font_size": "md", "ui_language": "zh",
}
_BOUNDS = {"command_timeout_seconds": (1, 3600), "task_timeout_seconds": (30, 14400),
           "output_cap_bytes": (1024, 4194304), "max_rounds": (1, 50),
           "state_refresh_seconds": (1, 300), "log_retention_days": (1, 7),
           "local_model_threads": (1, 16), "local_model_context": (512, 8192)}
_BOOL = {"model_enabled", "cloud_consent", "local_model_active", "disclaimer_accepted", "auto_check_updates", "background_locks",
         "local_cpu_acceleration_enabled", "local_gpu_acceleration_enabled", "local_npu_acceleration_enabled", "anima_low_memory_enabled", "mcp_enabled"}


def validate_settings(values: Any) -> dict[str, Any]:
    if not isinstance(values, dict):
        raise ValueError("设置必须是JSON对象。")
    # Old installations can contain the removed toggle preference. It has no effect.
    unknown = set(values) - set(DEFAULT_SETTINGS) - {"enabled_tools"}
    if unknown:
        raise ValueError("未知设置字段：" + ", ".join(sorted(unknown)))
    result = copy.deepcopy({key: value for key, value in values.items() if key in DEFAULT_SETTINGS})
    for key, value in result.items():
        if key in _BOOL and type(value) is not bool:
            raise ValueError(key + "必须是布尔值。")
        if key in _BOUNDS:
            low, high = _BOUNDS[key]
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{key}必须是{low}..{high}的整数。")
        if key in {"ui_theme", "ui_font_size", "ui_language"}:
            allowed = {"ui_theme": {"system", "light", "dark"}, "ui_font_size": {"xs", "sm", "md", "lg", "xl"}, "ui_language": {"zh", "en"}}
            if not isinstance(value, str) or value not in allowed[key]:
                raise ValueError(key + "包含不支持的界面选项。")
        if key == "default_runtime" and value not in {"system", "termux"}:
            raise ValueError("default_runtime必须是system或termux。")
        if key == "model_name" and (not isinstance(value, str) or len(value) > 200 or any(ord(c) < 32 for c in value)):
            raise ValueError("模型名称格式无效。")
        if key in {"model_base_url", "update_manifest_url"}:
            if not isinstance(value, str) or len(value) > 1000 or any(ord(c) < 32 for c in value):
                raise ValueError("URL格式无效。")
            if not value and key == "update_manifest_url":
                continue
            parsed = urllib.parse.urlsplit(value)
            try:
                parsed.port
            except ValueError as exc:
                raise ValueError("URL端口无效。") from exc
            schemes = {"https"} if key == "update_manifest_url" else {"http", "https"}
            if parsed.scheme not in schemes or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError("URL必须是有效的HTTP(S)端点，更新地址须HTTPS，不能嵌入凭据、查询或片段。")
        if key == "blacklist":
            if not isinstance(value, list) or len(value) > 256:
                raise ValueError("黑名单必须是最多256个字符串的列表。")
            for entry in value:
                if not isinstance(entry, str) or not entry or len(entry) > 2048 or any(ord(c) < 32 and c not in "\n\r\t" for c in entry):
                    raise ValueError("每条黑名单必须是1..2048字符的字符串。")
                if entry in {"glob:", "substring:"}:
                    raise ValueError("黑名单模式不能为空。")
    if result.get("local_gpu_acceleration_enabled") and result.get("local_npu_acceleration_enabled"):
        raise ValueError("GPU 与 NPU 加速不能同时开启；请只选择一种硬件后端。")
    return result


ACCELERATION_KEYS = ("local_cpu_acceleration_enabled", "local_gpu_acceleration_enabled",
                     "local_npu_acceleration_enabled", "anima_low_memory_enabled")
# The bundled engine always listens on 127.0.0.1:18xxx; no third-party profile uses that port.
_LOCAL_ENDPOINT = re.compile(r"^http://127\.0\.0\.1:1[89]\d{3}/v1$")


def acceleration_scope(values: dict[str, Any]) -> bool:
    """True only while a bundled local model is the selected engine."""
    if values.get("local_model_active", False):
        return True
    return bool(_LOCAL_ENDPOINT.match(str(values.get("model_base_url") or "")))


def apply_acceleration_policy(values: dict[str, Any]) -> dict[str, Any]:
    """Hardware acceleration belongs to the bundled local engine only.

    A remote OpenAI-compatible profile (address plus optional key) never carries
    acceleration authority, so switching to it clears every toggle instead of
    leaving a dormant flag that could be mistaken for an active setting.
    """
    result = dict(values)
    if not acceleration_scope(result):
        for key in ACCELERATION_KEYS:
            result[key] = False
    if result.get("local_gpu_acceleration_enabled") and result.get("local_npu_acceleration_enabled"):
        result["local_npu_acceleration_enabled"] = False
    return result



class SettingsStore:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._values = copy.deepcopy(DEFAULT_SETTINGS)
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                for key, value in loaded.items():
                    if key in DEFAULT_SETTINGS:
                        try:
                            self._values.update(validate_settings({key: value}))
                        except ValueError:
                            pass
        except (OSError, ValueError):
            pass
        self._values = apply_acceleration_policy(self._values)
        self._save()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._values)

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        validated = validate_settings(values)
        with self._lock:
            updated = {**self._values, **validated}
            # Remote profiles and idle states never carry acceleration authority.
            updated = apply_acceleration_policy(updated)
            # Revoking remote-data consent disables remote model use atomically.
            # A running local model remains usable without cloud consent.
            if not updated["cloud_consent"] and not updated["local_model_active"] and "model_enabled" not in validated:
                updated["model_enabled"] = False
            if updated["model_enabled"] and (not updated["model_name"].strip() or (not updated["cloud_consent"] and not updated["local_model_active"])):
                raise ValueError("启用模型前需填写模型名称；远程服务还需明确同意发送数据。")
            self._values = updated
            self._save()
            return self.snapshot()

    def _save(self) -> None:
        temp = self.path.with_suffix(".tmp")
        with temp.open("w", encoding="utf-8") as stream:
            stream.write(json.dumps(self._values, ensure_ascii=False, indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.chmod(temp, 0o600)
        except OSError:
            pass
        temp.replace(self.path)
