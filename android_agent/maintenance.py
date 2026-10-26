"""Local operational facilities. This module never executes downloaded code."""
from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import __version__
from .security import SecurityError, is_link_or_reparse

_SECRET = re.compile(r"(?:authorization|api[_-]?key|password|secret|token|credential)", re.I)
_LEVELS = {"INFO", "WARN", "ERROR"}


class LocalLog:
    """Daily JSONL with gzip size rotation, a seven-day retention window and no telemetry."""
    def __init__(self, root: Path, secret_provider=lambda: (), max_bytes: int = 10 * 1024 * 1024):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.secret_provider = secret_provider
        self.max_bytes = max_bytes
        self.lock = threading.RLock()

    def _sanitize(self, value: Any, key: str = "") -> Any:
        if _SECRET.search(key):
            return "[REDACTED]"
        if isinstance(value, dict):
            return {str(k): self._sanitize(v, str(k)) for k, v in list(value.items())[:80]}
        if isinstance(value, (list, tuple)):
            return [self._sanitize(item) for item in value[:80]]
        if isinstance(value, str):
            text = value[:16000]
            for secret in self.secret_provider():
                if isinstance(secret, str) and len(secret) >= 4:
                    text = text.replace(secret, "[REDACTED]")
            text = re.sub(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/-]+", r"\1[REDACTED]", text)
            text = re.sub(r"(?i)((?:api[_-]?key|password|access_token)\s*[:=]\s*)[^\s,;]+", r"\1[REDACTED]", text)
            return text
        if value is None or isinstance(value, (int, float, bool)):
            return value
        return self._sanitize(str(value))

    def _files(self):
        return sorted((p for p in self.root.iterdir() if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:\.[a-f0-9]+\.jsonl\.gz|\.jsonl)", p.name) and p.is_file() and not is_link_or_reparse(p)), key=lambda p:p.name, reverse=True)

    def cleanup(self):
        cutoff = (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=6)).isoformat()
        for file in self._files():
            if file.name[:10] < cutoff:
                file.unlink(missing_ok=True)

    def log(self, level: str, message: str, **fields: Any) -> None:
        level = level.upper()
        if level not in _LEVELS:
            level = "INFO"
        now = dt.datetime.now(dt.timezone.utc)
        item = self._sanitize({"timestamp":now.isoformat(), "time":now.timestamp(), "level":level, "message":str(message), "fields":fields})
        payload = (json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with self.lock:
            target = self.root / (now.date().isoformat() + ".jsonl")
            if is_link_or_reparse(target):
                raise SecurityError("日志目标不得为链接。")
            if target.exists() and target.stat().st_size + len(payload) > self.max_bytes:
                archive = self.root / (now.date().isoformat() + "." + secrets.token_hex(6) + ".jsonl.gz")
                with target.open("rb") as src, gzip.open(archive, "wb") as dst:
                    import shutil
                    shutil.copyfileobj(src, dst)
                target.unlink()
            flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(target, flags, 0o600)
            with os.fdopen(fd, "ab") as stream:
                stream.write(payload)
            self.cleanup()

    def query(self, level: str = "", q: str = "", limit: int = 200) -> list[dict[str, Any]]:
        level = str(level).upper()
        if level and level not in _LEVELS:
            raise ValueError("日志级别仅支持 INFO/WARN/ERROR。")
        if not isinstance(q, str) or len(q) > 200:
            raise ValueError("查询关键字过长。")
        limit = max(1, min(int(limit), 500))
        rows = []
        with self.lock:
            for file in self._files():
                opener = gzip.open if file.suffix == ".gz" else open
                with opener(file, "rt", encoding="utf-8", errors="replace") as stream:
                    for line in stream:
                        if len(line) > 131072:
                            continue
                        try:
                            row = self._sanitize(json.loads(line))
                        except (ValueError, TypeError):
                            continue
                        if isinstance(row, dict) and (not level or row.get("level") == level) and (not q or q.casefold() in json.dumps(row, ensure_ascii=False).casefold()):
                            rows.append(row)
                if len(rows) > limit * 3:
                    rows = sorted(rows, key=lambda x:x.get("time", 0), reverse=True)[:limit]
        return sorted(rows, key=lambda x:x.get("time", 0), reverse=True)[:limit]

    def export(self) -> str:
        return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in reversed(self.query(limit=500)))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("更新清单不允许重定向；请配置最终HTTPS地址。")


def _https_url(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("URL无效。")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError("更新地址必须是无凭据的 HTTPS URL。")
    return value


def version_key(version: str) -> tuple[int, ...]:
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:[-+][A-Za-z0-9.-]+)?", version)
    if not match:
        raise ValueError("版本号必须符合 major.minor.patch。")
    return tuple(int(value) for value in match.groups())


def validate_update(payload: Any, current: str = __version__) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("更新清单必须为JSON对象。")
    version = payload.get("version", "")
    latest = version_key(version)
    download = _https_url(payload.get("download_url", ""))
    checksum = payload.get("sha256", "")
    if not isinstance(checksum, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", checksum):
        raise ValueError("更新清单缺少有效的SHA-256。")
    checksum = checksum.lower()
    notes = payload.get("notes", "")
    if not isinstance(notes, str) or len(notes) > 16000:
        raise ValueError("更新说明过长。")
    return {"ok":True,"configured":True,"current_version":current,"latest_version":version,"update_available":latest > version_key(current),"download_url":download,"sha256":checksum,"notes":notes,"checked_at":time.time(),"automatic_install":False}


class AppMaintenance:
    def __init__(self, manager):
        self.manager = manager
        self.logs = LocalLog(manager.root / "data/logs", lambda: manager.secret_values() if hasattr(manager, "secret_values") else (getattr(manager, "api_token", ""), getattr(manager, "api_key", "")))
        self.logger = self.logs
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.thread = None
        self.cached_state: dict[str, Any] = {"ok":False,"supported":False,"stale":True,"checked_at":None,"message":"尚未获取设备状态。"}
        self.last_update: dict[str, Any] = {"ok":True,"configured":False,"current_version":__version__,"update_available":False,"message":"尚未配置更新清单地址。"}
        self.last_update_attempt = 0.0

    def _native(self, method: str, *args):
        bridge = getattr(self.manager, "android", None)
        native = getattr(bridge, "_native", None)
        if native is None or not hasattr(native, method):
            return {"ok":False,"supported":False,"error":{"code":"unsupported","message":"此能力仅在Android APK内可用。"}}
        value = getattr(native, method)(*args)
        result = json.loads(str(value))
        if not isinstance(result, dict):
            raise ValueError("原生服务返回格式无效。")
        return result

    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.stop_event.clear()
            self.logs.log("INFO", "应用维护服务启动", version=__version__)
            self.thread = threading.Thread(target=self._loop, name="agent-maintenance", daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                self.device_state(refresh=True)
                settings = self.manager.settings.snapshot()
                if settings.get("auto_check_updates") and settings.get("update_manifest_url") and time.time() - self.last_update_attempt > 24*3600:
                    self.check_updates()
            except Exception as exc:
                self.logs.log("WARN", "维护检查未完成", error=type(exc).__name__)
            self.stop_event.wait(5)

    def status(self):
        with self.lock:
            return {"state":dict(self.cached_state),"update":dict(self.last_update),"logs_retention_days":7,"log_max_bytes":self.logs.max_bytes,"log_export_limit":500}

    def device_state(self, refresh=False):
        with self.lock:
            cached = dict(self.cached_state)
        if not refresh and cached.get("checked_at") and time.time() - cached["checked_at"] < 10:
            return {**cached,"stale":False}
        try:
            state = self._native("deviceState")
            state["checked_at"] = time.time()
            state["stale"] = False
        except Exception as exc:
            state = {**cached,"ok":False,"stale":True,"error":{"code":"state_unavailable","message":str(exc)[:300]}}
        with self.lock:
            self.cached_state = state
        return dict(state)

    def query_logs(self, level="", q="", limit=200):
        return self.logs.query(level, q, limit)

    def export_logs(self):
        return self.logs.export()

    def check_updates(self):
        url = self.manager.settings.snapshot().get("update_manifest_url", "")
        self.last_update_attempt = time.time()
        if not url:
            result = {"ok":True,"configured":False,"current_version":__version__,"update_available":False,"message":"请在设置中填写发布者的HTTPS更新清单地址。"}
        else:
            try:
                url = _https_url(url)
                opener = urllib.request.build_opener(_NoRedirect)
                request = urllib.request.Request(url, headers={"Accept":"application/json","User-Agent":"LocalAndroidAgent/"+__version__})
                with opener.open(request,timeout=12) as response:
                    raw = response.read(262145)
                if len(raw) > 262144:
                    raise ValueError("更新清单超过256KiB。")
                result = validate_update(json.loads(raw))
                self.logs.log("INFO", "更新检查完成", latest=result["latest_version"], update_available=result["update_available"])
            except Exception as exc:
                result = {"ok":False,"configured":True,"current_version":__version__,"update_available":False,"message":str(exc)[:500],"checked_at":time.time()}
                self.logs.log("WARN", "更新检查失败", error=type(exc).__name__)
        with self.lock:
            self.last_update = result
        return dict(result)

    def backups(self):
        workspace = self.manager.workspace
        folder = workspace.root / ".backups"
        if not folder.exists():
            return []
        if is_link_or_reparse(folder):
            raise SecurityError("备份目录不得为链接。")
        found = []
        # Runtime directory enumeration; no links are followed.
        for directory, dirs, files in os.walk(folder, followlinks=False):
            dirs[:] = [name for name in dirs if not is_link_or_reparse(Path(directory)/name)][:200]
            for name in files[:1000]:
                target = Path(directory)/name
                if is_link_or_reparse(target) or not target.is_file():
                    continue
                relative = target.relative_to(workspace.root).as_posix()
                match = re.fullmatch(r"(.+)\.(\d{12,20})\.bak", target.relative_to(folder).as_posix())
                if not match:
                    continue
                info = target.stat()
                found.append({"id":relative,"path":match.group(1),"bytes":info.st_size,"created_at":int(match.group(2))/1000000})
                if len(found) >= 1000:
                    break
            if len(found) >= 1000:
                break
        return sorted(found,key=lambda x:x["created_at"],reverse=True)

    def restore_backup(self, backup_id: str, path: str | None = None):
        if not isinstance(backup_id, str):
            raise ValueError("备份ID无效。")
        match = next((row for row in self.backups() if row["id"] == backup_id), None)
        if not match or (path is not None and path != match["path"]):
            raise SecurityError("备份不存在或目标路径与原始文件不符。")
        result = self.manager.workspace.restore_backup(backup_id, match["path"])
        self.logs.log("INFO", "工作区文件恢复完成", bytes=result["bytes"])
        return {"ok":True,"path":match["path"],**result}

    def export_config(self):
        settings = self.manager.settings.snapshot()
        allowed = {key:value for key,value in settings.items() if not _SECRET.search(key) and key not in {"disclaimer_accepted","full_access","full_access_confirmed","enabled_tools","cloud_consent"}}
        result = {"format":"android-agent-config","version":1,"application_version":__version__,"settings":allowed,"exported_at":time.time(),"note":"不含密钥、令牌、凭据引用、完全权限开关或数据发送授权。"}
        models = getattr(self.manager, "models", None)
        if models is not None:
            from .models import PROFILE_FIELDS
            metadata = models.export_metadata()
            result["version"] = 2
            result["model_profiles"] = [{key: value for key, value in profile.items() if key in PROFILE_FIELDS - {"id"}} for profile in metadata["profiles"]]
        return result

    def import_config(self, data):
        if not isinstance(data,dict) or data.get("format") != "android-agent-config" or data.get("version") not in {1, 2} or not isinstance(data.get("settings"),dict):
            raise ValueError("配置文件格式或版本不支持。")
        current = self.manager.settings.snapshot()
        values = {key:value for key,value in data["settings"].items() if key in current and not _SECRET.search(key) and key not in {"disclaimer_accepted","full_access","full_access_confirmed","enabled_tools","cloud_consent","background_locks"}}
        values.update({"model_enabled": False, "cloud_consent": False})
        if data.get("version") == 2:
            from .models import ModelProfile, PROFILE_FIELDS
            from .config import validate_settings
            models = getattr(self.manager, "models", None)
            if models is None or not isinstance(data.get("model_profiles"), list):
                raise ValueError("模型配置导入格式无效。")
            current_models = models.export_metadata()
            imported = []
            for item in data["model_profiles"]:
                if not isinstance(item, dict):
                    raise ValueError("模型条目格式无效。")
                profile = {key: value for key, value in item.items() if key in PROFILE_FIELDS - {"id"}}
                profile["id"] = "import-" + secrets.token_hex(12)
                ModelProfile.parse(profile, allow_empty_model=True)
                imported.append(profile)
            values.update({"model_enabled": False, "cloud_consent": False})
            validate_settings(values)
            models.replace_all({"profiles": current_models["profiles"] + imported, "active_model_id": current_models["active_model_id"] or (imported[0]["id"] if imported else None)}, allow_empty_model=True)
        self.manager.settings.update(values)
        sync_ui = getattr(self.manager, "sync_ui_preferences", None)
        if callable(sync_ui):
            sync_ui()
        self.logs.log("INFO", "设置已导入", keys=sorted(values))
        return {"ok":True,"settings":self.manager.settings.snapshot(),"restart_required":False}
