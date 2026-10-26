"""Small, policy-reviewed Android workflows and secure workspace image renames.

Device commands only pass through the task manager. No local subprocess is used.
"""
from __future__ import annotations

import hmac
import json
import os
import re
import secrets
import shlex
import stat
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .security import SecurityError, Workspace, is_link_or_reparse

_PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+")
_SHA256 = re.compile(r"[0-9a-fA-F]{64}")
_EXTENSIONS = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif", ".avif"]


def definitions() -> list[dict[str, Any]]:
    def schema(properties, required):
        return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}

    package = {"type": "string", "pattern": _PACKAGE.pattern, "maxLength": 200}
    relative = {"type": "string", "maxLength": 512}
    return [
        {"name": "workflow.install_apk", "description": "Download an HTTPS APK, require and verify SHA256, install using the selected Root/Shizuku channel, and optionally launch. Requires existing curl and sha256sum; never installs dependencies or elevates permissions.", "inputSchema": schema({"url": {"type": "string", "maxLength": 4096}, "sha256": {"type": "string", "pattern": "^[0-9a-fA-F]{64}$"}, "package": package, "launch": {"type": "boolean", "default": False}}, ["url", "sha256"]), "requiresApproval": True, "disabledByDefault": True},
        {"name": "workflow.rename_images", "description": "Plan image renames in one workspace directory, sorted by case-insensitive name then exact name. Targets are prefix + unpadded number + original extension. Defaults to dry run; writes a rollback manifest under .backups when applied. Existing targets are never overwritten.", "inputSchema": schema({"directory": relative, "prefix": {"type": "string", "minLength": 1, "maxLength": 100}, "start": {"type": "integer", "minimum": 0, "maximum": 1000000000, "default": 1}, "dry_run": {"type": "boolean", "default": True}, "extensions": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 32, "default": list(_EXTENSIONS)}}, ["directory", "prefix"]), "requiresApproval": True},
        {"name": "workflow.backup_app", "description": "With the already selected Root channel, stop one app, archive its /data/user/0 private data to a new workspace .tar.gz/.tgz file, and attempt restart in finally. Archive publication is atomic and never overwrites.", "inputSchema": schema({"package": package, "archive": relative}, ["package", "archive"]), "requiresApproval": True, "disabledByDefault": True},
    ]


def _relative(value: Any, *, allow_root: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 512 or "\x00" in value:
        raise ValueError("Expected a workspace-relative path.")
    if value == "" and allow_root:
        return value
    if value.startswith("/") or "\\" in value or ":" in value:
        raise ValueError("Only workspace-relative POSIX paths are allowed.")
    parts = value.split("/")
    reserved = {"CON", "PRN", "AUX", "NUL"} | {f"{prefix}{i}" for prefix in ("COM", "LPT") for i in range(1, 10)}
    if any(part in {"", ".", ".."} or part.rstrip(" .") != part or part.upper().split(".")[0] in reserved or any(ord(c) < 32 or c in '<>"|?*' for c in part) for part in parts):
        raise ValueError("Unsafe workspace path or filename.")
    return value


def validate(name: str, args: Any) -> dict[str, Any]:
    definition = next((item for item in definitions() if item["name"] == name), None)
    if definition is None or not isinstance(args, dict):
        raise ValueError("Unknown workflow or invalid arguments.")
    schema = definition["inputSchema"]
    if set(args) - set(schema["properties"]) or set(schema["required"]) - set(args):
        raise ValueError("Missing or unknown workflow arguments.")
    result = dict(args)
    if "package" in result:
        package = result["package"]
        if not isinstance(package, str) or len(package) > 200 or not _PACKAGE.fullmatch(package):
            raise ValueError("Invalid Android package name.")
    if name == "workflow.install_apk":
        url, digest = result["url"], result["sha256"]
        if not isinstance(url, str) or not 1 <= len(url) <= 4096 or any(c.isspace() or ord(c) < 32 for c in url):
            raise ValueError("Expected an HTTPS URL without whitespace or credentials.")
        try:
            parsed = urlsplit(url)
            port = parsed.port
            if parsed.scheme.lower() != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.fragment or "\\" in parsed.netloc or port == 0:
                raise ValueError("HTTPS URL must have a host and no embedded credentials or fragment.")
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid HTTPS URL; embedded credentials are forbidden.") from exc
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise ValueError("A 64-hex-character SHA256 digest is required.")
        result["sha256"] = digest.lower()
        result.setdefault("launch", False)
        if type(result["launch"]) is not bool or (result["launch"] and "package" not in result):
            raise ValueError("launch must be boolean and requires package when true.")
    elif name == "workflow.rename_images":
        result["directory"] = _relative(result["directory"], allow_root=True)
        prefix = result["prefix"]
        if not isinstance(prefix, str) or not 1 <= len(prefix) <= 100 or "/" in prefix:
            raise ValueError("prefix must be a single filename prefix of 1-100 characters.")
        _relative(prefix + "0.jpg")
        result.setdefault("start", 1)
        result.setdefault("dry_run", True)
        if type(result["start"]) is not int or not 0 <= result["start"] <= 1000000000 or type(result["dry_run"]) is not bool:
            raise ValueError("Invalid start number or dry_run flag.")
        extensions = result.get("extensions", list(_EXTENSIONS))
        if not isinstance(extensions, list) or not 1 <= len(extensions) <= 32:
            raise ValueError("extensions must contain 1-32 image extensions.")
        normalized = set()
        for extension in extensions:
            if not isinstance(extension, str) or not re.fullmatch(r"\.?[A-Za-z0-9]{1,10}", extension):
                raise ValueError("Invalid image extension.")
            normalized.add("." + extension.lstrip(".").lower())
        result["extensions"] = sorted(normalized)
    else:
        result["archive"] = _relative(result["archive"])
        if not result["archive"].lower().endswith((".tar.gz", ".tgz")):
            raise ValueError("archive must end in .tar.gz or .tgz.")
    return result


def _shell(*parts: str) -> str:
    return " ".join(shlex.quote(part) for part in parts)


def _successful(result: dict[str, Any]) -> bool:
    return result.get("ok") is True and result.get("exit_code") == 0 and result.get("status") not in {"cancelled", "blocked", "denied", "timed_out", "timeout", "failed", "unsupported"}


def _execute(task, steps, label, command, *, runtime="system", timeout=60, final=False):
    if not final:
        task.check_cancelled()
    result = task.manager.execute_command(task, {"command": command, "channel": task.channel, "runtime": runtime, "timeout_seconds": timeout})
    if not isinstance(result, dict):
        raise RuntimeError("Command manager returned an invalid result.")
    steps.append({"step": label, **result})
    return result


def _device_channel(task, *, root_only=False) -> None:
    allowed = {"root"} if root_only else {"root", "shizuku"}
    if getattr(task, "channel", None) not in allowed:
        raise PermissionError("This workflow requires the already selected Root channel." if root_only else "APK installation requires an already selected Root or Shizuku channel.")
    if getattr(task, "runtime", "system") not in {"system", "termux"}:
        raise PermissionError("Android workflows require a POSIX system or Termux runtime.")
    android = getattr(task.manager, "android", None)
    if android is None or not android.available:
        raise PermissionError("Android commands are unavailable; no host/Windows command was executed.")
    status = android.status()
    capability = status.get(task.channel, {})
    if status.get("supported") is False or status.get("selected_channel", task.channel) != task.channel or capability.get("available") is not True or capability.get("granted") is not True:
        raise PermissionError("The selected Android permission channel is not actually available and granted; no escalation is attempted.")
    if task.channel == "shizuku" and getattr(task, "runtime", "system") == "termux":
        raise PermissionError("Shizuku cannot access the Termux prefix; select system runtime with accessible curl and sha256sum.")


def _identity(task, steps) -> bool:
    result = _execute(task, steps, "identity", _shell("id", "-u"))
    uid = result.get("stdout", "").strip()
    return _successful(result) and uid in ({"0"} if task.channel == "root" else {"0", "2000"})


def _failure(name, steps, step, message, **extra):
    return {"ok": False, "workflow": name, "status": "failed", "failed_step": step, "error": message, "steps": steps, **extra}


def _recovery_error(error, details):
    """Preserve cancellation/error type while making failed recovery observable."""
    error.workflow_recovery = details
    message = str(error) + "; workflow recovery: " + json.dumps(details, ensure_ascii=False)
    error.args = (message, *error.args[1:])


def run(name: str, args: Any, workspace: Workspace, task) -> dict[str, Any]:
    normalized = validate(name, args)
    task.check_cancelled()
    if name == "workflow.rename_images":
        return _rename_images(normalized, workspace, task)
    _device_channel(task, root_only=name == "workflow.backup_app")
    if name == "workflow.install_apk":
        return _install_apk(normalized, task)
    return _backup_app(normalized, workspace, task)


def _install_apk(args, task):
    name, steps = "workflow.install_apk", []
    if not _identity(task, steps):
        return _failure(name, steps, "identity", "Selected channel does not have the required actual Android identity.")
    runtime = task.runtime
    probe = _execute(task, steps, "dependencies", "command -v curl && command -v sha256sum", runtime=runtime)
    paths = [line.strip() for line in probe.get("stdout", "").splitlines() if line.strip()]
    if not _successful(probe) or len(paths) != 2 or any(not path.startswith("/") or any(c.isspace() for c in path) for path in paths):
        return _failure(name, steps, "dependencies", "curl and sha256sum must already be installed in the selected runtime; dependencies are never installed automatically.")
    curl, sha = paths
    if task.channel == "shizuku" and any(path.startswith("/data/data/") or path.startswith("/data/user/") for path in paths):
        return _failure(name, steps, "dependencies", "Shizuku cannot use the private Termux prefix; accessible system curl and sha256sum are required.")
    stage = "/data/local/tmp/android-agent-apk-" + secrets.token_hex(16)
    apk = stage + "/download.apk"
    created = False
    result, primary_error = None, None
    try:
        prepared = _execute(task, steps, "prepare", _shell("mkdir", "-m", "700", "--", stage))
        if not _successful(prepared):
            return _failure(name, steps, "prepare", "Cannot create a private Android staging directory.")
        created = True
        downloaded = _execute(task, steps, "download", _shell(curl, "--fail", "--location", "--silent", "--show-error", "--proto", "=https", "--proto-redir", "=https", "--max-redirs", "5", "--connect-timeout", "30", "--max-time", "300", "--output", apk, "--", args["url"]), runtime=runtime, timeout=330)
        if not _successful(downloaded):
            result = _failure(name, steps, "download", "HTTPS APK download failed.")
        else:
            hashed = _execute(task, steps, "sha256", _shell(sha, "--", apk), runtime=runtime)
            tokens = hashed.get("stdout", "").split()
            digest = tokens[0].lower() if tokens and _SHA256.fullmatch(tokens[0]) else ""
            if not _successful(hashed) or not hmac.compare_digest(digest, args["sha256"]):
                result = _failure(name, steps, "sha256", "APK SHA256 verification failed; installation was not attempted.")
            else:
                # pm may access the APK as system_server rather than the selected shell UID.
                shared = _execute(task, steps, "install_access", _shell("chmod", "711", "--", stage) + " && " + _shell("chmod", "644", "--", apk))
                installed = _execute(task, steps, "install", _shell("pm", "install", "-r", apk), timeout=180) if _successful(shared) else shared
                if not _successful(installed) or "Failure" in installed.get("stdout", "") or "Failure" in installed.get("stderr", ""):
                    result = _failure(name, steps, "install", "Android package installation failed.")
                elif args["launch"]:
                    launched = _execute(task, steps, "launch", _shell("monkey", "-p", args["package"], "-c", "android.intent.category.LAUNCHER", "1"))
                    result = {"ok": True, "workflow": name, "status": "succeeded", "sha256": digest, "launched": True, "steps": steps} if _successful(launched) else _failure(name, steps, "launch", "APK installed, but launching the requested package failed.", installed=True)
                else:
                    result = {"ok": True, "workflow": name, "status": "succeeded", "sha256": digest, "launched": False, "steps": steps}
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        if created:
            # Still routed through the shared manager: cancellation/policy is never bypassed.
            cleanup_error = None
            try:
                cleanup = _execute(task, steps, "cleanup", _shell("rm", "-f", "--", apk) + " && " + _shell("rmdir", "--", stage), final=True)
                if not _successful(cleanup):
                    cleanup_error = "APK staging cleanup failed or was blocked/cancelled by shared policy."
            except Exception as exc:
                cleanup_error = str(exc)
            if cleanup_error:
                if primary_error is not None:
                    _recovery_error(primary_error, {"cleanup_error": cleanup_error, "staging_directory": stage})
                elif result is not None:
                    result.update(ok=False, status="failed", cleanup_error=cleanup_error, staging_directory=stage)
    return result


class _Directory:
    """Anchor workspace operations with no-follow directory FDs on POSIX.

    Windows uses Python filesystem operations and the same reparse-point checks as
    Workspace; no command is executed. Link/unlink provides atomic no-clobber moves.
    """

    def __init__(self, workspace, relative, *, create=False):
        self.workspace, self.relative, self.fd = workspace, relative, None
        parts = workspace.parts(relative, allow_root=True)
        self.path = workspace._resolved(relative, allow_root=True)
        if os.name != "nt" and hasattr(os, "O_NOFOLLOW"):
            flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            current = os.open(workspace.root, flags)
            try:
                for part in parts:
                    if create:
                        try:
                            os.mkdir(part, 0o700, dir_fd=current)
                        except FileExistsError:
                            pass
                    child = os.open(part, flags, dir_fd=current)
                    os.close(current)
                    current = child
                self.fd = current
            except BaseException:
                os.close(current)
                raise
        else:
            if create:
                self.path.mkdir(mode=0o700, parents=True, exist_ok=True)
                self.path = workspace._resolved(relative, allow_root=True)
            if not self.path.is_dir() or is_link_or_reparse(self.path):
                raise SecurityError("Not a regular workspace directory.")

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def guard(self):
        path = self.workspace._resolved(self.relative, allow_root=True)
        if not path.is_dir() or is_link_or_reparse(path):
            raise SecurityError("Workspace directory changed or became a link.")
        if self.fd is not None:
            opened, current = os.fstat(self.fd), path.stat()
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise SecurityError("Workspace directory changed during operation.")

    def names(self):
        self.guard()
        return os.listdir(self.fd if self.fd is not None else self.path)

    def info(self, name):
        self.guard()
        if self.fd is not None:
            info = os.stat(name, dir_fd=self.fd, follow_symlinks=False)
        else:
            path = self.path / name
            if is_link_or_reparse(path):
                raise SecurityError("Symbolic links and reparse points are forbidden.")
            info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise SecurityError("Symbolic links and reparse points are forbidden.")
        return info

    def move(self, source, target):
        _relative(source)
        _relative(target)
        before = self.info(source)
        if not stat.S_ISREG(before.st_mode):
            raise SecurityError("Rename source must be a regular file.")
        if self.fd is not None:
            os.link(source, target, src_dir_fd=self.fd, dst_dir_fd=self.fd, follow_symlinks=False)
        else:
            os.link(self.path / source, self.path / target)
        try:
            after = self.info(target)
            current = self.info(source)
            if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino) or (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
                raise SecurityError("Rename source changed during operation.")
            self.unlink(source)
        except BaseException:
            # Only remove the newly linked target if it is still our file.
            try:
                target_info = self.info(target)
                if (before.st_dev, before.st_ino) == (target_info.st_dev, target_info.st_ino):
                    self.unlink(target)
            except (OSError, SecurityError):
                pass
            raise

    def unlink(self, name):
        self.guard()
        if self.fd is not None:
            os.unlink(name, dir_fd=self.fd)
        else:
            (self.path / name).unlink()

    def write_new(self, name, payload):
        self.guard()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(name, flags, 0o600, dir_fd=self.fd) if self.fd is not None else os.open(self.path / name, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())


def _rename_plan(args, directory):
    names = directory.names()
    selected = []
    for name in sorted(names, key=lambda value: (value.casefold(), value)):
        if Path(name).suffix.lower() not in args["extensions"]:
            continue
        info = directory.info(name)
        if stat.S_ISREG(info.st_mode):
            _relative(name)
            selected.append(name)
    if len(selected) > 10000:
        raise ValueError("At most 10000 images can be renamed in one workflow.")
    plan, targets = [], set()
    existing = {name.casefold(): name for name in names}
    for index, source in enumerate(selected, args["start"]):
        target = args["prefix"] + str(index) + Path(source).suffix
        _relative(target)
        relative = args["directory"] + "/" if args["directory"] else ""
        if target.casefold() in targets:
            raise FileExistsError("Duplicate rename target: " + target)
        targets.add(target.casefold())
        if target != source and target.casefold() in existing:
            raise FileExistsError("Rename target already exists: " + target)
        plan.append({"source": relative + source, "target": relative + target, "changed": source != target})
    return plan


def _rename_images(args, workspace, task):
    if args["directory"].split("/")[0] in {".backups", ".workflow_backups"}:
        raise SecurityError("Workflow backup directories cannot be renamed.")
    directory = _Directory(workspace, args["directory"])
    backups = None
    try:
        plan = _rename_plan(args, directory)
        result = {"ok": True, "workflow": "workflow.rename_images", "status": "succeeded", "dry_run": args["dry_run"], "plan": plan, "matched": len(plan), "renamed": 0, "manifest": None}
        if args["dry_run"] or not any(item["changed"] for item in plan):
            return result
        if not getattr(task, "full_access", False) and not task.request_approval("workflow.rename_images", args):
            raise PermissionError("User did not approve image renames.")
        task.check_cancelled()
        if plan != _rename_plan(args, directory):
            raise SecurityError("Directory contents changed while approval was pending; submit a new plan.")
        task.check_cancelled()
        backups = _Directory(workspace, ".backups", create=True)
        manifest_name = "workflow-rename-" + secrets.token_hex(16) + ".json"
        manifest_relative = ".backups/" + manifest_name
        manifest = {"version": 1, "workflow": "workflow.rename_images", "status": "planned", "directory": args["directory"], "plan": plan, "rollback": [{"source": item["target"], "target": item["source"]} for item in reversed(plan) if item["changed"]], "instructions": "For each rollback entry, rename source to target only if source is a regular non-link file and target is absent; never overwrite. Use the progress manifest after an interrupted/failed workflow."}
        task.check_cancelled()
        backups.write_new(manifest_name, json.dumps(manifest, ensure_ascii=False, indent=2))
        applied = []
        try:
            for item in plan:
                if not item["changed"]:
                    continue
                task.check_cancelled()
                directory.move(item["source"].rsplit("/", 1)[-1], item["target"].rsplit("/", 1)[-1])
                applied.append(item)
                task.check_cancelled()
        except BaseException as exc:
            rollback_errors, remaining = [], []
            for item in reversed(applied):
                try:
                    directory.move(item["target"].rsplit("/", 1)[-1], item["source"].rsplit("/", 1)[-1])
                except Exception as rollback_exc:
                    rollback_errors.append(str(rollback_exc))
                    remaining.append({"source": item["target"], "target": item["source"]})
            progress = {**manifest, "status": "rollback_failed" if rollback_errors else "rolled_back", "error": str(exc), "rollback": remaining, "rollback_errors": rollback_errors}
            try:
                backups.write_new(manifest_name + ".progress.json", json.dumps(progress, ensure_ascii=False, indent=2))
            except Exception as manifest_error:
                _recovery_error(exc, {"manifest": manifest_relative, "manifest_error": str(manifest_error), "rollback": remaining, "rollback_errors": rollback_errors})
            if rollback_errors:
                _recovery_error(exc, {"manifest": manifest_relative + ".progress.json", "rollback": remaining, "rollback_errors": rollback_errors})
            raise
        completed = {**manifest, "status": "completed", "renamed": len(applied)}
        backups.write_new(manifest_name + ".progress.json", json.dumps(completed, ensure_ascii=False, indent=2))
        result.update(renamed=len(applied), manifest=manifest_relative + ".progress.json", rollback=manifest["rollback"])
        return result
    finally:
        directory.close()
        if backups is not None:
            backups.close()


def _backup_app(args, workspace, task):
    name, steps = "workflow.backup_app", []
    archive = workspace._resolved(args["archive"])
    if not archive.parent.is_dir() or archive.exists() or is_link_or_reparse(archive):
        raise SecurityError("Archive parent must exist and the archive target must not exist.")
    if not _identity(task, steps):
        return _failure(name, steps, "identity", "The selected Root channel did not execute as uid 0.")
    probe = _execute(task, steps, "dependencies", "command -v tar && command -v ln && command -v mktemp")
    if not _successful(probe):
        return _failure(name, steps, "dependencies", "System tar, ln and mktemp must already be available.")
    package = args["package"]
    source = "/data/user/0/" + package
    destination = archive.as_posix()
    temporary_template = str(archive.parent.as_posix()) + "/.android-agent-backup-XXXXXXXX"
    private = _execute(task, steps, "prepare", "umask 077; " + _shell("mktemp", "-d", temporary_template))
    if not _successful(private):
        return _failure(name, steps, "prepare", "Could not create a private archive staging directory.")
    stage = private.get("stdout", "").strip()
    # Never interpolate unchecked command output into cleanup or privileged commands.
    expected_parent = archive.parent.as_posix()
    if not stage.startswith(expected_parent + "/.android-agent-backup-") or "/" in stage[len(expected_parent) + 1:] or not re.fullmatch(r"[.]android-agent-backup-[A-Za-z0-9]+", stage.rsplit("/", 1)[-1]):
        return _failure(name, steps, "prepare", "mktemp returned an unsafe staging path; no app was stopped.")
    temporary = stage + "/archive.tar.gz"
    stopped, result, primary_error = False, None, None
    try:
        task.check_cancelled()
        # Revalidate workspace components immediately before the shell touches them.
        if workspace._resolved(args["archive"]) != archive or archive.exists():
            raise SecurityError("Archive destination changed before backup.")
        checked = _execute(task, steps, "source", _shell("test", "-d", source) + " && ! " + _shell("test", "-L", source))
        if not _successful(checked):
            result = _failure(name, steps, "source", "Private application data directory is unavailable or is a symlink.")
        else:
            # A native failure can still follow a successful force-stop; restart in finally.
            stopped = True
            stop = _execute(task, steps, "force_stop", _shell("am", "force-stop", package))
            if not _successful(stop):
                result = _failure(name, steps, "force_stop", "Application force-stop failed.")
            else:
                packed = _execute(task, steps, "archive", "umask 077; " + _shell("tar", "-czf", temporary, "-C", "/data/user/0", "--", package), timeout=300)
                if not _successful(packed):
                    result = _failure(name, steps, "archive", "Application archive failed; the destination was not published.")
                else:
                    task.check_cancelled()
                    if workspace._resolved(args["archive"]) != archive or archive.exists():
                        raise SecurityError("Archive destination changed before publication.")
                    # Hard-link publication is atomic and unlike mv cannot clobber an existing target.
                    published = _execute(task, steps, "publish", _shell("ln", "-T", "--", temporary, destination))
                    result = {"ok": True, "workflow": name, "status": "succeeded", "package": package, "archive": args["archive"], "steps": steps} if _successful(published) else _failure(name, steps, "publish", "Atomic no-overwrite archive publication failed.")
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        final_errors = []
        if stopped:
            try:
                restarted = _execute(task, steps, "restart", _shell("monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"), final=True)
                if not _successful(restarted):
                    final_errors.append("Application restart failed or was blocked/cancelled by shared policy.")
            except Exception as exc:
                final_errors.append("Application restart failed: " + str(exc))
        try:
            cleaned = _execute(task, steps, "cleanup", _shell("rm", "-f", "--", temporary) + " && " + _shell("rmdir", "--", stage), final=True)
            if not _successful(cleaned):
                final_errors.append("Archive staging cleanup failed or was blocked/cancelled by shared policy.")
        except Exception as exc:
            final_errors.append("Archive staging cleanup failed: " + str(exc))
        if final_errors:
            if primary_error is not None:
                _recovery_error(primary_error, {"finalization_errors": final_errors, "staging_directory": stage})
            elif result is not None:
                result.update(ok=False, status="failed", finalization_errors=final_errors, staging_directory=stage)
    return result
