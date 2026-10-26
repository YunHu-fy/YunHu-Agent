"""Acceleration gating: local-only authority, default off, third-party locked.

The hardware toggles (CPU/GPU/NPU plus Anima low-memory) may only be enabled
while the bundled local engine owns the model configuration. Every other case
must stay off and must be rejected by the settings endpoint.
"""
from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from android_agent.android_bridge import AndroidBridge
from android_agent.config import ACCELERATION_KEYS, DEFAULT_SETTINGS, SettingsStore, acceleration_scope, apply_acceleration_policy
from android_agent.core import AgentManager
from android_agent.server import AgentHTTPServer, RequestHandler
from android_agent.store import Store

REMOTE_URL = "https://api.example.com/v1"
LOCAL_URL = "http://127.0.0.1:18286/v1"


class MockNative:
    def status(self):
        return json.dumps({"ok": True, "selected_channel": "normal",
                           **{channel: {"available": True, "granted": True} for channel in ("normal", "shizuku", "root")}})

    def runtimeStatus(self):
        return '{"ok":true,"ready":true,"deployed":true,"supported":true,"installed":true}'

    def localModelBackends(self):
        return json.dumps({"ok": True, "engine": "llama.cpp",
                           "probe": {"available": True, "flags": [], "devices": [],
                                     "cpu": {"available": True},
                                     "gpu": {"available": False, "device": None},
                                     "npu": {"available": False, "device": None}, "error": None}})


class QuietHandler(RequestHandler):
    def log_message(self, *args):
        pass


class AccelerationPolicyTests(unittest.TestCase):
    def test_defaults_are_off_for_every_toggle(self):
        with tempfile.TemporaryDirectory(prefix="accel-default-") as directory:
            settings = SettingsStore(Path(directory) / "settings.json")
            snapshot = settings.snapshot()
            for key in ACCELERATION_KEYS:
                self.assertIn(key, DEFAULT_SETTINGS)
                self.assertIs(snapshot[key], False)

    def test_remote_profile_never_keeps_acceleration_flags(self):
        values = {"model_base_url": REMOTE_URL, "local_model_active": False,
                  "local_cpu_acceleration_enabled": True, "local_gpu_acceleration_enabled": True,
                  "local_npu_acceleration_enabled": True, "anima_low_memory_enabled": True}
        self.assertFalse(acceleration_scope(values))
        cleared = apply_acceleration_policy(values)
        for key in ACCELERATION_KEYS:
            self.assertIs(cleared[key], False)

    def test_local_endpoint_and_active_flag_grant_scope(self):
        self.assertTrue(acceleration_scope({"model_base_url": LOCAL_URL}))
        self.assertTrue(acceleration_scope({"model_base_url": REMOTE_URL, "local_model_active": True}))
        self.assertFalse(acceleration_scope({"model_base_url": "http://127.0.0.1:1234/v1"}))
        self.assertFalse(acceleration_scope({"model_base_url": "http://127.0.0.1:18286/v1/chat"}))

    def test_gpu_and_npu_cannot_be_enabled_together(self):
        result = apply_acceleration_policy({"model_base_url": LOCAL_URL,
                                            "local_gpu_acceleration_enabled": True,
                                            "local_npu_acceleration_enabled": True})
        self.assertTrue(result["local_gpu_acceleration_enabled"])
        self.assertFalse(result["local_npu_acceleration_enabled"])


class AccelerationSettingsAPITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="accel-api-")
        self.root = Path(self.temporary.name)
        self.settings = SettingsStore(self.root / "data/settings.json")
        self.settings.update({"disclaimer_accepted": True, "model_base_url": REMOTE_URL})
        self.manager = AgentManager(self.root, self.settings, Store(self.root / "data/agent.sqlite3"),
                                    "accel-test-token", android=AndroidBridge(MockNative()))
        self.server = AgentHTTPServer(0, self.manager)
        self.server.RequestHandlerClass = QuietHandler
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        with RequestHandler._rate_lock:
            RequestHandler._rate.clear()

    def tearDown(self):
        self.manager.shutdown()
        self.manager.executor.shutdown(wait=True, cancel_futures=True)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.temporary.cleanup()

    def request(self, method, path, body=None):
        headers = {"Authorization": "Bearer " + self.manager.api_token}
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=4)
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        payload = response.read().decode("utf-8")
        status = response.status
        connection.close()
        try:
            return status, json.loads(payload)
        except ValueError:
            return status, payload

    def test_third_party_profile_rejects_every_toggle(self):
        for key in ACCELERATION_KEYS:
            with self.subTest(key=key):
                status, payload = self.request("POST", "/api/settings", {key: True})
                self.assertEqual(status, 400, payload)
                self.assertIn("仅支持本地模型", json.dumps(payload, ensure_ascii=False))
                self.assertFalse(self.settings.snapshot()[key])

    def test_remote_switch_clears_previously_enabled_toggles(self):
        self.settings.update({"model_base_url": LOCAL_URL, "local_model_active": True,
                              "local_cpu_acceleration_enabled": True, "local_gpu_acceleration_enabled": True})
        self.assertTrue(self.settings.snapshot()["local_gpu_acceleration_enabled"])
        saved = self.settings.update({"model_base_url": REMOTE_URL, "local_model_active": False})
        for key in ACCELERATION_KEYS:
            self.assertIs(saved[key], False)

    def test_local_scope_allows_cpu_gpu_and_reports_backends(self):
        self.settings.update({"model_base_url": LOCAL_URL, "local_model_active": True})
        status, payload = self.request("POST", "/api/settings",
                                       {"local_cpu_acceleration_enabled": True, "local_gpu_acceleration_enabled": True})
        self.assertEqual(status, 200, payload)
        settings = payload.get("settings", payload)
        self.assertTrue(settings["local_cpu_acceleration_enabled"])
        self.assertTrue(settings["local_gpu_acceleration_enabled"])
        status, payload = self.request("POST", "/api/settings",
                                       {"local_cpu_acceleration_enabled": True, "local_npu_acceleration_enabled": True})
        self.assertEqual(status, 400, payload)
        status, payload = self.request("GET", "/api/local-models/backends")
        self.assertEqual(status, 200, payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["engine"], "llama.cpp")
        self.assertIn("gpu", payload["probe"])
        self.assertEqual(payload["selected"], {"cpu": True, "gpu": True, "npu": False, "low_memory": False})

    def test_low_memory_stays_off_until_a_local_model_is_selected(self):
        self.assertFalse(self.settings.snapshot()["anima_low_memory_enabled"])
        status, _ = self.request("POST", "/api/settings", {"anima_low_memory_enabled": True})
        self.assertEqual(status, 400)
        self.settings.update({"model_base_url": LOCAL_URL, "local_model_active": True})
        status, payload = self.request("POST", "/api/settings", {"anima_low_memory_enabled": True})
        self.assertEqual(status, 200, payload)
        self.assertTrue(self.settings.snapshot()["anima_low_memory_enabled"])


if __name__ == "__main__":
    unittest.main()
