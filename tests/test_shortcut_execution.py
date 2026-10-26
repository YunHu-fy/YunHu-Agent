"""Compatibility shortcuts must share the general command policy on real native bridges."""
import tempfile
import unittest
from pathlib import Path
from tests.test_v1_backend import MockNative, wait_for
from android_agent.android_bridge import AndroidBridge, command_for
from android_agent.config import SettingsStore
from android_agent.core import AgentManager
from android_agent.store import Store


class ShortcutExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.native = MockNative()
        self.settings = SettingsStore(root/'data/settings.json')
        self.settings.update({'disclaimer_accepted': True})
        self.manager = AgentManager(root, self.settings, Store(root/'data/agent.sqlite3'), 'shortcut-test', android=AndroidBridge(self.native))

    def tearDown(self):
        self.manager.shutdown()
        self.manager.executor.shutdown(wait=True, cancel_futures=True)
        self.temp.cleanup()

    def task(self, name, arguments, full=False):
        return self.manager.create_tool_task(name, arguments, full_access=full, full_access_confirmed=full, ui_authorized=full)

    def test_real_native_shortcut_uses_streaming_executor_and_blacklist(self):
        self.manager.channel = self.native.channel = 'root'
        task = self.task('android.tap', {'x': 10, 'y': 20}, True)
        self.assertTrue(task.done.wait(3))
        self.assertEqual(task.state, 'succeeded', task.error)
        self.assertEqual(self.native.requests[-1]['command'], '/system/bin/input tap 10 20')
        self.assertEqual(self.native.requests[-1]['channel'], 'root')
        self.settings.update({'blacklist':['/system/bin/input']})
        count = len(self.native.requests)
        denied = self.task('android.tap', {'x': 1, 'y': 2}, True)
        self.assertTrue(denied.done.wait(3))
        self.assertEqual(denied.state, 'failed')
        self.assertEqual(len(self.native.requests), count)

    def test_review_shortcut_approves_exact_script_not_removed_native_method(self):
        self.manager.channel = self.native.channel = 'shizuku'
        task = self.task('android.tap', {'x': 10, 'y': 20})
        approval = wait_for(lambda:task.snapshot()['pending_approval'])
        self.assertEqual(approval['tool'], 'shell.execute')
        self.assertEqual(approval['command'], '/system/bin/input tap 10 20')
        self.assertEqual(approval['cwd'], '/data/local/tmp')
        self.manager.decide(task.id, approval['approval_id'], True)
        self.assertTrue(task.done.wait(3))
        self.assertEqual(task.state, 'succeeded', task.error)

    def test_normal_shortcut_does_not_acquire_privileged_channel(self):
        task = self.task('android.tap', {'x': 10, 'y': 20}, True)
        self.assertTrue(task.done.wait(3))
        self.assertEqual(task.state, 'failed')
        self.assertEqual(self.native.requests, [])
        self.assertEqual(command_for('android.launch_app', {'package':'com.example.app'}, 'normal'), '/system/bin/monkey -p com.example.app -c android.intent.category.LAUNCHER 1')

if __name__ == '__main__':
    unittest.main()
