from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from android_agent.android_bridge import AndroidBridge, validate
from android_agent.config import SettingsStore
from android_agent.core import AgentManager
from android_agent.store import Store


class FakeNative:
    def __init__(self):
        self.channel = "normal"
        self.calls = []

    def status(self):
        return json.dumps({"ok": True, "selected_channel":self.channel, "normal":{"available":True,"granted":True}, "shizuku":{"available":True,"granted":True}, "root":{"available":True,"granted":False}})

    def configureChannel(self, channel):
        self.channel = channel
        return json.dumps({"ok":True,"selected_channel":channel})

    def execute(self, op, args, channel):
        self.calls.append((op, json.loads(args), channel))
        return json.dumps({"ok":True,"operation":op,"channel":channel,"result":{"stdout":"fixture","stderr":"","exit_code":0}})

    def cancelAll(self):
        return '{"ok":true}'


def pending(task, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        request = task.snapshot()["pending_approval"]
        if request:
            return request
        time.sleep(0.01)
    raise AssertionError("approval was not requested")


class AndroidToolTests(unittest.TestCase):
    def test_schema_rejects_injection_and_range_errors(self):
        cases = [("android.tap", {"x":-1,"y":3}), ("android.tap", {"x":True,"y":3}), ("android.keyevent", {"key":"26;reboot"}), ("android.launch_app", {"package":"com.example;su"}), ("android.brightness", {"value":256}), ("android.swipe", {"x1":1,"x2":2,"y1":3,"y2":4,"duration_ms":4000}), ("android.reboot", {}), ("android.reboot", {"confirm":"yes"}), ("android.battery", {"channel":"root"})]
        for name, args in cases:
            with self.subTest(name=name,args=args), self.assertRaises(ValueError):
                validate(name,args)
        self.assertEqual(validate("android.tap", {"x":123,"y":456}), {"x":123,"y":456})

    def test_desktop_never_executes_android_commands(self):
        bridge = AndroidBridge()
        self.assertFalse(bridge.available)
        self.assertEqual(bridge.execute("android.battery", {}, "normal")["status"], "unsupported")
        with self.assertRaises(ValueError):
            bridge.configure("root")

    def test_permission_selection_and_device_call_each_need_fresh_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manager = AgentManager(root, SettingsStore(root/"data/settings.json"), Store(root/"data/agent.sqlite3"), "fixture")
            manager.settings.update({"disclaimer_accepted":True})
            native = FakeNative()
            manager.android._native = native
            try:
                configure = manager.create_channel_task("shizuku")
                approval = pending(configure)
                self.assertEqual(approval["arguments"]["target_channel"], "shizuku")
                self.assertEqual(native.channel,"normal")
                manager.decide(configure.id,approval["approval_id"],True)
                self.assertTrue(configure.done.wait(3))
                self.assertEqual(manager.channel,"shizuku")
                task = manager.create_tool_task("android.tap",{"x":3,"y":4})
                approval = pending(task)
                self.assertEqual(approval["channel"],"shizuku")
                self.assertFalse(manager.decide(task.id,"wrong",True))
                self.assertEqual(native.calls,[])
                manager.decide(task.id,approval["approval_id"],True)
                self.assertTrue(task.done.wait(3))
                self.assertEqual(native.calls,[("tap",{"x":3,"y":4},"shizuku")])
                self.assertEqual(task.state,"succeeded")
                task = manager.create_tool_task("android.tap",{"x":3,"y":4})
                approval = pending(task)
                manager.channel="normal"
                manager.decide(task.id,approval["approval_id"],True)
                self.assertTrue(task.done.wait(3))
                self.assertEqual(task.state,"failed")
                self.assertEqual(len(native.calls),1)
            finally:
                manager.shutdown()
                manager.executor.shutdown(wait=True,cancel_futures=True)

    def test_native_failure_marks_task_failed_and_audit_redacts_nested_output(self):
        from android_agent.tools import audit_result
        result = {"ok":False,"error":{"code":"permission_denied","message":"Denied"},"result":{"stdout":"private stdout","stderr":"private stderr","exit_code":1}}
        filtered = audit_result(result)
        self.assertNotIn("private", json.dumps(filtered))
        self.assertEqual(filtered["result"]["stdout_bytes"],14)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manager = AgentManager(root, SettingsStore(root/"data/settings.json"), Store(root/"data/agent.sqlite3"), "fixture")
            manager.settings.update({"disclaimer_accepted":True})
            native=FakeNative()
            native.execute=lambda *args: json.dumps(result)
            manager.android._native=native
            try:
                task=manager.create_tool_task("android.battery",{})
                approval=pending(task)
                manager.decide(task.id,approval["approval_id"],True)
                self.assertTrue(task.done.wait(3))
                self.assertEqual(task.state,"failed")
                self.assertIn("Denied",task.error)
                events=manager.store.events_after(task.id,0)
                self.assertFalse(any(item["event"] == "task_completed" for item in events))
            finally:
                manager.shutdown()
                manager.executor.shutdown(wait=True,cancel_futures=True)

    def test_reboot_confirmation_removed_before_fixed_native_command(self):
        bridge = AndroidBridge()
        native = FakeNative()
        bridge._native = native
        bridge.execute("android.reboot", {"confirm":"REBOOT"}, "root")
        self.assertEqual(native.calls,[("reboot",{},"root")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
