"""Focused Android Agent 1.1.0 model-profile regressions.

These tests deliberately avoid the large end-to-end suite.  Vaults and the provider
below are tiny local fakes so the assertions cover persistence and routing without
network/cloud dependencies.
"""
from __future__ import annotations

import dataclasses
import http.client
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from android_agent.android_bridge import AndroidBridge
from android_agent.config import SettingsStore
from android_agent.core import AgentManager
from android_agent.models import MemoryVault, ModelProfile, ModelSelection, ModelStore
from android_agent.server import AgentHTTPServer, RequestHandler
from android_agent.store import Store


LEGACY = {
    "model_base_url": "http://127.0.0.1:1234/v1",
    "model_name": "legacy-model",
}


def profile(
    profile_id: str,
    base_url: str = "http://127.0.0.1:1234/v1",
    model: str = "model",
    *,
    api_key: str | None = None,
    context_window: int = 65536,
    max_output_tokens: int = 512,
    reasoning_enabled: bool = False,
    reasoning_level: str = "medium",
    supports_images: bool = False,
) -> dict:
    result = {
        "id": profile_id,
        "base_url": base_url,
        "model": model,
        "context_window": context_window,
        "max_output_tokens": max_output_tokens,
        "reasoning_enabled": reasoning_enabled,
        "reasoning_level": reasoning_level,
        "supports_images": supports_images,
    }
    if api_key is not None:
        result["api_key"] = api_key
    return result


class RecordingVault:
    """Small Android-keystore-shaped vault used by pure ModelStore tests."""

    credential_persistence = "android_keystore"

    def __init__(self, values: dict[str, str] | None = None, corrupt: set[str] | None = None):
        self.values = dict(values or {})
        self.corrupt = set(corrupt or ())
        self.reads: list[str] = []
        self.writes: list[tuple[str, str]] = []
        self.deletes: list[str] = []
        self.fail_write = False

    def credential_get(self, credential_id: str) -> str:
        self.reads.append(credential_id)
        if credential_id in self.corrupt:
            raise ValueError("安全读取失败")
        return self.values.get(credential_id, "")

    def credential_set(self, credential_id: str, secret: str) -> None:
        self.writes.append((credential_id, secret))
        if self.fail_write:
            raise ValueError("安全保存失败")
        self.values[credential_id] = secret

    def credential_delete(self, credential_id: str) -> None:
        self.deletes.append(credential_id)
        self.values.pop(credential_id, None)


class FailingNative:
    def status(self):
        return json.dumps({
            "ok": True,
            "selected_channel": "normal",
            "normal": {"available": True, "granted": True},
            "shizuku": {"available": False, "granted": False},
            "root": {"available": False, "granted": False},
        })

    def credentialWrite(self, profile_id, value):
        return json.dumps({"ok": False, "error": {"message": "安全保存失败"}})

    def credentialRead(self, profile_id):
        return json.dumps({"ok": False, "error": {"message": "安全读取失败"}})

    def credentialDelete(self, profile_id):
        return json.dumps({"ok": False, "error": {"message": "安全删除失败"}})


class ProviderHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        body = json.loads(raw)
        with self.server.requests_lock:
            self.server.requests.append({
                "path": self.path,
                "authorization": self.headers.get("Authorization", ""),
                "body": body,
            })
            status = self.server.response_statuses.pop(0) if self.server.response_statuses else 200
            payload_value = self.server.response_payloads.pop(0) if self.server.response_payloads else {
                "id": "local-response",
                "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "local ok"}, "finish_reason": "stop"}],
            }
            pause = bool(getattr(self.server, "pause_first_request", False) and len(self.server.requests) == 1)
        if status == 503 or pause:
            self.server.first_request.set()
            self.server.release.wait(5)
        payload = json.dumps(payload_value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)


class QuietHandler(RequestHandler):
    def log_message(self, *args):
        pass


def wait_for(predicate, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("condition did not become true")


class ModelStoreRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="model-store-regression-")
        self.root = Path(self.temporary.name)
        self.path = self.root / "models.json"
        self.vault = RecordingVault()
        self.store = ModelStore(self.path, LEGACY, self.vault)

    def tearDown(self):
        self.temporary.cleanup()

    def save_one(self, **changes):
        values = profile("one", **changes)
        self.store.replace_all({"profiles": [values], "active_model_id": "one"})

    def test_metadata_and_credentials_persist_separately_without_secret_leaks(self):
        self.save_one(model="persisted-model", api_key="secret-persisted")
        reloaded = ModelStore(self.path, LEGACY, self.vault)
        selected = reloaded.select("one")

        self.assertIsNotNone(selected)
        self.assertEqual(selected.profile.model, "persisted-model")
        self.assertEqual(selected._api_key, "secret-persisted")
        public = reloaded.public()
        exported = reloaded.export_metadata()
        encoded_path = self.path.read_text(encoding="utf-8")
        self.assertTrue(public["profiles"][0]["has_api_key"])
        self.assertNotIn("secret-persisted", encoded_path)
        self.assertNotIn("secret-persisted", json.dumps(public))
        self.assertNotIn("secret-persisted", json.dumps(exported))
        self.assertNotIn("secret-persisted", repr(selected))
        self.assertEqual(reloaded.credential_persistence, "android_keystore")
        native_restart = AndroidBridge(RecordingNative())
        native_restart._native.values.update(self.vault.values)
        restored = ModelStore(self.path, LEGACY, native_restart)
        self.assertEqual(restored.select("one")._api_key, "secret-persisted")

    def test_same_endpoint_keeps_distinct_keys_and_models(self):
        endpoint = "http://127.0.0.1:4567/v1"
        self.store.replace_all({
            "profiles": [
                profile("one", endpoint, "model-one", api_key="key-one"),
                profile("two", endpoint, "model-two", api_key="key-two"),
            ],
            "active_model_id": "one",
        })

        first = self.store.select("one")
        second = self.store.select("two")
        self.assertEqual((first.profile.model, first._api_key), ("model-one", "key-one"))
        self.assertEqual((second.profile.model, second._api_key), ("model-two", "key-two"))
        records = json.loads(self.path.read_text(encoding="utf-8"))["profiles"]
        references = {record["credential_id"] for record in records}
        self.assertEqual(len(references), 2)
        self.assertNotEqual(first.profile.id, second.profile.id)
        self.assertNotIn("key-one", self.path.read_text(encoding="utf-8"))
        self.assertNotIn("key-two", self.path.read_text(encoding="utf-8"))

    def test_blank_api_key_keeps_key_but_explicit_clear_deletes_it(self):
        self.save_one(api_key="key-to-keep")
        first_reference = json.loads(self.path.read_text(encoding="utf-8"))["profiles"][0]["credential_id"]

        # Omitted and explicitly blank API keys are non-destructive edits.
        self.store.replace_all({"profiles": [profile("one", model="updated")], "active_model_id": "one"})
        self.assertEqual(self.store.select("one")._api_key, "key-to-keep")
        self.store.replace_all({"profiles": [{**profile("one", model="updated-again"), "api_key": ""}], "active_model_id": "one"})
        self.assertEqual(self.store.select("one")._api_key, "key-to-keep")

        self.store.replace_all({"profiles": [{**profile("one"), "clear_api_key": True}], "active_model_id": "one"})
        self.assertEqual(self.store.select("one")._api_key, "")
        self.assertNotIn(first_reference, self.vault.values)
        self.assertFalse(self.store.public()["profiles"][0]["has_api_key"])
        self.assertNotIn("key-to-keep", self.path.read_text(encoding="utf-8"))

    def test_changed_endpoint_requires_new_key_rebind_or_clear(self):
        old_endpoint = "http://127.0.0.1:4101/v1"
        new_endpoint = "http://127.0.0.1:4102/v1"
        self.save_one(base_url=old_endpoint, api_key="old-key")
        changed = profile("one", new_endpoint, "new-model")

        with self.assertRaisesRegex(ValueError, "端点已改变"):
            self.store.replace_all({"profiles": [changed], "active_model_id": "one"})
        with self.assertRaisesRegex(ValueError, "测试端点"):
            self.store.draft({"profile_id": "one", "base_url": new_endpoint, "model": "new-model"})

        # Explicit rebind authorizes carrying the existing credential reference.
        rebound = {**changed, "rebind_api_key": True}
        self.store.replace_all({"profiles": [rebound], "active_model_id": "one"})
        self.assertEqual(self.store.select("one")._api_key, "old-key")

        # A supplied key is another valid changed-endpoint repair and replaces the old one.
        with_key = {**profile("one", old_endpoint, "old-model"), "api_key": "replacement-key"}
        self.store.replace_all({"profiles": [with_key], "active_model_id": "one"})
        self.assertEqual(self.store.select("one")._api_key, "replacement-key")

        # Explicit clear is the third safe choice and cannot be confused with blank.
        cleared = {**profile("one", new_endpoint, "cleared-model"), "clear_api_key": True}
        self.store.replace_all({"profiles": [cleared], "active_model_id": "one"})
        self.assertEqual(self.store.select("one")._api_key, "")

    def test_failed_vault_write_preserves_previous_metadata_and_credential(self):
        self.save_one(model="before", api_key="stable-key")
        before_json = self.path.read_text(encoding="utf-8")
        self.vault.fail_write = True

        with self.assertRaisesRegex(ValueError, "安全保存失败"):
            self.store.replace_all({
                "profiles": [profile("one", model="after", api_key="new-key")],
                "active_model_id": "one",
            })

        self.assertEqual(self.path.read_text(encoding="utf-8"), before_json)
        self.assertEqual(self.store.select("one").profile.model, "before")
        self.assertEqual(self.store.select("one")._api_key, "stable-key")
        self.assertEqual(len(self.vault.values), 1)

    def test_draft_keys_are_scoped_and_changed_endpoint_requires_explicit_choice(self):
        endpoint = "http://127.0.0.1:4101/v1"
        self.store.replace_all({
            "profiles": [
                profile("one", endpoint, "model-one", api_key="saved-one"),
                profile("two", endpoint, "model-two", api_key="saved-two"),
            ],
            "active_model_id": "one",
        })

        blank = self.store.draft({"profile_id": "one", "api_key": ""})
        self.assertEqual(blank._api_key, "saved-one")
        new_profile = self.store.draft({"id": "unsaved", "base_url": endpoint, "model": "draft", "api_key": "draft-key"})
        self.assertEqual(new_profile._api_key, "draft-key")
        self.assertEqual(self.store.select("two")._api_key, "saved-two")

        changed_endpoint = {"profile_id": "one", "base_url": "http://127.0.0.1:4102/v1", "model": "new-endpoint-model"}
        with self.assertRaisesRegex(ValueError, "测试端点"):
            self.store.draft(changed_endpoint)
        cleared = self.store.draft({**changed_endpoint, "clear_api_key": True})
        self.assertEqual(cleared._api_key, "")
        rebound = self.store.draft({**changed_endpoint, "rebind_api_key": True})
        self.assertEqual(rebound._api_key, "saved-one")
        explicit = self.store.draft({**changed_endpoint, "api_key": "new-endpoint-key"})
        self.assertEqual(explicit._api_key, "new-endpoint-key")
        self.assertEqual(self.store.select("one")._api_key, "saved-one")

    def test_corrupt_inactive_vault_does_not_block_public_or_clear_repair(self):
        self.store.replace_all({
            "profiles": [
                profile("active", model="active-model", api_key="active-key"),
                profile("inactive", model="inactive-model", api_key="inactive-key"),
            ],
            "active_model_id": "active",
        })
        records = json.loads(self.path.read_text(encoding="utf-8"))["profiles"]
        active_ref = next(record["credential_id"] for record in records if record["id"] == "active")
        inactive_ref = next(record["credential_id"] for record in records if record["id"] == "inactive")
        corrupt = RecordingVault({active_ref: "active-key"}, {inactive_ref})
        repaired = ModelStore(self.path, LEGACY, corrupt)

        before_reads = list(corrupt.reads)
        public = repaired.public()
        self.assertEqual(corrupt.reads, before_reads)
        self.assertTrue(next(item for item in public["profiles"] if item["id"] == "inactive")["has_api_key"])

        # Metadata replacement can clear the broken inactive reference without decrypting it.
        repaired.replace_all({
            "profiles": [
                profile("active", model="active-model"),
                {**profile("inactive", model="inactive-model"), "clear_api_key": True},
            ],
            "active_model_id": "active",
        })
        self.assertEqual(repaired.select("active")._api_key, "active-key")
        self.assertEqual(repaired.select("inactive")._api_key, "")
        self.assertIn(inactive_ref, corrupt.deletes)

    def test_selection_is_immutable_snapshot_after_replace_and_delete(self):
        self.save_one(model="before", api_key="before-key")
        selected = self.store.select("one")
        self.assertIsInstance(selected, ModelSelection)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            selected.profile = selected.profile
        with self.assertRaises(dataclasses.FrozenInstanceError):
            selected._api_key = "mutated"

        self.store.replace_all({"profiles": [profile("one", model="after", api_key="after-key")], "active_model_id": "one"})
        self.assertEqual(selected.profile.model, "before")
        self.assertEqual(selected._api_key, "before-key")
        self.assertEqual(self.store.select("one").profile.model, "after")
        self.store.delete("one")
        with self.assertRaisesRegex(ValueError, "不存在"):
            self.store.select("one")
        self.assertEqual(selected.profile.model, "before")
        self.assertEqual(selected._api_key, "before-key")

    def test_profile_bounds_and_reasoning_levels_are_strict(self):
        valid = profile("bounded", context_window=256, max_output_tokens=255, reasoning_enabled=True, reasoning_level="high")
        self.store.replace_all({"profiles": [valid], "active_model_id": "bounded"})
        selected = self.store.select("bounded")
        self.assertEqual(selected.profile.context_window, 256)
        self.assertEqual(selected.profile.max_output_tokens, 255)
        self.assertEqual(selected.override_reasoning("low").profile.reasoning_level, "low")
        no_reasoning = selected.override_reasoning("none")
        self.assertFalse(no_reasoning.profile.reasoning_enabled)
        self.assertEqual(no_reasoning.profile.reasoning_level, "high")
        with self.assertRaises(ValueError):
            ModelProfile.parse({**valid, "context_window": 255})
        with self.assertRaises(ValueError):
            ModelProfile.parse({**valid, "max_output_tokens": 256})
        with self.assertRaises(ValueError):
            ModelProfile.parse({**valid, "reasoning_level": "none"})
        with self.assertRaises(ValueError):
            selected.override_reasoning("invalid")

    def test_desktop_memory_vault_is_explicit_and_native_errors_do_not_fallback(self):
        desktop = ModelStore(self.root / "desktop.json", LEGACY, MemoryVault())
        self.assertEqual(desktop.credential_persistence, "memory_session")
        bridge = AndroidBridge(FailingNative())
        with self.assertRaisesRegex(ValueError, "安全保存失败"):
            bridge.credential_set("profile", "native-secret")
        with self.assertRaisesRegex(ValueError, "安全读取失败"):
            bridge.credential_get("profile")
        with self.assertRaisesRegex(ValueError, "安全删除失败"):
            bridge.credential_delete("profile")
        self.assertNotIn("_session_credentials", vars(bridge))


class ModelHTTPRouteRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="model-http-regression-")
        self.root = Path(self.temporary.name)
        self.provider = ThreadingHTTPServer(("127.0.0.1", 0), ProviderHandler)
        self.provider.daemon_threads = True
        self.provider.requests = []
        self.provider.requests_lock = threading.Lock()
        self.provider.response_statuses = []
        self.provider.response_payloads = []
        self.provider.pause_first_request = False
        self.provider.first_request = threading.Event()
        self.provider.release = threading.Event()
        self.provider_thread = threading.Thread(target=self.provider.serve_forever, daemon=True)
        self.provider_thread.start()
        self.endpoint = f"http://127.0.0.1:{self.provider.server_address[1]}/v1"
        self.settings = SettingsStore(self.root / "data/settings.json")
        self.settings.update({"disclaimer_accepted": True, "cloud_consent": True})
        self.store = Store(self.root / "data/agent.sqlite3")
        self.native = RecordingNative()
        self.manager = AgentManager(self.root, self.settings, self.store, "local-route-token", android=AndroidBridge(self.native))
        self.server = AgentHTTPServer(0, self.manager)
        self.server.RequestHandlerClass = QuietHandler
        with RequestHandler._rate_lock:
            RequestHandler._rate.clear()
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.provider.release.set()
        self.manager.shutdown()
        self.manager.executor.shutdown(wait=True, cancel_futures=True)
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(2)
        self.provider.shutdown()
        self.provider.server_close()
        self.provider_thread.join(2)
        self.temporary.cleanup()

    def request(self, method: str, path: str, body=None):
        headers = {"Authorization": "Bearer " + self.manager.api_token}
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(method, path, json.dumps(body).encode("utf-8") if body is not None else None, headers)
        response = connection.getresponse()
        raw = response.read()
        status = response.status
        connection.close()
        return status, json.loads(raw.decode("utf-8"))

    def put_profiles(self):
        values = {
            "profiles": [
                profile("one", self.endpoint, "local-model-one", api_key="route-key-one", max_output_tokens=256),
                profile("two", self.endpoint, "local-model-two", api_key="route-key-two", max_output_tokens=512, reasoning_enabled=True, reasoning_level="high"),
            ],
            "active_model_id": "one",
        }
        return values, self.request("PUT", "/api/models", values)

    def provider_requests(self):
        with self.provider.requests_lock:
            return list(self.provider.requests)

    def wait_task(self, task_id: str):
        task = wait_for(lambda: self.manager.get_task(task_id))
        self.assertTrue(task.done.wait(5), task.snapshot())
        return task

    def test_models_routes_hide_keys_and_chat_selects_profile_key_and_parameters(self):
        _, (status, put_body) = self.put_profiles()
        self.assertEqual(status, 200)
        self.assertEqual(put_body["active_model_id"], "one")
        self.assertTrue(all(item["has_api_key"] for item in put_body["profiles"]))
        self.assertNotIn("route-key-one", json.dumps(put_body))
        self.assertNotIn("route-key-two", json.dumps(put_body))

        status, get_body = self.request("GET", "/api/models")
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in get_body["profiles"]], ["one", "two"])
        self.assertNotIn("route-key-one", json.dumps(get_body))
        self.assertNotIn("route-key-two", json.dumps(get_body))
        self.assertNotIn("route-key-one", self.manager.models.path.read_text(encoding="utf-8"))
        self.assertNotIn("route-key-two", json.dumps(self.manager.models.export_metadata()))
        self.assertNotIn("route-key-two", json.dumps(self.manager.maintenance.export_config()))

        self.settings.update({"model_enabled": True})
        status, first = self.request("POST", "/api/chat", {"message": "first", "model_profile_id": "two", "reasoning_level": "low"})
        self.assertEqual(status, 202)
        task = self.wait_task(first["task"]["id"])
        self.assertEqual(task.state, "succeeded", task.snapshot())
        request = wait_for(lambda: self.provider_requests()[-1] if self.provider_requests() else None)
        self.assertEqual(request["path"], "/v1/chat/completions")
        self.assertEqual(request["authorization"], "Bearer route-key-two")
        payload = request["body"]
        self.assertEqual(payload["model"], "local-model-two")
        self.assertEqual(payload["max_completion_tokens"], 512)
        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertNotIn("route-key-two", json.dumps(payload))

        status, second = self.request("POST", "/api/chat", {"message": "second", "model_profile_id": "one", "reasoning_level": "none"})
        self.assertEqual(status, 202)
        task = self.wait_task(second["task"]["id"])
        self.assertEqual(task.state, "succeeded", task.snapshot())
        request = wait_for(lambda: self.provider_requests()[-1] if len(self.provider_requests()) >= 2 else None)
        self.assertEqual(request["authorization"], "Bearer route-key-one")
        payload = request["body"]
        self.assertEqual(payload["model"], "local-model-one")
        self.assertEqual(payload["max_tokens"], 256)
        self.assertNotIn("max_completion_tokens", payload)
        self.assertNotIn("reasoning_effort", payload)
        self.assertEqual(task.snapshot()["model_profile_id"], "one")

    def test_enabled_settings_rejection_does_not_write_supplied_key(self):
        before = self.settings.snapshot()
        status, body = self.request("POST", "/api/settings", {
            "model_base_url": self.endpoint,
            "model_name": "atomic-model",
            "api_key": "must-not-be-written",
            "model_enabled": True,
            "cloud_consent": False,
        })
        self.assertEqual(status, 400, body)
        self.assertEqual(self.native.values, {})
        after = self.settings.snapshot()
        self.assertEqual(after["model_base_url"], before["model_base_url"])
        self.assertEqual(after["model_name"], before["model_name"])
        self.assertFalse(after["model_enabled"])
        self.assertFalse(self.manager.models.public()["profiles"][0]["has_api_key"])

    def test_withdrawing_consent_alone_disables_remote_model(self):
        self.settings.update({"model_name": "remote", "model_enabled": True, "cloud_consent": True})
        status, body = self.request("POST", "/api/settings", {"cloud_consent": False})
        self.assertEqual(status, 200, body)
        self.assertFalse(body["cloud_consent"])
        self.assertFalse(body["model_enabled"])
        self.assertFalse(self.settings.snapshot()["cloud_consent"])
        self.assertFalse(self.settings.snapshot()["model_enabled"])

    def test_revocation_stops_inflight_chat_before_dispatch_or_next_request(self):
        _, (status, saved) = self.put_profiles()
        self.assertEqual(status, 200, saved)
        self.settings.update({"model_enabled": True, "cloud_consent": True})
        self.provider.pause_first_request = True
        tool_call = {"id": "call_env", "type": "function", "function": {"name": "environment_status", "arguments": "{}"}}
        self.provider.response_payloads.append({"id": "first", "object": "chat.completion", "choices": [{"index": 0, "message": {"role": "assistant", "content": "", "tool_calls": [tool_call]}, "finish_reason": "tool_calls"}]})
        status, result = self.request("POST", "/api/chat", {"message": "revoke me", "model_profile_id": "one"})
        self.assertEqual(status, 202, result)
        task = wait_for(lambda: self.manager.get_task(result["task"]["id"]))
        self.assertTrue(self.provider.first_request.wait(3))
        status, settings_body = self.request("POST", "/api/settings", {"cloud_consent": False})
        self.assertEqual(status, 200, settings_body)
        self.provider.release.set()
        self.assertTrue(task.done.wait(5), task.snapshot())
        self.assertEqual(task.state, "cancelled", task.snapshot())
        self.assertEqual(len(self.provider_requests()), 1)

    def test_v2_export_import_never_restores_secrets_or_vault_references(self):
        _, (status, _) = self.put_profiles()
        self.assertEqual(status, 200)
        exported = self.manager.maintenance.export_config()
        encoded = json.dumps(exported)
        self.assertEqual(exported["version"], 2)
        self.assertNotIn("route-key-one", encoded)
        self.assertNotIn("route-key-two", encoded)
        self.assertTrue(all("id" not in item and "credential_id" not in item for item in exported["model_profiles"]))

        imported = json.loads(json.dumps(exported))
        imported["model_profiles"][0]["api_key"] = "untrusted-import-key"
        imported["model_profiles"][0]["credential_id"] = "untrusted-vault-reference"
        self.manager.maintenance.import_config(imported)
        public = self.manager.models.public()
        added = next(item for item in public["profiles"] if item["model"] == "local-model-one" and item["id"] != "one")
        self.assertFalse(added["has_api_key"])
        self.assertEqual(self.manager.models.select(added["id"])._api_key, "")
        new_export = self.manager.maintenance.export_config()
        self.assertNotIn("untrusted-import-key", json.dumps(new_export))
        self.assertNotIn("untrusted-vault-reference", json.dumps(new_export))
        self.assertNotIn("untrusted-import-key", self.manager.models.path.read_text(encoding="utf-8"))

    def test_running_chat_keeps_selection_through_retry_replacement_and_deletion(self):
        _, (status, _) = self.put_profiles()
        self.assertEqual(status, 200)
        self.settings.update({"model_enabled": True})
        with self.provider.requests_lock:
            self.provider.response_statuses[:] = [503]
        status, result = self.request("POST", "/api/chat", {
            "message": "retry snapshot",
            "model_profile_id": "two",
            "reasoning_level": "low",
        })
        self.assertEqual(status, 202)
        task_id = result["task"]["id"]
        self.assertTrue(self.provider.first_request.wait(3))
        first_request = self.provider_requests()[0]
        self.assertEqual(first_request["authorization"], "Bearer route-key-two")

        replacement_endpoint = self.endpoint + "/replacement"
        self.manager.save_models({
            "profiles": [profile("two", replacement_endpoint, "replacement-model", api_key="replacement-key", max_output_tokens=333)],
            "active_model_id": "two",
        })
        self.manager.models.delete("two")
        self.assertEqual(self.manager.models.public(), {"profiles": [], "active_model_id": None})
        self.provider.release.set()

        task = self.wait_task(task_id)
        self.assertEqual(task.state, "succeeded", task.snapshot())
        requests = self.provider_requests()
        self.assertEqual(len(requests), 2)
        for request in requests:
            self.assertEqual(request["path"], "/v1/chat/completions")
            self.assertEqual(request["authorization"], "Bearer route-key-two")
            payload = request["body"]
            self.assertEqual(payload["model"], "local-model-two")
            self.assertEqual(payload["max_completion_tokens"], 512)
            self.assertEqual(payload["reasoning_effort"], "low")
            self.assertNotIn("replacement-key", json.dumps(payload))
        self.assertEqual(task.snapshot()["model_profile_id"], "two")


class RecordingNative(RecordingVault):
    """The manager uses the Java JSON credential contract, not direct vault methods."""

    def credentialWrite(self, credential_id, secret):
        self.credential_set(credential_id, secret)
        return json.dumps({"ok": True})

    def credentialRead(self, credential_id):
        try:
            return json.dumps({"ok": True, "value": self.credential_get(credential_id)})
        except ValueError as exc:
            return json.dumps({"ok": False, "error": {"message": str(exc)}})

    def credentialDelete(self, credential_id):
        self.credential_delete(credential_id)
        return json.dumps({"ok": True})

    def status(self):
        return json.dumps({
            "ok": True,
            "selected_channel": "normal",
            "normal": {"available": True, "granted": True},
            "shizuku": {"available": False, "granted": False},
            "root": {"available": False, "granted": False},
        })


if __name__ == "__main__":
    unittest.main(verbosity=2)
