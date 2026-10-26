from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("apk_verifier", ROOT / "android/verify_apk.py")
assert SPEC and SPEC.loader
apk_verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(apk_verifier)


class BootstrapVerifierTests(unittest.TestCase):
    def test_accepts_all_required_bootstrap_tools(self):
        names = {"bin/" + tool for tool in apk_verifier.REQUIRED_BOOTSTRAP_TOOLS}
        apk_verifier.verify_bootstrap_tools(names)

    def test_requires_tar_and_gzip(self):
        for tool in ("tar", "gzip"):
            with self.subTest(tool=tool):
                names = {"bin/" + name for name in apk_verifier.REQUIRED_BOOTSTRAP_TOOLS}
                names.remove("bin/" + tool)
                with self.assertRaisesRegex(ValueError, f"Bootstrap tool missing: {tool}"):
                    apk_verifier.verify_bootstrap_tools(names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
