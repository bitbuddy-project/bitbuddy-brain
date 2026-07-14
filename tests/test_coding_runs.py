from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-coding-runs-test-")

from bitbuddy.coding.runs import (  # noqa: E402
    complete_coding_run,
    coding_run_to_json,
    list_coding_runs,
    record_coding_run_step,
    should_track_coding_request,
    start_coding_run,
    tool_phase,
)


class CodingRunsTest(unittest.TestCase):
    def test_tracks_coding_request_keywords(self) -> None:
        self.assertTrue(should_track_coding_request("fix the settings page build failure"))
        self.assertTrue(should_track_coding_request("make the button green"))
        self.assertFalse(should_track_coding_request("what should I eat for lunch?"))

    def test_tool_phase_mapping(self) -> None:
        self.assertEqual(tool_phase("read_file"), "inspect")
        self.assertEqual(tool_phase("patch_file"), "edit")
        self.assertEqual(tool_phase("run_project_validation"), "verify")
        self.assertEqual(tool_phase("run_shell_command"), "verify")

    def test_persists_run_steps_and_completion(self) -> None:
        run = start_coding_run(
            chat_id="chat-1",
            run_id="runtime-1",
            project_id="demo-123",
            user_request="fix the failing tests",
        )
        self.assertEqual(run.phase, "requested")
        self.assertEqual(len(run.steps), 1)

        run = record_coding_run_step(
            run.id,
            phase="inspect",
            tool="read_file",
            status="completed",
            summary="Read README.md.",
        )
        run = record_coding_run_step(
            run.id,
            phase="edit",
            tool="patch_file",
            status="completed",
            summary="Patched app.py.",
        )
        run = record_coding_run_step(
            run.id,
            phase="verify",
            tool="run_project_validation",
            status="completed",
            summary="Tests passed.",
        )
        run = complete_coding_run(run.id, summary="Fixed the failing tests.")

        self.assertEqual(run.status, "completed")
        self.assertEqual(run.phase, "completed")
        self.assertEqual([step.phase for step in run.steps], ["requested", "inspect", "edit", "verify", "completed"])

        listed = list_coding_runs(project_id="demo-123")
        self.assertEqual(listed[0].id, run.id)
        data = coding_run_to_json(listed[0])
        self.assertEqual(data["summary"], "Fixed the failing tests.")
        self.assertEqual(data["steps"][-1]["phase"], "completed")


if __name__ == "__main__":
    unittest.main()
