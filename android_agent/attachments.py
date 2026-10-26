"""Validated user-selected attachments; contents live in the private workspace, not events."""
from __future__ import annotations
import base64
import binascii
import hashlib
import os
import re
import stat
import uuid
from typing import Any
from .security import SecurityError

MAX_FILE = 20 * 1024 * 1024
MAX_TOTAL = 30 * 1024 * 1024
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


def prepare(values: Any, supports_images: bool) -> list[tuple[dict, bytes]]:
    if values is None:
        return []
    if not isinstance(values, list) or len(values) > 8:
        raise ValueError("最多添加8个附件。")
    result, total = [], 0
    for item in values:
        if not isinstance(item, dict) or set(item) != {"name", "mime_type", "data"}:
            raise ValueError("附件需要name、mime_type和base64 data。")
        name, mime, data = item["name"], item["mime_type"], item["data"]
        if not isinstance(name, str) or not name or len(name) > 240 or any(ord(c) < 32 for c in name) or "/" in name or chr(92) in name:
            raise ValueError("附件文件名无效。")
        if not isinstance(mime, str) or len(mime) > 120 or not re.fullmatch(r"[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+", mime):
            raise ValueError("附件MIME类型无效。")
        if not isinstance(data, str) or len(data) > (MAX_FILE + 2) // 3 * 4:
            raise ValueError("单个附件不能超过20 MiB。")
        try:
            raw = base64.b64decode(data, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("附件base64编码无效。") from exc
        total += len(raw)
        if len(raw) > MAX_FILE or total > MAX_TOTAL:
            raise ValueError("单个附件最多20 MiB，合计最多30 MiB。")
        if mime.startswith("image/"):
            if not supports_images:
                raise ValueError("当前模型未开启图片识别，请切换支持图片的模型。")
            valid = (mime == "image/png" and raw.startswith(b"\x89PNG\r\n\x1a\n") or
                     mime == "image/jpeg" and raw.startswith(b"\xff\xd8\xff") or
                     mime == "image/gif" and raw[:6] in {b"GIF87a", b"GIF89a"} or
                     mime == "image/webp" and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")
            if not valid:
                raise ValueError("图片类型或文件头无效，仅支持PNG、JPEG、GIF、WebP。")
        attachment_id = uuid.uuid4().hex
        result.append(({"id": attachment_id, "name": name, "mime_type": mime, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "path": "attachments/" + attachment_id + "/payload"}, raw))
    return result


def save(workspace: Any, prepared: list[tuple[dict, bytes]]) -> list[dict]:
    for metadata, raw in prepared:
        workspace._write_bytes(metadata["path"], raw, MAX_FILE)
    return [metadata for metadata, _ in prepared]


def discard(workspace: Any, metadata: list[dict]) -> None:
    for item in metadata:
        parts = workspace.parts(item["path"])
        if os.name == "nt" or not hasattr(os, "O_NOFOLLOW"):
            target = workspace._resolved(item["path"])
            if not target.is_symlink():
                target.unlink(missing_ok=True)
                try:
                    target.parent.rmdir()
                except OSError:
                    pass
            continue
        parent, name = workspace._open_parent(parts)
        try:
            try:
                os.unlink(name, dir_fd=parent)
            except FileNotFoundError:
                pass
        finally:
            os.close(parent)
        parent, name = workspace._open_parent(parts[:-1])
        try:
            try:
                os.rmdir(name, dir_fd=parent)
            except OSError:
                pass
        finally:
            os.close(parent)


def _read(workspace: Any, item: dict) -> bytes:
    relative = item["path"]
    parts = workspace.parts(relative)
    if os.name == "nt" or not hasattr(os, "O_NOFOLLOW"):
        target = workspace._resolved(relative)
        if not target.is_file() or target.stat().st_size > MAX_FILE:
            raise ValueError("附件已被移动或修改，请重新添加：" + item["name"])
        with target.open("rb") as stream:
            raw = stream.read(MAX_FILE + 1)
    else:
        parent, name = workspace._open_parent(parts)
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        finally:
            os.close(parent)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE:
                raise SecurityError("附件必须是允许大小内的普通文件。")
            with os.fdopen(fd, "rb") as stream:
                fd = -1
                raw = stream.read(MAX_FILE + 1)
        finally:
            if fd >= 0:
                os.close(fd)
    if len(raw) > MAX_FILE or len(raw) != item["bytes"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
        raise ValueError("附件已被修改，请重新添加：" + item["name"])
    return raw


def content(workspace: Any, text: str, metadata: list[dict], supports_images: bool = True) -> str | list[dict]:
    parts: list[dict] = []
    notes = []
    for item in metadata:
        raw = _read(workspace, item)
        if item["mime_type"] in IMAGE_TYPES:
            if supports_images:
                parts.append({"type": "image_url", "image_url": {"url": "data:" + item["mime_type"] + ";base64," + base64.b64encode(raw).decode("ascii"), "detail": "low"}})
            else:
                notes.append("历史图片附件未发送（当前模型未开启图片支持）：" + item["name"])
        else:
            note = "用户附件：" + item["name"] + "；工作区相对路径：" + item["path"]
            if len(raw) <= 512 * 1024:
                try:
                    decoded = raw.decode("utf-8")
                    if "\x00" not in decoded:
                        note += "\n<attachment-text>\n" + decoded + "\n</attachment-text>"
                except UnicodeDecodeError:
                    pass
            notes.append(note)
    combined = text + (("\n\n" if text else "") + "\n\n".join(notes) if notes else "")
    if not parts:
        return combined
    return [{"type": "text", "text": combined or "请查看所附图片。"}, *parts]
