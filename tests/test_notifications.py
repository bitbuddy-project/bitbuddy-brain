from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-notifications-test-")

from bitbuddy.memory.consolidation import ConsolidationJob, notify_memory_consolidation_completed  # noqa: E402
from bitbuddy.notifications import (  # noqa: E402
    create_notification,
    dismiss_notification,
    ensure_notification_database,
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
    subscribe_notifications,
    unsubscribe_notifications,
    unread_notification_count,
)
from bitbuddy.paths import GLOBAL_DB_PATH  # noqa: E402


class NotificationsTest(unittest.TestCase):
    def setUp(self) -> None:
        ensure_notification_database()
        with closing(sqlite3.connect(GLOBAL_DB_PATH)) as connection, connection:
            connection.execute("delete from notifications")

    def test_notifications_can_be_read_and_dismissed(self) -> None:
        first = create_notification(category="memory", title="Memory updated", body="Saved a useful detail.")
        second = create_notification(category="autonomy", title="BitBuddy added a message", body="A queued question was delivered.")

        self.assertEqual(unread_notification_count(), 2)
        self.assertEqual([item.id for item in list_notifications(after_id=first.id)], [second.id])

        self.assertTrue(mark_notification_read(first.id))
        self.assertEqual(unread_notification_count(), 1)

        self.assertTrue(dismiss_notification(second.id))
        self.assertEqual(unread_notification_count(), 0)
        visible = list_notifications()
        self.assertEqual([item.id for item in visible], [first.id])
        self.assertIsNotNone(visible[0].read_at)

    def test_mark_all_read_updates_unread_count(self) -> None:
        create_notification(category="memory", title="One", body="First")
        create_notification(category="memory", title="Two", body="Second")

        self.assertEqual(mark_all_notifications_read(), 2)
        self.assertEqual(unread_notification_count(), 0)

    def test_create_notification_broadcasts_to_subscribers(self) -> None:
        subscriber = subscribe_notifications()
        try:
            notification = create_notification(category="reminder", title="Soon", body="Appointment soon.")

            event = subscriber.get_nowait()
        finally:
            unsubscribe_notifications(subscriber)

        self.assertEqual(event["kind"], "notification")
        self.assertEqual(event["notification"]["id"], notification.id)
        self.assertEqual(event["notification"]["category"], "reminder")

    def test_memory_consolidation_notifies_only_for_successful_writes(self) -> None:
        job = ConsolidationJob("chat-1", "job-1", None, {}, 0, 10, 2, 3)

        notify_memory_consolidation_completed(job, {"actions": []}, "No changes needed.")
        self.assertEqual(list_notifications(), [])

        notify_memory_consolidation_completed(
            job,
            {
                "actions": [
                    {
                        "tool": "record_memory",
                        "ok": True,
                        "summary": "Saved relationship memory.",
                        "arguments_summary": {"memory_id": "mem-1", "layer": "relationship"},
                        "error": "",
                    }
                ]
            },
            "I remembered your preference.",
        )

        notifications = list_notifications()
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0].category, "memory")
        self.assertEqual(notifications[0].chat_id, "chat-1")
        self.assertEqual(notifications[0].action_url, "/memory?tab=relationship&memory=mem-1")
        self.assertEqual(notifications[0].metadata["write_count"], 1)


if __name__ == "__main__":
    unittest.main()
