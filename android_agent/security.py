from __future__ import annotations

import os
import secrets
import stat
import time
from pathlib import Path
from typing import Any


class SecurityError(Exception):
    pass


def create_runtime_token(data_dir: Path) -> str:
    data_dir.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    target = data_dir / "runtime.token"
    temp = data_dir / (".runtime." + secrets.token_hex(8))
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as stream:
        stream.write(token)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.chmod(temp, 0o600)
    except OSError:
        pass
    os.replace(temp, target)
    return token


def valid_bearer(value: str, expected: str) -> bool:
    if not value.startswith("Bearer ") or value.count(" ") != 1:
        return False
    candidate = value[7:]
    return bool(candidate) and secrets.compare_digest(candidate, expected)


def is_link_or_reparse(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attrs = getattr(info, "st_file_attributes", 0)
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attrs & flag)


class Workspace:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve()

    def parts(self, relative: str, allow_root: bool = False) -> tuple[str, ...]:
        if not isinstance(relative, str) or len(relative) > 512 or chr(0) in relative:
            raise SecurityError("路径格式无效。")
        if relative == "" and allow_root:
            return ()
        if relative.startswith("/") or chr(92) in relative or ":" in relative:
            raise SecurityError("仅允许使用正斜杠表示的工作区相对路径。")
        parts = tuple(relative.split("/"))
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise SecurityError("路径不得为空，也不得包含路径遍历。")
        reserved = {"CON", "PRN", "AUX", "NUL"}
        reserved.update("COM" + str(i) for i in range(1, 10))
        reserved.update("LPT" + str(i) for i in range(1, 10))
        if any(part.rstrip(" .") != part or part.upper().split(".")[0] in reserved for part in parts):
            raise SecurityError("路径包含不受支持的文件名。")
        return parts

    def _resolved(self, relative: str, allow_root: bool = False) -> Path:
        parts = self.parts(relative, allow_root)
        path = self.root.joinpath(*parts)
        current = self.root
        for part in parts:
            current = current / part
            if is_link_or_reparse(current):
                raise SecurityError("工作区不允许符号链接或reparse point。")
        resolved = path.resolve(strict=False)
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise SecurityError("路径超出工作区范围。") from exc
        return resolved

    def _open_parent(self, parts: tuple[str, ...], create: bool = False) -> tuple[int, str]:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        current = os.open(self.root, flags)
        try:
            for part in parts[:-1]:
                if create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=current)
                    except FileExistsError:
                        pass
                next_fd = os.open(part, flags, dir_fd=current)
                os.close(current)
                current = next_fd
            return current, parts[-1]
        except BaseException:
            os.close(current)
            raise

    def list(self, relative: str = "") -> list[dict[str, Any]]:
        path = self._resolved(relative, allow_root=True)
        if not path.is_dir():
            raise SecurityError("目录不存在。")
        result = []
        for item in sorted(path.iterdir(), key=lambda entry: entry.name.casefold())[:200]:
            if is_link_or_reparse(item):
                result.append({"name": item.name, "type": "blocked_link", "bytes": None})
            elif item.is_dir():
                result.append({"name": item.name, "type": "directory", "bytes": None})
            elif item.is_file():
                result.append({"name": item.name, "type": "file", "bytes": item.stat().st_size})
        return result

    def read(self, relative: str, limit: int = 65536) -> str:
        parts = self.parts(relative)
        if os.name == "nt" or not hasattr(os, "O_NOFOLLOW"):
            path = self._resolved(relative)
            if not path.is_file() or path.stat().st_size > limit:
                raise SecurityError("仅允许读取不超过64 KiB的普通文件。")
            with path.open("r", encoding="utf-8") as stream:
                data = stream.read(limit + 1)
        else:
            parent, name = self._open_parent(parts)
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            finally:
                os.close(parent)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                    raise SecurityError("仅允许读取不超过64 KiB的普通文件。")
                with os.fdopen(fd, "r", encoding="utf-8") as stream:
                    fd = -1
                    data = stream.read(limit + 1)
            finally:
                if fd >= 0:
                    os.close(fd)
        if len(data.encode("utf-8")) > limit:
            raise SecurityError("文件超过64 KiB读取上限。")
        return data

    def write(self, relative: str, content: str) -> dict[str, Any]:
        if not isinstance(content, str):
            raise SecurityError("文件内容必须是UTF-8文本。")
        return self._write_bytes(relative, content.encode("utf-8"), 262144)

    def _write_bytes(self, relative: str, raw: bytes, limit: int) -> dict[str, Any]:
        parts = self.parts(relative)
        if len(raw) > limit:
            raise SecurityError("文件内容超过写入上限。")
        if os.name == "nt" or not hasattr(os, "O_NOFOLLOW"):
            path = self._resolved(relative)
            path.parent.mkdir(parents=True, exist_ok=True)
            backup = None
            if path.exists():
                if not path.is_file() or is_link_or_reparse(path) or path.stat().st_size > 4 * 1024 * 1024:
                    raise SecurityError("目标不是普通文件或超过备份限制。")
                backup_dir = self._resolved(".backups")
                backup_dir.mkdir(parents=True, exist_ok=True)
                stamp = str(int(time.time() * 1000000))
                backup_rel = ".backups/" + "/".join(parts) + "." + stamp + ".bak"
                backup_path = self._resolved(backup_rel)
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                backup_path.write_bytes(path.read_bytes())
                backup = backup_rel
            temp = path.with_name(path.name + ".tmp." + secrets.token_hex(6))
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
        else:
            parent, name = self._open_parent(parts, create=True)
            backup = None
            temp_name = ".tmp." + secrets.token_hex(12)
            try:
                try:
                    old_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
                except FileNotFoundError:
                    old_fd = None
                if old_fd is not None:
                    try:
                        info = os.fstat(old_fd)
                        if not stat.S_ISREG(info.st_mode) or info.st_size > 4 * 1024 * 1024:
                            raise SecurityError("目标不是普通文件或超过备份限制。")
                        with os.fdopen(old_fd, "rb") as stream:
                            old_fd = -1
                            old = stream.read()
                    finally:
                        if old_fd >= 0:
                            os.close(old_fd)
                    backup_dir = self._resolved(".backups")
                    backup_dir.mkdir(parents=True, exist_ok=True)
                    backup = ".backups/" + "/".join(parts) + "." + str(int(time.time() * 1000000)) + ".bak"
                    backup_parent, backup_name = self._open_parent(self.parts(backup), create=True)
                    try:
                        backup_fd = os.open(backup_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=backup_parent)
                        with os.fdopen(backup_fd, "wb") as stream:
                            stream.write(old)
                    finally:
                        os.close(backup_parent)
                fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_name, name, src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
            finally:
                try:
                    os.unlink(temp_name, dir_fd=parent)
                except FileNotFoundError:
                    pass
                os.close(parent)
        return {"bytes": len(raw), "backup": backup}

    def read_bytes(self, relative: str, limit: int = 4 * 1024 * 1024) -> bytes:
        parts = self.parts(relative)
        if os.name == "nt" or not hasattr(os, "O_NOFOLLOW"):
            path = self._resolved(relative)
            if not path.is_file() or path.stat().st_size > limit:
                raise SecurityError("备份不是普通文件或超过读取上限。")
            with path.open("rb") as stream:
                raw = stream.read(limit + 1)
        else:
            parent, name = self._open_parent(parts)
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            finally:
                os.close(parent)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                    raise SecurityError("备份不是普通文件或超过读取上限。")
                with os.fdopen(fd, "rb") as stream:
                    fd = -1
                    raw = stream.read(limit + 1)
            finally:
                if fd >= 0:
                    os.close(fd)
        if len(raw) > limit:
            raise SecurityError("备份超过读取上限。")
        return raw

    def restore_backup(self, backup_id: str, relative: str) -> dict[str, Any]:
        import re
        self.parts(relative)
        self.parts(backup_id)
        pattern = r"\.backups/" + re.escape(relative) + r"\.[0-9]{12,20}\.bak"
        if not re.fullmatch(pattern, backup_id) or relative.startswith(".backups/"):
            raise SecurityError("备份ID与恢复目标不符。")
        raw = self.read_bytes(backup_id)
        result = self._write_bytes(relative, raw, 4 * 1024 * 1024)
        return {"restored_from":backup_id, **result}

