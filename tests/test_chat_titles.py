from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ.setdefault("HOME", tempfile.mkdtemp(prefix="bitbuddy-title-test-"))

from bitbuddy.prompt_builder import title_from_text  # noqa: E402


class ChatTitleTest(unittest.TestCase):
    def test_title_is_shorter_than_raw_first_message(self) -> None:
        title = title_from_text("can you add the settings page for dreaming under new section called autonomy and make it scroll nicely")

        self.assertLessEqual(len(title), 44)
        self.assertEqual(title, "add the settings page for dreaming under")

    def test_title_trims_at_word_boundary(self) -> None:
        title = title_from_text("Please investigate why consolidation misses important memories after long conversations")

        self.assertLessEqual(len(title), 44)
        self.assertFalse(title.endswith(" "))
        self.assertNotIn("Please", title)
        self.assertEqual(title, "investigate why consolidation misses")

    def test_empty_title_falls_back(self) -> None:
        self.assertEqual(title_from_text("   \n\t  "), "Untitled chat")


if __name__ == "__main__":
    unittest.main()
