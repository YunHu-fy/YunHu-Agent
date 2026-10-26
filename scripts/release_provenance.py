"""Capture and validate the complete source set used for v1 Android builds."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

SCHEMA_VERSION = 1
SOURCE_ROOTS = ("android", "android_agent", "web")
EXCLUDED_DIRS = {".git", ".gradle", ".kotlin", ".idea", "__pycache__",
                 "build", "node_modules", "downloads"}
EXCLUDED_FILES = {"local.properties"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".jks", ".keystore", ".log"}
VARIANTS = ("debug", "release")


def release_metadata(root: Path) -> dict:
    """Read and validate the Python/Android version without importing app code."""
    python = (root / "android_agent/__init__.py").read_text(encoding="utf-8-sig")
    gradle = (root / "android/app/build.gradle.kts").read_text(encoding="utf-8-sig")
    py_match = re.search(r'^__version__\s*=\s*"(\d+\.\d+\.\d+)"\s*$', python, re.MULTILINE)
    name_match = re.search(r'^\s*versionName\s*=\s*"(\d+\.\d+\.\d+)"\s*$', gradle, re.MULTILINE)
    code_match = re.search(r'^\s*versionCode\s*=\s*(\d+)\s*$', gradle, re.MULTILINE)
    if not py_match or not name_match or not code_match:
        raise ValueError("Missing release version metadata for build-source provenance")
    if py_match.group(1) != name_match.group(1):
        raise ValueError("Python and Android release versions differ")
    version = py_match.group(1)
    major, minor, patch = (int(part) for part in version.split("."))
    version_code = int(code_match.group(1))
    if version_code != major * 10000 + minor * 100 + patch:
        raise ValueError("Android versionCode does not match release metadata")
    return {"version": version, "version_code": version_code}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_records(root: Path) -> list[dict]:
    root = root.resolve()
    records = []
    for source_root in SOURCE_ROOTS:
        base = root / source_root
        if not base.is_dir() or base.is_symlink():
            raise ValueError(f"Missing build-source directory: {source_root}")
        for parent, dirs, names in os.walk(base, topdown=True, followlinks=False):
            dirs[:] = sorted(name for name in dirs
                             if name not in EXCLUDED_DIRS and not (Path(parent) / name).is_symlink())
            for name in sorted(names):
                path = Path(parent) / name
                if path.is_symlink() or name in EXCLUDED_FILES or path.suffix.lower() in EXCLUDED_SUFFIXES:
                    continue
                records.append({"path": path.relative_to(root).as_posix(), "sha256": sha256_file(path)})
    records.sort(key=lambda item: item["path"])
    if not records:
        raise ValueError("Build-source set is empty")
    return records


def source_snapshot(root: Path) -> dict:
    records = _source_records(root)
    encoded = json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return {"source_set_sha256": hashlib.sha256(encoded).hexdigest(), "files": records}


def manifest_path(root: Path, version: str) -> Path:
    return root / "artifacts" / f"android-v{version}-build-source-sha256.json"


def write_manifest(root: Path, manifest: dict) -> Path:
    path = manifest_path(root, manifest["version"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return path


def start_manifest(root: Path, metadata: dict) -> dict:
    snapshot = source_snapshot(root)
    return {"schema_version": SCHEMA_VERSION, **metadata, "status": "building",
            **snapshot, "apks": {}}


def apk_paths(root: Path) -> dict[str, Path]:
    return {variant: root / f"android/app/build/outputs/apk/{variant}/app-{variant}.apk"
            for variant in VARIANTS}


def record_apks(root: Path, source_set_sha256: str | None = None) -> dict:
    result = {}
    for variant, path in apk_paths(root).items():
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Missing final {variant} APK: {path.relative_to(root).as_posix()}")
        result[variant] = {"sha256": sha256_file(path), "size_bytes": path.stat().st_size}
        if source_set_sha256 is not None:
            result[variant]["source_set_sha256"] = source_set_sha256
    return result


def finish_manifest(root: Path, before: dict, after: dict) -> dict:
    if before["files"] != after["files"]:
        before["status"] = "failed"
        before["failure"] = "build_source_changed_during_build"
        before["source_after_sha256"] = after["source_set_sha256"]
        before["source_after_file_count"] = len(after["files"])
        before["apks"] = {}
        return before
    before["status"] = "success"
    before["apks"] = record_apks(root, before["source_set_sha256"])
    return before


def fail_manifest(manifest: dict, reason: str) -> dict:
    manifest["status"] = "failed"
    manifest["failure"] = reason
    manifest["apks"] = {}
    return manifest


def _validate_records(records) -> None:
    if not isinstance(records, list) or not records:
        raise ValueError("Build-source manifest has no file records")
    names = []
    for record in records:
        if (not isinstance(record, dict) or not isinstance(record.get("path"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", "")))
                or Path(record["path"]).is_absolute() or ".." in Path(record["path"]).parts):
            raise ValueError("Invalid build-source manifest file record")
        names.append(record["path"])
    if names != sorted(set(names)):
        raise ValueError("Build-source manifest paths must be unique and sorted")


def _source_difference(expected: list[dict], actual: list[dict]) -> str:
    old = {item["path"]: item["sha256"] for item in expected}
    new = {item["path"]: item["sha256"] for item in actual}
    added = sorted(new.keys() - old.keys())
    removed = sorted(old.keys() - new.keys())
    changed = sorted(name for name in old.keys() & new.keys() if old[name] != new[name])
    return f"added={added[:8]}, removed={removed[:8]}, changed={changed[:8]}"


def verify_build_manifest(root: Path, metadata: dict | None = None) -> dict:
    """Reject unproven builds, source drift, and APKs not bound to the manifest."""
    metadata = metadata or release_metadata(root)
    path = manifest_path(root, metadata["version"])
    if not path.is_file():
        raise ValueError(f"Missing successful build-source manifest: {path.relative_to(root).as_posix()}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read build-source manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported build-source manifest schema")
    if manifest.get("status") != "success":
        raise ValueError("Build-source manifest does not record a successful stable build")
    if manifest.get("version") != metadata["version"] or manifest.get("version_code") != metadata["version_code"]:
        raise ValueError("Build-source manifest release metadata differs from current release")
    records = manifest.get("files")
    _validate_records(records)
    calculated = hashlib.sha256(json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    if manifest.get("source_set_sha256") != calculated:
        raise ValueError("Build-source manifest source-set digest is invalid")
    current = source_snapshot(root)
    if current["files"] != records:
        raise ValueError("Build sources changed after successful build: " + _source_difference(records, current["files"]))
    recorded_apks = manifest.get("apks")
    if not isinstance(recorded_apks, dict) or set(recorded_apks) != set(VARIANTS):
        raise ValueError("Build-source manifest must bind both debug and release APKs")
    for variant, apk in apk_paths(root).items():
        record = recorded_apks.get(variant)
        if (not isinstance(record, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", "")))
                or not isinstance(record.get("size_bytes"), int) or record["size_bytes"] < 0):
            raise ValueError(f"Invalid build-source APK binding: {variant}")
        if not apk.is_file() or apk.is_symlink():
            raise ValueError(f"Missing APK bound to build sources: {variant}")
        if record.get("source_set_sha256") != manifest["source_set_sha256"]:
            raise ValueError(f"{variant} APK binding is not tied to this source set")
        actual = {"sha256": sha256_file(apk), "size_bytes": apk.stat().st_size,
                  "source_set_sha256": manifest["source_set_sha256"]}
        if record != actual:
            raise ValueError(f"{variant} APK differs from the APK bound to build sources")
    return manifest


def binding_summary(root: Path, manifest: dict) -> dict:
    """Return the compact source/APK binding embedded in verification reports."""
    path = manifest_path(root, manifest["version"])
    return {"manifest": path.relative_to(root).as_posix(),
            "manifest_sha256": sha256_file(path),
            "source_set_sha256": manifest["source_set_sha256"],
            "source_file_count": len(manifest["files"]),
            "apks": manifest["apks"]}
