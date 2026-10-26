"""Package reviewed v1 sources and artifacts without local state or signing keys."""
from pathlib import Path
import hashlib
import json
import importlib.util
import shutil
import xml.etree.ElementTree as ET
import zipfile

ROOT=Path(__file__).resolve().parents[1]
DIST=ROOT/'dist'
module=importlib.util.spec_from_file_location('apk_check',ROOT/'android/verify_apk.py')
checker=importlib.util.module_from_spec(module)
module.loader.exec_module(checker)
verification_module=importlib.util.spec_from_file_location('artifact_verifier',ROOT/'scripts/verify_v1_artifacts.py')
artifact_verifier=importlib.util.module_from_spec(verification_module)
verification_module.loader.exec_module(artifact_verifier)
provenance_spec=importlib.util.spec_from_file_location('release_provenance',ROOT/'scripts/release_provenance.py')
provenance=importlib.util.module_from_spec(provenance_spec)
provenance_spec.loader.exec_module(provenance)
METADATA=checker.release_metadata(ROOT)
VERSION=METADATA['version']
EXCLUDE_DIRS={'.git','.gradle','.bootstrap','build','__pycache__','node_modules','.idea','downloads'}
EXCLUDE_FILES={'local.properties','.DS_Store'}
EXCLUDE_SUFFIX={'.pyc','.pyo','.jks','.keystore','.log'}
DIRECTORIES=['android_agent','web','tests','android','docs','scripts']
FILES=['README.md','VALIDATION.md','THIRD_PARTY_NOTICES.md','LICENSE','开发文档.md','start.ps1','start.bat','start-termux.sh','.gitignore','图标.ico','eZ.json']
EVIDENCE_PATTERNS=[f'artifacts/python-v{VERSION}-*.txt',f'artifacts/browser-v{VERSION}-*.txt',
                   f'artifacts/android-v{VERSION}-*.txt',f'artifacts/android-v{VERSION}-*.json',
                   f'artifacts/*-v{VERSION}.png']
DELIVERY_HELPER=ROOT/'artifacts/package_delivery.py'
VERIFICATION=ROOT/f'artifacts/android-v{VERSION}-artifact-verification.json'
SIGNATURES=ROOT/f'artifacts/android-v{VERSION}-signatures.txt'
BUILD_LOG=ROOT/f'artifacts/android-v{VERSION}-final-build.txt'

def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()

def sources():
    import os
    found=[]
    for directory in DIRECTORIES:
        base=ROOT/directory
        if not base.is_dir():
            continue
        for parent,dirs,files in os.walk(base,followlinks=False):
            dirs[:]=sorted(name for name in dirs if name not in EXCLUDE_DIRS and not (Path(parent)/name).is_symlink())
            for name in sorted(files):
                file=Path(parent)/name
                if file.is_symlink() or name in EXCLUDE_FILES or file.suffix.lower() in EXCLUDE_SUFFIX:
                    continue
                found.append(file)
    found.extend(ROOT/name for name in FILES if (ROOT/name).is_file())
    for pattern in EVIDENCE_PATTERNS:
        found.extend(path for path in ROOT.glob(pattern) if path.is_file() and not path.is_symlink()
                     and "failure" not in path.name and path.name != f"ui-dark-en-xl-v{VERSION}.png")
    # Keep the delivery entry point in the source package when a checkout provides it.
    if DELIVERY_HELPER.is_file() and not DELIVERY_HELPER.is_symlink():
        found.append(DELIVERY_HELPER)
    return sorted(set(found),key=lambda path:path.relative_to(ROOT).as_posix())

def verified_apks():
    build_source=provenance.verify_build_manifest(ROOT,METADATA)
    if not VERIFICATION.is_file() or not SIGNATURES.is_file() or not BUILD_LOG.is_file():
        raise RuntimeError('Run build_release.py, verify_v1_artifacts.py, and verify_signatures.py after the final build before packaging')
    build_log=BUILD_LOG.read_text(encoding='utf-8',errors='replace')
    if 'BUILD SUCCESSFUL' not in build_log:
        raise RuntimeError('Current release build log does not record BUILD SUCCESSFUL')
    report=json.loads(VERIFICATION.read_text(encoding='utf-8'))
    if any(report.get(key)!=value for key,value in METADATA.items()):
        raise RuntimeError('Artifact verification metadata differs from the current release')
    expected_build_source=provenance.binding_summary(ROOT,build_source)
    if report.get('build_source')!=expected_build_source:
        raise RuntimeError('Artifact verification is not bound to the current build-source manifest')
    current_tests,current_suites=artifact_verifier.native_test_summary(ROOT/'android/app/build/test-results/testDebugUnitTest')
    if report.get('native_tests')!=current_tests or report.get('native_test_suites')!=current_suites:
        raise RuntimeError('Native JUnit XML changed after artifact verification')
    lint=ET.parse(ROOT/'android/app/build/reports/lint-results-debug.xml').getroot()
    lint_summary={level:sum(issue.get('severity')==level for issue in lint) for level in ('Error','Fatal','Warning','Information')}
    if report.get('lint')!=lint_summary or lint_summary['Error'] or lint_summary['Fatal']:
        raise RuntimeError('Android lint XML changed or contains errors after artifact verification')
    if report.get('real_device_verified') is not False:
        raise RuntimeError('Release report must not claim unperformed real-device verification')
    signing=SIGNATURES.read_text(encoding='utf-8')
    if f"versionName='{VERSION}'" not in signing or f"versionCode='{METADATA['version_code']}'" not in signing:
        raise RuntimeError('Signature evidence differs from the current release')
    paths={}
    for variant in ['release','debug']:
        source=ROOT/f'android/app/build/outputs/apk/{variant}/app-{variant}.apk'
        if not source.is_file():
            raise RuntimeError('Missing final APK: '+str(source))
        current=checker.verify(source)
        recorded=report.get('artifacts',{}).get(variant,{})
        if any(recorded.get(key)!=current[key] for key in ['sha256','size_bytes','version','version_code']):
            raise RuntimeError('APK changed after artifact verification: '+variant)
        if f"APK_SHA256 {variant} {current['sha256']}" not in signing:
            raise RuntimeError('APK changed after signature verification: '+variant)
        paths[variant]=source
    return paths

def assert_source_zip(archive: Path, paths: list[Path]) -> None:
    """Require an exact, readable source entry set with byte-for-byte hashes."""
    expected={file.relative_to(ROOT).as_posix():sha(file) for file in paths}
    if 'artifacts/package_delivery.py' in expected and not DELIVERY_HELPER.is_file():
        raise RuntimeError('Selected delivery helper disappeared before source packaging')
    with zipfile.ZipFile(archive) as bundle:
        corrupt=bundle.testzip()
        if corrupt:
            raise RuntimeError(f'Corrupt source ZIP entry: {corrupt}')
        names=bundle.namelist()
        if len(names)!=len(set(names)):
            raise RuntimeError('Source ZIP contains duplicate entries')
        if set(names)!=set(expected):
            missing=sorted(set(expected)-set(names))
            unexpected=sorted(set(names)-set(expected))
            raise RuntimeError(f'Source ZIP entry set differs: missing={missing}, unexpected={unexpected}')
        for name, expected_sha in expected.items():
            actual=hashlib.sha256(bundle.read(name)).hexdigest()
            if actual!=expected_sha:
                raise RuntimeError(f'Source ZIP entry hash mismatch: {name}')
        if 'LICENSE' not in names:
            raise RuntimeError('Source ZIP must contain LICENSE')
        if not any(name.endswith('termux/bootstrap-aarch64.zip') for name in names):
            raise RuntimeError('Source ZIP must contain the pinned bootstrap source asset')
        if not any('/terminal-emulator/src/main/java/' in name for name in names):
            raise RuntimeError('Source ZIP must contain terminal-emulator Java sources')


def main():
    apks=verified_apks()
    DIST.mkdir(exist_ok=True)
    artifacts=[]
    for variant in ['release','debug']:
        source=apks[variant]
        dest=DIST/f'AndroidAgent-{VERSION}-{variant}.apk'
        shutil.copyfile(source,dest)
        assert sha(dest)==sha(source)
        artifacts.append({'file':dest.name,'bytes':dest.stat().st_size,'sha256':sha(dest)})
    paths=sources()
    archive=DIST/f'AndroidAgent-{VERSION}-source.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
        for file in paths:
            relative=file.relative_to(ROOT).as_posix()
            bundle.write(file,relative)
    assert_source_zip(archive,paths)
    final_build_source=provenance.verify_build_manifest(ROOT,METADATA)
    final_binding=provenance.binding_summary(ROOT,final_build_source)
    verified_report=json.loads(VERIFICATION.read_text(encoding='utf-8'))
    if verified_report.get('build_source')!=final_binding:
        raise RuntimeError('Build-source provenance changed while packaging')
    artifacts.append({'file':archive.name,'bytes':archive.stat().st_size,'sha256':sha(archive),'source_files':len(paths)})
    manifest={**METADATA,'build_source':final_binding,
              'artifacts':artifacts,'excludes':'runtime workspace/data, logs, build caches, dependency downloads and signing keys'}
    (DIST/f'AndroidAgent-{VERSION}-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+chr(10),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
