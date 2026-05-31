from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "brain"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-self-notes-test-")

from bitbuddy.paths import GLOBAL_DB_PATH  # noqa: E402
from bitbuddy.self_notes import create_self_note, ensure_self_notes_database, get_self_note, list_self_notes, select_self_notes_for_context, cleanup_self_notes  # noqa: E402


class SelfNotesTest(unittest.TestCase):
    def setUp(self) -> None:
        ensure_self_notes_database()
        with sqlite3.connect(GLOBAL_DB_PATH) as connection:
            connection.execute("delete from self_notes")

    def test_create_and_list_active_self_note(self) -> None:
        note = create_self_note("Remember to avoid broad prompt injection.", topic="dreaming", priority=4, source="dreaming")

        notes = list_self_notes()

        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0].id, note.id)
        self.assertEqual(notes[0].source, "dreaming")

    def test_selective_injection_decrements_remaining_count(self) -> None:
        note = create_self_note("Mention queue cleanup only when relevant.", topic="queue cleanup", remaining_injections=1, injection_policy="next_n_chats")

        selected = select_self_notes_for_context(query="queue cleanup status", limit=3, mark_injected=True)

        self.assertEqual([item.id for item in selected], [note.id])
        self.assertEqual(get_self_note(note.id).status, "injected")

    def test_cleanup_expires_old_self_notes(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        note = create_self_note("Temporary note.", expires_at=(now - timedelta(minutes=1)).isoformat())

        expired = cleanup_self_notes(now=now)

        self.assertEqual(expired, 1)
        self.assertEqual(get_self_note(note.id).status, "expired")


if __name__ == "__main__":
    unittest.main()
