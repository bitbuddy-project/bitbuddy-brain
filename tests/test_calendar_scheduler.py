from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-calendar-scheduler-test-")

from bitbuddy.autonomy.delivery_scheduler import set_active_visible_chat  # noqa: E402
from bitbuddy.autonomy.intentions import ensure_intentions_database, list_pending_intentions  # noqa: E402
from bitbuddy.calendar import scheduler, store  # noqa: E402
from bitbuddy.chats.repository import create_chat, ensure_chat_database, get_chat  # noqa: E402
from bitbuddy.continuity import ensure_continuity_database  # noqa: E402
from bitbuddy.notifications import ensure_notification_database, list_notifications  # noqa: E402
from bitbuddy.paths import GLOBAL_DB_PATH  # noqa: E402


class CalendarSchedulerTest(unittest.TestCase):
    def setUp(self) -> None:
        store.ensure_calendar_database()
        ensure_chat_database()
        ensure_continuity_database()
        ensure_notification_database()
        ensure_intentions_database()
        set_active_visible_chat("")
        with closing(sqlite3.connect(GLOBAL_DB_PATH)) as connection, connection:
            connection.execute("delete from calendar_reminders")
            connection.execute("delete from calendar_events")
            connection.execute("delete from chat_messages")
            connection.execute("delete from chats")
            connection.execute("delete from continuity_events")
            connection.execute("delete from notifications")
            connection.execute("delete from intentions")
            connection.execute("delete from intention_surfaces")

    def test_upcoming_reminder_creates_notification_immediately(self) -> None:
        self._insert_event("Heads up meeting", minutes_out=30)

        scheduler._process_reminders(self._config(chat_nudges_enabled=False))

        notifications = list_notifications()
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0].category, "reminder")
        self.assertEqual(notifications[0].severity, "info")
        self.assertEqual(notifications[0].metadata["calendar_reminder_kind"], "upcoming")
        self.assertFalse(notifications[0].metadata["calendar_urgent"])

    def test_starting_soon_reminder_creates_urgent_persistent_notification(self) -> None:
        event = self._insert_event("Leave for appointment", minutes_out=5)

        scheduler._process_reminders(self._config(chat_nudges_enabled=False))

        notifications = list_notifications()
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0].severity, "warning")
        self.assertEqual(notifications[0].metadata["calendar_reminder_kind"], "starting_soon")
        self.assertTrue(notifications[0].metadata["calendar_urgent"])
        self.assertTrue(notifications[0].metadata["persistent"])
        self.assertEqual(notifications[0].metadata["calendar_event_id"], event.id)

    def test_reminder_notification_does_not_depend_on_autonomy_or_intention_cooldown(self) -> None:
        self._insert_event("Cooldown proof appointment", minutes_out=5)
        with closing(sqlite3.connect(GLOBAL_DB_PATH)) as connection, connection:
            connection.execute(
                "insert into intention_surfaces (chat_id, intention_id, surfaced_at, metadata) values (?, ?, current_timestamp, ?)",
                ("chat-1", 1, "{}"),
            )

        scheduler._process_reminders(self._config(autonomy_enabled=False, chat_nudges_enabled=True))

        notifications = list_notifications()
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0].metadata["calendar_reminder_kind"], "starting_soon")
        self.assertEqual(list_pending_intentions(), [])

    def test_starting_soon_reminder_posts_directly_to_active_chat(self) -> None:
        chat = create_chat("Today", "chat")
        set_active_visible_chat(chat.id)
        event = self._insert_event("Doctor appointment", minutes_out=5)

        scheduler._process_reminders(self._config(chat_nudges_enabled=True))

        persisted = get_chat(chat.id)
        assistant_text = "\n".join(str(message["content"]) for message in persisted["messages"] if message["role"] == "assistant")
        notifications = list_notifications()
        self.assertIn("Calendar reminder - starting soon", assistant_text)
        self.assertIn("Doctor appointment", assistant_text)
        self.assertEqual(list_pending_intentions(), [])
        self.assertEqual(notifications[0].chat_id, chat.id)
        self.assertEqual(notifications[0].action_url, f"/?chat_id={chat.id}")
        self.assertEqual(notifications[0].metadata["calendar_event_id"], event.id)

    def test_upcoming_reminder_posts_directly_to_chat_when_enabled(self) -> None:
        chat = create_chat("Today", "chat")
        set_active_visible_chat(chat.id)
        self._insert_event("Planning block", minutes_out=30)

        scheduler._process_reminders(self._config(chat_nudges_enabled=True))

        persisted = get_chat(chat.id)
        assistant_text = "\n".join(str(message["content"]) for message in persisted["messages"] if message["role"] == "assistant")
        self.assertIn("Calendar reminder: Upcoming: Planning block", assistant_text)
        self.assertEqual(list_pending_intentions(), [])

    def test_duplicate_scheduler_ticks_do_not_duplicate_reminders(self) -> None:
        self._insert_event("No duplicate reminder", minutes_out=5)
        config = self._config(chat_nudges_enabled=False)

        scheduler._process_reminders(config)
        scheduler._process_reminders(config)

        self.assertEqual(len(list_notifications()), 1)

    def _insert_event(self, title: str, *, minutes_out: int):
        _account, calendar = store.ensure_default_calendar("UTC")
        start = datetime.now(timezone.utc) + timedelta(minutes=minutes_out)
        end = start + timedelta(minutes=30)
        return store.insert_event(
            calendar_id=calendar.id,
            title=title,
            start_at=start.isoformat(),
            end_at=end.isoformat(),
            timezone_name="UTC",
        )

    def _config(self, *, autonomy_enabled: bool = True, chat_nudges_enabled: bool = True):
        return SimpleNamespace(
            user_context=SimpleNamespace(timezone="UTC"),
            autonomy=SimpleNamespace(enabled=autonomy_enabled),
            calendar=SimpleNamespace(
                reminder_upcoming_minutes=60,
                reminder_starting_soon_minutes=15,
                urgent_interrupts_enabled=True,
                urgent_interrupt_persistent=True,
                conflict_warnings_enabled=False,
                chat_nudges_enabled=chat_nudges_enabled,
            ),
        )


if __name__ == "__main__":
    unittest.main()
