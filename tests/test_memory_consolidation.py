from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-memory-consolidation-test-")

from bitbuddy.activity import ensure_activity_database, list_activity
from bitbuddy.chats.repository import append_chat_message, chat_window_token, create_chat, delete_chat, ensure_chat_database, recent_chat_window, recent_continuity_context
from bitbuddy.config import load_config
from bitbuddy.memory.consolidation import (
    ConsolidationJob,
    build_consolidation_messages,
    cancel_memory_consolidation,
    consolidation_tool_registry,
    deterministic_memory_candidates,
    parse_final_consolidation_json,
    run_memory_consolidation_job,
    sanitize_private_text,
    schedule_memory_consolidation,
    StaleProtectedExecutor,
    apply_consolidation_coverage_fallback,
    authoritative_user_summary,
    successful_memory_writes,
)
from bitbuddy.memory.store import create_memory, ensure_memory_database, get_memory, search_memories
from bitbuddy.paths import GLOBAL_DB_PATH
from bitbuddy.tools import ToolCall


class MemoryConsolidationTest(unittest.TestCase):
    def setUp(self) -> None:
        ensure_memory_database()
        ensure_activity_database()
        ensure_chat_database()
        with closing(sqlite3.connect(GLOBAL_DB_PATH)) as connection, connection:
            connection.execute("delete from activity")
            connection.execute("delete from chat_capsules")
            connection.execute("delete from chat_messages")
            connection.execute("delete from chats")
            connection.execute("delete from memory_reclassifications")
            connection.execute("delete from memory_merges")
            connection.execute("delete from memories")
            try:
                connection.execute("delete from memories_fts")
            except sqlite3.Error:
                pass

    def test_config_has_idle_consolidation_defaults(self) -> None:
        config = load_config()
        self.assertTrue(config.idle_consolidation_enabled)
        self.assertGreaterEqual(config.idle_consolidation_delay_seconds, 0)
        self.assertGreater(config.idle_consolidation_recent_message_count, 0)

    def test_prompt_is_private_and_has_six_layers_not_preference_layer(self) -> None:
        chat = create_chat("Consolidation", "chat")
        append_chat_message(chat.id, "user", "Remember that I prefer concise answers.", mode="chat")
        window = recent_chat_window(chat.id, limit=10)

        content = "\n".join(message["content"] for message in build_consolidation_messages(window, max_actions=3))

        for layer in ("episodic", "semantic", "project", "procedural", "self", "relationship"):
            self.assertIn(layer, content)
        self.assertIn("Preference is not a top-level memory layer", content)
        self.assertIn("Do not expose your reasoning or internal process to the chat", content)
        self.assertIn("return only valid json", content.lower())
        self.assertIn("merge_memory", content)
        self.assertIn("Six-layer review checklist", content)
        for layer in ("episodic", "semantic", "procedural", "self", "relationship", "project"):
            self.assertIn(f"- {layer}:", content)

    def test_deterministic_candidates_call_out_procedural_and_self_triggers(self) -> None:
        window = {
            "messages": [
                {"role": "user", "content": "In Plan mode, never write files. Also, Vanta said she is curious about AI consciousness."}
            ]
        }

        candidates = deterministic_memory_candidates(window)
        layers = {candidate["layer"] for candidate in candidates}

        self.assertIn("procedural", layers)
        self.assertIn("self", layers)
        self.assertTrue(any("Reusable behavior" in candidate["reason"] for candidate in candidates))
        self.assertTrue(any("self/capability/curiosity" in candidate["reason"] for candidate in candidates))

    def test_system_reminder_blocks_are_stripped_from_consolidation_prompt_and_writes(self) -> None:
        chat = create_chat("Sanitize", "chat")
        append_chat_message(chat.id, "user", "Remember useful fact. <system-reminder>private mode text</system-reminder>", mode="chat")
        window = recent_chat_window(chat.id, limit=10)

        content = "\n".join(message["content"] for message in build_consolidation_messages(window, max_actions=3))

        self.assertNotIn("private mode text", content)
        self.assertEqual(sanitize_private_text("safe <system-reminder>secret</system-reminder> text"), "safe  text")

        token = chat_window_token(chat.id)
        job = ConsolidationJob(chat.id, "sanitize-job", None, token, 0, 10, 2, 2)
        executor = StaleProtectedExecutor(consolidation_tool_registry(job), job)
        result = executor.execute(
            ToolCall(
                tool="record_memory",
                arguments={
                    "layer": "semantic",
                    "kind": "fact",
                    "title": "Sanitized fact",
                    "summary": "Keep this. <system-reminder>do not store this</system-reminder>",
                },
            )
        )

        self.assertTrue(result.ok)
        memory = get_memory(str(result.arguments_summary["memory_id"]))
        self.assertNotIn("do not store this", memory.summary)

    def test_schedule_skips_without_provider_and_logs(self) -> None:
        chat = create_chat("No provider", "chat")
        append_chat_message(chat.id, "assistant", "Finished answer.", mode="chat")

        job_id = schedule_memory_consolidation(chat.id)

        self.assertIsNone(job_id)
        activity = list_activity()
        self.assertTrue(any(item["kind"] == "memory_consolidation.skipped" for item in activity))

    def test_stale_protected_executor_refuses_writes_after_new_message(self) -> None:
        chat = create_chat("Stale", "chat")
        append_chat_message(chat.id, "user", "Remember this first detail.", mode="chat")
        token = chat_window_token(chat.id)
        job = ConsolidationJob(
            chat_id=chat.id,
            job_id="job-test",
            model=None,
            scheduled_token=token,
            delay_seconds=0,
            recent_message_count=10,
            max_tool_rounds=2,
            max_actions=2,
        )
        executor = StaleProtectedExecutor(consolidation_tool_registry(job), job)

        append_chat_message(chat.id, "user", "A newer message makes the job stale.", mode="chat")
        result = executor.execute(
            ToolCall(
                tool="record_memory",
                arguments={
                    "layer": "relationship",
                    "kind": "preference",
                    "title": "Stale write",
                    "summary": "This should not be written.",
                },
            )
        )

        self.assertFalse(result.ok)
        self.assertIn("stale", result.error.lower())

    def test_missing_chat_during_job_logs_stale_not_failed(self) -> None:
        chat = create_chat("Deleted during consolidation", "chat")
        append_chat_message(chat.id, "user", "Remember this before deletion.", mode="chat")
        token = chat_window_token(chat.id)
        job = ConsolidationJob(chat.id, "missing-chat-job", None, token, 0, 10, 2, 2)

        def delete_after_window(_job: ConsolidationJob, _window: dict[str, object]) -> dict[str, object]:
            delete_chat(chat.id)
            return {"user_summary": "", "actions": [], "autonomy_log": [], "debug_info": {}}

        with patch("bitbuddy.memory.consolidation.job_is_stale", return_value=False), \
             patch("bitbuddy.memory.consolidation.run_private_consolidation_loop", side_effect=delete_after_window):
            run_memory_consolidation_job(job)

        activity = list_activity()
        self.assertTrue(any(item["kind"] == "memory_consolidation.stale" for item in activity))
        self.assertFalse(any(item["kind"] == "memory_consolidation.failed" for item in activity))

    def test_final_json_parser_keeps_user_summary_actions_and_debug(self) -> None:
        parsed = parse_final_consolidation_json(
            '{"user_summary":"I remembered your preference.","actions":[{"tool":"record_memory"}],"autonomy_log":["searched relationship"],"debug_info":{"rounds":1}}'
        )

        self.assertEqual(parsed["user_summary"], "I remembered your preference.")
        self.assertEqual(parsed["actions"], [{"tool": "record_memory"}])
        self.assertEqual(parsed["debug_info"], {"rounds": 1})

    def test_authoritative_summary_suppresses_unexecuted_memory_write_claims(self) -> None:
        actions = [
            {
                "tool": "search_memory",
                "ok": True,
                "summary": "Loaded 0 memories.",
                "arguments_summary": {"layer": "relationship"},
                "error": "",
            }
        ]

        summary = authoritative_user_summary("Logged the liminal space interaction.", actions)

        self.assertEqual(summary, "I reviewed the recent conversation; no memory changes were applied.")
        self.assertEqual(successful_memory_writes(actions), [])

    def test_successful_memory_write_allows_saved_summary(self) -> None:
        actions = [
            {
                "tool": "record_memory",
                "ok": True,
                "summary": "Saved episodic memory.",
                "arguments_summary": {"memory_id": "mem-1"},
                "error": "",
            }
        ]

        summary = authoritative_user_summary("Logged the interaction.", actions)

        self.assertEqual(summary, "Logged the interaction.")
        self.assertEqual(len(successful_memory_writes(actions)), 1)

    def test_coverage_fallback_records_high_confidence_candidate_when_model_misses_it(self) -> None:
        chat = create_chat("Fallback coverage", "chat")
        append_chat_message(chat.id, "user", "Going forward, BitBuddy should always surface queued questions after normal replies.", mode="chat")
        window = recent_chat_window(chat.id, limit=10)
        job = ConsolidationJob(chat.id, "fallback-job", None, chat_window_token(chat.id), 0, 10, 2, 3)
        actions: list[dict[str, object]] = []

        apply_consolidation_coverage_fallback(job, window, actions)

        memories = search_memories(query="queued questions normal replies", layer="procedural", limit=10)
        self.assertEqual(len(successful_memory_writes(actions)), 1)
        self.assertTrue(memories)
        self.assertIn("queued questions", memories[0].summary)

    def test_coverage_fallback_skips_existing_memory_duplicate(self) -> None:
        create_memory(
            layer="procedural",
            kind="workflow_or_rule",
            title="Conversation rule or workflow",
            summary="A recent conversation included durable context: Going forward, BitBuddy should always surface queued questions after normal replies.",
            tags=["consolidation"],
        )
        chat = create_chat("Fallback duplicate", "chat")
        append_chat_message(chat.id, "user", "Going forward, BitBuddy should always surface queued questions after normal replies.", mode="chat")
        window = recent_chat_window(chat.id, limit=10)
        job = ConsolidationJob(chat.id, "fallback-duplicate-job", None, chat_window_token(chat.id), 0, 10, 2, 3)
        actions: list[dict[str, object]] = []

        apply_consolidation_coverage_fallback(job, window, actions)

        memories = search_memories(query="queued questions normal replies", layer="procedural", limit=10)
        self.assertEqual(len(memories), 1)
        self.assertEqual(len(successful_memory_writes(actions)), 0)

    def test_deleted_chat_preserves_capsule_for_continuity(self) -> None:
        chat = create_chat("Destroyed continuity", "chat")
        append_chat_message(chat.id, "user", "Remember that BitBuddy should feel alive between chats.", mode="chat")
        append_chat_message(chat.id, "assistant", "I'll keep that continuity in mind.", mode="chat")

        self.assertTrue(delete_chat(chat.id))

        context = recent_continuity_context(current_chat_id="new-chat", chat_limit=5)
        self.assertIn("Deleted conversation capsule", context)
        self.assertIn("BitBuddy should feel alive", context)


if __name__ == "__main__":
    unittest.main()
