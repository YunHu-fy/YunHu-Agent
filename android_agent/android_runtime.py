"""Lifecycle entry points for the Chaquopy foreground service."""
from __future__ import annotations

import threading
from pathlib import Path

from .config import SettingsStore
from .core import AgentManager
from .security import create_runtime_token
from .server import AgentHTTPServer
from .store import Store

_lock = threading.RLock()
_server: AgentHTTPServer | None = None
_thread: threading.Thread | None = None
_url = ""


def start(files_dir: str, port: int = 8686) -> str:
    """Bind loopback synchronously, start serving in a thread, return private launch URL."""
    global _server, _thread, _url
    with _lock:
        if _server is not None:
            return _url
        root = Path(files_dir) / "agent"
        root.mkdir(parents=True, exist_ok=True)
        data = root / "data"
        token = create_runtime_token(data)
        settings = SettingsStore(data / "settings.json")
        manager = AgentManager(root, settings, Store(data / "agent.sqlite3"), token)
        server = None
        try:
            server = AgentHTTPServer(int(port), manager)
            from .server import WEB_ROOT
            for resource in ("index.html", "static/app.css", "static/app.js", "static/markdown.js"):
                if not (WEB_ROOT / resource).is_file() or (WEB_ROOT / resource).stat().st_size == 0:
                    raise RuntimeError("内嵌网页资源缺失或为空：" + resource)
            _url = "http://127.0.0.1:" + str(server.server_address[1]) + "/#token=" + token
            _server = server
            _thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True, name="agent-http")
            _thread.start()
            return _url
        except BaseException:
            if server is not None:
                server.server_close()
            manager.shutdown()
            _server = None
            _url = ""
            raise


def launch_url() -> str:
    with _lock:
        if _server is None:
            raise RuntimeError("本地服务尚未启动。")
        return _url


def stop() -> None:
    global _server, _thread, _url
    with _lock:
        server = _server
        thread = _thread
        _server = None
        _thread = None
        _url = ""
    if server is not None:
        server.manager.shutdown()
        server.shutdown()
        server.server_close()
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=3)
