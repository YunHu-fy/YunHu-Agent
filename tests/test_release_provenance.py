from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

provenance = load("release_provenance_test", ROOT / "scripts/release_provenance.py")
build_release = load("build_release_test", ROOT / "scripts/build_release.py")
package_v1 = load("package_v1_test", ROOT / "scripts/package_v1.py")


class ReleaseProvenanceTests(unittest.TestCase):
    def fixture(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        (root / "android/app/build/outputs/apk/debug").mkdir(parents=True)
        (root / "android/app/build/outputs/apk/release").mkdir(parents=True)
        (root / "android/app/src/main/res").mkdir(parents=True)
        (root / "android_agent").mkdir()
        (root / "web/static").mkdir(parents=True)
        (root / "scripts").mkdir()
        (root / "android_agent/__init__.py").write_text('__version__ = "1.3.5"\n', encoding="utf-8")
        (root / "android/app/build.gradle.kts").write_text(
            'versionCode = 10305\nversionName = "1.3.5"\n', encoding="utf-8")
        (root / "android/app/src/main/res/layout.xml").write_text("original", encoding="utf-8")
        (root / "android_agent/runner.py").write_text("print(1)\n", encoding="utf-8")
        (root / "web/index.html").write_text("<html />", encoding="utf-8")
        (root / "web/static/app.js").write_text("ok", encoding="utf-8")
        for variant in provenance.VARIANTS:
            (root / f"android/app/build/outputs/apk/{variant}/app-{variant}.apk").write_bytes(
                (variant + "-apk").encode("ascii"))
        return temp, root

    def test_snapshot_covers_android_python_and_web_and_excludes_generated_state(self):
        temp, root = self.fixture()
        with temp:
            (root / "android/app/build/generated.bin").write_bytes(b"ignored")
            downloads = root / "android/vendor/termux/downloads"
            downloads.mkdir(parents=True)
            (downloads / "bootstrap.apk").write_bytes(b"ignored download")
            snapshot = provenance.source_snapshot(root)
            names = {record["path"] for record in snapshot["files"]}
            self.assertIn("android/app/build.gradle.kts", names)
            self.assertIn("android_agent/runner.py", names)
            self.assertIn("web/static/app.js", names)
            self.assertNotIn("android/app/build/generated.bin", names)
            self.assertNotIn("android/vendor/termux/downloads/bootstrap.apk", names)

    def test_verify_rejects_android_source_change_and_apk_change(self):
        temp, root = self.fixture()
        with temp:
            metadata = provenance.release_metadata(root)
            manifest = provenance.start_manifest(root, metadata)
            manifest = provenance.finish_manifest(root, manifest, provenance.source_snapshot(root))
            provenance.write_manifest(root, manifest)
            self.assertEqual(provenance.verify_build_manifest(root)["status"], "success")
            (root / "android/app/src/main/res/layout.xml").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Build sources changed"):
                provenance.verify_build_manifest(root)
            (root / "android/app/src/main/res/layout.xml").write_text("original", encoding="utf-8")
            (root / "android/app/build/outputs/apk/debug/app-debug.apk").write_bytes(b"changed apk")
            with self.assertRaisesRegex(ValueError, "debug APK differs"):
                provenance.verify_build_manifest(root)

    def test_build_runner_records_source_drift_without_real_build(self):
        temp, root = self.fixture()
        with temp:
            def fake_runner(command, cwd, env, stdout, stderr, shell):
                self.assertIn(":app:assembleRelease", command)
                (root / "android/app/src/main/res/layout.xml").write_text("mutated during build", encoding="utf-8")
                return type("Result", (), {"returncode": 0})()
            self.assertEqual(build_release.run_build(root, runner=fake_runner, environ={"JAVA_HOME": "fake"}, platform="posix"), 1)
            manifest = json.loads(provenance.manifest_path(root, "1.3.5").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "failed")
            self.assertEqual(manifest["failure"], "build_source_changed_during_build")

    def test_packaging_rejects_source_and_apk_drift_before_other_artifacts(self):
        temp, root = self.fixture()
        with temp:
            old_values = (package_v1.ROOT, package_v1.METADATA, package_v1.VERSION,
                          package_v1.VERIFICATION, package_v1.SIGNATURES, package_v1.BUILD_LOG)
            package_v1.ROOT = root
            package_v1.METADATA = provenance.release_metadata(root)
            package_v1.VERSION = package_v1.METADATA["version"]
            package_v1.VERIFICATION = root / "artifacts/verification.json"
            package_v1.SIGNATURES = root / "artifacts/signatures.txt"
            package_v1.BUILD_LOG = root / "artifacts/build.txt"
            try:
                manifest = provenance.start_manifest(root, package_v1.METADATA)
                manifest = provenance.finish_manifest(root, manifest, provenance.source_snapshot(root))
                provenance.write_manifest(root, manifest)
                (root / "android/app/src/main/res/layout.xml").write_text("changed", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Build sources changed"):
                    package_v1.verified_apks()
                (root / "android/app/src/main/res/layout.xml").write_text("original", encoding="utf-8")
                (root / "android/app/build/outputs/apk/release/app-release.apk").write_bytes(b"replacement")
                with self.assertRaisesRegex(ValueError, "release APK differs"):
                    package_v1.verified_apks()
            finally:
                (package_v1.ROOT, package_v1.METADATA, package_v1.VERSION,
                 package_v1.VERIFICATION, package_v1.SIGNATURES, package_v1.BUILD_LOG) = old_values

    def test_selected_set_includes_delivery_helper_when_present(self):
        temp, root = self.fixture()
        with temp:
            (root / "artifacts").mkdir()
            helper = root / "artifacts/package_delivery.py"
            helper.write_text("delivery", encoding="utf-8")
            old_values = (package_v1.ROOT, package_v1.DIRECTORIES, package_v1.FILES,
                          package_v1.EVIDENCE_PATTERNS, package_v1.DELIVERY_HELPER)
            package_v1.ROOT = root
            package_v1.DIRECTORIES = []
            package_v1.FILES = []
            package_v1.EVIDENCE_PATTERNS = []
            package_v1.DELIVERY_HELPER = helper
            try:
                self.assertIn(helper, package_v1.sources())
            finally:
                (package_v1.ROOT, package_v1.DIRECTORIES, package_v1.FILES,
                 package_v1.EVIDENCE_PATTERNS, package_v1.DELIVERY_HELPER) = old_values

    def test_source_zip_requires_exact_entries_and_hashes(self):
        temp, root = self.fixture()
        with temp:
            # package_v1's helper is tested with a temporary root, not the checkout.
            old_root, old_helper = package_v1.ROOT, package_v1.DELIVERY_HELPER
            package_v1.ROOT = root
            package_v1.DELIVERY_HELPER = root / "artifacts/package_delivery.py"
            try:
                (root / "LICENSE").write_text("license", encoding="utf-8")
                (root / "artifacts").mkdir()
                (root / "artifacts/package_delivery.py").write_text("helper", encoding="utf-8")
                paths = [root / "LICENSE", root / "artifacts/package_delivery.py"]
                archive = root / "source.zip"
                with zipfile.ZipFile(archive, "w") as bundle:
                    for path in paths:
                        bundle.write(path, path.relative_to(root).as_posix())
                # The fixture omits mandatory Android entries; add them to exercise exact checks.
                (root / "android/app/src/main/assets/termux").mkdir(parents=True)
                (root / "android/app/src/main/assets/termux/bootstrap-aarch64.zip").write_bytes(b"bootstrap")
                (root / "android/vendor/source/terminal-emulator/src/main/java").mkdir(parents=True)
                (root / "android/vendor/source/terminal-emulator/src/main/java/Source.java").write_text("java", encoding="utf-8")
                paths.extend([root / "android/app/src/main/assets/termux/bootstrap-aarch64.zip", root / "android/vendor/source/terminal-emulator/src/main/java/Source.java"])
                archive.unlink()
                with zipfile.ZipFile(archive, "w") as bundle:
                    for path in paths:
                        bundle.write(path, path.relative_to(root).as_posix())
                package_v1.assert_source_zip(archive, paths)
                archive.unlink()
                with zipfile.ZipFile(archive, "w") as bundle:
                    for path in paths[:-1]:
                        bundle.write(path, path.relative_to(root).as_posix())
                with self.assertRaisesRegex(RuntimeError, "entry set differs"):
                    package_v1.assert_source_zip(archive, paths)
                archive.unlink()
                with zipfile.ZipFile(archive, "w") as bundle:
                    for path in paths:
                        bundle.write(path, path.relative_to(root).as_posix())
                (root / "LICENSE").write_text("tampered", encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
                    package_v1.assert_source_zip(archive, paths)
            finally:
                package_v1.ROOT, package_v1.DELIVERY_HELPER = old_root, old_helper


if __name__ == "__main__":
    unittest.main(verbosity=2)
