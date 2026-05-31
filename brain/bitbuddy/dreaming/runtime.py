from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..chats.repository import chat_activity_token
from ..database import db_connection
from ..lifecycle import get_lifecycle_state, iso_local, transition_lifecycle
from ..paths import GLOBAL_DB_PATH, ensure_app_dirs
from .log import log_dream
from .tasks import minidream_tasks, run_dream_task


@dataclass
class DreamJob:
    dream_id: str
    mode: str
    reason: str
    scheduled_token: dict[str, object]
    cancel_event: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None


_DREAM_LOCK = threading.Lock()
_ACTIVE_DREAM: DreamJob | None = None


def ensure_dream_database() -> None:
    ensure_app_dirs()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            create table if not exists dream_runs (
                id text primary key,
                mode text not null,
                status text not null,
                reason text not null default '',
                previous_state text not null default '',
                transition_reason text not null default '',
                started_at text default current_timestamp,
                completed_at text,
                interrupted_at text,
                scheduled_token text not null default '{}',
                metadata text not null default '{}'
            )
            """
        )
        connection.execute(
            """
            create table if not exists dream_tasks (
                id integer primary key autoincrement,
                dream_run_id text not null,
                kind text not null,
                status text not null,
                started_at text default current_timestamp,
                completed_at text,
                summary text not null default '',
                changes text not null default '{}',
                error text not null default ''
            )
            """
        )
        connection.execute("create index if not exists idx_dream_runs_status on dream_runs(status, started_at desc)")
        connection.execute("create index if not exists idx_dream_tasks_run on dream_tasks(dream_run_id, id)")


def start_minidream(reason: str, now: datetime | None = None) -> str | None:
    job = prepare_minidream(reason=reason, now=now)
    if job is None:
        return None
    thread = threading.Thread(target=run_dream_job, args=(job, now), name=f"bitbuddy-dream-{job.dream_id}", daemon=True)
    job.thread = thread
    thread.start()
    return job.dream_id


def run_minidream(reason: str = "manual", now: datetime | None = None) -> str | None:
    job = prepare_minidream(reason=reason, now=now)
    if job is None:
        return None
    run_dream_job(job, now=now)
    return job.dream_id


def prepare_minidream(reason: str, now: datetime | None = None) -> DreamJob | None:
    ensure_dream_database()
    state = get_lifecycle_state()
    if state.state != "NightEligible":
        log_dream("skipped", "MiniDream skipped because lifecycle is not NightEligible", {"state": state.state, "reason": reason})
        return None
    dream_id = str(uuid.uuid4())
    token = chat_activity_token()
    job = DreamJob(dream_id=dream_id, mode="mini", reason=reason, scheduled_token=token)
    with _DREAM_LOCK:
        global _ACTIVE_DREAM
        if _ACTIVE_DREAM is not None:
            log_dream("skipped", "MiniDream skipped because another dream is active", {"active_dream_id": _ACTIVE_DREAM.dream_id})
            return None
        _ACTIVE_DREAM = job
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            insert into dream_runs (id, mode, status, reason, previous_state, transition_reason, scheduled_token, metadata)
            values (?, 'mini', 'running', ?, ?, 'idle timer elapsed', ?, ?)
            """,
            (dream_id, reason, state.state, json.dumps(token), json.dumps({"night_reason": state.night_reason})),
        )
    transition_lifecycle("Dreaming", reason="idle timer elapsed", current_dream_id=dream_id, metadata_patch={"dream_mode": "mini"}, now=now)
    log_dream("started", "Started MiniDream", {"dream_id": dream_id, "reason": reason})
    return job


def run_dream_job(job: DreamJob, now: datetime | None = None) -> None:
    started = time.monotonic()
    status = "completed"
    try:
        for task_kind in minidream_tasks():
            if dream_interrupted(job):
                status = "interrupted"
                break
            task_id = start_task(job.dream_id, task_kind)
            try:
                result = run_dream_task(task_kind, now=now)
                complete_task(task_id, "completed", result.summary, result.changes)
                log_dream("task_completed", result.summary, {"dream_id": job.dream_id, "task": task_kind, "changes": result.changes})
            except Exception as error:
                complete_task(task_id, "failed", "Dream task failed.", {}, error=str(error))
                log_dream("task_failed", "Dream task failed", {"dream_id": job.dream_id, "task": task_kind, "error": str(error)})
        if dream_interrupted(job):
            status = "interrupted"
        if status == "completed":
            finish_dream(job, status="completed", elapsed_seconds=round(time.monotonic() - started, 3), now=now)
            transition_lifecycle("Sleep", reason="MiniDream completed", current_dream_id="", now=now)
        else:
            finish_dream(job, status="interrupted", elapsed_seconds=round(time.monotonic() - started, 3), now=now)
    finally:
        with _DREAM_LOCK:
            global _ACTIVE_DREAM
            if _ACTIVE_DREAM is job:
                _ACTIVE_DREAM = None


def request_dream_interrupt(reason: str = "interrupted") -> None:
    with _DREAM_LOCK:
        job = _ACTIVE_DREAM
    if job is None:
        return
    job.cancel_event.set()
    mark_dream_interrupted(job.dream_id, reason)
    log_dream("interrupt_requested", "Requested dream interruption", {"dream_id": job.dream_id, "reason": reason})


def dream_interrupted(job: DreamJob) -> bool:
    if job.cancel_event.is_set():
        return True
    try:
        return chat_activity_token() != job.scheduled_token
    except Exception:
        return True


def start_task(dream_id: str, kind: str) -> int:
    with db_connection(GLOBAL_DB_PATH) as connection:
        cursor = connection.execute(
            "insert into dream_tasks (dream_run_id, kind, status) values (?, ?, 'running')",
            (dream_id, kind),
        )
        return int(cursor.lastrowid)


def complete_task(task_id: int, status: str, summary: str, changes: dict[str, Any], error: str = "") -> None:
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            update dream_tasks
            set status = ?, completed_at = current_timestamp, summary = ?, changes = ?, error = ?
            where id = ?
            """,
            (status, summary[:1000], json.dumps(changes), error[:1000], task_id),
        )


def finish_dream(job: DreamJob, *, status: str, elapsed_seconds: float, now: datetime | None = None) -> None:
    timestamp = iso_local(now) if now is not None else None
    with db_connection(GLOBAL_DB_PATH) as connection:
        if status == "completed":
            connection.execute(
                "update dream_runs set status = ?, completed_at = coalesce(?, current_timestamp), metadata = ? where id = ?",
                (status, timestamp, json.dumps({"elapsed_seconds": elapsed_seconds}), job.dream_id),
            )
        else:
            connection.execute(
                "update dream_runs set status = ?, interrupted_at = coalesce(?, current_timestamp), metadata = ? where id = ?",
                (status, timestamp, json.dumps({"elapsed_seconds": elapsed_seconds}), job.dream_id),
            )
    log_dream(status, f"MiniDream {status}", {"dream_id": job.dream_id, "elapsed_seconds": elapsed_seconds})
    try:
        from ..continuity import record_continuity_event

        record_continuity_event(
            "dream_run_completed",
            f"MiniDream {status}: {job.reason}",
            source="dreaming",
            run_id=job.dream_id,
            metadata={"mode": job.mode, "status": status, "elapsed_seconds": elapsed_seconds},
        )
    except Exception:
        pass


def mark_dream_interrupted(dream_id: str, reason: str) -> None:
    ensure_dream_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute("select metadata from dream_runs where id = ?", (dream_id,)).fetchone()
        metadata = safe_json(row[0], {}) if row else {}
        if not isinstance(metadata, dict):
            metadata = {}
        metadata["interrupt_reason"] = reason
        connection.execute(
            """
            update dream_runs
            set status = case when status = 'running' then 'interrupting' else status end,
                interrupted_at = current_timestamp,
                metadata = ?
            where id = ?
            """,
            (json.dumps(metadata), dream_id),
        )


def list_dream_runs(limit: int = 20) -> list[dict[str, Any]]:
    ensure_dream_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            "select id, mode, status, reason, previous_state, transition_reason, started_at, completed_at, interrupted_at, scheduled_token, metadata from dream_runs order by started_at desc limit ?",
            (max(1, min(100, int(limit))),),
        ).fetchall()
    return [dream_run_to_json(row) for row in rows]


def list_dream_tasks(dream_run_id: str) -> list[dict[str, Any]]:
    ensure_dream_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            "select id, dream_run_id, kind, status, started_at, completed_at, summary, changes, error from dream_tasks where dream_run_id = ? order by id asc",
            (dream_run_id,),
        ).fetchall()
    return [dream_task_to_json(row) for row in rows]


def dream_run_to_json(row: Any) -> dict[str, Any]:
    return {
        "id": row[0],
        "mode": row[1],
        "status": row[2],
        "reason": row[3],
        "previous_state": row[4],
        "transition_reason": row[5],
        "started_at": row[6],
        "completed_at": row[7],
        "interrupted_at": row[8],
        "scheduled_token": safe_json(row[9], {}),
        "metadata": safe_json(row[10], {}),
    }


def dream_task_to_json(row: Any) -> dict[str, Any]:
    return {
        "id": row[0],
        "dream_run_id": row[1],
        "kind": row[2],
        "status": row[3],
        "started_at": row[4],
        "completed_at": row[5],
        "summary": row[6],
        "changes": safe_json(row[7], {}),
        "error": row[8],
    }


def safe_json(value: str, fallback: Any) -> Any:
    try:
        parsed = json.loads(value or "")
    except json.JSONDecodeError:
        return fallback
    return parsed
