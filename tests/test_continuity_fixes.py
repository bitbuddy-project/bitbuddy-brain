from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "brain"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-continuity-test-")

from bitbuddy.chats.runtime import (  # noqa: E402
    WORKING_PLAN_MARKER,
    compact_plan_from_thinking,
    response_claims_file_created,
    working_plan_note,
)
from bitbuddy.paths import GLOBAL_DB_PATH  # noqa: E402
from bitbuddy.self_model import (  # noqa: E402
    create_goal,
    ensure_self_model_database,
    get_goal,
    goal_task_state,
    set_goal_task_state,
)


class WorkingPlanNoteTest(unittest.TestCase):
    def test_compact_plan_keeps_tail_within_budget(self) -> None:
        thinking = "\n".join(f"line {i}" for i in range(200))
        plan = compact_plan_from_thinking(thinking)
        self.assertTrue(plan)
        self.assertLessEqual(len(plan), 700)
        # The plan/decision usually lands at the end, so the tail is kept.
        self.assertIn("line 199", plan)

    def test_empty_thinking_yields_no_note(self) -> None:
        self.assertEqual(compact_plan_from_thinking("   \n  \n"), "")
        self.assertIsNone(working_plan_note("   "))

    def test_working_plan_note_is_marked_user_context(self) -> None:
        note = working_plan_note("Step 1: read the file. Step 2: patch it. Decision: patch now.")
        self.assertIsNotNone(note)
        assert note is not None
        self.assertEqual(note["role"], "user")
        self.assertTrue(note.get(WORKING_PLAN_MARKER))
        self.assertIn("Working Plan", note["content"])
        self.assertIn("patch", note["content"])


class FileEditClaimDetectionTest(unittest.TestCase):
    def test_detects_svelte_edit_narration(self) -> None:
        # The transcript's failure: claims edits to a .svelte file without a tool call.
        text = "I've updated src/routes/configuration/+page.svelte to include the wrapper."
        self.assertTrue(response_claims_file_created(text))

    def test_detects_markdown_edit_narration(self) -> None:
        self.assertTrue(response_claims_file_created("I edited README.md with the new section."))

    def test_plain_answer_is_not_a_file_claim(self) -> None:
        self.assertFalse(response_claims_file_created("Here is an explanation of how locking works."))


class GoalTaskStateTest(unittest.TestCase):
    def setUp(self) -> None:
        ensure_self_model_database()
        with sqlite3.connect(GLOBAL_DB_PATH) as connection:
            connection.execute("delete from goals")

    def test_task_state_round_trip_and_advance(self) -> None:
        goal = create_goal(
            "Ship the docs update",
            "Users keep hitting the daemonize footgun.",
            owner="self",
            horizon="day",
            risk_level=1,
            autonomy_allowed=True,
            next_action="draft the warning section",
        )
        self.assertEqual(goal_task_state(goal), {})

        set_goal_task_state(
            goal.id,
            status="in_progress",
            plan=["draft warning", "add wrapper example", "update site"],
            step_index=0,
            last_cycle_id="cycle-1",
        )
        state = goal_task_state(get_goal(goal.id))
        self.assertEqual(state["status"], "in_progress")
        self.assertEqual(state["plan"], ["draft warning", "add wrapper example", "update site"])
        self.assertEqual(state["step_index"], 0)
        self.assertEqual(state["last_cycle_id"], "cycle-1")

        # A later cycle advances the same plan rather than restarting it.
        set_goal_task_state(
            goal.id,
            status="in_progress",
            plan=state["plan"],
            step_index=1,
            last_cycle_id="cycle-2",
        )
        advanced = goal_task_state(get_goal(goal.id))
        self.assertEqual(advanced["step_index"], 1)
        self.assertEqual(advanced["plan"], state["plan"])

    def test_blocked_state_keeps_reason(self) -> None:
        goal = create_goal(
            "Investigate flaky deploy",
            "It fails intermittently.",
            owner="self",
            horizon="week",
            risk_level=1,
            autonomy_allowed=True,
            next_action="reproduce locally",
        )
        set_goal_task_state(goal.id, status="blocked", plan=["reproduce"], step_index=0, blocked_reason="needs prod creds")
        state = goal_task_state(get_goal(goal.id))
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["blocked_reason"], "needs prod creds")


if __name__ == "__main__":
    unittest.main()
