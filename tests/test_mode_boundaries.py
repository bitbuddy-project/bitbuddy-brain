from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "brain"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-mode-test-")

from bitbuddy.prompt_builder import build_chat_messages  # noqa: E402
from bitbuddy.tools import ToolCall, ToolExecutor, default_tool_registry, tool_instruction_message  # noqa: E402


class ModeBoundaryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.executor = ToolExecutor(default_tool_registry())

    def test_plan_blocks_memory_write_tools(self) -> None:
        executor = ToolExecutor(default_tool_registry(), mode="plan")
        call = ToolCall(
            tool="record_memory",
            arguments={"layer": "semantic", "title": "Fact", "summary": "A fact."},
        )

        error = executor.check_mode_restrictions(call)

        self.assertIn("Plan mode is strictly read-only", error)

    def test_plan_blocks_shell_writes_tests_and_builds(self) -> None:
        executor = ToolExecutor(default_tool_registry(), mode="plan")

        blocked_commands = [
            "touch created.txt",
            "rm stale.txt",
            "python -m pytest",
            "npm run build",
        ]

        for command in blocked_commands:
            with self.subTest(command=command):
                error = executor.check_mode_restrictions(
                    ToolCall(tool="run_shell_command", arguments={"command": command})
                )
                self.assertIn("Plan mode is strictly read-only", error)

    def test_plan_allows_read_only_shell_inspection(self) -> None:
        executor = ToolExecutor(default_tool_registry(), mode="plan")

        allowed_commands = ["pwd", "ls -la", "rg mode brain/bitbuddy", "git status", "git diff"]

        for command in allowed_commands:
            with self.subTest(command=command):
                error = executor.check_mode_restrictions(
                    ToolCall(tool="run_shell_command", arguments={"command": command})
                )
                self.assertEqual(error, "")

    def test_debug_blocks_unrelated_mutations(self) -> None:
        executor = ToolExecutor(default_tool_registry(), mode="debug", mode_context="Add a new feature.")

        error = executor.check_mode_restrictions(
            ToolCall(tool="run_shell_command", arguments={"command": "touch new_feature.txt"})
        )

        self.assertIn("Debug mode only allows", error)

    def test_debug_allows_debug_related_mutations(self) -> None:
        executor = ToolExecutor(default_tool_registry(), mode="debug", mode_context="Fix the failing parser test.")

        error = executor.check_mode_restrictions(
            ToolCall(tool="run_shell_command", arguments={"command": "rm failing-test-output.log"})
        )

        self.assertEqual(error, "")

    def test_chat_has_no_mode_boundary_restriction(self) -> None:
        executor = ToolExecutor(default_tool_registry(), mode="chat")

        error = executor.check_mode_restrictions(
            ToolCall(tool="run_shell_command", arguments={"command": "touch anything.txt"})
        )

        self.assertEqual(error, "")

    def test_prompts_explain_current_mode_boundaries(self) -> None:
        plan_messages = build_chat_messages([{"role": "user", "content": "make a plan"}], "plan")
        debug_messages = build_chat_messages([{"role": "user", "content": "debug this failure"}], "debug")
        tool_message = tool_instruction_message(default_tool_registry())

        self.assertIn("[Current Mode: Plan]", plan_messages[0]["content"])
        self.assertIn("strictly read-only", plan_messages[0]["content"])
        self.assertIn("[Current Mode: Debug]", debug_messages[0]["content"])
        self.assertIn("directly related", debug_messages[0]["content"])
        self.assertIn("Mode boundaries:", tool_message["content"])


if __name__ == "__main__":
    unittest.main()
