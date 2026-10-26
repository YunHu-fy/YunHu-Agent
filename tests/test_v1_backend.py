"""v1 backend contracts tested with native JSON mocks only, never a host shell."""
from __future__ import annotations

import http.client
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from android_agent.android_bridge import AndroidBridge
from android_agent.config import SettingsStore
from android_agent.core import AgentManager, TransientModelError
from android_agent.server import AgentHTTPServer, RequestHandler
from android_agent.store import Store
from android_agent.tools import blacklist_match, definitions, validate_command


def wait_for(predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("condition did not become true")


class MockNative:
    def __init__(self):
        self.channel = "normal"
        self.requests = []
        self.cancelled = []
        self.polls = {}
        self.release = threading.Event()
        self.block = False
        self.stdout = "first\nsecond\n"
        self.stderr = "warning\n"
        self.exit_code = 0
        self.granted = True
        self.calls = []
        self.credentials = {}

    def credentialRead(self, profile_id):
        return json.dumps({"ok": True, "value": self.credentials.get(profile_id, "")})

    def credentialWrite(self, profile_id, value):
        self.credentials[profile_id] = value
        return '{"ok":true}'

    def credentialDelete(self, profile_id):
        self.credentials.pop(profile_id, None)
        return '{"ok":true}'

    def status(self):
        return json.dumps({"ok": True, "selected_channel": self.channel, **{channel: {"available": True, "granted": self.granted} for channel in ("normal", "shizuku", "root")}})

    def configureChannel(self, channel):
        self.channel = channel
        return json.dumps({"ok": True, "selected_channel": channel})

    def commandStart(self, raw):
        request = json.loads(raw)
        self.requests.append(request)
        self.polls[request["id"]] = 0
        return json.dumps({"ok": True, "id": request["id"]})

    def commandPoll(self, command_id, after):
        self.polls[command_id] += 1
        chunks = [{"seq": 1, "stream": "stdout", "text": self.stdout}, {"seq": 2, "stream": "stderr", "text": self.stderr}]
        chunks = [chunk for chunk in chunks if chunk["seq"] > after]
        done = not self.block or self.release.is_set() or command_id in self.cancelled
        return json.dumps({"ok": True, "chunks": chunks, "done": done, "result": {"stdout": self.stdout, "stderr": self.stderr, "exit_code": self.exit_code, "status": "succeeded" if self.exit_code == 0 else "failed", "truncated": False, "duration_ms": 25} if done else None})

    def commandCancel(self, command_id):
        self.cancelled.append(command_id)
        return '{"ok":true}'

    def runtimeStatus(self):
        self.calls.append("runtimeStatus")
        return '{"ok":true,"ready":true,"deployed":true,"home":"/data/data/com.termux/files/home"}'

    def runtimeDeploy(self):
        self.calls.append("runtimeDeploy")
        return '{"ok":true,"status":"deployed"}'

    def openTerminal(self):
        self.calls.append("openTerminal")
        return '{"ok":true,"opened":true}'

    def deviceState(self):
        return '{"ok":true,"battery":75}'

    def diagnostics(self):
        return '{"ok":true,"checks":[]}'

    def serviceControl(self, action):
        self.calls.append("service:" + action)
        return '{"ok":true}'


class QuietHandler(RequestHandler):
    def log_message(self, *args):
        pass


class BackendV1Tests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="agent-v1-")
        self.root = Path(self.temporary.name)
        self.settings = SettingsStore(self.root / "data/settings.json")
        self.settings.update({"disclaimer_accepted": True})
        self.store = Store(self.root / "data/agent.sqlite3")
        self.native = MockNative()
        self.manager = AgentManager(self.root, self.settings, self.store, "v1-test-session-secret", android=AndroidBridge(self.native))
        self.server = AgentHTTPServer(0, self.manager)
        self.server.RequestHandlerClass = QuietHandler
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        with RequestHandler._rate_lock:
            RequestHandler._rate.clear()

    def tearDown(self):
        self.native.release.set()
        self.manager.shutdown()
        self.manager.executor.shutdown(wait=True, cancel_futures=True)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.temporary.cleanup()

    def request(self, method, path, body=None, headers=None, auth=True):
        values = {"Authorization": "Bearer " + self.manager.api_token} if auth else {}
        if body is not None:
            values["Content-Type"] = "application/json"
        values.update(headers or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=4)
        connection.request(method, path, json.dumps(body) if body is not None else None, values)
        response = connection.getresponse()
        payload = response.read().decode("utf-8")
        status = response.status
        connection.close()
        try:
            return status, json.loads(payload)
        except ValueError:
            return status, payload

    def done(self, task):
        self.assertTrue(task.done.wait(4), task.snapshot())
        return self.manager.task_snapshot(task.id)

    def full_task(self, command="printf hello", **arguments):
        return self.manager.create_command_task({"command": command, **arguments}, full_access=True, full_access_confirmed=True, ui_authorized=True)

    def approve(self, task):
        approval = wait_for(lambda: task.snapshot()["pending_approval"])
        self.assertTrue(self.manager.decide(task.id, approval["approval_id"], True))
        return approval

    def test_tools_always_available_without_toggle(self):
        self.settings.update({"enabled_tools": []})
        names = {item["name"] for item in definitions(set())}
        self.assertTrue({"shell.execute", "environment.status", "workspace.write"} <= names)
        self.assertNotIn("enabled_tools", self.settings.snapshot())
        self.assertEqual(self.request("POST", "/api/tools/toggle", {"name": "shell.execute", "enabled": False})[0], 410)
        self.assertEqual(self.request("GET", "/api/tools")[0], 200)

    def test_review_exact_posix_script_cwd_env_runtime_channel(self):
        script = "for f in /sdcard/*.txt; do\n  printf '%s\\n' \"$f\" | /system/bin/tee -a /data/local/tmp/log\ndone"
        args = {"command": script, "cwd": "/data/local/tmp", "environment": {"VALUE": "a b;$(literal)"}, "runtime": "system", "channel": "normal", "timeout_seconds": 55}
        task = self.manager.create_command_task(args)
        approval = wait_for(lambda: task.snapshot()["pending_approval"])
        self.assertEqual(approval["arguments"], args)
        for key in ("command", "cwd", "environment", "runtime", "channel"):
            self.assertEqual(approval[key], args[key])
        self.assertEqual(self.native.requests, [])
        self.assertFalse(self.manager.decide(task.id, "stale", True))
        self.manager.decide(task.id, approval["approval_id"], True)
        self.assertEqual(self.done(task)["status"], "succeeded")
        request = self.native.requests[0]
        self.assertEqual(set(request), {"id", *args})
        self.assertEqual(request["command"], script)
        self.assertEqual(request["environment"], args["environment"])
        events = self.store.events_after(task.id, 0)
        output = [row["data"] for row in events if row["event"] == "command_output"]
        self.assertEqual([item["stream"] for item in output], ["stdout", "stderr"])
        self.assertEqual("".join(item["text"] for item in output), self.native.stdout + self.native.stderr)

    def test_full_access_explicit_session_authority_and_snapshot(self):
        for kwargs in ({"full_access": True}, {"full_access": True, "full_access_confirmed": True}, {"full_access": "true", "ui_authorized": True}):
            with self.assertRaises((PermissionError, ValueError)):
                self.manager.create_command_task({"command": "id"}, **kwargs)
        task = self.full_task()
        snapshot = self.done(task)
        self.assertTrue(snapshot["full_access"])
        self.assertIsNone(snapshot["pending_approval"])
        self.assertTrue(self.store.get_task(task.id)["full_access"])
        review = self.manager.create_command_task({"command": "id"})
        wait_for(lambda: review.snapshot()["pending_approval"])
        self.assertFalse(review.full_access)
        self.manager.cancel(review.id)
        self.done(review)
        self.assertNotIn("full_access", self.settings.snapshot())

    def test_http_full_access_needs_risk_confirmation_auth_and_same_origin(self):
        args = {"command": "id", "full_access": True}
        self.assertEqual(self.request("POST", "/api/commands", args)[0], 428)
        args["full_access_confirmed"] = True
        self.assertEqual(self.request("POST", "/api/commands", args, auth=False)[0], 401)
        self.assertEqual(self.request("POST", "/api/commands", args, headers={"Origin": "http://evil.invalid"})[0], 403)
        self.assertEqual(self.request("POST", "/api/commands", args, headers={"Host": "evil.invalid"})[0], 421)
        status, result = self.request("POST", "/api/commands", args)
        self.assertEqual(status, 202)
        self.assertTrue(result["task"]["full_access"])
        self.assertEqual(self.done(self.manager.get_task(result["task"]["id"]))["status"], "succeeded")

    def test_blacklist_literal_glob_and_full_access(self):
        self.assertEqual(blacklist_match("echo blocked\nid", ["blocked"]), "blocked")
        self.assertEqual(blacklist_match("echo blocked\nid", ["glob:*blocked*id"]), "glob:*blocked*id")
        self.assertIsNone(blacklist_match("ECHO blocked", ["echo blocked"]))
        self.assertEqual(blacklist_match("xx [abc] yy", ["substring:[abc]"]), "substring:[abc]")
        self.settings.update({"blacklist": ["glob:*blocked*"]})
        task = self.full_task("echo blocked")
        self.assertEqual(self.done(task)["status"], "failed")
        self.assertEqual(self.native.requests, [])

    def test_blacklist_rechecked_after_approval(self):
        task = self.manager.create_command_task({"command": "echo newrule"})
        approval = wait_for(lambda: task.snapshot()["pending_approval"])
        self.settings.update({"blacklist": ["newrule"]})
        self.manager.decide(task.id, approval["approval_id"], True)
        self.assertEqual(self.done(task)["status"], "failed")
        self.assertEqual(self.native.requests, [])

    def test_schema_strict_bounds_not_command_allowlist(self):
        script = "cat <<'EOF' | tr a-z A-Z\nhello; $world\nEOF\n"
        self.assertEqual(validate_command({"command": script})["command"], script)
        bad = [{"command": "x\x00y"}, {"command": "x\x01y"}, {"command": "x", "timeout_seconds": True},
               {"command": "x", "timeout_seconds": 3601}, {"command": "x", "cwd": "C:/Windows"},
               {"command": "x", "environment": {"BAD-NAME": "x"}}, {"command": "x", "environment": {"OK": 1}},
               {"command": "x", "full_access": True}, {"command": "x", "runtime": "powershell"},
               {"command": "x", "channel": "auto"}, {"command": "x" * 65537}]
        for args in bad:
            with self.subTest(args=str(args)[:100]), self.assertRaises(ValueError):
                validate_command(args)

    def test_unavailable_actual_channel_and_no_silent_escalation(self):
        task = self.full_task(channel="root")
        self.assertEqual(self.done(task)["status"], "failed")
        self.assertEqual(self.native.requests, [])
        self.native.granted = False
        task = self.full_task()
        self.assertEqual(self.done(task)["status"], "failed")
        self.assertEqual(self.native.requests, [])

    def test_selected_channel_synced_and_snapshot_cannot_be_changed(self):
        self.native.channel = "root"
        manager = AgentManager(self.root / "root-start", SettingsStore(self.root / "root-start/settings.json"), Store(self.root / "root-start/db.sqlite3"), "other", android=AndroidBridge(self.native))
        self.assertEqual(manager.channel, "root")
        manager.shutdown()
        manager.executor.shutdown(wait=True)
        self.native.channel = "normal"
        task = self.manager.create_command_task({"command": "id"})
        approval = wait_for(lambda: task.snapshot()["pending_approval"])
        self.manager.channel = "root"
        self.native.channel = "root"
        self.manager.decide(task.id, approval["approval_id"], True)
        self.assertEqual(self.done(task)["status"], "failed")
        self.assertEqual(self.native.requests, [])

    def test_cancel_is_per_command_and_streams_before_done(self):
        self.native.block = True
        first = self.full_task("long first")
        second = self.full_task("long second")
        wait_for(lambda: len(self.native.requests) == 2)
        wait_for(lambda: any(item["event"] == "command_output" for item in self.store.events_after(first.id, 0)))
        self.assertFalse(first.done.is_set())
        first_id = next(item["id"] for item in self.native.requests if item["command"] == "long first")
        second_id = next(item["id"] for item in self.native.requests if item["command"] == "long second")
        self.assertTrue(self.manager.cancel(first.id))
        self.assertEqual(self.done(first)["status"], "cancelled")
        self.assertIn(first_id, self.native.cancelled)
        self.assertNotIn(second_id, self.native.cancelled)
        self.native.release.set()
        self.assertEqual(self.done(second)["status"], "succeeded")
        first_events = [item["event"] for item in self.store.events_after(first.id, 0)]
        self.assertNotIn("task_completed", first_events)
        self.assertEqual(first_events.count("task_cancelled"), 1)

    def test_command_timeout_and_total_task_deadline_are_honest(self):
        self.native.block = True
        task = self.full_task(timeout_seconds=1)
        self.assertEqual(self.done(task)["status"], "timed_out")
        self.assertIn(self.native.requests[0]["id"], self.native.cancelled)
        task = self.full_task("another long command")
        wait_for(lambda: len(self.native.requests) == 2)
        self.manager._expire(task.id)
        self.assertEqual(self.done(task)["status"], "timed_out")
        self.assertIn(self.native.requests[1]["id"], self.native.cancelled)

    def test_native_failure_and_output_cap(self):
        self.settings.update({"output_cap_bytes": 1024})
        self.native.stdout = "汉" * 1000
        self.native.stderr = "private warning"
        self.native.exit_code = 7
        task = self.full_task()
        self.assertEqual(self.done(task)["status"], "failed")
        result = next(item["data"]["result"] for item in self.store.events_after(task.id, 0) if item["event"] == "tool_result")
        self.assertTrue(result["truncated"])
        self.assertLessEqual(len((result["stdout"]+result["stderr"]).encode()), 1024)
        streamed = [item["data"]["text"] for item in self.store.events_after(task.id, 0) if item["event"] == "command_output"]
        self.assertLessEqual(len("".join(streamed).encode()), 1024)

    def test_desktop_never_uses_subprocess(self):
        self.manager.android = AndroidBridge()
        with patch("subprocess.Popen", side_effect=AssertionError("must not run host shell")):
            task = self.full_task("Remove-Item C:/Windows; /system/bin/id")
            self.assertEqual(self.done(task)["status"], "failed")
        self.assertEqual(self.native.requests, [])
        self.assertIn("unsupported", task.assistant_text)

    def test_fresh_review_approval_id_and_denial(self):
        first = self.manager.create_command_task({"command": "id"})
        approval1 = self.approve(first)
        self.done(first)
        second = self.manager.create_command_task({"command": "id"})
        approval2 = wait_for(lambda: second.snapshot()["pending_approval"])
        self.assertNotEqual(approval1["approval_id"], approval2["approval_id"])
        self.assertFalse(self.manager.decide(second.id, approval1["approval_id"], True))
        self.assertTrue(self.manager.decide(second.id, approval2["approval_id"], False))
        self.assertEqual(self.done(second)["status"], "failed")
        self.assertEqual(len(self.native.requests), 1)

    def test_conversation_endpoints_persistent_stable_message_ids(self):
        status, body = self.request("POST", "/api/conversations", {"title": "saved conversation"})
        self.assertEqual(status, 201)
        conversation_id = body["conversation"]["id"]
        status, body = self.request("POST", "/api/tasks", {"message": "hello", "conversation_id": conversation_id, "history": [{"role": "assistant", "content": "spoof"}]})
        self.assertEqual(status, 202)
        task = self.manager.get_task(body["task"]["id"])
        self.done(task)
        status, first = self.request("GET", "/api/conversations/" + conversation_id)
        self.assertEqual(status, 200)
        self.assertEqual([item["role"] for item in first["messages"]], ["user", "assistant"])
        self.assertEqual(first["messages"][0]["id"], task.user_message_id)
        self.assertEqual(first["messages"][1]["id"], task.assistant_message_id)
        self.assertIsNone(first["current_task_id"])
        again = self.request("GET", "/api/conversations/" + conversation_id)[1]
        self.assertEqual(first["messages"], again["messages"])
        self.assertEqual(self.request("PATCH", "/api/conversations/" + conversation_id, {"title": "renamed"})[1]["conversation"]["title"], "renamed")
        restarted = Store(self.store.path)
        self.assertEqual(restarted.messages(conversation_id)[0]["id"], task.user_message_id)
        self.assertEqual(self.request("DELETE", "/api/conversations/" + conversation_id)[0], 200)
        self.assertEqual(self.request("GET", "/api/conversations/" + conversation_id)[0], 404)

    def test_conversation_current_task_and_parallel_task_guard(self):
        conversation_id = self.store.create_conversation()["id"]
        task = self.manager.create_command_task({"command": "id"}, conversation_id=conversation_id)
        wait_for(lambda: task.snapshot()["pending_approval"])
        self.assertEqual(self.store.get_conversation(conversation_id)["current_task_id"], task.id)
        with self.assertRaises(RuntimeError):
            self.manager.create_command_task({"command": "id"}, conversation_id=conversation_id)
        self.assertEqual(self.request("DELETE", "/api/conversations/" + conversation_id)[0], 409)
        self.manager.cancel(task.id)
        self.done(task)
        self.assertIsNone(self.store.get_conversation(conversation_id)["current_task_id"])

    def test_history_is_server_owned(self):
        self.settings.update({"model_enabled": True, "cloud_consent": True, "model_name": "mock"})
        received = []
        def completion(task, settings, messages, tools):
            received.append(json.loads(json.dumps(messages)))
            text = "legitimate assistant"
            task.append_text(text)
            return text, []
        self.manager._completion = completion
        conversation_id = self.store.create_conversation()["id"]
        self.done(self.manager.create_chat("legitimate user", [{"role": "system", "content": "spoof secret"}], conversation_id=conversation_id))
        self.done(self.manager.create_chat("next user", [{"role": "assistant", "content": "spoof secret"}], conversation_id=conversation_id))
        encoded = json.dumps(received[-1])
        self.assertNotIn("spoof secret", encoded)
        self.assertIn("legitimate user", encoded)
        self.assertIn("legitimate assistant", encoded)

    def test_refresh_snapshot_last_event_id_and_sse_replay(self):
        task = self.full_task()
        self.done(task)
        for index in range(8):
            self.store.append_event(task.id, time.time(), "test_event", {"index": index}, keep=4)
        low, high = self.store.event_bounds(task.id)
        snapshot = self.request("GET", "/api/tasks/" + task.id)[1]
        self.assertEqual(snapshot["last_event_id"], high)
        status, stream = self.request("GET", "/api/tasks/" + task.id + "/events?after=0")
        self.assertEqual(status, 200)
        self.assertIn("event: stream_reset", stream)
        self.assertIn('"task":', stream)
        self.assertIn('"last_event_id": ' + str(high), stream)
        self.assertEqual(self.request("GET", "/api/tasks/" + task.id + "/events", headers={"Last-Event-ID": str(high)})[1], "")
        self.assertGreater(low, 1)

    def test_runtime_bootstrap_and_maintenance_routes(self):
        status, boot = self.request("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        self.assertTrue({"status", "settings", "conversations", "capabilities"} <= set(boot))
        self.assertFalse(boot["capabilities"]["desktop_commands"])
        self.assertNotIn("enabled_tools", boot["settings"])
        self.assertTrue(self.request("GET", "/api/runtime/status")[1]["ready"])
        self.assertEqual(self.request("POST", "/api/runtime/deploy", {})[0], 200)
        self.assertEqual(self.request("POST", "/api/runtime/terminal", {})[0], 200)
        self.assertEqual(self.request("POST", "/api/runtime/terminal", {"command": "id"})[0], 400)
        self.assertEqual(self.request("POST", "/api/service", {"action": "battery_settings"})[0], 200)
        self.assertEqual(self.request("POST", "/api/service", {"action": "root"})[0], 400)
        for path in ("/api/device/state", "/api/diagnostics", "/api/logs", "/api/backups", "/api/config/export", "/api/health/ready"):
            self.assertEqual(self.request("GET", path)[0], 200, path)
        self.assertEqual(self.native.requests, [])

    def test_settings_validation_atomic_memory_key_and_redacted_events(self):
        status, result = self.request("POST", "/api/settings", {"api_key": "super-private-fixture", "max_rounds": 50, "blacklist": ["glob:*format*"], "default_runtime": "termux"})
        self.assertEqual(status, 200)
        self.assertEqual(result["max_rounds"], 50)
        self.assertNotIn("super-private-fixture", self.settings.path.read_text())
        self.assertNotIn("super-private-fixture", json.dumps(result))
        self.assertEqual(self.request("POST", "/api/settings", {"api_key": "wrong-new-key", "max_rounds": 51})[0], 400)
        self.assertEqual(self.manager.api_key, "super-private-fixture")
        for body in ({"command_timeout_seconds": 0}, {"max_rounds": True}, {"full_access": True}, {"blacklist": [""]}, {"model_base_url": "https://u:p@bad.invalid/v1"}, {"update_manifest_url": "http://bad.invalid/update"}):
            self.assertEqual(self.request("POST", "/api/settings", body)[0], 400, body)
        self.native.stdout = "super-private-fixture " + self.manager.api_token
        task = self.full_task()
        self.done(task)
        self.assertNotIn("super-private-fixture", json.dumps(self.store.events_after(task.id, 0)))
        self.assertNotIn(self.manager.api_token, json.dumps(self.store.events_after(task.id, 0)))
        self.assertNotIn("super-private-fixture", json.dumps(self.store.list_audit()))

    def test_termux_default_home_and_mcp_cannot_set_full_access(self):
        self.settings.update({"default_runtime": "termux"})
        task = self.full_task()
        self.done(task)
        self.assertEqual(self.native.requests[0]["cwd"], "/data/data/com.termux/files/home")
        self.assertEqual(self.native.requests[0]["runtime"], "termux")
        self.assertEqual(self.request("POST", "/api/mcp/tools/call", {"name": "shell.execute", "arguments": {"command": "id"}, "full_access": True})[0], 400)
        self.assertEqual(self.request("POST", "/api/mcp/tools/call", {"name": "shell.execute", "arguments": {"command": "id", "full_access": True}})[0], 400)

    def test_transient_retry_never_replays_mutating_tool(self):
        self.settings.update({"model_enabled": True, "cloud_consent": True, "model_name": "mock"})
        stages = []
        def completion(task, settings, messages, tools):
            tool_results = [item for item in messages if item["role"] == "tool"]
            stages.append(bool(tool_results))
            if not tool_results:
                return "", [{"id": "same-call", "name": "shell_execute", "arguments": '{"command":"id"}'}]
            if stages.count(True) == 1:
                raise TransientModelError("HTTP503")
            task.append_text("done")
            return "done", []
        self.manager._completion = completion
        task = self.manager.create_chat("run", full_access=True, full_access_confirmed=True, ui_authorized=True)
        self.assertEqual(self.done(task)["status"], "succeeded")
        self.assertEqual(len(self.native.requests), 1)
        self.assertEqual(stages, [False, True, True])

    def test_shizuku_system_cwd_and_termux_rejected(self):
        self.manager.channel = "shizuku"
        self.native.channel = "shizuku"
        task = self.full_task("id", channel="shizuku", runtime="system")
        self.assertEqual(self.done(task)["status"], "succeeded")
        self.assertEqual(self.native.requests[0]["cwd"], "/data/local/tmp")
        task = self.full_task("id", channel="shizuku", runtime="termux")
        self.assertEqual(self.done(task)["status"], "failed")
        self.assertIn("Shizuku", task.error)
        self.assertEqual(len(self.native.requests), 1)

    def test_native_chunk_only_result_reconstructed_and_more_drained(self):
        def poll(command_id, after):
            if after == 0:
                return json.dumps({"chunks": [{"seq": 1, "stream": "stdout", "text": "part one\n"}], "done": True, "more": True})
            return json.dumps({"chunks": [{"seq": 2, "stream": "stderr", "text": "part two\n"}], "done": True,
                               "result": {"output_from_chunks": True, "exit_code": 0, "status": "succeeded", "truncated": False}})
        self.native.commandPoll = poll
        task = self.full_task()
        self.assertEqual(self.done(task)["status"], "succeeded")
        result = next(item["data"]["result"] for item in self.store.events_after(task.id, 0) if item["event"] == "tool_result")
        self.assertEqual(result["stdout"], "part one\n")
        self.assertEqual(result["stderr"], "part two\n")

    def test_cancel_delayed_permission_config_resets_native_and_manager(self):
        entered = threading.Event()
        released = threading.Event()
        def configure(channel):
            if channel == "root":
                entered.set()
                released.wait(2)
            self.native.channel = channel
            return json.dumps({"ok": True, "selected_channel": channel})
        self.native.configureChannel = configure
        task = self.manager.create_channel_task("root")
        self.approve(task)
        self.assertTrue(entered.wait(2))
        self.manager.cancel(task.id)
        released.set()
        self.assertEqual(self.done(task)["status"], "cancelled")
        self.assertEqual(self.manager.channel, "normal")
        self.assertEqual(self.native.channel, "normal")

    def test_mcp_resources_prompts_and_file_read_share_review(self):
        for method, key in (("resources/list", "resources"), ("resources/templates/list", "resourceTemplates"), ("prompts/list", "prompts")):
            status, body = self.request("POST", "/mcp", {"jsonrpc": "2.0", "id": 1, "method": method, "params": {}})
            self.assertEqual(status, 200)
            self.assertIn(key, body["result"])
        _, body = self.request("POST", "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "prompts/get", "params": {"name": "workflow_install_apk", "arguments": {"url": "https://example.invalid/a.apk", "sha256": "f"*64}}})
        self.assertIn("messages", body["result"])
        _, body = self.request("POST", "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "prompts/get", "params": {"name": "workflow_install_apk", "arguments": {}}})
        self.assertEqual(body["error"]["code"], -32602)
        for uri in ("agent://device/status", "agent://device/info", "agent://device/state"):
            _, body = self.request("POST", "/mcp", {"jsonrpc": "2.0", "id": 3, "method": "resources/read", "params": {"uri": uri}})
            self.assertIn("contents", body["result"])
        self.manager.workspace.write("space name.txt", "resource secret fixture")
        response = []
        reader = threading.Thread(target=lambda: response.append(self.request("POST", "/mcp", {"jsonrpc": "2.0", "id": 4, "method": "resources/read", "params": {"uri": "agent://workspace/space%20name.txt"}})), daemon=True)
        reader.start()
        approvals = wait_for(lambda: self.manager.approvals())
        approval = approvals[0]["pending_approval"]
        self.assertEqual(approval["tool"], "workspace.read")
        self.assertTrue(self.manager.decide(approvals[0]["id"], approval["approval_id"], True))
        reader.join(3)
        self.assertEqual(response[0][1]["result"]["contents"][0]["text"], "resource secret fixture")
        for uri in ("agent://workspace/%2e%2e/secret", "agent://workspace/%GG", "agent://workspace/file?x=1"):
            _, body = self.request("POST", "/mcp", {"jsonrpc": "2.0", "id": 5, "method": "resources/read", "params": {"uri": uri}})
            self.assertIn("error", body)

    def test_malformed_mcp_request_and_duplicate_authorization(self):
        for request in ({"jsonrpc": "2.0", "id": {}, "method": "ping"}, {"jsonrpc": "2.0", "id": True, "method": "ping"}, {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": []}):
            _, body = self.request("POST", "/mcp", request)
            self.assertIn("error", body)
        status, _ = self.request("POST", "/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"})
        self.assertEqual(status, 202)
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.putrequest("GET", "/api/status")
        connection.putheader("Authorization", "Bearer " + self.manager.api_token)
        connection.putheader("Authorization", "Bearer " + self.manager.api_token)
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 401)
        response.read()
        connection.close()

    def test_repeated_call_id_is_cached_and_round_limit_honest(self):
        self.settings.update({"model_enabled": True, "cloud_consent": True, "model_name": "mock", "max_rounds": 3})
        def completion(task, settings, messages, tools):
            return "", [{"id": "duplicate", "name": "shell_execute", "arguments": '{"command":"id"}'}]
        self.manager._completion = completion
        task = self.manager.create_chat("repeat", full_access=True, full_access_confirmed=True, ui_authorized=True)
        self.assertEqual(self.done(task)["status"], "failed")
        self.assertEqual(len(self.native.requests), 1)
        self.assertIn("轮数上限", task.error)
        self.assertFalse(any(item["event"] == "task_completed" for item in self.store.events_after(task.id, 0)))


class ModelHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append(payload)
        if self.server.failures:
            self.server.failures -= 1
            self.send_response(503)
            body = b"{}"
        else:
            self.send_response(200)
            body = json.dumps({"choices": [{"message": {"content": "OK", "tool_calls": []}}]}).encode()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class ModelHTTPV1Tests(unittest.TestCase):
    def test_real_http_retry_and_connection_test_never_sends_tools_or_saves_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = ThreadingHTTPServer(("127.0.0.1", 0), ModelHTTPHandler)
            server.daemon_threads = True
            server.requests, server.failures = [], 1
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            settings = SettingsStore(root / "settings.json")
            settings.update({"disclaimer_accepted": True, "model_enabled": True, "cloud_consent": True, "model_name": "fixture", "model_base_url": "http://127.0.0.1:"+str(server.server_port)+"/v1"})
            manager = AgentManager(root, settings, Store(root / "db.sqlite3"), "secret-session", android=AndroidBridge(MockNative()))
            try:
                task = manager.create_chat("hello")
                self.assertTrue(task.done.wait(4))
                self.assertEqual(task.state, "succeeded", task.error)
                self.assertEqual(len(server.requests), 2)
                result = manager.test_model({"api_key": "temporary-test-only"})
                self.assertTrue(result["ok"])
                self.assertNotIn("tools", server.requests[-1])
                self.assertNotIn("tool_choice", server.requests[-1])
                self.assertEqual(manager.api_key, "")
                self.assertNotIn("temporary-test-only", settings.path.read_text())
            finally:
                manager.shutdown()
                manager.executor.shutdown(wait=True, cancel_futures=True)
                server.shutdown()
                server.server_close()
                thread.join(2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
