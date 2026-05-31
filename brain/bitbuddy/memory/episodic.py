from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any

from ..database import db_connection
from ..paths import GLOBAL_DB_PATH, ensure_app_dirs
from .layers import MemoryLayer
from .store import (
    create_memory,
    get_memory,
    hard_delete_memory,
    search_memories,
    update_memory,
    ensure_column,
    ensure_memory_database,
)


@dataclass(frozen=True)
class Episode:
    id: str
    created_at: str
    updated_at: str
    conversation_id: str | None
    project_id: str | None
    type: str
    title: str
    summary: str
    importance: int
    emotional_tone: str | None
    source: str | None
    tags: list[str]
    metadata: dict[str, Any]


def ensure_episodic_memory_database() -> None:
    ensure_app_dirs()
    with db_connection(GLOBAL_DB_PATH) as connection:
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
            """
            create index if not exists idx_episodes_updated_at
            on episodes(updated_at desc)
            """
        )
        connection.execute(
            """
            create index if not exists idx_episodes_importance
            on episodes(importance desc)
            """
        )
        ensure_column(connection, "episodes", "layer", "text not null default 'episodic'")
        ensure_column(connection, "episodes", "kind", "text not null default 'episode'")
    ensure_memory_database()


def create_episode(
    title: str,
    summary: str,
    type: str = "episode",
    importance: int = 3,
    conversation_id: str | None = None,
    project_id: str | None = None,
    emotional_tone: str | None = None,
    source: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Episode:
    ensure_episodic_memory_database()
    episode_id = str(uuid.uuid4())
    now = _iso_now()
    clean_tags = tags or []
    clean_metadata = metadata or {}

    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            insert into episodes (
                id, created_at, updated_at, conversation_id, project_id,
                type, title, summary, importance, emotional_tone, source, tags, metadata
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                episode_id,
                now,
                now,
                conversation_id,
                project_id,
                type,
                title.strip(),
                summary.strip(),
                importance,
                emotional_tone,
                source,
                json.dumps(clean_tags),
                json.dumps(clean_metadata),
            ),
        )

    create_memory(
        memory_id=episode_id,
        layer=MemoryLayer.EPISODIC,
        kind=type,
        title=title,
        summary=summary,
        importance=importance,
        conversation_id=conversation_id,
        project_id=project_id,
        emotional_tone=emotional_tone,
        source=source,
        tags=clean_tags,
        metadata=clean_metadata,
        created_at=now,
        updated_at=now,
    )

    return get_episode(episode_id)


def get_episode(episode_id: str) -> Episode:
    ensure_episodic_memory_database()
    try:
        memory = get_memory(episode_id, include_archived=False)
    except ValueError:
        with _episodic_connection() as connection:
            row = connection.execute(
                "select * from episodes where id = ?",
                (episode_id,),
            ).fetchone()
        if row is None:
            raise ValueError(f"Unknown episode: {episode_id}")
        return _row_to_episode(row)
    if memory.layer != MemoryLayer.EPISODIC.value:
        raise ValueError(f"Memory is not episodic: {episode_id}")
    return _memory_to_episode(memory)


def delete_episode(episode_id: str) -> Episode:
    ensure_episodic_memory_database()
    existing = get_episode(episode_id)
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute("delete from episodes where id = ?", (episode_id,))
    try:
        hard_delete_memory(episode_id)
    except ValueError:
        pass
    return existing


def update_episode(
    episode_id: str,
    *,
    title: str | None = None,
    summary: str | None = None,
    type: str | None = None,
    importance: int | None = None,
    project_id: str | None = None,
    emotional_tone: str | None = None,
    tags: list[str] | None = None,
    metadata_patch: dict[str, Any] | None = None,
) -> Episode:
    ensure_episodic_memory_database()
    existing = get_episode(episode_id)

    fields: dict[str, Any] = {"updated_at": _iso_now()}
    if title is not None:
        fields["title"] = title.strip()
    if summary is not None:
        fields["summary"] = summary.strip()
    if type is not None:
        fields["type"] = type.strip() or "episode"
    if importance is not None:
        fields["importance"] = importance
    if project_id is not None:
        fields["project_id"] = project_id.strip() or None
    if emotional_tone is not None:
        fields["emotional_tone"] = emotional_tone.strip() or None
    if tags is not None:
        fields["tags"] = json.dumps(tags)
    if metadata_patch:
        fields["metadata"] = json.dumps({**existing.metadata, **metadata_patch})

    if not fields:
        return existing

    assignments = ", ".join(f"{column} = ?" for column in fields)
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            f"update episodes set {assignments} where id = ?",
            (*fields.values(), episode_id),
        )

    update_memory(
        episode_id,
        title=title,
        summary=summary,
        kind=type,
        importance=importance,
        project_id=project_id,
        emotional_tone=emotional_tone,
        tags=tags,
        metadata_patch=metadata_patch,
    )

    return get_episode(episode_id)


def list_recent_episodes(limit: int = 10) -> list[Episode]:
    ensure_episodic_memory_database()
    return [_memory_to_episode(memory) for memory in search_memories(layer=MemoryLayer.EPISODIC, limit=limit)]


def search_episodes(query: str, limit: int = 10) -> list[Episode]:
    ensure_episodic_memory_database()
    return [_memory_to_episode(memory) for memory in search_memories(query=query, layer=MemoryLayer.EPISODIC, limit=limit)]


def count_auto_episodes_for_conversation(conversation_id: str) -> int:
    """Count model-auto-created episodes for a conversation."""
    ensure_episodic_memory_database()
    with _episodic_connection() as connection:
        row = connection.execute(
            """
            select count(*) from memories
            where conversation_id = ?
              and layer = 'episodic'
              and metadata like '%"created_by": "model"%'
              and metadata like '%"creation_mode": "auto"%'
            """,
            (conversation_id,),
        ).fetchone()
    return row[0] if row else 0


def episodic_memory_context(
    query: str = "",
    limit: int = 4,
    max_chars: int = 1600,
    include_baseline: bool = False,
    baseline_limit: int = 3,
) -> str:
    """Build a bounded episodic memory block for prompt injection."""
    episodes: list[Episode] = []
    if query.strip():
        episodes = search_episodes(query, limit=limit)

    if include_baseline:
        seen = {episode.id for episode in episodes}
        for episode in list_recent_episodes(limit=baseline_limit):
            if episode.id in seen:
                continue
            episodes.append(episode)
            seen.add(episode.id)

    if not episodes:
        episodes = list_recent_episodes(limit=limit)

    if not episodes:
        return ""

    lines: list[str] = []
    for episode in episodes:
        tag_str = f" [{', '.join(episode.tags)}]" if episode.tags else ""
        project_str = f" (project: {episode.project_id})" if episode.project_id else ""
        lines.append(
            f"- {episode.title}{tag_str}{project_str} (id {episode.id}, importance {episode.importance}): {episode.summary}"
        )

    content = "\n".join(lines)
    if len(content) > max_chars:
        content = content[:max_chars].rstrip() + "\n..."

    return "\n".join(
        [
            "[Relevant Episodic Memories]",
            "Distilled remembered episodes from prior interactions. Use as context; current user message always wins.",
            "",
            content,
        ]
    )


def _episodic_connection():
    return db_connection(GLOBAL_DB_PATH, row_factory=sqlite3.Row)


def _row_to_episode(row: sqlite3.Row) -> Episode:
    tags = _safe_json_list(row["tags"])
    metadata = _safe_json_dict(row["metadata"])
    return Episode(
        id=row["id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        conversation_id=row["conversation_id"] or None,
        project_id=row["project_id"] or None,
        type=row["type"],
        title=row["title"],
        summary=row["summary"],
        importance=row["importance"],
        emotional_tone=row["emotional_tone"] or None,
        source=row["source"] or None,
        tags=tags,
        metadata=metadata,
    )


def _memory_to_episode(memory: Any) -> Episode:
    return Episode(
        id=memory.id,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
        conversation_id=memory.conversation_id,
        project_id=memory.project_id,
        type=memory.kind,
        title=memory.title,
        summary=memory.summary,
        importance=memory.importance,
        emotional_tone=memory.emotional_tone,
        source=memory.source,
        tags=memory.tags,
        metadata=memory.metadata,
    )


def _safe_json_list(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _safe_json_dict(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _iso_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
