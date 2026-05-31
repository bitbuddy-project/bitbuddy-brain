from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "brain"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-librarian-selection-test-")

from bitbuddy.librarian import build_advisory_whisper_message, regenerate_card, select_project_context
from bitbuddy.chats.runtime import clean_synthesis_text
from bitbuddy.memory.project import initialize_project_database, register_project


class LibrarianSelectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.stasis = cls.create_project(
            "Stasis",
            "Stasis is a modern Wayland idle manager that knows when to step back.",
        )
        cls.anchorbox = cls.create_project(
            "Anchorbox",
            "Anchorbox is a note-taking test project.",
        )

    @staticmethod
    def create_project(name: str, purpose: str):
        root = Path(tempfile.mkdtemp(prefix=f"bitbuddy-{name.lower()}-repo-"))
        (root / "README.md").write_text(f"# {name}\n", encoding="utf-8")
        project = register_project(name, [str(root)])
        initialize_project_database(project.database_path)
        with sqlite3.connect(project.database_path) as connection:
            connection.execute(
                """
                insert into project_profile (
                    id, name, repo_path, stack, purpose, current_status,
                    verified_facts, inferred_facts, needs_read, repo_structure_snapshot
                ) values (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project.name,
                    str(root),
                    "Rust",
                    purpose,
                    "Indexed for tests.",
                    "stack=Rust",
                    "",
                    "Read source before exact claims.",
                    "README.md",
                ),
            )
            connection.execute("insert into scans (finished_at) values (current_timestamp)")
        regenerate_card(project.id)
        return project

    def test_exact_project_mention_selects_project_context(self) -> None:
        selections = select_project_context("Read README.md for stasis")

        self.assertTrue(selections)
        self.assertEqual(selections[0].card.project_id, self.stasis.id)
        self.assertEqual(selections[0].confidence, "high")

    def test_generic_project_memory_does_not_select_random_project(self) -> None:
        selections = select_project_context("how should project memory work?")

        self.assertEqual(selections, [])

    def test_system_reminder_text_does_not_create_project_match(self) -> None:
        selections = select_project_context(
            "what should we do? <system-reminder>Stasis stasis-c3804eb0 README.md</system-reminder>"
        )

        self.assertEqual(selections, [])

    def test_active_project_resolves_followup_readme_reference(self) -> None:
        selections = select_project_context("Read README.md", active_project_ids=[self.stasis.id])

        self.assertTrue(selections)
        self.assertEqual(selections[0].card.project_id, self.stasis.id)
        self.assertEqual(selections[0].source, "active_chat")

    def test_advisory_whisper_uses_scored_selection(self) -> None:
        message = build_advisory_whisper_message("Stasis is mainly a Wayland idle manager", max_chars=2000)

        self.assertIsNotNone(message)
        assert message is not None
        self.assertIn(self.stasis.id, message["content"])
        self.assertIn("Selection: high confidence", message["content"])
        self.assertIn("answer directly from this context", message["content"])
        self.assertIn("modern Wayland idle manager", message["content"])

    def test_final_synthesis_cleaning_strips_system_reminder(self) -> None:
        text = """Anchorbox summary.
<system-reminder>
Your operational mode has changed from plan to build.
</system-reminder>"""

        clean = clean_synthesis_text(text)

        self.assertEqual(clean, "Anchorbox summary.")


if __name__ == "__main__":
    unittest.main()
