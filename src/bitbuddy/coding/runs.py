from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from typing import Any

from ..database import db_connection
from ..paths import GLOBAL_DB_PATH, ensure_app_dirs

CODING_PHASES = ("requested", "inspect", "plan", "build", "edit", "review", "test", "verify", "summarize", "waiting", "completed", "needs_attention", "cancelled", "failed")
INSPECT_TOOLS = {
    "glob_files",
    "list_directory",
    "search_text",
    "get_project_brief",
    "get_project_memory",
    "read_file",
    "read_file_range",
}
EDIT_TOOLS = {"write_file", "patch_file", "make_directory"}
VERIFY_TOOLS = {"run_shell_command", "run_project_validation"}
CODING_TOOL_NAMES = INSPECT_TOOLS | EDIT_TOOLS | VERIFY_TOOLS | {"run_subagent"}
CODING_REQUEST_RE = re.compile(
    r"\b("
    r"code|coding|repo|repository|project|implement|build|add|change|edit|modify|patch|refactor|"
    r"fix|bug|debug|test|pytest|lint|typecheck|type-check|compile|failing|failure|feature|"
    r"function|class|component|endpoint|api|svelte|python|typescript|javascript|ui|page|button|screen"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CodingRun:
    id: str
    chat_id: str
    run_id: str
    project_id: str
    user_request: str
    status: str
    phase: str
    created_at: str
    updated_at: str
    completed_at: str | None
    summary: str
    metadata: dict[str, Any]
    steps: list["CodingRunStep"]


@dataclass(frozen=True)
class CodingRunStep:
    id: int
    coding_run_id: str
    phase: str
    kind: str
    tool: str
    status: str
    summary: str
    metadata: dict[str, Any]
    created_at: str


def ensure_coding_runs_database() -> None:
    ensure_app_dirs()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            create table if not exists coding_runs (
                id text primary key,
                chat_id text not null default '',
                run_id text not null default '',
                project_id text not null default '',
                user_request text not null default '',
                status text not null default 'running',
                phase text not null default 'requested',
                created_at text default current_timestamp,
                updated_at text default current_timestamp,
                completed_at text,
                summary text not null default '',
                metadata text not null default '{}'
            )
            """
        )
        connection.execute("create index if not exists idx_coding_runs_chat on coding_runs(chat_id, created_at desc)")
        connection.execute("create index if not exists idx_coding_runs_project on coding_runs(project_id, created_at desc)")
        connection.execute(
            """
            create table if not exists coding_run_steps (
                id integer primary key autoincrement,
                coding_run_id text not null,
                phase text not null,
                kind text not null default 'runtime',
                tool text not null default '',
                status text not null default 'completed',
                summary text not null default '',
                metadata text not null default '{}',
                created_at text default current_timestamp
            )
            """
        )
        connection.execute("create index if not exists idx_coding_run_steps_run on coding_run_steps(coding_run_id, id)")


def should_track_coding_request(text: str) -> bool:
    return bool(CODING_REQUEST_RE.search(text or ""))


def tool_phase(tool: str, arguments: dict[str, object] | None = None) -> str:
    clean = str(tool or "")
    if clean in EDIT_TOOLS:
        return "edit"
    if clean in VERIFY_TOOLS:
        return "verify"
    if clean == "run_subagent":
        task = str((arguments or {}).get("task") or "")
        return "edit" if re.search(r"\b(implement|edit|patch|fix|change|update)\b", task, re.IGNORECASE) else "inspect"
    if clean in INSPECT_TOOLS:
        return "inspect"
    return "requested"


def start_coding_run(
    *,
    chat_id: str,
    run_id: str,
    user_request: str,
    project_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> CodingRun:
    ensure_coding_runs_database()
    coding_run_id = str(uuid.uuid4())
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            insert into coding_runs (id, chat_id, run_id, project_id, user_request, metadata)
            values (?, ?, ?, ?, ?, ?)
            """,
            (
                coding_run_id,
                chat_id,
                run_id,
                project_id.strip(),
                user_request.strip(),
                json.dumps(metadata or {}),
            ),
        )
        connection.execute(
            """
            insert into coding_run_steps (coding_run_id, phase, kind, summary, metadata)
            values (?, 'requested', 'runtime', ?, ?)
            """,
            (coding_run_id, user_request.strip()[:1000] or "Coding run started.", json.dumps({})),
        )
    return get_coding_run(coding_run_id)


def record_coding_run_step(
    coding_run_id: str,
    *,
    phase: str,
    kind: str = "tool",
    tool: str = "",
    status: str = "completed",
    summary: str = "",
    project_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> CodingRun:
    ensure_coding_runs_database()
    clean_phase = phase if phase in CODING_PHASES else "requested"
    clean_status = status if status in {"running", "completed", "error", "failed"} else "completed"
    with db_connection(GLOBAL_DB_PATH) as connection:
        if project_id.strip():
            connection.execute("update coding_runs set project_id = ? where id = ? and project_id = ''", (project_id.strip(), coding_run_id))
        connection.execute(
            """
            update coding_runs
            set phase = ?, updated_at = current_timestamp
            where id = ? and status = 'running'
            """,
            (clean_phase, coding_run_id),
        )
        connection.execute(
            """
            insert into coding_run_steps (coding_run_id, phase, kind, tool, status, summary, metadata)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                coding_run_id,
                clean_phase,
                kind.strip() or "runtime",
                tool.strip(),
                clean_status,
                summary.strip()[:2000],
                json.dumps(metadata or {}),
            ),
        )
    return get_coding_run(coding_run_id)


def complete_coding_run(coding_run_id: str, *, status: str = "completed", summary: str = "") -> CodingRun:
    ensure_coding_runs_database()
    clean_status = status if status in {"completed", "needs_attention", "cancelled", "failed"} else "completed"
    phase = clean_status
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            update coding_runs
            set status = ?, phase = ?, summary = ?, completed_at = current_timestamp, updated_at = current_timestamp
            where id = ?
            """,
            (clean_status, phase, summary.strip()[:2000], coding_run_id),
        )
        connection.execute(
            """
            insert into coding_run_steps (coding_run_id, phase, kind, status, summary, metadata)
            values (?, ?, 'runtime', ?, ?, '{}')
            """,
            (coding_run_id, phase, clean_status, summary.strip()[:2000] or f"Coding run {clean_status}."),
        )
    return get_coding_run(coding_run_id)


def update_coding_run(
    coding_run_id: str,
    *,
    status: str | None = None,
    phase: str | None = None,
    summary: str | None = None,
    metadata_patch: dict[str, Any] | None = None,
) -> CodingRun:
    run = get_coding_run(coding_run_id)
    metadata = {**run.metadata, **(metadata_patch or {})}
    clean_phase = phase if phase in CODING_PHASES else run.phase
    clean_status = status or run.status
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            update coding_runs
            set status = ?, phase = ?, summary = ?, metadata = ?, updated_at = current_timestamp
            where id = ?
            """,
            (clean_status, clean_phase, run.summary if summary is None else summary.strip()[:2000], json.dumps(metadata), coding_run_id),
        )
    return get_coding_run(coding_run_id)


def get_coding_run(coding_run_id: str) -> CodingRun:
    ensure_coding_runs_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute(
            """
            select id, chat_id, run_id, project_id, user_request, status, phase, created_at, updated_at,
                   completed_at, summary, metadata
            from coding_runs
            where id = ?
            """,
            (coding_run_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"Unknown coding run: {coding_run_id}")
        step_rows = connection.execute(
            """
            select id, coding_run_id, phase, kind, tool, status, summary, metadata, created_at
            from coding_run_steps
            where coding_run_id = ?
            order by id
            """,
            (coding_run_id,),
        ).fetchall()
    return coding_run_from_row(row, step_rows)


def list_coding_runs(limit: int = 20, project_id: str = "", chat_id: str = "") -> list[CodingRun]:
    ensure_coding_runs_database()
    clauses: list[str] = []
    params: list[Any] = []
    if project_id.strip():
        clauses.append("project_id = ?")
        params.append(project_id.strip())
    if chat_id.strip():
        clauses.append("chat_id = ?")
        params.append(chat_id.strip())
    where = f"where {' and '.join(clauses)}" if clauses else ""
    params.append(max(1, min(100, int(limit))))
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            f"""
            select id, chat_id, run_id, project_id, user_request, status, phase, created_at, updated_at,
                   completed_at, summary, metadata
            from coding_runs
            {where}
            order by created_at desc
            limit ?
            """,
            params,
        ).fetchall()
        ids = [str(row[0]) for row in rows]
        steps_by_run: dict[str, list[Any]] = {run_id: [] for run_id in ids}
        if ids:
            placeholders = ",".join("?" for _ in ids)
            step_rows = connection.execute(
                f"""
                select id, coding_run_id, phase, kind, tool, status, summary, metadata, created_at
                from coding_run_steps
                where coding_run_id in ({placeholders})
                order by coding_run_id, id
                """,
                ids,
            ).fetchall()
            for step in step_rows:
                steps_by_run.setdefault(str(step[1]), []).append(step)
    return [coding_run_from_row(row, steps_by_run.get(str(row[0]), [])) for row in rows]


def delete_coding_run(coding_run_id: str) -> bool:
    """Remove a coding run and its steps. Returns True if a row was deleted."""
    ensure_coding_runs_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute("delete from coding_run_steps where coding_run_id = ?", (coding_run_id,))
        cursor = connection.execute("delete from coding_runs where id = ?", (coding_run_id,))
        return cursor.rowcount > 0


def coding_run_from_row(row: Any, step_rows: list[Any]) -> CodingRun:
    return CodingRun(
        id=str(row[0]),
        chat_id=str(row[1] or ""),
        run_id=str(row[2] or ""),
        project_id=str(row[3] or ""),
        user_request=str(row[4] or ""),
        status=str(row[5] or "running"),
        phase=str(row[6] or "requested"),
        created_at=str(row[7] or ""),
        updated_at=str(row[8] or ""),
        completed_at=str(row[9]) if row[9] is not None else None,
        summary=str(row[10] or ""),
        metadata=_json_dict(row[11]),
        steps=[coding_run_step_from_row(step) for step in step_rows],
    )


def coding_run_step_from_row(row: Any) -> CodingRunStep:
    return CodingRunStep(
        id=int(row[0]),
        coding_run_id=str(row[1]),
        phase=str(row[2] or ""),
        kind=str(row[3] or ""),
        tool=str(row[4] or ""),
        status=str(row[5] or ""),
        summary=str(row[6] or ""),
        metadata=_json_dict(row[7]),
        created_at=str(row[8] or ""),
    )


def coding_run_to_json(run: CodingRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "chat_id": run.chat_id,
        "run_id": run.run_id,
        "project_id": run.project_id,
        "user_request": run.user_request,
        "status": run.status,
        "phase": run.phase,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "completed_at": run.completed_at,
        "summary": run.summary,
        "metadata": run.metadata,
        "steps": [
            {
                "id": step.id,
                "coding_run_id": step.coding_run_id,
                "phase": step.phase,
                "kind": step.kind,
                "tool": step.tool,
                "status": step.status,
                "summary": step.summary,
                "metadata": step.metadata,
                "created_at": step.created_at,
            }
            for step in run.steps
        ],
    }


def _json_dict(raw: object) -> dict[str, Any]:
    try:
        parsed = json.loads(str(raw or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
