from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-tasks-test-")

from bitbuddy.autonomy.delivery_scheduler import set_active_visible_chat  # noqa: E402
from bitbuddy.chats.repository import create_chat, ensure_chat_database, get_chat  # noqa: E402
from bitbuddy.continuity import ensure_continuity_database  # noqa: E402
from bitbuddy.notifications import ensure_notification_database, list_notifications  # noqa: E402
from bitbuddy.paths import GLOBAL_DB_PATH  # noqa: E402
from bitbuddy.tasks import scheduler, store  # noqa: E402
from bitbuddy.toolbox.base import ToolCall, ToolExecutor  # noqa: E402
from bitbuddy.toolbox.registry import default_tool_registry  # noqa: E402


def _past(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


def _future(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


class TaskStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        store.ensure_tasks_database()
        with closing(sqlite3.connect(GLOBAL_DB_PATH)) as connection, connection:
            connection.execute("delete from tasks")

    def test_create_and_list_round_trip(self) -> None:
        task = store.create_task("Call the dentist", remind_at=_future(60), priority=4)
        self.assertEqual(task.status, "open")
        self.assertEqual(task.priority, 4)
        self.assertIsNotNone(task.remind_at)
        self.assertEqual([t.title for t in store.list_tasks("open")], ["Call the dentist"])

    def test_blank_title_rejected(self) -> None:
        with self.assertRaises(ValueError):
            store.create_task("   ")

    def test_complete_sets_status_and_completed_at(self) -> None:
        task = store.create_task("Review PR")
        done = store.complete_task(task.id)
        self.assertEqual(done.status, "done")
        self.assertTrue(done.completed_at)
        self.assertEqual(store.list_tasks("open"), [])
        self.assertEqual([t.title for t in store.list_tasks("done")], ["Review PR"])

    def test_update_clears_completed_when_reopened(self) -> None:
        task = store.create_task("Groceries")
        store.complete_task(task.id)
        reopened = store.update_task(task.id, status="open")
        self.assertEqual(reopened.status, "open")
        self.assertIsNone(reopened.completed_at)

    def test_update_fields_and_clear_remind(self) -> None:
        task = store.create_task("Thing", remind_at=_future(30))
        updated = store.update_task(task.id, title="Better thing", remind_at="")
        self.assertEqual(updated.title, "Better thing")
        self.assertIsNone(updated.remind_at)

    def test_delete(self) -> None:
        task = store.create_task("Temporary")
        self.assertTrue(store.delete_task(task.id))
        self.assertFalse(store.delete_task(task.id))
        with self.assertRaises(ValueError):
            store.get_task(task.id)

    def test_due_tasks_to_fire_only_returns_open_past_unfired(self) -> None:
        due = store.create_task("Due now", remind_at=_past(1))
        store.create_task("Future", remind_at=_future(60))
        store.create_task("No reminder")
        done = store.create_task("Done one", remind_at=_past(1))
        store.complete_task(done.id)

        fire = store.due_tasks_to_fire()
        self.assertEqual([t.id for t in fire], [due.id])

    def test_mark_reminded_dedupes(self) -> None:
        task = store.create_task("Once", remind_at=_past(1))
        self.assertEqual(len(store.due_tasks_to_fire()), 1)
        store.mark_task_reminded(task.id)
        self.assertEqual(store.due_tasks_to_fire(), [])

    def test_naive_remind_time_uses_user_timezone(self) -> None:
        # A time with no offset (model resolving "5pm") must be interpreted in
        # the user's timezone, not UTC. America/Halifax is UTC-3 in June, so
        # 17:00 local is 20:00 UTC — regression guard for the off-by-tz bug.
        with patch.object(store, "_user_timezone", return_value="America/Halifax"):
            task = store.create_task("Dinner reminder", remind_at="2026-06-26T17:00")
        self.assertEqual(task.remind_at, "2026-06-26T20:00:00+00:00")

    def test_offset_aware_remind_time_is_respected(self) -> None:
        with patch.object(store, "_user_timezone", return_value="America/Halifax"):
            task = store.create_task("Has offset", remind_at="2026-06-26T17:00-04:00")
        self.assertEqual(task.remind_at, "2026-06-26T21:00:00+00:00")


class TaskSchedulerTest(unittest.TestCase):
    def setUp(self) -> None:
        store.ensure_tasks_database()
        ensure_chat_database()
        ensure_continuity_database()
        ensure_notification_database()
        set_active_visible_chat("")
        with closing(sqlite3.connect(GLOBAL_DB_PATH)) as connection, connection:
            connection.execute("delete from tasks")
            connection.execute("delete from chat_messages")
            connection.execute("delete from chats")
            connection.execute("delete from continuity_events")
            connection.execute("delete from notifications")

    def test_due_task_fires_notification_once(self) -> None:
        store.create_task("Call the dentist", remind_at=_past(1), priority=4)

        scheduler._process_due_tasks()

        notifications = list_notifications()
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0].category, "reminder")
        self.assertEqual(notifications[0].source_kind, "task")
        self.assertEqual(notifications[0].severity, "warning")  # priority >= 4
        self.assertEqual(notifications[0].action_url, "/tasks")

        # A second tick must not re-fire (reminded_at dedup).
        scheduler._process_due_tasks()
        self.assertEqual(len(list_notifications()), 1)

    def test_reminder_is_toast_only_not_chat(self) -> None:
        # Reminders surface as a toast notification, never a chat message.
        chat = create_chat("Today", "chat")
        set_active_visible_chat(chat.id)
        store.create_task("Stretch break", remind_at=_past(1))

        scheduler._process_due_tasks()

        persisted = get_chat(chat.id)
        assistant_messages = [m for m in persisted["messages"] if m["role"] == "assistant"]
        self.assertEqual(assistant_messages, [])
        notification = list_notifications()[0]
        self.assertEqual(notification.chat_id, "")
        self.assertEqual(notification.action_url, "/tasks")


class TaskToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        store.ensure_tasks_database()
        with closing(sqlite3.connect(GLOBAL_DB_PATH)) as connection, connection:
            connection.execute("delete from tasks")
        self.executor = ToolExecutor(default_tool_registry(), mode="chat")

    def _run(self, tool: str, arguments: dict) -> object:
        return self.executor.execute(ToolCall(tool=tool, arguments=arguments))

    def test_create_then_list(self) -> None:
        created = self._run("create_task", {"title": "Ship tasks feature", "priority": 3})
        self.assertTrue(created.ok)
        listed = self._run("list_tasks", {"status": "open"})
        self.assertTrue(listed.ok)
        self.assertIn("Ship tasks feature", listed.content)

    def test_complete_via_tool(self) -> None:
        task = store.create_task("Close me")
        result = self._run("complete_task", {"task_id": task.id})
        self.assertTrue(result.ok)
        self.assertEqual(store.get_task(task.id).status, "done")

    def test_list_tasks_allowed_in_plan_mode(self) -> None:
        store.create_task("Visible while planning")
        plan_executor = ToolExecutor(default_tool_registry(), mode="plan")
        result = plan_executor.execute(ToolCall(tool="list_tasks", arguments={}))
        self.assertTrue(result.ok)
        # Mutations stay blocked in plan mode.
        blocked = plan_executor.execute(ToolCall(tool="create_task", arguments={"title": "nope"}))
        self.assertFalse(blocked.ok)


if __name__ == "__main__":
    unittest.main()
