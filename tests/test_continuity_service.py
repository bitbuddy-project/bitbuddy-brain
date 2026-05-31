from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "brain"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-continuity-service-test-")

from bitbuddy.autonomy.context import build_autonomy_context  # noqa: E402
from bitbuddy.autonomy.intentions import create_intention, ensure_intentions_database  # noqa: E402
from bitbuddy.chats.repository import create_chat, ensure_chat_database  # noqa: E402
from bitbuddy.continuity import (  # noqa: E402
    build_continuity_digest,
    capture_post_chat_episodic_fallback,
    continuity_state,
    ensure_continuity_database,
    recent_continuity_events,
    record_continuity_event,
)
from bitbuddy.memory.consolidation import ConsolidationJob, apply_consolidation_coverage_fallback, build_consolidation_messages  # noqa: E402
from bitbuddy.memory.episodic import ensure_episodic_memory_database, list_recent_episodes  # noqa: E402
from bitbuddy.memory.store import ensure_memory_database, search_memories  # noqa: E402
from bitbuddy.paths import GLOBAL_DB_PATH  # noqa: E402
from bitbuddy.prompt_builder import build_chat_messages  # noqa: E402


class ContinuityServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        ensure_chat_database()
        ensure_memory_database()
        ensure_episodic_memory_database()
        ensure_intentions_database()
        ensure_continuity_database()
        with sqlite3.connect(GLOBAL_DB_PATH) as connection:
            for table in (
                "continuity_events",
                "episodic_memory_capture_log",
                "intentions",
                "episodes",
                "chat_messages",
                "chats",
                "memory_reclassifications",
                "memory_merges",
                "memories",
            ):
                connection.execute(f"delete from {table}")
            connection.execute(
                """
                update continuity_state
                set active_project_id = '', active_topic = '', last_chat_id = '',
                    last_user_message_at = '', last_assistant_message_at = '',
                    last_user_summary = '', last_assistant_action_summary = '',
                    last_tool_result_summary = '', last_autonomy_summary = '',
                    last_memory_update_summary = '', last_meaningful_turn_at = '',
                    last_meaningful_turn_summary = '', unresolved_threads_json = '[]'
                where id = 1
                """
            )
            try:
                connection.execute("delete from memories_fts")
            except sqlite3.Error:
                pass

    def test_record_event_updates_state_without_trivial_meaningful_overwrite(self) -> None:
        record_continuity_event(
            "assistant_response_completed",
            "User and Vanta planned the continuity memory reliability pass for BitBuddy.",
            source="chat",
            chat_id="chat-one",
            topic="memory continuity",
        )
        record_continuity_event("user_message_received", "lol", source="chat", chat_id="chat-one")

        state = continuity_state()

        self.assertEqual(state["last_user_summary"], "lol")
        self.assertIn("continuity memory reliability", state["last_meaningful_turn_summary"])

    def test_post_chat_saves_episodic_when_no_clear_layer(self) -> None:
        chat = create_chat("Continuity", "chat")

        memory = capture_post_chat_episodic_fallback(
            chat_id=chat.id,
            run_id="run-one",
            latest_user_text="We need Vanta to remember what happened recently and what thread is unresolved.",
            assistant_text="I will add a continuity digest and episodic fallback capture so the current situation is not lost.",
        )

        episodes = list_recent_episodes(limit=5)
        self.assertIsNotNone(memory)
        self.assertEqual(len(episodes), 1)
        self.assertIn("continuity", episodes[0].summary.lower())

    def test_post_chat_skips_trivial_exchange(self) -> None:
        chat = create_chat("Trivial", "chat")

        memory = capture_post_chat_episodic_fallback(
            chat_id=chat.id,
            latest_user_text="ok",
            assistant_text="Sounds good.",
        )

        self.assertIsNone(memory)
        self.assertEqual(list_recent_episodes(limit=5), [])

    def test_continuity_digest_includes_recent_episodic_memory(self) -> None:
        chat = create_chat("Digest", "chat")
        capture_post_chat_episodic_fallback(
            chat_id=chat.id,
            latest_user_text="User is focusing on continuity problems in BitBuddy.",
            assistant_text="Vanta planned episodic fallback capture and deterministic digest injection.",
        )

        digest = build_continuity_digest(chat_id=chat.id, latest_user_text="Where did we leave off?", source="chat")

        self.assertIn("[Continuity Digest]", digest)
        self.assertIn("last_meaningful_turn", digest)
        self.assertIn("episodic", digest.lower())

    def test_chat_context_receives_continuity_digest(self) -> None:
        chat = create_chat("Prompt", "chat")
        record_continuity_event("assistant_response_completed", "Vanta last planned a continuity digest for chat prompts.", source="chat", chat_id=chat.id)

        messages = build_chat_messages([{"role": "user", "content": "what were we doing?"}], "chat", chat_id=chat.id)

        self.assertTrue(any("[Continuity Digest]" in message.get("content", "") for message in messages))

    def test_autonomy_context_receives_continuity_digest(self) -> None:
        record_continuity_event("assistant_response_completed", "Current topic is memory continuity for Vanta.", source="chat", chat_id="chat-auto")

        context = build_autonomy_context("chat-auto")

        self.assertIn("[Continuity Digest]", context)
        self.assertIn("memory continuity", context)

    def test_consolidation_prompt_receives_continuity_digest(self) -> None:
        chat = create_chat("Consolidation", "chat")
        record_continuity_event("assistant_response_completed", "Consolidation should use continuity digest context.", source="chat", chat_id=chat.id)
        window = {"chat_id": chat.id, "messages": [{"role": "user", "content": "We need better continuity memory."}]}

        content = "\n".join(message["content"] for message in build_consolidation_messages(window, max_actions=3))

        self.assertIn("[Continuity Digest]", content)
        self.assertIn("Episodic memory is a first-line catch/funnel layer", content)

    def test_intention_created_records_continuity_event(self) -> None:
        create_intention("question", "Should I ask Dustin about unresolved continuity threads?", "Useful follow-up", "cycle-one")

        events = recent_continuity_events(limit=5)

        self.assertTrue(any(event.event_type == "intention_created" for event in events))

    def test_consolidation_fallback_can_save_episodic_continuity(self) -> None:
        chat = create_chat("Fallback", "chat")
        window = {
            "chat_id": chat.id,
            "messages": [
                {
                    "role": "user",
                    "content": "Today we discussed an unresolved thread about where we left off after a long conversation.",
                }
            ],
        }
        job = ConsolidationJob(chat.id, "job-one", None, {"max_message_id": 0}, 0, 10, 2, 3)
        actions: list[dict[str, object]] = []

        apply_consolidation_coverage_fallback(job, window, actions)

        memories = search_memories(query="unresolved thread where we left off", layer="episodic", limit=5)
        self.assertTrue(memories)
        self.assertTrue(any(action.get("arguments_summary", {}).get("layer") == "episodic" for action in actions if isinstance(action.get("arguments_summary"), dict)))


if __name__ == "__main__":
    unittest.main()
