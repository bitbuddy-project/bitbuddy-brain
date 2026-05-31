from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any

from .database import db_connection
from .paths import GLOBAL_DB_PATH, ensure_app_dirs


@dataclass(frozen=True)
class Notification:
    id: int
    category: str
    severity: str
    title: str
    body: str
    source_kind: str
    chat_id: str
    action_url: str
    metadata: dict[str, Any]
    created_at: str
    read_at: str | None
    dismissed_at: str | None


def ensure_notification_database() -> None:
    ensure_app_dirs()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            create table if not exists notifications (
                id integer primary key autoincrement,
                category text not null,
                severity text not null default 'info',
                title text not null,
                body text not null,
                source_kind text not null default '',
                chat_id text not null default '',
                action_url text not null default '',
                metadata text not null default '{}',
                created_at text default current_timestamp,
                read_at text,
                dismissed_at text
            )
            """
        )
        connection.execute("create index if not exists idx_notifications_id on notifications(id)")
        connection.execute("create index if not exists idx_notifications_read on notifications(read_at, dismissed_at)")


def create_notification(
    *,
    category: str,
    title: str,
    body: str,
    severity: str = "info",
    source_kind: str = "",
    chat_id: str = "",
    action_url: str = "",
    metadata: dict[str, Any] | None = None,
) -> Notification:
    ensure_notification_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        cursor = connection.execute(
            """
            insert into notifications (category, severity, title, body, source_kind, chat_id, action_url, metadata)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_text(category, "system", 80),
                clean_text(severity, "info", 40),
                clean_text(title, "Notification", 160),
                clean_text(body, "", 800),
                clean_text(source_kind, "", 120),
                clean_text(chat_id, "", 120),
                clean_text(action_url, "", 300),
                json.dumps(metadata or {}),
            ),
        )
        notification_id = int(cursor.lastrowid)
    return get_notification(notification_id)


def notify_user(**kwargs: Any) -> Notification | None:
    try:
        return create_notification(**kwargs)
    except Exception as error:
        print(f"BitBuddy notification failed: {error}", file=sys.stderr)
        return None


def get_notification(notification_id: int) -> Notification:
    ensure_notification_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute(
            """
            select id, category, severity, title, body, source_kind, chat_id, action_url, metadata, created_at, read_at, dismissed_at
            from notifications
            where id = ?
            """,
            (notification_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"Unknown notification: {notification_id}")
    return notification_from_row(row)


def list_notifications(after_id: int = 0, limit: int = 50, include_dismissed: bool = False) -> list[Notification]:
    ensure_notification_database()
    clean_limit = max(1, min(100, int(limit)))
    clauses = []
    parameters: list[Any] = []
    if after_id > 0:
        clauses.append("id > ?")
        parameters.append(after_id)
    if not include_dismissed:
        clauses.append("dismissed_at is null")
    where = f"where {' and '.join(clauses)}" if clauses else ""
    order = "asc" if after_id > 0 else "desc"
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            f"""
            select id, category, severity, title, body, source_kind, chat_id, action_url, metadata, created_at, read_at, dismissed_at
            from notifications
            {where}
            order by id {order}
            limit ?
            """,
            (*parameters, clean_limit),
        ).fetchall()
    return [notification_from_row(row) for row in rows]


def unread_notification_count() -> int:
    ensure_notification_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute("select count(*) from notifications where read_at is null and dismissed_at is null").fetchone()
    return int(row[0] or 0) if row else 0


def mark_notification_read(notification_id: int) -> bool:
    ensure_notification_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        cursor = connection.execute(
            "update notifications set read_at = coalesce(read_at, current_timestamp) where id = ? and dismissed_at is null",
            (notification_id,),
        )
    return bool(cursor.rowcount)


def mark_all_notifications_read() -> int:
    ensure_notification_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        cursor = connection.execute("update notifications set read_at = current_timestamp where read_at is null and dismissed_at is null")
    return int(cursor.rowcount or 0)


def dismiss_notification(notification_id: int) -> bool:
    ensure_notification_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        cursor = connection.execute(
            "update notifications set dismissed_at = coalesce(dismissed_at, current_timestamp), read_at = coalesce(read_at, current_timestamp) where id = ?",
            (notification_id,),
        )
    return bool(cursor.rowcount)


def notification_to_json(notification: Notification) -> dict[str, Any]:
    return {
        "id": notification.id,
        "category": notification.category,
        "severity": notification.severity,
        "title": notification.title,
        "body": notification.body,
        "source_kind": notification.source_kind,
        "chat_id": notification.chat_id,
        "action_url": notification.action_url,
        "metadata": notification.metadata,
        "created_at": notification.created_at,
        "read_at": notification.read_at,
        "dismissed_at": notification.dismissed_at,
    }


def notification_from_row(row: tuple[Any, ...]) -> Notification:
    metadata = {}
    try:
        parsed = json.loads(row[8] or "{}")
        if isinstance(parsed, dict):
            metadata = parsed
    except json.JSONDecodeError:
        metadata = {}
    return Notification(
        id=int(row[0]),
        category=str(row[1] or "system"),
        severity=str(row[2] or "info"),
        title=str(row[3] or "Notification"),
        body=str(row[4] or ""),
        source_kind=str(row[5] or ""),
        chat_id=str(row[6] or ""),
        action_url=str(row[7] or ""),
        metadata=metadata,
        created_at=str(row[9] or ""),
        read_at=str(row[10]) if row[10] else None,
        dismissed_at=str(row[11]) if row[11] else None,
    )


def clean_text(value: str, fallback: str, limit: int) -> str:
    clean = str(value or "").strip()
    if not clean:
        clean = fallback
    return clean[:limit]
