from __future__ import annotations

import json
import os
import shlex
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from android_agent import workflows
from android_agent.security import SecurityError, Workspace


DIGEST = "a" * 64
INSTALL = {"url": "https://example.test/app.apk", "sha256": DIGEST}
BACKUP = {"package": "com.example.app", "archive": "app.tar.gz"}


def command_result(stdout="", *, ok=True, exit_code=0, status="succeeded", stderr=""):
    return {"ok": ok, "stdout": stdout, "stderr": stderr, "exit_code": exit_code, "status": status}


class Cancelled(Exception):
    pass


class FakeAndroid:
    def __init__(self, channel="root", granted=True, available=True):
        self.available = available
        self.channel, self.granted = channel, granted

    def status(self):
        return {"selected_channel": self.channel, "root": {"available": True, "granted": self.granted}, "shizuku": {"available": True, "granted": self.granted}}


class FakeManager:
    def __init__(self, channel="root"):
        self.android = FakeAndroid(channel)
        self.calls = []
        self.digest = DIGEST
        self.dependencies = "/system/bin/curl\n/system/bin/sha256sum\n"
        self.handler = None

    def execute_command(self, task, arguments):
        self.calls.append(dict(arguments))
        task.check_cancelled()
        if self.handler:
            handled = self.handler(task, arguments)
            if handled is not None:
                return handled
        command = arguments["command"]
        tokens = shlex.split(command)
        if command == "id -u":
            return command_result("0\n" if task.channel == "root" else "2000\n")
        if command == "command -v curl && command -v sha256sum":
            return command_result(self.dependencies)
        if command == "command -v tar && command -v ln && command -v mktemp":
            return command_result("/system/bin/tar\n/system/bin/ln\n/system/bin/mktemp\n")
        if "mktemp" in tokens:
            return command_result(tokens[-1].replace("XXXXXXXX", "a1b2c3d4") + "\n")
        if tokens[0].endswith("/sha256sum"):
            return command_result(self.digest + "  " + tokens[-1] + "\n")
        if tokens[:2] == ["pm", "install"]:
            return command_result("Success\n")
        return command_result()


class FakeTask:
    def __init__(self, *, channel="root", runtime="system", full_access=False):
        self.channel, self.runtime, self.full_access = channel, runtime, full_access
        self.manager = FakeManager(channel)
        self.approvals = []
        self.approve = True
        self.on_approval = None
        self.cancelled = False

    def check_cancelled(self):
        if self.cancelled:
            raise Cancelled("cancelled by user")

    def request_approval(self, name, args):
        self.check_cancelled()
        self.approvals.append((name, dict(args)))
        if self.on_approval:
            self.on_approval()
        return self.approve


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Workspace(Path(self.temp.name))
        self.task = FakeTask()

    def run_workflow(self, name, args, task=None):
        return workflows.run("workflow." + name, args, self.workspace, task or self.task)

    def image(self, name, content=b"image"):
        target = self.workspace.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target

    def commands(self):
        return [call["command"] for call in self.task.manager.calls]

    def test_definitions_and_normalized_defaults(self):
        definitions = workflows.definitions()
        self.assertEqual({item["name"] for item in definitions}, {"workflow.install_apk", "workflow.rename_images", "workflow.backup_app"})
        self.assertTrue(all(item["inputSchema"]["additionalProperties"] is False for item in definitions))
        args = workflows.validate("workflow.rename_images", {"directory": "", "prefix": "image_", "extensions": ["JPG", ".png", ".jpg"]})
        self.assertEqual(args["extensions"], [".jpg", ".png"])
        self.assertTrue(args["dry_run"])
        self.assertEqual(args["start"], 1)
        self.assertFalse(workflows.validate("workflow.install_apk", INSTALL)["launch"])

    def test_validation_rejects_unsafe_or_untyped_arguments(self):
        cases = [
            ("install_apk", {"url": "http://example.test/app.apk", "sha256": DIGEST}),
            ("install_apk", {"url": "https://user:pass@example.test/app.apk", "sha256": DIGEST}),
            ("install_apk", {"url": "https://example.test/app.apk\n", "sha256": DIGEST}),
            ("install_apk", {"url": "https://example.test:bad/app.apk", "sha256": DIGEST}),
            ("install_apk", {"url": "https://example.test/app.apk"}),
            ("install_apk", {**INSTALL, "sha256": "a" * 63}),
            ("install_apk", {**INSTALL, "launch": True}),
            ("install_apk", {**INSTALL, "package": "com.example;reboot"}),
            ("install_apk", {**INSTALL, "channel": "root"}),
            ("rename_images", {"directory": "../photos", "prefix": "x"}),
            ("rename_images", {"directory": "C:/photos", "prefix": "x"}),
            ("rename_images", {"directory": chr(92).join(["photos", "nested"]), "prefix": "x"}),
            ("rename_images", {"directory": "", "prefix": ".." + chr(92) + "outside"}),
            ("backup_app", {"package": "com.example.app", "archive": ".." + chr(92) + "app.tar.gz"}),
            ("rename_images", {"directory": "", "prefix": "../x"}),
            ("rename_images", {"directory": "", "prefix": "CON.", "start": 0}),
            ("rename_images", {"directory": "", "prefix": "x", "start": True}),
            ("rename_images", {"directory": "", "prefix": "x", "dry_run": 1}),
            ("rename_images", {"directory": "", "prefix": "x", "extensions": ["../jpg"]}),
            ("backup_app", {"package": "com.example.app", "archive": "../app.tar.gz"}),
            ("backup_app", {"package": "com.example.app", "archive": "app.zip"}),
        ]
        for name, args in cases:
            with self.subTest(name=name, args=args), self.assertRaises(ValueError):
                workflows.validate("workflow." + name, args)

    def test_rename_dry_run_is_deterministic_and_has_no_approval_or_mutations(self):
        self.image("photos/b.jpg", b"b")
        self.image("photos/A.PNG", b"a")
        self.image("photos/ignore.txt")
        result = self.run_workflow("rename_images", {"directory": "photos", "prefix": "pic_", "start": 8})
        self.assertEqual([(item["source"], item["target"]) for item in result["plan"]], [("photos/A.PNG", "photos/pic_8.PNG"), ("photos/b.jpg", "photos/pic_9.jpg")])
        self.assertEqual(result["renamed"], 0)
        self.assertEqual(self.task.approvals, [])
        self.assertFalse((self.workspace.root / ".backups").exists())
        self.assertTrue((self.workspace.root / "photos/A.PNG").exists())
        self.assertEqual(self.task.manager.calls, [])

    def test_rename_apply_approves_normalized_arguments_and_writes_rollback_manifest(self):
        self.image("a.jpg", b"first")
        self.image("b.jpg", b"second")
        result = self.run_workflow("rename_images", {"directory": "", "prefix": "image_", "dry_run": False, "extensions": ["JPG"]})
        self.assertTrue(result["ok"])
        self.assertEqual(result["renamed"], 2)
        self.assertEqual((self.workspace.root / "image_1.jpg").read_bytes(), b"first")
        self.assertFalse((self.workspace.root / "a.jpg").exists())
        self.assertEqual(self.task.approvals[0][0], "workflow.rename_images")
        self.assertEqual(self.task.approvals[0][1]["extensions"], [".jpg"])
        self.assertTrue(result["manifest"].startswith(".backups/"))
        manifest = json.loads(self.workspace._resolved(result["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual(manifest["rollback"], [{"source": "image_2.jpg", "target": "b.jpg"}, {"source": "image_1.jpg", "target": "a.jpg"}])
        for item in manifest["rollback"]:
            os.rename(self.workspace._resolved(item["source"]), self.workspace._resolved(item["target"]))
        self.assertEqual((self.workspace.root / "a.jpg").read_bytes(), b"first")
        self.assertEqual(self.task.manager.calls, [])

    def test_full_access_rename_skips_approval(self):
        self.image("a.jpg")
        self.task.full_access = True
        self.assertTrue(self.run_workflow("rename_images", {"directory": "", "prefix": "x", "dry_run": False})["ok"])
        self.assertEqual(self.task.approvals, [])

    def test_rename_denial_and_cancellation_before_mutation(self):
        source = self.image("a.jpg")
        self.task.approve = False
        with self.assertRaises(PermissionError):
            self.run_workflow("rename_images", {"directory": "", "prefix": "x", "dry_run": False})
        self.assertTrue(source.exists())
        self.assertFalse((self.workspace.root / ".backups").exists())
        self.task.approve = True
        self.task.on_approval = lambda: setattr(self.task, "cancelled", True)
        with self.assertRaises(Cancelled):
            self.run_workflow("rename_images", {"directory": "", "prefix": "x", "dry_run": False})
        self.assertTrue(source.exists())
        self.assertFalse((self.workspace.root / ".backups").exists())

    def test_rename_collision_never_overwrites_including_case_only(self):
        self.image("a.jpg", b"original")
        target = self.image("PIC1.JPG", b"existing")
        with self.assertRaises(FileExistsError):
            self.run_workflow("rename_images", {"directory": "", "prefix": "pic", "dry_run": False, "extensions": ["jpg"]})
        self.assertEqual(target.read_bytes(), b"existing")
        self.assertEqual(self.task.approvals, [])

    def test_rename_rechecks_pending_approval_changes(self):
        self.image("a.jpg")
        self.task.on_approval = lambda: self.image("b.jpg")
        with self.assertRaises(SecurityError):
            self.run_workflow("rename_images", {"directory": "", "prefix": "x", "dry_run": False})
        self.assertTrue((self.workspace.root / "a.jpg").exists())
        self.assertFalse((self.workspace.root / ".backups").exists())

    def test_rename_rolls_back_after_midway_failure(self):
        self.image("a.jpg", b"a")
        self.image("b.jpg", b"b")
        real_move = workflows._Directory.move
        def fail_second(directory, source, target):
            if source == "b.jpg":
                raise OSError("simulated rename failure")
            return real_move(directory, source, target)
        with patch.object(workflows._Directory, "move", fail_second), self.assertRaisesRegex(OSError, "simulated"):
            self.run_workflow("rename_images", {"directory": "", "prefix": "x", "dry_run": False})
        self.assertEqual((self.workspace.root / "a.jpg").read_bytes(), b"a")
        self.assertEqual((self.workspace.root / "b.jpg").read_bytes(), b"b")
        progress = next((self.workspace.root / ".backups").glob("*.progress.json"))
        self.assertEqual(json.loads(progress.read_text(encoding="utf-8"))["status"], "rolled_back")

    def test_rename_rolls_back_after_cancellation_between_mutations(self):
        self.image("a.jpg")
        self.image("b.jpg")
        real_move = workflows._Directory.move
        def cancel_after_move(directory, source, target):
            real_move(directory, source, target)
            if source == "a.jpg":
                self.task.cancelled = True
        with patch.object(workflows._Directory, "move", cancel_after_move), self.assertRaises(Cancelled):
            self.run_workflow("rename_images", {"directory": "", "prefix": "x", "dry_run": False})
        self.assertTrue((self.workspace.root / "a.jpg").exists())
        self.assertFalse((self.workspace.root / "x1.jpg").exists())

    def test_rename_atomic_move_does_not_clobber_racing_target(self):
        self.image("a.jpg", b"original")
        real_move = workflows._Directory.move
        def race(directory, source, target):
            (directory.path / target).write_bytes(b"racer")
            return real_move(directory, source, target)
        with patch.object(workflows._Directory, "move", race), self.assertRaises(FileExistsError):
            self.run_workflow("rename_images", {"directory": "", "prefix": "x", "dry_run": False})
        self.assertEqual((self.workspace.root / "a.jpg").read_bytes(), b"original")
        self.assertEqual((self.workspace.root / "x1.jpg").read_bytes(), b"racer")

    def test_rename_rejects_backup_directory(self):
        self.image(".backups/a.jpg")
        with self.assertRaises(SecurityError):
            self.run_workflow("rename_images", {"directory": ".backups", "prefix": "x"})

    def test_rename_rejects_symlink_directory_and_image(self):
        outside = self.workspace.root / "outside"
        outside.mkdir()
        (outside / "a.jpg").write_bytes(b"safe")
        link = self.workspace.root / "link"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Host does not permit creating symlinks")
        if not link.is_symlink():
            self.skipTest("Host filesystem did not create a real symlink")
        with self.assertRaises(SecurityError):
            self.run_workflow("rename_images", {"directory": "link", "prefix": "x"})
        (self.workspace.root / "linked.jpg").symlink_to(outside / "a.jpg")
        if not (self.workspace.root / "linked.jpg").is_symlink():
            self.skipTest("Host filesystem did not create a real symlink")
        with self.assertRaises(SecurityError):
            self.run_workflow("rename_images", {"directory": "", "prefix": "x"})

    def test_install_verifies_hash_then_installs_and_optionally_launches(self):
        result = self.run_workflow("install_apk", {**INSTALL, "package": "com.example.app", "launch": True})
        self.assertTrue(result["ok"])
        labels = [step["step"] for step in result["steps"]]
        self.assertLess(labels.index("sha256"), labels.index("install"))
        self.assertLess(labels.index("install"), labels.index("launch"))
        self.assertEqual(labels[-1], "cleanup")
        self.assertTrue(all(call["channel"] == "root" for call in self.task.manager.calls))
        self.assertFalse(any("pkg install" in cmd or "apt " in cmd or "su " in cmd for cmd in self.commands()))
        self.assertEqual(self.task.approvals, [])

    def test_install_mismatch_does_not_install_and_still_cleans_up(self):
        self.task.manager.digest = "b" * 64
        result = self.run_workflow("install_apk", INSTALL)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_step"], "sha256")
        self.assertFalse(any(cmd.startswith("pm install") for cmd in self.commands()))
        self.assertEqual(result["steps"][-1]["step"], "cleanup")

    def test_install_url_is_one_quoted_argument_and_redirects_require_https(self):
        url = "https://example.test/app.apk?x=';$(reboot)&y=1"
        result = self.run_workflow("install_apk", {**INSTALL, "url": url})
        self.assertTrue(result["ok"])
        command = next(cmd for cmd in self.commands() if "--proto-redir" in cmd)
        tokens = shlex.split(command)
        self.assertEqual(tokens[-1], url)
        self.assertEqual(tokens[tokens.index("--proto") + 1], "=https")
        self.assertEqual(tokens[tokens.index("--proto-redir") + 1], "=https")

    def test_install_termux_runtime_only_for_download_and_hash(self):
        self.task.runtime = "termux"
        self.task.manager.dependencies = "/data/data/com.termux/files/usr/bin/curl\n/data/data/com.termux/files/usr/bin/sha256sum\n"
        self.assertTrue(self.run_workflow("install_apk", INSTALL)["ok"])
        install = next(call for call in self.task.manager.calls if call["command"].startswith("pm install"))
        download = next(call for call in self.task.manager.calls if "--proto-redir" in call["command"])
        self.assertEqual(install["runtime"], "system")
        self.assertEqual(download["runtime"], "termux")

    def test_install_shizuku_system_and_private_prefix_restrictions(self):
        self.task = FakeTask(channel="shizuku")
        self.assertTrue(self.run_workflow("install_apk", INSTALL)["ok"])
        self.assertTrue(all(call["channel"] == "shizuku" for call in self.task.manager.calls))
        self.task.manager.calls.clear()
        self.task.manager.dependencies = "/data/data/com.termux/files/usr/bin/curl\n/system/bin/sha256sum\n"
        result = self.run_workflow("install_apk", INSTALL)
        self.assertFalse(result["ok"])
        self.assertIn("Termux", result["error"])
        self.assertFalse(any(cmd.startswith("mkdir") for cmd in self.commands()))
        self.task.runtime = "termux"
        with self.assertRaisesRegex(PermissionError, "Termux"):
            self.run_workflow("install_apk", INSTALL)

    def test_commands_require_actual_selected_capability_and_no_desktop_fallback(self):
        for name, args in [("install_apk", INSTALL), ("backup_app", BACKUP)]:
            for setup in [lambda t: setattr(t.manager.android, "available", False), lambda t: setattr(t.manager.android, "granted", False), lambda t: setattr(t.manager.android, "channel", "normal"), lambda t: setattr(t, "channel", "normal"), lambda t: setattr(t, "runtime", "powershell")]:
                task = FakeTask()
                setup(task)
                with self.subTest(name=name), self.assertRaises(PermissionError):
                    self.run_workflow(name, args, task)
                self.assertEqual(task.manager.calls, [])

    def test_install_stops_on_shared_policy_failure(self):
        self.task.manager.handler = lambda task, args: command_result(ok=False, exit_code=None, status="blocked", stderr="blacklist") if "--proto-redir" in args["command"] else None
        result = self.run_workflow("install_apk", INSTALL)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_step"], "download")
        self.assertFalse(any(cmd.startswith("pm install") for cmd in self.commands()))

    def test_backup_is_root_only_and_checks_actual_uid(self):
        task = FakeTask(channel="shizuku")
        with self.assertRaises(PermissionError):
            self.run_workflow("backup_app", BACKUP, task)
        self.assertEqual(task.manager.calls, [])
        self.task.manager.handler = lambda task, args: command_result("2000\n") if args["command"] == "id -u" else None
        result = self.run_workflow("backup_app", BACKUP)
        self.assertEqual(result["failed_step"], "identity")
        self.assertFalse(any("force-stop" in cmd for cmd in self.commands()))

    def test_backup_archives_private_data_and_atomically_publishes_then_restarts(self):
        self.task.runtime = "termux"
        result = self.run_workflow("backup_app", BACKUP)
        self.assertTrue(result["ok"])
        commands = self.commands()
        tar_command = next(cmd for cmd in commands if "tar -czf" in cmd)
        self.assertIn("/data/user/0", shlex.split(tar_command))
        self.assertEqual(shlex.split(tar_command)[-1], "com.example.app")
        publication = next(cmd for cmd in commands if cmd.startswith("ln "))
        self.assertEqual(shlex.split(publication)[:3], ["ln", "-T", "--"])
        self.assertEqual(shlex.split(publication)[-1], (self.workspace.root / BACKUP["archive"]).as_posix())
        labels = [item["step"] for item in result["steps"]]
        self.assertLess(labels.index("force_stop"), labels.index("archive"))
        self.assertLess(labels.index("publish"), labels.index("restart"))
        self.assertEqual(labels[-1], "cleanup")
        self.assertTrue(all(call["runtime"] == "system" for call in self.task.manager.calls))

    def test_backup_tar_failure_keeps_failure_and_restarts_finally(self):
        self.task.manager.handler = lambda task, args: command_result(ok=False, exit_code=2, stderr="tar failed") if "tar -czf" in args["command"] else None
        result = self.run_workflow("backup_app", BACKUP)
        self.assertFalse(result["ok"])
        self.assertEqual(result["failed_step"], "archive")
        self.assertTrue(any(cmd.startswith("monkey ") for cmd in self.commands()))
        self.assertFalse(any(cmd.startswith("ln ") for cmd in self.commands()))
        self.assertEqual(result["steps"][-1]["step"], "cleanup")

    def test_backup_exception_and_cancellation_attempt_finally_through_shared_manager(self):
        def exception(task, args):
            if "tar -czf" in args["command"]:
                raise OSError("native archive error")
        self.task.manager.handler = exception
        with self.assertRaisesRegex(OSError, "native archive"):
            self.run_workflow("backup_app", BACKUP)
        self.assertTrue(any(cmd.startswith("monkey ") for cmd in self.commands()))
        self.assertTrue(any(cmd.startswith("rm -f") for cmd in self.commands()))
        self.task = FakeTask()
        def cancel(task, args):
            if "tar -czf" in args["command"]:
                task.cancelled = True
                raise Cancelled("cancelled archive")
        self.task.manager.handler = cancel
        with self.assertRaises(Cancelled):
            self.run_workflow("backup_app", BACKUP)
        self.assertTrue(any(cmd.startswith("monkey ") for cmd in self.commands()))
        self.assertTrue(any(cmd.startswith("rm -f") for cmd in self.commands()))

    def test_recovery_failures_remain_visible_on_original_exception(self):
        for name, args, marker in [("install_apk", INSTALL, "--proto-redir"), ("backup_app", BACKUP, "tar -czf")]:
            self.task = FakeTask()
            def cancel(task, arguments):
                if marker in arguments["command"]:
                    task.cancelled = True
                    raise Cancelled("original cancellation")
            self.task.manager.handler = cancel
            with self.subTest(name=name), self.assertRaisesRegex(Cancelled, "workflow recovery") as raised:
                self.run_workflow(name, args)
            self.assertIn("staging_directory", raised.exception.workflow_recovery)

    def test_rename_rollback_failure_has_recovery_manifest_and_no_overwrite(self):
        self.image("a.jpg", b"original")
        self.image("b.jpg", b"second")
        real_move = workflows._Directory.move
        def fail_with_collision(directory, source, target):
            if source == "b.jpg":
                (directory.path / "a.jpg").write_bytes(b"concurrent")
                raise OSError("rename interrupted")
            return real_move(directory, source, target)
        with patch.object(workflows._Directory, "move", fail_with_collision), self.assertRaisesRegex(OSError, "workflow recovery") as raised:
            self.run_workflow("rename_images", {"directory": "", "prefix": "x", "dry_run": False})
        self.assertEqual((self.workspace.root / "a.jpg").read_bytes(), b"concurrent")
        self.assertEqual((self.workspace.root / "x1.jpg").read_bytes(), b"original")
        recovery = raised.exception.workflow_recovery
        manifest = json.loads(self.workspace._resolved(recovery["manifest"]).read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "rollback_failed")
        self.assertEqual(manifest["rollback"], [{"source": "x1.jpg", "target": "a.jpg"}])

    def test_rename_reparse_point_is_blocked_even_without_symlink_privilege(self):
        self.image("photos/a.jpg")
        from android_agent import security
        real_check = security.is_link_or_reparse
        def reparse(path):
            return path.name == "photos" or real_check(path)
        with patch.object(security, "is_link_or_reparse", reparse), self.assertRaises(SecurityError):
            self.run_workflow("rename_images", {"directory": "photos", "prefix": "x", "dry_run": False})
        self.assertTrue((self.workspace.root / "photos/a.jpg").exists())
        self.assertEqual(self.task.approvals, [])

    def test_backup_existing_archive_never_runs_commands(self):
        self.image("app.tar.gz", b"existing")
        with self.assertRaises(SecurityError):
            self.run_workflow("backup_app", BACKUP)
        self.assertEqual(self.task.manager.calls, [])
        self.assertEqual((self.workspace.root / "app.tar.gz").read_bytes(), b"existing")

    def test_cleanup_or_restart_failure_is_not_reported_as_success(self):
        for name, args in [("install_apk", INSTALL), ("backup_app", BACKUP)]:
            self.task = FakeTask()
            self.task.manager.handler = lambda task, args: command_result(ok=False, exit_code=1, stderr="cleanup failed") if args["command"].startswith("rm -f") else None
            result = self.run_workflow(name, args)
            self.assertFalse(result["ok"])
            self.assertEqual(result["status"], "failed")
        self.task = FakeTask()
        self.task.manager.handler = lambda task, args: command_result(ok=False, exit_code=1, stderr="no launcher") if args["command"].startswith("monkey ") else None
        result = self.run_workflow("backup_app", BACKUP)
        self.assertFalse(result["ok"])
        self.assertIn("restart", result["finalization_errors"][0])


if __name__ == "__main__":
    unittest.main()
