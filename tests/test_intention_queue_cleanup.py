from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-intention-cleanup-test-")

from bitbuddy.autonomy.intentions import cleanup_intention_queue, create_intention, ensure_intentions_database, list_pending_intentions, mark_intention_shown, next_eligible_intention, record_intention_surface  # noqa: E402
from bitbuddy.paths import GLOBAL_DB_PATH  # noqa: E402


def config(max_questions: int = 12) -> SimpleNamespace:
    return SimpleNamespace(
        autonomy=SimpleNamespace(max_pending_questions=max_questions, max_pending_comments=12, max_new_questions_per_cycle=1, max_autonomous_deliveries_per_day=10),
        dreaming=SimpleNamespace(stale_intention_days=14, low_priority_stale_intention_days=7),
    )


class IntentionQueueCleanupTest(unittest.TestCase):
    def setUp(self) -> None:
        ensure_intentions_database()
        with closing(sqlite3.connect(GLOBAL_DB_PATH)) as connection, connection:
            connection.execute("delete from intentions")

    def test_existing_pending_status_migrates_to_queued(self) -> None:
        with closing(sqlite3.connect(GLOBAL_DB_PATH)) as connection, connection:
            connection.execute(
                "insert into intentions (kind, content, reason, source, status, metadata) values ('question', 'Old item?', '', 'test', 'pending', '{}')"
            )

        ensure_intentions_database()
        pending = list_pending_intentions()

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].status, "queued")

    def test_queue_full_blocks_new_questions(self) -> None:
        with patch("bitbuddy.autonomy.intentions.load_config", return_value=config(max_questions=1)):
            create_intention("question", "First question?")
            with self.assertRaisesRegex(ValueError, "queue is full"):
                create_intention("question", "Second question?")

    def test_cleanup_stales_normalized_duplicate_intentions(self) -> None:
        create_intention("question", "Should I ask about Dreaming Mode?")
        with closing(sqlite3.connect(GLOBAL_DB_PATH)) as connection, connection:
            connection.execute(
                """
                insert into intentions (kind, content, reason, source, status, metadata)
                values ('question', 'Should I ask about dreaming mode', '', 'test', 'queued', '{}')
                """
            )

        with patch("bitbuddy.autonomy.intentions.load_config", return_value=config()):
            result = cleanup_intention_queue(now=datetime.now(timezone.utc))

        self.assertEqual(len(result["duplicates_staled"]), 1)
        self.assertEqual(len(list_pending_intentions()), 1)

    def test_cleanup_expires_low_priority_old_items(self) -> None:
        with closing(sqlite3.connect(GLOBAL_DB_PATH)) as connection, connection:
            connection.execute(
                """
                insert into intentions (kind, content, reason, source, status, metadata, created_at, updated_at)
                values ('comment', 'Old low priority comment.', '', 'test', 'queued', '{"priority": 1}', '2026-01-01 00:00:00', '2026-01-01 00:00:00')
                """
            )

        with patch("bitbuddy.autonomy.intentions.load_config", return_value=config()):
            result = cleanup_intention_queue(now=datetime(2026, 1, 10, tzinfo=timezone.utc))

        self.assertEqual(len(result["stale"]), 1)
        self.assertEqual(list_pending_intentions(), [])

    def test_next_eligible_filters_terminal_statuses(self) -> None:
        shown = create_intention("question", "Should we discuss apples?", metadata={"priority": 5})
        mark_intention_shown(shown.id)
        active = create_intention("question", "Should we discuss apples now?", metadata={"priority": 5})

        selected = next_eligible_intention("chat-filter", latest_user_text="apples")

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.id, active.id)

    def test_next_eligible_project_match_wins(self) -> None:
        high_priority = create_intention("question", "Should we discuss unrelated deployment?", metadata={"priority": 5, "project_id": "other"})
        project_match = create_intention("question", "Should we discuss project testing?", metadata={"priority": 3, "project_id": "bitbuddy"})

        selected = next_eligible_intention("chat-project", latest_user_text="testing", active_project_id="bitbuddy")

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.id, project_match.id)
        self.assertNotEqual(selected.id, high_priority.id)

    def test_next_eligible_priority_beats_age_after_relevance(self) -> None:
        with closing(sqlite3.connect(GLOBAL_DB_PATH)) as connection, connection:
            connection.execute(
                """
                insert into intentions (kind, content, reason, source, status, metadata, created_at, eligible_at, updated_at)
                values ('question', 'Should we talk about apples later?', '', 'test', 'queued', '{"priority": 2}', '2026-01-01 00:00:00', '2026-01-01 00:00:00', '2026-01-01 00:00:00')
                """
            )
            cursor = connection.execute(
                """
                insert into intentions (kind, content, reason, source, status, metadata, created_at, eligible_at, updated_at)
                values ('question', 'Should we revisit apples today?', '', 'test', 'queued', '{"priority": 5}', '2026-01-02 00:00:00', '2026-01-02 00:00:00', '2026-01-02 00:00:00')
                """
            )
            high_id = int(cursor.lastrowid)

        selected = next_eligible_intention("chat-priority", latest_user_text="apples")

        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.id, high_id)

    def test_surface_cooldown_prevents_repeated_selection(self) -> None:
        create_intention("question", "Should we discuss apples?", metadata={"priority": 5})
        record_intention_surface("chat-cooldown", 999, "run-one")

        selected = next_eligible_intention("chat-cooldown", latest_user_text="apples")

        self.assertIsNone(selected)


if __name__ == "__main__":
    unittest.main()
