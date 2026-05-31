from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "brain"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-skills-test-")

from bitbuddy.paths import SKILLS_DIR  # noqa: E402
from bitbuddy.prompt_builder import build_chat_messages  # noqa: E402
from bitbuddy.skills import archive_skill, create_skill, list_skills, load_skill, patch_skill, skill_catalog_prompt, validate_skill, write_skill_file  # noqa: E402
from bitbuddy.tools import ToolCall, ToolExecutor, default_tool_registry, tool_instruction_message  # noqa: E402


class SkillsRegistryTest(unittest.TestCase):
    def test_starter_skills_are_seeded_under_bitbuddy_home(self) -> None:
        skills = list_skills()
        names = {skill.name for skill in skills}

        self.assertIn("skill-authoring", names)
        self.assertIn("bitbuddy-development", names)
        self.assertTrue((SKILLS_DIR / "skill-authoring" / "SKILL.md").exists())

    def test_create_load_patch_validate_and_archive_skill(self) -> None:
        body = "# Example Workflow\n\n## Overview\n\nReusable steps."
        skill = create_skill("example-workflow", "Use when testing skill creation.", body)

        self.assertEqual(skill.name, "example-workflow")
        self.assertTrue(validate_skill("example-workflow").ok)
        self.assertIn("Reusable steps", load_skill("example-workflow").body)

        patched = patch_skill("example-workflow", "Reusable steps.", "Reusable patched steps.")
        self.assertIn("Reusable patched steps", patched.body)

        archived = archive_skill("example-workflow")
        self.assertTrue(archived.archived)
        self.assertNotIn("example-workflow", {skill.name for skill in list_skills()})
        self.assertIn("example-workflow", {skill.name for skill in list_skills(include_archived=True)})

    def test_support_file_writes_are_confined_to_allowed_skill_subdirs(self) -> None:
        create_skill("support-workflow", "Use when testing support files.", "# Support\n\n## Overview\n\nBody.")

        path = write_skill_file("support-workflow", "references/details.md", "details")

        self.assertEqual(path.read_text(encoding="utf-8"), "details")
        with self.assertRaises(ValueError):
            write_skill_file("support-workflow", "../escape.md", "nope")
        with self.assertRaises(ValueError):
            write_skill_file("support-workflow", "random/details.md", "nope")

    def test_skill_catalog_prompt_lists_active_skills_only(self) -> None:
        create_skill("catalog-workflow", "Use when testing skill catalog output.", "# Catalog\n\n## Overview\n\nBody.")
        create_skill("archived-workflow", "Use when testing archived skills.", "# Archived\n\n## Overview\n\nBody.")
        archive_skill("archived-workflow")

        prompt = skill_catalog_prompt()

        self.assertIn("[Available Skills]", prompt)
        self.assertIn("catalog-workflow", prompt)
        self.assertNotIn("archived-workflow", prompt)


class SkillsToolIntegrationTest(unittest.TestCase):
    def test_default_tool_registry_exposes_skill_tools(self) -> None:
        content = tool_instruction_message(default_tool_registry())["content"]

        self.assertIn("- list_skills:", content)
        self.assertIn("- load_skill:", content)
        self.assertIn("- create_skill:", content)
        self.assertIn("- patch_skill:", content)
        self.assertIn("- archive_skill:", content)
        self.assertIn("- validate_skill:", content)

    def test_plan_mode_allows_read_only_skill_tools_and_blocks_skill_writes(self) -> None:
        executor = ToolExecutor(default_tool_registry(), mode="plan")

        self.assertEqual(executor.check_mode_restrictions(ToolCall("list_skills", {})), "")
        self.assertEqual(executor.check_mode_restrictions(ToolCall("load_skill", {"name": "skill-authoring"})), "")
        self.assertIn(
            "Plan mode is strictly read-only",
            executor.check_mode_restrictions(
                ToolCall("create_skill", {"name": "blocked-skill", "description": "Use when blocked.", "body": "# Blocked"})
            ),
        )

    def test_skill_tools_execute_against_registry(self) -> None:
        registry = default_tool_registry()
        executor = ToolExecutor(registry)

        create_result = executor.execute(
            ToolCall(
                "create_skill",
                {
                    "name": "tool-created-skill",
                    "description": "Use when testing skill tool creation.",
                    "body": "# Tool Created\n\n## Overview\n\nCreated by a tool.",
                },
            )
        )
        self.assertTrue(create_result.ok)

        load_result = executor.execute(ToolCall("load_skill", {"name": "tool-created-skill"}))
        self.assertTrue(load_result.ok)
        self.assertIn("Created by a tool", load_result.content)

        list_result = executor.execute(ToolCall("list_skills", {}))
        self.assertTrue(list_result.ok)
        payload = json.loads(list_result.content)
        self.assertIn("tool-created-skill", {item["name"] for item in payload["skills"]})

    def test_prompt_exposes_skill_discovery(self) -> None:
        messages = build_chat_messages([{"role": "user", "content": "Help me improve a skill."}], "chat")

        self.assertIn("[Available Skills]", messages[0]["content"])
        self.assertIn("skill-authoring", messages[0]["content"])
        self.assertIn("Call load_skill", messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
