from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from android_agent.core import AgentManager
from android_agent.extensions import ExtensionManager


class MemoryVault:
    def __init__(self):
        self.values: dict[str, str] = {}

    def credential_set(self, credential_id: str, value: str) -> None:
        self.values[credential_id] = value

    def credential_get(self, credential_id: str) -> str:
        return self.values.get(credential_id, "")

    def credential_delete(self, credential_id: str) -> None:
        self.values.pop(credential_id, None)


class ExtensionManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="extensions-test-")
        self.root = Path(self.temporary.name) / "extensions"
        self.vault = MemoryVault()
        self.manager = ExtensionManager(self.root, self.vault)

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def skill(body: str = "Do the task safely.") -> str:
        return f"---\nname: sample-skill\ndescription: A test skill\n---\n{body}\n"

    def _request_with_body(self, content: bytes, content_type: str = "application/json", payload=None):
        class Response:
            headers = {"Mcp-Session-Id": "response-session"}

            def __init__(self):
                self.headers = {"Content-Type": content_type, "Mcp-Session-Id": "response-session"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self, _limit):
                return content

        class Opener:
            def open(self, _request, timeout):
                self.timeout = timeout
                return Response()

        opener = Opener()
        with patch("android_agent.extensions.urllib.request.build_opener", return_value=opener):
            result = self.manager._request(
                {"url": "https://example.invalid/mcp", "credential_id": ""},
                payload if payload is not None else {"jsonrpc": "2.0", "id": 1},
            )
        self.assertEqual(opener.timeout, 8)
        return result

    def test_valid_skill_install_and_frontmatter_validation(self):
        result = self.manager.install_skill({
            "SKILL.md": self.skill(),
            "references/guide.txt": "fixture reference\n",
        })
        self.assertEqual(result, {
            "ok": True,
            "name": "sample-skill",
            "description": "A test skill",
            "updated": False,
        })
        self.assertEqual(self.manager.list_skills(), [{
            "name": "sample-skill",
            "description": "A test skill",
            "active": True,
            "files": 2,
        }])
        self.assertEqual((self.manager.skills_root / "sample-skill" / "references" / "guide.txt").read_text(encoding="utf-8"), "fixture reference\n")

        for content in (
            "name: missing-frontmatter\nbody\n",
            "---\nname: bad/name\ndescription: invalid slug\n---\nbody\n",
            "---\nname: no-body\ndescription: missing body\n---\n",
        ):
            with self.subTest(content=content), self.assertRaises(ValueError):
                self.manager.install_skill({"SKILL.md": content})

    def test_skill_paths_reject_traversal_and_absolute_paths(self):
        unsafe_paths = (
            "../outside.txt",
            "nested/../../outside.txt",
            r"..\outside.txt",
            "/outside.txt",
            r"\outside.txt",
        )
        for path in unsafe_paths:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.manager.install_skill({"SKILL.md": self.skill(), path: "must not escape"})
        self.assertFalse((self.root / "outside.txt").exists())
        self.assertEqual(list(self.manager.skills_root.iterdir()), [])

    def test_skill_update_replaces_old_tree_atomically(self):
        first = self.manager.install_skill({
            "SKILL.md": self.skill("Version one."),
            "obsolete.txt": "remove me",
        })
        self.assertFalse(first["updated"])

        updated = self.manager.install_skill({
            "SKILL.md": self.skill("Version two."),
            "new/note.txt": "new file",
        })
        target = self.manager.skills_root / "sample-skill"
        self.assertTrue(updated["updated"])
        self.assertEqual((target / "SKILL.md").read_text(encoding="utf-8"), self.skill("Version two."))
        self.assertFalse((target / "obsolete.txt").exists())
        self.assertEqual((target / "new" / "note.txt").read_text(encoding="utf-8"), "new file")
        self.assertEqual(list(self.manager.skills_root.glob(".stage-*")), [])
        self.assertEqual(list(self.manager.skills_root.glob(".old-*")), [])

    def test_skill_update_failure_restores_previous_directory(self):
        self.manager.install_skill({
            "SKILL.md": self.skill("Known good version."),
            "keep.txt": "preserve",
        })
        real_replace = os.replace
        calls = 0

        def fail_publication_once(source, destination):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated stage publication failure")
            return real_replace(source, destination)

        with patch("android_agent.extensions.os.replace", side_effect=fail_publication_once):
            with self.assertRaisesRegex(OSError, "simulated stage publication failure"):
                self.manager.install_skill({"SKILL.md": self.skill("Unpublished version.")})

        target = self.manager.skills_root / "sample-skill"
        self.assertEqual((target / "SKILL.md").read_text(encoding="utf-8"), self.skill("Known good version."))
        self.assertEqual((target / "keep.txt").read_text(encoding="utf-8"), "preserve")
        self.assertEqual(list(self.manager.skills_root.glob(".stage-*")), [])
        self.assertEqual(list(self.manager.skills_root.glob(".old-*")), [])

    def test_mcp_token_stays_in_vault_and_never_appears_in_public_list_or_registry(self):
        token = "mcp-secret-fixture-token"
        added = self.manager.add_mcp("  Demo server  ", "https://example.invalid/mcp/", token, "demo")
        self.assertEqual(added["server"], {
            "id": "demo",
            "name": "Demo server",
            "url": "https://example.invalid/mcp",
            "has_token": True,
        })
        self.assertEqual(self.vault.values, {"mcp_demo": token})
        self.assertNotIn(token, self.manager.registry.read_text(encoding="utf-8"))
        self.assertNotIn(token, json.dumps(self.manager.list_mcp()))
        self.assertEqual(self.manager.secret_values(), (token,))

        harness = SimpleNamespace(secret_values=self.manager.secret_values)
        redacted = AgentManager.redact(harness, f"request failed with Bearer {token}")
        self.assertNotIn(token, redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_mcp_requests_send_vault_token_and_session_header_without_network(self):
        token = "request-header-secret"
        self.manager.add_mcp("Demo", "https://example.invalid/mcp", token, "demo")
        row = self.manager._row("demo")

        class Response:
            headers = {"Content-Type": "application/json", "Mcp-Session-Id": "session-fixture"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

            def read(self, _limit):
                return b'{"jsonrpc": "2.0", "id": 1, "result": {"ok": true}}'

        class Opener:
            def __init__(self):
                self.request = None

            def open(self, request, timeout):
                self.request = request
                self.timeout = timeout
                return Response()

        opener = Opener()
        with patch("android_agent.extensions.urllib.request.build_opener", return_value=opener) as build_opener:
            reply, session = self.manager._request(row, {"jsonrpc": "2.0", "id": 1}, "prior-session")

        self.assertEqual(reply, {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}})
        self.assertEqual(session, "session-fixture")
        self.assertEqual(opener.timeout, 8)
        headers = {key.lower(): value for key, value in opener.request.header_items()}
        self.assertEqual(headers["authorization"], "Bearer " + token)
        self.assertEqual(headers["mcp-session-id"], "prior-session")
        self.assertEqual(headers["mcp-protocol-version"], "2025-03-26")
        self.assertEqual(json.loads(opener.request.data), {"jsonrpc": "2.0", "id": 1})
        build_opener.assert_called_once()

    def test_mcp_request_rejects_unmatched_or_malformed_jsonrpc_envelopes(self):
        invalid_messages = (
            {"jsonrpc": "2.0", "id": 2, "result": {}},
            {"id": 1, "result": {}},
            {"jsonrpc": "2.0", "id": 1},
            {"jsonrpc": "2.0", "id": 1, "result": {}, "error": {"code": -1, "message": "bad"}},
        )
        for message in invalid_messages:
            with self.subTest(message=message), self.assertRaises(ValueError):
                self._request_with_body(json.dumps(message).encode("utf-8"))

        with self.assertRaisesRegex(ValueError, "无效 JSON"):
            self._request_with_body(b"not-json")

    def test_mcp_request_sse_selects_matching_id_from_multiple_messages(self):
        events = (
            'data: {"jsonrpc":"2.0","id":99,"result":{"ignored":true}}\n\n'
            'data: {"jsonrpc":"2.0","id":1,"result":{"matched":true}}\n\n'
        ).encode("utf-8")
        reply, session = self._request_with_body(events, "text/event-stream; charset=utf-8")
        self.assertEqual(reply, {"jsonrpc": "2.0", "id": 1, "result": {"matched": True}})
        self.assertEqual(session, "response-session")

    def test_mcp_notification_accepts_empty_response_body(self):
        reply, session = self._request_with_body(
            b"", payload={"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        self.assertEqual(reply, {})
        self.assertEqual(session, "response-session")

    def test_mcp_tools_rejects_absent_or_non_list_tools(self):
        self.manager.add_mcp("Demo", "https://example.invalid/mcp", server_id="demo")
        for result in ({}, {"tools": None}, {"tools": {"name": "tool"}}):
            responses = [
                ({"jsonrpc": "2.0", "id": 1, "result": {}}, "session"),
                ({}, "session"),
                ({"jsonrpc": "2.0", "id": 2, "result": result}, "session"),
            ]
            with self.subTest(result=result), patch.object(self.manager, "_request", side_effect=responses):
                with self.assertRaises(ValueError):
                    self.manager.mcp_tools("demo")

    def test_call_mcp_rejects_absent_or_non_object_result(self):
        self.manager.add_mcp("Demo", "https://example.invalid/mcp", server_id="demo")
        for response in (
            {"jsonrpc": "2.0", "id": 4},
            {"jsonrpc": "2.0", "id": 4, "result": None},
            {"jsonrpc": "2.0", "id": 4, "result": []},
        ):
            request_responses = [
                ({"jsonrpc": "2.0", "id": 3, "result": {}}, "session"),
                ({}, "session"),
                (response, "session"),
            ]
            with self.subTest(response=response), patch.object(self.manager, "mcp_tools", return_value=[{"name": "hello"}]), patch.object(self.manager, "_request", side_effect=request_responses):
                with self.assertRaises(ValueError):
                    self.manager.call_mcp("demo", "hello", {})

    def test_mcp_urls_reject_embedded_credentials_query_and_fragment(self):
        invalid_urls = (
            "https://user:password@example.invalid/mcp",
            "https://example.invalid/mcp?token=secret",
            "https://example.invalid/mcp#fragment",
        )
        for url in invalid_urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.manager.add_mcp("Demo", url, "")

    def test_delete_mcp_removes_vault_credential(self):
        self.manager.add_mcp("Demo", "https://example.invalid/mcp", "delete-me", "demo")
        self.assertTrue(self.manager.delete_mcp("demo"))
        self.assertEqual(self.vault.values, {})
        self.assertEqual(self.manager.secret_values(), ())
        self.assertFalse(self.manager.delete_mcp("demo"))


if __name__ == "__main__":
    unittest.main()
