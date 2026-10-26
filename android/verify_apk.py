"""Inspect frozen APK bytes, native assets and every staged Python/web file without installing it."""
from __future__ import annotations
import hashlib
import io
import json
import re
import sys
import zipfile
from pathlib import Path

BOOTSTRAP_SHA256 = "c8d702b6f742935001c37cda81b8ac69504a95d5cf28f2899532dd8cd4b057eb"
JNI_SHA256 = "41fad4b73caa033dc4b3de113f743efbd0039af6889ae7dd40ecb739fef17242"
REQUIRED_BOOTSTRAP_TOOLS = ("bash", "pkg", "apt", "curl", "tar", "gzip", "setsid")
REQUIRED = {"android_agent/__init__.py", "android_agent/__main__.py",
            "android_agent/attachments.py", "android_agent/models.py", "android_agent/local_models.py",
            "android_agent/context_manager.py", "android_agent/model_stream.py",
            "android_agent/android_runtime.py", "android_agent/android_bridge.py",
            "android_agent/server.py", "android_agent/core.py", "android_agent/maintenance.py",
            "android_agent/workflows.py", "android_agent/security.py", "android_agent/config.py",
            "android_agent/store.py", "android_agent/tools.py", "android_agent/mcp_stdio.py",
            "web/index.html", "web/static/app.js", "web/static/app.css", "web/static/markdown.js",
            "web/static/preferences.js", "web/static/i18n.js", "web/static/brand-icon.png"}

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def verify_bootstrap_tools(bootstrap_names: set[str]) -> None:
    """Reject bootstrap archives missing a required command-line tool."""
    for tool in REQUIRED_BOOTSTRAP_TOOLS:
        if "bin/" + tool not in bootstrap_names:
            raise ValueError(f"Bootstrap tool missing: {tool}")

def release_metadata(source_root: Path | None = None) -> dict:
    """Read metadata without importing application code; reject a split Python/Android version."""
    source_root = source_root or Path(__file__).resolve().parent.parent
    python = (source_root / "android_agent/__init__.py").read_text(encoding="utf-8-sig")
    gradle = (source_root / "android/app/build.gradle.kts").read_text(encoding="utf-8-sig")
    python_version = re.search(r'^__version__\s*=\s*"(\d+\.\d+\.\d+)"\s*$', python, re.MULTILINE)
    android_version = re.search(r'^\s*versionName\s*=\s*"(\d+\.\d+\.\d+)"\s*$', gradle, re.MULTILINE)
    version_code = re.search(r"^\s*versionCode\s*=\s*(\d+)\s*$", gradle, re.MULTILINE)
    if not python_version or not android_version or not version_code:
        raise ValueError("Missing release version metadata")
    if python_version.group(1) != android_version.group(1):
        raise ValueError("Python and Android release versions differ")
    major, minor, patch = (int(part) for part in python_version.group(1).split("."))
    parsed_code = int(version_code.group(1))
    if parsed_code != major * 10000 + minor * 100 + patch:
        raise ValueError("Android versionCode does not match major/minor/patch release metadata")
    return {"version": python_version.group(1), "version_code": parsed_code}

def verify(apk: Path) -> dict:
    source_root = Path(__file__).resolve().parent.parent
    metadata = release_metadata(source_root)
    expected = {p.relative_to(source_root).as_posix():p.read_bytes()
                for p in (source_root / "android_agent").rglob("*.py")}
    expected["web/index.html"] = (source_root / "web/index.html").read_bytes()
    expected.update({p.relative_to(source_root).as_posix():p.read_bytes()
                     for p in (source_root / "web/static").rglob("*") if p.is_file()})
    missing_source = REQUIRED - expected.keys()
    if missing_source:
        raise ValueError(f"Expected release workspace files missing: {sorted(missing_source)}")
    with zipfile.ZipFile(apk) as archive:
        corrupt = archive.testzip()
        if corrupt: raise ValueError(f"Corrupt APK entry: {corrupt}")
        entries = set(archive.namelist())
        app_archives = sorted(n for n in entries if n.startswith("assets/chaquopy/") and "/app" in n)
        packaged = {}
        for name in app_archives:
            payload = archive.read(name)
            if not zipfile.is_zipfile(io.BytesIO(payload)): continue
            with zipfile.ZipFile(io.BytesIO(payload)) as sources:
                for n in sources.namelist():
                    if not n.endswith("/"):
                        if n in packaged: raise ValueError(f"Duplicate embedded source: {n}")
                        packaged[n] = sources.read(n)
        if set(expected) != set(packaged):
            raise ValueError(f"Embedded file set differs: missing={sorted(set(expected)-set(packaged))}, unexpected={sorted(set(packaged)-set(expected))}")
        for name, payload in expected.items():
            if packaged[name] != payload: raise ValueError(f"Packaged source differs from frozen source: {name}")
        abis = sorted({n.split("/")[1] for n in entries if n.startswith("lib/") and n.endswith(".so")})
        if abis != ["arm64-v8a"]: raise ValueError(f"Unexpected ABI set: {abis}")
        if "lib/arm64-v8a/libpython3.13.so" not in entries: raise ValueError("Python 3.13 ARM64 missing")
        pinned = {"assets/termux/bootstrap-aarch64.zip":BOOTSTRAP_SHA256,"lib/arm64-v8a/libtermux.so":JNI_SHA256}
        for name, sha in pinned.items():
            if digest(archive.read(name)) != sha: raise ValueError(f"Pinned asset hash mismatch: {name}")
        for name in ("GPL-3.0.txt","Apache-2.0.txt","NOTICE.txt","PROVENANCE.json","Lottie-MIT.txt"):
            path = "assets/licenses/"+name
            if path not in entries: raise ValueError(f"Legal asset missing: {path}")
            workspace = source_root / "android/app/src/main/assets/licenses" / name
            if archive.read(path) != workspace.read_bytes(): raise ValueError(f"Legal asset differs: {name}")
        if len(archive.read("assets/licenses/GPL-3.0.txt")) < 30000: raise ValueError("Incomplete GPLv3 license")
        welcome_path = source_root / "android/app/src/main/assets/welcome/eZ.json"
        if not welcome_path.is_file(): raise ValueError("Missing bundled eZ welcome animation")
        for welcome_name in ("eZ.json", "eZ.html", "lottie.min.js"):
            welcome_file = source_root / "android/app/src/main/assets/welcome" / welcome_name
            archive_name = "assets/welcome/" + welcome_name
            if not welcome_file.is_file(): raise ValueError(f"Missing bundled welcome asset: {welcome_name}")
            if archive_name not in entries: raise ValueError(f"Bundled welcome asset missing from APK: {welcome_name}")
            if archive.read(archive_name) != welcome_file.read_bytes(): raise ValueError(f"Bundled welcome asset differs from workspace: {welcome_name}")
        if any(n.endswith(".apk") for n in entries): raise ValueError("External APK nested in application")
        with zipfile.ZipFile(io.BytesIO(archive.read("assets/termux/bootstrap-aarch64.zip"))) as bootstrap:
            bootstrap_names = set(bootstrap.namelist())
            verify_bootstrap_tools(bootstrap_names)
            if "SYMLINKS.txt" not in bootstrap_names: raise ValueError("Bootstrap symlink manifest missing")
        return {**metadata,"apk":str(apk.resolve()),"size_bytes":apk.stat().st_size,"sha256":digest(apk.read_bytes()),
                "abis":abis,"python_runtime":"3.13","embedded_source_archives":app_archives,
                "source_files_match":len(expected),"source_paths":sorted(expected),
                "bootstrap_sha256":BOOTSTRAP_SHA256,"jni_sha256":JNI_SHA256,
                "legal_assets_verified":True,"embedded_apk":False}

if __name__ == "__main__":
    apk = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "app/build/outputs/apk/debug/app-debug.apk"
    print(json.dumps(verify(apk), ensure_ascii=False, indent=2))
