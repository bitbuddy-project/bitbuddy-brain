from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..database import db_connection
from ..paths import GLOBAL_DB_PATH, ensure_app_dirs
from .embeddings import (
    embed_text,
    ensure_embedding_table,
    memory_embedding_text,
    semantic_ranked_ids,
    store_memory_embedding,
    table_exists,
)
from .layers import MemoryLayer, MEMORY_LAYER_DESCRIPTIONS, memory_layer


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    layer: str
    kind: str
    title: str
    summary: str
    importance: int
    created_at: str
    updated_at: str
    archived_at: str | None
    conversation_id: str | None
    project_id: str | None
    emotional_tone: str | None
    source: str | None
    tags: list[str]
    metadata: dict[str, Any]


def ensure_memory_database() -> None:
    ensure_app_dirs()
    with _connection() as connection:
        connection.execute(
            """
            create table if not exists memories (
                id text primary key,
                layer text not null,
                kind text not null default 'memory',
                title text not null,
                summary text not null,
                importance integer not null default 3,
                created_at text default current_timestamp,
                updated_at text default current_timestamp,
                archived_at text,
                conversation_id text,
                project_id text,
                emotional_tone text,
                source text,
                tags text not null default '[]',
                metadata text not null default '{}'
            )
            """
        )
        for column, spec in (
            ("layer", "text not null default 'episodic'"),
            ("kind", "text not null default 'memory'"),
            ("archived_at", "text"),
            ("conversation_id", "text"),
            ("project_id", "text"),
            ("emotional_tone", "text"),
            ("source", "text"),
            ("tags", "text not null default '[]'"),
            ("metadata", "text not null default '{}'"),
        ):
            ensure_column(connection, "memories", column, spec)

        connection.execute("create index if not exists idx_memories_layer on memories(layer, archived_at, updated_at desc)")
        connection.execute("create index if not exists idx_memories_project on memories(project_id, layer, updated_at desc)")
        connection.execute("create index if not exists idx_memories_importance on memories(importance desc, updated_at desc)")

        connection.execute(
            """
            create table if not exists memory_reclassifications (
                id integer primary key autoincrement,
                memory_id text not null,
                previous_layer text not null,
                new_layer text not null,
                reason text not null,
                source text,
                source_metadata text not null default '{}',
                project_id text,
                tags text not null default '[]',
                before_data text not null default '{}',
                after_data text not null default '{}',
                created_at text default current_timestamp
            )
            """
        )
        connection.execute(
            "create index if not exists idx_memory_reclassifications_memory on memory_reclassifications(memory_id, created_at desc)"
        )
        connection.execute(
            """
            create table if not exists memory_merges (
                id integer primary key autoincrement,
                target_memory_id text not null,
                source_memory_ids text not null default '[]',
                reason text not null,
                source text,
                source_metadata text not null default '{}',
                before_data text not null default '{}',
                after_data text not null default '{}',
                created_at text default current_timestamp
            )
            """
        )
        connection.execute("create index if not exists idx_memory_merges_target on memory_merges(target_memory_id, created_at desc)")
        ensure_memory_fts(connection)
        ensure_embedding_table(connection)
        migrate_legacy_episodes(connection)


def create_memory(
    *,
    title: str,
    summary: str,
    layer: str | MemoryLayer,
    kind: str = "memory",
    importance: int = 3,
    conversation_id: str | None = None,
    project_id: str | None = None,
    emotional_tone: str | None = None,
    source: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    memory_id: str | None = None,
    created_at: str | None = None,
    updated_at: str | None = None,
) -> MemoryRecord:
    ensure_memory_database()
    clean_layer = memory_layer(layer).value
    clean_id = memory_id or str(uuid.uuid4())
    now = _iso_now()
    clean_title = title.strip()
    clean_summary = summary.strip()
    if not clean_title:
        raise ValueError("title is required.")
    if not clean_summary:
        raise ValueError("summary is required.")
    with _connection() as connection:
        connection.execute(
            """
            insert into memories (
                id, layer, kind, title, summary, importance, created_at, updated_at,
                conversation_id, project_id, emotional_tone, source, tags, metadata
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(id) do update set
                layer = excluded.layer,
                kind = excluded.kind,
                title = excluded.title,
                summary = excluded.summary,
                importance = excluded.importance,
                updated_at = excluded.updated_at,
                conversation_id = excluded.conversation_id,
                project_id = excluded.project_id,
                emotional_tone = excluded.emotional_tone,
                source = excluded.source,
                tags = excluded.tags,
                metadata = excluded.metadata
            """,
            (
                clean_id,
                clean_layer,
                (kind or "memory").strip() or "memory",
                clean_title,
                clean_summary,
                max(1, min(5, int(importance))),
                created_at or now,
                updated_at or now,
                conversation_id,
                project_id,
                emotional_tone,
                source,
                json.dumps(tags or []),
                json.dumps(metadata or {}),
            ),
        )
        sync_memory_fts(connection, clean_id)
    # Embed outside the write transaction so a slow/dead model never blocks the write.
    try:
        store_memory_embedding(_connection, clean_id, memory_embedding_text(clean_title, clean_summary, tags or []))
    except Exception:
        pass
    return get_memory(clean_id, include_archived=True)


def get_memory(memory_id: str, *, include_archived: bool = False) -> MemoryRecord:
    ensure_memory_database()
    with _connection() as connection:
        row = connection.execute("select * from memories where id = ?", (memory_id,)).fetchone()
    if row is None or (row["archived_at"] and not include_archived):
        raise ValueError(f"Unknown memory: {memory_id}")
    return row_to_memory(row)


def search_memories(
    query: str = "",
    *,
    layer: str | MemoryLayer | None = None,
    project_id: str | None = None,
    limit: int = 10,
    include_archived: bool = False,
) -> list[MemoryRecord]:
    ensure_memory_database()
    clean_layer = memory_layer(layer).value if layer else None
    clean_limit = max(1, min(100, int(limit)))
    clean_query = query.strip()
    # Embed the query before opening the connection so network I/O never holds the db.
    query_vector = embed_text(clean_query) if clean_query else None
    with _connection() as connection:
        if clean_query and fts_available(connection):
            keyword_rows = search_memories_fts(connection, clean_query, clean_layer, project_id, clean_limit, include_archived)
        else:
            keyword_rows = search_memories_fallback(connection, clean_query, clean_layer, project_id, clean_limit, include_archived)
        if query_vector is None:
            return [row_to_memory(row) for row in keyword_rows]
        semantic_ids = semantic_ranked_ids(
            connection, query_vector, clean_layer, project_id, include_archived, clean_limit
        )
        rows = fuse_search_results(connection, keyword_rows, semantic_ids, clean_limit)
    return [row_to_memory(row) for row in rows]


def fuse_search_results(
    connection: sqlite3.Connection,
    keyword_rows: list[sqlite3.Row],
    semantic_ids: list[str],
    limit: int,
) -> list[sqlite3.Row]:
    """Blend keyword and semantic rankings with reciprocal rank fusion (k=60)."""
    if not semantic_ids:
        return keyword_rows[:limit]
    k = 60.0
    scores: dict[str, float] = {}
    rows_by_id: dict[str, sqlite3.Row] = {}
    for rank, row in enumerate(keyword_rows):
        scores[row["id"]] = scores.get(row["id"], 0.0) + 1.0 / (k + rank)
        rows_by_id[row["id"]] = row
    for rank, memory_id in enumerate(semantic_ids):
        scores[memory_id] = scores.get(memory_id, 0.0) + 1.0 / (k + rank)
    missing = [memory_id for memory_id in scores if memory_id not in rows_by_id]
    if missing:
        placeholders = ",".join("?" for _ in missing)
        for row in connection.execute(f"select * from memories where id in ({placeholders})", tuple(missing)).fetchall():
            rows_by_id[row["id"]] = row
    ordered_ids = sorted(scores, key=lambda memory_id: scores[memory_id], reverse=True)
    fused = [rows_by_id[memory_id] for memory_id in ordered_ids if memory_id in rows_by_id]
    return fused[:limit]


def backfill_memory_embeddings(limit: int = 50) -> dict[str, Any]:
    """Embed active memories that have no current-model vector yet. Best-effort, non-fatal."""
    from .embeddings import _client_and_model

    ensure_memory_database()
    client, model = _client_and_model()
    if client is None or not model:
        return {"embedded": 0, "status": "embeddings_unavailable"}
    with _connection() as connection:
        rows = connection.execute(
            """
            select m.id as id, m.title as title, m.summary as summary, m.tags as tags
            from memories m
            left join memory_embeddings me on me.memory_id = m.id and me.model = ?
            where me.memory_id is null and m.archived_at is null
            order by m.importance desc, m.updated_at desc
            limit ?
            """,
            (model, max(1, min(500, int(limit)))),
        ).fetchall()
    embedded = 0
    for row in rows:
        text = memory_embedding_text(row["title"], row["summary"], safe_json(row["tags"], []))
        if store_memory_embedding(_connection, row["id"], text):
            embedded += 1
        else:
            # Provider became unavailable mid-run; stop and let the next cycle retry.
            break
    return {"embedded": embedded, "candidates": len(rows), "model": model}


def update_memory(
    memory_id: str,
    *,
    title: str | None = None,
    summary: str | None = None,
    layer: str | MemoryLayer | None = None,
    kind: str | None = None,
    importance: int | None = None,
    project_id: str | None = None,
    emotional_tone: str | None = None,
    source: str | None = None,
    tags: list[str] | None = None,
    metadata_patch: dict[str, Any] | None = None,
) -> MemoryRecord:
    ensure_memory_database()
    existing = get_memory(memory_id, include_archived=True)
    fields: dict[str, Any] = {"updated_at": _iso_now()}
    if title is not None:
        fields["title"] = title.strip()
    if summary is not None:
        fields["summary"] = summary.strip()
    if layer is not None:
        fields["layer"] = memory_layer(layer).value
    if kind is not None:
        fields["kind"] = kind.strip() or "memory"
    if importance is not None:
        fields["importance"] = max(1, min(5, int(importance)))
    if project_id is not None:
        fields["project_id"] = project_id.strip() or None
    if emotional_tone is not None:
        fields["emotional_tone"] = emotional_tone.strip() or None
    if source is not None:
        fields["source"] = source.strip() or None
    if tags is not None:
        fields["tags"] = json.dumps(tags)
    if metadata_patch:
        fields["metadata"] = json.dumps({**existing.metadata, **metadata_patch})
    if any(key in fields and fields[key] == "" for key in ("title", "summary")):
        raise ValueError("title and summary cannot be empty.")

    assignments = ", ".join(f"{column} = ?" for column in fields)
    with _connection() as connection:
        connection.execute(f"update memories set {assignments} where id = ?", (*fields.values(), memory_id))
        sync_memory_fts(connection, memory_id)
    if any(key in fields for key in ("title", "summary", "tags")):
        try:
            refreshed = get_memory(memory_id, include_archived=True)
            store_memory_embedding(_connection, memory_id, memory_embedding_text(refreshed.title, refreshed.summary, refreshed.tags))
        except Exception:
            pass
    return get_memory(memory_id, include_archived=True)


def archive_memory(memory_id: str, *, reason: str = "", source: str | None = None) -> MemoryRecord:
    ensure_memory_database()
    existing = get_memory(memory_id, include_archived=True)
    metadata = dict(existing.metadata)
    metadata["archived_reason"] = reason
    if source:
        metadata["archived_source"] = source
    with _connection() as connection:
        connection.execute(
            "update memories set archived_at = ?, updated_at = ?, metadata = ? where id = ?",
            (_iso_now(), _iso_now(), json.dumps(metadata), memory_id),
        )
        sync_memory_fts(connection, memory_id)
    return get_memory(memory_id, include_archived=True)


def hard_delete_memory(memory_id: str) -> MemoryRecord:
    ensure_memory_database()
    existing = get_memory(memory_id, include_archived=True)
    with _connection() as connection:
        connection.execute("delete from memories where id = ?", (memory_id,))
        if fts_available(connection):
            connection.execute("delete from memories_fts where memory_id = ?", (memory_id,))
        if table_exists(connection, "memory_embeddings"):
            connection.execute("delete from memory_embeddings where memory_id = ?", (memory_id,))
    return existing


def move_memory(
    memory_id: str,
    *,
    new_layer: str | MemoryLayer,
    reason: str,
    source: str | None = None,
    source_metadata: dict[str, Any] | None = None,
) -> MemoryRecord:
    ensure_memory_database()
    clean_new_layer = memory_layer(new_layer).value
    if not reason.strip():
        raise ValueError("reason is required for memory reclassification.")
    before = get_memory(memory_id, include_archived=True)
    after = update_memory(
        memory_id,
        layer=clean_new_layer,
        metadata_patch={"reclassified_at": _iso_now(), "reclassification_reason": reason.strip()},
    )
    with _connection() as connection:
        connection.execute(
            """
            insert into memory_reclassifications (
                memory_id, previous_layer, new_layer, reason, source, source_metadata,
                project_id, tags, before_data, after_data
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                before.layer,
                after.layer,
                reason.strip(),
                source,
                json.dumps(source_metadata or {}),
                after.project_id,
                json.dumps(after.tags),
                json.dumps(memory_to_json(before), sort_keys=True),
                json.dumps(memory_to_json(after), sort_keys=True),
            ),
        )
    return after


def merge_memories(
    *,
    target_memory_id: str,
    source_memory_ids: list[str],
    reason: str,
    title: str | None = None,
    summary: str | None = None,
    kind: str | None = None,
    tags: list[str] | None = None,
    metadata_patch: dict[str, Any] | None = None,
    source: str | None = None,
    source_metadata: dict[str, Any] | None = None,
) -> MemoryRecord:
    ensure_memory_database()
    clean_sources = [memory_id.strip() for memory_id in source_memory_ids if memory_id.strip() and memory_id.strip() != target_memory_id]
    if not clean_sources:
        raise ValueError("At least one source memory id is required for merge.")
    if not reason.strip():
        raise ValueError("reason is required for memory merge.")

    before_target = get_memory(target_memory_id, include_archived=True)
    before_sources = [get_memory(memory_id, include_archived=True) for memory_id in clean_sources]
    merged_tags = tags if tags is not None else sorted({*before_target.tags, *(tag for memory in before_sources for tag in memory.tags)})
    merged_metadata = {"merged_from": clean_sources, "merge_reason": reason.strip(), **(metadata_patch or {})}

    after = update_memory(
        target_memory_id,
        title=title,
        summary=summary,
        kind=kind,
        tags=merged_tags,
        metadata_patch=merged_metadata,
    )
    archived_sources: list[MemoryRecord] = []
    for memory_id in clean_sources:
        archived_sources.append(archive_memory(memory_id, reason=f"Merged into {target_memory_id}: {reason}", source=source or "memory_merge"))

    with _connection() as connection:
        connection.execute(
            """
            insert into memory_merges (
                target_memory_id, source_memory_ids, reason, source, source_metadata,
                before_data, after_data
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                target_memory_id,
                json.dumps(clean_sources),
                reason.strip(),
                source,
                json.dumps(source_metadata or {}),
                json.dumps(
                    {
                        "target": memory_to_json(before_target),
                        "sources": [memory_to_json(memory) for memory in before_sources],
                    },
                    sort_keys=True,
                ),
                json.dumps(
                    {
                        "target": memory_to_json(after),
                        "archived_sources": [memory_to_json(memory) for memory in archived_sources],
                    },
                    sort_keys=True,
                ),
            ),
        )
    return after


def layered_memory_context(
    *,
    query: str = "",
    project_id: str | None = None,
    max_chars: int = 2400,
) -> str:
    ensure_memory_database()
    selected: list[MemoryRecord] = []
    seen: set[str] = set()

    for layer in (MemoryLayer.SELF, MemoryLayer.RELATIONSHIP):
        for memory in search_memories(layer=layer, limit=3):
            if memory.id not in seen:
                selected.append(memory)
                seen.add(memory.id)

    if query.strip():
        for layer in (MemoryLayer.EPISODIC, MemoryLayer.SEMANTIC, MemoryLayer.PROCEDURAL):
            for memory in search_memories(query=query, layer=layer, limit=3):
                if memory.id not in seen:
                    selected.append(memory)
                    seen.add(memory.id)
        project_limit = 3 if project_id else 2
        for memory in search_memories(query=query, layer=MemoryLayer.PROJECT, project_id=project_id, limit=project_limit):
            if memory.id not in seen:
                selected.append(memory)
                seen.add(memory.id)
        if not selected and memory_recall_query(query):
            for memory in search_memories(layer=MemoryLayer.EPISODIC, limit=3):
                if memory.id not in seen:
                    selected.append(memory)
                    seen.add(memory.id)
    elif project_id:
        for memory in search_memories(layer=MemoryLayer.PROJECT, project_id=project_id, limit=3):
            if memory.id not in seen:
                selected.append(memory)
                seen.add(memory.id)

    if not selected:
        return ""

    lines = ["[Relevant Layered Memories]", "Bounded memory context. Current user message wins over old memory.", ""]
    for memory in selected:
        tags = f" tags={memory.tags}" if memory.tags else ""
        project = f" project_id={memory.project_id}" if memory.project_id else ""
        lines.append(
            f"- layer={memory.layer} id {memory.id} kind={memory.kind} importance={memory.importance}{tags}{project}\n"
            f"  {memory.title}: {memory.summary}"
        )

    content = "\n".join(lines)
    if len(content) > max_chars:
        content = content[:max_chars].rstrip() + "\n..."
    return content


def memory_recall_query(query: str) -> bool:
    text = query.lower()
    return any(
        marker in text
        for marker in (
            "remember",
            "what do you know",
            "what do you remember",
            "where did we leave off",
            "left off",
            "pick up where",
        )
    )


def memory_to_json(memory: MemoryRecord) -> dict[str, Any]:
    return asdict(memory)


def get_reclassification_history(memory_id: str) -> list[dict[str, Any]]:
    ensure_memory_database()
    with _connection() as connection:
        rows = connection.execute(
            "select * from memory_reclassifications where memory_id = ? order by created_at desc, id desc",
            (memory_id,),
        ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key in ("source_metadata", "tags", "before_data", "after_data"):
            item[key] = safe_json(item.get(key), {} if key != "tags" else [])
        result.append(item)
    return result


def migrate_legacy_episodes(connection: sqlite3.Connection) -> None:
    exists = connection.execute(
        "select 1 from sqlite_master where type = 'table' and name = 'episodes'"
    ).fetchone()
    if not exists:
        return
    rows = connection.execute("select * from episodes").fetchall()
    for row in rows:
        if connection.execute("select 1 from memories where id = ?", (row["id"],)).fetchone():
            continue
        metadata = safe_json(row["metadata"], {})
        migrated_metadata = {**metadata, "migrated_from": "episodes"}
        layer = infer_legacy_episode_layer(row)
        connection.execute(
            """
            insert into memories (
                id, layer, kind, title, summary, importance, created_at, updated_at,
                conversation_id, project_id, emotional_tone, source, tags, metadata
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                layer,
                row["type"] or "episode",
                row["title"],
                row["summary"],
                row["importance"],
                row["created_at"],
                row["updated_at"],
                row["conversation_id"],
                row["project_id"],
                row["emotional_tone"],
                row["source"],
                row["tags"],
                json.dumps(migrated_metadata),
            ),
        )
        sync_memory_fts(connection, row["id"])


def infer_legacy_episode_layer(row: sqlite3.Row) -> str:
    title = str(row["title"] or "")
    summary = str(row["summary"] or "")
    kind = str(row["type"] or "").lower()
    tags = [str(tag).lower() for tag in safe_json(row["tags"], [])]
    metadata = safe_json(row["metadata"], {})
    explicit_layer = metadata.get("layer")
    if isinstance(explicit_layer, str) and explicit_layer.strip():
        try:
            return memory_layer(explicit_layer).value
        except ValueError:
            pass
    if kind in {"semantic", "procedural", "self", "relationship"}:
        return memory_layer(kind).value
    if "semantic" in tags or "procedural" in tags or "self" in tags or "relationship" in tags:
        for candidate in ("self", "relationship", "procedural", "semantic"):
            if candidate in tags:
                return candidate

    text = f"{title}\n{summary}".lower()
    if any(name in text for name in ("vanta", "bitbuddy")) and any(
        marker in text for marker in ("identity", "personality", "presentation", "pronoun", "quirk", "self-concept", "name")
    ):
        return MemoryLayer.SELF.value
    if re.search(r"\b(?:dustin|user)\s+(?:prefers|wants|dislikes|likes|asked vanta|trusts|expects)\b", text):
        return MemoryLayer.RELATIONSHIP.value
    return MemoryLayer.EPISODIC.value


def ensure_memory_fts(connection: sqlite3.Connection) -> None:
    try:
        connection.execute(
            """
            create virtual table if not exists memories_fts using fts5(
                memory_id unindexed,
                title,
                summary,
                tags,
                metadata
            )
            """
        )
    except sqlite3.Error:
        connection.execute("create table if not exists memory_fts_unavailable (id integer primary key check (id = 1))")


def fts_available(connection: sqlite3.Connection) -> bool:
    try:
        row = connection.execute(
            "select 1 from sqlite_master where type = 'table' and name = 'memories_fts'"
        ).fetchone()
        return row is not None
    except sqlite3.Error:
        return False


def sync_memory_fts(connection: sqlite3.Connection, memory_id: str) -> None:
    if not fts_available(connection):
        return
    try:
        connection.execute("delete from memories_fts where memory_id = ?", (memory_id,))
        row = connection.execute("select title, summary, tags, metadata from memories where id = ?", (memory_id,)).fetchone()
        if row:
            connection.execute(
                "insert into memories_fts (memory_id, title, summary, tags, metadata) values (?, ?, ?, ?, ?)",
                (memory_id, row["title"], row["summary"], row["tags"], row["metadata"]),
            )
    except sqlite3.Error:
        return


def search_memories_fts(
    connection: sqlite3.Connection,
    query: str,
    layer: str | None,
    project_id: str | None,
    limit: int,
    include_archived: bool,
) -> list[sqlite3.Row]:
    match_query = fts_query(query)
    if not match_query:
        return search_memories_fallback(connection, query, layer, project_id, limit, include_archived)
    where = ["memories_fts match ?"]
    params: list[Any] = [match_query]
    if layer:
        where.append("m.layer = ?")
        params.append(layer)
    if project_id:
        where.append("m.project_id = ?")
        params.append(project_id)
    if not include_archived:
        where.append("m.archived_at is null")
    params.append(limit)
    sql = f"""
        select m.* from memories_fts f
        join memories m on m.id = f.memory_id
        where {' and '.join(where)}
        order by bm25(memories_fts), m.importance desc, m.updated_at desc
        limit ?
    """
    try:
        return connection.execute(sql, tuple(params)).fetchall()
    except sqlite3.Error:
        return search_memories_fallback(connection, query, layer, project_id, limit, include_archived)


def search_memories_fallback(
    connection: sqlite3.Connection,
    query: str,
    layer: str | None,
    project_id: str | None,
    limit: int,
    include_archived: bool,
) -> list[sqlite3.Row]:
    where: list[str] = []
    params: list[Any] = []
    if query.strip():
        pattern = f"%{query.strip()}%"
        where.append("(title like ? or summary like ? or tags like ? or metadata like ?)")
        params.extend([pattern, pattern, pattern, pattern])
    if layer:
        where.append("layer = ?")
        params.append(layer)
    if project_id:
        where.append("project_id = ?")
        params.append(project_id)
    if not include_archived:
        where.append("archived_at is null")
    clause = " where " + " and ".join(where) if where else ""
    params.append(limit)
    return connection.execute(
        f"select * from memories{clause} order by importance desc, updated_at desc limit ?",
        tuple(params),
    ).fetchall()


def fts_query(query: str) -> str:
    terms = re.findall(r"[A-Za-z0-9_]+", query.lower())
    if not terms:
        return ""
    return " OR ".join(f"{term}*" for term in terms[:8])


def ensure_column(connection: sqlite3.Connection, table: str, column: str, spec: str) -> None:
    columns = {row[1] for row in connection.execute(f"pragma table_info({table})")}
    if column not in columns:
        connection.execute(f"alter table {table} add column {column} {spec}")


def row_to_memory(row: sqlite3.Row) -> MemoryRecord:
    return MemoryRecord(
        id=row["id"],
        layer=row["layer"],
        kind=row["kind"],
        title=row["title"],
        summary=row["summary"],
        importance=int(row["importance"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        archived_at=row["archived_at"] or None,
        conversation_id=row["conversation_id"] or None,
        project_id=row["project_id"] or None,
        emotional_tone=row["emotional_tone"] or None,
        source=row["source"] or None,
        tags=safe_json(row["tags"], []),
        metadata=safe_json(row["metadata"], {}),
    )


def safe_json(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value or json.dumps(fallback))
    except (TypeError, json.JSONDecodeError):
        return fallback
    if isinstance(fallback, list):
        return parsed if isinstance(parsed, list) else fallback
    if isinstance(fallback, dict):
        return parsed if isinstance(parsed, dict) else fallback
    return parsed


def _connection():
    return db_connection(GLOBAL_DB_PATH, row_factory=sqlite3.Row)


def _iso_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
