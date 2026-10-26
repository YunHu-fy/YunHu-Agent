from __future__ import annotations

import http.client
import json
import os
import re
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from android_agent.config import SettingsStore
from android_agent.core import AgentManager
from android_agent.security import SecurityError, Workspace, create_runtime_token, valid_bearer
from android_agent.server import AgentHTTPServer, RequestHandler
from android_agent.store import Store, TERMINAL
from android_agent.tools import audit_arguments, validate


class SilentHandler(RequestHandler):
    def log_message(self, *args):
        pass


class ModelHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(body)
        names = [tool["function"]["name"] for tool in body.get("tools", [])]
        if any(not re.fullmatch(r"[a-zA-Z0-9_-]+", name) for name in names):
            self.send_error(400)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        def emit(delta):
            try:
                self.wfile.write(("data: " + json.dumps({"choices": [{"delta": delta}]}, ensure_ascii=False) + "\n\n").encode())
                self.wfile.flush()
            except OSError:
                return

        mode = self.server.mode
        if mode == "tool" and not any(message["role"] == "tool" for message in body["messages"]):
            emit({"tool_calls": [{"index": 0, "id": "call_001", "function": {"name": "workspace_read", "arguments": '{"path":"sample.txt"}'}}]})
        elif mode == "two_tools" and sum(message["role"] == "tool" for message in body["messages"]) < 2:
            index = sum(message["role"] == "tool" for message in body["messages"])
            tool = "workspace_list" if index == 0 else "workspace_read"
            args = "{}" if index == 0 else '{"path":"sample.txt"}'
            emit({"tool_calls": [{"index": 0, "id": "call_" + str(index), "function": {"name": tool, "arguments": args}}]})
        else:
            emit({"content": "第一段"})
            self.server.started.set()
            if mode in {"stream", "idle"}:
                self.server.release.wait(5)
            emit({"content": "，第二段。"})
        try:
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except OSError:
            pass


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(0.02)
    raise AssertionError("condition did not become true before timeout")


class AgentIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agent-test-")
        self.root = Path(self.temp.name)
        self.settings = SettingsStore(self.root / "data" / "settings.json")
        self.store = Store(self.root / "data" / "agent.sqlite3")
        self.manager = AgentManager(self.root, self.settings, self.store, "test-token-123")
        self.manager.workspace.write("sample.txt", "hello tool")
        self.server = AgentHTTPServer(0, self.manager)
        self.server.RequestHandlerClass = SilentHandler
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.model = ThreadingHTTPServer(("127.0.0.1", 0), ModelHandler)
        self.model.daemon_threads = True
        self.model.mode = "plain"
        self.model.started = threading.Event()
        self.model.release = threading.Event()
        self.model.requests = []
        self.model_thread = threading.Thread(target=self.model.serve_forever, daemon=True)
        self.model_thread.start()

    def tearDown(self):
        self.model.release.set()
        self.manager.shutdown()
        self.manager.executor.shutdown(wait=True, cancel_futures=True)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.model.shutdown()
        self.model.server_close()
        self.model_thread.join(2)
        self.temp.cleanup()

    def request(self, method, path, body=None, auth=True, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        values = {"Authorization": "Bearer test-token-123"} if auth else {}
        if body is not None:
            values["Content-Type"] = "application/json"
        values.update(headers or {})
        data = json.dumps(body).encode() if body is not None else None
        conn.request(method, path, body=data, headers=values)
        response = conn.getresponse()
        payload = response.read()
        status = response.status
        conn.close()
        try:
            return status, json.loads(payload)
        except ValueError:
            return status, payload.decode("utf-8", errors="replace")

    def enable_model(self, mode="plain"):
        self.model.mode = mode
        self.settings.update({"disclaimer_accepted": True, "model_enabled": True, "cloud_consent": True, "model_name": "fixture-model", "model_base_url": "http://127.0.0.1:" + str(self.model.server_address[1]) + "/v1"})
        self.manager.api_key = "fixture-key"

    def await_done(self, task):
        self.assertTrue(task.done.wait(5), task.snapshot())
        return self.store.get_task(task.id)

    def test_index_is_public_but_contains_no_token(self):
        status, page = self.request("GET", "/", auth=False)
        self.assertEqual(status, 200)
        self.assertIn('content=""', page)
        self.assertNotIn(self.manager.api_token, page)
        status, _ = self.request("GET", "/api/bootstrap", auth=False)
        self.assertEqual(status, 401)

    def test_auth_host_origin_and_content_type(self):
        self.assertEqual(self.request("GET", "/api/status", auth=False)[0], 401)
        self.assertEqual(self.request("GET", "/api/status", headers={"Authorization": "Bearer wrong"})[0], 401)
        self.assertEqual(self.request("GET", "/api/status", headers={"Origin": "http://evil.invalid"})[0], 403)
        self.assertEqual(self.request("GET", "/api/status", headers={"Host": "evil.invalid"})[0], 421)
        self.assertEqual(self.request("POST", "/api/tasks", {}, headers={"Content-Type": "text/plain"})[0], 400)
        self.assertEqual(self.request("GET", "/api/status")[0], 200)
        self.assertEqual(self.request("GET", "/api/health/live", auth=False), (200, {"status": "alive"}))

    def test_disclaimer_required_and_acceptance(self):
        self.assertEqual(self.request("POST", "/api/tasks", {"message": "hello"})[0], 428)
        self.assertEqual(self.request("POST", "/api/disclaimer", {"accepted": True})[0], 200)
        status, result = self.request("POST", "/api/tasks", {"message": "hello"})
        self.assertEqual(status, 202)
        task = self.manager.get_task(result["task"]["id"])
        self.assertEqual(self.await_done(task)["state"], "succeeded")

    def test_sse_completes_and_replays_by_id(self):
        self.settings.update({"disclaimer_accepted": True})
        task = self.manager.create_chat("hello", [])
        self.await_done(task)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        conn.request("GET", "/api/tasks/" + task.id + "/events", headers={"Authorization": "Bearer test-token-123"})
        response = conn.getresponse()
        stream = response.read().decode()
        self.assertIn("event: task_completed\n", stream)
        ids = [int(item) for item in re.findall(r"^id: (\d+)$", stream, re.M)]
        self.assertEqual(ids, sorted(set(ids)))
        conn.close()
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=2)
        conn.request("GET", "/api/tasks/" + task.id + "/events", headers={"Authorization": "Bearer test-token-123", "Last-Event-ID": str(ids[-1])})
        response = conn.getresponse()
        self.assertEqual(response.read(), b"")
        conn.close()

    def test_model_streams_before_completion_with_legal_tool_names(self):
        self.enable_model("stream")
        task = self.manager.create_chat("hello", [])
        self.assertTrue(self.model.started.wait(3))
        wait_until(lambda: bool(self.store.get_task(task.id)["assistant_text"]))
        self.assertFalse(task.done.is_set())
        self.assertEqual(self.store.get_task(task.id)["assistant_text"], "第一段")
        self.model.release.set()
        row = self.await_done(task)
        self.assertEqual(row["state"], "succeeded", row)
        self.assertEqual(row["assistant_text"], "第一段，第二段。")
        for tool in self.model.requests[0]["tools"]:
            self.assertRegex(tool["function"]["name"], r"^[a-zA-Z0-9_-]+$")
        deltas = [event for event in self.store.events_after(task.id, 0) if event["event"] == "assistant_delta"]
        self.assertEqual(len(deltas), 2)

    def test_model_tool_approval_then_result_roundtrip(self):
        self.enable_model("tool")
        task = self.manager.create_chat("read sample", [])
        request = wait_until(lambda: task.snapshot()["pending_approval"])
        self.assertEqual(request["tool"], "workspace.read")
        self.assertFalse(self.manager.decide(task.id, "stale", True))
        self.assertTrue(self.manager.decide(task.id, request["approval_id"], True))
        self.assertEqual(self.await_done(task)["state"], "succeeded")
        messages = self.model.requests[-1]["messages"]
        tool_result = next(item for item in messages if item["role"] == "tool")
        self.assertIn("hello tool", tool_result["content"])
        audit = self.store.list_audit()
        self.assertTrue(any(row["decision"] == "approved" for row in audit))
        self.assertNotIn("hello tool", json.dumps(audit))

    def test_stale_approval_cannot_authorize_next_tool(self):
        self.enable_model("two_tools")
        task = self.manager.create_chat("two tools", [])
        first = wait_until(lambda: task.snapshot()["pending_approval"])
        self.manager.decide(task.id, first["approval_id"], True)
        def next_approval():
            request = task.snapshot()["pending_approval"]
            return request if request and request["approval_id"] != first["approval_id"] else None
        second = wait_until(next_approval)
        self.assertFalse(self.manager.decide(task.id, first["approval_id"], True))
        self.assertEqual(task.snapshot()["pending_approval"]["approval_id"], second["approval_id"])
        self.manager.decide(task.id, second["approval_id"], False)
        self.assertEqual(self.await_done(task)["state"], "succeeded")

    def test_cancel_waiting_approval_clears_pending_and_never_completes(self):
        task = self.manager.create_tool_task("workspace.read", {"path": "sample.txt"})
        wait_until(lambda: task.snapshot()["pending_approval"])
        self.assertTrue(self.manager.cancel(task.id))
        self.assertEqual(self.await_done(task)["state"], "cancelled")
        self.assertEqual(self.manager.approvals(), [])
        events = [item["event"] for item in self.store.events_after(task.id, 0)]
        self.assertEqual(events.count("task_cancelled"), 1)
        self.assertNotIn("task_completed", events)
        self.assertNotIn("tool_result", events)

    def test_cancel_idle_model_closes_network(self):
        self.enable_model("idle")
        task = self.manager.create_chat("hello", [])
        self.assertTrue(self.model.started.wait(3))
        wait_until(lambda: bool(task.snapshot()["assistant_text"]))
        start = time.monotonic()
        self.assertTrue(self.manager.cancel(task.id))
        row = self.await_done(task)
        self.assertLess(time.monotonic() - start, 2)
        self.assertEqual(row["state"], "cancelled")
        events = [item["event"] for item in self.store.events_after(task.id, 0)]
        self.assertEqual(events.count("task_cancelled"), 1)
        self.assertNotIn("task_completed", events)

    def test_mcp_discovery_and_safe_tool(self):
        for method, key in (("initialize", "serverInfo"), ("tools/list", "tools"), ("resources/list", "resources"), ("prompts/list", "prompts")):
            status, body = self.request("POST", "/mcp", {"jsonrpc":"2.0", "id":1, "method":method, "params":{}})
            self.assertEqual(status, 200)
            self.assertIn(key, body["result"])
        status, body = self.request("POST", "/mcp", {"jsonrpc":"2.0", "id":2, "method":"tools/call", "params":{"name":"device.info", "arguments":{}}})
        self.assertEqual(status, 200)
        self.assertFalse(body["result"]["isError"])
        self.assertIn('"permission_channel": "normal"', body["result"]["content"][0]["text"])
        _, body = self.request("POST", "/mcp", {"jsonrpc":"2.0", "id":3, "method":"unknown"})
        self.assertEqual(body["error"]["code"], -32601)

    def test_api_key_never_persisted_or_returned(self):
        status, body = self.request("POST", "/api/settings", {"model_base_url":"https://example.com/v1", "model_name":"test", "api_key":"sensitive-fixture", "cloud_consent":True, "model_enabled":True})
        self.assertEqual(status, 200)
        self.assertNotIn("sensitive-fixture", json.dumps(body))
        self.assertNotIn("sensitive-fixture", self.settings.path.read_text())
        self.assertEqual(self.manager.api_key, "sensitive-fixture")

    def test_local_model_supports_no_api_key(self):
        self.enable_model()
        self.manager.api_key = ""
        task = self.manager.create_chat("hello local model", [])
        row = self.await_done(task)
        self.assertEqual(row["state"], "succeeded", row)
        self.assertEqual(row["assistant_text"], "第一段，第二段。")

    def test_mcp_stdio_transport(self):
        import subprocess
        import sys
        token_file = self.root / "stdio.token"
        token_file.write_text(self.manager.api_token, encoding="ascii")
        messages = [
            {"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"fixture","version":"1"}}},
            {"jsonrpc":"2.0","method":"notifications/initialized"},
            {"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"device.info","arguments":{}}},
        ]
        completed = subprocess.run([sys.executable,"-m","android_agent.mcp_stdio","--url","http://127.0.0.1:"+str(self.port)+"/mcp","--token-file",str(token_file)], input="".join(json.dumps(item)+"\n" for item in messages), text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        self.assertEqual(completed.returncode,0,completed.stderr)
        output = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual([item["id"] for item in output],[1,2])
        self.assertIn("serverInfo",output[0]["result"])
        self.assertFalse(output[1]["result"]["isError"])

    def test_write_always_available_but_review_requires_exact_approval(self):
        status, body = self.request("POST", "/api/mcp/tools/call", {"name":"workspace.write", "arguments":{"path":"out.txt", "content":"secret-text"}})
        self.assertEqual(status, 202)
        self.assertIn(self.request("POST", "/api/tools/toggle", {"name":"workspace.write", "enabled":False})[0], {404,410})
        task = self.manager.get_task(body["task"]["id"])
        approval = wait_until(lambda: task.snapshot()["pending_approval"])
        self.assertFalse((self.manager.workspace.root / "out.txt").exists())
        self.assertEqual(self.request("POST", "/api/tasks/" + task.id + "/decision", {"approval_id":"wrong", "approved":True})[0], 409)
        self.assertEqual(self.request("POST", "/api/tasks/" + task.id + "/decision", {"approval_id":approval["approval_id"], "approved":True})[0], 200)
        self.assertEqual(self.await_done(task)["state"], "succeeded")
        self.assertEqual(self.manager.workspace.read("out.txt"), "secret-text")
        self.assertNotIn("secret-text", json.dumps(self.store.list_audit()))


class WorkspaceAndStoreTests(unittest.TestCase):
    def test_paths_and_nested_backups(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(Path(temp) / "workspace")
            for bad in ("../x", "/etc/passwd", "C:/Windows/test", "//server/share", "x/../y", "x//y", "NUL.txt", "a:", "a" + chr(92) + "b", "x" + chr(0)):
                with self.subTest(path=bad), self.assertRaises(SecurityError):
                    workspace.read(bad)
            workspace.write("nested/sub/file.txt", "one")
            result = workspace.write("nested/sub/file.txt", "two")
            self.assertEqual(workspace.read("nested/sub/file.txt"), "two")
            self.assertEqual(workspace.read(result["backup"]), "one")
            self.assertIn("nested", [entry["name"] for entry in workspace.list()])
            with self.assertRaises(SecurityError):
                workspace.write("too-large.txt", "x" * 262145)
            with self.assertRaises(SecurityError):
                workspace.read("too-large.txt")

    def test_link_escape_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = Workspace(root / "workspace")
            outside = root / "secret.txt"
            outside.write_text("secret")
            try:
                (workspace.root / "link.txt").symlink_to(outside)
            except OSError:
                self.skipTest("symlink privilege unavailable on host")
            if not (workspace.root / "link.txt").is_symlink():
                self.skipTest("host filesystem did not create a real symlink")
            with self.assertRaises((SecurityError, OSError)):
                workspace.read("link.txt")
            with self.assertRaises((SecurityError, OSError)):
                workspace.write("link.txt", "overwritten")
            self.assertEqual(outside.read_text(), "secret")

    def test_restart_recovery_monotonic_replay_and_connection_release(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "agent.sqlite3"
            store = Store(path)
            task = {"id":"a" * 32,"message":"test","origin":"test","state":"running","created_at":time.time(),"updated_at":time.time()}
            store.create_task(task)
            for i in range(10):
                self.assertEqual(store.append_event(task["id"], time.time(), "chunk", {"i":i}, keep=5), i+1)
            self.assertEqual(store.event_bounds(task["id"]), (6, 10))
            self.assertEqual([row["id"] for row in store.events_after(task["id"], 8)], [9, 10])
            restarted = Store(path)
            self.assertEqual(restarted.get_task(task["id"])["state"], "failed")
            self.assertTrue(restarted.sqlite_ready())
            renamed = path.with_name("renamed.sqlite3")
            path.rename(renamed)
            renamed.unlink()

    def test_token_rotation_and_strict_auth(self):
        with tempfile.TemporaryDirectory() as temp:
            first = create_runtime_token(Path(temp))
            second = create_runtime_token(Path(temp))
            self.assertNotEqual(first, second)
            self.assertTrue(valid_bearer("Bearer " + second, second))
            for bad in ("", "bearer " + second, "Bearer  " + second, "Bearer " + first, "Bearer " + second + " trailing"):
                self.assertFalse(valid_bearer(bad, second))

    def test_tool_schema_and_write_audit_redaction(self):
        with self.assertRaises(ValueError):
            validate("device.info", {"shell":"rm -rf /"}, {"device.info"})
        with self.assertRaises(ValueError):
            validate("system.run", {"command":"anything"}, {"system.status"})
        result = audit_arguments("workspace.write", {"path":"out.txt","content":"not-for-audit"})
        self.assertNotIn("not-for-audit", json.dumps(result))
        self.assertEqual(len(result["sha256"]), 64)


if __name__ == "__main__":
    unittest.main(verbosity=2)
