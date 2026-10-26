from __future__ import annotations

import threading
import unittest

from android_agent.runtime_packages import OLLAMA_RELEASE, PACKAGES, ROOTFS, TERMUX_HOME, TERMUX_PREFIX, RuntimePackages

APT_GET = ROOTFS + "{distro}/usr/bin/apt-get"


class FakeAndroidRuntime:
    """Mock bridge that models the private Termux prefix plus PRoot rootfs files."""

    def __init__(self, *, supported=True, installed=True, proot_distro=None, paths=None,
                 default_exists=True, stdout="fixture", on_command=None, rootfs_dirs=None):
        self.runtime = {"supported": supported, "installed": installed,
                        "prefix": TERMUX_PREFIX, "home": TERMUX_HOME}
        self.proot_distro = proot_distro
        self.paths = paths
        self.default_exists = default_exists
        self.commands = []
        self.stdout = stdout
        self.on_command = on_command
        self.rootfs_dirs = rootfs_dirs

    def runtime_status(self):
        return dict(self.runtime)

    def runtime_path_exists(self, path):
        if "/var/lib/proot-distro/installed-rootfs/" in path:
            distro = next((name for name in ("debian", "ubuntu") if f"/installed-rootfs/{name}" in path), None)
            if distro is None:
                return False
            if path.rstrip("/") == (ROOTFS + distro).rstrip("/"):
                if self.rootfs_dirs is not None:
                    return distro in self.rootfs_dirs
                return self.proot_distro == distro
            if path == APT_GET.format(distro=distro):
                return self.proot_distro == distro
            return bool(self.paths) and path in self.paths and self.proot_distro == distro
        if self.paths is not None:
            return path in self.paths
        return self.default_exists

    def execute_command(self, request):
        self.commands.append(request)
        if self.on_command is not None:
            self.on_command(request["command"])
        return {"ok": True, "status": "succeeded", "exit_code": 0, "stdout": self.stdout}


class FakeStreamingAndroid(FakeAndroidRuntime):
    streaming_commands = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cancelled = []
        self.polls = 0

    def command_start(self, request):
        self.commands.append(request)
        return {"ok": True, "id": request["id"]}

    def command_poll(self, command_id, after):
        self.polls += 1
        chunks = [{"seq": 1, "stream": "stdout", "text": "line\n"}] if after < 1 else []
        return {"ok": True, "chunks": chunks, "done": True,
                "result": {"status": "succeeded", "exit_code": 0, "stdout": "line\n", "stderr": "", "duration_ms": 5}}

    def cancel_command(self, command_id):
        self.cancelled.append(command_id)
        return {"ok": True}


class RuntimePackagesTests(unittest.TestCase):
    def test_status_exposes_only_fixed_catalog_and_runtime_availability(self):
        android = FakeAndroidRuntime()
        status = RuntimePackages(android).status()
        self.assertEqual({item["id"] for item in status["packages"]}, set(PACKAGES))
        self.assertTrue(status["ready"])
        self.assertIsNone(status["reason"])
        self.assertEqual(status["native_packages"], "termux")
        self.assertEqual(status["selected_distro"], "termux")
        by_id = {item["id"]: item for item in status["packages"]}
        self.assertTrue(by_id["curl"]["available"])
        # Ollama needs a glibc userland: no Termux package, container only.
        self.assertFalse(by_id["ollama"]["available"])
        self.assertIn("容器", by_id["ollama"]["detail"])
        self.assertEqual(PACKAGES["ollama"]["termux"], [])
        self.assertEqual(PACKAGES["ollama"]["debian"], [])
        self.assertTrue(PACKAGES["ollama"]["proot_only"])

    def test_ollama_release_is_pinned_with_a_published_digest(self):
        self.assertEqual(len(OLLAMA_RELEASE["sha256"]), 64)
        self.assertTrue(OLLAMA_RELEASE["url"].startswith("https://github.com/ollama/ollama/releases/download/"))
        self.assertTrue(OLLAMA_RELEASE["url"].endswith(OLLAMA_RELEASE["asset"]))
        self.assertIn("v" + OLLAMA_RELEASE["version"], OLLAMA_RELEASE["url"])
        self.assertGreater(OLLAMA_RELEASE["min_free_bytes"], OLLAMA_RELEASE["bytes"])

    def test_only_whitelisted_package_ids_can_be_installed(self):
        android = FakeAndroidRuntime()
        packages = RuntimePackages(android)
        for package_id in ("../../curl", "curl; touch /tmp/pwned", "unknown-package", None):
            with self.subTest(package_id=package_id), self.assertRaises(ValueError):
                packages.install(package_id)
        self.assertEqual(android.commands, [])

    def test_multiple_installs_reject_duplicates_and_oversized_batches(self):
        packages = RuntimePackages(FakeAndroidRuntime())
        with self.assertRaises(ValueError):
            packages.install_many(["curl", "curl"])
        with self.assertRaises(ValueError):
            packages.install_many(["curl"] * 25)

    def test_install_runs_catalog_command_then_version_probe(self):
        android = FakeAndroidRuntime(stdout="VER|curl|curl 8.9.1\nVER|node|v22.9.0\n")
        result = RuntimePackages(android).install("curl")
        self.assertEqual(result["packages"], PACKAGES["curl"]["termux"])
        self.assertEqual(result["distro"], "termux")
        self.assertEqual(result["versions"]["curl"], "curl 8.9.1")
        self.assertEqual(len(android.commands), 2)
        self.assertEqual(android.commands[0]["command"], "pkg install -y curl")
        self.assertEqual(android.commands[0]["runtime"], "termux")
        self.assertIn("ver node node --version", android.commands[1]["command"])

    def test_post_install_verification_fails_when_the_binary_is_absent(self):
        android = FakeAndroidRuntime(paths=set())
        with self.assertRaisesRegex(RuntimeError, "未检测到可执行文件"):
            RuntimePackages(android).install("curl")

    def test_install_accepts_json_null_as_termux(self):
        android = FakeAndroidRuntime()
        result = RuntimePackages(android).install_many(["curl"], proot=None)
        self.assertEqual(result["distro"], "termux")
        self.assertEqual(android.commands[0]["command"], "pkg install -y curl")

    def test_unsupported_or_missing_runtime_refuses_install_without_execution(self):
        for runtime_args in (
            {"supported": False, "installed": True},
            {"supported": True, "installed": False},
        ):
            with self.subTest(runtime_args=runtime_args):
                android = FakeAndroidRuntime(**runtime_args)
                with self.assertRaises(ValueError):
                    RuntimePackages(android).install("curl")
                self.assertEqual(android.commands, [])

    def test_missing_distro_is_reported_without_faking_package_availability(self):
        android = FakeAndroidRuntime()
        packages = RuntimePackages(android)
        status = packages.status("debian")
        self.assertFalse(status["ready"])
        self.assertEqual(status["reason"], "distro_missing")
        self.assertEqual(status["distros"], [{"id": "debian", "installed": False}, {"id": "ubuntu", "installed": False}])
        self.assertTrue(all(not item["available"] for item in status["packages"]))
        with self.assertRaisesRegex(ValueError, "尚未部署指定的 Linux PRoot"):
            packages.install("git", proot="debian")
        self.assertEqual(android.commands, [])

    def test_termux_cannot_install_ollama(self):
        android = FakeAndroidRuntime()
        packages = RuntimePackages(android)
        for proot in (None, False, True, "termux"):
            with self.subTest(proot=proot), self.assertRaises(ValueError):
                packages.install("ollama", proot=proot)
        self.assertEqual(android.commands, [])

    def test_ollama_in_container_downloads_the_pinned_release(self):
        paths = set()

        def after(command):
            if "ollama.tar.zst" in command:
                paths.add(ROOTFS + "debian/usr/local/bin/ollama")

        android = FakeAndroidRuntime(proot_distro="debian", paths=paths, on_command=after)
        packages = RuntimePackages(android)
        status = packages.status("debian")
        self.assertTrue(status["ready"])
        by_id = {item["id"]: item for item in status["packages"]}
        self.assertTrue(by_id["ollama"]["available"])
        self.assertFalse(by_id["ollama"]["installed"])
        result = packages.install("ollama", proot="debian")
        self.assertIn("ollama", result["packages"])
        self.assertEqual(len(android.commands), 2)
        download = android.commands[0]["command"]
        self.assertIn("proot-distro login debian", download)
        self.assertIn(OLLAMA_RELEASE["url"], download)
        self.assertIn(OLLAMA_RELEASE["sha256"], download)
        self.assertIn("sha256sum -c -", download)
        self.assertIn("tar --zstd", download)
        self.assertIn("apt-get install -y --no-install-recommends ca-certificates curl zstd tar", download)
        self.assertIn("proot-distro login debian", android.commands[1]["command"])

    def test_container_install_uses_apt_inside_the_rootfs(self):
        android = FakeAndroidRuntime(proot_distro="debian", paths={ROOTFS + "debian/usr/bin/jq", ROOTFS + "debian/usr/bin/git"})
        RuntimePackages(android).install_many(["jq", "git"], proot="debian")
        command = android.commands[0]["command"]
        self.assertTrue(command.startswith("proot-distro login debian -- "))
        self.assertIn("apt-get update", command)
        self.assertIn("apt-get install -y --no-install-recommends jq git", command)

    def test_deploy_installs_the_proot_helper_before_the_distro(self):
        paths = set()

        def after(command):
            if command == "pkg install -y proot-distro":
                paths.add(TERMUX_PREFIX + "/bin/proot-distro")
            if command == "proot-distro install debian":
                android.proot_distro = "debian"

        android = FakeAndroidRuntime(paths=paths, on_command=after)
        packages = RuntimePackages(android)
        result = packages.deploy_distro("debian")
        self.assertFalse(result["already_installed"])
        self.assertEqual([item["command"] for item in android.commands[:2]],
                         ["pkg install -y proot-distro", "proot-distro install debian"])
        self.assertTrue(android.commands[2]["command"].startswith("proot-distro login debian -- "))
        again = packages.deploy_distro("debian")
        self.assertTrue(again["already_installed"])
        self.assertEqual(len(android.commands), 3)

    def test_deploy_reports_a_residual_container_instead_of_raw_proot_distro_error(self):
        android = FakeAndroidRuntime(rootfs_dirs={"ubuntu"})
        with self.assertRaisesRegex(RuntimeError, "清理并重装"):
            RuntimePackages(android).deploy_distro("ubuntu")
        self.assertEqual(android.commands, [])

    def test_deploy_with_reset_removes_the_residual_container_before_installing(self):
        android = None

        def after(command):
            if command == "proot-distro install ubuntu":
                android.proot_distro = "ubuntu"

        android = FakeAndroidRuntime(paths={TERMUX_PREFIX + "/bin/proot-distro"},
                                     rootfs_dirs={"ubuntu"}, on_command=after)
        result = RuntimePackages(android).deploy_distro("ubuntu", reset=True)
        self.assertFalse(result["already_installed"])
        self.assertEqual([item["command"] for item in android.commands[:2]],
                         ["proot-distro remove ubuntu", "proot-distro install ubuntu"])

    def test_already_exists_failure_is_translated_into_the_clean_up_guidance(self):
        android = FakeAndroidRuntime(paths={TERMUX_PREFIX + "/bin/proot-distro"})

        def boom(request):
            android.commands.append(request)
            return {"ok": True, "status": "failed", "exit_code": 1,
                    "stderr": "Error: container 'debian' already exists. Specify a different name with '--name NAME'."}

        android.execute_command = boom
        with self.assertRaisesRegex(RuntimeError, "清理并重装"):
            RuntimePackages(android).deploy_distro("debian")

    def test_deploy_requires_a_deployed_termux_runtime(self):
        android = FakeAndroidRuntime(installed=False)
        with self.assertRaisesRegex(ValueError, "内嵌 Termux"):
            RuntimePackages(android).deploy_distro("debian")
        self.assertEqual(android.commands, [])

    def test_streaming_runtime_collects_chunks_and_surfaces_them(self):
        android = FakeStreamingAndroid()
        phases = []
        RuntimePackages(android)._execute("pkg install -y curl", {"home": TERMUX_HOME}, timeout=30,
                                         reporter=lambda phase, value, seq: phases.append(phase))
        self.assertEqual(phases[0], "start")
        self.assertIn("stdout", phases)
        self.assertEqual(phases[-1], "end")

    def test_streaming_runtime_honours_cancellation(self):
        android = FakeStreamingAndroid()
        cancel = threading.Event()

        def poll(command_id, after):
            cancel.set()
            return {"ok": True, "chunks": [], "done": False}

        android.command_poll = poll
        with self.assertRaisesRegex(RuntimeError, "已取消"):
            RuntimePackages(android)._execute("pkg install -y curl", {"home": TERMUX_HOME}, timeout=30,
                                             cancelled=cancel.is_set)
        self.assertEqual(len(android.cancelled), 1)


if __name__ == "__main__":
    unittest.main()
