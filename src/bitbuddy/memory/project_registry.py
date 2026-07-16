from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from ..activity import log_activity
from ..database import db_connection
from ..paths import GLOBAL_DB_PATH, PROJECTS_DIR, ensure_app_dirs
from .project_helpers import ensure_column, resolve_allowed_path, slugify, stable_project_id
from .project_schema import initialize_project_database
from .project_types import LOGGER, Project

def ensure_global_database() -> None:
    ensure_app_dirs()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            create table if not exists projects (
                id text primary key,
                name text not null,
                metadata_path text not null,
                database_path text not null,
                created_at text default current_timestamp,
                updated_at text default current_timestamp
            )
            """
        )
        ensure_column(connection, "projects", "metadata_path", "text not null default ''")
        ensure_column(connection, "projects", "updated_at", "text default current_timestamp")


def register_project(name: str, raw_paths: list[str]) -> Project:
    ensure_global_database()
    if not raw_paths:
        raise ValueError("At least one project path is required.")

    paths = tuple(resolve_allowed_path(path) for path in raw_paths)
    canonical_path = paths[0]
    project_id = stable_project_id(name, canonical_path)

    LOGGER.debug(
        "register_project input name=%r input_path=%r canonical_path=%r project_id=%r",
        name,
        raw_paths[0],
        str(canonical_path),
        project_id,
    )

    existing_project = find_project_by_canonical_path(canonical_path)
    if existing_project is not None:
        LOGGER.debug(
            "register_project matched existing project project_id=%r metadata_path=%r",
            existing_project.id,
            str(existing_project.metadata_path),
        )
        upsert_global_project(existing_project)
        return existing_project

    project_dir = PROJECTS_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    database_path = project_dir / "memory.sqlite"
    metadata_path = project_dir / "project.yaml"

    metadata = {
        "id": project_id,
        "name": name,
        "access": "read-only",
        "paths": [str(path) for path in paths],
        "database": str(database_path),
    }
    metadata_path.write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8")
    initialize_project_database(database_path)

    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            insert into projects (id, name, metadata_path, database_path)
            values (?, ?, ?, ?)
            on conflict(id) do update set
                name = excluded.name,
                metadata_path = excluded.metadata_path,
                database_path = excluded.database_path,
                updated_at = current_timestamp
            """,
            (project_id, name, str(metadata_path), str(database_path)),
        )

    log_activity(
        "project.registered",
        f"Registered project memory {name}",
        {"project_id": project_id, "paths": [str(path) for path in paths]},
    )
    LOGGER.debug(
        "register_project created new project project_id=%r metadata_path=%r database_path=%r",
        project_id,
        str(metadata_path),
        str(database_path),
    )
    return Project(project_id, name, paths, database_path, metadata_path)


def update_project_paths(project_id_or_name: str, raw_paths: list[str]) -> Project:
    """Re-point an existing project at new directories, keeping its id and memory."""
    if not raw_paths:
        raise ValueError("At least one project path is required.")
    project = load_project(project_id_or_name)
    paths = tuple(resolve_allowed_path(path) for path in raw_paths)

    raw = yaml.safe_load(project.metadata_path.read_text(encoding="utf-8")) or {}
    raw["paths"] = [str(path) for path in paths]
    project.metadata_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    updated = Project(project.id, project.name, paths, project.database_path, project.metadata_path)
    upsert_global_project(updated)

    log_activity(
        "project.paths_updated",
        f"Updated project directories for {project.name}",
        {"project_id": project.id, "paths": [str(path) for path in paths]},
    )
    return updated


def find_project_by_canonical_path(canonical_path: Path) -> Project | None:
    for metadata_path in sorted(PROJECTS_DIR.glob("*/project.yaml")):
        raw = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
        stored_paths = raw.get("paths", [])
        if not isinstance(stored_paths, list):
            continue

        for stored_path in stored_paths:
            if Path(str(stored_path)).expanduser().resolve() != canonical_path:
                continue
            return Project(
                id=str(raw["id"]),
                name=str(raw["name"]),
                paths=tuple(Path(path).expanduser().resolve() for path in stored_paths),
                database_path=Path(raw["database"]).expanduser().resolve(),
                metadata_path=metadata_path,
            )

    return None


def upsert_global_project(project: Project) -> None:
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            insert into projects (id, name, metadata_path, database_path)
            values (?, ?, ?, ?)
            on conflict(id) do update set
                name = excluded.name,
                metadata_path = excluded.metadata_path,
                database_path = excluded.database_path,
                updated_at = current_timestamp
            """,
            (project.id, project.name, str(project.metadata_path), str(project.database_path)),
        )


def list_projects() -> list[Project]:
    if not PROJECTS_DIR.exists():
        return []
    projects: list[Project] = []
    for metadata_path in sorted(PROJECTS_DIR.glob("*/project.yaml")):
        project = load_project(metadata_path.parent.name)
        projects.append(project)
    return projects


def project_list_context(max_projects: int = 10, max_chars: int = 1200) -> str:
    """Build a bounded project registry block for prompt injection."""
    projects = list_projects()
    if not projects:
        return ""

    lines: list[str] = []
    for project in projects[:max_projects]:
        paths_str = ", ".join(str(p) for p in project.paths[:2])
        if len(project.paths) > 2:
            paths_str += f", +{len(project.paths) - 2} more"
        lines.append(f"- {project.name} (id: {project.id}) — {paths_str}")

    content = "\n".join(lines)
    if len(content) > max_chars:
        content = content[:max_chars].rstrip() + "\n..."

    return "\n".join(
        [
            "[Registered Projects]",
            "You have access to the following projects. When the user mentions a project name or asks about their work,",
            "use the matching project_id with the project-related tools from [Available Tools].",
            "This project registry is not a complete tool list.",
            "Do not ask the user what projects they have — you already know from this list.",
            "",
            content,
        ]
    )


def load_project(project_id_or_name: str) -> Project:
    candidates = [PROJECTS_DIR / project_id_or_name / "project.yaml"]
    slug = slugify(project_id_or_name)
    if slug != project_id_or_name:
        candidates.append(PROJECTS_DIR / slug / "project.yaml")

    for metadata_path in PROJECTS_DIR.glob("*/project.yaml"):
        raw = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
        if raw.get("name") == project_id_or_name:
            candidates.append(metadata_path)

    for metadata_path in candidates:
        if metadata_path.exists():
            raw = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
            return Project(
                id=str(raw["id"]),
                name=str(raw["name"]),
                paths=tuple(Path(path).expanduser().resolve() for path in raw.get("paths", [])),
                database_path=Path(raw["database"]).expanduser().resolve(),
                metadata_path=metadata_path,
            )
    raise ValueError(f"Unknown project: {project_id_or_name}")


def unregister_project(project_id_or_name: str) -> bool:
    """Delete a project and all its data. Returns True if deleted."""
    try:
        project = load_project(project_id_or_name)
    except ValueError:
        return False

    # 1. Delete global DB row
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute("delete from projects where id = ?", (project.id,))

    # 2. Delete librarian card
    try:
        from ..librarian import delete_card
        delete_card(project.id)
    except Exception:
        pass

    # 3. Delete project directory (YAML + memory.sqlite)
    project_dir = project.metadata_path.parent
    if project_dir.exists():
        shutil.rmtree(project_dir, ignore_errors=True)

    log_activity("project.deleted", f"Deleted project {project.name}", {"project_id": project.id, "project_name": project.name})
    return True
