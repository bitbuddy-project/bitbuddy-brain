from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "brain"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-commitments-test-")

from bitbuddy.config import write_config  # noqa: E402
from bitbuddy.paths import GLOBAL_DB_PATH  # noqa: E402
from bitbuddy.autonomy import commitments  # noqa: E402
from bitbuddy.autonomy.commitments import Commitment  # noqa: E402
from bitbuddy.autonomy.intentions import (  # noqa: E402
    create_intention,
    ensure_intentions_database,
    next_eligible_intention,
)


NOW = datetime(2026, 6, 14, 9, 0, tzinfo=timezone.utc)


def reset_intentions() -> None:
    ensure_intentions_database()
    with sqlite3.connect(GLOBAL_DB_PATH) as connection:
        connection.execute("delete from intentions")
        connection.execute("delete from intention_surfaces")


def window_with(text: str) -> dict:
    return {"messages": [{"role": "user", "content": text}, {"role": "assistant", "content": "ok"}]}


def stub_client(payload: str):
    return patch("bitbuddy.autonomy.commitments.collect_model_text", return_value=payload)


class ExtractCommitmentsTest(unittest.TestCase):
    def setUp(self) -> None:
        write_config("none", "", "")

    def test_keeps_future_confident_commitment_and_drops_the_rest(self) -> None:
        payload = (
            '{"commitments": ['
            '{"summary": "send the deck to Sarah", "due_iso": "2026-06-19T17:00:00+00:00", "confidence": 0.9, "quote": "I\'ll send the deck Friday"},'
            '{"summary": "past thing", "due_iso": "2026-06-10T09:00:00+00:00", "confidence": 0.95},'
            '{"summary": "vague maybe", "due_iso": "2026-06-20T09:00:00+00:00", "confidence": 0.2},'
            '{"summary": "", "due_iso": "2026-06-20T09:00:00+00:00", "confidence": 0.9}'
            ']}'
        )
        with stub_client(payload):
            results = commitments.extract_commitments(object(), window_with("I'll send the deck to Sarah by Friday"), now=NOW)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].summary, "send the deck to Sarah")
        self.assertGreaterEqual(results[0].confidence, 0.6)

    def test_no_user_text_returns_empty(self) -> None:
        with stub_client('{"commitments": []}') as mocked:
            self.assertEqual(commitments.extract_commitments(object(), {"messages": [{"role": "assistant", "content": "hi"}]}, now=NOW), [])
        mocked.assert_not_called()

    def test_model_failure_is_swallowed(self) -> None:
        with patch("bitbuddy.autonomy.commitments.collect_model_text", side_effect=RuntimeError("down")):
            self.assertEqual(commitments.extract_commitments(object(), window_with("I'll do X by Friday"), now=NOW), [])


class QueueCommitmentFollowupsTest(unittest.TestCase):
    def setUp(self) -> None:
        write_config("none", "", "")
        reset_intentions()

    def _commitment(self) -> Commitment:
        due = (NOW + timedelta(days=2)).isoformat()
        return Commitment(summary="send the deck to Sarah", due_iso=due, confidence=0.9, quote="Friday")

    def test_queues_followup_with_future_eligible_at(self) -> None:
        queued = commitments.queue_commitment_followups([self._commitment()], chat_id="c1", now=NOW)
        self.assertEqual(len(queued), 1)
        intention = queued[0]
        self.assertEqual(intention.kind, "follow_up")
        self.assertEqual(intention.metadata.get("source_activity"), "commitment_tracker")
        self.assertTrue(intention.metadata.get("commitment_key"))
        self.assertIn("send the deck to Sarah", intention.content)
        eligible = datetime.fromisoformat(intention.eligible_at)
        self.assertGreater(eligible, NOW)  # scheduled for before the deadline, still in the future

    def test_second_run_dedupes(self) -> None:
        commitments.queue_commitment_followups([self._commitment()], chat_id="c1", now=NOW)
        again = commitments.queue_commitment_followups([self._commitment()], chat_id="c1", now=NOW + timedelta(hours=1))
        self.assertEqual(again, [])


class EligibleAtGateTest(unittest.TestCase):
    """The linchpin fix: a future eligible_at must hide an intention from in-chat surfacing."""

    def setUp(self) -> None:
        write_config("none", "", "")
        reset_intentions()

    def test_future_followup_is_hidden_then_surfaces_when_due(self) -> None:
        future = create_intention(
            "follow_up",
            "Earlier you said you'd send the deck to Sarah. Still on track?",
            "commitment",
            metadata={"source_activity": "commitment_tracker", "priority": 4, "quality": {"accepted": True, "importance": 4}},
            eligible_at=(NOW + timedelta(days=1)).isoformat(),
        )
        hidden = next_eligible_intention("c1", latest_user_text="how are things", now=NOW)
        self.assertIsNone(hidden)
        # Once its time has arrived, the same intention becomes surfaceable.
        surfaced = next_eligible_intention("c1", latest_user_text="how are things", now=NOW + timedelta(days=2))
        self.assertIsNotNone(surfaced)
        self.assertEqual(surfaced.id, future.id)


if __name__ == "__main__":
    unittest.main()
