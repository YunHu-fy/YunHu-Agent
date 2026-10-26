"""Pinned GGUF catalog, downloads, and bounded local inference settings.

When `anima_low_memory_enabled` is on, the requested context is conservatively
capped at 2048 tokens using the already-supported ctx-size parameter; no native
runtime flags are added."""
from __future__ import annotations

import hashlib
import os
import shutil
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

REV_05 = "9217f5db79a29953eb74d5343926648285ec7e67"
REV_15 = "91cad51170dc346986eccefdc2dd33a9da36ead9"
_REPOS = {"0.5B": ("Qwen/Qwen2.5-0.5B-Instruct-GGUF", REV_05), "1.5B": ("Qwen/Qwen2.5-1.5B-Instruct-GGUF", REV_15)}
_FILES = [
    ("qwen25-05-q2", "0.5B", "qwen2.5-0.5b-instruct-q2_k.gguf", 415182688, "9ee36184e616dfc76df4f5dd66f908dbde6979524ae36e6cefb67f532f798cb8", "Qwen2.5 0.5B · Q2_K", "低存储 · 质量较低"),
    ("qwen25-05-q3km", "0.5B", "qwen2.5-0.5b-instruct-q3_k_m.gguf", 432041824, "590d2479d401db206fe12a4562294d2de6211e06338a6e34fbad64b32f1469d0", "Qwen2.5 0.5B · Q3_K_M", "轻量均衡"),
    ("qwen25-05-q40", "0.5B", "qwen2.5-0.5b-instruct-q4_0.gguf", 428730208, "7671c0c304e6ce5a7fc577bcb12aba01e2c155cc2efd29b2213c95b18edaf6ed", "Qwen2.5 0.5B · Q4_0", "轻量均衡"),
    ("qwen25-05-q4km", "0.5B", "qwen2.5-0.5b-instruct-q4_k_m.gguf", 491400032, "74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db", "Qwen2.5 0.5B · Q4_K_M", "推荐入门"),
    ("qwen25-05-q50", "0.5B", "qwen2.5-0.5b-instruct-q5_0.gguf", 490475360, "925946ab27801fea3eead42933f857b6449c6d299f062e374cee2ac48426f2a5", "Qwen2.5 0.5B · Q5_0", "较高质量"),
    ("qwen25-05-q5km", "0.5B", "qwen2.5-0.5b-instruct-q5_k_m.gguf", 522186592, "041474553fcabfc2a2d67903f9d2c2e50bd92528e670da4f33b5d0ce6e59fd55", "Qwen2.5 0.5B · Q5_K_M", "较高质量"),
    ("qwen25-15-q2", "1.5B", "qwen2.5-1.5b-instruct-q2_k.gguf", 752880160, "5ede348e91ce1e7a330926ec5b202c27b864d065149dc463257fde1f98865b3a", "Qwen2.5 1.5B · Q2_K", "低存储 · 质量较低"),
    ("qwen25-15-q3km", "1.5B", "qwen2.5-1.5b-instruct-q3_k_m.gguf", 924455968, "58cb5c05ecef48e82961f1a2be6544145ea26136f69dddda4bbbd092f0e4b993", "Qwen2.5 1.5B · Q3_K_M", "中等存储"),
    ("qwen25-15-q40", "1.5B", "qwen2.5-1.5b-instruct-q4_0.gguf", 1066227232, "dcd819ff094852c38faba6873d8ff0c9d51eadb2844539e52042ae5d647bbfdb", "Qwen2.5 1.5B · Q4_0", "中等存储"),
    ("qwen25-15-q4km", "1.5B", "qwen2.5-1.5b-instruct-q4_k_m.gguf", 1117320736, "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e", "Qwen2.5 1.5B · Q4_K_M", "较佳均衡"),
]
CATALOG: dict[str, dict[str, Any]] = {}
for model_id, tier, filename, size, digest, name, note in _FILES:
    repo, revision = _REPOS[tier]
    CATALOG[model_id] = {"id": model_id, "name": name, "note": note, "repo": repo, "revision": revision,
        "filename": filename, "bytes": size, "sha256": digest, "license": "Apache-2.0 (仓库元数据)",
        "context_window": 4096, "tool_support": False, "supports_images": False}

class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not _allowed_host(host) or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError("模型源重定向到未获允许的 HTTPS 主机，下载已拒绝。")
        return super().redirect_request(req, fp, code, msg, headers, newurl)

LOW_MEMORY_CONTEXT_LIMIT = 2048


def effective_context_size(context_size: Any, low_memory: Any = False) -> int:
    """Validate configured ctx-size and apply the documented low-memory cap.

    The cap uses only llama-server's existing --ctx-size argument; no native
    memory flags are assumed or introduced.
    """
    if type(context_size) is not int or not 512 <= context_size <= 8192:
        raise ValueError("上下文长度必须为512..8192。")
    if type(low_memory) is not bool:
        raise ValueError("低内存模式必须是布尔值。")
    return min(context_size, LOW_MEMORY_CONTEXT_LIMIT) if low_memory else context_size


class LocalModelManager:
    def __init__(self, directory: Path, android: Any):
        self.root = directory.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.android = android
        self._lock = threading.RLock()
        self._downloads: dict[str, dict[str, Any]] = {}
        self._cancel: dict[str, threading.Event] = {}
        self._engine_install_requested = False
        self._engine_state: dict[str, Any] = {"installed": False, "installing": False, "active_model_id": None, "running": False}

    @staticmethod
    def catalog() -> list[dict[str, Any]]:
        return [{**item, "size_label": _size(item["bytes"]),
                 "sources": {"mirror": f"https://hf-mirror.com/{item['repo']}/resolve/{item['revision']}/{item['filename']}?download=true",
                             "original": f"https://huggingface.co/{item['repo']}/resolve/{item['revision']}/{item['filename']}?download=true"}}
                for item in CATALOG.values()]

    def _file(self, model_id: str) -> Path:
        if model_id not in CATALOG:
            raise ValueError("模型目录项不存在。")
        target = self.root / (model_id + ".gguf")
        if target.parent != self.root:
            raise ValueError("模型路径超出私有目录。")
        return target

    def list(self) -> dict[str, Any]:
        models = []
        for item in CATALOG.values():
            path = self._file(item["id"])
            if path.is_symlink():
                raise RuntimeError("模型文件路径异常；请删除并重新下载。")
            ready = path.is_file() and path.stat().st_size == item["bytes"]
            models.append({"id": item["id"], "downloaded": ready, "bytes": path.stat().st_size if path.is_file() else 0,
                           "expected_bytes": item["bytes"]})
        with self._lock:
            jobs = [self._public_job(value) for value in self._downloads.values()]
        native = self.android.local_model_status() if hasattr(self.android, "local_model_status") else {"supported": False, "installed": False, "running": False}
        runtime = self.android.runtime_status() if hasattr(self.android, "runtime_status") else {"supported": False, "installed": False}
        with self._lock:
            install_requested = self._engine_install_requested
            runtime_failed = install_requested and runtime.get("stage") == "failed"
            native_failed = install_requested and native.get("install_state") == "failed" and not native.get("installing")
            if install_requested and runtime.get("installed") and not native.get("installed") and not native.get("installing") and not native_failed:
                native = self.android.local_model_install() if hasattr(self.android, "local_model_install") else native
                if native.get("ok") is False:
                    native = {**native, "install_error": native.get("error"), "installing": False, "install_state": "failed"}
                    native_failed = True
            if install_requested and (native.get("installed") or runtime_failed or native_failed):
                self._engine_install_requested = False
            installing = bool(native.get("installing") or (self._engine_install_requested and runtime.get("installing")))
            self._engine_state = {**self._engine_state, **native, "runtime_installed": bool(runtime.get("installed")),
                                 "runtime_installing": bool(self._engine_install_requested and runtime.get("installing")),
                                 "installing": installing,
                                 "progress": native.get("progress", runtime.get("progress") if installing else 0)}
            if runtime_failed:
                self._engine_state["install_error"] = runtime.get("error")
            elif native_failed:
                self._engine_state["install_error"] = native.get("install_error") or native.get("error") or "Local inference engine installation failed"
        return {"models": models, "jobs": jobs, "engine": dict(self._engine_state), "storage_bytes": shutil.disk_usage(self.root).free}

    @staticmethod
    def _public_job(job: dict[str, Any]) -> dict[str, Any]:
        return {key: job.get(key) for key in ("id", "model_id", "state", "received", "total", "progress", "source", "error", "updated_at")}

    def download(self, model_id: Any, source: Any = "mirror") -> dict[str, Any]:
        if not isinstance(model_id, str) or model_id not in CATALOG:
            raise ValueError("只能下载内置模型目录中的项目。")
        if source not in {"mirror", "original"}:
            raise ValueError("下载源只能选择国内镜像或 Hugging Face 官方源。")
        item = CATALOG[model_id]
        target = self._file(model_id)
        if target.is_symlink() or target.with_suffix(".gguf.part").is_symlink():
            raise RuntimeError("模型下载路径异常；请移除异常路径后重试。")
        if target.is_file() and target.stat().st_size == item["bytes"] and _sha256(target) == item["sha256"]:
            return {"ok": True, "already_downloaded": True, "model_id": model_id}
        free = shutil.disk_usage(self.root).free
        required = item["bytes"] + max(1024**3, item["bytes"] // 4)
        if free < required:
            raise RuntimeError(f"存储空间不足：需要约 {_size(required)}，当前可用 {_size(free)}。")
        with self._lock:
            if any(job["state"] in {"queued", "downloading", "verifying", "cancel_requested"} for job in self._downloads.values()):
                raise RuntimeError("已有模型下载正在进行；请等待完成或取消后再试。")
            job_id = uuid.uuid4().hex
            job = {"id": job_id, "model_id": model_id, "state": "queued", "received": 0, "total": item["bytes"],
                   "progress": 0, "source": source, "error": None, "updated_at": time.time()}
            self._downloads[job_id] = job
            cancel = threading.Event(); self._cancel[job_id] = cancel
        threading.Thread(target=self._download_worker, args=(job_id, target, item, source, cancel), daemon=True, name="gguf-download").start()
        return {"ok": True, "job": self._public_job(job)}

    def _download_worker(self, job_id: str, target: Path, item: dict[str, Any], source: str, cancel: threading.Event) -> None:
        part = target.with_suffix(".gguf.part")
        host = "hf-mirror.com" if source == "mirror" else "huggingface.co"
        url = f"https://{host}/{item['repo']}/resolve/{item['revision']}/{item['filename']}?download=true"
        try:
            if cancel.is_set(): raise InterruptedError("下载已取消；已下载部分保留供续传。")
            if part.is_symlink() or target.is_symlink():
                raise ValueError("模型下载路径异常。")
            offset = part.stat().st_size if part.is_file() else 0
            if offset > item["bytes"]:
                part.unlink(); offset = 0
            headers = {"User-Agent": "Yunhu-Android/1.4 local-model-downloader"}
            if offset: headers["Range"] = f"bytes={offset}-"
            opener = urllib.request.build_opener(_SafeRedirect())
            response = opener.open(urllib.request.Request(url, headers=headers), timeout=30)
            if offset and response.status != 206:
                response.close(); part.unlink(missing_ok=True); offset = 0
                response = opener.open(urllib.request.Request(url, headers={"User-Agent": headers["User-Agent"]}), timeout=30)
            elif offset:
                content_range = response.headers.get("Content-Range", "")
                match = __import__("re").fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range.strip())
                if not match or int(match.group(1)) != offset or int(match.group(2)) >= int(match.group(3)) or int(match.group(3)) != item["bytes"]:
                    response.close(); part.unlink(missing_ok=True); raise ValueError("续传响应的 Content-Range 与目录文件大小不匹配。")
            final_url = urllib.parse.urlsplit(response.geturl())
            if final_url.scheme != "https" or not _allowed_host(final_url.hostname or ""):
                response.close(); raise ValueError("模型源响应地址不可信。")
            with self._lock:
                if cancel.is_set(): raise InterruptedError("下载已取消；已下载部分保留供续传。")
                self._downloads[job_id].update(state="downloading", received=offset, updated_at=time.time())
            received = offset
            flags = os.O_WRONLY | os.O_CREAT | (os.O_APPEND if offset else os.O_TRUNC) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
            fd = os.open(str(part), flags, 0o600)
            with response, os.fdopen(fd, "ab" if offset else "wb") as output:
                while True:
                    if cancel.is_set(): raise InterruptedError("下载已取消；已下载部分保留供续传。")
                    block = response.read(1024 * 1024)
                    if not block: break
                    received += len(block)
                    if received > item["bytes"]: raise ValueError("下载数据超过目录登记的文件大小。")
                    output.write(block)
                    with self._lock: self._downloads[job_id].update(received=received, progress=min(99, received * 100 // item["bytes"]), updated_at=time.time())
                output.flush(); os.fsync(output.fileno())
            if received != item["bytes"]: raise ValueError(f"下载大小不匹配：{received} / {item['bytes']} bytes。")
            with self._lock:
                if cancel.is_set(): raise InterruptedError("下载已取消；已下载部分保留供续传。")
                self._downloads[job_id].update(state="verifying", updated_at=time.time())
            if cancel.is_set(): raise InterruptedError("下载已取消；已下载部分保留供续传。")
            if _sha256(part) != item["sha256"]:
                part.unlink(missing_ok=True); raise ValueError("SHA-256 校验失败，已删除损坏文件。")
            if cancel.is_set(): raise InterruptedError("下载已取消；已下载部分保留供续传。")
            with open(part, "rb") as stream:
                if stream.read(4) != b"GGUF":
                    part.unlink(missing_ok=True); raise ValueError("文件头不是有效 GGUF。")
            # Linearize cancellation and publication: if cancellation wins the lock,
            # the final file is never published; if publication wins, cancel returns false.
            with self._lock:
                if cancel.is_set() or self._downloads[job_id].get("state") == "cancel_requested":
                    raise InterruptedError("下载已取消；已下载部分保留供续传。")
                os.replace(part, target)
                self._downloads[job_id].update(state="completed", received=received, progress=100, updated_at=time.time())
        except InterruptedError:
            with self._lock: self._downloads[job_id].update(state="cancelled", error="下载已取消；可从已下载数据续传。", updated_at=time.time())
        except Exception as exc:
            if cancel.is_set():
                with self._lock: self._downloads[job_id].update(state="cancelled", error="下载已取消；可从已下载数据续传。", updated_at=time.time())
                return
            safe_error = str(exc)[:300] if isinstance(exc, (ValueError, PermissionError)) else "下载失败，请检查网络或切换下载源后重试。"
            with self._lock: self._downloads[job_id].update(state="failed", error=safe_error, updated_at=time.time())

    def cancel_download(self, job_id: Any) -> bool:
        if not isinstance(job_id, str): return False
        with self._lock:
            event, job = self._cancel.get(job_id), self._downloads.get(job_id)
            if not event or not job or job.get("state") not in {"queued", "downloading", "verifying"}: return False
            event.set()
            job.update(state="cancel_requested", updated_at=time.time())
            return True

    def install_engine(self) -> dict[str, Any]:
        runtime = self.android.runtime_status() if hasattr(self.android, "runtime_status") else {"status": "unsupported"}
        if runtime.get("status") != "unsupported" and not runtime.get("installed"):
            if not runtime.get("installing"):
                runtime = self.android.runtime_deploy() if hasattr(self.android, "runtime_deploy") else {"ok": False, "error": {"message": "Android 运行时桥接不可用。"}}
            if runtime.get("ok") is False:
                error = runtime.get("error")
                raise RuntimeError(error.get("message", "Android 运行时安装失败。") if isinstance(error, dict) else str(error or "Android 运行时安装失败。"))
            with self._lock:
                self._engine_install_requested = True
                self._engine_state.update(installed=False, installing=bool(runtime.get("installing")), runtime_installing=bool(runtime.get("installing")), progress=runtime.get("progress", 0))
            return {"ok": True, "installed": False, "installing": bool(runtime.get("installing")),
                    "runtime_installing": bool(runtime.get("installing")), "progress": runtime.get("progress", 0), "stage": runtime.get("stage")}
        result = self.android.local_model_install() if hasattr(self.android, "local_model_install") else {"ok": False, "error": {"message": "本地推理引擎仅能在 Android APK 内安装。"}}
        if result.get("ok") is False:
            error = result.get("error"); raise RuntimeError(error.get("message", "本地推理引擎安装失败。") if isinstance(error, dict) else str(error or "本地推理引擎安装失败。"))
        with self._lock:
            self._engine_install_requested = bool(result.get("installing"))
            self._engine_state.update(result)
        return result

    def profile_is_active(self, profile: Any) -> bool:
        if not getattr(profile, "id", "").startswith("local-"):
            return False
        status = self.android.local_model_status() if hasattr(self.android, "local_model_status") else {}
        return bool(status.get("running") and status.get("healthy") and status.get("active_model_id") == getattr(profile, "model", None)
                    and profile.base_url == f"http://127.0.0.1:{status.get('port')}/v1")

    def activate(self, model_id: Any, port: int = 18286, context_size: int = 4096, threads: int = 4,
                 low_memory: bool = False, backend: dict[str, Any] | None = None) -> dict[str, Any]:
        if not isinstance(model_id, str) or model_id not in CATALOG: raise ValueError("模型目录项不存在。")
        if type(port) is not int or not 18000 <= port <= 18999: raise ValueError("推理端口无效。")
        context_size = effective_context_size(context_size, low_memory)
        if type(threads) is not int or not 1 <= threads <= 16: raise ValueError("线程数必须为1..16。")
        item, path = CATALOG[model_id], self._file(model_id)
        if path.is_symlink() or path.resolve() != path or not path.is_file() or path.stat().st_size != item["bytes"] or _sha256(path) != item["sha256"]:
            raise ValueError("模型尚未完整下载或完整性校验未通过。")
        if not hasattr(self.android, "local_model_start"): raise RuntimeError("Android 本地引擎桥接不可用。")
        current = self.android.local_model_status() if hasattr(self.android, "local_model_status") else {}
        acceleration = {key: bool((backend or {}).get(key, False)) for key in ("cpu", "gpu", "npu")}
        acceleration["low_memory"] = bool(low_memory)
        if current.get("running"):
            if current.get("active_model_id") != model_id or current.get("port") != port:
                raise RuntimeError("已有其他本地模型正在运行，请先停止后再切换。")
            known_context = current.get("context_size", self._engine_state.get("context_size"))
            known_threads = current.get("threads", self._engine_state.get("threads"))
            if known_context != context_size or known_threads != threads:
                raise RuntimeError("正在运行的本地模型配置与请求不匹配或无法确认；请先停止再启动。")
            result = {**current, "ok": True}
        else:
            result = self.android.local_model_start(str(path), model_id, port, context_size, threads,
                                                    {"backend": acceleration})
        if result.get("ok") is False:
            error = result.get("error"); raise RuntimeError(error.get("message", "本地模型启动失败。") if isinstance(error, dict) else str(error or "本地模型启动失败。"))
        # The native layer may bind a neighbouring port when the requested one is still held
        # by a leftover server; advertising the requested port would then point at nothing.
        actual_port = result.get("port") if isinstance(result.get("port"), int) and 18000 <= result["port"] <= 18999 else port
        engine = {**result, "context_size": context_size, "threads": threads, "backend": result.get("backend") or _backend_label(acceleration)}
        self._engine_state.update(engine, active_model_id=model_id, running=True)
        return {"ok": True, "model_id": model_id, "base_url": f"http://127.0.0.1:{actual_port}/v1", "model": model_id,
                "context_size": context_size, "threads": threads, "backend": engine["backend"], "engine": engine,
                "port": actual_port}

    def engine_log(self) -> dict[str, Any]:
        if not hasattr(self.android, "local_model_log"):
            return {"ok": False, "error": {"code": "unsupported", "message": "引擎日志仅能在 Android APK 内读取。"}}
        return self.android.local_model_log()

    def stop(self) -> dict[str, Any]:
        result = self.android.local_model_stop() if hasattr(self.android, "local_model_stop") else {"ok": False, "error": {"message": "本地引擎桥接不可用。"}}
        if result.get("ok") is False:
            error = result.get("error"); raise RuntimeError(error.get("message", "停止本地引擎失败。") if isinstance(error, dict) else str(error or "停止本地引擎失败。"))
        self._engine_state.update(result, running=False, active_model_id=None)
        return result

    def delete(self, model_id: Any) -> dict[str, Any]:
        if not isinstance(model_id, str) or model_id not in CATALOG: raise ValueError("模型目录项不存在。")
        status = self.android.local_model_status() if hasattr(self.android, "local_model_status") else {}
        if status.get("running") and status.get("active_model_id") == model_id: raise RuntimeError("请先停止正在使用的模型。")
        target = self._file(model_id); part = target.with_suffix(".gguf.part")
        with self._lock:
            if any(job.get("model_id") == model_id and job.get("state") in {"queued", "downloading", "verifying", "cancel_requested"} for job in self._downloads.values()):
                raise RuntimeError("模型下载正在进行；请取消或等待下载结束后再删除。")
            if target.is_symlink() or part.is_symlink(): raise RuntimeError("模型文件路径异常；已拒绝删除。")
            part.unlink(missing_ok=True); target.unlink(missing_ok=True)
        return {"ok": True, "model_id": model_id}

def _backend_label(acceleration: dict[str, Any]) -> str:
    labels = ["cpu"]
    if acceleration.get("cpu"):
        labels.append("cpu-accel")
    if acceleration.get("gpu"):
        labels.append("gpu")
    if acceleration.get("npu"):
        labels.append("npu")
    if acceleration.get("low_memory"):
        labels.append("low-memory")
    return "+".join(labels)


def _allowed_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    return host in {"huggingface.co", "hf-mirror.com"} or host.endswith(".xethub.hf.co")

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()

def _size(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]: return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} GiB"
