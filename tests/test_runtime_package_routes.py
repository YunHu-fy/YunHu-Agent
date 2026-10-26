"""HTTP route coverage for the fixed runtime package catalog."""
from __future__ import annotations

import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any

from android_agent.android_bridge import AndroidBridge
from android_agent.config import SettingsStore
from android_agent.core import AgentManager
from android_agent.server import AgentHTTPServer, RequestHandler
from android_agent.store import Store


_NO_BODY = object()


class FakeRuntimeNative:
    """Small native bridge double that records only package operations."""

    prefix = "/data/data/com.termux/files/usr"

    def __init__(self) -> None:
        self.commands: list[dict[str, Any]] = []
        self.installed_distros: set[str] = set()
        self.installed_paths: set[str] = set()

    def status(self) -> str:
        return json.dumps({
            "ok": True,
            "selected_channel": "normal",
            "normal": {"available": True, "granted": True},
            "shizuku": {"available": False, "granted": False},
            "root": {"available": False, "granted": False, "checked": False},
        })

    def runtimeStatus(self) -> str:
        return json.dumps({
            "ok": True,
            "supported": True,
            "installed": True,
            "installing": False,
            "stage": "ready",
            "prefix": self.prefix,
            "home": self.prefix.rsplit("/", 2)[0] + "/home",
        })

    def runtimePathExists(self, path: str) -> bool:
        if path == self.prefix + "/bin/proot-distro":
            return True
        for distro in ("debian", "ubuntu"):
            apt = self.prefix + f"/var/lib/proot-distro/installed-rootfs/{distro}/usr/bin/apt-get"
            if path == apt:
                return distro in self.installed_distros
        return path in self.installed_paths

    def executeCommand(self, encoded_request: str) -> str:
        request = json.loads(encoded_request)
        self.commands.append(request)
        command = request["command"]
        if command.startswith("proot-distro install "):
            self.installed_distros.add(command.removeprefix("proot-distro install "))
        if command.startswith("pkg install -y "):
            for name in command.split()[3:]:
                self.installed_paths.add(self.prefix + "/bin/" + name)
        return json.dumps({"ok": True, "status": "succeeded", "exit_code": 0,
                           "stdout": "VER|curl|curl 8.9.1\nVER|node|v22.9.0\n"})

    def localModelStatus(self) -> str:
        return json.dumps({"supported": False, "installed": False, "installing": False, "running": False})

    def appUiPreferences(self, _encoded_values: str) -> str:
        return json.dumps({"ok": True})

    def deviceState(self) -> str:
        return json.dumps({"ok": True, "supported": True})


class RuntimePackageHTTPFixture:
    """Composed HTTP fixture; it does not inherit another route test case."""

    def __init__(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="runtime-package-route-")
        root = Path(self.temporary.name)
        self.settings = SettingsStore(root / "data" / "settings.json")
        self.settings.update({"disclaimer_accepted": True})
        self.store = Store(root / "data" / "agent.sqlite3")
        self.native = FakeRuntimeNative()
        self.manager = AgentManager(root, self.settings, self.store, "runtime-route-token", android=AndroidBridge(self.native))
        self.server = AgentHTTPServer(0, self.manager)
        with RequestHandler._rate_lock:
            RequestHandler._rate.clear()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def close(self) -> None:
        self.manager.shutdown()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.temporary.cleanup()

    def request(self, method: str, path: str, body: Any = _NO_BODY) -> tuple[int, Any]:
        headers = {"Authorization": "Bearer " + self.manager.api_token}
        encoded = None
        if body is not _NO_BODY:
            encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        try:
            connection.request(method, path, encoded, headers)
            response = connection.getresponse()
            raw = response.read()
            status = response.status
            content_type = response.getheader("Content-Type", "")
        finally:
            connection.close()
        if "application/json" in content_type:
            return status, json.loads(raw.decode("utf-8"))
        return status, raw.decode("utf-8")

    def wait_for_approval(self, task_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            status, task = self.request("GET", f"/api/tasks/{task_id}")
            if status == 200 and task.get("pending_approval"):
                return task
            time.sleep(0.02)
        raise AssertionError("package task did not reach approval state")

    def wait_for_terminal(self, task_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            status, task = self.request("GET", f"/api/tasks/{task_id}")
            if status == 200 and task.get("status") in {"succeeded", "failed", "cancelled", "timed_out"}:
                return task
            time.sleep(0.02)
        raise AssertionError("package task did not reach a terminal state")

    def run_approved(self, payload: dict[str, Any], approved: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
        status, response = self.request("POST", "/api/runtime/packages", payload)
        if status != 202:
            raise AssertionError(f"package task was not accepted: {status} {response!r}")
        created = response["task"]
        pending = self.wait_for_approval(created["id"])
        status, decision = self.request("POST", f"/api/tasks/{created['id']}/decision", {
            "approval_id": pending["pending_approval"]["approval_id"],
            "approved": approved,
        })
        if status != 200:
            raise AssertionError(f"approval decision failed: {status} {decision!r}")
        return created, self.wait_for_terminal(created["id"])


class RuntimePackageRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.http = RuntimePackageHTTPFixture()
        self.addCleanup(self.http.close)

    def task_count(self) -> int:
        status, payload = self.http.request("GET", "/api/tasks")
        self.assertEqual(status, 200, payload)
        return len(payload["tasks"])

    def test_termux_install_null_is_approved_and_executes_catalog_command(self) -> None:
        created, finished = self.http.run_approved({"package_ids": ["curl"], "distro": None})

        self.assertEqual(finished["status"], "succeeded")
        result = json.loads(finished["assistant_text"])
        self.assertEqual(result["distro"], "termux")
        self.assertEqual(result["package_ids"], ["curl"])
        self.assertEqual(result["versions"]["curl"], "curl 8.9.1")
        # One catalog install plus one read-only version probe.
        self.assertEqual(len(self.http.native.commands), 2)
        command = self.http.native.commands[0]
        self.assertEqual(command["command"], "pkg install -y curl")
        self.assertEqual(command["channel"], "normal")
        self.assertEqual(command["runtime"], "termux")
        self.assertIn("ver node node --version", self.http.native.commands[1]["command"])
        self.assertEqual(created["conversation_id"], None)

    def test_denied_termux_install_never_executes_android_command(self) -> None:
        _created, finished = self.http.run_approved({"package_ids": ["curl"], "distro": None}, approved=False)

        self.assertEqual(finished["status"], "failed")
        self.assertIn("未获批准", finished["error"])
        self.assertEqual(self.http.native.commands, [])

    def test_deploy_debian_and_ubuntu_is_successful_and_idempotent(self) -> None:
        for distro in ("debian", "ubuntu"):
            with self.subTest(distro=distro):
                _created, first = self.http.run_approved({"action": "deploy", "distro": distro})
                self.assertEqual(first["status"], "succeeded")
                first_result = json.loads(first["assistant_text"])
                self.assertEqual(first_result["distro"], distro)
                self.assertFalse(first_result["already_installed"])
                self.assertEqual(self.http.native.commands[-2]["command"], f"proot-distro install {distro}")
                self.assertTrue(self.http.native.commands[-1]["command"].startswith(f"proot-distro login {distro} -- "))
                command_count = len(self.http.native.commands)

                _created, duplicate = self.http.run_approved({"action": "deploy", "distro": distro})
                self.assertEqual(duplicate["status"], "succeeded")
                duplicate_result = json.loads(duplicate["assistant_text"])
                self.assertTrue(duplicate_result["already_installed"])
                self.assertEqual(len(self.http.native.commands), command_count)

    def test_residual_container_blocks_deploy_with_clean_up_guidance(self) -> None:
        rootfs = self.http.native.prefix + "/var/lib/proot-distro/installed-rootfs/ubuntu"
        self.http.native.installed_paths.add(rootfs)
        _created, task = self.http.run_approved({"action": "deploy", "distro": "ubuntu"})
        self.assertEqual(task["status"], "failed")
        self.assertIn("清理并重装", task.get("error") or "")
        self.assertEqual(self.http.native.commands, [])

    def test_reset_removes_the_residual_container_then_deploys(self) -> None:
        rootfs = self.http.native.prefix + "/var/lib/proot-distro/installed-rootfs/ubuntu"
        self.http.native.installed_paths.add(rootfs)
        _created, task = self.http.run_approved({"action": "deploy", "distro": "ubuntu", "reset": True})
        self.assertEqual(task["status"], "succeeded", task.get("error"))
        commands = [item["command"] for item in self.http.native.commands]
        self.assertEqual(commands[:2], ["proot-distro remove ubuntu", "proot-distro install ubuntu"])

    def test_reset_is_rejected_for_package_installs(self) -> None:
        status, response = self.http.request("POST", "/api/runtime/packages",
                                             {"package_ids": ["curl"], "reset": True})
        self.assertEqual(status, 400, response)
        self.assertEqual(self.task_count(), 0)
        self.assertEqual(self.http.native.commands, [])

    def test_invalid_and_duplicate_catalog_ids_are_rejected_before_task_creation(self) -> None:
        for package_ids in (["not-in-catalog"], ["curl", "curl"]):
            with self.subTest(package_ids=package_ids):
                status, response = self.http.request("POST", "/api/runtime/packages", {
                    "package_ids": package_ids,
                    "distro": None,
                })
                self.assertEqual(status, 400, response)
                self.assertEqual(self.task_count(), 0)
        self.assertEqual(self.http.native.commands, [])

    def test_deploy_rejects_package_ids_before_creating_task(self) -> None:
        for package_ids in ([], ["curl"]):
            with self.subTest(package_ids=package_ids):
                status, response = self.http.request("POST", "/api/runtime/packages", {
                    "action": "deploy",
                    "distro": "debian",
                    "package_ids": package_ids,
                })
                self.assertEqual(status, 400, response)
                self.assertEqual(self.task_count(), 0)
        self.assertEqual(self.http.native.commands, [])

    def test_conversation_linkage_and_events_are_exposed_for_package_task(self) -> None:
        status, response = self.http.request("POST", "/api/conversations", {"title": "runtime packages"})
        self.assertEqual(status, 201, response)
        conversation_id = response["conversation"]["id"]

        _created, finished = self.http.run_approved({
            "package_ids": ["curl"],
            "distro": None,
            "conversation_id": conversation_id,
        })
        self.assertEqual(finished["conversation_id"], conversation_id)

        status, conversation = self.http.request("GET", f"/api/conversations/{conversation_id}")
        self.assertEqual(status, 200, conversation)
        self.assertEqual(conversation["tasks"][0]["id"], finished["id"])
        self.assertEqual(conversation["tasks"][0]["conversation_id"], conversation_id)
        self.assertEqual(conversation["conversation"]["current_task_id"], None)

        status, event_stream = self.http.request("GET", f"/api/tasks/{finished['id']}/events")
        self.assertEqual(status, 200, event_stream)
        events = []
        for block in event_stream.strip().split("\n\n"):
            event_name = next((line[7:] for line in block.splitlines() if line.startswith("event: ")), None)
            data_line = next((line[6:] for line in block.splitlines() if line.startswith("data: ")), None)
            if event_name:
                events.append((event_name, json.loads(data_line) if data_line else None))
        names = [name for name, _data in events]
        self.assertEqual(names[:2], ["task_started", "approval_required"])
        self.assertIn("approval_resolved", names)
        self.assertIn("tool_result", names)
        self.assertEqual(names[-1], "task_completed")
        resolved = next(data for name, data in events if name == "approval_resolved")
        self.assertTrue(resolved["approved"])

    def test_probe_reports_detected_versions_without_changing_packages(self) -> None:
        status, response = self.http.request("GET", "/api/runtime/packages?distro=termux&probe=true")

        self.assertEqual(status, 200, response)
        self.assertEqual(response["selected_distro"], "termux")
        self.assertEqual(response["native_packages"], "termux")
        self.assertEqual(response["versions"]["curl"], "curl 8.9.1")
        self.assertEqual(response["versions"]["node"], "v22.9.0")
        self.assertIsNone(response["version_error"])
        self.assertEqual(self.http.native.commands[0]["command"].splitlines()[0], "ver() {")

    def test_probe_is_rejected_for_an_undeployed_container(self) -> None:
        status, response = self.http.request("GET", "/api/runtime/packages?distro=debian&probe=true")

        self.assertEqual(status, 200, response)
        self.assertFalse(response["ready"])
        self.assertEqual(response["reason"], "distro_missing")
        self.assertEqual(self.http.native.commands, [])

    def test_ollama_is_only_available_inside_a_deployed_container(self) -> None:
        status, termux = self.http.request("GET", "/api/runtime/packages?distro=termux")
        self.assertEqual(status, 200, termux)
        by_id = {item["id"]: item for item in termux["packages"]}
        self.assertFalse(by_id["ollama"]["available"])
        self.assertIn("容器", by_id["ollama"]["detail"])
        self.assertEqual(termux["ollama"]["sha256"], self.http.manager.runtime_packages.status("termux")["ollama"]["sha256"])

        self.http.native.installed_distros.add("debian")
        status, debian = self.http.request("GET", "/api/runtime/packages?distro=debian")
        self.assertEqual(status, 200, debian)
        by_id = {item["id"]: item for item in debian["packages"]}
        self.assertTrue(by_id["ollama"]["available"])
        self.assertFalse(by_id["ollama"]["installed"])

    def test_missing_distro_status_is_not_ready_and_packages_are_unavailable(self) -> None:
        status, response = self.http.request("GET", "/api/runtime/packages?distro=debian")

        self.assertEqual(status, 200, response)
        self.assertFalse(response["ready"])
        self.assertEqual(response["selected_distro"], "debian")
        self.assertEqual(response["distros"], [
            {"id": "debian", "installed": False},
            {"id": "ubuntu", "installed": False},
        ])
        packages = {item["id"]: item for item in response["packages"]}
        self.assertFalse(packages["curl"]["available"])
        self.assertFalse(packages["coreutils"]["available"])


if __name__ == "__main__":
    unittest.main()
