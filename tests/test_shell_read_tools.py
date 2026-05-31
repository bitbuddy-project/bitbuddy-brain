from __future__ import annotations

import os
import json
import sys
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "brain"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-shell-read-test-")

from bitbuddy.chats.runtime import tool_call_announcement, tool_call_thinking  # noqa: E402
from bitbuddy.projects.routing import requested_project_file_path, resolve_project_file_request, shell_read_tool_calls, tool_result_answer  # noqa: E402
from bitbuddy.tools import ToolCall, ToolExecutor, ToolParseError, contains_tool_call, default_tool_registry, parse_tool_call, parse_tool_call_lines, parse_tool_calls, tool_instruction_message  # noqa: E402


@dataclass(frozen=True)
class FakeProject:
    id: str
    name: str
    paths: tuple[Path, ...]


@dataclass(frozen=True)
class FakeToolResult:
    ok: bool
    content: str = ""
    error: str = ""
    tool: str = ""


class ShellReadToolConversionTest(unittest.TestCase):
    def test_tool_prompt_lists_tools_without_project_routing_policy(self) -> None:
        content = tool_instruction_message(default_tool_registry())["content"]

        self.assertIn("You may use tools", content)
        self.assertIn("[Available Tools]", content)
        self.assertIn("- get_project_brief:", content)
        self.assertIn("- glob_files:", content)
        self.assertIn("- search_text:", content)
        self.assertIn("- run_subagent:", content)
        self.assertIn("- read_file:", content)
        self.assertIn("tool_call:", content)
        self.assertNotIn("For a named project", content)
        self.assertNotIn("Do not answer with shell commands", content)

    def test_tool_call_parser_valid_format(self) -> None:
        call = parse_tool_call(
            'tool_call: {"name":"list_projects","arguments":{}}'
        )

        self.assertEqual(call.tool, "list_projects")
        self.assertEqual(call.arguments, {})

    def test_tool_call_parser_accepts_multiple_tool_call_lines(self) -> None:
        calls = parse_tool_calls(
            'tool_call: {"name":"read_file","arguments":{"file_path":"README.md"}}\n'
            'tool_call: {"name":"get_project_brief","arguments":{"project_id":"stasis-c3804eb0"}}'
        )

        self.assertEqual([call.tool for call in calls], ["read_file", "get_project_brief"])
        self.assertEqual(calls[0].arguments, {"file_path": "README.md"})
        self.assertEqual(calls[1].arguments, {"project_id": "stasis-c3804eb0"})

    def test_tool_call_parser_rejects_multiple_tool_calls_mixed_with_prose(self) -> None:
        with self.assertRaises(ToolParseError):
            parse_tool_calls(
                'I will read these.\n'
                'tool_call: {"name":"read_file","arguments":{"file_path":"README.md"}}\n'
                'tool_call: {"name":"get_project_brief","arguments":{"project_id":"stasis-c3804eb0"}}'
            )

    def test_tool_call_line_parser_recovers_tool_calls_mixed_with_prose(self) -> None:
        calls = parse_tool_call_lines(
            'I will read these.\n\n'
            'tool_call: {"name":"read_file","arguments":{"file_path":"README.md"}}\n'
            'tool_call: {"name":"get_project_brief","arguments":{"project_id":"stasis-c3804eb0"}}'
        )

        self.assertEqual([call.tool for call in calls], ["read_file", "get_project_brief"])
        self.assertEqual(calls[0].arguments, {"file_path": "README.md"})
        self.assertEqual(calls[1].arguments, {"project_id": "stasis-c3804eb0"})

    def test_tool_call_parser_accepts_old_xml_format(self) -> None:
        call = parse_tool_call('<bitbuddy_tool_call>{"name":"list_projects","arguments":{}}</bitbuddy_tool_call>')
        self.assertEqual(call.tool, "list_projects")
        self.assertEqual(call.arguments, {})

    def test_tool_call_parser_rejects_tool_code(self) -> None:
        with self.assertRaises(ToolParseError):
            parse_tool_call('<tool_code>read_file(path="README.md")</tool_code>')

    def test_tool_call_parser_rejects_prose_mixed_with_tool_call(self) -> None:
        with self.assertRaises(ToolParseError):
            parse_tool_call('Let me read the file.\ntool_call: {"name":"read_file","arguments":{"file_path":"README.md"}}')

    def test_tool_call_parser_rejects_invalid_json(self) -> None:
        with self.assertRaises(ToolParseError):
            parse_tool_call('tool_call: {not valid json}')

    def test_tool_call_parser_rejects_missing_name(self) -> None:
        with self.assertRaises(ToolParseError):
            parse_tool_call('tool_call: {"arguments": {}}')

    def test_tool_call_parser_accepts_old_tool_key(self) -> None:
        call = parse_tool_call('tool_call: {"tool": "read_file", "arguments": {"file_path": "README.md"}}')
        self.assertEqual(call.tool, "read_file")
        self.assertEqual(call.arguments, {"file_path": "README.md"})

    def test_tool_call_parser_rejects_oversized_payload(self) -> None:
        with self.assertRaises(ToolParseError):
            parse_tool_call('tool_call: {"name":"read_file","arguments":{"file_path":"' + "x" * 5000 + '"}}')

    def test_contains_tool_call_detects_tool_call_prefix(self) -> None:
        self.assertTrue(contains_tool_call('tool_call: {"name":"read_file","arguments":{"file_path":"README.md"}}'))

    def test_contains_tool_call_detects_mixed_prose_tool_call_line(self) -> None:
        self.assertTrue(
            contains_tool_call(
                'I will save that.\n\n'
                'tool_call: {"name":"record_episode","arguments":{"title":"Passed courses","summary":"User passed courses."}}'
            )
        )

    def test_contains_tool_call_rejects_normal_text(self) -> None:
        self.assertFalse(contains_tool_call("Hello there"))

    def test_requested_project_file_path_detects_readme_requests(self) -> None:
        self.assertEqual(requested_project_file_path("Can you read that project's README.md please?"), "README.md")
        self.assertEqual(requested_project_file_path("Please summarize the readme"), "README.md")
        self.assertIsNone(requested_project_file_path("Does the project have a README.md?"))

    def test_one_project_that_project_readme_resolves_automatically(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bitbuddy-anchorbox-") as directory:
            project_root = Path(directory) / "anchorbox"
            project_root.mkdir()
            (project_root / "README.md").write_text("# Anchorbox\n", encoding="utf-8")
            resolution = resolve_project_file_request(
                "Can you read that project's README.md please?",
                [FakeProject("anchorbox-fa44bda3", "Anchorbox", (project_root,))],
            )

            self.assertIsNotNone(resolution)
            assert resolution is not None
            self.assertEqual(resolution.clarification, "")
            self.assertIsNotNone(resolution.tool_call)
            assert resolution.tool_call is not None
            self.assertEqual(resolution.tool_call.tool, "read_file")
            self.assertEqual(resolution.tool_call.arguments, {"project_id": "anchorbox-fa44bda3", "file_path": "README.md"})

    def test_two_projects_that_project_readme_asks_clarification(self) -> None:
        resolution = resolve_project_file_request(
            "Can you read that project's README.md please?",
            [
                FakeProject("anchorbox-fa44bda3", "Anchorbox", (Path("/tmp/anchorbox"),)),
                FakeProject("bitbuddy-12345678", "BitBuddy", (Path("/tmp/bitbuddy"),)),
            ],
        )

        self.assertIsNotNone(resolution)
        assert resolution is not None
        self.assertIsNone(resolution.tool_call)
        self.assertIn("Which project do you mean?", resolution.clarification)
        self.assertIn("* Anchorbox", resolution.clarification)
        self.assertIn("* BitBuddy", resolution.clarification)

    def test_explicit_project_name_with_multiple_projects_resolves(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bitbuddy-projects-") as directory:
            anchorbox_root = Path(directory) / "anchorbox"
            bitbuddy_root = Path(directory) / "bitbuddy"
            anchorbox_root.mkdir()
            bitbuddy_root.mkdir()
            (anchorbox_root / "README.md").write_text("# Anchorbox\n", encoding="utf-8")
            (bitbuddy_root / "README.md").write_text("# BitBuddy\n", encoding="utf-8")
            resolution = resolve_project_file_request(
                "Can you read Anchorbox's README.md please?",
                [
                    FakeProject("anchorbox-fa44bda3", "Anchorbox", (anchorbox_root,)),
                    FakeProject("bitbuddy-12345678", "BitBuddy", (bitbuddy_root,)),
                ],
            )

            self.assertIsNotNone(resolution)
            assert resolution is not None
            self.assertEqual(resolution.clarification, "")
            self.assertIsNotNone(resolution.tool_call)
            assert resolution.tool_call is not None
            self.assertEqual(resolution.tool_call.arguments, {"project_id": "anchorbox-fa44bda3", "file_path": "README.md"})

    def test_readme_request_searches_subdirectories_when_top_level_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bitbuddy-anchorbox-") as directory:
            project_root = Path(directory) / "anchorbox"
            web_dir = project_root / "web"
            web_dir.mkdir(parents=True)
            (web_dir / "README.md").write_text("# Web README\n", encoding="utf-8")

            resolution = resolve_project_file_request(
                "Can you read that project's README.md please?",
                [FakeProject("anchorbox-fa44bda3", "Anchorbox", (project_root,))],
            )

            self.assertIsNotNone(resolution)
            assert resolution is not None
            self.assertIsNotNone(resolution.tool_call)
            assert resolution.tool_call is not None
            self.assertEqual(resolution.tool_call.arguments, {"project_id": "anchorbox-fa44bda3", "file_path": "web/README.md"})

    def test_multiple_readmes_asks_which_and_offers_all(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bitbuddy-anchorbox-") as directory:
            project_root = Path(directory) / "anchorbox"
            (project_root / "web").mkdir(parents=True)
            (project_root / "docs").mkdir(parents=True)
            (project_root / "web" / "README.md").write_text("# Web README\n", encoding="utf-8")
            (project_root / "docs" / "README.md").write_text("# Docs README\n", encoding="utf-8")

            resolution = resolve_project_file_request(
                "Can you read that project's README.md please?",
                [FakeProject("anchorbox-fa44bda3", "Anchorbox", (project_root,))],
            )

            self.assertIsNotNone(resolution)
            assert resolution is not None
            self.assertIsNone(resolution.tool_call)
            self.assertIn("Which one do you mean?", resolution.clarification)
            self.assertIn('say "all"', resolution.clarification)
            self.assertIn("* docs/README.md", resolution.clarification)
            self.assertIn("* web/README.md", resolution.clarification)

    def test_readme_search_skips_dependency_directories(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bitbuddy-anchorbox-") as directory:
            project_root = Path(directory) / "anchorbox"
            (project_root / "web" / "node_modules" / "package").mkdir(parents=True)
            (project_root / "web").mkdir(exist_ok=True)
            (project_root / "web" / "README.md").write_text("# Web README\n", encoding="utf-8")
            (project_root / "web" / "node_modules" / "package" / "README.md").write_text("# Dependency README\n", encoding="utf-8")

            resolution = resolve_project_file_request(
                "Can you read that project's README.md please?",
                [FakeProject("anchorbox-fa44bda3", "Anchorbox", (project_root,))],
            )

            self.assertIsNotNone(resolution)
            assert resolution is not None
            self.assertIsNotNone(resolution.tool_call)
            assert resolution.tool_call is not None
            self.assertEqual(resolution.tool_call.arguments, {"project_id": "anchorbox-fa44bda3", "file_path": "web/README.md"})

    def test_tool_result_answer_returns_read_file_content(self) -> None:
        self.assertEqual(tool_result_answer(FakeToolResult(ok=True, content="# README.md\n\nHello")), "# README.md\n\nHello")

    def test_tool_result_answer_reports_read_errors(self) -> None:
        self.assertEqual(
            tool_result_answer(FakeToolResult(ok=False, error="Project file not found: README.md")),
            "I couldn't read that file: Project file not found: README.md",
        )

    def test_tool_call_thinking_is_safe_user_visible_status(self) -> None:
        text = tool_call_thinking(ToolCall("get_project_brief", {"project_id": "anchorbox-fa44bda3"}))

        self.assertIn("briefing", text)
        self.assertNotIn("<bitbuddy_tool_call>", text)
        self.assertNotIn("get_project_brief", text)
        self.assertNotIn("I should", text)

    def test_tool_call_parser_normalizes_type_instead_of_name(self) -> None:
        call = parse_tool_call('tool_call: {"type": "read_file", "arguments": {"file_path": "README.md"}}')
        self.assertEqual(call.tool, "read_file")
        self.assertEqual(call.arguments, {"file_path": "README.md"})

    def test_tool_call_parser_normalizes_flat_arguments(self) -> None:
        call = parse_tool_call('tool_call: {"name": "read_file", "file_path": "README.md", "project_id": "stasis"}')
        self.assertEqual(call.tool, "read_file")
        self.assertEqual(call.arguments, {"file_path": "README.md", "project_id": "stasis"})

    def test_tool_call_parser_normalizes_path_to_file_path(self) -> None:
        call = parse_tool_call('tool_call: {"name": "read_file", "arguments": {"path": "README.md"}}')
        self.assertEqual(call.tool, "read_file")
        # Parser adds file_path alias but keeps original path key too
        self.assertEqual(call.arguments.get("file_path"), "README.md")

    def test_structured_file_search_tools_execute(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bitbuddy-tools-") as directory:
            root = Path(directory)
            (root / "src").mkdir()
            (root / "src" / "app.py").write_text("class ToolExecutor:\n    pass\n", encoding="utf-8")
            executor = ToolExecutor(default_tool_registry())

            glob_result = executor.execute(ToolCall("glob_files", {"root_path": str(root), "pattern": "**/*.py"}))
            search_result = executor.execute(ToolCall("search_text", {"root_path": str(root), "pattern": "ToolExecutor", "include": "**/*.py"}))
            range_result = executor.execute(ToolCall("read_file_range", {"root_path": str(root), "file_path": "src/app.py", "start_line": 1, "line_count": 1}))

        self.assertTrue(glob_result.ok)
        self.assertIn("src/app.py", glob_result.content)
        self.assertTrue(search_result.ok)
        self.assertIn("ToolExecutor", search_result.content)
        self.assertTrue(range_result.ok)
        self.assertIn("1: class ToolExecutor:", range_result.content)


if __name__ == "__main__":
    unittest.main()
