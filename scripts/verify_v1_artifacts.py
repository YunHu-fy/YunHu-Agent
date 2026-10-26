"""Collect actual built artifacts, XML test counts, lint, and signature block IDs."""
from __future__ import annotations
import importlib.util
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
module = importlib.util.spec_from_file_location("apk_check", ROOT / "android/verify_apk.py")
checker = importlib.util.module_from_spec(module)
module.loader.exec_module(checker)
provenance_spec = importlib.util.spec_from_file_location("release_provenance", ROOT / "scripts/release_provenance.py")
provenance = importlib.util.module_from_spec(provenance_spec)
provenance_spec.loader.exec_module(provenance)


def signature_blocks(path: Path) -> list[str]:
    raw = path.read_bytes()
    eocd = raw.rfind(b"PK\x05\x06")
    if eocd < 0 or eocd + 22 > len(raw):
        raise ValueError("Missing ZIP EOCD")
    directory = struct.unpack_from("<I", raw, eocd + 16)[0]
    if directory < 32 or directory > eocd or raw[directory - 16:directory] != b"APK Sig Block 42":
        raise ValueError("Missing APK signing block")
    size = struct.unpack_from("<Q", raw, directory - 24)[0]
    cursor = directory - size - 8
    if size < 24 or cursor < 0 or struct.unpack_from("<Q", raw, cursor)[0] != size:
        raise ValueError("Signing block size mismatch")
    cursor += 8
    ids = []
    while cursor < directory - 24:
        if cursor + 12 > directory - 24:
            raise ValueError("Truncated signing block entry")
        length = struct.unpack_from("<Q", raw, cursor)[0]
        if length < 4 or cursor + 8 + length > directory - 24:
            raise ValueError("Invalid signing block entry length")
        ids.append(hex(struct.unpack_from("<I", raw, cursor + 8)[0]))
        cursor += 8 + length
    if cursor != directory - 24:
        raise ValueError("Trailing bytes in APK signing block")
    return ids


def native_test_summary(directory: Path) -> tuple[dict, list[dict]]:
    paths = sorted(directory.glob("TEST-*.xml"))
    if not paths:
        raise ValueError("No native JUnit XML results; run :app:testDebugUnitTest first")
    totals = {key: 0 for key in ("tests", "failures", "errors", "skipped")}
    details = []
    for path in paths:
        suite = ET.parse(path).getroot()
        if suite.tag != "testsuite":
            raise ValueError(f"Unexpected JUnit XML root: {path}")
        counts = {key: int(suite.get(key, "0")) for key in totals}
        if any(value < 0 for value in counts.values()) or sum(counts[key] for key in ("failures", "errors", "skipped")) > counts["tests"]:
            raise ValueError(f"Invalid JUnit test counts: {path}")
        for key, value in counts.items():
            totals[key] += value
        details.append({"file": path.name, "name": suite.get("name"), "timestamp": suite.get("timestamp"), **counts})
    if totals["tests"] <= totals["skipped"] or totals["failures"] or totals["errors"]:
        raise ValueError(f"Native tests did not pass: {totals}")
    return totals, details


def main() -> None:
    metadata = checker.release_metadata(ROOT)
    build_source = provenance.verify_build_manifest(ROOT, metadata)
    apks = {}
    for variant in ("debug", "release"):
        path = ROOT / f"android/app/build/outputs/apk/{variant}/app-{variant}.apk"
        result = checker.verify(path)
        result["signing_block_ids"] = signature_blocks(path)
        if not {"0x7109871a", "0xf05368c0"}.issubset(result["signing_block_ids"]):
            raise ValueError(f"Missing v2/v3 signing block: {variant}")
        apks[variant] = result
    tests, suites = native_test_summary(ROOT / "android/app/build/test-results/testDebugUnitTest")
    lint_path = ROOT / "android/app/build/reports/lint-results-debug.xml"
    lint = ET.parse(lint_path).getroot()
    lint_summary = {level: sum(issue.get("severity") == level for issue in lint) for level in ("Error", "Fatal", "Warning", "Information")}
    if lint_summary["Error"] or lint_summary["Fatal"]:
        raise ValueError(f"Android lint failed: {lint_summary}")
    for variant in ("debug", "release"):
        binding = build_source["apks"][variant]
        if apks[variant]["sha256"] != binding["sha256"] or apks[variant]["size_bytes"] != binding["size_bytes"]:
            raise ValueError(f"{variant} APK differs from its successful build-source binding")
    final_build_source = provenance.verify_build_manifest(ROOT, metadata)
    if provenance.binding_summary(ROOT, final_build_source) != provenance.binding_summary(ROOT, build_source):
        raise ValueError("Build-source provenance changed during artifact verification")
    report = {**metadata, "build_source": provenance.binding_summary(ROOT, final_build_source),
              "native_tests": tests, "native_test_suites": suites, "lint": lint_summary,
              "artifacts": apks, "real_device_verified": False}
    output = ROOT / f"artifacts/android-v{metadata['version']}-artifact-verification.json"
    output.parent.mkdir(exist_ok=True)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    output.write_text(text, encoding="utf-8")
    # Preserve the prior alias as versioned historical evidence before updating it.
    latest = ROOT / "artifacts/v1-artifact-verification.json"
    if latest.is_file():
        previous = json.loads(latest.read_text(encoding="utf-8"))
        previous_version = previous.get("version")
        if isinstance(previous_version, str) and previous_version != metadata["version"]:
            archive = ROOT / f"artifacts/android-v{previous_version}-artifact-verification.json"
            if not archive.exists():
                archive.write_text(json.dumps(previous, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
