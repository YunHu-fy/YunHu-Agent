"""HTTP route regressions for local-model setup and message mutations."""
from __future__ import annotations

import http.client
import json
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

from android_agent.android_bridge import AndroidBridge
from android_agent.config import SettingsStore
from android_agent.core import AgentManager
from android_agent.server import AgentHTTPServer, RequestHandler
from android_agent.store import Store


class FakeLocalNative:
    def __init__(self):
        self.local = {"ok": True, "supported": True, "installed": False, "installing": False,
                      "running": False, "healthy": False, "active_model_id": None, "port": None}
        self.runtime = {"ok": True, "supported": True, "installed": True, "installing": False, "stage": "ready"}

    def status(self):
        return json.dumps({"ok": True, "selected_channel": "normal", "normal": {"available": True, "granted": True},
                           "shizuku": {"available": False, "granted": False}, "root": {"available": False, "granted": False}})

    def runtimeStatus(self):
        return json.dumps(self.runtime)

    def runtimeDeploy(self):
        self.runtime.update(installed=True, stage="ready")
        return json.dumps(self.runtime)

    def localModelStatus(self):
        return json.dumps(self.local)

    def localModelInstall(self):
        self.local.update(installed=True, installing=False, install_state="succeeded")
        return json.dumps(self.local)

    def localModelStart(self, path, alias, port, context, threads):
        self.local.update(running=True, healthy=True, active_model_id=alias, port=port)
        return json.dumps(self.local)

    def localModelStop(self):
        self.local.update(running=False, healthy=False, active_model_id=None, port=None)
        return json.dumps(self.local)

    def localModelLog(self):
        return json.dumps({"ok": True, "path": "/data/data/com.termux/files/private/server.log",
                           "bytes": 24, "text": "error: invalid argument: --no-webui"})


class LocalRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="local-route-")
        root = Path(self.temporary.name)
        self.settings = SettingsStore(root / "data" / "settings.json")
        self.settings.update({"disclaimer_accepted": True})
        self.store = Store(root / "data" / "agent.sqlite3")
        self.native = FakeLocalNative()
        self.manager = AgentManager(root, self.settings, self.store, "route-test-token", android=AndroidBridge(self.native))
        self.server = AgentHTTPServer(0, self.manager)
        with RequestHandler._rate_lock:
            RequestHandler._rate.clear()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.manager.shutdown()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.temporary.cleanup()

    def request(self, method: str, path: str, body=None):
        headers = {"Authorization": "Bearer " + self.manager.api_token}
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(method, path, json.dumps(body).encode("utf-8") if body is not None else None, headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        status = response.status
        connection.close()
        return status, payload

    def add_completed_turn(self, text: str, answer: str):
        conversation = self.store.create_conversation(text)
        now = time.time()
        task_id, user_id, assistant_id = (uuid.uuid4().hex for _ in range(3))
        self.store.create_task({"id": task_id, "message": text, "origin": "chat", "state": "queued",
                                "created_at": now, "updated_at": now, "assistant_text": "",
                                "conversation_id": conversation["id"], "user_message_id": user_id,
                                "assistant_message_id": assistant_id})
        self.store.update_task(task_id, "succeeded", now + 1, assistant_text=answer)
        return conversation["id"], user_id

    def test_local_catalog_and_status_routes_are_public_and_path_safe(self):
        status, catalog = self.request("GET", "/api/local-models/catalog")
        self.assertEqual(status, 200)
        self.assertEqual(len(catalog["catalog"]), 10)
        status, models = self.request("GET", "/api/local-models")
        self.assertEqual(status, 200)
        self.assertEqual(len(models["models"]), 10)
        self.assertNotIn(str(self.temporary.name), json.dumps(models))
        self.assertIn("configuration", models)

    def test_runtime_package_route_validates_catalog_and_links_conversation(self):
        conversation = self.store.create_conversation("runtime")
        status, result = self.request("POST", "/api/runtime/packages", {"package_ids": ["unknown-package"], "distro": None, "conversation_id": conversation["id"]})
        self.assertEqual(status, 400)
        self.assertNotIn("unknown-package", json.dumps(result))
        status, result = self.request("POST", "/api/runtime/packages", {"package_ids": ["curl"], "distro": None, "conversation_id": conversation["id"]})
        self.assertEqual(status, 202, result)
        task_id = result["task"]["id"]
        self.assertEqual(result["task"]["conversation_id"], conversation["id"])
        self.assertEqual(self.store.get_task(task_id)["conversation_id"], conversation["id"])
        other = self.store.create_conversation("deploy")
        status, result = self.request("POST", "/api/runtime/packages", {"action": "deploy", "distro": "debian", "package_ids": ["curl"], "conversation_id": other["id"]})
        self.assertEqual(status, 400)

    def test_engine_log_route_exposes_only_the_text(self):
        status, result = self.request("GET", "/api/local-models/engine-log")
        self.assertEqual(status, 200, result)
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "error: invalid argument: --no-webui")
        self.assertEqual(result["bytes"], 24)
        self.assertNotIn("server.log", json.dumps(result))

    def test_engine_install_route_and_download_input_validation(self):
        status, result = self.request("POST", "/api/local-models/engine/install", {})
        self.assertEqual(status, 202)
        self.assertTrue(result["installed"])
        status, result = self.request("POST", "/api/local-models/download", {"model_id": "qwen25-05-q2", "source": "file"})
        self.assertEqual(status, 400)
        self.assertNotIn("path", json.dumps(result).lower())

    def test_message_edit_and_delete_routes_mutate_only_complete_turns(self):
        conversation_id, message_id = self.add_completed_turn("original", "answer")
        status, edited = self.request("PATCH", f"/api/conversations/{conversation_id}/messages/{message_id}", {"content": "corrected"})
        self.assertEqual(status, 200, edited)
        self.assertTrue(edited["resubmit_required"])
        self.assertEqual(edited["edited_content"], "corrected")
        conversation_id, message_id = self.add_completed_turn("remove", "reply")
        status, deleted = self.request("DELETE", f"/api/conversations/{conversation_id}/messages/{message_id}")
        self.assertEqual(status, 200, deleted)
        self.assertTrue(deleted["ok"])
        self.assertEqual(self.store.messages(conversation_id), [])


if __name__ == "__main__":
    unittest.main()
