from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .database import db_connection
from .paths import GLOBAL_DB_PATH, ensure_app_dirs


ACTIVE_SELF_NOTE_STATUSES = {"active"}


@dataclass(frozen=True)
class SelfNote:
    id: str
    text: str
    kind: str
    priority: int
    created_at: str
    expires_at: str | None
    remaining_injections: int | None
    injection_policy: str
    status: str
    source: str
    topic: str
    project_id: str
    metadata: dict[str, Any]


def ensure_self_notes_database() -> None:
    ensure_app_dirs()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            create table if not exists self_notes (
                id text primary key,
                text text not null,
                kind text not null default 'reminder',
                priority integer not null default 3,
                created_at text default current_timestamp,
                expires_at text,
                remaining_injections integer,
                injection_policy text not null default 'next_chat_once',
                status text not null default 'active',
                source text not null default 'chat_consolidation',
                topic text not null default '',
                project_id text not null default '',
                metadata text not null default '{}'
            )
            """
        )
        connection.execute("create index if not exists idx_self_notes_status on self_notes(status, priority desc, created_at desc)")
        connection.execute("create index if not exists idx_self_notes_project on self_notes(project_id, status, priority desc)")


def create_self_note(
    text: str,
    *,
    kind: str = "reminder",
    priority: int = 3,
    expires_at: str | None = None,
    remaining_injections: int | None = None,
    injection_policy: str = "next_chat_once",
    source: str = "chat_consolidation",
    topic: str = "",
    project_id: str = "",
    metadata: dict[str, Any] | None = None,
    note_id: str | None = None,
) -> SelfNote:
    clean_text = text.strip()
    if not clean_text:
        raise ValueError("text is required.")
    ensure_self_notes_database()
    clean_id = note_id or str(uuid.uuid4())
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            insert into self_notes (
                id, text, kind, priority, expires_at, remaining_injections,
                injection_policy, status, source, topic, project_id, metadata
            ) values (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
            """,
            (
                clean_id,
                clean_text,
                kind.strip() or "reminder",
                max(1, min(5, int(priority))),
                expires_at,
                remaining_injections,
                injection_policy.strip() or "next_chat_once",
                source.strip() or "chat_consolidation",
                topic.strip(),
                project_id.strip(),
                json.dumps(metadata or {}),
            ),
        )
    return get_self_note(clean_id)


def get_self_note(note_id: str) -> SelfNote:
    ensure_self_notes_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute("select * from self_notes where id = ?", (note_id,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown self note: {note_id}")
    return self_note_from_row(row)


def list_self_notes(status: str = "active", limit: int = 20) -> list[SelfNote]:
    ensure_self_notes_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            """
            select * from self_notes
            where status = ?
            order by priority desc, created_at desc
            limit ?
            """,
            (status, max(1, min(100, int(limit)))),
        ).fetchall()
    return [self_note_from_row(row) for row in rows]


def select_self_notes_for_context(
    *,
    query: str = "",
    project_id: str = "",
    limit: int = 3,
    mark_injected: bool = False,
) -> list[SelfNote]:
    cleanup_self_notes()
    query_terms = set(normalize_words(query))
    selected: list[SelfNote] = []
    for note in list_self_notes(limit=50):
        if note.project_id and project_id and note.project_id != project_id:
            continue
        if note.topic:
            topic_terms = set(normalize_words(note.topic))
            if query_terms and topic_terms and not query_terms.intersection(topic_terms):
                continue
        selected.append(note)
        if len(selected) >= limit:
            break
    if mark_injected:
        for note in selected:
            mark_self_note_injected(note.id)
    return selected


def mark_self_note_injected(note_id: str) -> None:
    note = get_self_note(note_id)
    remaining = note.remaining_injections
    status = note.status
    if remaining is not None:
        remaining = max(0, remaining - 1)
        if remaining == 0:
            status = "injected"
    elif note.injection_policy == "next_chat_once":
        status = "injected"
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            "update self_notes set remaining_injections = ?, status = ? where id = ?",
            (remaining, status, note_id),
        )


def cleanup_self_notes(now: datetime | None = None) -> int:
    ensure_self_notes_database()
    current = (now or datetime.now(timezone.utc)).replace(microsecond=0).isoformat()
    with db_connection(GLOBAL_DB_PATH) as connection:
        cursor = connection.execute(
            """
            update self_notes
            set status = 'expired'
            where status = 'active'
              and expires_at is not null
              and expires_at != ''
              and expires_at <= ?
            """,
            (current,),
        )
        return cursor.rowcount


def self_note_to_json(note: SelfNote) -> dict[str, Any]:
    return {
        "id": note.id,
        "text": note.text,
        "kind": note.kind,
        "priority": note.priority,
        "created_at": note.created_at,
        "expires_at": note.expires_at,
        "remaining_injections": note.remaining_injections,
        "injection_policy": note.injection_policy,
        "status": note.status,
        "source": note.source,
        "topic": note.topic,
        "project_id": note.project_id,
        "metadata": note.metadata,
    }


def self_note_from_row(row: Any) -> SelfNote:
    try:
        metadata = json.loads(row[12] or "{}")
    except json.JSONDecodeError:
        metadata = {}
    return SelfNote(
        id=str(row[0]),
        text=str(row[1]),
        kind=str(row[2] or "reminder"),
        priority=int(row[3] or 3),
        created_at=str(row[4] or ""),
        expires_at=str(row[5]) if row[5] else None,
        remaining_injections=int(row[6]) if row[6] is not None else None,
        injection_policy=str(row[7] or "next_chat_once"),
        status=str(row[8] or "active"),
        source=str(row[9] or "chat_consolidation"),
        topic=str(row[10] or ""),
        project_id=str(row[11] or ""),
        metadata=metadata if isinstance(metadata, dict) else {},
    )


def normalize_words(text: str) -> list[str]:
    return [word for word in "".join(char.lower() if char.isalnum() else " " for char in text).split() if len(word) > 2]
