"""Pinned Termux/PRoot package catalog.

Every install path is built here from fixed package IDs, fixed binary names and
one pinned Ollama release. Caller supplied text never reaches a shell: the
catalog decides the command, and the only variable parts are validated IDs.
"""
from __future__ import annotations

import shlex
import threading
import time
import uuid
from typing import Any, Callable

TERMUX_PREFIX = "/data/data/com.termux/files/usr"
TERMUX_HOME = "/data/data/com.termux/files/home"
ROOTFS = TERMUX_PREFIX + "/var/lib/proot-distro/installed-rootfs/"

# proot-distro refuses to install over an existing container, so an interrupted
# download leaves a rootfs directory that blocks every later attempt. The message
# is stable because the UI matches it to offer "clean up and redeploy".
RESIDUAL_CONTAINER = ("检测到上次中断留下的 {distro} 容器：rootfs 已存在但缺少 apt-get，"
                      "proot-distro 会拒绝重名安装。请使用“清理并重装”移除该残留容器后再部署；"
                      "容器内的数据会被清除。")

# Ollama has no Termux package and no generally usable Android/arm64 build outside
# a glibc userland, so it is provisioned inside the Debian/Ubuntu PRoot container
# from the pinned upstream release archive, verified against the published digest.
OLLAMA_RELEASE = {
    "version": "0.40.11",
    "asset": "ollama-linux-arm64.tar.zst",
    "bytes": 1564235434,
    "sha256": "77b278837b9e62c172f77d703675be4c52c8054e9075639031a9a6d5a53f1924",
    "url": "https://github.com/ollama/ollama/releases/download/v0.40.11/ollama-linux-arm64.tar.zst",
    "min_free_bytes": 6 * 1024 ** 3,
}

PACKAGES: dict[str, dict[str, Any]] = {
    "coreutils": {"label": "GNU coreutils", "termux": ["coreutils"], "debian": ["coreutils"]},
    "jq": {"label": "jq", "termux": ["jq"], "debian": ["jq"]},
    "yq": {"label": "yq (Go)", "termux": ["yq"], "debian": ["yq"]},
    "curl": {"label": "curl", "termux": ["curl"], "debian": ["curl"]},
    "build-essential": {"label": "build-essential / clang", "termux": ["clang", "make", "pkg-config"], "debian": ["build-essential"]},
    "git": {"label": "git", "termux": ["git"], "debian": ["git"]},
    "python": {"label": "Python 3 + pip", "termux": ["python", "python-pip"], "debian": ["python3", "python3-pip"]},
    "nodejs": {"label": "Node.js LTS", "termux": ["nodejs-lts"], "debian": ["nodejs", "npm"]},
    "proot-distro": {"label": "PRoot + Debian/Ubuntu installer", "termux": ["proot-distro"], "debian": ["proot"]},
    "apktool-jadx": {"label": "apktool + JADX (需要 Java)", "termux": ["apktool", "jadx", "openjdk-17"], "debian": ["apktool", "jadx", "openjdk-17-jre-headless"]},
    "adb": {"label": "Android platform tools (ADB)", "termux": ["android-tools"], "debian": ["adb"]},
    "ollama": {"label": "Ollama（Linux 容器内，ARM64）", "termux": [], "debian": [], "proot_only": True},
}

# Binary probes are relative to $PREFIX (Termux) or <rootfs>/usr (PRoot).
PROBES = {
    "termux": {"coreutils": ["bin/base64", "bin/realpath"], "jq": ["bin/jq"], "yq": ["bin/yq"], "curl": ["bin/curl"],
               "build-essential": ["bin/clang", "bin/cc"], "git": ["bin/git"], "python": ["bin/python", "bin/python3"],
               "nodejs": ["bin/node"], "proot-distro": ["bin/proot-distro"], "apktool-jadx": ["bin/apktool", "bin/jadx"],
               "adb": ["bin/adb"], "ollama": []},
    "debian": {"coreutils": ["bin/base64"], "jq": ["bin/jq"], "yq": ["bin/yq"], "curl": ["bin/curl"],
               "build-essential": ["bin/cc", "bin/gcc"], "git": ["bin/git"], "python": ["bin/python3"],
               "nodejs": ["bin/node"], "proot-distro": ["bin/proot"], "apktool-jadx": ["bin/apktool", "bin/jadx"],
               "adb": ["bin/adb"], "ollama": ["local/bin/ollama"]},
}

# One POSIX probe prints "VER|<key>|<first line>" for every tool; missing tools
# print an empty value so the UI can distinguish "not installed" from "unknown".
VERSION_SCRIPT = """ver() {
  key="$1"; shift
  if command -v "$1" >/dev/null 2>&1; then
    out=$("$@" 2>&1 | head -n 1 | tr -d '\\r')
    printf 'VER|%s|%s\\n' "$key" "$out"
  else
    printf 'VER|%s|\\n' "$key"
  fi
}
ver node node --version
ver npm npm --version
ver python python3 --version
ver pip pip3 --version
ver git git --version
ver curl curl --version
ver jq jq --version
ver yq yq --version
ver adb adb version
ver apktool apktool --version
ver jadx jadx --version
ver ollama ollama --version
ver cc cc --version
ver make make --version
"""

_VERSION_KEYS = ("node", "npm", "python", "pip", "git", "curl", "jq", "yq", "adb", "apktool", "jadx", "ollama", "cc", "make")
_VERSION_TTL_SECONDS = 120.0


class RuntimePackages:
    """Fixed catalog plus a bounded, cancellable command runner."""

    def __init__(self, android: Any):
        self.android = android
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._versions: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------ status
    @staticmethod
    def _known(runtime: dict[str, Any]) -> bool:
        return runtime.get("supported") is not False and runtime.get("installed") is True

    def _runtime(self) -> dict[str, Any]:
        try:
            runtime = self.android.runtime_status()
        except Exception as exc:  # never let a bridge hiccup blank the settings panel
            return {"supported": True, "installed": False, "error": str(exc)[:300]}
        return runtime if isinstance(runtime, dict) else {"supported": False, "installed": False}

    def status(self, distro: str | None = None, probe: bool = False) -> dict[str, Any]:
        if distro not in {None, "termux", "debian", "ubuntu"}:
            raise ValueError("运行环境只支持 Termux、Debian 或 Ubuntu。")
        runtime = dict(self._runtime())
        known = self._known(runtime)
        prefix = runtime.get("prefix") or TERMUX_PREFIX
        exists = getattr(self.android, "runtime_path_exists", None)
        callable_exists = callable(exists)

        def present(path: str) -> bool:
            if not callable_exists:
                return False
            try:
                return bool(exists(path))
            except Exception:
                return False

        distros = [name for name in ("debian", "ubuntu") if known and present(f"{ROOTFS}{name}/usr/bin/apt-get")]
        selected = distro if distro in {"debian", "ubuntu"} else (None if distro == "termux" else next((name for name in ("debian", "ubuntu") if name in distros), None))
        selected_installed = selected is None or selected in distros
        root = f"{ROOTFS}{selected}" if selected else None
        probes = PROBES["debian" if selected else "termux"]
        packages = []
        for key, item in PACKAGES.items():
            selected_packages = item["debian"] if selected else item["termux"]
            base = f"{root}/usr" if root else prefix
            probe_paths = probes.get(key, [])
            # proot_only entries ship no distro package but are provisioned from a
            # pinned upstream archive, so a deployed container still supports them.
            supported = bool(selected_packages) or bool(item.get("proot_only") and selected and probe_paths)
            installed = bool(known and selected_installed and supported
                             and any(present(f"{base}/{binary}") for binary in probe_paths))
            available = bool(known and selected_installed and supported)
            detail = None
            if item.get("proot_only") and not selected:
                detail = "需要先部署 Debian 或 Ubuntu 容器；Termux 仓库没有可验证的 Ollama 包。"
            elif known and not selected_installed:
                detail = "该容器尚未部署。"
            elif not known:
                detail = "请先部署内嵌 Termux 环境。"
            packages.append({**item, "id": key, "available": available, "installed": installed,
                             "detail": detail, "version": (self._versions.get(selected or "termux", {}).get("versions", {}) or {}).get(_version_key(key))})
        proot_ready = bool(known and present(prefix + "/bin/proot-distro"))
        reason = None
        if not known:
            reason = "runtime_missing" if runtime.get("supported") is not False else "runtime_unsupported"
        elif not selected_installed:
            reason = "distro_missing"
        if probe and known and selected_installed:
            self._refresh_versions(selected, runtime)
        runtime["proot_distros"] = distros
        runtime["proot_distro_available"] = proot_ready
        versions = dict(self._versions.get(selected or "termux", {})) if known else {}
        return {"ok": True, "runtime": runtime, "native_packages": "proot" if selected else "termux",
                "ready": bool(known and selected_installed), "reason": reason,
                "selected_distro": selected or "termux", "proot_installed": proot_ready,
                "distros": [{"id": name, "installed": name in distros} for name in ("debian", "ubuntu")],
                "packages": packages, "versions": versions.get("versions", {}), "version_error": versions.get("error"),
                "version_checked_at": versions.get("at"), "jobs": list(self._jobs.values()),
                "ollama": {key: OLLAMA_RELEASE[key] for key in ("version", "asset", "bytes", "sha256", "min_free_bytes")},
                "limitations": {
                    "ollama": "Ollama 只在 Debian/Ubuntu 容器内安装，下载约 " + _size(OLLAMA_RELEASE["bytes"]) + "；不支持 Termux 直接运行，也不会执行未知安装脚本。",
                    "proot": "PRoot 提供用户态发行版，不提供 Linux 内核或 GPU/NPU 直通。",
                }}

    # -------------------------------------------------------------- execution
    def _check_channel(self) -> None:
        status = self.android.status() if callable(getattr(self.android, "status", None)) else {"selected_channel": "normal"}
        if status.get("selected_channel", "normal") != "normal":
            raise PermissionError("运行环境管理只在普通 Android 权限通道中执行；请切换通道后重试。")
        normal = status.get("normal", {})
        if normal.get("available") is False or normal.get("granted") is False:
            raise PermissionError("普通 Android 命令通道当前不可用。")

    @staticmethod
    def _failure_text(result: dict[str, Any]) -> str:
        error = result.get("error")
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or "未知错误")[:800]
        if error:
            return str(error)[:800]
        for stream in ("stderr", "stdout"):
            text = str(result.get(stream) or "").strip()
            if text:
                return text[-800:]
        return str(result.get("status") or "未知错误")[:800]

    def _execute(self, command: str, runtime: dict[str, Any], timeout: int = 3600,
                 reporter: Callable[[str, str, int], None] | None = None,
                 cancelled: Callable[[], bool] | None = None) -> dict[str, Any]:
        """Run one fixed command through the selected private Termux runtime.

        Streaming is preferred so long package installs can surface output and be
        cancelled; the documented synchronous native call remains the fallback.
        ``reporter(phase, value, seq)`` receives ``start``, ``stdout``, ``stderr``
        and ``end`` phases for the task card.
        """
        self._check_channel()
        command_id = uuid.uuid4().hex
        request = {"id": command_id, "command": command,
                   "channel": "normal", "runtime": "termux",
                   "cwd": runtime.get("home") or TERMUX_HOME,
                   "timeout_seconds": max(1, min(int(timeout), 86400)), "environment": {}}
        if reporter is not None:
            reporter("start", command, 0)
        try:
            result = self._execute_inner(request, reporter, cancelled)
        except Exception:
            if reporter is not None:
                reporter("end", "failed", 0)
            raise
        if reporter is not None:
            reporter("end", str(result.get("status") or "succeeded"), 0)
        return result

    def _execute_inner(self, request: dict[str, Any], reporter: Callable[[str, str, int], None] | None,
                       cancelled: Callable[[], bool] | None) -> dict[str, Any]:
        command_id = str(request["id"])
        if not getattr(self.android, "streaming_commands", False):
            result = self.android.execute_command(request)
            if not isinstance(result, dict):
                raise RuntimeError("运行环境返回了无效结果。")
            if result.get("ok") is False or result.get("status") not in {"succeeded", None} or result.get("exit_code") not in {0, None}:
                raise RuntimeError("运行环境操作未成功：" + self._failure_text(result))
            return result
        begin = self.android.command_start(request)
        if not isinstance(begin, dict) or begin.get("ok") is False or begin.get("error"):
            raise RuntimeError("运行环境操作未开始：" + self._failure_text(begin if isinstance(begin, dict) else {}))
        if begin.get("id", command_id) != command_id:
            self.android.cancel_command(command_id)
            raise RuntimeError("原生命令ID与请求不一致，已取消。")
        started = time.monotonic()
        deadline = started + int(request["timeout_seconds"]) + 30
        after = 0
        stdout: list[str] = []
        stderr: list[str] = []
        kept = 0
        truncated = False
        while True:
            if cancelled is not None and cancelled():
                self.android.cancel_command(command_id)
                raise RuntimeError("运行环境任务已取消。")
            if time.monotonic() > deadline:
                self.android.cancel_command(command_id)
                raise RuntimeError("运行环境操作超时（" + str(request["timeout_seconds"]) + " 秒）。")
            poll = self.android.command_poll(command_id, after)
            if not isinstance(poll, dict):
                raise RuntimeError("运行环境返回了无效的轮询结果。")
            if poll.get("ok") is False or poll.get("error"):
                raise RuntimeError("运行环境轮询失败：" + self._failure_text(poll))
            for chunk in poll.get("chunks") or []:
                if not isinstance(chunk, dict):
                    continue
                seq = chunk.get("seq")
                text = chunk.get("text")
                if type(seq) is not int or seq <= after or not isinstance(text, str) or not text:
                    continue
                after = seq
                stream = "stderr" if chunk.get("stream") == "stderr" else "stdout"
                if reporter is not None:
                    reporter(stream, text, seq)
                size = len(text.encode("utf-8"))
                if kept < 256 * 1024:
                    (stderr if stream == "stderr" else stdout).append(text)
                    kept += size
                else:
                    truncated = True
            if poll.get("done") and not poll.get("more", False):
                result = poll.get("result") or {}
                if not isinstance(result, dict):
                    result = {}
                merged = {"ok": True,
                          "status": result.get("status", "succeeded"),
                          "exit_code": result.get("exit_code"),
                          "duration_ms": result.get("duration_ms", int((time.monotonic() - started) * 1000)),
                          "truncated": bool(result.get("truncated")) or truncated,
                          "stdout": "".join(stdout) or str(result.get("stdout") or ""),
                          "stderr": "".join(stderr) or str(result.get("stderr") or "")}
                if merged["status"] != "succeeded" or merged["exit_code"] not in {0, None}:
                    raise RuntimeError("运行环境操作未成功：" + self._failure_text(merged))
                return merged
            time.sleep(0.08)


    # ------------------------------------------------------------- provisioning
    def deploy_distro(self, distro: str, reset: bool = False, cancelled: Callable[[], bool] | None = None,
                      reporter: Callable[[str, str, int], None] | None = None) -> dict[str, Any]:
        if distro not in {"debian", "ubuntu"}:
            raise ValueError("只支持 Debian 或 Ubuntu PRoot。")
        runtime = self._runtime()
        if runtime.get("supported") is False:
            raise ValueError("此操作仅支持 Android APK 环境。")
        if not runtime.get("installed"):
            raise ValueError("请先在 Android APK 中部署内嵌 Termux 环境。")
        prefix = runtime.get("prefix") or TERMUX_PREFIX
        exists = getattr(self.android, "runtime_path_exists", None)
        present = callable(exists)

        def has(path: str) -> bool:
            try:
                return bool(present and exists(path))
            except Exception:
                return False

        rootfs = f"{ROOTFS}{distro}"
        installed = has(f"{rootfs}/usr/bin/apt-get")
        if installed and not reset:
            return {"ok": True, "distro": distro, "already_installed": True}
        leftover = has(rootfs)
        if leftover and not reset:
            raise RuntimeError(RESIDUAL_CONTAINER.format(distro=distro))
        # proot-distro used to be a manual prerequisite; install it here so the
        # "deploy Linux" button cannot dead-end on a missing helper.
        if not has(prefix + "/bin/proot-distro"):
            self._execute("pkg install -y proot-distro", runtime, timeout=1800, reporter=reporter, cancelled=cancelled)
            if not has(prefix + "/bin/proot-distro"):
                raise RuntimeError("proot-distro 安装后仍未检测到可执行文件，请检查 Termux 仓库网络后重试。")
        if leftover:
            self._execute("proot-distro remove " + distro, runtime, timeout=600, reporter=reporter, cancelled=cancelled)
        try:
            self._execute("proot-distro install " + distro, runtime, timeout=5400, reporter=reporter, cancelled=cancelled)
        except RuntimeError as exc:
            if "already exists" in str(exc).lower():
                raise RuntimeError(RESIDUAL_CONTAINER.format(distro=distro)) from exc
            raise
        if not has(f"{rootfs}/usr/bin/apt-get"):
            raise RuntimeError("Linux PRoot 部署后未检测到 apt-get；请查看任务输出中的下载错误。")
        self._refresh_versions(distro, runtime, force=True, reporter=reporter, cancelled=cancelled)
        return {"ok": True, "distro": distro, "already_installed": False}

    def install_many(self, package_ids: Any, proot: bool | str | None = False,
                     cancelled: Callable[[], bool] | None = None,
                     reporter: Callable[[str, str, int], None] | None = None) -> dict[str, Any]:
        if not isinstance(package_ids, list) or not 1 <= len(package_ids) <= 24 or any(not isinstance(item, str) or item not in PACKAGES for item in package_ids):
            raise ValueError("请提供 1..24 个受支持的软件包 ID。")
        if len(set(package_ids)) != len(package_ids):
            raise ValueError("软件包列表不能包含重复项。")
        if proot is None or proot is True or proot is False:
            # None is the JSON representation used by the Termux UI.
            distro = None
        elif isinstance(proot, str) and proot in {"debian", "ubuntu"}:
            distro = proot
        else:
            raise ValueError("只支持 Debian 或 Ubuntu PRoot。")
        runtime = self._runtime()
        if runtime.get("supported") is False:
            raise ValueError("此操作仅支持 Android APK 环境。")
        if not runtime.get("installed"):
            raise ValueError("请先部署内嵌 Termux 环境。")
        prefix = runtime.get("prefix") or TERMUX_PREFIX
        exists = getattr(self.android, "runtime_path_exists", None)

        def has(path: str) -> bool:
            try:
                return bool(callable(exists) and exists(path))
            except Exception:
                return False

        if distro:
            if not has(f"{ROOTFS}{distro}/usr/bin/apt-get"):
                raise ValueError("尚未部署指定的 Linux PRoot 容器。")
        elif "ollama" in package_ids:
            raise ValueError("Ollama 需要 Debian 或 Ubuntu 容器：请先部署容器并选择对应运行环境。")
        package_names: list[str] = []
        for package_id in package_ids:
            if package_id == "ollama":
                continue
            names = PACKAGES[package_id]["debian" if distro else "termux"]
            if not names:
                raise ValueError("所选软件包没有可验证的官方 Android 包；不会尝试未知二进制或脚本。")
            package_names.extend(names)
        installed: list[str] = []
        if package_names:
            if distro:
                inner = "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends " + " ".join(shlex.quote(name) for name in package_names)
                command = "proot-distro login " + distro + " -- /usr/bin/env DEBIAN_FRONTEND=noninteractive /bin/sh -c " + shlex.quote(inner)
            else:
                command = "pkg install -y " + " ".join(package_names)
            self._execute(command, runtime, timeout=3600, reporter=reporter, cancelled=cancelled)
            installed.extend(package_names)
        if "ollama" in package_ids:
            self._install_ollama(distro or "", runtime, reporter=reporter, cancelled=cancelled)
            installed.append("ollama")
        versions = self._refresh_versions(distro, runtime, force=True, reporter=reporter, cancelled=cancelled)
        missing = self._missing(package_ids, distro, runtime)
        if missing:
            raise RuntimeError("以下软件包安装后未检测到可执行文件：" + ", ".join(missing) + "。请查看任务输出中的下载/依赖错误。")
        return {"ok": True, "package_ids": package_ids, "packages": installed,
                "distro": distro or "termux", "versions": versions.get("versions", {})}

    def install(self, package_id: Any, proot: bool | str = False) -> dict[str, Any]:
        result = self.install_many([package_id], proot=proot)
        return {**result, "package_id": package_id, "packages": result["packages"]}

    def _installed(self, package_id: str, distro: str | None, runtime: dict[str, Any]) -> bool:
        exists = getattr(self.android, "runtime_path_exists", None)
        if not callable(exists):
            return False
        base = f"{ROOTFS}{distro}/usr" if distro else (runtime.get("prefix") or TERMUX_PREFIX)
        probes = PROBES["debian" if distro else "termux"].get(package_id, [])
        for binary in probes:
            try:
                if exists(f"{base}/{binary}"):
                    return True
            except Exception:
                continue
        return False

    def _missing(self, package_ids: list[str], distro: str | None, runtime: dict[str, Any]) -> list[str]:
        return [item for item in package_ids if not self._installed(item, distro, runtime)]

    def _install_ollama(self, distro: str, runtime: dict[str, Any],
                        reporter: Callable[[str, str, int], None] | None = None,
                        cancelled: Callable[[], bool] | None = None) -> None:
        if distro not in {"debian", "ubuntu"}:
            raise ValueError("Ollama 只能安装到 Debian 或 Ubuntu 容器。")
        release = OLLAMA_RELEASE
        script = (
            "set -e; export DEBIAN_FRONTEND=noninteractive; "
            "apt-get update; "
            "apt-get install -y --no-install-recommends ca-certificates curl zstd tar; "
            "mkdir -p /opt/ollama-download; "
            "df -B1 --output=avail /opt | tail -n 1 | tr -d ' ' > /tmp/ollama-avail; "
            f"[ \"$(cat /tmp/ollama-avail)\" -ge {release['min_free_bytes']} ] || "
            "{ echo 'ROOTFS_DISK_TOO_SMALL'; exit 74; }; "
            "curl -fL --retry 3 --retry-delay 2 --progress-bar -o /opt/ollama-download/ollama.tar.zst " + shlex.quote(release["url"]) + "; "
            f"echo {shlex.quote(release['sha256'] + '  /opt/ollama-download/ollama.tar.zst')} | sha256sum -c -; "
            "tar --zstd -xf /opt/ollama-download/ollama.tar.zst -C /usr/local; "
            "rm -f /opt/ollama-download/ollama.tar.zst; "
            "/usr/local/bin/ollama --version"
        )
        command = "proot-distro login " + distro + " -- /usr/bin/env DEBIAN_FRONTEND=noninteractive /bin/sh -c " + shlex.quote(script)
        try:
            self._execute(command, runtime, timeout=7200, reporter=reporter, cancelled=cancelled)
        except RuntimeError as exc:
            text = str(exc)
            if "ROOTFS_DISK_TOO_SMALL" in text:
                raise RuntimeError("容器可用空间不足：Ollama 需要至少 " + _size(release["min_free_bytes"]) + " 空闲空间。") from None
            raise

    # ---------------------------------------------------------------- versions
    def _refresh_versions(self, distro: str | None, runtime: dict[str, Any], *, force: bool = False,
                          reporter: Callable[[str, str, int], None] | None = None,
                          cancelled: Callable[[], bool] | None = None) -> dict[str, Any]:
        key = distro or "termux"
        cached = self._versions.get(key)
        now = time.time()
        if not force and cached and now - float(cached.get("at") or 0) < _VERSION_TTL_SECONDS:
            return cached
        if distro:
            command = "proot-distro login " + distro + " -- /usr/bin/env /bin/sh -c " + shlex.quote(VERSION_SCRIPT)
        else:
            command = VERSION_SCRIPT
        try:
            result = self._execute(command, runtime, timeout=120, reporter=reporter, cancelled=cancelled)
            text = str(result.get("stdout") or "")
            versions = {name: "" for name in _VERSION_KEYS}
            for line in text.splitlines():
                parts = line.strip().split("|", 2)
                if len(parts) == 3 and parts[0] == "VER" and parts[1] in versions:
                    versions[parts[1]] = parts[2].strip()[:120]
            payload = {"versions": versions, "error": None, "at": now}
        except Exception as exc:
            payload = {"versions": (cached or {}).get("versions", {}), "error": str(exc)[:300], "at": now}
        self._versions[key] = payload
        return payload


def _version_key(package_id: str) -> str:
    return {"python": "python", "nodejs": "node", "build-essential": "cc", "apktool-jadx": "apktool"}.get(package_id, package_id)


def _size(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB")
    amount = float(value)
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{amount:.1f} GiB"
