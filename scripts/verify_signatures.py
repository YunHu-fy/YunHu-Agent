"""Check SDK signatures, manifest version, ABI, and optional upgrade continuity."""
from __future__ import annotations
import argparse
import importlib.util
import hashlib
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CERT = "d75741c68b60590d0f462c27403889f80cb3082567cda2bb867d9db083c4bcdd"
metadata_module = importlib.util.spec_from_file_location("apk_check", ROOT / "android/verify_apk.py")
metadata_loader = importlib.util.module_from_spec(metadata_module)
metadata_module.loader.exec_module(metadata_loader)


def sdk_build_tools() -> Path:
    sdk = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
    if not sdk:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise RuntimeError("Set ANDROID_SDK_ROOT or ANDROID_HOME before signature verification")
        sdk = str(Path(local_app_data) / "Android/Sdk")
    path = Path(sdk) / "build-tools/36.1.0"
    if not (path / "apksigner.bat").is_file():
        raise RuntimeError(f"Android Build Tools 36.1.0 not found: {path}")
    return path


def run(command: list[Path | str], output: list[str]) -> str:
    result = subprocess.run([str(item) for item in command], cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    text = result.stdout
    output.append(text)
    if result.returncode:
        raise RuntimeError(text)
    return text


def certificate_digest(text: str) -> str:
    match = re.search(r"Signer #1 certificate SHA-256 digest: ([0-9a-fA-F]{64})", text)
    if not match:
        raise RuntimeError("apksigner output did not contain a signer certificate SHA-256 digest")
    return match.group(1).lower()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-apk", type=Path, help="Optional prior release APK for same-certificate upgrade verification")
    args = parser.parse_args()
    metadata = metadata_loader.release_metadata(ROOT)
    sdk = sdk_build_tools()
    output: list[str] = []
    expected_release = os.environ.get("ANDROID_AGENT_EXPECTED_CERT_SHA256", "").strip().lower()
    allow_debug_release = os.environ.get("AGENT_ALLOW_DEBUG_RELEASE_SIGNING") == "1"
    if not expected_release:
        raise RuntimeError("Set ANDROID_AGENT_EXPECTED_CERT_SHA256 to the pinned non-debug release certificate digest")
    if expected_release == DEFAULT_CERT and not allow_debug_release:
        raise RuntimeError("The Android debug certificate is not a production release certificate; use an owner key or explicitly set AGENT_ALLOW_DEBUG_RELEASE_SIGNING=1 for development")
    expected_certs = {
        "release": expected_release,
        "debug": os.environ.get("ANDROID_AGENT_EXPECTED_DEBUG_CERT_SHA256", DEFAULT_CERT).strip().lower(),
    }
    if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in expected_certs.values()):
        raise RuntimeError("Expected certificate digests must be 64 hexadecimal characters")
    certs: dict[str, str] = {}
    for variant in ("release", "debug"):
        apk = ROOT / f"android/app/build/outputs/apk/{variant}/app-{variant}.apk"
        if not apk.is_file():
            raise RuntimeError(f"Missing {variant} APK: {apk}; build it before signature verification")
        output.append(f"FINAL {variant}\nAPK_SHA256 {variant} {hashlib.sha256(apk.read_bytes()).hexdigest()}\n")
        signing = run([sdk / "apksigner.bat", "verify", "--verbose", "--print-certs", apk], output)
        if "v3): true" not in signing:
            raise RuntimeError(f"{variant} APK is not v3-signed")
        cert = certificate_digest(signing)
        certs[variant] = cert
        if variant == "release" and cert == DEFAULT_CERT and not allow_debug_release:
            raise RuntimeError("Release APK is signed with the Android debug certificate")
        if cert != expected_certs[variant]:
            raise RuntimeError(f"{variant} certificate differs from its expected SHA-256 digest")
        older = run([sdk / "apksigner.bat", "verify", "--verbose", "--min-sdk-version", "24", "--max-sdk-version", "27", apk], output)
        if "v2): true" not in older:
            raise RuntimeError(f"{variant} APK is not v2-compatible for API 24..27")
        run([sdk / "zipalign.exe", "-c", "-P", "16", "4", apk], output)
        badging = run([sdk / "aapt2.exe", "dump", "badging", apk], output)
        required = (
            "name='com.termux'",
            f"versionName='{metadata['version']}'",
            f"versionCode='{metadata['version_code']}'",
            "minSdkVersion:'29'",
            "targetSdkVersion:'28'",
            "native-code: 'arm64-v8a'",
            "application-label:'云琥'",
        )
        if any(item not in badging for item in required):
            raise RuntimeError(f"{variant} manifest does not match release metadata/ABI")
    prior = args.prior_apk or (Path(os.environ["ANDROID_AGENT_PRIOR_APK"]) if os.environ.get("ANDROID_AGENT_PRIOR_APK") else None)
    if prior is not None:
        if not prior.is_file():
            raise RuntimeError(f"Prior APK not found: {prior}")
        prior_text = run([sdk / "apksigner.bat", "verify", "--print-certs", prior], output)
        prior_cert = certificate_digest(prior_text)
        if prior_cert != certs["release"]:
            raise RuntimeError("Release certificate differs from the explicitly supplied prior APK")
        output.append(f"UPGRADE_CERTIFICATE_MATCH {prior.resolve()}\n")
    else:
        output.append("UPGRADE_CERTIFICATE_CHECK not_run (no --prior-apk supplied)\n")
    report = ROOT / f"artifacts/android-v{metadata['version']}-signatures.txt"
    report.parent.mkdir(exist_ok=True)
    output.insert(0, "RELEASE_SIGNING_MODE " + ("explicit-debug-development-override" if allow_debug_release and certs.get("release") == DEFAULT_CERT else "pinned-owner-certificate"))
    report.write_text("\n".join(output), encoding="utf-8")
    print(f"PASS release/debug v2+v3, manifest {metadata['version']}/{metadata['version_code']}, ARM64, zipalign; upgrade certificate check is {'performed' if prior else 'not run'}")


if __name__ == "__main__":
    main()
