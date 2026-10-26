"""Run release verification tasks and bind APKs to an unchanged source set."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("release_provenance", ROOT / "scripts/release_provenance.py")
provenance = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(provenance)


def run_build(root: Path = ROOT, runner=None, environ: dict | None = None, platform: str | None = None) -> int:
    """Build with a before/after source snapshot; runner is injectable for tests."""
    root = Path(root).resolve()
    env = dict(os.environ if environ is None else environ)
    platform = os.name if platform is None else platform
    metadata = provenance.release_metadata(root)
    log = root / f"artifacts/android-v{metadata['version']}-final-build.txt"
    manifest = provenance.start_manifest(root, metadata)
    provenance.write_manifest(root, manifest)
    android = root / "android"
    gradle_args = [
        ":app:testDebugUnitTest",
        ":app:lintDebug",
        ":app:assembleDebug",
        ":app:assembleRelease",
        "--console=plain",
        "--no-daemon",
    ]
    if env.get("BUILD_OFFLINE") == "1":
        gradle_args.append("--offline")
    if platform == "nt":
        command = [str(android / "gradlew.bat"), *gradle_args]
        use_shell = True
    else:
        command = ["./gradlew", *gradle_args]
        use_shell = False

    java_home = env.get("JAVA_HOME", "<not set>")
    print(f"Building release version {metadata['version']}; JAVA_HOME={java_home}; log: {log}")
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("wb") as stream:
        stream.write(f"Release version: {metadata['version']}\nJAVA_HOME: {java_home}\nCommand: {' '.join(command)}\n\n".encode("utf-8"))
        try:
            result = (runner or subprocess.run)(command, cwd=android, env=env, stdout=stream,
                                                stderr=subprocess.STDOUT, shell=use_shell)
        except Exception:
            provenance.write_manifest(root, provenance.fail_manifest(manifest, "gradle_runner_exception"))
            raise
        if result.returncode != 0:
            provenance.write_manifest(root, provenance.fail_manifest(manifest, f"gradle_exit_{result.returncode}"))
            print(f"Build exit: {result.returncode}; log: {log}")
            return result.returncode
        try:
            after = provenance.source_snapshot(root)
            completed = provenance.finish_manifest(root, manifest, after)
        except Exception as exc:
            completed = provenance.fail_manifest(manifest, f"post_build_provenance_error: {exc}")
            provenance.write_manifest(root, completed)
            stream.write(f"\nBuild provenance failure: {exc}\n".encode("utf-8", errors="replace"))
            print(f"Build exit: 1; log: {log}")
            return 1
        if completed.get("status") != "success":
            provenance.write_manifest(root, completed)
            stream.write(b"\nBuild provenance failure: build sources changed during Gradle execution.\n")
            print(f"Build exit: 1; log: {log}")
            return 1
        provenance.write_manifest(root, completed)
    print(f"Build exit: 0; log: {log}; source set: {completed['source_set_sha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(run_build())
