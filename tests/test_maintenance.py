from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from android_agent.maintenance import AppMaintenance, LocalLog, validate_update
from android_agent.security import SecurityError, Workspace


class MemorySettings:
    def __init__(self):
        self.values={"model_name":"fixture","model_base_url":"https://example.test/v1","api_key":"never-export","cloud_consent":True,"disclaimer_accepted":True,"full_access":True,"blacklist":["blocked"],"update_manifest_url":""}
    def snapshot(self):
        return dict(self.values)
    def update(self,values):
        self.values.update(values)
        return self.snapshot()


class MaintenanceTests(unittest.TestCase):
    def test_logs_redact_filter_rotate_and_expire(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            log=LocalLog(root,lambda:["bearer-secret", "model-secret"],max_bytes=500)
            stale=root/"2000-01-01.jsonl"
            stale.write_text("{}",encoding="utf-8")
            log.log("INFO","startup model-secret", api_key="value", authorization="Bearer bearer-secret")
            log.log("WARN","connection failure", nested={"password":"value"})
            for _ in range(6):
                log.log("ERROR","x"*100)
            self.assertFalse(stale.exists())
            self.assertTrue(list(root.glob("*.gz")))
            exported=log.export()
            for secret in ["bearer-secret","model-secret",'"value"']:
                self.assertNotIn(secret,exported)
            rows=log.query("WARN","connection",20)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]["level"],"WARN")
            with self.assertRaises(ValueError):
                log.query("DEBUG")

    def test_update_manifest_validation_never_accepts_code_or_insecure_urls(self):
        item={"version":"1.2.3","download_url":"https://example.test/app.apk","sha256":"ab"*32,"notes":"hello"}
        validated=validate_update(item,"1.0.0")
        self.assertTrue(validated["update_available"])
        self.assertFalse(validated["automatic_install"])
        for value in [{**item,"download_url":"http://example.test/app.apk"},{**item,"sha256":"wrong"},{**item,"version":"latest"},{**item,"download_url":"https://user:pass@example.test/app.apk"}]:
            with self.assertRaises(ValueError):
                validate_update(value,"1.0.0")

    def test_backup_restore_preserves_old_binary_and_makes_undo_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace=Workspace(Path(folder)/"workspace")
            target=workspace.root/"nested/entry.bin"
            target.parent.mkdir()
            original=b"\x00\xff\x01binary"
            target.write_bytes(original)
            record=workspace.write("nested/entry.bin","new")
            restored=workspace.restore_backup(record["backup"],"nested/entry.bin")
            self.assertEqual(target.read_bytes(),original)
            self.assertEqual(workspace.read(restored["backup"]),"new")
            with self.assertRaises(SecurityError):
                workspace.restore_backup(record["backup"],"different")
            with self.assertRaises(SecurityError):
                workspace.restore_backup("../escape","nested/entry.bin")

    def test_maintenance_exports_no_authority_and_restores_only_bound_path(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            manager=SimpleNamespace(root=root,workspace=Workspace(root/"workspace"),settings=MemorySettings(),api_token="test-token",api_key="secret",android=SimpleNamespace(_native=None))
            maintenance=AppMaintenance(manager)
            manager.workspace.write("note.txt","one")
            backup=manager.workspace.write("note.txt","two")["backup"]
            rows=maintenance.backups()
            self.assertEqual(rows[0]["id"],backup)
            with self.assertRaises(SecurityError):
                maintenance.restore_backup(backup,"other.txt")
            maintenance.restore_backup(backup,"note.txt")
            self.assertEqual(manager.workspace.read("note.txt"),"one")
            exported=maintenance.export_config()
            for key in ["api_key","cloud_consent","disclaimer_accepted","full_access"]:
                self.assertNotIn(key,exported["settings"])
            maintenance.import_config({"format":"android-agent-config","version":1,"settings":{"model_name":"new","full_access":False,"api_key":"bad","cloud_consent":False}})
            self.assertEqual(manager.settings.snapshot()["model_name"],"new")
            self.assertEqual(manager.settings.snapshot()["api_key"],"never-export")
            self.assertFalse(manager.settings.snapshot()["cloud_consent"])
            self.assertFalse(manager.settings.snapshot()["model_enabled"])
            self.assertFalse(maintenance.check_updates()["configured"])
            self.assertFalse(maintenance.device_state()["supported"])


if __name__ == "__main__":
    unittest.main()
