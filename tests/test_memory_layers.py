from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-memory-layers-test-")

from bitbuddy.memory.layers import MEMORY_LAYER_VALUES, MemoryLayer, memory_layer
from bitbuddy.memory.store import (
    create_memory,
    ensure_memory_database,
    get_memory,
    get_reclassification_history,
    memory_to_json,
    merge_memories,
    move_memory,
    search_memories,
)
from bitbuddy.paths import GLOBAL_DB_PATH
from bitbuddy.tools import ToolCall, ToolExecutor, default_tool_registry, tool_instruction_message


class MemoryLayerTest(unittest.TestCase):
    def setUp(self) -> None:
        ensure_memory_database()
        with closing(sqlite3.connect(GLOBAL_DB_PATH)) as connection, connection:
            connection.execute("delete from memory_reclassifications")
            connection.execute("delete from memory_merges")
            connection.execute("delete from memories")
            try:
                connection.execute("delete from memories_fts")
            except sqlite3.Error:
                pass
            if connection.execute("select 1 from sqlite_master where type = 'table' and name = 'episodes'").fetchone():
                connection.execute("delete from episodes")

    def test_canonical_layers_reject_preference_layer(self) -> None:
        self.assertEqual(
            set(MEMORY_LAYER_VALUES),
            {"episodic", "semantic", "project", "procedural", "self", "relationship"},
        )
        with self.assertRaises(ValueError):
            memory_layer("preference")

    def test_write_and_read_each_layer(self) -> None:
        for layer in MemoryLayer:
            memory = create_memory(
                layer=layer,
                kind="preference" if layer == MemoryLayer.RELATIONSHIP else "fact",
                title=f"{layer.value} title",
                summary=f"Durable {layer.value} summary",
                tags=["preference"] if layer == MemoryLayer.RELATIONSHIP else [layer.value],
            )
            fetched = get_memory(memory.id)
            self.assertEqual(fetched.layer, layer.value)
            self.assertEqual(fetched.title, f"{layer.value} title")

    def test_search_by_each_layer(self) -> None:
        for layer in MemoryLayer:
            create_memory(layer=layer, title=f"Needle {layer.value}", summary="Layer-specific durable fact")

        for layer in MemoryLayer:
            results = search_memories("Needle", layer=layer, limit=10)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].layer, layer.value)

    def test_move_memory_preserves_id_and_metadata_with_audit(self) -> None:
        memory = create_memory(
            layer=MemoryLayer.EPISODIC,
            kind="fact",
            title="Halley description",
            summary="Halley is a Wayland compositor.",
            project_id="halley-123",
            tags=["project", "fact"],
            metadata={"source_tool": "read_file"},
        )

        moved = move_memory(
            memory.id,
            new_layer=MemoryLayer.SEMANTIC,
            reason="This is a durable factual statement, not a specific event.",
            source="unit_test",
            source_metadata={"confidence": "high"},
        )

        self.assertEqual(moved.id, memory.id)
        self.assertEqual(moved.layer, "semantic")
        self.assertEqual(moved.project_id, "halley-123")
        self.assertEqual(moved.tags, ["project", "fact"])
        self.assertEqual(moved.metadata.get("source_tool"), "read_file")
        history = get_reclassification_history(memory.id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["previous_layer"], "episodic")
        self.assertEqual(history[0]["new_layer"], "semantic")
        self.assertEqual(history[0]["project_id"], "halley-123")
        self.assertEqual(history[0]["tags"], ["project", "fact"])
        self.assertEqual(history[0]["before_data"]["layer"], "episodic")
        self.assertEqual(history[0]["after_data"]["layer"], "semantic")

    def test_generic_tools_write_search_update_archive_move_and_merge(self) -> None:
        executor = ToolExecutor(default_tool_registry())
        write = executor.execute(
            ToolCall(
                tool="record_memory",
                arguments={
                    "layer": "relationship",
                    "kind": "preference",
                    "title": "Dustin likes concise replies",
                    "summary": "Dustin prefers concise replies unless he asks for depth.",
                    "tags": ["preference", "tone"],
                    "importance": 4,
                },
            )
        )
        self.assertTrue(write.ok, write.error)
        memory_id = json.loads(write.content)["id"]

        search = executor.execute(ToolCall(tool="search_memory", arguments={"query": "concise", "layer": "relationship"}))
        self.assertTrue(search.ok, search.error)
        self.assertIn(memory_id, search.content)

        update = executor.execute(ToolCall(tool="update_memory", arguments={"memory_id": memory_id, "importance": 5}))
        self.assertTrue(update.ok, update.error)
        self.assertEqual(get_memory(memory_id).importance, 5)

        moved = executor.execute(
            ToolCall(
                tool="move_memory",
                arguments={"memory_id": memory_id, "new_layer": "procedural", "reason": "Testing reclassification audit."},
            )
        )
        self.assertTrue(moved.ok, moved.error)
        self.assertEqual(get_memory(memory_id).layer, "procedural")

        duplicate = create_memory(
            layer="procedural",
            kind="preference",
            title="Concise replies duplicate",
            summary="Dustin likes short direct replies.",
            tags=["tone"],
        )
        merged = executor.execute(
            ToolCall(
                tool="merge_memory",
                arguments={
                    "target_memory_id": memory_id,
                    "source_memory_ids": [duplicate.id],
                    "reason": "Duplicate preference wording.",
                    "summary": "Dustin prefers concise replies unless he asks for depth.",
                },
            )
        )
        self.assertTrue(merged.ok, merged.error)
        self.assertIsNotNone(get_memory(duplicate.id, include_archived=True).archived_at)

        archived = executor.execute(ToolCall(tool="archive_memory", arguments={"memory_id": memory_id, "reason": "Test cleanup."}))
        self.assertTrue(archived.ok, archived.error)
        self.assertIsNotNone(get_memory(memory_id, include_archived=True).archived_at)

    def test_prompt_exposes_all_layers_and_preference_not_layer(self) -> None:
        content = tool_instruction_message(default_tool_registry())["content"]
        for layer in MEMORY_LAYER_VALUES:
            self.assertIn(layer, content)
        self.assertIn("Preference is not a top-level MemoryLayer", content)
        self.assertIn("record_memory creates canonical memories", content)
        self.assertNotIn("write_memory creates canonical memories", content)
        self.assertIn("If it happened once at a specific time/conversation", content)
        self.assertIn("If it is a reusable method", content)

    def test_conservative_legacy_episode_migration(self) -> None:
        with closing(sqlite3.connect(GLOBAL_DB_PATH)) as connection, connection:
            connection.execute(
                """
                create table if not exists episodes (
                    id text primary key,
                    created_at text default current_timestamp,
                    updated_at text default current_timestamp,
                    conversation_id text,
                    project_id text,
                    type text not null default 'episode',
                    title text not null,
                    summary text not null,
                    importance integer not null default 3,
                    emotional_tone text,
                    source text,
                    tags text not null default '[]',
                    metadata text not null default '{}'
                )
                """
            )
            connection.execute(
                "insert into episodes (id, type, title, summary, tags, metadata) values (?, ?, ?, ?, ?, ?)",
                ("event-1", "episode", "README chat", "Dustin asked about Halley on May 12.", "[]", "{}"),
            )
            connection.execute(
                "insert into episodes (id, type, title, summary, tags, metadata) values (?, ?, ?, ?, ?, ?)",
                ("relationship-1", "episode", "Dustin prefers concise answers", "Dustin prefers concise answers from Vanta.", "[]", "{}"),
            )

        ensure_memory_database()

        self.assertEqual(get_memory("event-1").layer, "episodic")
        self.assertEqual(get_memory("relationship-1").layer, "relationship")


if __name__ == "__main__":
    unittest.main()
