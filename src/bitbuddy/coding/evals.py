from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Iterable

from ..database import db_connection
from ..paths import GLOBAL_DB_PATH, ensure_app_dirs
from .runs import CodingRun, get_coding_run


@dataclass(frozen=True)
class CodingEvalTask:
    id: str
    name: str
    prompt: str
    project_id: str
    validation_recipe: str
    tags: list[str]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class CodingEvalRun:
    id: str
    task_id: str
    coding_run_id: str
    provider: str
    model: str
    status: str
    score: float
    passed: bool
    metrics: dict[str, Any]
    notes: str
    created_at: str


def ensure_coding_eval_database() -> None:
    ensure_app_dirs()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            create table if not exists coding_eval_tasks (
                id text primary key,
                name text not null unique,
                prompt text not null,
                project_id text not null default '',
                validation_recipe text not null default '',
                tags text not null default '[]',
                created_at text default current_timestamp,
                updated_at text default current_timestamp
            )
            """
        )
        connection.execute("create index if not exists idx_coding_eval_tasks_project on coding_eval_tasks(project_id)")
        connection.execute(
            """
            create table if not exists coding_eval_runs (
                id text primary key,
                task_id text not null,
                coding_run_id text not null,
                provider text not null default '',
                model text not null default '',
                status text not null default 'unknown',
                score real not null default 0,
                passed integer not null default 0,
                metrics text not null default '{}',
                notes text not null default '',
                created_at text default current_timestamp
            )
            """
        )
        connection.execute("create index if not exists idx_coding_eval_runs_task on coding_eval_runs(task_id, created_at desc)")
        connection.execute("create index if not exists idx_coding_eval_runs_run on coding_eval_runs(coding_run_id)")


def upsert_eval_task(
    *,
    name: str,
    prompt: str,
    project_id: str = "",
    validation_recipe: str = "",
    tags: Iterable[str] = (),
    task_id: str = "",
) -> CodingEvalTask:
    ensure_coding_eval_database()
    clean_name = name.strip()
    clean_prompt = prompt.strip()
    if not clean_name:
        raise ValueError("Eval task name is required.")
    if not clean_prompt:
        raise ValueError("Eval task prompt is required.")

    clean_tags = [str(tag).strip() for tag in tags if str(tag).strip()]
    selected_id = task_id.strip() or str(uuid.uuid4())
    with db_connection(GLOBAL_DB_PATH) as connection:
        existing = connection.execute("select id from coding_eval_tasks where name = ?", (clean_name,)).fetchone()
        if existing is not None:
            selected_id = str(existing[0])
            connection.execute(
                """
                update coding_eval_tasks
                set prompt = ?, project_id = ?, validation_recipe = ?, tags = ?, updated_at = current_timestamp
                where id = ?
                """,
                (clean_prompt, project_id.strip(), validation_recipe.strip(), json.dumps(clean_tags), selected_id),
            )
        else:
            connection.execute(
                """
                insert into coding_eval_tasks (id, name, prompt, project_id, validation_recipe, tags)
                values (?, ?, ?, ?, ?, ?)
                """,
                (
                    selected_id,
                    clean_name,
                    clean_prompt,
                    project_id.strip(),
                    validation_recipe.strip(),
                    json.dumps(clean_tags),
                ),
            )
    task = get_eval_task(selected_id)
    if task is None:
        raise ValueError("Could not save eval task.")
    return task


def get_eval_task(task_id_or_name: str) -> CodingEvalTask | None:
    ensure_coding_eval_database()
    key = task_id_or_name.strip()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute(
            """
            select id, name, prompt, project_id, validation_recipe, tags, created_at, updated_at
            from coding_eval_tasks
            where id = ? or name = ?
            """,
            (key, key),
        ).fetchone()
    return coding_eval_task_from_row(row) if row is not None else None


def list_eval_tasks(project_id: str = "") -> list[CodingEvalTask]:
    ensure_coding_eval_database()
    params: list[Any] = []
    where = ""
    if project_id.strip():
        where = "where project_id = ?"
        params.append(project_id.strip())
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            f"""
            select id, name, prompt, project_id, validation_recipe, tags, created_at, updated_at
            from coding_eval_tasks
            {where}
            order by updated_at desc, name
            """,
            params,
        ).fetchall()
    return [coding_eval_task_from_row(row) for row in rows]


def delete_eval_task(task_id_or_name: str) -> bool:
    ensure_coding_eval_database()
    task = get_eval_task(task_id_or_name)
    if task is None:
        return False
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute("delete from coding_eval_tasks where id = ?", (task.id,))
        connection.execute("delete from coding_eval_runs where task_id = ?", (task.id,))
    return True


def score_coding_run_for_task(
    *,
    task_id: str,
    coding_run_id: str,
    provider: str = "",
    model: str = "",
    notes: str = "",
) -> CodingEvalRun:
    ensure_coding_eval_database()
    task = get_eval_task(task_id)
    if task is None:
        raise ValueError(f"Unknown eval task: {task_id}")
    run = get_coding_run(coding_run_id)
    metrics = coding_run_eval_metrics(task, run)
    score = float(metrics["score"])
    passed = bool(metrics["passed"])
    eval_run_id = str(uuid.uuid4())
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            insert into coding_eval_runs (id, task_id, coding_run_id, provider, model, status, score, passed, metrics, notes)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                eval_run_id,
                task.id,
                run.id,
                provider.strip(),
                model.strip(),
                run.status,
                score,
                1 if passed else 0,
                json.dumps(metrics, sort_keys=True),
                notes.strip()[:2000],
            ),
        )
    eval_run = get_eval_run(eval_run_id)
    if eval_run is None:
        raise ValueError("Could not save eval run.")
    return eval_run


def list_eval_runs(task_id: str = "", limit: int = 50) -> list[CodingEvalRun]:
    ensure_coding_eval_database()
    clauses: list[str] = []
    params: list[Any] = []
    if task_id.strip():
        task = get_eval_task(task_id)
        if task is None:
            return []
        clauses.append("task_id = ?")
        params.append(task.id)
    where = f"where {' and '.join(clauses)}" if clauses else ""
    params.append(max(1, min(200, int(limit))))
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            f"""
            select id, task_id, coding_run_id, provider, model, status, score, passed, metrics, notes, created_at
            from coding_eval_runs
            {where}
            order by created_at desc
            limit ?
            """,
            params,
        ).fetchall()
    return [coding_eval_run_from_row(row) for row in rows]


def get_eval_run(eval_run_id: str) -> CodingEvalRun | None:
    ensure_coding_eval_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute(
            """
            select id, task_id, coding_run_id, provider, model, status, score, passed, metrics, notes, created_at
            from coding_eval_runs
            where id = ?
            """,
            (eval_run_id,),
        ).fetchone()
    return coding_eval_run_from_row(row) if row is not None else None


def coding_run_eval_metrics(task: CodingEvalTask, run: CodingRun) -> dict[str, Any]:
    inspect_steps = count_steps(run, phase="inspect")
    edit_steps = count_steps(run, phase="edit")
    verify_steps = count_steps(run, phase="verify")
    failed_steps = sum(1 for step in run.steps if step.status in {"error", "failed"})
    validation_seen = validation_recipe_seen(run, task.validation_recipe)
    project_matched = not task.project_id or run.project_id == task.project_id

    criteria = {
        "completed": run.status == "completed",
        "project_matched": project_matched,
        "inspected": inspect_steps > 0,
        "edited": edit_steps > 0,
        "verified": verify_steps > 0,
        "validation_recipe_seen": validation_seen,
        "no_failed_steps": failed_steps == 0,
    }

    score = 0.0
    score += 0.30 if criteria["completed"] else 0.0
    score += 0.10 if criteria["project_matched"] else 0.0
    score += 0.15 if criteria["inspected"] else 0.0
    score += 0.20 if criteria["edited"] else 0.0
    score += 0.20 if criteria["verified"] else 0.0
    score += 0.05 if criteria["no_failed_steps"] else 0.0

    requires_recipe = bool(task.validation_recipe)
    passed = (
        criteria["completed"]
        and criteria["project_matched"]
        and criteria["edited"]
        and criteria["verified"]
        and criteria["no_failed_steps"]
        and (not requires_recipe or criteria["validation_recipe_seen"])
        and score >= 0.80
    )
    if requires_recipe and not criteria["validation_recipe_seen"]:
        score = min(score, 0.79)

    return {
        "score": round(score, 2),
        "passed": passed,
        "criteria": criteria,
        "inspect_steps": inspect_steps,
        "edit_steps": edit_steps,
        "verify_steps": verify_steps,
        "failed_steps": failed_steps,
        "step_count": len(run.steps),
        "task_project_id": task.project_id,
        "run_project_id": run.project_id,
        "required_validation_recipe": task.validation_recipe,
    }


def count_steps(run: CodingRun, *, phase: str) -> int:
    return sum(1 for step in run.steps if step.phase == phase)


def validation_recipe_seen(run: CodingRun, recipe_name: str) -> bool:
    clean_name = recipe_name.strip()
    for step in run.steps:
        if step.tool != "run_project_validation":
            continue
        if not clean_name:
            return step.status == "completed"
        haystack = f"{step.summary}\n{json.dumps(step.metadata, sort_keys=True)}"
        if clean_name in haystack:
            return step.status == "completed"
    return False


def coding_eval_task_from_row(row: Any) -> CodingEvalTask:
    return CodingEvalTask(
        id=str(row[0]),
        name=str(row[1] or ""),
        prompt=str(row[2] or ""),
        project_id=str(row[3] or ""),
        validation_recipe=str(row[4] or ""),
        tags=_json_list(row[5]),
        created_at=str(row[6] or ""),
        updated_at=str(row[7] or ""),
    )


def coding_eval_run_from_row(row: Any) -> CodingEvalRun:
    return CodingEvalRun(
        id=str(row[0]),
        task_id=str(row[1] or ""),
        coding_run_id=str(row[2] or ""),
        provider=str(row[3] or ""),
        model=str(row[4] or ""),
        status=str(row[5] or "unknown"),
        score=float(row[6] or 0),
        passed=bool(row[7]),
        metrics=_json_dict(row[8]),
        notes=str(row[9] or ""),
        created_at=str(row[10] or ""),
    )


def coding_eval_task_to_json(task: CodingEvalTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "name": task.name,
        "prompt": task.prompt,
        "project_id": task.project_id,
        "validation_recipe": task.validation_recipe,
        "tags": task.tags,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


def coding_eval_run_to_json(run: CodingEvalRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "task_id": run.task_id,
        "coding_run_id": run.coding_run_id,
        "provider": run.provider,
        "model": run.model,
        "status": run.status,
        "score": run.score,
        "passed": run.passed,
        "metrics": run.metrics,
        "notes": run.notes,
        "created_at": run.created_at,
    }


def _json_dict(raw: object) -> dict[str, Any]:
    try:
        parsed = json.loads(str(raw or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(raw: object) -> list[str]:
    try:
        parsed = json.loads(str(raw or "[]"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]
