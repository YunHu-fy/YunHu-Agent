"""Loopback browser fixture: real backend/storage/SSE + mock provider/native bridge.

No command is ever executed on the developer machine. Run python -m tests.browser_fixture.
"""
from __future__ import annotations

import json
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from android_agent.android_bridge import AndroidBridge
from android_agent.config import SettingsStore
from android_agent.core import AgentManager
from android_agent.server import AgentHTTPServer, RequestHandler
from android_agent.store import Store


class FixtureBridge(AndroidBridge):
    def __init__(self):
        self.channel = "normal"
        self.commands = {}
        self.installed = False
        self.deploy_started = 0
        self.deploy_attempts = 0
        self.runtime_polls = 0
        self.locks = False

    @property
    def available(self):
        return True

    @property
    def streaming_commands(self):
        return True

    def status(self):
        return {"supported": True, "selected_channel": self.channel,
                **{name: {"available": True, "granted": True} for name in ("normal", "shizuku", "root")}}

    def local_model_status(self):
        return {"ok": True, "supported": True, "installed": False, "installing": False,
                "running": False, "healthy": False, "active_model_id": None, "port": None}

    def local_model_install(self):
        return {"ok": True, "supported": True, "installed": True, "installing": False}

    def configure(self, channel):
        self.channel = channel
        return {"ok": True, "selected_channel": channel}

    def request_shizuku(self):
        return {"ok": True, "message": "fixture permission requested"}

    def command_start(self, request):
        self.commands[request["id"]] = {"request": request, "started": time.monotonic(), "cancelled": False}
        return {"ok": True, "id": request["id"]}

    def command_poll(self, command_id, after=0):
        item = self.commands[command_id]
        slow = "hold-task" in item["request"]["command"]
        elapsed = time.monotonic() - item["started"]
        done = item["cancelled"] or elapsed > (30 if slow else .6)
        chunks = []
        if after < 1:
            chunks.append({"seq": 1, "stream": "stdout", "text": "hello command\n"})
        if after < 2 and elapsed > .2:
            chunks.append({"seq": 2, "stream": "stderr", "text": "fixture warning\n"})
        return {"ok": True, "done": done, "chunks": chunks,
                "result": {"ok": not item["cancelled"], "status": "cancelled" if item["cancelled"] else "succeeded",
                           "stdout": "hello command\n", "stderr": "fixture warning\n", "exit_code": -1 if item["cancelled"] else 0,
                           "duration_ms": int(elapsed*1000)}}

    def cancel_command(self, command_id):
        if command_id in self.commands:
            self.commands[command_id]["cancelled"] = True
        return {"ok": True}

    def runtime_status(self):
        if self.deploy_started:
            self.runtime_polls += 1
            if self.deploy_attempts > 1 and self.runtime_polls == 3:
                raise OSError("fixture transient runtime status failure")
        failed = self.deploy_attempts == 1 and self.runtime_polls >= 3
        progress = min(100, max(1, int((time.monotonic()-self.deploy_started)*45))) if self.deploy_started else 0
        if failed:
            progress = 42
        elif self.deploy_started and progress == 100:
            self.installed = True
        return {"ok": not failed, "supported": True, "installed": self.installed, "installing": bool(self.deploy_started and not self.installed and not failed),
                "progress": progress, "stage": "failed" if failed else "ready" if self.installed else "extracting" if self.deploy_started else "not_installed",
                "error": "fixture native extraction failed" if failed else None,
                "version": "0.118.3", "prefix": "/data/data/com.termux/files/usr", "terminal_available": self.installed,
                "background_locks": self.locks}

    def runtime_deploy(self):
        self.installed = False
        self.deploy_attempts += 1
        self.runtime_polls = 0
        self.deploy_started = time.monotonic()
        return self.runtime_status()

    def open_terminal(self):
        return {"ok": self.installed}

    def diagnostics(self):
        return {"ok": True, "summary": "fixture diagnostics", "background_locks": self.locks}

    def device_state(self):
        return {"ok": True, "battery": {"level": 87}, "platform": "browser_fixture", "background_locks": self.locks}

    def service_control(self, action):
        if action == "locks_on":
            self.locks = True
        elif action == "locks_off":
            self.locks = False
        return {"ok": True, "action": action, "background_locks": self.locks}


class MockProvider(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        messages = body.get("messages", [])
        last_user = max((i for i, item in enumerate(messages) if item.get("role") == "user"), default=0)
        content = messages[last_user].get("content", "") if messages else ""
        prompt = "\n".join(item.get("text", "") for item in content if item.get("type") == "text") if isinstance(content, list) else str(content)
        tool_done = any(item.get("role") == "tool" for item in messages[last_user+1:])
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def emit(delta):
            self.wfile.write(("data: " + json.dumps({"choices": [{"delta": delta}]}, ensure_ascii=False) + "\n\n").encode())
            self.wfile.flush()

        try:
            if body.get("tools") and not tool_done:
                command = "printf 'hold-task'" if "等待" in prompt or "hold" in prompt else "printf 'blocked-fixture'" if "黑名单" in prompt else "printf 'hello command'; printf 'fixture warning' >&2"
                emit({"tool_calls": [{"index": 0, "id": "fixture_call", "function": {"name": "shell_execute", "arguments": json.dumps({"command": command, "runtime": "system", "channel": "normal", "cwd": "/data/user/0/com.termux/files", "environment": {"FIXTURE": "1"}, "timeout_seconds": 60})}}]})
            else:
                fence = chr(96)*3
                emit({"content": "## 执行结果\n\n已完成 **设备检查**，输出如下。\n\n"})
                time.sleep(.15)
                emit({"content": fence + "sh\nprintf 'hello command'\n" + fence + "\n\n- 命令已处理\n- 结果可在上方查看\n\n<script>window.__xss=1</script>\n[危险链接](javascript:alert(1))"})
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def configure_fixture_models(server, base_url):
    """Seed profiles through the same redacted API contract the browser uses."""
    profiles = [
        {"id": "fixture-standard", "base_url": base_url, "model": "fixture-model",
         "api_key": "fixture-key", "context_window": 128000, "max_output_tokens": 4096,
         "reasoning_enabled": True, "reasoning_level": "medium", "supports_images": False},
        {"id": "fixture-vision", "base_url": base_url, "model": "fixture-vision-model",
         "api_key": "fixture-key", "context_window": 64000, "max_output_tokens": 2048,
         "reasoning_enabled": True, "reasoning_level": "low", "supports_images": True},
    ]
    request = urllib.request.Request(
        "http://127.0.0.1:" + str(server.server_address[1]) + "/api/models",
        data=json.dumps({"profiles": profiles, "active_model_id": "fixture-standard"}).encode(),
        headers={"Authorization": "Bearer browser-fixture-only", "Content-Type": "application/json"},
        method="PUT",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.load(response)
        assert len(result["profiles"]) == 2
        assert all(item["has_api_key"] and "api_key" not in item for item in result["profiles"])
        print("Fixture ready: http://127.0.0.1:" + str(server.server_address[1]) + "/", flush=True)
    except Exception as error:
        print("Fixture model contract setup failed: " + str(error), flush=True)
        server.shutdown()


def main():
    with tempfile.TemporaryDirectory(prefix="agent-browser-") as temporary:
        root = Path(temporary)
        model = ThreadingHTTPServer(("127.0.0.1", 0), MockProvider)
        model.daemon_threads = True
        threading.Thread(target=model.serve_forever, daemon=True).start()
        settings = SettingsStore(root / "data/settings.json")
        settings.update({"model_base_url": "http://127.0.0.1:"+str(model.server_address[1])+"/v1", "model_name": "fixture-model", "model_enabled": True, "cloud_consent": True})
        manager = AgentManager(root, settings, Store(root / "data/agent.sqlite3"), "browser-fixture-only", android=FixtureBridge())
        manager.workspace.write("sample.txt", "old content")
        manager.workspace.write("sample.txt", "new content")
        server = AgentHTTPServer(8697, manager)
        # Browser tests intentionally make hundreds of localhost requests; keep the
        # production limiter unchanged while raising only the isolated fixture cap.
        import android_agent.server as server_module
        server_module.MAX_REQUESTS_PER_MIN = 5000
        with RequestHandler._rate_lock:
            RequestHandler._rate.clear()
        threading.Thread(target=configure_fixture_models, args=(server, "http://127.0.0.1:" + str(model.server_address[1]) + "/v1"), daemon=True).start()
        try:
            server.serve_forever(poll_interval=.2)
        except KeyboardInterrupt:
            pass
        finally:
            manager.shutdown()
            server.server_close()
            model.shutdown()
            model.server_close()
            manager.executor.shutdown(wait=True, cancel_futures=True)


if __name__ == "__main__":
    main()
