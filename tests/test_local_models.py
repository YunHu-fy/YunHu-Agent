from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
import threading
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from android_agent.android_bridge import AndroidBridge
from android_agent.config import SettingsStore
from android_agent.core import AgentManager
from android_agent.local_models import CATALOG, LocalModelManager, _allowed_host, effective_context_size
from android_agent.store import Store


class FakeNative:
    def __init__(self):
        self.local_status = {"ok": True, "installed": True, "running": False, "healthy": False,
                            "active_model_id": None, "port": None}
        self.local_model_start_args = None
        self.local_model_start_ex_args = None
        self.server_log = ""
        self.returned_port = None
        self.backends = {"available": True, "flags": [], "devices": [],
                         "cpu": {"available": True}, "gpu": {"available": False, "device": None},
                         "npu": {"available": False, "device": None}, "error": None}

    def status(self):
        return json.dumps({"ok": True, "selected_channel": "normal", "normal": {"available": True, "granted": True},
                           "shizuku": {"available": False, "granted": False}, "root": {"available": False, "granted": False}})

    def uiPreferences(self, value):
        return "{}"

    def localModelStatus(self):
        return json.dumps(self.local_status)

    def localModelStart(self, path, alias, port, context, threads):
        self.local_model_start_args = (path, alias, port, context, threads)
        bound = port if self.returned_port is None else self.returned_port
        self.local_status.update(running=True, healthy=True, active_model_id=alias, port=bound,
                                 context_size=context, threads=threads)
        return json.dumps({"ok": True, **self.local_status, "port": bound})

    def localModelStartEx(self, path, alias, port, context, threads, options_json):
        self.local_model_start_ex_args = (path, alias, port, context, threads, json.loads(options_json))
        bound = port if self.returned_port is None else self.returned_port
        self.local_status.update(running=True, healthy=True, active_model_id=alias, port=bound,
                                 context_size=context, threads=threads)
        return json.dumps({"ok": True, **self.local_status, "port": bound})

    def localModelBackends(self):
        return json.dumps({"ok": True, "engine": "llama.cpp", "probe": dict(self.backends)})

    def localModelStop(self):
        self.local_status.update(running=False, healthy=False, active_model_id=None, port=None)
        return json.dumps({"ok": True, **self.local_status})

    def localModelInstall(self):
        return json.dumps({"ok": True, "installed": True, "installing": False})

    def localModelLog(self):
        return json.dumps({"ok": True, "path": "/private/server.log", "bytes": len(self.server_log), "text": self.server_log})


class LocalModelManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="local-models-")
        self.root = Path(self.temporary.name) / "models"
        self.native = FakeNative()
        self.android = AndroidBridge(self.native)
        self.manager = LocalModelManager(self.root, self.android)

    def tearDown(self):
        self.temporary.cleanup()

    def test_pinned_catalog_has_ten_entries_and_only_expected_download_hosts(self):
        self.assertEqual(len(CATALOG), 10)
        public = self.manager.catalog()
        self.assertEqual(len(public), 10)
        self.assertTrue(all(item["sha256"] and item["revision"] for item in public))
        self.assertTrue(_allowed_host("huggingface.co"))
        self.assertTrue(_allowed_host("hf-mirror.com"))
        self.assertTrue(_allowed_host("cas-bridge.xethub.hf.co"))
        self.assertFalse(_allowed_host("attacker-hf.co"))
        self.assertFalse(_allowed_host("example.com"))
        self.assertFalse(_allowed_host("127.0.0.1"))

    def test_status_does_not_disclose_private_model_file_paths(self):
        result = self.manager.list()
        self.assertEqual(len(result["models"]), 10)
        for model in result["models"]:
            self.assertNotIn("path", model)
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_only_fixed_catalog_ids_and_sources_can_be_downloaded(self):
        for model_id, source in (("../../secret", "mirror"), (next(iter(CATALOG)), "file")):
            with self.assertRaises(ValueError):
                self.manager.download(model_id, source)

    def test_local_activation_requires_exact_hash_and_uses_private_catalog_file(self):
        model_id = next(iter(CATALOG))
        original = CATALOG[model_id]
        payload = b"GGUF-test-model"
        CATALOG[model_id] = {**original, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            target = self.root / (model_id + ".gguf")
            target.write_bytes(payload)
            result = self.manager.activate(model_id)
            self.assertTrue(result["ok"])
            self.assertEqual(result["engine"]["active_model_id"], model_id)
            self.assertTrue(self.native.local_status["healthy"])
            self.assertEqual(self.native.local_model_start_args[3:], (4096, 4))
            target.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "完整性校验"):
                self.manager.activate(model_id)
        finally:
            CATALOG[model_id] = original

    def test_context_and_thread_bounds_and_low_memory_cap_use_supported_context_argument(self):
        self.assertEqual(effective_context_size(512), 512)
        self.assertEqual(effective_context_size(8192), 8192)
        self.assertEqual(effective_context_size(8192, True), 2048)
        for invalid in (511, 8193, True, 512.0):
            with self.subTest(context=invalid), self.assertRaises(ValueError):
                effective_context_size(invalid)
        with self.assertRaises(ValueError):
            effective_context_size(2048, 1)

        model_id = next(iter(CATALOG))
        original = CATALOG[model_id]
        payload = b"GGUF-bounds-model"
        CATALOG[model_id] = {**original, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / (model_id + ".gguf")).write_bytes(payload)
            result = self.manager.activate(model_id, context_size=8192, threads=16, low_memory=True)
            self.assertEqual(self.native.local_model_start_ex_args[3:5], (2048, 16))
            self.assertEqual(self.native.local_model_start_ex_args[5], {"backend": {"cpu": False, "gpu": False, "npu": False, "low_memory": True}})
            self.assertIsNone(self.native.local_model_start_args)
            self.assertEqual(result["context_size"], 2048)
            with self.assertRaisesRegex(ValueError, "上下文长度"):
                self.manager.activate(model_id, context_size=8193)
            with self.assertRaisesRegex(ValueError, "线程数"):
                self.manager.activate(model_id, threads=17)
        finally:
            CATALOG[model_id] = original

    def test_cancel_during_hashing_prevents_atomic_publication(self):
        model_id = next(iter(CATALOG))
        original = CATALOG[model_id]
        payload = b"GGUF-cancellation-test"
        item = {**original, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        CATALOG[model_id] = item
        job_id = "verify-cancel"
        part = self.root / (model_id + ".gguf.part")
        target = self.root / (model_id + ".gguf")
        self.root.mkdir(parents=True, exist_ok=True)
        entered_hash, resume_hash = threading.Event(), threading.Event()
        cancel = threading.Event()
        self.manager._downloads[job_id] = {"id": job_id, "model_id": model_id, "state": "queued", "received": 0, "total": len(payload), "progress": 0, "source": "mirror", "error": None, "updated_at": 0}
        self.manager._cancel[job_id] = cancel
        class Response:
            status = 200
            headers = {}
            def __init__(self): self.sent = False
            def geturl(self): return "https://hf-mirror.com/file"
            def read(self, _size=-1):
                if self.sent: return b""
                self.sent = True
                return payload
            def close(self): pass
            def __enter__(self): return self
            def __exit__(self, *_args): self.close()
        class Opener:
            def open(self, *_args, **_kwargs): return Response()
        def paused_hash(_path):
            entered_hash.set()
            self.assertTrue(resume_hash.wait(3))
            return item["sha256"]
        worker = threading.Thread(target=self.manager._download_worker, args=(job_id, target, item, "mirror", cancel))
        try:
            with patch("android_agent.local_models.urllib.request.build_opener", return_value=Opener()), patch("android_agent.local_models._sha256", side_effect=paused_hash):
                worker.start()
                self.assertTrue(entered_hash.wait(3))
                self.assertTrue(self.manager.cancel_download(job_id))
                resume_hash.set()
                worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(self.manager._downloads[job_id]["state"], "cancelled")
            self.assertFalse(target.exists())
        finally:
            CATALOG[model_id] = original

    def test_delete_refuses_active_or_downloading_model(self):
        model_id = next(iter(CATALOG))
        self.native.local_status.update(running=True, active_model_id=model_id)
        with self.assertRaisesRegex(RuntimeError, "先停止"):
            self.manager.delete(model_id)
        self.native.local_status.update(running=False, active_model_id=None)
        self.manager._downloads["test-job"] = {"id": "test-job", "model_id": model_id, "state": "downloading"}
        with self.assertRaisesRegex(RuntimeError, "下载正在进行"):
            self.manager.delete(model_id)


    def test_activation_advertises_the_port_the_engine_actually_bound(self):
        model_id = next(iter(CATALOG))
        original = CATALOG[model_id]
        payload = b"GGUF-rebound-model"
        CATALOG[model_id] = {**original, "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / (model_id + ".gguf")).write_bytes(payload)
            self.native.returned_port = 18287
            result = self.manager.activate(model_id, port=18286)
            self.assertEqual(self.native.local_model_start_args[2], 18286)
            self.assertEqual(result["port"], 18287)
            self.assertEqual(result["base_url"], "http://127.0.0.1:18287/v1")
            self.assertEqual(result["engine"]["port"], 18287)
        finally:
            CATALOG[model_id] = original

    def test_engine_log_returns_the_native_tail(self):
        self.native.server_log = "llama_model_load: error loading model"
        result = self.manager.engine_log()
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "llama_model_load: error loading model")

class LocalProfileConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="local-profile-")
        self.root = Path(self.temporary.name)
        self.settings = SettingsStore(self.root / "data" / "settings.json")
        self.settings.update({"cloud_consent": True})
        self.native = FakeNative()
        self.manager = AgentManager(self.root, self.settings, Store(self.root / "data" / "db.sqlite3"),
                                    "local-profile-test-token", android=AndroidBridge(self.native))
        self.activation_calls = []
        self.backend_calls = []
        def activate_local_model(model_id, port=18286, context_size=4096, threads=4, backend=None):
            actual_context = effective_context_size(context_size, bool((backend or {}).get("low_memory")))
            self.activation_calls.append((model_id, port, context_size, threads))
            self.backend_calls.append(dict(backend or {}))
            self.native.local_status.update(running=True, healthy=True, active_model_id=model_id, port=port,
                                            context_size=actual_context, threads=threads)
            return {"ok": True, "model_id": model_id, "base_url": f"http://127.0.0.1:{port}/v1",
                    "model": model_id, "context_size": actual_context, "threads": threads, "backend": "cpu"}
        self.manager.local_models.activate = activate_local_model

    def tearDown(self):
        self.manager.shutdown()
        self.temporary.cleanup()

    def test_pending_activation_persists_profile_only_after_healthy_poll(self):
        model_id = next(iter(CATALOG))
        self.manager._pending_local_model = (model_id, 18286)
        early = self.manager.sync_local_model_profile({"running": True, "healthy": False, "active_model_id": model_id, "port": 18286})
        self.assertFalse(early["ready"])
        self.assertNotIn("local-" + model_id, {item["id"] for item in self.manager.models.public()["profiles"]})
        self.native.local_status.update(running=True, healthy=True, active_model_id=model_id, port=18286)
        ready = self.manager.sync_local_model_profile(self.native.local_status)
        self.assertTrue(ready["ready"])
        self.assertEqual(self.manager.models.active_model_id, "local-" + model_id)
        self.assertTrue(self.settings.snapshot()["model_enabled"])
        self.assertTrue(self.settings.snapshot()["local_model_active"])
        self.assertTrue(self.settings.snapshot()["cloud_consent"])
        profile = next(item for item in ready["models"]["profiles"] if item["id"] == "local-" + model_id)
        self.assertEqual(profile["context_window"], 4096)
        self.assertIsNone(self.manager._pending_local_model)

    def test_configure_forwards_settings_and_profile_uses_effective_context(self):
        model_id = next(iter(CATALOG))
        # Acceleration belongs to a local profile, so the scope flag is set first;
        # the settings endpoint rejects toggles outside that scope by design.
        self.settings.update({"local_model_active": True})
        self.settings.update({"local_model_context": 8192, "local_model_threads": 12, "anima_low_memory_enabled": True})
        result = self.manager.configure_local_model(model_id)
        self.assertTrue(result["ready"])
        self.assertEqual(self.activation_calls, [(model_id, 18286, 2048, 12)])
        self.assertEqual(self.backend_calls, [{"cpu": False, "gpu": False, "npu": False, "low_memory": True}])
        profile = next(item for item in result["models"]["profiles"] if item["id"] == "local-" + model_id)
        self.assertEqual(profile["context_window"], 2048)
        self.assertEqual(result["engine"]["context_size"], 2048)
        self.assertEqual(result["engine"]["threads"], 12)

    def test_unrequested_running_alias_cannot_replace_active_profile(self):
        model_id = next(iter(CATALOG))
        self.native.local_status.update(running=True, healthy=True, active_model_id=model_id, port=18286)
        self.assertFalse(self.manager.sync_local_model_profile(self.native.local_status)["ready"])
        self.assertNotIn("local-" + model_id, {item["id"] for item in self.manager.models.public()["profiles"]})

    def test_deleting_local_model_also_reconciles_saved_profile_and_settings(self):
        model_id = next(iter(CATALOG))
        self.manager._pending_local_model = (model_id, 18286)
        self.native.local_status.update(running=True, healthy=True, active_model_id=model_id, port=18286)
        self.assertTrue(self.manager.sync_local_model_profile(self.native.local_status)["ready"])
        self.native.local_status.update(running=False, healthy=False, active_model_id=None, port=None)
        result = self.manager.delete_local_model(model_id)
        self.assertTrue(result["ok"])
        self.assertNotIn("local-" + model_id, {item["id"] for item in result["models"]["profiles"]})
        settings = self.settings.snapshot()
        self.assertFalse(settings["local_model_active"])
        self.assertFalse(settings["model_enabled"])
        self.assertEqual(settings["model_name"], "")
        self.assertIsNone(self.manager._pending_local_model)


    def test_configure_keeps_the_profile_ready_when_the_engine_rebinds_the_port(self):
        model_id = next(iter(CATALOG))

        def activate_local_model(model_id, port=18286, context_size=4096, threads=4, backend=None):
            bound = 18287
            self.native.local_status.update(running=True, healthy=True, active_model_id=model_id, port=bound,
                                            context_size=context_size, threads=threads)
            return {"ok": True, "model_id": model_id, "base_url": f"http://127.0.0.1:{bound}/v1",
                    "model": model_id, "context_size": context_size, "threads": threads, "backend": "cpu", "port": bound}

        self.manager.local_models.activate = activate_local_model
        result = self.manager.configure_local_model(model_id)
        self.assertTrue(result["ready"])
        self.assertEqual(result["base_url"], "http://127.0.0.1:18287/v1")
        self.assertEqual(result["port"], 18287)
        profile = next(item for item in result["models"]["profiles"] if item["id"] == "local-" + model_id)
        self.assertEqual(profile["base_url"], "http://127.0.0.1:18287/v1")

    def test_engine_log_payload_is_bounded_for_the_ui(self):
        self.native.server_log = "a" * 70000 + "error: invalid argument"
        result = self.manager.local_model_engine_log()
        self.assertTrue(result["ok"])
        self.assertLessEqual(len(result["text"]), 65536)
        self.assertTrue(result["text"].endswith("error: invalid argument"))


if __name__ == "__main__":
    unittest.main()
