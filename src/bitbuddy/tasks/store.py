from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..calendar.store import to_utc_iso
from ..database import db_connection
from ..paths import GLOBAL_DB_PATH, ensure_app_dirs

TASK_STATUSES = ("open", "done", "dismissed")

_COLUMNS = (
    "id, title, notes, due_at, remind_at, status, priority, project_id, "
    "source, created_at, updated_at, completed_at, reminded_at, metadata"
)


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    notes: str
    due_at: str | None
    remind_at: str | None
    status: str
    priority: int
    project_id: str
    source: str
    created_at: str
    updated_at: str
    completed_at: str | None
    reminded_at: str | None
    metadata: dict[str, Any]


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #


def ensure_tasks_database() -> None:
    ensure_app_dirs()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            create table if not exists tasks (
                id text primary key,
                title text not null,
                notes text not null default '',
                due_at text,
                remind_at text,
                status text not null default 'open',
                priority integer not null default 3,
                project_id text not null default '',
                source text not null default 'chat',
                created_at text default current_timestamp,
                updated_at text default current_timestamp,
                completed_at text,
                reminded_at text,
                metadata text not null default '{}'
            )
            """
        )
        connection.execute("create index if not exists idx_tasks_status on tasks(status, priority desc, created_at desc)")
        connection.execute("create index if not exists idx_tasks_due on tasks(status, remind_at)")
        connection.execute("create index if not exists idx_tasks_project on tasks(project_id, status)")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _user_timezone() -> str:
    """The user's configured timezone, used to interpret naive (offset-less) times."""
    try:
        from ..config import load_config

        return load_config().user_context.timezone or "UTC"
    except Exception:
        return "UTC"


def _normalize_dt(value: str | datetime | None) -> str | None:
    """Normalize an optional due/remind time to a UTC ISO8601 string, or None.

    A time without an explicit offset (e.g. ``2026-06-26T17:00`` from the model
    resolving "5pm") is interpreted in the user's timezone, not UTC — otherwise
    the reminder fires hours off. Offset-aware values are respected as-is.
    """
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    return to_utc_iso(value, fallback_tz=_user_timezone())


def _clean_status(status: str) -> str:
    clean = (status or "").strip().lower()
    return clean if clean in TASK_STATUSES else "open"


# --------------------------------------------------------------------------- #
# CRUD
# --------------------------------------------------------------------------- #


def create_task(
    title: str,
    *,
    notes: str = "",
    due_at: str | datetime | None = None,
    remind_at: str | datetime | None = None,
    priority: int = 3,
    project_id: str = "",
    source: str = "chat",
    metadata: dict[str, Any] | None = None,
    task_id: str | None = None,
) -> Task:
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("A task title is required.")
    ensure_tasks_database()
    clean_id = task_id or str(uuid.uuid4())
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            insert into tasks (id, title, notes, due_at, remind_at, status, priority, project_id, source, metadata)
            values (?, ?, ?, ?, ?, 'open', ?, ?, ?, ?)
            """,
            (
                clean_id,
                clean_title,
                notes.strip(),
                _normalize_dt(due_at),
                _normalize_dt(remind_at),
                max(1, min(5, int(priority))),
                project_id.strip(),
                (source or "chat").strip(),
                json.dumps(metadata or {}),
            ),
        )
    return get_task(clean_id)


def get_task(task_id: str) -> Task:
    ensure_tasks_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute(f"select {_COLUMNS} from tasks where id = ?", (task_id,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown task: {task_id}")
    return task_from_row(row)


def list_tasks(status: str | None = "open", project_id: str = "", limit: int = 50) -> list[Task]:
    """List tasks. ``status`` of None or 'all' returns every status."""
    ensure_tasks_database()
    clauses: list[str] = []
    params: list[Any] = []
    if status and status.lower() != "all":
        clauses.append("status = ?")
        params.append(_clean_status(status))
    if project_id.strip():
        clauses.append("project_id = ?")
        params.append(project_id.strip())
    where = f"where {' and '.join(clauses)}" if clauses else ""
    params.append(max(1, min(200, int(limit))))
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            f"""
            select {_COLUMNS} from tasks
            {where}
            order by (status = 'open') desc,
                     coalesce(remind_at, due_at) is null,
                     coalesce(remind_at, due_at) asc,
                     priority desc,
                     created_at desc
            limit ?
            """,
            params,
        ).fetchall()
    return [task_from_row(row) for row in rows]


_UPDATABLE_TEXT = {"title", "notes", "project_id", "source"}
_UPDATABLE_DT = {"due_at", "remind_at"}


def update_task(task_id: str, **fields: Any) -> Task:
    existing = get_task(task_id)
    assignments: list[str] = []
    params: list[Any] = []
    for key, value in fields.items():
        if value is None and key not in _UPDATABLE_DT:
            continue
        if key in _UPDATABLE_TEXT:
            assignments.append(f"{key} = ?")
            params.append(str(value).strip())
        elif key in _UPDATABLE_DT:
            assignments.append(f"{key} = ?")
            params.append(_normalize_dt(value))
        elif key == "priority":
            assignments.append("priority = ?")
            params.append(max(1, min(5, int(value))))
        elif key == "status":
            new_status = _clean_status(str(value))
            assignments.append("status = ?")
            params.append(new_status)
            if new_status == "done" and not existing.completed_at:
                assignments.append("completed_at = ?")
                params.append(_now_iso())
            elif new_status != "done":
                assignments.append("completed_at = null")
        elif key == "metadata" and isinstance(value, dict):
            assignments.append("metadata = ?")
            params.append(json.dumps(value))
    if not assignments:
        return existing
    assignments.append("updated_at = ?")
    params.append(_now_iso())
    params.append(task_id)
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(f"update tasks set {', '.join(assignments)} where id = ?", params)
    return get_task(task_id)


def complete_task(task_id: str) -> Task:
    return update_task(task_id, status="done")


def delete_task(task_id: str) -> bool:
    ensure_tasks_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        cursor = connection.execute("delete from tasks where id = ?", (task_id,))
    return bool(cursor.rowcount)


# --------------------------------------------------------------------------- #
# Reminder firing
# --------------------------------------------------------------------------- #


def due_tasks_to_fire(now: datetime | None = None) -> list[Task]:
    """Open tasks whose reminder is due and has not yet fired."""
    ensure_tasks_database()
    now_iso = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            f"""
            select {_COLUMNS} from tasks
            where status = 'open'
              and remind_at is not null
              and remind_at != ''
              and remind_at <= ?
              and reminded_at is null
            order by remind_at asc
            """,
            (now_iso,),
        ).fetchall()
    return [task_from_row(row) for row in rows]


def mark_task_reminded(task_id: str, fired_at: str | None = None) -> None:
    ensure_tasks_database()
    stamp = fired_at or _now_iso()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute("update tasks set reminded_at = ? where id = ?", (stamp, task_id))


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #


def task_to_json(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "notes": task.notes,
        "due_at": task.due_at,
        "remind_at": task.remind_at,
        "status": task.status,
        "priority": task.priority,
        "project_id": task.project_id,
        "source": task.source,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
        "completed_at": task.completed_at,
        "reminded_at": task.reminded_at,
        "metadata": task.metadata,
    }


def task_from_row(row: Any) -> Task:
    try:
        metadata = json.loads(row[13] or "{}")
    except json.JSONDecodeError:
        metadata = {}
    return Task(
        id=str(row[0]),
        title=str(row[1] or ""),
        notes=str(row[2] or ""),
        due_at=str(row[3]) if row[3] else None,
        remind_at=str(row[4]) if row[4] else None,
        status=str(row[5] or "open"),
        priority=int(row[6] or 3),
        project_id=str(row[7] or ""),
        source=str(row[8] or "chat"),
        created_at=str(row[9] or ""),
        updated_at=str(row[10] or ""),
        completed_at=str(row[11]) if row[11] else None,
        reminded_at=str(row[12]) if row[12] else None,
        metadata=metadata if isinstance(metadata, dict) else {},
    )
