from __future__ import annotations

import hashlib
import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from android_agent.config import SettingsStore
from android_agent.core import AgentManager
from android_agent.server import AgentHTTPServer, RequestHandler
from android_agent.store import Store


class McpDynamicHandler(RequestHandler):
    def log_message(self, *args):
        pass


class McpDynamicTests(unittest.TestCase):
    """Regression coverage for MCP dynamic discovery and dispatch boundaries."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mcp-dynamic-")
        root = Path(self.temp.name)
        self.settings = SettingsStore(root / "data" / "settings.json")
        self.settings.update({"disclaimer_accepted": True, "mcp_enabled": True})
        self.store = Store(root / "data" / "agent.sqlite3")
        self.manager = AgentManager(root, self.settings, self.store, "mcp-test-api-token")
        self.server = AgentHTTPServer(0, self.manager)
        self.server.RequestHandlerClass = McpDynamicHandler
        with RequestHandler._rate_lock:
            RequestHandler._rate.clear()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

        self.server_id = "fixture-server"
        self.tool_name = "echo.tool"
        self.alias = (
            "mcp_" + hashlib.sha256(self.server_id.encode()).hexdigest()[:20]
            + "_" + hashlib.sha256(self.tool_name.encode()).hexdigest()[:20]
        )
        self.connector_token = "mcp-connector-test-secret"
        self.remote_tools = [{
            "name": self.tool_name,
            "description": "Remote echo fixture.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "minLength": 1, "maxLength": 20},
                    "count": {"type": "integer", "minimum": 1, "maximum": 3},
                    "enabled": {"type": "boolean"},
                    "tags": {"type": "array", "maxItems": 2, "items": {"type": "string", "maxLength": 5}},
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        }]
        self.manager.extensions.add_mcp("Fixture", "https://fixture.invalid/mcp", self.connector_token, self.server_id)
        self.manager.extensions.mcp_tools = lambda _server_id: list(self.remote_tools)
        self.manager.extensions.call_mcp = lambda _server_id, tool, args: {
            "ok": True, "tool": tool, "arguments": args,
            "content": [{"type": "text", "text": "echoed"}],
        }

    def tearDown(self):
        self.manager.shutdown()
        self.manager.executor.shutdown(wait=True, cancel_futures=True)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.temp.cleanup()

    def request(self, method: str, path: str, body=None):
        headers = {"Authorization": "Bearer " + self.manager.api_token}
        if body is not None:
            headers["Content-Type"] = "application/json"
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=6)
        conn.request(method, path, json.dumps(body).encode("utf-8") if body is not None else None, headers)
        response = conn.getresponse()
        raw = response.read()
        status = response.status
        conn.close()
        try:
            return status, json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return status, raw

    @staticmethod
    def wait_until(predicate, timeout=4):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            time.sleep(0.02)
        raise AssertionError("condition not reached before timeout")

    def dynamic_tool(self, tools):
        return next((tool for tool in tools if tool.get("name") == self.alias), None)

    def test_hashed_alias_discovery_across_api_bootstrap_and_rpc_tools_list(self):
        status, api = self.request("GET", "/api/tools")
        self.assertEqual(status, 200)
        api_tool = self.dynamic_tool(api["tools"])
        self.assertIsNotNone(api_tool)

        status, bootstrap = self.request("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        self.assertEqual(self.dynamic_tool(bootstrap["tools"]), api_tool)
        self.assertEqual(self.dynamic_tool(bootstrap["all_tools"]), api_tool)

        status, rpc = self.request("POST", "/mcp", {
            "jsonrpc": "2.0", "id": "list-1", "method": "tools/list", "params": {},
        })
        self.assertEqual(status, 200)
        self.assertEqual(rpc["id"], "list-1")
        rpc_tool = self.dynamic_tool(rpc["result"]["tools"])
        self.assertIsNotNone(rpc_tool)
        self.assertEqual(rpc_tool["name"], api_tool["name"])
        self.assertEqual(rpc_tool["inputSchema"], api_tool["inputSchema"])
        self.assertEqual(api_tool["name"], self.alias)
        self.assertTrue(api_tool["requiresApproval"])

    def test_bootstrap_uses_a_single_discovery_snapshot(self):
        first = list(self.remote_tools)
        self.manager.extensions.mcp_tools = Mock(side_effect=[first, []])
        status, body = self.request("GET", "/api/bootstrap")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["tools"], body["all_tools"])

    def test_direct_api_dispatch_waits_for_explicit_approval(self):
        remote_call = Mock(return_value={"ok": True, "content": []})
        self.manager.extensions.call_mcp = remote_call
        status, response = self.request("POST", "/api/mcp/tools/call", {
            "name": self.alias, "arguments": {"text": "hello", "count": 2},
        })
        self.assertEqual(status, 202, response)
        task = self.manager.get_task(response["task"]["id"])
        approval = self.wait_until(lambda: task.snapshot().get("pending_approval"))
        self.assertEqual(approval["tool"], self.alias)
        self.assertEqual(approval["arguments"]["tool_name"], self.tool_name)
        self.assertEqual(approval["arguments"]["arguments"], {"text": "hello", "count": 2})
        remote_call.assert_not_called()
        self.assertTrue(self.manager.decide(task.id, approval["approval_id"], True))
        self.assertTrue(task.done.wait(4), task.snapshot())
        self.assertEqual(self.store.get_task(task.id)["state"], "succeeded")
        remote_call.assert_called_once_with(self.server_id, self.tool_name, {"text": "hello", "count": 2})

    def test_rpc_tools_call_waits_for_approval_and_preserves_id(self):
        replies = []
        caller = threading.Thread(target=lambda: replies.append(self.request("POST", "/mcp", {
            "jsonrpc": "2.0", "id": "call-2", "method": "tools/call",
            "params": {"name": self.alias, "arguments": {"text": "hello"}},
        })), daemon=True)
        caller.start()
        approvals = self.wait_until(lambda: self.manager.approvals())
        approval = approvals[0]["pending_approval"]
        self.assertTrue(self.manager.decide(approvals[0]["id"], approval["approval_id"], False))
        caller.join(4)
        self.assertFalse(caller.is_alive(), "JSON-RPC tools/call did not return after denial")
        status, response = replies[0]
        self.assertEqual(status, 200)
        self.assertEqual(response["id"], "call-2")
        self.assertTrue(response["result"]["isError"])
        self.assertIn("未获批准", response["result"]["content"][0]["text"])

    def test_unknown_missing_and_wrong_typed_arguments_are_rejected(self):
        cases = [
            ("mcp_" + "0" * 20 + "_" + "0" * 20, {"text": "hello"}),
            (self.alias, []),
            (self.alias, {}),
            (self.alias, {"text": ""}),
            (self.alias, {"text": "hello", "count": True}),
            (self.alias, {"text": "hello", "count": 4}),
            (self.alias, {"text": "hello", "tags": ["fine", "too-long"]}),
            (self.alias, {"text": "hello", "extra": "undeclared"}),
        ]
        for name, arguments in cases:
            with self.subTest(name=name, arguments=arguments):
                status, response = self.request("POST", "/api/mcp/tools/call", {
                    "name": name, "arguments": arguments,
                })
                self.assertEqual(status, 400, response)
                self.assertIn("error", response)

    def test_disabled_connector_hides_tools_and_rejects_dispatch(self):
        self.settings.update({"mcp_enabled": False})
        status, response = self.request("GET", "/api/tools")
        self.assertEqual(status, 200)
        self.assertIsNone(self.dynamic_tool(response["tools"]))
        status, response = self.request("POST", "/api/mcp/tools/call", {
            "name": self.alias, "arguments": {"text": "hello"},
        })
        self.assertEqual(status, 428, response)
        self.assertIn("error", response)

    def test_stale_task_mapping_is_rejected_before_approval_or_remote_call(self):
        _items, targets = self.manager._discover_mcp_tools()
        fake_task = SimpleNamespace(
            mcp_tool_targets=targets,
            request_approval=Mock(return_value=True),
            check_cancelled=Mock(),
        )
        self.remote_tools.clear()
        remote_call = Mock(side_effect=AssertionError("stale mapping reached remote call"))
        self.manager.extensions.call_mcp = remote_call
        with self.assertRaises(ValueError):
            self.manager.call_mcp_tool(fake_task, self.alias, {"text": "hello"})
        fake_task.request_approval.assert_not_called()
        remote_call.assert_not_called()

    def test_connector_credential_is_redacted_from_dynamic_metadata(self):
        self.remote_tools[0]["description"] = "Fixture " + self.connector_token
        self.remote_tools[0]["inputSchema"]["properties"]["text"]["description"] = self.connector_token
        status, api = self.request("GET", "/api/tools")
        self.assertEqual(status, 200)
        status, bootstrap = self.request("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        status, rpc = self.request("POST", "/mcp", {
            "jsonrpc": "2.0", "id": 9, "method": "tools/list", "params": {},
        })
        self.assertEqual(status, 200)
        exposed = [
            self.dynamic_tool(api["tools"]), self.dynamic_tool(bootstrap["tools"]),
            self.dynamic_tool(rpc["result"]["tools"]),
        ]
        for tool in exposed:
            with self.subTest(tool=tool):
                self.assertIsNotNone(tool)
                self.assertNotIn(self.connector_token, json.dumps(tool, ensure_ascii=False))

    def test_json_rpc_invalid_arguments_use_invalid_params_code(self):
        status, response = self.request("POST", "/mcp", {
            "jsonrpc": "2.0", "id": 11, "method": "tools/call",
            "params": {"name": self.alias, "arguments": {"text": ""}},
        })
        self.assertEqual(status, 200)
        self.assertEqual(response["id"], 11)
        self.assertEqual(response["error"]["code"], -32602)

    def test_zero_max_length_constraint_is_preserved(self):
        self.remote_tools[0]["inputSchema"] = {
            "type": "object",
            "properties": {"text": {"type": "string", "maxLength": 0}},
            "required": ["text"],
        }
        status, response = self.request("POST", "/api/mcp/tools/call", {
            "name": self.alias, "arguments": {"text": "x"},
        })
        if status == 202:
            self.manager.cancel(response["task"]["id"])
        self.assertEqual(status, 400, response)


    def test_nullable_schema_does_not_break_all_tool_discovery(self):
        self.remote_tools[0]["inputSchema"]["properties"]["text"]["type"] = ["string", "null"]
        status, response = self.request("GET", "/api/tools")
        # Either advertise a supported nullable schema or omit this tool safely;
        # one unhandled schema must not take down the entire tool-list endpoint.
        self.assertEqual(status, 200, response)
        self.assertIn("tools", response)

    def test_huge_json_integer_is_rejected_without_internal_error(self):
        status, response = self.request("POST", "/api/mcp/tools/call", {
            "name": self.alias, "arguments": {"text": "hello", "count": 10 ** 1000},
        })
        self.assertEqual(status, 400, response)
        self.assertIn("error", response)

    def test_disabling_connector_during_approval_blocks_remote_dispatch(self):
        remote_call = Mock(return_value={"ok": True})
        self.manager.extensions.call_mcp = remote_call
        task = self.manager.create_tool_task(self.alias, {"text": "hello"})
        approval = self.wait_until(lambda: task.snapshot().get("pending_approval"))
        self.settings.update({"mcp_enabled": False})
        self.assertTrue(self.manager.decide(task.id, approval["approval_id"], True))
        self.assertTrue(task.done.wait(4), task.snapshot())
        remote_call.assert_not_called()
        self.assertEqual(self.store.get_task(task.id)["state"], "failed")

    def test_connector_credential_is_redacted_from_result_and_approval_events(self):
        self.remote_tools[0]["inputSchema"]["properties"]["text"]["maxLength"] = 64
        self.manager.extensions.call_mcp = Mock(return_value={
            "ok": True, "result": {"content": [{"type": "text", "text": self.connector_token}]},
        })
        task = self.manager.create_tool_task(self.alias, {"text": self.connector_token})
        approval = self.wait_until(lambda: task.snapshot().get("pending_approval"))
        self.assertNotIn(self.connector_token, json.dumps(approval))
        self.assertTrue(self.manager.decide(task.id, approval["approval_id"], True))
        self.assertTrue(task.done.wait(4), task.snapshot())
        self.assertEqual(self.store.get_task(task.id)["state"], "succeeded")
        self.assertNotIn(self.connector_token, json.dumps(self.store.events_after(task.id, 0)))
        self.assertNotIn(self.connector_token, json.dumps(task.snapshot()))

    def test_malformed_aliases_are_rejected_without_discovery(self):
        discovery = Mock(side_effect=AssertionError("malformed alias triggered discovery"))
        self.manager.extensions.mcp_tools = discovery
        for name in ("mcp_", "mcp_" + "g" * 20 + "_" + "0" * 20,
                     "mcp_" + "0" * 20 + "-" + "0" * 20,
                     "mcp_" + "0" * 20 + "_" + "0" * 19):
            with self.subTest(name=name):
                status, response = self.request("POST", "/api/mcp/tools/call", {
                    "name": name, "arguments": {},
                })
                self.assertEqual(status, 400, response)
        discovery.assert_not_called()


if __name__ == "__main__":
    unittest.main()
