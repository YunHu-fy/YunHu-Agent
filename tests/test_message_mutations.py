"""Store-level regression tests for atomic chat turn edits and deletion."""
from __future__ import annotations

import tempfile
import time
import unittest
import uuid
from pathlib import Path

from android_agent.store import Store


class MessageMutationStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="message-mutations-")
        self.store = Store(Path(self.temporary.name) / "agent.sqlite3")
        self.conversation_id = self.store.create_conversation()["id"]

    def tearDown(self):
        self.temporary.cleanup()

    def add_turn(self, content="question", *, state="succeeded", reply="answer", with_attachments=False):
        now = time.time()
        task_id = uuid.uuid4().hex
        user_id = uuid.uuid4().hex
        assistant_id = uuid.uuid4().hex
        self.store.create_task({
            "id": task_id,
            "message": content,
            "origin": "chat",
            "state": "queued",
            "created_at": now,
            "updated_at": now,
            "assistant_text": "",
            "conversation_id": self.conversation_id,
            "user_message_id": user_id,
            "assistant_message_id": assistant_id,
        })
        self.store.update_task(task_id, state, time.time(), assistant_text=reply)
        self.store.append_event(task_id, time.time(), "task_completed", {"task_id": task_id})
        record_id = self.store.archive_context(self.conversation_id, task_id, "summary", "private context for " + content)
        checkpoint = {"version": 1, "task_id": task_id, "goal": content, "summary": "summary " + content, "state": state}
        self.store.save_checkpoint(task_id, self.conversation_id, checkpoint)
        if with_attachments:
            self.store.save_attachments(user_id, [{"id": "user-file-" + task_id, "name": "user.txt", "path": "attachments/user-" + task_id + "/payload", "bytes": 1}])
            self.store.save_attachments(assistant_id, [{"id": "assistant-file-" + task_id, "name": "assistant.txt", "path": "attachments/assistant-" + task_id + "/payload", "bytes": 1}])
        return {"task_id": task_id, "user_id": user_id, "assistant_id": assistant_id, "record_id": record_id, "checkpoint": checkpoint}

    def rows(self, query, params=()):
        with self.store._lock, self.store._connect() as db:
            return [dict(row) for row in db.execute(query, params).fetchall()]

    def test_edit_removes_old_turn_records_and_restores_previous_context(self):
        previous = self.add_turn("previous user", reply="previous assistant")
        current = self.add_turn("original user", reply="original assistant", with_attachments=True)
        current_memory = {"version": 1, "task_id": current["task_id"], "goal": "original user", "summary": "current summary"}
        self.store.set_context_memory(self.conversation_id, current_memory)

        result = self.store.edit_message(self.conversation_id, current["user_id"], "  corrected user  ")

        self.assertEqual(result["ok"], True)
        self.assertEqual(result["edited_content"], "corrected user")
        self.assertTrue(result["resubmit_required"])
        self.assertEqual(result["old_task_id"], current["task_id"])
        self.assertEqual(result["old_user_message_id"], current["user_id"])
        self.assertEqual(result["old_assistant_message_id"], current["assistant_id"])
        self.assertEqual(result["old_message_ids"], [current["user_id"], current["assistant_id"]])
        self.assertEqual({item["id"] for item in result["_attachments_for_cleanup"]}, {"user-file-" + current["task_id"], "assistant-file-" + current["task_id"]})
        remaining = self.store.messages(self.conversation_id)
        self.assertEqual([item["id"] for item in remaining], [previous["user_id"], previous["assistant_id"]])
        self.assertEqual([item["role"] for item in remaining], ["user", "assistant"])
        self.assertIsNotNone(self.store.get_task(previous["task_id"]))
        self.assertIsNone(self.store.get_task(current["task_id"]))
        self.assertEqual(self.store.events_after(current["task_id"], 0), [])
        self.assertEqual(self.store.get_checkpoint(current["task_id"]), {})
        self.assertEqual(self.store.recall_context(self.conversation_id)["total_records"], 1)
        self.assertEqual(self.store.recall_context(self.conversation_id)["records"][0]["task_id"], previous["task_id"])
        self.assertEqual(self.store.get_checkpoint(previous["task_id"]), previous["checkpoint"])
        self.assertEqual(self.store.get_context_memory(self.conversation_id)["task_id"], previous["task_id"])
        self.assertEqual(self.store.get_conversation(self.conversation_id)["current_task_id"], None)
        self.assertEqual(self.rows("SELECT message_id FROM message_attachments"), [])
        audit = self.store.list_audit(limit=1)[0]
        self.assertEqual(audit["task_id"], current["task_id"])
        self.assertEqual(audit["decision"], "edited")

    def test_delete_removes_pair_task_events_memory_checkpoint_and_attachments(self):
        turn = self.add_turn("delete me", with_attachments=True)
        self.store.set_context_memory(self.conversation_id, {"version": 1, "task_id": turn["task_id"], "goal": "delete me"})

        result = self.store.delete_message(self.conversation_id, turn["user_id"])

        self.assertTrue(result["ok"])
        self.assertEqual(result["old_message_ids"], [turn["user_id"], turn["assistant_id"]])
        self.assertEqual(self.store.messages(self.conversation_id), [])
        self.assertEqual(self.store.conversation_tasks(self.conversation_id), [])
        self.assertEqual(self.store.events_after(turn["task_id"], 0), [])
        self.assertEqual(self.store.get_checkpoint(turn["task_id"]), {})
        self.assertEqual(self.store.get_context_memory(self.conversation_id), {})
        self.assertEqual(self.store.recall_context(self.conversation_id)["total_records"], 0)
        self.assertEqual(self.rows("SELECT message_id FROM message_attachments"), [])
        self.assertEqual(len(result["_attachments_for_cleanup"]), 2)

    def test_only_latest_complete_turn_is_mutable(self):
        earlier = self.add_turn("first")
        latest = self.add_turn("second")

        with self.assertRaises(ValueError):
            self.store.edit_message(self.conversation_id, earlier["user_id"], "not allowed")
        with self.assertRaises(ValueError):
            self.store.delete_message(self.conversation_id, earlier["user_id"])
        with self.assertRaises(ValueError):
            self.store.delete_message(self.conversation_id, latest["assistant_id"])

        self.assertIsNotNone(self.store.get_task(earlier["task_id"]))
        self.assertIsNotNone(self.store.get_task(latest["task_id"]))
        self.assertEqual(len(self.store.messages(self.conversation_id)), 4)

    def test_active_task_is_rejected_without_mutation(self):
        turn = self.add_turn("still running", state="running")
        before = self.store.messages(self.conversation_id)

        with self.assertRaises(RuntimeError):
            self.store.edit_message(self.conversation_id, turn["user_id"], "new prompt")
        with self.assertRaises(RuntimeError):
            self.store.delete_message(self.conversation_id, turn["user_id"])

        self.assertEqual(self.store.messages(self.conversation_id), before)
        self.assertIsNotNone(self.store.get_task(turn["task_id"]))

    def test_edit_rejects_empty_oversized_and_control_content(self):
        turn = self.add_turn("unchanged")
        for invalid in ("  ", "x" * 8001, "bad\x00text"):
            with self.subTest(invalid=repr(invalid)), self.assertRaises(ValueError):
                self.store.edit_message(self.conversation_id, turn["user_id"], invalid)
        self.assertIsNotNone(self.store.get_task(turn["task_id"]))
        self.assertEqual(len(self.store.messages(self.conversation_id)), 2)

    def test_unknown_conversation_and_foreign_message_are_rejected(self):
        turn = self.add_turn("belongs here")
        other_conversation = self.store.create_conversation()["id"]
        with self.assertRaises(LookupError):
            self.store.delete_message("0" * 32, turn["user_id"])
        with self.assertRaises(ValueError):
            self.store.delete_message(other_conversation, turn["user_id"])
        self.assertIsNotNone(self.store.get_task(turn["task_id"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
