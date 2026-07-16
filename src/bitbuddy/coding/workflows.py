from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from ..config import load_config
from ..database import db_connection
from ..paths import GLOBAL_DB_PATH, ensure_app_dirs

STAGE_KINDS = ("plan", "build", "review", "test")


@dataclass(frozen=True)
class CodingStage:
    id: str
    kind: str
    name: str
    provider_key: str
    model: str
    reasoning_effort: str
    instructions: str
    approval_gate: bool
    validation_recipes: tuple[str, ...]


@dataclass(frozen=True)
class CodingWorkflow:
    id: str
    name: str
    stages: tuple[CodingStage, ...]
    is_default: bool
    created_at: str
    updated_at: str
    bypass_permissions: bool = False


def ensure_workflow_database() -> None:
    ensure_app_dirs()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            create table if not exists coding_workflows (
                id text primary key,
                name text not null,
                stages text not null default '[]',
                is_default integer not null default 0,
                bypass_permissions integer not null default 0,
                created_at text default current_timestamp,
                updated_at text default current_timestamp
            )
            """
        )
        columns = {str(row[1]) for row in connection.execute("pragma table_info(coding_workflows)").fetchall()}
        if "bypass_permissions" not in columns:
            connection.execute("alter table coding_workflows add column bypass_permissions integer not null default 0")
        count = int(connection.execute("select count(*) from coding_workflows").fetchone()[0])
        if count == 0:
            workflow = default_workflow()
            connection.execute(
                "insert into coding_workflows (id, name, stages, is_default) values (?, ?, ?, 1)",
                (workflow.id, workflow.name, json.dumps([stage_to_json(stage) for stage in workflow.stages])),
            )


def default_workflow() -> CodingWorkflow:
    config = load_config()
    provider = config.provider
    provider_key = provider.key or provider.type
    model = provider.model
    effort = provider.reasoning_effort
    stages = (
        CodingStage(str(uuid.uuid4()), "plan", "Plan", provider_key, model, effort, "Inspect the project and produce an implementation-ready plan.", False, ()),
        CodingStage(str(uuid.uuid4()), "build", "Build", provider_key, model, effort, "Implement the approved plans and verify your edits as you work.", False, ()),
        CodingStage(str(uuid.uuid4()), "review", "Review", provider_key, model, effort, "Review the implementation independently for correctness, regressions, and missed requirements.", False, ()),
        CodingStage(str(uuid.uuid4()), "test", "Test", provider_key, model, effort, "Run the selected project checks and assess whether the implementation is ready.", False, ()),
    )
    return CodingWorkflow(str(uuid.uuid4()), "Plan, build, review, test", stages, True, "", "", False)


def parse_stage(raw: object, index: int = 0) -> CodingStage:
    if not isinstance(raw, dict):
        raise ValueError("Workflow stages must be objects.")
    kind = str(raw.get("kind") or "").strip().lower()
    if kind not in STAGE_KINDS:
        raise ValueError(f"Unsupported coding stage kind: {kind or '(empty)'}")
    provider_key = str(raw.get("provider_key") or "").strip()
    model = str(raw.get("model") or "").strip()
    recipes = raw.get("validation_recipes")
    return CodingStage(
        id=str(raw.get("id") or uuid.uuid4()),
        kind=kind,
        name=str(raw.get("name") or kind.title()).strip()[:80] or kind.title(),
        provider_key=provider_key,
        model=model,
        reasoning_effort=str(raw.get("reasoning_effort") or "medium").strip(),
        instructions=str(raw.get("instructions") or "").strip()[:8000],
        approval_gate=bool(raw.get("approval_gate")),
        validation_recipes=tuple(str(item).strip() for item in recipes if str(item).strip()) if isinstance(recipes, list) else (),
    )


def validate_stages(stages: tuple[CodingStage, ...]) -> None:
    if not stages:
        raise ValueError("A coding workflow requires stages.")
    builds = [index for index, stage in enumerate(stages) if stage.kind == "build"]
    if len(builds) != 1:
        raise ValueError("A coding workflow requires exactly one Build stage.")
    build_index = builds[0]
    if any(stage.kind != "plan" for stage in stages[:build_index]):
        raise ValueError("Only Plan stages may appear before Build.")
    if any(stage.kind not in {"review", "test"} for stage in stages[build_index + 1 :]):
        raise ValueError("Only Review and Test stages may appear after Build.")
    ids = [stage.id for stage in stages]
    if len(ids) != len(set(ids)):
        raise ValueError("Stage ids must be unique.")
    config = load_config()
    provider_keys = {provider.key or provider.type for provider in config.providers}
    for stage in stages:
        if not stage.provider_key or stage.provider_key not in provider_keys:
            raise ValueError(f"Stage `{stage.name}` must select a configured provider.")
        if not stage.model:
            raise ValueError(f"Stage `{stage.name}` must select a model.")


def save_workflow(*, name: str, stages: list[object], workflow_id: str = "", is_default: bool | None = None, bypass_permissions: bool = False) -> CodingWorkflow:
    ensure_workflow_database()
    clean_name = name.strip()[:120]
    if not clean_name:
        raise ValueError("Workflow name is required.")
    parsed = tuple(parse_stage(raw, index) for index, raw in enumerate(stages))
    validate_stages(parsed)
    selected_id = workflow_id.strip() or str(uuid.uuid4())
    with db_connection(GLOBAL_DB_PATH) as connection:
        existing = connection.execute("select is_default from coding_workflows where id = ?", (selected_id,)).fetchone()
        default_value = bool(existing[0]) if existing is not None else False
        if is_default is not None:
            default_value = is_default
        if default_value:
            connection.execute("update coding_workflows set is_default = 0")
        connection.execute(
            """
            insert into coding_workflows (id, name, stages, is_default, bypass_permissions)
            values (?, ?, ?, ?, ?)
            on conflict(id) do update set name = excluded.name, stages = excluded.stages,
                is_default = excluded.is_default, bypass_permissions = excluded.bypass_permissions,
                updated_at = current_timestamp
            """,
            (selected_id, clean_name, json.dumps([stage_to_json(stage) for stage in parsed]), int(default_value), int(bool(bypass_permissions))),
        )
    return get_workflow(selected_id)


def list_workflows() -> list[CodingWorkflow]:
    ensure_workflow_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute("select id, name, stages, is_default, created_at, updated_at, bypass_permissions from coding_workflows order by is_default desc, updated_at desc").fetchall()
    return [workflow_from_row(row) for row in rows]


def get_workflow(workflow_id: str) -> CodingWorkflow:
    ensure_workflow_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute("select id, name, stages, is_default, created_at, updated_at, bypass_permissions from coding_workflows where id = ?", (workflow_id,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown coding workflow: {workflow_id}")
    return workflow_from_row(row)


def delete_workflow(workflow_id: str) -> bool:
    ensure_workflow_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute("select is_default from coding_workflows where id = ?", (workflow_id,)).fetchone()
        if row is None:
            return False
        if bool(row[0]):
            raise ValueError("Choose another default workflow before deleting this one.")
        cursor = connection.execute("delete from coding_workflows where id = ?", (workflow_id,))
    return bool(cursor.rowcount)


def stage_to_json(stage: CodingStage) -> dict[str, Any]:
    return {
        "id": stage.id,
        "kind": stage.kind,
        "name": stage.name,
        "provider_key": stage.provider_key,
        "model": stage.model,
        "reasoning_effort": stage.reasoning_effort,
        "instructions": stage.instructions,
        "approval_gate": stage.approval_gate,
        "validation_recipes": list(stage.validation_recipes),
    }


def workflow_to_json(workflow: CodingWorkflow) -> dict[str, Any]:
    return {
        "id": workflow.id,
        "name": workflow.name,
        "stages": [stage_to_json(stage) for stage in workflow.stages],
        "is_default": workflow.is_default,
        "bypass_permissions": workflow.bypass_permissions,
        "created_at": workflow.created_at,
        "updated_at": workflow.updated_at,
    }


def workflow_from_row(row: Any) -> CodingWorkflow:
    try:
        raw_stages = json.loads(row[2] or "[]")
    except (TypeError, json.JSONDecodeError):
        raw_stages = []
    stages = tuple(parse_stage(raw, index) for index, raw in enumerate(raw_stages))
    bypass = bool(row[6]) if len(row) > 6 else False
    return CodingWorkflow(str(row[0]), str(row[1]), stages, bool(row[3]), str(row[4] or ""), str(row[5] or ""), bypass)
