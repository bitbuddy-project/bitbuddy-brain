from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-project-context-test-")

from bitbuddy.projects.context import build_project_context_pack  # noqa: E402
from bitbuddy.memory.project import register_project  # noqa: E402


class ProjectContextRelevanceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project_dir = Path(tempfile.mkdtemp(prefix="bitbuddy-project-context-repo-"))
        (cls.project_dir / "README.md").write_text("# Test project\n", encoding="utf-8")
        cls.project = register_project("anchorbox", [str(cls.project_dir)])

    def assert_emits_context(self, query: str) -> None:
        pack = build_project_context_pack([{"role": "user", "content": query}], "chat", max_chars=6000)
        self.assertIsNotNone(pack)
        assert pack is not None
        self.assertIn("[Project Context Pack", pack)
        self.assertIn(self.project.id, pack)

    def test_how_hard_folder_system_like_gallery_emits_context(self) -> None:
        self.assert_emits_context("how hard would it be to add folder system to notes app like image gallery app?")

    def test_how_hard_folders_to_notes_emits_context(self) -> None:
        self.assert_emits_context("how hard would it be to add folders to notes?")

    def test_what_would_it_take_similar_gallery_albums_emits_context(self) -> None:
        self.assert_emits_context("what would it take to make notes folders similar to gallery albums?")

    def test_casual_lunch_query_does_not_emit_context(self) -> None:
        pack = build_project_context_pack([{"role": "user", "content": "what should I eat for lunch?"}], "chat", max_chars=6000)
        self.assertIsNone(pack)


if __name__ == "__main__":
    unittest.main()
