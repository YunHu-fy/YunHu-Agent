"""Model metadata and revisioned credentials; JSON never contains API secrets."""
from __future__ import annotations

import copy
import json
import os
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from .config import validate_settings

PROFILE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
REASONING_LEVELS = {"low", "medium", "high"}
PROFILE_FIELDS = {"id", "base_url", "model", "context_window", "max_output_tokens", "reasoning_enabled", "reasoning_level", "supports_images"}
SECRET_FIELDS = {"api_key", "clear_api_key", "rebind_api_key"}


def validate_api_key(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 2000 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("API密钥格式无效。")
    return value if value.strip() else ""


@dataclass(frozen=True)
class ModelProfile:
    id: str
    base_url: str
    model: str
    context_window: int = 65536
    max_output_tokens: int = 4096
    reasoning_enabled: bool = False
    reasoning_level: str = "medium"
    supports_images: bool = False

    @classmethod
    def parse(cls, value: Any, *, allow_empty_model: bool = False) -> "ModelProfile":
        if not isinstance(value, dict) or set(value) - PROFILE_FIELDS - SECRET_FIELDS - {"has_api_key"}:
            raise ValueError("模型配置包含未知字段。")
        profile_id = value.get("id") or uuid.uuid4().hex
        if not isinstance(profile_id, str) or not PROFILE_ID.fullmatch(profile_id):
            raise ValueError("模型配置ID必须为1..64个字母、数字、下划线或短横线。")
        if "id" in value and not value["id"]:
            raise ValueError("模型配置ID不能为空。")
        base = value.get("base_url", "http://127.0.0.1:1234/v1")
        name = value.get("model", "")
        validate_settings({"model_base_url": base, "model_name": name})
        if not allow_empty_model and not name.strip():
            raise ValueError("请填写模型名称。")
        context = value.get("context_window", 65536)
        output = value.get("max_output_tokens", 4096)
        if type(context) is not int or not 256 <= context <= 2097152:
            raise ValueError("context_window必须是256..2097152的整数。")
        if type(output) is not int or not 1 <= output <= 1048576 or output >= context:
            raise ValueError("max_output_tokens必须是正整数且小于context_window（最多1048576）。")
        for key in ("reasoning_enabled", "supports_images", "clear_api_key", "rebind_api_key", "has_api_key"):
            if key in value and type(value[key]) is not bool:
                raise ValueError(key + "必须是布尔值。")
        level = value.get("reasoning_level", "medium")
        if not isinstance(level, str) or level not in REASONING_LEVELS:
            raise ValueError("reasoning_level必须是low、medium或high。")
        if "api_key" in value:
            validate_api_key(value["api_key"])
        if value.get("clear_api_key") and value.get("api_key", "").strip():
            raise ValueError("不能同时填写API密钥并清除密钥。")
        return cls(profile_id, base.rstrip("/"), name.strip(), context, output,
                   value.get("reasoning_enabled", False), level, value.get("supports_images", False))


@dataclass(frozen=True)
class ModelSelection:
    profile: ModelProfile
    _api_key: str = field(repr=False, compare=False)

    def override_reasoning(self, level: Any) -> "ModelSelection":
        if level is None:
            return self
        if not isinstance(level, str) or level not in REASONING_LEVELS | {"none"}:
            raise ValueError("本次任务reasoning_level必须是none、low、medium或high。")
        profile = replace(self.profile, reasoning_enabled=level != "none",
                          reasoning_level=self.profile.reasoning_level if level == "none" else level)
        return ModelSelection(profile, self._api_key)


class MemoryVault:
    """Explicit session-only fallback for desktop and injected test adapters."""
    credential_persistence = "memory_session"

    def __init__(self):
        self._keys: dict[str, str] = {}

    def credential_get(self, profile_id: str) -> str:
        return self._keys.get(profile_id, "")

    def credential_set(self, profile_id: str, secret: str) -> None:
        self._keys[profile_id] = secret

    def credential_delete(self, profile_id: str) -> None:
        self._keys.pop(profile_id, None)


class ModelStore:
    def __init__(self, path: Path, legacy: dict[str, Any], vault: Any = None):
        self.path = path
        self.vault = vault if vault is not None else MemoryVault()
        self._lock = threading.RLock()
        self._known_secrets: set[str] = set()
        self._redaction_loaded: set[str] = set()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._profiles: dict[str, ModelProfile] = {}
        self._credentials: dict[str, str] = {}
        self.active_model_id: str | None = None
        if path.exists():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict) or set(loaded) - {"profiles", "active_model_id", "version"} or not isinstance(loaded.get("profiles"), list):
                raise ValueError("models.json格式无效。")
            for record in loaded["profiles"]:
                if not isinstance(record, dict):
                    raise ValueError("保存的模型配置格式无效。")
                values = {key: value for key, value in record.items() if key != "credential_id"}
                profile = ModelProfile.parse(values, allow_empty_model=True)
                if profile.id in self._profiles:
                    raise ValueError("保存的模型配置ID重复。")
                credential_id = record.get("credential_id", "")
                if not isinstance(credential_id, str) or (credential_id and not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", credential_id)):
                    raise ValueError("保存的模型凭据引用无效。")
                self._profiles[profile.id] = profile
                self._credentials[profile.id] = credential_id
            self.active_model_id = loaded.get("active_model_id")
            self._validate_active(self.active_model_id, self._profiles)
        else:
            profile = ModelProfile.parse({"id": "default", "base_url": legacy["model_base_url"], "model": legacy["model_name"]}, allow_empty_model=True)
            self._profiles[profile.id] = profile
            self._credentials[profile.id] = ""
            self.active_model_id = profile.id
            self._save(self._profiles, self._credentials, self.active_model_id)

    @property
    def credential_persistence(self) -> str:
        return getattr(self.vault, "credential_persistence", "memory_session")

    @staticmethod
    def _validate_active(active: Any, profiles: dict[str, ModelProfile]) -> None:
        if (profiles and (not isinstance(active, str) or active not in profiles)) or (not profiles and active is not None):
            raise ValueError("active_model_id必须引用一个已保存的模型配置；空列表只能使用null。")

    def _key(self, profile_id: str) -> str:
        credential_id = self._credentials.get(profile_id, "")
        key = validate_api_key(self.vault.credential_get(credential_id)) if credential_id else ""
        if credential_id and not key and self.credential_persistence == "android_keystore":
            raise ValueError("已保存的模型密钥不可读取，请在该模型配置中重新输入并保存。")
        if key:
            self._known_secrets.add(key)
        return key

    def remember_secret(self, secret: str) -> None:
        if secret:
            with self._lock:
                self._known_secrets.add(secret)

    def secret_values(self) -> tuple[str, ...]:
        with self._lock:
            for profile_id in self._profiles:
                reference = self._credentials.get(profile_id, "")
                if not reference or reference in self._redaction_loaded:
                    continue
                try:
                    self._key(profile_id)
                except Exception:
                    pass
                self._redaction_loaded.add(reference)
            return tuple(self._known_secrets)

    def public(self) -> dict[str, Any]:
        with self._lock:
            return {"profiles": [{**asdict(profile), "has_api_key": bool(self._credentials.get(profile.id))} for profile in self._profiles.values()],
                    "active_model_id": self.active_model_id}

    def export_metadata(self) -> dict[str, Any]:
        """Portable metadata only. Import must use replace_all and never restore vault references."""
        with self._lock:
            return {"profiles": [asdict(profile) for profile in self._profiles.values()], "active_model_id": self.active_model_id}

    def select(self, profile_id: Any = None) -> ModelSelection | None:
        with self._lock:
            selected = self.active_model_id if profile_id is None else profile_id
            if selected is None:
                return None
            if not isinstance(selected, str) or selected not in self._profiles:
                raise ValueError("模型配置不存在。")
            return ModelSelection(self._profiles[selected], self._key(selected))

    def replace_all(self, values: Any, *, allow_empty_model: bool = False) -> dict[str, Any]:
        if not isinstance(values, dict) or set(values) != {"profiles", "active_model_id"} or not isinstance(values["profiles"], list) or len(values["profiles"]) > 64:
            raise ValueError("模型配置需要profiles列表（最多64项）和active_model_id。")
        # Validate the entire request before touching any credential or metadata.
        profiles: dict[str, ModelProfile] = {}
        drafts: dict[str, dict[str, Any]] = {}
        for value in values["profiles"]:
            profile = ModelProfile.parse(value, allow_empty_model=allow_empty_model)
            if profile.id in profiles:
                raise ValueError("模型配置ID不得重复。")
            profiles[profile.id] = profile
            drafts[profile.id] = value
        active = values["active_model_id"]
        self._validate_active(active, profiles)
        with self._lock:
            credentials: dict[str, str] = {}
            updates: list[tuple[str, str]] = []
            for profile_id, profile in profiles.items():
                draft = drafts[profile_id]
                key = validate_api_key(draft.get("api_key", ""))
                existing = self._profiles.get(profile_id)
                old_reference = self._credentials.get(profile_id, "")
                if existing and existing.base_url != profile.base_url and old_reference and not (key or draft.get("clear_api_key") or draft.get("rebind_api_key")):
                    raise ValueError("端点已改变；请重新输入API密钥、明确清除或确认重新绑定密钥。")
                if draft.get("clear_api_key"):
                    credentials[profile_id] = ""
                elif key:
                    # A new vault reference makes metadata replacement the commit point.
                    credential_id = uuid.uuid4().hex
                    credentials[profile_id] = credential_id
                    updates.append((credential_id, key))
                else:
                    credentials[profile_id] = self._credentials.get(profile_id, "")
            created: list[str] = []
            try:
                for credential_id, key in updates:
                    created.append(credential_id)
                    self._known_secrets.add(key)
                    self.vault.credential_set(credential_id, key)
                    self._redaction_loaded.add(credential_id)
                self._save(profiles, credentials, active)
            except Exception:
                for credential_id in created:
                    try:
                        self.vault.credential_delete(credential_id)
                    except Exception:
                        pass
                raise
            obsolete = set(self._credentials.values()) - set(credentials.values()) - {""}
            self._profiles, self._credentials, self.active_model_id = profiles, credentials, active
            for credential_id in obsolete:
                try:
                    self.vault.credential_delete(credential_id)
                except Exception:
                    pass  # Metadata already unlinks the old ciphertext; a later device cleanup can remove it.
            return self.public()

    def update_legacy(self, base_url: str, model: str, **secret: Any) -> None:
        with self._lock:
            profile_id = self.active_model_id or "default"
            existing = self._profiles.get(profile_id)
            profiles = [asdict(profile) for profile in self._profiles.values() if profile.id != profile_id]
            profiles.append({**(asdict(existing) if existing else {"id": profile_id}), "base_url": base_url, "model": model, **secret})
            self.replace_all({"profiles": profiles, "active_model_id": profile_id}, allow_empty_model=True)

    def delete(self, profile_id: str) -> dict[str, Any]:
        with self._lock:
            if profile_id not in self._profiles:
                raise ValueError("模型配置不存在。")
            profiles = [asdict(profile) for profile in self._profiles.values() if profile.id != profile_id]
            active = self.active_model_id if self.active_model_id != profile_id else (profiles[0]["id"] if profiles else None)
            return self.replace_all({"profiles": profiles, "active_model_id": active}, allow_empty_model=True)

    def draft(self, values: dict[str, Any]) -> ModelSelection:
        """Resolve a test draft without giving a changed endpoint another saved key."""
        with self._lock:
            profile_id = values.get("profile_id", values.get("model_profile_id"))
            profile_id = self.active_model_id if profile_id is None else profile_id
            if profile_id is not None and (not isinstance(profile_id, str) or profile_id not in self._profiles):
                raise ValueError("模型配置不存在。")
            existing = self._profiles.get(profile_id)
            base_values = asdict(existing) if existing else {}
            aliases = {"model_base_url": "base_url", "model_name": "model"}
            for key, value in values.items():
                target = aliases.get(key, key)
                if target in PROFILE_FIELDS | SECRET_FIELDS:
                    base_values[target] = value
            profile = ModelProfile.parse(base_values)
            key = validate_api_key(values.get("api_key", ""))
            if values.get("clear_api_key"):
                key = ""
            elif not key and existing:
                if profile.base_url != existing.base_url and self._credentials.get(profile_id) and not values.get("rebind_api_key"):
                    raise ValueError("测试端点与保存端点不同；请重新输入API密钥或明确清除密钥。")
                key = self._key(profile_id)
            if key:
                self._known_secrets.add(key)
            return ModelSelection(profile, key)


    def _save(self, profiles: dict[str, ModelProfile], credentials: dict[str, str], active: str | None) -> None:
        data = {"version": 1, "profiles": [{**asdict(profile), "credential_id": credentials.get(profile.id, "")} for profile in profiles.values()], "active_model_id": active}
        temp = self.path.with_name(self.path.name + ".tmp." + uuid.uuid4().hex)
        try:
            with temp.open("x", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.chmod(temp, 0o600)
            except OSError:
                pass
            temp.replace(self.path)
        finally:
            temp.unlink(missing_ok=True)


def completion_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"type": "function", "function": {"name": item["name"].replace(".", "_"), "description": item["description"], "parameters": item["inputSchema"]}} for item in tools]


def estimate_context(profile: ModelProfile, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> int:
    """Conservative UTF-8 byte upper bound; no provider tokenizer dependency or clipping.

    Image parts use low detail and reserve 4096 tokens each across compatible models.
    Base64 transport bytes are not text tokens. All other content and tool schemas
    count in full, with message framing and an output reservation.
    """
    bounded = copy.deepcopy(messages)
    images = 0
    for message in bounded:
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if part.get("type") == "image_url":
                    if not profile.supports_images:
                        raise ValueError("所选模型不支持图片；请选择支持图片的模型配置。")
                    part["image_url"] = {"url": "[image]", "detail": "low"}
                    images += 1
    # One token per UTF-8 byte intentionally errs toward rejecting, never truncating.
    tokens = len(json.dumps({"messages": bounded, "tools": completion_tools(tools)}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 32 * len(messages) + 256 + images * 4096
    return tokens


def validate_context(profile: ModelProfile, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> int:
    tokens = estimate_context(profile, messages, tools)
    if tokens + profile.max_output_tokens > profile.context_window:
        raise ValueError(f"自动整理后请求预算仍为{tokens}，输出预留{profile.max_output_tokens}，超过context_window={profile.context_window}。该配置不足以容纳必要指令/工具或当前图片，请使用实际支持更大窗口的模型或减少最大输出。")
    return tokens
