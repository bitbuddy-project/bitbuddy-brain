from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-coding-evals-test-")

from bitbuddy.coding.evals import (  # noqa: E402
    coding_eval_run_to_json,
    coding_eval_task_to_json,
    delete_eval_task,
    list_eval_runs,
    list_eval_tasks,
    score_coding_run_for_task,
    upsert_eval_task,
)
from bitbuddy.coding.runs import complete_coding_run, record_coding_run_step, start_coding_run  # noqa: E402


class CodingEvalsTest(unittest.TestCase):
    def test_saves_task_and_scores_successful_coding_run(self) -> None:
        task = upsert_eval_task(
            name="settings-build-fix",
            prompt="Fix the settings page build failure.",
            project_id="bitbuddy",
            validation_recipe="web-check",
            tags=["ui", "build"],
        )
        run = start_coding_run(
            chat_id="chat-1",
            run_id="runtime-1",
            project_id="bitbuddy",
            user_request=task.prompt,
        )
        record_coding_run_step(run.id, phase="inspect", tool="read_file", summary="Read settings page.")
        record_coding_run_step(run.id, phase="edit", tool="patch_file", summary="Patched settings page.")
        record_coding_run_step(
            run.id,
            phase="verify",
            tool="run_project_validation",
            summary="Validation web-check passed.",
            metadata={"name": "web-check"},
        )
        complete_coding_run(run.id, summary="Fixed the build failure.")

        scored = score_coding_run_for_task(
            task_id=task.id,
            coding_run_id=run.id,
            provider="codex",
            model="gpt-5.5",
        )

        self.assertTrue(scored.passed)
        self.assertEqual(scored.score, 1.0)
        self.assertEqual(scored.metrics["criteria"]["validation_recipe_seen"], True)
        self.assertIn("settings-build-fix", {item.name for item in list_eval_tasks()})
        self.assertEqual(list_eval_runs(task_id=task.name)[0].id, scored.id)
        self.assertEqual(coding_eval_task_to_json(task)["tags"], ["ui", "build"])
        self.assertEqual(coding_eval_run_to_json(scored)["provider"], "codex")

    def test_required_validation_recipe_caps_score_when_missing(self) -> None:
        task = upsert_eval_task(
            name="missing-validation",
            prompt="Make a small code change.",
            project_id="demo",
            validation_recipe="smoke",
        )
        run = start_coding_run(chat_id="chat-2", run_id="runtime-2", project_id="demo", user_request=task.prompt)
        record_coding_run_step(run.id, phase="inspect", tool="read_file", summary="Read file.")
        record_coding_run_step(run.id, phase="edit", tool="patch_file", summary="Patched file.")
        record_coding_run_step(run.id, phase="verify", tool="run_shell_command", summary="Ran tests.")
        complete_coding_run(run.id, summary="Done.")

        scored = score_coding_run_for_task(task_id=task.id, coding_run_id=run.id)

        self.assertFalse(scored.passed)
        self.assertEqual(scored.score, 0.79)
        self.assertFalse(scored.metrics["criteria"]["validation_recipe_seen"])

    def test_delete_eval_task_removes_task_and_scores(self) -> None:
        task = upsert_eval_task(name="delete-me", prompt="Delete this task.")
        run = start_coding_run(chat_id="chat-3", run_id="runtime-3", user_request=task.prompt)
        record_coding_run_step(run.id, phase="edit", tool="patch_file", summary="Patched file.")
        record_coding_run_step(run.id, phase="verify", tool="run_shell_command", summary="Ran tests.")
        complete_coding_run(run.id, summary="Done.")
        score_coding_run_for_task(task_id=task.id, coding_run_id=run.id)

        self.assertTrue(delete_eval_task(task.name))
        self.assertNotIn("delete-me", {item.name for item in list_eval_tasks()})
        self.assertEqual(list_eval_runs(task_id=task.id), [])


if __name__ == "__main__":
    unittest.main()
