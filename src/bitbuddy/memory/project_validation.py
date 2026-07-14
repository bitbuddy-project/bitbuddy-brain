from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..database import db_connection
from .project_registry import load_project
from .project_schema import initialize_project_database

VALIDATION_KINDS = ("test", "lint", "typecheck", "build", "smoke", "format", "custom")


@dataclass(frozen=True)
class ValidationRecipe:
    name: str
    command: str
    kind: str
    working_directory: str
    description: str
    created_at: str
    updated_at: str
    last_run_at: str | None = None
    last_exit_code: int | None = None
    last_status: str = ""
    last_output: str = ""
    source: str = "stored"


@dataclass(frozen=True)
class ValidationRun:
    recipe: ValidationRecipe
    cwd: str
    exit_code: int
    status: str
    stdout: str
    stderr: str
    elapsed_seconds: float


def ensure_validation_recipe_database(project_id_or_name: str) -> None:
    project = load_project(project_id_or_name)
    initialize_project_database(project.database_path)
    with db_connection(project.database_path) as connection:
        connection.execute(
            """
            create table if not exists validation_recipes (
                name text primary key,
                command text not null,
                kind text not null default 'custom',
                working_directory text not null default '.',
                description text not null default '',
                created_at text default current_timestamp,
                updated_at text default current_timestamp,
                last_run_at text,
                last_exit_code integer,
                last_status text not null default '',
                last_output text not null default ''
            )
            """
        )
        connection.execute("create index if not exists idx_validation_recipes_kind on validation_recipes(kind, updated_at desc)")


def upsert_validation_recipe(
    project_id_or_name: str,
    *,
    name: str,
    command: str,
    kind: str = "custom",
    working_directory: str = ".",
    description: str = "",
) -> ValidationRecipe:
    clean_name = _clean_name(name)
    clean_command = command.strip()
    if not clean_command:
        raise ValueError("Validation command is required.")
    clean_kind = kind.strip().lower() if kind.strip().lower() in VALIDATION_KINDS else "custom"
    clean_working_directory = _clean_working_directory(working_directory)
    _resolve_recipe_cwd(project_id_or_name, clean_working_directory)
    ensure_validation_recipe_database(project_id_or_name)
    project = load_project(project_id_or_name)
    with db_connection(project.database_path) as connection:
        connection.execute(
            """
            insert into validation_recipes (name, command, kind, working_directory, description)
            values (?, ?, ?, ?, ?)
            on conflict(name) do update set
                command = excluded.command,
                kind = excluded.kind,
                working_directory = excluded.working_directory,
                description = excluded.description,
                updated_at = current_timestamp
            """,
            (clean_name, clean_command, clean_kind, clean_working_directory, description.strip()),
        )
    return get_validation_recipe(project_id_or_name, clean_name)


def get_validation_recipe(project_id_or_name: str, name: str) -> ValidationRecipe:
    ensure_validation_recipe_database(project_id_or_name)
    project = load_project(project_id_or_name)
    clean_name = _clean_name(name)
    with db_connection(project.database_path) as connection:
        row = connection.execute(
            """
            select name, command, kind, working_directory, description, created_at, updated_at,
                   last_run_at, last_exit_code, last_status, last_output
            from validation_recipes
            where name = ?
            """,
            (clean_name,),
        ).fetchone()
    if row is None:
        raise ValueError(f"Unknown validation recipe: {clean_name}")
    return recipe_from_row(row)


def list_validation_recipes(project_id_or_name: str, *, include_suggestions: bool = False) -> list[ValidationRecipe]:
    ensure_validation_recipe_database(project_id_or_name)
    project = load_project(project_id_or_name)
    with db_connection(project.database_path) as connection:
        rows = connection.execute(
            """
            select name, command, kind, working_directory, description, created_at, updated_at,
                   last_run_at, last_exit_code, last_status, last_output
            from validation_recipes
            order by kind, name
            """
        ).fetchall()
    recipes = [recipe_from_row(row) for row in rows]
    if not include_suggestions:
        return recipes
    stored_names = {recipe.name for recipe in recipes}
    return [*recipes, *[recipe for recipe in suggest_validation_recipes(project_id_or_name) if recipe.name not in stored_names]]


def delete_validation_recipe(project_id_or_name: str, name: str) -> bool:
    ensure_validation_recipe_database(project_id_or_name)
    project = load_project(project_id_or_name)
    clean_name = _clean_name(name)
    with db_connection(project.database_path) as connection:
        cursor = connection.execute("delete from validation_recipes where name = ?", (clean_name,))
    return bool(cursor.rowcount)


def run_validation_recipe(project_id_or_name: str, name: str, *, timeout_seconds: int = 300) -> ValidationRun:
    recipe = get_validation_recipe(project_id_or_name, name)
    cwd = _resolve_recipe_cwd(project_id_or_name, recipe.working_directory)
    started = datetime.now(timezone.utc)
    result = subprocess.run(
        recipe.command,
        shell=True,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        timeout=max(1, min(900, int(timeout_seconds))),
    )
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    status = "passed" if result.returncode == 0 else "failed"
    output_excerpt = _cap_output("\n".join(part for part in (result.stdout, result.stderr) if part).strip())
    project = load_project(project_id_or_name)
    with db_connection(project.database_path) as connection:
        connection.execute(
            """
            update validation_recipes
            set last_run_at = current_timestamp,
                last_exit_code = ?,
                last_status = ?,
                last_output = ?,
                updated_at = current_timestamp
            where name = ?
            """,
            (result.returncode, status, output_excerpt, recipe.name),
        )
    return ValidationRun(
        recipe=get_validation_recipe(project_id_or_name, recipe.name),
        cwd=str(cwd),
        exit_code=result.returncode,
        status=status,
        stdout=result.stdout,
        stderr=result.stderr,
        elapsed_seconds=elapsed,
    )


def suggest_validation_recipes(project_id_or_name: str) -> list[ValidationRecipe]:
    project = load_project(project_id_or_name)
    if not project.paths:
        return []
    root = project.paths[0] if project.paths[0].is_dir() else project.paths[0].parent
    now = ""
    suggestions: list[ValidationRecipe] = []
    package_json = root / "package.json"
    if package_json.is_file():
        suggestions.extend(_package_json_suggestions(package_json, now))
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        suggestions.extend(_pyproject_suggestions(pyproject, now))
    return _dedupe_suggestions(suggestions)


def recipe_to_json(recipe: ValidationRecipe) -> dict[str, Any]:
    return {
        "name": recipe.name,
        "command": recipe.command,
        "kind": recipe.kind,
        "working_directory": recipe.working_directory,
        "description": recipe.description,
        "created_at": recipe.created_at,
        "updated_at": recipe.updated_at,
        "last_run_at": recipe.last_run_at,
        "last_exit_code": recipe.last_exit_code,
        "last_status": recipe.last_status,
        "last_output": recipe.last_output,
        "source": recipe.source,
    }


def validation_run_to_json(run: ValidationRun) -> dict[str, Any]:
    return {
        "recipe": recipe_to_json(run.recipe),
        "cwd": run.cwd,
        "exit_code": run.exit_code,
        "status": run.status,
        "stdout": run.stdout,
        "stderr": run.stderr,
        "elapsed_seconds": run.elapsed_seconds,
    }


def recipe_from_row(row: Any) -> ValidationRecipe:
    return ValidationRecipe(
        name=str(row[0]),
        command=str(row[1]),
        kind=str(row[2] or "custom"),
        working_directory=str(row[3] or "."),
        description=str(row[4] or ""),
        created_at=str(row[5] or ""),
        updated_at=str(row[6] or ""),
        last_run_at=str(row[7]) if row[7] is not None else None,
        last_exit_code=int(row[8]) if row[8] is not None else None,
        last_status=str(row[9] or ""),
        last_output=str(row[10] or ""),
    )


def _clean_name(name: str) -> str:
    clean = " ".join(name.strip().lower().replace("_", "-").split())
    clean = clean.replace(" ", "-")
    if not clean:
        raise ValueError("Validation recipe name is required.")
    if "/" in clean or "\\" in clean:
        raise ValueError("Validation recipe name cannot contain path separators.")
    return clean[:80]


def _clean_working_directory(value: str) -> str:
    clean = (value or ".").strip() or "."
    path = Path(clean).expanduser()
    if path.is_absolute():
        raise ValueError("Validation recipe working_directory must be project-relative.")
    return path.as_posix()


def _resolve_recipe_cwd(project_id_or_name: str, working_directory: str) -> Path:
    project = load_project(project_id_or_name)
    if not project.paths:
        raise ValueError(f"Project has no registered paths: {project_id_or_name}")
    root = project.paths[0] if project.paths[0].is_dir() else project.paths[0].parent
    cwd = (root / working_directory).resolve()
    try:
        cwd.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError("Validation recipe working_directory escapes the project root.") from error
    if not cwd.exists():
        raise ValueError(f"Validation recipe working_directory does not exist: {working_directory}")
    if not cwd.is_dir():
        raise ValueError(f"Validation recipe working_directory is not a directory: {working_directory}")
    return cwd


def _package_json_suggestions(path: Path, created_at: str) -> list[ValidationRecipe]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return []
    preferred = {
        "test": "test",
        "lint": "lint",
        "check": "typecheck",
        "typecheck": "typecheck",
        "type-check": "typecheck",
        "build": "build",
    }
    result: list[ValidationRecipe] = []
    for script, kind in preferred.items():
        if script not in scripts:
            continue
        result.append(_suggested_recipe(script, f"npm run {script}", kind, created_at))
    return result


def _pyproject_suggestions(path: Path, created_at: str) -> list[ValidationRecipe]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    lowered = text.lower()
    result = [_suggested_recipe("test", "python -m pytest", "test", created_at)]
    if "ruff" in lowered:
        result.append(_suggested_recipe("lint", "python -m ruff check .", "lint", created_at))
    if "mypy" in lowered:
        result.append(_suggested_recipe("typecheck", "python -m mypy .", "typecheck", created_at))
    return result


def _suggested_recipe(name: str, command: str, kind: str, created_at: str) -> ValidationRecipe:
    return ValidationRecipe(
        name=name,
        command=command,
        kind=kind,
        working_directory=".",
        description="Suggested from project files; save it before relying on it as the canonical validation recipe.",
        created_at=created_at,
        updated_at=created_at,
        source="suggested",
    )


def _dedupe_suggestions(recipes: list[ValidationRecipe]) -> list[ValidationRecipe]:
    result: list[ValidationRecipe] = []
    seen: set[str] = set()
    for recipe in recipes:
        if recipe.name in seen:
            continue
        seen.add(recipe.name)
        result.append(recipe)
    return result


def _cap_output(text: str, limit: int = 8000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n... validation output truncated ..."
