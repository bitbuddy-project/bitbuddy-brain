from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "brain"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-artifacts-test-")

from bitbuddy.paths import ARTIFACTS_DIR  # noqa: E402
from bitbuddy.chats.runtime import should_repair_unbacked_artifact_response  # noqa: E402
from bitbuddy.tools import ToolCall, ToolExecutor, ToolResult, default_tool_registry, needs_permission  # noqa: E402


class ArtifactToolTest(unittest.TestCase):
    def setUp(self) -> None:
        self.executor = ToolExecutor(default_tool_registry())

    def test_write_file_defaults_to_artifacts_without_permission(self) -> None:
        call = ToolCall("write_file", {"file_path": "kicad/demo.py", "content": "print('ok')\n"})

        self.assertEqual(needs_permission(call), (False, ""))
        result = self.executor.execute(call)

        self.assertTrue(result.ok, result.error)
        path = ARTIFACTS_DIR / "kicad" / "demo.py"
        self.assertEqual(path.read_text(encoding="utf-8"), "print('ok')\n")
        self.assertIn(str(path), result.summary)
        diff = (result.metadata or {}).get("diff")
        self.assertIsInstance(diff, dict)
        files = diff.get("files")  # type: ignore[union-attr]
        self.assertEqual(files[0]["status"], "created")
        self.assertEqual(files[0]["added"], 1)
        self.assertEqual(files[0]["removed"], 0)
        self.assertIn("+print('ok')", files[0]["unified"])

    def test_patch_file_updates_artifact(self) -> None:
        self.executor.execute(ToolCall("write_file", {"file_path": "notes.txt", "content": "alpha\nbeta\n"}))

        result = self.executor.execute(
            ToolCall("patch_file", {"file_path": "notes.txt", "old_text": "beta", "new_text": "gamma"})
        )

        self.assertTrue(result.ok, result.error)
        self.assertEqual((ARTIFACTS_DIR / "notes.txt").read_text(encoding="utf-8"), "alpha\ngamma\n")
        diff = (result.metadata or {}).get("diff")
        self.assertIsInstance(diff, dict)
        files = diff.get("files")  # type: ignore[union-attr]
        self.assertEqual(files[0]["status"], "modified")
        self.assertEqual(files[0]["added"], 1)
        self.assertEqual(files[0]["removed"], 1)
        self.assertIn("-beta", files[0]["unified"])
        self.assertIn("+gamma", files[0]["unified"])

    def test_make_directory_defaults_to_artifacts(self) -> None:
        result = self.executor.execute(ToolCall("make_directory", {"path": "exports/svg"}))

        self.assertTrue(result.ok, result.error)
        self.assertTrue((ARTIFACTS_DIR / "exports" / "svg").is_dir())

    def test_non_artifact_file_writes_require_permission(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bitbuddy-project-write-") as directory:
            call = ToolCall("write_file", {"root_path": directory, "file_path": "created.txt", "content": "x"})

            required, reason = needs_permission(call)

        self.assertTrue(required)
        self.assertIn("outside BitBuddy's managed artifacts workspace", reason)

    def test_home_file_write_requires_permission_but_resolves_home_path(self) -> None:
        home_file = Path.home() / "smiley.svg"
        call = ToolCall("write_file", {"file_path": "~/smiley.svg", "content": "<svg></svg>\n"})

        required, reason = needs_permission(call)
        result = self.executor.execute(call)

        self.assertTrue(required)
        self.assertIn("outside BitBuddy's managed artifacts workspace", reason)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(home_file.read_text(encoding="utf-8"), "<svg></svg>\n")

    def test_home_file_patch_resolves_home_path(self) -> None:
        home_file = Path.home() / "smiley.svg"
        home_file.write_text("<svg>flat</svg>\n", encoding="utf-8")

        result = self.executor.execute(
            ToolCall("patch_file", {"file_path": "~/smiley.svg", "old_text": "flat", "new_text": "3d"})
        )

        self.assertTrue(result.ok, result.error)
        self.assertEqual(home_file.read_text(encoding="utf-8"), "<svg>3d</svg>\n")

    def test_plan_mode_blocks_file_writes(self) -> None:
        executor = ToolExecutor(default_tool_registry(), mode="plan")

        error = executor.check_mode_restrictions(ToolCall("write_file", {"file_path": "x.txt", "content": "x"}))

        self.assertIn("Plan mode is strictly read-only", error)

    def test_shell_command_supports_working_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bitbuddy-shell-cwd-") as directory:
            result = self.executor.execute(
                ToolCall("run_shell_command", {"command": "pwd", "working_directory": directory, "timeout_seconds": 5})
            )

            self.assertTrue(result.ok, result.error)
            self.assertEqual(result.content.strip(), str(Path(directory).resolve()))
            self.assertEqual(result.arguments_summary["working_directory"], str(Path(directory).resolve()))

    def test_hermes_style_script_generation_flow(self) -> None:
        self.executor.execute(
            ToolCall(
                "write_file",
                {
                    "file_path": "svg-flow/generate_smiley.py",
                    "content": "from pathlib import Path\nPath('smiley.svg').write_text('<svg></svg>\\n', encoding='utf-8')\n",
                },
            )
        )
        result = self.executor.execute(
            ToolCall(
                "run_shell_command",
                {
                    "command": f"{sys.executable} generate_smiley.py",
                    "working_directory": str(ARTIFACTS_DIR / "svg-flow"),
                    "timeout_seconds": 5,
                },
            )
        )

        self.assertTrue(result.ok, result.error)
        self.assertEqual((ARTIFACTS_DIR / "svg-flow" / "smiley.svg").read_text(encoding="utf-8"), "<svg></svg>\n")

    def test_unbacked_artifact_claim_requires_repair(self) -> None:
        self.assertTrue(
            should_repair_unbacked_artifact_response(
                "create a smiley.svg file",
                "Saved to: ~/smiley.svg",
                [],
            )
        )

    def test_read_then_fake_update_claim_requires_repair(self) -> None:
        read_result = ToolResult(
            tool="read_file",
            ok=True,
            content="# /home/dustin/smiley.svg\n\n<svg></svg>",
            summary="Read /home/dustin/smiley.svg (465 bytes).",
            arguments_summary={"file_path": "~/smiley.svg"},
        )

        self.assertTrue(
            should_repair_unbacked_artifact_response(
                "update it make it more like uhm like 3d like",
                "I've updated the SVG. It's saved to ~/smiley.svg.",
                [read_result],
            )
        )

    def test_prose_draft_that_mentions_file_updates_does_not_require_repair(self) -> None:
        self.assertFalse(
            should_repair_unbacked_artifact_response(
                "can you PLEASE draft that",
                "Proposed README.md Updates\n\nI can apply these documentation updates if you want.",
                [],
            )
        )

    def test_backed_artifact_claim_does_not_require_repair(self) -> None:
        result = self.executor.execute(ToolCall("write_file", {"file_path": "smiley.svg", "content": "<svg></svg>\n"}))

        self.assertFalse(
            should_repair_unbacked_artifact_response(
                "create a smiley.svg file",
                "Saved to ~/.bitbuddy/artifacts/smiley.svg",
                [result],
            )
        )


if __name__ == "__main__":
    unittest.main()
