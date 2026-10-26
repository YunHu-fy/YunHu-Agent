"""Focused 1.3.0 display-preference persistence and backend isolation tests."""
from __future__ import annotations

import copy
import http.client
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from android_agent.android_bridge import AndroidBridge
from android_agent.config import DEFAULT_SETTINGS, SettingsStore
from android_agent.core import AgentManager, SYSTEM_PROMPT
from android_agent.server import AgentHTTPServer, RequestHandler
from android_agent.store import Store


DEFAULT_UI = {"ui_theme": "system", "ui_font_size": "md", "ui_language": "zh"}
CUSTOM_UI = {"ui_theme": "dark", "ui_font_size": "xl", "ui_language": "en"}


class RecordingNative:
    """Only display and credential bridge contracts; never runs device commands."""

    def __init__(self, credentials=None):
        self.preferences = []
        self.raw_preferences = []
        self.credentials = credentials if credentials is not None else {}

    def status(self):
        return json.dumps({"ok": True, "supported": True, "selected_channel": "normal",
                           "normal": {"available": True, "granted": True},
                           "shizuku": {"available": False, "granted": False},
                           "root": {"available": False, "granted": False}})

    def appUiPreferences(self, payload):
        self.raw_preferences.append(payload)
        self.preferences.append(json.loads(payload))
        return json.dumps({"ok": True, "supported": True})

    def credentialRead(self, reference):
        return json.dumps({"ok": True, "value": self.credentials.get(reference, "")})

    def credentialWrite(self, reference, value):
        self.credentials[reference] = value
        return json.dumps({"ok": True})

    def credentialDelete(self, reference):
        self.credentials.pop(reference, None)
        return json.dumps({"ok": True})


class QuietHandler(RequestHandler):
    def log_message(self, *args):
        pass


class PreferenceModelHandler(BaseHTTPRequestHandler):
    """Capture real completion payloads, blocking round one during a UI save."""

    def log_message(self, *args):
        pass

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        request = {"path": self.path, "authorization": self.headers.get("Authorization"),
                   "body": payload}
        with self.server.capture_lock:
            self.server.captures.append(request)
            number = len(self.server.captures)
        if number == 1:
            self.server.arrived.set()
            if not self.server.release.wait(8):
                self.send_error(504)
                return
            message = {"role": "assistant", "content": "第一阶段 / keep literal; ",
                       "tool_calls": [{"id": "ui-round-one", "type": "function", "function": {
                           "name": "environment_status", "arguments": "{}"}}]}
            reason = "tool_calls"
        else:
            message = {"role": "assistant", "content": "保留中文 / English literal final"}
            reason = "stop"
        data = json.dumps({"choices": [{"index": 0, "message": message,
                                       "finish_reason": reason}]}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(data)


class UiPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="ui-preferences-")
        self.root = Path(self.temporary.name)
        self.settings = SettingsStore(self.root / "data/settings.json")
        self.managers = []
        self.servers = []
        self.providers = []

    def tearDown(self):
        for provider, _thread in self.providers:
            provider.release.set()
        for server, thread in reversed(self.servers):
            server.shutdown()
            server.server_close()
            thread.join(2)
        for manager in reversed(self.managers):
            manager.shutdown()
            manager.executor.shutdown(wait=True, cancel_futures=True)
        for provider, thread in self.providers:
            provider.shutdown()
            provider.server_close()
            thread.join(2)
        self.temporary.cleanup()

    @staticmethod
    def ui(values):
        return {key: values[key] for key in DEFAULT_UI}

    def start_manager(self, *, settings=None, native=None):
        native = native if native is not None else RecordingNative()
        manager = AgentManager(self.root, settings or self.settings,
                               Store(self.root / "data/agent.sqlite3"),
                               "ui-local-token", AndroidBridge(native))
        self.managers.append(manager)
        return manager, native

    def start_http(self, manager):
        server = AgentHTTPServer(0, manager)
        server.RequestHandlerClass = QuietHandler
        with RequestHandler._rate_lock:
            RequestHandler._rate.clear()
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.servers.append((server, thread))
        return server.server_address[1]

    def request(self, port, method, path, body=None, *, token="ui-local-token"):
        headers = {}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            connection.request(method, path, json.dumps(body).encode("utf-8") if body is not None else None,
                               headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read().decode("utf-8"))
        finally:
            connection.close()

    def configure_model(self, manager, endpoint="http://127.0.0.1:1234/v1"):
        manager.save_models({"profiles": [{"id": "ui-model", "base_url": endpoint,
                             "model": "unchanged-model", "api_key": "ui-private-model-key",
                             "context_window": 65536, "max_output_tokens": 1024,
                             "reasoning_enabled": True, "reasoning_level": "high"}],
                             "active_model_id": "ui-model"})

    def test_old_settings_migrate_display_defaults_without_losing_other_values(self):
        path = self.root / "legacy.json"
        legacy = {key: copy.deepcopy(value) for key, value in DEFAULT_SETTINGS.items()
                  if key not in DEFAULT_UI}
        legacy.update({"blacklist": ["substring:keep-this"], "command_timeout_seconds": 19,
                       "state_refresh_seconds": 17})
        path.write_text(json.dumps(legacy), encoding="utf-8")
        migrated = SettingsStore(path)
        self.assertEqual(self.ui(migrated.snapshot()), DEFAULT_UI)
        self.assertEqual({key: value for key, value in migrated.snapshot().items() if key not in DEFAULT_UI},
                         legacy)
        disk = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(self.ui(disk), DEFAULT_UI)
        self.assertEqual(SettingsStore(path).snapshot(), migrated.snapshot())
        # Invalid persisted display options fall back independently, not to an invalid enum.
        path.write_text(json.dumps({**legacy, "ui_theme": "sepia", "ui_font_size": 1,
                                    "ui_language": "en"}), encoding="utf-8")
        self.assertEqual(self.ui(SettingsStore(path).snapshot()), {**DEFAULT_UI, "ui_language": "en"})

    def test_invalid_types_and_enums_preserve_all_settings_atomically(self):
        before = self.settings.snapshot()
        original = self.settings.path.read_bytes()
        bad_values = {"ui_theme": [None, True, 1, [], {}, "", "auto", "Dark"],
                      "ui_font_size": [None, False, 1.5, [], {}, "", "medium", "MD"],
                      "ui_language": [None, True, 0, [], {}, "", "fr", "EN"]}
        for key, values in bad_values.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    with self.assertRaises(ValueError):
                        self.settings.update({"blacklist": ["should-not-save"], key: value})
                    self.assertEqual(self.settings.snapshot(), before)
                    self.assertEqual(self.settings.path.read_bytes(), original)
        self.assertEqual(SettingsStore(self.settings.path).snapshot(), before)

    def test_all_allowed_options_persist_and_restart_with_independent_fields(self):
        allowed = {"ui_theme": ("system", "light", "dark"),
                   "ui_font_size": ("xs", "sm", "md", "lg", "xl"),
                   "ui_language": ("zh", "en")}
        for key, values in allowed.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    before = self.settings.snapshot()
                    result = self.settings.update({key: value})
                    expected = {**before, key: value}
                    self.assertEqual(result, expected)
                    self.assertEqual(SettingsStore(self.settings.path).snapshot(), expected)
        self.settings.update(CUSTOM_UI)
        self.assertEqual(self.ui(SettingsStore(self.settings.path).snapshot()), CUSTOM_UI)

    def test_bridge_passes_native_json_and_desktop_is_an_explicit_noop(self):
        native = RecordingNative()
        result = AndroidBridge(native).ui_preferences(CUSTOM_UI)
        self.assertTrue(result["ok"])
        self.assertEqual(native.preferences, [CUSTOM_UI])
        self.assertIsInstance(native.raw_preferences[0], str)
        desktop = AndroidBridge()
        desktop._native = None
        result = desktop.ui_preferences(CUSTOM_UI)
        self.assertTrue(result["ok"])
        self.assertIs(result["supported"], False)
        self.assertNotIn("_session_preferences", vars(desktop))
        self.assertEqual(self.ui(self.settings.snapshot()), DEFAULT_UI)

    def test_startup_restart_and_sync_mirror_only_display_fields(self):
        self.settings.update({**CUSTOM_UI, "model_name": "private-model-content",
                              "blacklist": ["private-device-authority"], "cloud_consent": True,
                              "disclaimer_accepted": True, "default_runtime": "termux"})
        manager, native = self.start_manager()
        self.assertEqual(native.preferences, [CUSTOM_UI])
        self.configure_model(manager)
        before_models = manager.models.export_metadata()
        before_authority = manager.settings.snapshot()
        manager.sync_ui_preferences()
        self.assertEqual(native.preferences, [CUSTOM_UI, CUSTOM_UI])
        for payload in native.preferences:
            self.assertEqual(set(payload), set(DEFAULT_UI))
        raw = " ".join(native.raw_preferences)
        for forbidden in (manager.api_token, "ui-private-model-key", "private-model-content",
                          "private-device-authority", "cloud_consent", "full_access", "model_name",
                          "default_runtime", "api_key"):
            self.assertNotIn(forbidden, raw)
        self.assertEqual(manager.models.export_metadata(), before_models)
        self.assertEqual(manager.settings.snapshot(), before_authority)
        manager.shutdown()
        restarted, fresh_native = self.start_manager(
            settings=SettingsStore(self.settings.path), native=RecordingNative(native.credentials))
        self.assertEqual(fresh_native.preferences, [CUSTOM_UI])
        self.assertEqual(restarted.models.select()._api_key, "ui-private-model-key")

    def test_authenticated_api_save_and_bootstrap_return_persisted_preferences(self):
        manager, native = self.start_manager()
        port = self.start_http(manager)
        before = manager.settings.snapshot()
        for token in (None, "wrong-ui-token"):
            with self.subTest(token=token):
                status, _ = self.request(port, "POST", "/api/settings", CUSTOM_UI, token=token)
                self.assertEqual(status, 401)
        self.assertEqual(manager.settings.snapshot(), before)
        self.assertEqual(native.preferences, [DEFAULT_UI])
        status, saved = self.request(port, "POST", "/api/settings", CUSTOM_UI)
        self.assertEqual(status, 200, saved)
        self.assertEqual(self.ui(saved), CUSTOM_UI)
        self.assertEqual(native.preferences[-1], CUSTOM_UI)
        status, bootstrap = self.request(port, "GET", "/api/bootstrap")
        self.assertEqual(status, 200, bootstrap)
        self.assertEqual(self.ui(bootstrap["settings"]), CUSTOM_UI)
        self.assertEqual(self.ui(SettingsStore(self.settings.path).snapshot()), CUSTOM_UI)
        self.assertEqual({key: value for key, value in manager.settings.snapshot().items() if key not in DEFAULT_UI},
                         {key: value for key, value in before.items() if key not in DEFAULT_UI})

    def test_api_invalid_updates_neither_partially_save_nor_notify_native(self):
        manager, native = self.start_manager()
        port = self.start_http(manager)
        before = manager.settings.snapshot()
        disk_before = self.settings.path.read_bytes()
        cases = ({"ui_theme": []}, {"ui_font_size": True}, {"ui_language": "fr"},
                 {"ui_theme": "Dark"}, {"ui_font_size": "medium"}, {"ui_language": None},
                 {"ui_language": "en", "ui_theme": "dark", "language_instruction": "answer English"})
        for values in cases:
            with self.subTest(values=values):
                status, body = self.request(port, "POST", "/api/settings",
                                            {"blacklist": ["not-persisted"], **values})
                self.assertEqual(status, 400, body)
                self.assertEqual(manager.settings.snapshot(), before)
                self.assertEqual(self.settings.path.read_bytes(), disk_before)
                self.assertEqual(native.preferences, [DEFAULT_UI])
        status, body = self.request(port, "GET", "/api/settings")
        self.assertEqual(status, 200, body)
        self.assertEqual(self.ui(body), DEFAULT_UI)

    def test_configuration_import_roundtrips_preferences_and_rejects_invalid_atomically(self):
        manager, native = self.start_manager()
        self.configure_model(manager)
        self.settings.update({**CUSTOM_UI, "model_enabled": True, "cloud_consent": True})
        exported = manager.maintenance.export_config()
        self.assertEqual(self.ui(exported["settings"]), CUSTOM_UI)
        self.assertNotIn("ui-private-model-key", json.dumps(exported))
        self.settings.update(DEFAULT_UI)
        result = manager.maintenance.import_config(exported)
        self.assertTrue(result["ok"])
        self.assertEqual(self.ui(self.settings.snapshot()), CUSTOM_UI)
        self.assertEqual(native.preferences[-1], CUSTOM_UI)
        self.assertEqual(set(native.preferences[-1]), set(DEFAULT_UI))
        # Display import does not import data-sending consent or model execution authorization.
        self.assertFalse(self.settings.snapshot()["cloud_consent"])
        self.assertFalse(self.settings.snapshot()["model_enabled"])
        before, disk_before = self.settings.snapshot(), self.settings.path.read_bytes()
        models_before, calls_before = manager.models.export_metadata(), len(native.preferences)
        for version in (1, 2):
            invalid = copy.deepcopy(exported)
            invalid["version"] = version
            invalid["settings"].update({"ui_theme": "light", "ui_language": {"locale": "en"}})
            with self.subTest(version=version), self.assertRaises(ValueError):
                manager.maintenance.import_config(invalid)
            self.assertEqual(self.settings.snapshot(), before)
            self.assertEqual(self.settings.path.read_bytes(), disk_before)
            self.assertEqual(manager.models.export_metadata(), models_before)
            self.assertEqual(len(native.preferences), calls_before)

    def test_language_change_does_not_modify_running_chat_model_messages_or_output(self):
        provider = ThreadingHTTPServer(("127.0.0.1", 0), PreferenceModelHandler)
        provider.daemon_threads = True
        provider.capture_lock = threading.Lock()
        provider.captures = []
        provider.arrived, provider.release = threading.Event(), threading.Event()
        thread = threading.Thread(target=provider.serve_forever, daemon=True)
        thread.start()
        self.providers.append((provider, thread))
        manager, native = self.start_manager()
        self.configure_model(manager, "http://127.0.0.1:" + str(provider.server_address[1]) + "/v1")
        self.settings.update({"disclaimer_accepted": True, "cloud_consent": True, "model_enabled": True})
        port = self.start_http(manager)
        original_text = "不要翻译用户正文。Keep this user text exactly unchanged."
        status, created = self.request(port, "POST", "/api/chat",
                                       {"message": original_text, "model_profile_id": "ui-model"})
        self.assertEqual(status, 202, created)
        task = manager.get_task(created["task"]["id"])
        self.assertTrue(provider.arrived.wait(5), task.snapshot())
        selection = task.model_selection
        before_models = manager.models.export_metadata()
        original_policy = (task.channel, task.runtime, task.full_access)
        original_settings = self.settings.snapshot()
        status, saved = self.request(port, "POST", "/api/settings", {"ui_language": "en"})
        self.assertEqual(status, 200, saved)
        self.assertEqual(saved["ui_language"], "en")
        self.assertIs(task.model_selection, selection)
        self.assertEqual(task.message, original_text)
        self.assertEqual((task.channel, task.runtime, task.full_access), original_policy)
        self.assertEqual(manager.models.export_metadata(), before_models)
        self.assertEqual(self.settings.snapshot(), {**original_settings, "ui_language": "en"})
        self.assertEqual(native.preferences[-1], {**DEFAULT_UI, "ui_language": "en"})
        provider.release.set()
        self.assertTrue(task.done.wait(6), task.snapshot())
        self.assertEqual(task.state, "succeeded", task.snapshot())
        expected_output = "第一阶段 / keep literal; 保留中文 / English literal final"
        self.assertEqual(task.assistant_text, expected_output)
        with provider.capture_lock:
            captures = copy.deepcopy(provider.captures)
        self.assertEqual(len(captures), 2)
        first, second = [row["body"] for row in captures]
        for row in captures:
            self.assertEqual(row["path"], "/v1/chat/completions")
            self.assertEqual(row["authorization"], "Bearer ui-private-model-key")
            body = row["body"]
            self.assertEqual(body["model"], "unchanged-model")
            self.assertEqual(body["reasoning_effort"], "high")
            self.assertEqual(body["max_completion_tokens"], 1024)
            self.assertEqual([message["content"] for message in body["messages"] if message["role"] == "user"],
                             [original_text])
            self.assertEqual([message for message in body["messages"] if message["role"] == "system"],
                             [first["messages"][0]])
            self.assertTrue(body["messages"][0]["content"].startswith(SYSTEM_PROMPT))
            self.assertFalse({"ui_theme", "ui_font_size", "ui_language", "language", "locale", "instruction_language"} & set(body))
            self.assertNotIn("ui_language", json.dumps(body))
            self.assertNotIn("answer in English", json.dumps(body))
        self.assertEqual(first["messages"][0], second["messages"][0])
        self.assertEqual(second["messages"][2]["content"], "第一阶段 / keep literal; ")
        self.assertEqual(manager.store.get_task(task.id)["assistant_text"], expected_output)
        self.assertEqual(self.ui(self.request(port, "GET", "/api/bootstrap")[1]["settings"]),
                         {**DEFAULT_UI, "ui_language": "en"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
