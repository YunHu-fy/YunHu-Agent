"""Focused attachment validation and chat-history regressions."""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from android_agent import attachments
from android_agent.android_bridge import AndroidBridge
from android_agent.config import SettingsStore
from android_agent.core import AgentManager
from android_agent.security import Workspace
from android_agent.server import AgentHTTPServer, RequestHandler
from android_agent.store import Store


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jX4kAAAAASUVORK5CYII="
)
LEGACY = {"model_base_url": "http://127.0.0.1:1234/v1", "model_name": "legacy-model"}


def upload(name: str, raw: bytes, mime_type: str = "text/plain") -> dict:
    return {"name": name, "mime_type": mime_type, "data": base64.b64encode(raw).decode("ascii")}


def wait_for(predicate, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("condition did not become true")


class ProviderHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        with self.server.requests_lock:
            self.server.requests.append(body)
        payload = json.dumps({
            "id": "attachment-fixture",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "received attachment"}, "finish_reason": "stop"}],
        }).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)


class QuietHandler(RequestHandler):
    def log_message(self, *args):
        pass


class AttachmentValidationTests(unittest.TestCase):
    def test_empty_and_eight_item_limits(self):
        self.assertEqual(attachments.prepare(None, False), [])
        self.assertEqual(attachments.prepare([], False), [])
        eight = [upload(f"{index}.txt", b"x") for index in range(8)]
        prepared = attachments.prepare(eight, False)
        self.assertEqual(len(prepared), 8)
        with self.assertRaisesRegex(ValueError, "8"):
            attachments.prepare(eight + [upload("ninth.txt", b"x")], False)

    def test_exact_20_mib_file_is_accepted_and_one_byte_over_is_rejected(self):
        exact = upload("limit.bin", b"x" * attachments.MAX_FILE)
        prepared = attachments.prepare([exact], False)
        self.assertEqual(prepared[0][0]["bytes"], 20 * 1024 * 1024)
        self.assertEqual(prepared[0][0]["sha256"], hashlib.sha256(b"x" * attachments.MAX_FILE).hexdigest())
        with self.assertRaisesRegex(ValueError, "20 MiB"):
            attachments.prepare([upload("too-large.bin", b"x" * (attachments.MAX_FILE + 1))], False)

    def test_exact_30_mib_total_is_accepted_and_one_byte_over_is_rejected(self):
        values = [upload("twenty.bin", b"a" * (20 * 1024 * 1024)), upload("ten.bin", b"b" * (10 * 1024 * 1024))]
        prepared = attachments.prepare(values, False)
        self.assertEqual(sum(metadata["bytes"] for metadata, _ in prepared), 30 * 1024 * 1024)
        with self.assertRaisesRegex(ValueError, "合计最多30 MiB"):
            attachments.prepare(values + [upload("one-byte.bin", b"c")], False)

    def test_rejects_invalid_names_mime_base64_and_unsupported_or_malformed_images(self):
        cases = [
            upload("../escape.txt", b"x"),
            upload("bad\nname.txt", b"x"),
            {"name": "x", "mime_type": "not a mime", "data": "eA=="},
            {"name": "x", "mime_type": "text/plain", "data": "%%%"},
            upload("image.png", PNG_1X1, "image/png"),
            upload("fake.png", b"not png", "image/png"),
        ]
        for value in cases:
            with self.subTest(value=value["name"]), self.assertRaises(ValueError):
                attachments.prepare([value], supports_images=False)
        with self.assertRaisesRegex(ValueError, "文件头"):
            attachments.prepare([upload("fake.png", b"not png", "image/png")], supports_images=True)

    def test_utf8_content_image_data_url_and_hash_integrity(self):
        with tempfile.TemporaryDirectory(prefix="attachment-content-") as temp:
            workspace = Workspace(Path(temp) / "workspace")
            text_raw = "Café 你好\nsecond line".encode("utf-8")
            prepared = attachments.prepare([
                upload("notes.txt", text_raw),
                upload("pixel.png", PNG_1X1, "image/png"),
            ], supports_images=True)
            metadata = attachments.save(workspace, prepared)

            payload = attachments.content(workspace, "summarize", metadata, supports_images=True)
            self.assertIsInstance(payload, list)
            self.assertIn("Café 你好\nsecond line", payload[0]["text"])
            image_url = payload[1]["image_url"]["url"]
            self.assertEqual(image_url, "data:image/png;base64," + base64.b64encode(PNG_1X1).decode("ascii"))
            self.assertEqual(payload[1]["image_url"]["detail"], "low")
            self.assertEqual(metadata[0]["sha256"], hashlib.sha256(text_raw).hexdigest())

            target = workspace._resolved(metadata[0]["path"])
            target.write_bytes(b"tampered")
            with self.assertRaisesRegex(ValueError, "已被修改"):
                attachments.content(workspace, "summarize", metadata[:1], supports_images=True)


class AttachmentChatHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="attachment-chat-history-")
        self.root = Path(self.temporary.name)
        self.provider = ThreadingHTTPServer(("127.0.0.1", 0), ProviderHandler)
        self.provider.daemon_threads = True
        self.provider.requests = []
        self.provider.requests_lock = threading.Lock()
        self.provider_thread = threading.Thread(target=self.provider.serve_forever, daemon=True)
        self.provider_thread.start()
        endpoint = f"http://127.0.0.1:{self.provider.server_address[1]}/v1"
        self.settings = SettingsStore(self.root / "data/settings.json")
        self.settings.update({"disclaimer_accepted": True, "cloud_consent": True})
        self.store = Store(self.root / "data/agent.sqlite3")
        native = NativeVault()
        self.manager = AgentManager(self.root, self.settings, self.store, "attachment-local-token", android=AndroidBridge(native))
        self.manager.save_models({
            "profiles": [{
                "id": "vision",
                "base_url": endpoint,
                "model": "local-vision-model",
                "context_window": 65536,
                "max_output_tokens": 512,
                "reasoning_enabled": False,
                "reasoning_level": "medium",
                "supports_images": True,
                "api_key": "local-attachment-key",
            }],
            "active_model_id": "vision",
        })
        self.settings.update({"model_enabled": True})
        self.server = AgentHTTPServer(0, self.manager)
        self.server.RequestHandlerClass = QuietHandler
        with RequestHandler._rate_lock:
            RequestHandler._rate.clear()
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
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
        connection.request(method, path, json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None, headers)
        response = connection.getresponse()
        raw = response.read()
        status = response.status
        connection.close()
        return status, json.loads(raw.decode("utf-8"))

    def provider_requests(self):
        with self.provider.requests_lock:
            return list(self.provider.requests)

    def wait_task(self, task_id: str):
        task = wait_for(lambda: self.manager.get_task(task_id))
        self.assertTrue(task.done.wait(5), task.snapshot())
        self.assertEqual(task.state, "succeeded", task.snapshot())
        return task

    def test_chat_sends_real_attachment_content_and_restores_it_from_history(self):
        text_raw = "Résumé: 東京\nprice: €5".encode("utf-8")
        text = upload("receipt.txt", text_raw)
        image = upload("pixel.png", PNG_1X1, "image/png")
        status, result = self.request("POST", "/api/chat", {
            "message": "Read these files",
            "model_profile_id": "vision",
            "attachments": [text, image],
        })
        self.assertEqual(status, 202, result)
        first_task = self.wait_task(result["task"]["id"])
        conversation_id = first_task.conversation_id

        first_payload = wait_for(lambda: self.provider_requests()[0] if self.provider_requests() else None)
        user_content = first_payload["messages"][-1]["content"]
        self.assertEqual(user_content[0]["type"], "text")
        self.assertIn("Résumé: 東京\nprice: €5", user_content[0]["text"])
        self.assertEqual(user_content[1]["image_url"]["url"], "data:image/png;base64," + base64.b64encode(PNG_1X1).decode("ascii"))

        status, conversation = self.request("GET", "/api/conversations/" + conversation_id)
        self.assertEqual(status, 200)
        user_row = next(row for row in conversation["messages"] if row["role"] == "user")
        self.assertEqual(len(user_row["attachments"]), 2)
        by_name = {item["name"]: item for item in user_row["attachments"]}
        self.assertEqual(by_name["receipt.txt"]["bytes"], len(text_raw))
        self.assertEqual(by_name["receipt.txt"]["sha256"], hashlib.sha256(text_raw).hexdigest())
        self.assertEqual(by_name["pixel.png"]["sha256"], hashlib.sha256(PNG_1X1).hexdigest())
        self.assertNotIn("data:image", json.dumps(conversation))
        self.assertNotIn(base64.b64encode(text_raw).decode("ascii"), json.dumps(conversation))

        status, followup = self.request("POST", "/api/chat", {
            "message": "Use the previous files too",
            "model_profile_id": "vision",
            "conversation_id": conversation_id,
        })
        self.assertEqual(status, 202, followup)
        self.wait_task(followup["task"]["id"])
        requests = self.provider_requests()
        self.assertEqual(len(requests), 2)
        history_payload = requests[1]["messages"]
        previous_user = next(message for message in history_payload if message["role"] == "user" and isinstance(message["content"], list))
        self.assertIn("Résumé: 東京\nprice: €5", previous_user["content"][0]["text"])
        self.assertEqual(previous_user["content"][1]["image_url"]["url"], "data:image/png;base64," + base64.b64encode(PNG_1X1).decode("ascii"))
        self.assertEqual(history_payload[-1]["content"], "Use the previous files too")


class NativeVault:
    def __init__(self):
        self.values = {}

    def status(self):
        return json.dumps({
            "ok": True,
            "selected_channel": "normal",
            "normal": {"available": True, "granted": True},
            "shizuku": {"available": False, "granted": False},
            "root": {"available": False, "granted": False},
        })

    def credentialWrite(self, profile_id, value):
        self.values[profile_id] = value
        return json.dumps({"ok": True})

    def credentialRead(self, profile_id):
        return json.dumps({"ok": True, "value": self.values.get(profile_id, "")})

    def credentialDelete(self, profile_id):
        self.values.pop(profile_id, None)
        return json.dumps({"ok": True})


if __name__ == "__main__":
    unittest.main(verbosity=2)
