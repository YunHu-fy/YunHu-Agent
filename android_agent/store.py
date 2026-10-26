from __future__ import annotations

import json
from contextlib import contextmanager
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

TERMINAL = {"succeeded", "failed", "cancelled", "timed_out"}


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                PRAGMA synchronous=FULL;
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at REAL NOT NULL,
                    updated_at REAL NOT NULL, current_task_id TEXT
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, position INTEGER NOT NULL,
                    role TEXT NOT NULL, content TEXT NOT NULL DEFAULT '', task_id TEXT,
                    status TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    UNIQUE(conversation_id,position),
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id,position);
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, message TEXT NOT NULL, origin TEXT NOT NULL,
                    state TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    assistant_text TEXT NOT NULL DEFAULT '', error TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    task_id TEXT NOT NULL, seq INTEGER NOT NULL, created_at REAL NOT NULL,
                    event TEXT NOT NULL, data TEXT NOT NULL,
                    PRIMARY KEY(task_id, seq), FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, created_at REAL NOT NULL,
                    task_id TEXT, tool TEXT NOT NULL, decision TEXT NOT NULL, details TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS audit_created ON audit(created_at DESC);
                CREATE INDEX IF NOT EXISTS events_task ON events(task_id, seq);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(tasks)")}
            for name, spec in {"conversation_id": "TEXT", "user_message_id": "TEXT", "assistant_message_id": "TEXT", "full_access": "INTEGER NOT NULL DEFAULT 0", "channel": "TEXT NOT NULL DEFAULT 'normal'", "runtime": "TEXT NOT NULL DEFAULT 'system'", "deadline_at": "REAL"}.items():
                if name not in columns:
                    db.execute("ALTER TABLE tasks ADD COLUMN " + name + " " + spec)
            db.execute("CREATE TABLE IF NOT EXISTS message_attachments (message_id TEXT PRIMARY KEY, metadata TEXT NOT NULL, FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE)")
            db.execute("CREATE TABLE IF NOT EXISTS context_memories (conversation_id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at REAL NOT NULL, FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE)")
            db.execute("CREATE TABLE IF NOT EXISTS context_records (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, task_id TEXT NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL, created_at REAL NOT NULL, FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE, FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE)")
            db.execute("CREATE INDEX IF NOT EXISTS context_records_conversation ON context_records(conversation_id,created_at DESC,id DESC)")
            db.execute("CREATE TABLE IF NOT EXISTS task_checkpoints (task_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, payload TEXT NOT NULL, updated_at REAL NOT NULL, FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE, FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE)")
            now = time.time()
            interrupted = db.execute("SELECT id,assistant_message_id FROM tasks WHERE state NOT IN ('succeeded','failed','cancelled','timed_out')").fetchall()
            db.execute("UPDATE tasks SET state='failed', error='服务重启，未完成任务已停止。', updated_at=? WHERE state NOT IN ('succeeded','failed','cancelled','timed_out')", (now,))
            for row in interrupted:
                db.execute("UPDATE messages SET status='failed',updated_at=? WHERE id=?", (now, row["assistant_message_id"]))
                seq = db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE task_id=?", (row["id"],)).fetchone()[0]
                db.execute("INSERT INTO events VALUES(?,?,?,?,?)", (row["id"], seq, now, "task_error", json.dumps({"task_id": row["id"], "message": "服务重启，未完成任务已停止。"}, ensure_ascii=False)))
            db.execute("UPDATE conversations SET current_task_id=NULL WHERE current_task_id IN (SELECT id FROM tasks WHERE state IN ('succeeded','failed','cancelled','timed_out'))")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level="IMMEDIATE")
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create_task(self, task: dict[str, Any]) -> None:
        with self._lock, self._connect() as db:
            conversation_id = task.get("conversation_id")
            if conversation_id:
                row = db.execute("SELECT current_task_id FROM conversations WHERE id=?", (conversation_id,)).fetchone()
                if row is None:
                    raise ValueError("对话不存在。")
                if row["current_task_id"]:
                    active = db.execute("SELECT state FROM tasks WHERE id=?", (row["current_task_id"],)).fetchone()
                    if active and active["state"] not in TERMINAL:
                        raise RuntimeError("此对话已有运行中的任务，请等待或先中断。")
            db.execute("INSERT INTO tasks(id,message,origin,state,created_at,updated_at,assistant_text,error,conversation_id,user_message_id,assistant_message_id,full_access,channel,runtime,deadline_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                task["id"], task["message"], task["origin"], task.get("state", task.get("status", "queued")), task["created_at"], task["updated_at"], task.get("assistant_text", ""), task.get("error"),
                conversation_id, task.get("user_message_id"), task.get("assistant_message_id"), int(task.get("full_access", False)), task.get("channel", "normal"), task.get("runtime", "system"), task.get("deadline_at"),
            ))
            if conversation_id:
                position = db.execute("SELECT COALESCE(MAX(position),0) FROM messages WHERE conversation_id=?", (conversation_id,)).fetchone()[0]
                now = task["created_at"]
                for offset, role, content, msg_id in ((1, "user", task["message"], task["user_message_id"]), (2, "assistant", "", task["assistant_message_id"])):
                    db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?,?,?,?)", (msg_id, conversation_id, position + offset, role, content, task["id"], "complete" if role == "user" else "queued", now, now))
                if task.get("attachments"):
                    db.execute("INSERT INTO message_attachments VALUES(?,?)", (task["user_message_id"], json.dumps(task["attachments"], ensure_ascii=False)))
                db.execute("UPDATE conversations SET current_task_id=?,updated_at=? WHERE id=?", (task["id"], now, conversation_id))

    def update_task(self, task_id: str, state: str, updated_at: float, assistant_text: str | None = None, error: str | None = None) -> None:
        with self._lock, self._connect() as db:
            if assistant_text is None:
                db.execute("UPDATE tasks SET state=?,updated_at=?,error=? WHERE id=?", (state, updated_at, error, task_id))
            else:
                db.execute("UPDATE tasks SET state=?,updated_at=?,assistant_text=?,error=? WHERE id=?", (state, updated_at, assistant_text, error, task_id))
            row = db.execute("SELECT conversation_id,assistant_message_id,assistant_text FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row and row["conversation_id"]:
                db.execute("UPDATE messages SET content=?,status=?,updated_at=? WHERE id=?", (row["assistant_text"], state, updated_at, row["assistant_message_id"]))
                db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (updated_at, row["conversation_id"]))
                if state in TERMINAL:
                    db.execute("UPDATE conversations SET current_task_id=NULL WHERE id=? AND current_task_id=?", (row["conversation_id"], task_id))

    def append_event(self, task_id: str, created_at: float, event: str, data: dict[str, Any], keep: int = 1200) -> int:
        encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        with self._lock, self._connect() as db:
            row = db.execute("SELECT COALESCE(MAX(seq),0)+1 AS seq FROM events WHERE task_id=?", (task_id,)).fetchone()
            seq = int(row["seq"])
            db.execute("INSERT INTO events(task_id,seq,created_at,event,data) VALUES(?,?,?,?,?)", (task_id, seq, created_at, event, encoded))
            db.execute("DELETE FROM events WHERE task_id=? AND seq <= ?", (task_id, max(0, seq - keep)))
            return seq

    def events_after(self, task_id: str, after: int, limit: int = 500) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT seq,event,data,created_at FROM events WHERE task_id=? AND seq>? ORDER BY seq LIMIT ?", (task_id, after, limit)).fetchall()
        return [{"id": row["seq"], "event": row["event"], "data": json.loads(row["data"]), "created_at": row["created_at"]} for row in rows]

    def event_bounds(self, task_id: str) -> tuple[int, int]:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT COALESCE(MIN(seq),0) AS lo, COALESCE(MAX(seq),0) AS hi FROM events WHERE task_id=?", (task_id,)).fetchone()
        return int(row["lo"]), int(row["hi"])

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None

    def create_conversation(self, title: str = "新对话") -> dict[str, Any]:
        if not isinstance(title, str) or not title.strip() or len(title) > 200 or any(ord(char) < 32 for char in title):
            raise ValueError("对话标题必须是1..200字符。")
        now = time.time()
        item = {"id": uuid.uuid4().hex, "title": title.strip(), "created_at": now, "updated_at": now, "current_task_id": None}
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO conversations VALUES(?,?,?,?,?)", tuple(item.values()))
        return item

    def list_conversations(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS message_count FROM conversations c ORDER BY updated_at DESC,id LIMIT ?", (max(1, min(500, limit)),)).fetchall()
        return [dict(row) for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        return dict(row) if row else None

    def save_attachments(self, message_id: str, metadata: list[dict[str, Any]]) -> None:
        with self._lock, self._connect() as db:
            db.execute("INSERT OR REPLACE INTO message_attachments VALUES(?,?)", (message_id, json.dumps(metadata, ensure_ascii=False)))

    def messages(self, conversation_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT * FROM (SELECT * FROM messages WHERE conversation_id=? ORDER BY position DESC LIMIT ?) ORDER BY position", (conversation_id, max(1, min(10000, limit)))).fetchall()
            metadata = {row["message_id"]: json.loads(row["metadata"]) for row in db.execute("SELECT a.* FROM message_attachments a JOIN messages m ON m.id=a.message_id WHERE m.conversation_id=?", (conversation_id,))}
        return [{**dict(row), "attachments": metadata.get(row["id"], [])} for row in rows]

    def conversation_tasks(self, conversation_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT * FROM tasks WHERE conversation_id=? ORDER BY created_at DESC,id LIMIT ?", (conversation_id, limit)).fetchall()
        return [dict(row) for row in rows]

    def get_context_memory(self, conversation_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT payload FROM context_memories WHERE conversation_id=?", (conversation_id,)).fetchone()
        return json.loads(row[0]) if row else {}

    def set_context_memory(self, conversation_id: str, payload: dict[str, Any]) -> None:
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO context_memories VALUES(?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at", (conversation_id, json.dumps(payload, ensure_ascii=False), time.time()))

    def save_checkpoint(self, task_id: str, conversation_id: str, payload: dict[str, Any]) -> None:
        with self._lock, self._connect() as db:
            text = json.dumps(payload, ensure_ascii=False)
            db.execute("INSERT INTO task_checkpoints VALUES(?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at", (task_id, conversation_id, text, time.time()))
            prior = db.execute("SELECT m.payload FROM context_memories m WHERE conversation_id=?", (conversation_id,)).fetchone()
            previous = json.loads(prior[0]) if prior else {}
            previous_task = db.execute("SELECT created_at FROM tasks WHERE id=?", (previous.get("task_id", ""),)).fetchone()
            current_task = db.execute("SELECT created_at FROM tasks WHERE id=?", (task_id,)).fetchone()
            if not previous_task or (current_task and current_task[0] >= previous_task[0]):
                db.execute("INSERT INTO context_memories VALUES(?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at", (conversation_id, text, time.time()))

    def get_checkpoint(self, task_id: str) -> dict[str, Any]:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT payload FROM task_checkpoints WHERE task_id=?", (task_id,)).fetchone()
        return json.loads(row[0]) if row else {}

    def archive_context(self, conversation_id: str, task_id: str, kind: str, content: str) -> str:
        record_id = uuid.uuid4().hex
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO context_records VALUES(?,?,?,?,?,?)", (record_id, conversation_id, task_id, kind, content, time.time()))
        return record_id

    def recall_context(self, conversation_id: str, record_id: str = "", offset: int = 0, limit: int = 4096, query: str = "") -> dict[str, Any]:
        if not isinstance(record_id, str) or len(record_id) > 32 or type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 8192 or not isinstance(query, str) or len(query) > 200:
            raise ValueError("记忆分页参数无效。")
        with self._lock, self._connect() as db:
            if not record_id:
                count = db.execute("SELECT COUNT(*) FROM context_records WHERE conversation_id=? AND (? = '' OR instr(content,?) > 0)", (conversation_id, query, query)).fetchone()[0]
                rows = db.execute("SELECT id,task_id,kind,length(content) AS chars,created_at FROM context_records WHERE conversation_id=? AND (? = '' OR instr(content,?) > 0) ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?", (conversation_id, query, query, min(40, limit), offset)).fetchall()
                next_offset = min(count, offset + len(rows))
                return {"ok": True, "records": [dict(row) for row in rows], "offset": min(offset, count), "next_offset": next_offset, "total_records": count, "has_more": next_offset < count}
            row = db.execute("SELECT content,kind,task_id FROM context_records WHERE id=? AND conversation_id=?", (record_id, conversation_id)).fetchone()
        if row is None:
            raise ValueError("记忆记录不存在或不属于当前对话。")
        text = row["content"]
        if query:
            found = text.find(query, offset)
            if found < 0:
                return {"ok": True, "record_id": record_id, "found": False, "total_chars": len(text)}
            offset = max(offset, found - min(256, limit // 4))
        offset = min(offset, len(text))
        end = min(len(text), offset + limit)
        return {"ok": True, "record_id": record_id, "kind": row["kind"], "task_id": row["task_id"], "offset": offset, "next_offset": end, "total_chars": len(text), "has_more": end < len(text), "content": text[offset:end]}

    def _editable_turn(self, db: sqlite3.Connection, conversation_id: str, message_id: str) -> sqlite3.Row:
        conversation = db.execute("SELECT id FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        if conversation is None:
            raise LookupError("对话不存在。")
        active = db.execute(
            "SELECT id FROM tasks WHERE conversation_id=? AND state NOT IN ('succeeded','failed','cancelled','timed_out') LIMIT 1",
            (conversation_id,),
        ).fetchone()
        if active is not None:
            raise RuntimeError("此对话存在活动任务，请等待任务结束后再编辑或删除消息。")
        latest = db.execute(
            "SELECT id,position FROM messages WHERE conversation_id=? AND role='user' ORDER BY position DESC LIMIT 1",
            (conversation_id,),
        ).fetchone()
        if latest is None or latest["id"] != message_id:
            raise ValueError("只能编辑或删除当前对话最近一轮的用户消息。")
        row = db.execute(
            """
            SELECT m.id AS message_id,m.position AS message_position,m.role AS message_role,
                   m.content AS message_content,m.status AS message_status,
                   t.id AS task_id,t.message AS task_message,t.origin AS task_origin,t.state AS task_state,
                   t.conversation_id AS task_conversation_id,t.user_message_id,t.assistant_message_id,
                   t.assistant_text,
                   a.id AS assistant_id,a.position AS assistant_position,a.role AS assistant_role,
                   a.content AS assistant_content,a.status AS assistant_status
              FROM messages m
              JOIN tasks t ON t.id=m.task_id
              JOIN messages a ON a.id=t.assistant_message_id
             WHERE m.id=? AND m.conversation_id=? AND m.role='user'
            """,
            (message_id, conversation_id),
        ).fetchone()
        if row is None:
            raise ValueError("消息不存在、不是可编辑的用户消息，或消息关联已损坏。")
        max_position = db.execute(
            "SELECT COALESCE(MAX(position),0) FROM messages WHERE conversation_id=?",
            (conversation_id,),
        ).fetchone()[0]
        if (
            row["task_origin"] != "chat"
            or row["task_conversation_id"] != conversation_id
            or row["user_message_id"] != message_id
            or row["assistant_role"] != "assistant"
            or row["assistant_position"] != row["message_position"] + 1
            or row["assistant_position"] != max_position
            or row["message_status"] != "complete"
            or row["message_content"] != row["task_message"]
            or row["assistant_content"] != row["assistant_text"]
            or row["assistant_status"] != row["task_state"]
        ):
            raise ValueError("消息未形成当前对话的一致、完整最近一轮，拒绝修改。")
        if row["task_state"] not in TERMINAL:
            raise RuntimeError("该消息对应的任务仍在运行，请等待任务结束后再编辑或删除。")
        return row

    @staticmethod
    def _restore_context_memory(db: sqlite3.Connection, conversation_id: str, task_id: str) -> None:
        row = db.execute(
            "SELECT payload FROM context_memories WHERE conversation_id=?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            return
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict) or payload.get("task_id") != task_id:
            return
        previous = db.execute(
            """
            SELECT c.payload
              FROM task_checkpoints c
              JOIN tasks t ON t.id=c.task_id
             WHERE c.conversation_id=? AND c.task_id<>?
             ORDER BY t.created_at DESC,t.id DESC
             LIMIT 1
            """,
            (conversation_id, task_id),
        ).fetchone()
        if previous is None:
            db.execute("DELETE FROM context_memories WHERE conversation_id=?", (conversation_id,))
        else:
            db.execute(
                "UPDATE context_memories SET payload=?,updated_at=? WHERE conversation_id=?",
                (previous["payload"], time.time(), conversation_id),
            )

    @staticmethod
    def _validate_message_ids(conversation_id: str, message_id: str) -> None:
        for value in (conversation_id, message_id):
            if not isinstance(value, str) or len(value) != 32 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError("对话或消息ID格式无效。")

    def _remove_turn(self, conversation_id: str, message_id: str, *, edited_content: str | None) -> dict[str, Any]:
        self._validate_message_ids(conversation_id, message_id)
        now = time.time()
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = self._editable_turn(db, conversation_id, message_id)
            task_id = row["task_id"]
            assistant_id = row["assistant_id"]
            attachment_rows = db.execute(
                "SELECT metadata FROM message_attachments WHERE message_id IN (?,?)",
                (message_id, assistant_id),
            ).fetchall()
            attachments_to_cleanup: list[dict[str, Any]] = []
            for attachment_row in attachment_rows:
                try:
                    metadata = json.loads(attachment_row["metadata"])
                except (TypeError, ValueError):
                    continue
                if isinstance(metadata, list):
                    attachments_to_cleanup.extend(item for item in metadata if isinstance(item, dict))
            self._restore_context_memory(db, conversation_id, task_id)
            db.execute("DELETE FROM messages WHERE id IN (?,?)", (message_id, assistant_id))
            db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
            db.execute(
                "UPDATE conversations SET current_task_id=NULL,updated_at=? WHERE id=?",
                (now, conversation_id),
            )
            operation = "edited" if edited_content is not None else "deleted"
            db.execute(
                "INSERT INTO audit(created_at,task_id,tool,decision,details) VALUES(?,?,?,?,?)",
                (now, task_id, "conversation.message", operation, json.dumps({"conversation_id": conversation_id, "message_id": message_id}, ensure_ascii=False, separators=(",", ":"))),
            )
            return {
                "ok": True,
                "old_task_id": task_id,
                "old_user_message_id": message_id,
                "old_assistant_message_id": assistant_id,
                "old_message_ids": [message_id, assistant_id],
                "_attachments_for_cleanup": attachments_to_cleanup,
            }

    def edit_message(self, conversation_id: str, message_id: str, content: str) -> dict[str, Any]:
        if (
            not isinstance(content, str)
            or not content.strip()
            or len(content) > 8000
            or any((ord(char) < 32 and char not in "\n\r\t") or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF for char in content)
        ):
            raise ValueError("消息内容必须是1..8000字符，且不能包含控制字符。")
        result = self._remove_turn(conversation_id, message_id, edited_content=content.strip())
        result["edited_content"] = content.strip()
        result["resubmit_required"] = True
        return result

    def delete_message(self, conversation_id: str, message_id: str) -> dict[str, Any]:
        return self._remove_turn(conversation_id, message_id, edited_content=None)

    def rename_conversation(self, conversation_id: str, title: Any) -> dict[str, Any] | None:
        if not isinstance(title, str) or not title.strip() or len(title) > 200 or any(ord(char) < 32 for char in title):
            raise ValueError("对话标题必须是1..200字符。")
        with self._lock, self._connect() as db:
            db.execute("UPDATE conversations SET title=?,updated_at=? WHERE id=?", (title.strip(), time.time(), conversation_id))
        return self.get_conversation(conversation_id)

    def delete_conversation(self, conversation_id: str) -> bool:
        with self._lock, self._connect() as db:
            active = db.execute("SELECT id FROM tasks WHERE conversation_id=? AND state NOT IN ('succeeded','failed','cancelled','timed_out')", (conversation_id,)).fetchone()
            if active:
                raise RuntimeError("请先中断此对话的活动任务再删除。")
            db.execute("DELETE FROM events WHERE task_id IN (SELECT id FROM tasks WHERE conversation_id=?)", (conversation_id,))
            db.execute("DELETE FROM tasks WHERE conversation_id=?", (conversation_id,))
            return db.execute("DELETE FROM conversations WHERE id=?", (conversation_id,)).rowcount > 0

    def audit(self, task_id: str | None, tool: str, decision: str, details: dict[str, Any]) -> None:
        with self._lock, self._connect() as db:
            db.execute("INSERT INTO audit(created_at,task_id,tool,decision,details) VALUES(?,?,?,?,?)", (time.time(), task_id, tool, decision, json.dumps(details, ensure_ascii=False, separators=(",", ":"))))
            db.execute("DELETE FROM audit WHERE created_at < ?", (time.time() - 7 * 86400,))
            row = db.execute("SELECT COALESCE(MAX(id),0) AS top FROM audit").fetchone()
            if int(row["top"]) > 10000:
                db.execute("DELETE FROM audit WHERE id <= ?", (int(row["top"]) - 10000,))

    def list_audit(self, limit: int = 100, query: str = "") -> list[dict[str, Any]]:
        pattern = "%" + query.replace("%", "").replace("_", "") + "%"
        with self._lock, self._connect() as db:
            if query:
                rows = db.execute("SELECT * FROM audit WHERE tool LIKE ? OR decision LIKE ? OR details LIKE ? ORDER BY id DESC LIMIT ?", (pattern, pattern, pattern, limit)).fetchall()
            else:
                rows = db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": row["id"], "timestamp": row["created_at"], "task_id": row["task_id"], "tool": row["tool"], "decision": row["decision"], "details": json.loads(row["details"])} for row in rows]

    def sqlite_ready(self) -> bool:
        try:
            with self._connect() as db:
                return db.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        except sqlite3.Error:
            return False
