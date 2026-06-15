from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-episodic-test-")

from bitbuddy.memory.episodic import (
    create_episode,
    ensure_episodic_memory_database,
    get_episode,
    list_recent_episodes,
    search_episodes,
    episodic_memory_context,
)
from bitbuddy.chats.repository import create_chat, delete_chat
from bitbuddy.prompt_builder import build_chat_messages
from bitbuddy.tools import (
    ToolCall,
    ToolDefinition,
    ToolExecutor,
    ToolResult,
    default_tool_registry,
    forget_episode_tool,
    get_episode_memory_tool,
    record_episode_tool,
    update_episode_tool,
)


def legacy_episode_tool_result(tool: str, arguments: dict[str, object]) -> ToolResult:
    handlers = {
        "record_episode": record_episode_tool,
        "update_episode": update_episode_tool,
        "forget_episode": forget_episode_tool,
        "get_episode_memory": get_episode_memory_tool,
    }
    definition = ToolDefinition(tool, "legacy compatibility test tool", {}, 6000)
    try:
        return handlers[tool](arguments, definition)
    except Exception as error:
        return ToolResult(tool, False, "", f"Tool failed: {tool}", {}, error=str(error))


class EpisodicMemoryTest(unittest.TestCase):
    def setUp(self) -> None:
        ensure_episodic_memory_database()
        # Clear episodes table between tests to avoid cross-test contamination
        from bitbuddy.paths import GLOBAL_DB_PATH
        import sqlite3
        with closing(sqlite3.connect(GLOBAL_DB_PATH)) as connection, connection:
            connection.execute("delete from episodes")
            connection.execute("delete from memories")
            try:
                connection.execute("delete from memories_fts")
            except sqlite3.Error:
                pass

    def test_create_and_retrieve_episode(self) -> None:
        episode = create_episode(
            title="Personality discussion",
            summary="The user liked Vanta having quirks like liminal spaces and cartography.",
            importance=4,
            tags=["personality", "preferences"],
        )

        fetched = get_episode(episode.id)
        self.assertEqual(fetched.title, "Personality discussion")
        self.assertEqual(fetched.summary, "The user liked Vanta having quirks like liminal spaces and cartography.")
        self.assertEqual(fetched.importance, 4)
        self.assertEqual(fetched.tags, ["personality", "preferences"])
        self.assertIsNone(fetched.conversation_id)
        self.assertIsNone(fetched.project_id)

    def test_recent_episodes_newest_first(self) -> None:
        e1 = create_episode(title="First", summary="First episode", importance=1)
        e2 = create_episode(title="Second", summary="Second episode", importance=5)
        e3 = create_episode(title="Third", summary="Third episode", importance=3)

        recent = list_recent_episodes(limit=10)
        titles = [ep.title for ep in recent]

        # Ordered by importance DESC, then updated_at DESC
        self.assertEqual(titles, ["Second", "Third", "First"])

    def test_recent_episodes_respects_limit(self) -> None:
        for i in range(5):
            create_episode(title=f"Episode {i}", summary=f"Summary {i}", importance=i)

        recent = list_recent_episodes(limit=3)
        self.assertEqual(len(recent), 3)

    def test_search_finds_by_title(self) -> None:
        create_episode(title="Action naming", summary="The user decided to rename something.")
        create_episode(title="UI cleanup", summary="The user was frustrated with raw JSON.")

        results = search_episodes("action naming")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Action naming")

    def test_search_finds_by_summary(self) -> None:
        create_episode(title="Naming", summary="The user decided the action layer should not be called skills.")
        create_episode(title="UI", summary="The user was frustrated with raw JSON.")

        results = search_episodes("skills")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Naming")

    def test_search_finds_by_tags(self) -> None:
        create_episode(title="A", summary="Summary A", tags=["frontend", "ui"])
        create_episode(title="B", summary="Summary B", tags=["backend", "api"])

        results = search_episodes("frontend")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "A")

    def test_search_orders_by_importance(self) -> None:
        create_episode(title="Low", summary="Low importance", importance=1)
        create_episode(title="High", summary="High importance", importance=5)
        create_episode(title="Medium", summary="Medium importance", importance=3)

        results = search_episodes("importance")
        titles = [ep.title for ep in results]
        self.assertEqual(titles, ["High", "Medium", "Low"])

    def test_episode_survives_chat_deletion(self) -> None:
        chat = create_chat("Test chat", "chat")
        episode = create_episode(
            title="Chat event",
            summary="Something happened in a chat.",
            conversation_id=chat.id,
        )

        delete_chat(chat.id)

        # Episode should still exist
        fetched = get_episode(episode.id)
        self.assertEqual(fetched.title, "Chat event")
        self.assertEqual(fetched.conversation_id, chat.id)

    def test_prompt_builder_includes_episodic_memories(self) -> None:
        create_episode(
            title="Daemon restart",
            summary="Remember that the daemon restart was the next action.",
            importance=5,
            tags=["action"],
        )

        messages = build_chat_messages(
            [{"role": "user", "content": "Where did we leave off?"}],
            "chat",
        )

        episodic_messages = [msg for msg in messages if "[Relevant Layered Memories]" in msg.get("content", "")]
        self.assertEqual(len(episodic_messages), 1)
        self.assertIn("Daemon restart", episodic_messages[0]["content"])
        self.assertIn("daemon restart was the next action", episodic_messages[0]["content"])

    def test_prompt_builder_bounded_no_dump(self) -> None:
        for i in range(20):
            create_episode(
                title=f"Episode {i}",
                summary=f"This is a long summary for episode {i} with lots of text to make it take up space.",
                importance=i % 5 + 1,
            )

        messages = build_chat_messages(
            [{"role": "user", "content": "What do you remember?"}],
            "chat",
        )

        episodic_messages = [msg for msg in messages if "[Relevant Layered Memories]" in msg.get("content", "")]
        self.assertEqual(len(episodic_messages), 1)
        content = episodic_messages[0]["content"]

        # Should be bounded (max ~1600 chars for content, plus header)
        self.assertLess(len(content), 2500)

        # Should not contain all 20 episodes
        episode_count = content.count("Episode ")
        self.assertLess(episode_count, 10)

    def test_prompt_builder_includes_relevant_and_baseline_episodic_memories(self) -> None:
        create_episode(title="Math confidence", summary="User feels discouraged about math.", importance=3)
        create_episode(title="Late bloomer", summary="User identifies as a late bloomer and feels stuck.", importance=5)

        messages = build_chat_messages(
            [{"role": "user", "content": "I feel bad about math again."}],
            "chat",
        )

        episodic_messages = [msg for msg in messages if "[Relevant Layered Memories]" in msg.get("content", "")]
        self.assertEqual(len(episodic_messages), 1)
        content = episodic_messages[0]["content"]
        self.assertIn("Math confidence", content)
        self.assertIn("Late bloomer", content)
        self.assertIn("id ", content)

    def test_episodic_memory_context_with_query(self) -> None:
        create_episode(title="Frontend work", summary="Fixed the CSS layout.", tags=["css"])
        create_episode(title="Backend work", summary="Optimized the database queries.", tags=["sql"])

        context = episodic_memory_context(query="database", limit=4)
        self.assertIn("Backend work", context)
        self.assertNotIn("Frontend work", context)

    def test_episodic_memory_context_can_include_baseline_with_query(self) -> None:
        create_episode(title="Frontend work", summary="Fixed the CSS layout.", tags=["css"], importance=5)
        create_episode(title="Backend work", summary="Optimized the database queries.", tags=["sql"], importance=3)

        context = episodic_memory_context(query="database", limit=4, include_baseline=True, baseline_limit=1)

        self.assertIn("Backend work", context)
        self.assertIn("Frontend work", context)

    def test_episodic_memory_context_empty_when_no_episodes(self) -> None:
        context = episodic_memory_context(query="nonexistent")
        self.assertEqual(context, "")

    def test_episode_with_project_id(self) -> None:
        episode = create_episode(
            title="Project event",
            summary="Something about the project.",
            project_id="test-project-123",
        )

        fetched = get_episode(episode.id)
        self.assertEqual(fetched.project_id, "test-project-123")

    def test_episode_metadata(self) -> None:
        episode = create_episode(
            title="Meta test",
            summary="Testing metadata.",
            metadata={"key": "value", "nested": {"a": 1}},
        )

        fetched = get_episode(episode.id)
        self.assertEqual(fetched.metadata, {"key": "value", "nested": {"a": 1}})

    def test_record_episode_tool_saves_episode(self) -> None:
        result = legacy_episode_tool_result(
            "record_episode",
            {
                "title": "Tool-saved memory",
                "summary": "This was saved via the tool.",
                "importance": 4,
                "conversation_id": "test-chat-123",
            },
        )

        self.assertTrue(result.ok)
        self.assertIn("Saved episode", result.content)

        # Verify it was actually saved
        recent = list_recent_episodes(limit=5)
        self.assertTrue(any(ep.title == "Tool-saved memory" for ep in recent))

    def test_record_episode_tool_anti_spam_cap(self) -> None:
        # Save 2 auto episodes
        for i in range(2):
            result = legacy_episode_tool_result(
                "record_episode",
                {
                    "title": f"Auto memory {i}",
                    "summary": "Auto-saved.",
                    "conversation_id": "spam-chat-123",
                },
            )
            self.assertTrue(result.ok)

        # Third auto episode should fail
        result = legacy_episode_tool_result(
            "record_episode",
            {
                "title": "Auto memory 3",
                "summary": "Should be blocked.",
                "conversation_id": "spam-chat-123",
            },
        )
        self.assertFalse(result.ok)
        self.assertIn("limit", result.error.lower())

        # Explicit user request should bypass
        result = legacy_episode_tool_result(
            "record_episode",
            {
                "title": "Explicit memory",
                "summary": "User asked to remember.",
                "conversation_id": "spam-chat-123",
                "explicit_user_request": True,
            },
        )
        self.assertTrue(result.ok)

    def test_record_episode_tool_duplicate_detection(self) -> None:
        result = legacy_episode_tool_result(
            "record_episode",
            {
                "title": "Duplicate check",
                "summary": "First save.",
                "conversation_id": "dup-chat-123",
            },
        )
        self.assertTrue(result.ok)

        result = legacy_episode_tool_result(
            "record_episode",
            {
                "title": "Duplicate check",
                "summary": "Second save.",
                "conversation_id": "dup-chat-123",
            },
        )
        self.assertFalse(result.ok)
        self.assertIn("similar", result.error.lower())

    def test_record_episode_tool_includes_creation_metadata(self) -> None:
        result = legacy_episode_tool_result(
            "record_episode",
            {
                "title": "Metadata check",
                "summary": "Should have model metadata.",
                "conversation_id": "meta-chat-123",
            },
        )

        self.assertTrue(result.ok)
        recent = list_recent_episodes(limit=5)
        episode = next(ep for ep in recent if ep.title == "Metadata check")
        self.assertEqual(episode.metadata.get("created_by"), "model")
        self.assertEqual(episode.metadata.get("creation_mode"), "auto")

    def test_update_episode_tool_updates_existing_memory_by_title_query(self) -> None:
        original = create_episode(
            title="User passed university courses",
            summary="User passed the semester except math.",
            type="milestone",
            importance=4,
            tags=["education"],
        )
        result = legacy_episode_tool_result(
            "update_episode",
            {
                "title_query": "User passed university courses",
                "summary": "User passed the semester and is celebrating; math was the only stubborn borderline course.",
                "importance": 5,
                "tags": ["education", "achievement"],
            },
        )

        self.assertTrue(result.ok)
        self.assertIn("Updated episode", result.content)
        updated = get_episode(original.id)
        self.assertEqual(updated.summary, "User passed the semester and is celebrating; math was the only stubborn borderline course.")
        self.assertEqual(updated.importance, 5)
        self.assertEqual(updated.tags, ["education", "achievement"])
        self.assertEqual(updated.metadata.get("updated_by"), "model")

    def test_update_episode_tool_rejects_ambiguous_title_query(self) -> None:
        create_episode(title="Course milestone one", summary="First.")
        create_episode(title="Course milestone two", summary="Second.")
        result = legacy_episode_tool_result("update_episode", {"title_query": "Course milestone", "summary": "Updated."})

        self.assertFalse(result.ok)
        self.assertIn("multiple", result.error.lower())

    def test_get_episode_memory_tool_returns_ids_for_cleanup(self) -> None:
        episode = create_episode(title="Scattered memory", summary="A duplicate-like memory.", importance=4)
        result = legacy_episode_tool_result("get_episode_memory", {"query": "Scattered", "limit": 5})

        self.assertTrue(result.ok)
        self.assertIn(episode.id, result.content)
        self.assertIn("Scattered memory", result.content)

    def test_forget_episode_tool_deletes_existing_memory_with_explicit_request(self) -> None:
        episode = create_episode(title="Duplicate old memory", summary="This should be removed.")
        result = legacy_episode_tool_result("forget_episode", {"title_query": "Duplicate old memory", "explicit_user_request": True})

        self.assertTrue(result.ok)
        self.assertIn("Forgot episode", result.content)
        with self.assertRaises(ValueError):
            get_episode(episode.id)

    def test_forget_episode_tool_requires_explicit_user_request(self) -> None:
        create_episode(title="Do not delete automatically", summary="Protected.")
        result = legacy_episode_tool_result("forget_episode", {"title_query": "Do not delete automatically"})

        self.assertFalse(result.ok)
        self.assertIn("explicit_user_request", result.error)

    def test_forget_episode_tool_rejects_ambiguous_title_query(self) -> None:
        create_episode(title="Duplicate cleanup one", summary="First.")
        create_episode(title="Duplicate cleanup two", summary="Second.")
        result = legacy_episode_tool_result("forget_episode", {"title_query": "Duplicate cleanup", "explicit_user_request": True})

        self.assertFalse(result.ok)
        self.assertIn("multiple", result.error.lower())

    def test_tool_registry_includes_memory_tools(self) -> None:
        registry = default_tool_registry()
        self.assertIsNone(registry.definition("get_episode_memory"))
        self.assertIsNone(registry.definition("record_episode"))
        self.assertIsNone(registry.definition("update_episode"))
        self.assertIsNone(registry.definition("forget_episode"))
        self.assertIsNotNone(registry.definition("record_project_memory"))
        self.assertIsNotNone(registry.definition("record_memory"))
        self.assertIsNone(registry.definition("write_memory"))
        self.assertIsNotNone(registry.definition("search_memory"))
        self.assertIsNotNone(registry.definition("update_memory"))
        self.assertIsNotNone(registry.definition("archive_memory"))
        self.assertIsNotNone(registry.definition("list_memory"))
        self.assertIsNotNone(registry.definition("move_memory"))
        self.assertIsNotNone(registry.definition("merge_memory"))


if __name__ == "__main__":
    unittest.main()
