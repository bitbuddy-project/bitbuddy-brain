from __future__ import annotations

import json
from typing import Any

from .database import db_connection
from .paths import GLOBAL_DB_PATH, ensure_app_dirs


def ensure_activity_database() -> None:
    ensure_app_dirs()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            create table if not exists activity (
                id integer primary key autoincrement,
                kind text not null,
                message text not null,
                metadata text not null default '{}',
                created_at text default current_timestamp
            )
            """
        )


def log_activity(kind: str, message: str, metadata: dict[str, Any] | None = None) -> None:
    ensure_activity_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            "insert into activity (kind, message, metadata) values (?, ?, ?)",
            (kind, message, json.dumps(metadata or {})),
        )


def list_activity(limit: int = 100) -> list[dict[str, Any]]:
    ensure_activity_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            """
            select id, kind, message, metadata, created_at
            from activity
            order by id desc
            limit ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "id": row[0],
            "kind": row[1],
            "message": row[2],
            "metadata": json.loads(row[3] or "{}"),
            "created_at": row[4],
        }
        for row in rows
    ]
