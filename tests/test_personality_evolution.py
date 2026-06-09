from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "brain"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-personality-evolution-test-")

from bitbuddy.activity import ensure_activity_database, log_activity  # noqa: E402
from bitbuddy.paths import GLOBAL_DB_PATH  # noqa: E402
from bitbuddy.prompt_builder import build_chat_messages  # noqa: E402
from bitbuddy.self_model import (  # noqa: E402
    ensure_self_model_database,
    get_self_state,
    list_goals,
    personality_evolution_review,
    upsert_personality_evolution,
)


class PersonalityEvolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        ensure_self_model_database()
        ensure_activity_database()
        with sqlite3.connect(GLOBAL_DB_PATH) as connection:
            connection.execute("delete from personality_evolution")
            connection.execute("delete from self_journal")
            connection.execute("delete from goals")
            connection.execute("delete from activity")

    def test_repeated_evidence_matures_trait_and_creates_goal(self) -> None:
        first = upsert_personality_evolution(
            "project_affinity",
            "BitBuddy project work",
            "BitBuddy enjoys improving BitBuddy itself.",
            project_id="bitbuddy",
            evidence="First signal",
        )
        second = upsert_personality_evolution(
            "project_affinity",
            "BitBuddy project work",
            "BitBuddy enjoys improving BitBuddy itself.",
            project_id="bitbuddy",
            evidence="Second signal",
        )
        third = upsert_personality_evolution(
            "project_affinity",
            "BitBuddy project work",
            "BitBuddy enjoys improving BitBuddy itself.",
            project_id="bitbuddy",
            evidence="Third signal",
        )

        self.assertEqual(first.status, "emerging")
        self.assertEqual(second.status, "emerging")
        self.assertEqual(third.status, "stable")
        self.assertEqual(third.evidence_count, 3)
        self.assertTrue(any("BitBuddy project work" in goal.title for goal in list_goals()))

    def test_self_snapshot_and_prompt_include_stable_evolution(self) -> None:
        upsert_personality_evolution(
            "interest",
            "companion interface identity",
            "BitBuddy is developing taste around companion UI and personality feel.",
            evidence="first",
        )
        upsert_personality_evolution(
            "interest",
            "companion interface identity",
            "BitBuddy is developing taste around companion UI and personality feel.",
            evidence="second",
        )
        upsert_personality_evolution(
            "interest",
            "companion interface identity",
            "BitBuddy is developing taste around companion UI and personality feel.",
            evidence="third",
        )

        snapshot = get_self_state()
        messages = build_chat_messages([{"role": "user", "content": "hello"}], "chat")
        system_prompt = messages[0]["content"]

        self.assertEqual(snapshot["evolution"][0]["status"], "stable")
        self.assertIn("Documented personality growth", system_prompt)
        self.assertIn("companion interface identity", system_prompt)

    def test_dream_review_detects_bitbuddy_affinity_signal(self) -> None:
        log_activity(
            "memory_consolidation.completed",
            "Dustin said he loves working on the BitBuddy project, especially UI, font, theme, and personality evolution.",
            {},
        )

        result = personality_evolution_review()

        labels = {item["label"] for item in result["updated"]}
        self.assertIn("BitBuddy project work", labels)


if __name__ == "__main__":
    unittest.main()
