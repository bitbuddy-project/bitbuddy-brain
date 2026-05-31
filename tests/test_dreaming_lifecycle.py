from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "brain"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-dream-lifecycle-test-")

from bitbuddy.activity import ensure_activity_database  # noqa: E402
from bitbuddy.autonomy.intentions import create_intention, ensure_intentions_database, list_pending_intentions  # noqa: E402
from bitbuddy.chats.repository import ensure_chat_database  # noqa: E402
from bitbuddy.dreaming.runtime import ensure_dream_database, list_dream_runs, run_minidream  # noqa: E402
from bitbuddy.lifecycle import ensure_lifecycle_database, evaluate_lifecycle, get_lifecycle_state, record_user_activity, transition_lifecycle  # noqa: E402
from bitbuddy.paths import GLOBAL_DB_PATH  # noqa: E402


class FakeTimer:
    def __init__(self, delay, target, args=()) -> None:
        self.delay = delay
        self.target = target
        self.args = args
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True


def dreaming_test_config() -> SimpleNamespace:
    return SimpleNamespace(
        user_context=SimpleNamespace(timezone="UTC"),
        dreaming=SimpleNamespace(
            enabled=True,
            bedtime="23:00",
            wake_time="08:00",
            goodnight_triggers=("goodnight", "good night"),
            goodmorning_triggers=("good morning",),
            idle_before_dream_minutes=30,
            minimum_dream_window_minutes=45,
            max_dream_tasks_per_night=3,
            allow_post_dream_autonomy_rounds=0,
            soft_delete_memories=True,
            quiet_mode_after_bedtime=True,
            goodnight_immediate_winddown=False,
            stale_intention_days=14,
            low_priority_stale_intention_days=7,
            self_note_injection_enabled=False,
        ),
        autonomy=SimpleNamespace(max_pending_questions=12, max_pending_comments=12, max_new_questions_per_cycle=1, max_autonomous_deliveries_per_day=10),
    )


class DreamingLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        ensure_activity_database()
        ensure_chat_database()
        ensure_intentions_database()
        ensure_lifecycle_database()
        ensure_dream_database()
        with sqlite3.connect(GLOBAL_DB_PATH) as connection:
            connection.execute("delete from activity")
            connection.execute("delete from intentions")
            connection.execute("delete from chat_messages")
            connection.execute("delete from chats")
            connection.execute("delete from dream_tasks")
            connection.execute("delete from dream_runs")
            connection.execute("delete from lifecycle_state")
        ensure_lifecycle_database()

    def test_bedtime_moves_to_nighteligible_not_dreaming(self) -> None:
        now = datetime(2026, 5, 15, 23, 0, tzinfo=ZoneInfo("UTC"))
        with patch("bitbuddy.lifecycle.load_config", return_value=dreaming_test_config()), patch("bitbuddy.lifecycle.threading.Timer", FakeTimer):
            state = evaluate_lifecycle(now=now)

        self.assertEqual(state.state, "NightEligible")
        self.assertEqual(state.previous_state, "Awake")
        self.assertEqual(state.transition_reason, "bedtime window opened")
        self.assertEqual(state.night_reason, "bedtime")
        self.assertTrue(state.quiet_mode)
        self.assertIn("23:30:00", state.dream_allowed_after)

    def test_chat_after_bedtime_postpones_dreaming(self) -> None:
        bedtime = datetime(2026, 5, 15, 23, 0, tzinfo=ZoneInfo("UTC"))
        active = datetime(2026, 5, 15, 23, 10, tzinfo=ZoneInfo("UTC"))
        with patch("bitbuddy.lifecycle.load_config", return_value=dreaming_test_config()), patch("bitbuddy.lifecycle.threading.Timer", FakeTimer):
            evaluate_lifecycle(now=bedtime)
            state = record_user_activity(chat_id="chat-night", text="still here", now=active)

        self.assertEqual(state.state, "NightEligible")
        self.assertIn("23:10:00", state.last_user_activity_at)
        self.assertIn("23:40:00", state.dream_allowed_after)

    def test_minidream_cleans_queue_and_enters_sleep(self) -> None:
        now = datetime(2026, 5, 15, 23, 31, tzinfo=ZoneInfo("UTC"))
        create_intention("question", "Should I ask about BitBuddy dreaming?", metadata={"priority": 3})
        with sqlite3.connect(GLOBAL_DB_PATH) as connection:
            connection.execute(
                """
                insert into intentions (kind, content, reason, source, status, metadata, created_at, updated_at)
                values ('question', 'Should I ask about bitbuddy dreaming', '', 'test', 'queued', '{}', current_timestamp, current_timestamp)
                """
            )

        with patch("bitbuddy.lifecycle.load_config", return_value=dreaming_test_config()), patch("bitbuddy.autonomy.intentions.load_config", return_value=dreaming_test_config()):
            transition_lifecycle("NightEligible", reason="test", night_reason="bedtime", quiet_mode=True, dream_allowed_after=now.isoformat(), now=now)
            dream_id = run_minidream(reason="bedtime", now=now)

        self.assertIsNotNone(dream_id)
        self.assertEqual(get_lifecycle_state().state, "Sleep")
        self.assertEqual(len(list_pending_intentions()), 1)
        self.assertEqual(list_dream_runs(limit=1)[0]["status"], "completed")

    def test_sleep_chat_before_wake_returns_to_nighteligible_quiet(self) -> None:
        now = datetime(2026, 5, 16, 1, 0, tzinfo=ZoneInfo("UTC"))
        with patch("bitbuddy.lifecycle.load_config", return_value=dreaming_test_config()), patch("bitbuddy.lifecycle.threading.Timer", FakeTimer):
            transition_lifecycle("Sleep", reason="test sleep", now=now)
            state = record_user_activity(chat_id="sleep-chat", text="hey", now=now)

        self.assertEqual(state.state, "NightEligible")
        self.assertTrue(state.quiet_mode)
        self.assertEqual(state.night_reason, "bedtime")

    def test_sleep_chat_after_wake_time_returns_to_awake(self) -> None:
        now = datetime(2026, 5, 16, 9, 0, tzinfo=ZoneInfo("UTC"))
        with patch("bitbuddy.lifecycle.load_config", return_value=dreaming_test_config()), patch("bitbuddy.lifecycle.threading.Timer", FakeTimer):
            transition_lifecycle("Sleep", reason="test sleep", now=now)
            state = record_user_activity(chat_id="morning-chat", text="hey", now=now)

        self.assertEqual(state.state, "Awake")
        self.assertFalse(state.quiet_mode)


if __name__ == "__main__":
    unittest.main()
