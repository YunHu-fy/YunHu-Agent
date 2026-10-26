"""Read-only provenance and safe-extraction audit for the pinned official bootstrap."""
import hashlib, json, pathlib, posixpath, zipfile
root = pathlib.Path(__file__).resolve().parents[2]
asset = root / "app/src/main/assets/termux/bootstrap-aarch64.zip"
expected = "c8d702b6f742935001c37cda81b8ac69504a95d5cf28f2899532dd8cd4b057eb"
assert hashlib.sha256(asset.read_bytes()).hexdigest() == expected
prefix = "/data/data/com.termux/files/usr"
with zipfile.ZipFile(asset) as z:
    assert z.testzip() is None
    names = set()
    for entry in z.infolist():
        name = entry.filename.removeprefix("./").rstrip("/")
        assert name and not name.startswith("/") and "\\" not in name
        assert all(p not in ("", ".", "..") for p in name.split("/"))
        assert name not in names, name
        names.add(name)
    links = []
    for line in z.read("SYMLINKS.txt").decode().splitlines():
        source, target = line.split("←")
        target = target.removeprefix("./")
        assert target not in names, target
        dest = posixpath.normpath(source if source.startswith("/") else posixpath.join(prefix, posixpath.dirname(target), source))
        assert dest == prefix or dest.startswith(prefix + "/"), (source, target)
        links.append((source, target))
    assert len({l[1] for l in links}) == len(links)
    required = ["bin/" + p for p in ("bash", "pkg", "apt", "curl", "tar", "gzip", "setsid")]
    assert all(p in names or p in {l[1] for l in links} for p in required)
    summary = {"sha256":expected,"entries":len(names),"symlinks":len(links),"uncompressed_bytes":sum(e.file_size for e in z.infolist()),"required_tools":required,"validated":True}
    print(json.dumps(summary, indent=2))
