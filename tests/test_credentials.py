from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from android_agent.android_bridge import AndroidBridge


class NativeVault:
    def __init__(self):
        self.values = {}
        self.fail = False

    def credentialWrite(self, profile, value):
        if self.fail:
            return json.dumps({"ok": False, "error": {"message": "安全保存失败"}})
        self.values[profile] = value
        return json.dumps({"ok": True})

    def credentialRead(self, profile):
        if self.fail:
            return json.dumps({"ok": False, "error": {"message": "安全读取失败"}})
        return json.dumps({"ok": True, "value": self.values.get(profile, "")})

    def credentialDelete(self, profile):
        self.values.pop(profile, None)
        return json.dumps({"ok": True})


class CredentialAdapterTests(unittest.TestCase):
    def adapter(self, native=None):
        bridge = AndroidBridge()
        bridge._native = native
        return bridge

    def test_new_adapter_uses_same_native_vault_without_returning_key_as_settings(self):
        native = NativeVault()
        first = self.adapter(native)
        first.credential_set("profile-one", "sk-native-one")
        second = self.adapter(native)
        self.assertEqual(second.credential_get("profile-one"), "sk-native-one")
        self.assertEqual(second.credential_persistence, "android_keystore")
        self.assertNotIn("_session_credentials", vars(second))

    def test_profile_keys_stay_separate_and_delete_is_scoped(self):
        bridge = self.adapter(NativeVault())
        bridge.credential_set("one", "key-one")
        bridge.credential_set("two", "key-two")
        bridge.credential_delete("one")
        self.assertEqual(bridge.credential_get("one"), "")
        self.assertEqual(bridge.credential_get("two"), "key-two")

    def test_native_failure_never_falls_back_to_session_memory(self):
        native = NativeVault()
        native.fail = True
        bridge = self.adapter(native)
        with self.assertRaisesRegex(ValueError, "安全保存失败"):
            bridge.credential_set("one", "secret")
        with self.assertRaisesRegex(ValueError, "安全读取失败"):
            bridge.credential_get("one")
        self.assertNotIn("_session_credentials", vars(bridge))

    def test_desktop_fallback_is_explicitly_session_only(self):
        bridge = self.adapter()
        bridge.credential_set("one", "preview")
        self.assertEqual(bridge.credential_persistence, "memory_session")
        self.assertEqual(bridge.credential_get("one"), "preview")
        self.assertEqual(self.adapter().credential_get("one"), "")

    def test_missing_android_bridge_cannot_claim_key_was_saved(self):
        bridge = self.adapter()
        with patch("android_agent.android_bridge.sys.platform", "android"):
            with self.assertRaisesRegex(ValueError, "密钥没有保存"):
                bridge.credential_set("one", "secret")
        self.assertNotIn("_session_credentials", vars(bridge))


if __name__ == "__main__":
    unittest.main()
