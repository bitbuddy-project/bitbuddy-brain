from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "brain"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-autonomy-depth-test-")

from bitbuddy.providers import StreamChunk  # noqa: E402
from bitbuddy.config import write_config  # noqa: E402
from bitbuddy.paths import GLOBAL_DB_PATH  # noqa: E402
from bitbuddy.autonomy import activities  # noqa: E402
from bitbuddy.autonomy.activities import GOAL_STALL_THRESHOLD, pursue_goal  # noqa: E402
from bitbuddy.autonomy.decision import AutonomyActivityType, AutonomyDecision  # noqa: E402
from bitbuddy.self_model import (  # noqa: E402
    create_goal,
    ensure_self_model_database,
    get_goal,
    goal_task_state,
    set_goal_task_state,
)
from bitbuddy.workspace import ensure_workspace_database  # noqa: E402


class SequencedClient:
    """Returns queued JSON responses, one per collect_model_text call.

    pursue_goal_step makes two calls (plan, then authored note); a `draft` action
    avoids any web search so the sequence is deterministic.
    """

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)

    def stream_chat(self, _messages, model=None, **_kwargs):
        text = self._responses.pop(0) if self._responses else "{}"
        yield StreamChunk("response", text)


def plan_step(step_index: int, total: int, status: str = "in_progress") -> str:
    return json.dumps(
        {
            "action": "draft",
            "rationale": f"step {step_index}",
            "plan": [f"step {i}" for i in range(total)],
            "step_index": step_index,
            "task_status": status,
            "queue_comment": False,
        }
    )


def authored_note(title: str) -> str:
    return json.dumps({"kind": "notes", "title": title, "summary": "one line", "body": f"body for {title}", "tags": []})


DECISION = AutonomyDecision(AutonomyActivityType.PURSUE_GOAL, "advance it", {})


class AutonomyDepthTest(unittest.TestCase):
    def setUp(self) -> None:
        write_config("none", "", "")
        ensure_self_model_database()
        ensure_workspace_database()
        with sqlite3.connect(GLOBAL_DB_PATH) as connection:
            connection.execute("delete from goals")
            connection.execute("delete from workspace_documents")

    def _goal(self) -> object:
        return create_goal(
            "Map the onboarding flow",
            "So I can help with it later.",
            owner="self",
            horizon="day",
            risk_level=1,
            autonomy_allowed=True,
            next_action="outline the steps",
        )

    def test_takes_multiple_steps_per_session_at_high_level(self) -> None:
        write_config("none", "", "")
        from bitbuddy.config import update_autonomy_config

        update_autonomy_config({"activity_level": "high"})  # max_steps_per_session = 4
        goal = self._goal()
        client = SequencedClient(
            [
                plan_step(0, 3), authored_note("note 0"),
                plan_step(1, 3), authored_note("note 1"),
                plan_step(2, 3, status="done"), authored_note("note 2"),
            ]
        )
        result = pursue_goal("cycle-1", client, DECISION)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.metadata["steps_done"], 3)
        self.assertEqual(result.metadata["task_status"], "done")
        self.assertEqual(get_goal(goal.id).status, "completed")

    def test_low_level_takes_one_step(self) -> None:
        from bitbuddy.config import update_autonomy_config

        update_autonomy_config({"activity_level": "low"})  # max_steps_per_session = 1
        goal = self._goal()
        client = SequencedClient([plan_step(0, 3), authored_note("note 0")])
        result = pursue_goal("cycle-1", client, DECISION)
        self.assertEqual(result.metadata["steps_done"], 1)
        self.assertEqual(goal_task_state(get_goal(goal.id))["step_index"], 1)

    def test_anti_stuck_blocks_after_threshold(self) -> None:
        goal = self._goal()
        # Seed an in-progress task already at the brink of the stall threshold.
        set_goal_task_state(
            goal.id,
            status="in_progress",
            plan=["only step"],
            step_index=1,
            last_cycle_id="cycle-0",
            stalled_count=GOAL_STALL_THRESHOLD - 1,
        )
        # A step that pins the same index (no progress) should trip the auto-unstick.
        client = SequencedClient([plan_step(1, 1), authored_note("stuck note")])
        pursue_goal("cycle-1", client, AutonomyDecision(AutonomyActivityType.PURSUE_GOAL, "resume", {"goal_id": str(goal.id)}))
        state = goal_task_state(get_goal(goal.id))
        self.assertEqual(state["status"], "blocked")
        self.assertTrue(state["blocked_reason"])


if __name__ == "__main__":
    unittest.main()
