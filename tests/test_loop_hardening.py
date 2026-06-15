from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-loop-hardening-test-")

from bitbuddy.chats.runtime import post_result_response_is_nonsense, recovery_message_from_tool_result  # noqa: E402
from bitbuddy.loop_learning import loop_lessons_prompt, record_loop_incident, select_loop_lessons  # noqa: E402
from bitbuddy.subagents.runtime import is_desktop_control_tool, selected_tool_names  # noqa: E402
from bitbuddy.toolbox.base import ToolDefinition, ToolRegistry, ToolResult  # noqa: E402


class LoopHardeningTest(unittest.TestCase):
    def test_records_loop_incident_and_injects_capped_lesson(self) -> None:
        record_loop_incident(
            provider="ollama",
            model="hermes",
            mode="chat",
            reason="duplicate_tool_call",
            tools=["read_file"],
            recovery="synthesize_from_last_successful_tool",
            chat_id="chat-1",
            run_id="run-1",
        )

        lessons = select_loop_lessons("ollama", "hermes")
        self.assertEqual(len(lessons), 1)
        self.assertIn("already called", lessons[0].lesson)

        prompt = loop_lessons_prompt("ollama", "hermes")
        self.assertIn("[BitBuddy Loop Lessons]", prompt)
        self.assertIn("duplicate_tool_call/read_file", prompt)

    def test_post_result_nonsense_detection_is_conservative(self) -> None:
        result = ToolResult("read_file", True, "file contents", "Read README.md", {"file_path": "README.md"})

        self.assertTrue(post_result_response_is_nonsense("", result))
        self.assertTrue(post_result_response_is_nonsense("done", result))
        self.assertTrue(post_result_response_is_nonsense("<tool_call>{}</tool_call>", result))
        self.assertFalse(post_result_response_is_nonsense("The file explains how to run setup.", result))
        self.assertFalse(post_result_response_is_nonsense("done", None))

    def test_recovery_message_uses_friendly_copy(self) -> None:
        result = ToolResult("read_file", True, "Useful result", "Read README.md", {"file_path": "README.md"})

        message = recovery_message_from_tool_result(result)

        self.assertIn("The model got stuck trying to use tools", message)
        self.assertIn("Useful result", message)
        self.assertNotIn("couldn’t parse", message.lower())

    def test_subagents_filter_unsafe_requested_tools(self) -> None:
        registry = ToolRegistry()
        for name, annotations in (
            ("read_file", {}),
            ("write_file", {}),
            ("patch_file", {}),
            ("run_shell_command", {}),
            ("email_trash_message", {}),
            ("email_create_auto_trash_rule", {}),
            ("calendar_create_event", {}),
            ("calendar_modify_event", {}),
            ("calendar_delete_event", {}),
            ("mcp_read_status", {"mcp": True, "readOnlyHint": True}),
            ("mcp_mutate_status", {"mcp": True, "readOnlyHint": False}),
            ("mcp_computer_use_linux_click", {"mcp": True, "mcp_server": "computer_use_linux", "mcp_tool": "click"}),
        ):
            registry.register(
                ToolDefinition(
                    name=name,
                    description=name,
                    arguments_schema={"type": "object"},
                    max_chars=1000,
                    annotations=annotations,
                ),
                lambda _args, definition: ToolResult(definition.name, True, "", "ok"),
            )

        self.assertTrue(is_desktop_control_tool(registry.definition("mcp_computer_use_linux_click"), "mcp_computer_use_linux_click"))

        selected = selected_tool_names(
            registry,
            [
                "read_file",
                "write_file",
                "patch_file",
                "run_shell_command",
                "email_trash_message",
                "email_create_auto_trash_rule",
                "calendar_create_event",
                "calendar_modify_event",
                "calendar_delete_event",
                "mcp_read_status",
                "mcp_mutate_status",
                "mcp_computer_use_linux_click",
            ],
        )

        self.assertEqual(selected, {"read_file", "mcp_read_status"})

    def test_default_subagent_tools_include_email_read_only_but_not_mutations(self) -> None:
        registry = ToolRegistry()
        for name in (
            "email_list_mailboxes",
            "email_recent_messages",
            "email_search_messages",
            "email_read_message",
            "email_trash_message",
            "email_create_auto_trash_rule",
            "mcp_computer_use_linux_click",
        ):
            annotations = {"mcp": True, "mcp_server": "computer_use_linux", "mcp_tool": "click"} if name.startswith("mcp_") else {}
            registry.register(
                ToolDefinition(
                    name=name,
                    description=name,
                    arguments_schema={"type": "object"},
                    max_chars=1000,
                    annotations=annotations,
                ),
                lambda _args, definition: ToolResult(definition.name, True, "", "ok"),
            )

        selected = selected_tool_names(registry, None)

        self.assertIn("email_list_mailboxes", selected)
        self.assertIn("email_recent_messages", selected)
        self.assertIn("email_search_messages", selected)
        self.assertIn("email_read_message", selected)
        self.assertNotIn("email_trash_message", selected)
        self.assertNotIn("email_create_auto_trash_rule", selected)
        self.assertNotIn("mcp_computer_use_linux_click", selected)


if __name__ == "__main__":
    unittest.main()
