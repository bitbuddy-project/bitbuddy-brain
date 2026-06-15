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
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-social-brief-test-")

from bitbuddy.config import write_config  # noqa: E402
from bitbuddy.paths import GLOBAL_DB_PATH  # noqa: E402
from bitbuddy.autonomy.activities import create_autonomy_intentions  # noqa: E402
from bitbuddy.autonomy.intentions import (  # noqa: E402
    create_intention,
    ensure_intentions_database,
    has_intention_with_metadata,
    list_pending_intentions,
    recent_spontaneous_remark,
)
from bitbuddy.autonomy.delivery_scheduler import effective_min_autonomous_priority  # noqa: E402
from bitbuddy.autonomy import morning_brief  # noqa: E402
from bitbuddy.autonomy.levels import profile_for_level  # noqa: E402


def reset_intentions() -> None:
    ensure_intentions_database()
    with closing(sqlite3.connect(GLOBAL_DB_PATH)) as connection, connection:
        connection.execute("delete from intentions")
        connection.execute("delete from intention_surfaces")


class SpontaneousChannelTest(unittest.TestCase):
    def setUp(self) -> None:
        write_config("none", "", "")
        reset_intentions()

    def test_spontaneous_remark_is_rate_limited(self) -> None:
        first = create_autonomy_intentions(
            [{"kind": "comment", "content": "Found a concrete tradeoff worth flagging here.", "reason": "found a real tradeoff in the design", "importance": 4, "playfulness": 0, "excited": True}],
            cycle_id="c1",
            source_activity="web_curiosity",
            spontaneous=True,
        )
        self.assertEqual(len(first), 1)
        self.assertTrue(first[0].metadata.get("excited"))
        self.assertTrue(recent_spontaneous_remark(cooldown_minutes=90))
        # A second spontaneous remark within the cooldown window is held back.
        second = create_autonomy_intentions(
            [{"kind": "comment", "content": "Another discovery worth noting here.", "reason": "discovered", "importance": 4, "playfulness": 0}],
            cycle_id="c2",
            source_activity="web_curiosity",
            spontaneous=True,
        )
        self.assertEqual(second, [])

    def test_deliberate_channel_is_not_gated_by_spontaneous_cooldown(self) -> None:
        create_autonomy_intentions(
            [{"kind": "comment", "content": "Found a neat thing while researching.", "reason": "found", "importance": 4, "playfulness": 0}],
            cycle_id="c1",
            source_activity="web_curiosity",
            spontaneous=True,
        )
        deliberate = create_autonomy_intentions(
            [{"kind": "question", "content": "Should we prioritize the onboarding rewrite?", "reason": "decision", "importance": 5, "playfulness": 0}],
            cycle_id="c2",
            source_activity="generate_user_prompts",
            spontaneous=False,
        )
        self.assertEqual(len(deliberate), 1)


class AntiStarvationTest(unittest.TestCase):
    def test_floor_loosens_when_quiet_and_tightens_when_busy(self) -> None:
        profile = profile_for_level("low")  # min_autonomous_priority = 4, cap = 4
        quiet = effective_min_autonomous_priority(profile, delivered_today=0)
        busy = effective_min_autonomous_priority(profile, delivered_today=profile.max_autonomous_deliveries_per_day)
        self.assertLess(quiet, profile.min_autonomous_priority)
        self.assertGreaterEqual(quiet, 3)  # never below the historical floor
        self.assertGreaterEqual(busy, profile.min_autonomous_priority)


class MorningBriefTest(unittest.TestCase):
    def setUp(self) -> None:
        write_config("none", "", "")
        reset_intentions()

    def _email_cfg(self, enabled: bool = True) -> SimpleNamespace:
        return SimpleNamespace(enabled=enabled, default_mailbox="INBOX")

    def test_silent_when_no_unread(self) -> None:
        seen = [SimpleNamespace(subject="Receipt", from_addr="store@x.com", flags=["\\Seen"])]
        with patch("bitbuddy.autonomy.morning_brief.load_config", return_value=SimpleNamespace(email=self._email_cfg())), \
             patch("bitbuddy.email.service.list_messages", return_value=seen):
            self.assertEqual(morning_brief.build_morning_brief_content(), "")
        self.assertIsNone(morning_brief.queue_morning_brief())

    def test_briefs_when_useful_and_dedupes(self) -> None:
        unread = [
            SimpleNamespace(subject="Invoice due Friday", from_addr="Acme Billing <billing@acme.com>", flags=[]),
            SimpleNamespace(subject="Re: launch plan", from_addr="dana@team.com", flags=["\\Seen"]),
        ]
        with patch("bitbuddy.autonomy.morning_brief.load_config", return_value=SimpleNamespace(email=self._email_cfg())), \
             patch("bitbuddy.email.service.list_messages", return_value=unread):
            content = morning_brief.build_morning_brief_content()
            self.assertIn("1 unread", content)
            self.assertIn("Invoice due Friday", content)
            intention = morning_brief.queue_morning_brief()
            self.assertIsNotNone(intention)
            # de-dupe: a second attempt within the window does nothing
            self.assertIsNone(morning_brief.queue_morning_brief())
        self.assertEqual(len(list_pending_intentions()), 1)

    def test_disabled_email_stays_silent(self) -> None:
        with patch("bitbuddy.autonomy.morning_brief.load_config", return_value=SimpleNamespace(email=self._email_cfg(enabled=False))):
            self.assertEqual(morning_brief.build_morning_brief_content(), "")


class EmailTriageTest(unittest.TestCase):
    def setUp(self) -> None:
        write_config("none", "", "")
        reset_intentions()

    def _email_cfg(self, enabled: bool = True) -> SimpleNamespace:
        return SimpleNamespace(enabled=enabled, default_mailbox="INBOX")

    def _msgs(self):
        return [
            SimpleNamespace(id="m1", mailbox="INBOX", subject="Invoice due Friday", from_addr="Acme Billing <billing@acme.com>", snippet="Your invoice of $420 is due 2026-06-19.", flags=[]),
            SimpleNamespace(id="m2", mailbox="INBOX", subject="Weekend sale!", from_addr="deals@shop.com", snippet="50% off everything", flags=[]),
        ]

    def test_triage_keeps_only_important_decisions(self) -> None:
        from bitbuddy.autonomy import email_triage

        canned = (
            '{"important": ['
            '{"message_id": "m1", "importance": 5, "needs_decision": true, "one_line": "Pay the Acme invoice", "suggested_actions": ["calendar", "reminder"], "due_hint": "Friday"},'
            '{"message_id": "m2", "importance": 2, "needs_decision": false, "one_line": "marketing", "suggested_actions": ["trash"]},'
            '{"message_id": "ghost", "importance": 5, "needs_decision": true, "one_line": "hallucinated", "suggested_actions": ["task"]}'
            ']}'
        )
        with patch("bitbuddy.autonomy.email_triage.load_config", return_value=SimpleNamespace(email=self._email_cfg())), \
             patch("bitbuddy.email.service.list_messages", return_value=self._msgs()), \
             patch("bitbuddy.autonomy.email_triage.collect_model_text", return_value=canned):
            results = email_triage.triage_unread(object())
        self.assertEqual(len(results), 1)
        item = results[0]
        self.assertEqual(item.message_id, "m1")
        self.assertEqual(item.mailbox, "INBOX")
        self.assertEqual(item.subject, "Invoice due Friday")  # taken from our handle, not the model echo
        self.assertEqual(item.suggested_actions, ["calendar", "reminder"])
        self.assertEqual(item.due_hint, "Friday")

    def test_triage_failure_returns_empty(self) -> None:
        from bitbuddy.autonomy import email_triage

        with patch("bitbuddy.autonomy.email_triage.load_config", return_value=SimpleNamespace(email=self._email_cfg())), \
             patch("bitbuddy.email.service.list_messages", return_value=self._msgs()), \
             patch("bitbuddy.autonomy.email_triage.collect_model_text", side_effect=RuntimeError("model down")):
            self.assertEqual(email_triage.triage_unread(object()), [])

    def test_queue_surfaces_question_with_email_handle(self) -> None:
        from bitbuddy.autonomy.email_triage import TriagedEmail

        triaged = [TriagedEmail(message_id="m1", mailbox="INBOX", subject="Invoice due Friday", sender="Acme Billing", importance=5, one_line="Pay the Acme invoice", suggested_actions=["calendar", "reminder", "trash"], due_hint="Friday")]
        with patch("bitbuddy.autonomy.morning_brief.load_config", return_value=SimpleNamespace(email=self._email_cfg(), provider=SimpleNamespace(type="none"))), \
             patch("bitbuddy.autonomy.morning_brief.triage_unread", return_value=triaged):
            intention = morning_brief.queue_morning_brief(client=object())
        self.assertIsNotNone(intention)
        self.assertEqual(intention.kind, "question")
        self.assertEqual(intention.metadata.get("source_activity"), "email_triage")
        self.assertEqual(intention.metadata.get("priority"), morning_brief.TRIAGE_PRIORITY)
        self.assertEqual(intention.metadata.get("email", {}).get("message_id"), "m1")
        self.assertIn("Invoice due Friday", intention.content)
        self.assertIn("filter that sender", intention.content)
        # throttled: a second wake within the window stays silent
        with patch("bitbuddy.autonomy.morning_brief.load_config", return_value=SimpleNamespace(email=self._email_cfg(), provider=SimpleNamespace(type="none"))), \
             patch("bitbuddy.autonomy.morning_brief.triage_unread", return_value=triaged):
            self.assertIsNone(morning_brief.queue_morning_brief(client=object()))

    def test_queue_falls_back_to_count_when_triage_empty(self) -> None:
        with patch("bitbuddy.autonomy.morning_brief.load_config", return_value=SimpleNamespace(email=self._email_cfg(), provider=SimpleNamespace(type="none"))), \
             patch("bitbuddy.autonomy.morning_brief.triage_unread", return_value=[]), \
             patch("bitbuddy.email.service.list_messages", return_value=self._msgs()):
            intention = morning_brief.queue_morning_brief(client=object())
        self.assertIsNotNone(intention)
        self.assertEqual(intention.kind, "comment")
        self.assertEqual(intention.metadata.get("source_activity"), "morning_brief")


class ShowAndTellGateTest(unittest.TestCase):
    def setUp(self) -> None:
        write_config("none", "", "")
        reset_intentions()

    def test_metadata_lookup_finds_prior_share(self) -> None:
        create_intention(
            "comment",
            "Look what I made.",
            "Sharing workspace doc d-1",
            metadata={"source_activity": "show_and_tell", "show_and_tell_doc_id": "d-1"},
        )
        self.assertTrue(has_intention_with_metadata(source_activity="show_and_tell", within_hours=24))
        self.assertTrue(has_intention_with_metadata(metadata_key="show_and_tell_doc_id", metadata_value="d-1"))
        self.assertFalse(has_intention_with_metadata(metadata_key="show_and_tell_doc_id", metadata_value="d-2"))


if __name__ == "__main__":
    unittest.main()
