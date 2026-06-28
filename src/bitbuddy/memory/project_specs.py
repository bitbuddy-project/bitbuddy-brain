from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import yaml

from ..database import db_connection
from .project_registry import load_project
from .project_schema import initialize_project_database


SPEC_STATUSES = ("draft", "active", "archived")
DEFAULT_STATUS = "draft"
ACTIVE_BODY_LIMIT = 6000


@dataclass(frozen=True)
class ProjectSpec:
    id: str
    title: str
    status: str
    rel_path: str
    tags: list[str]
    created_at: str
    updated_at: str
    body: str = ""


_COLUMNS = "id, title, status, rel_path, tags, created_at, updated_at"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_status(status: str) -> str:
    clean = (status or "").strip().lower()
    return clean if clean in SPEC_STATUSES else DEFAULT_STATUS


def _normalize_tags(tags: Iterable[str] | None) -> list[str]:
    if not tags:
        return []
    result: list[str] = []
    for tag in tags:
        clean = str(tag).strip()
        if clean and clean not in result:
            result.append(clean)
    return result[:12]


def slugify_spec(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug[:60] or "spec"


def _specs_dir_for(project_id_or_name: str):
    project = load_project(project_id_or_name)
    return project, project.metadata_path.parent / "specs"


def _render_spec_file(spec: ProjectSpec) -> str:
    frontmatter = {
        "id": spec.id,
        "title": spec.title,
        "status": spec.status,
        "tags": spec.tags,
        "created_at": spec.created_at,
        "updated_at": spec.updated_at,
    }
    front = yaml.safe_dump(
        {key: value for key, value in frontmatter.items() if value not in ("", [], None)},
        sort_keys=False,
    ).strip()
    return f"---\n{front}\n---\n\n{spec.body.strip()}\n"


def _parse_spec_file(path) -> tuple[dict[str, Any], str]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) == 3:
            try:
                front = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                front = {}
            return (front if isinstance(front, dict) else {}), parts[2].lstrip("\n")
    return {}, raw


def _row_to_spec(row: Any, *, include_body: bool, specs_root) -> ProjectSpec:
    try:
        tags = json.loads(row[4] or "[]")
    except json.JSONDecodeError:
        tags = []
    body = ""
    if include_body:
        abs_path = specs_root.parent / str(row[3])
        if abs_path.is_file():
            _, body = _parse_spec_file(abs_path)
    return ProjectSpec(
        id=str(row[0]),
        title=str(row[1] or ""),
        status=str(row[2] or DEFAULT_STATUS),
        rel_path=str(row[3] or ""),
        tags=tags if isinstance(tags, list) else [],
        created_at=str(row[5] or ""),
        updated_at=str(row[6] or ""),
        body=body,
    )


def _upsert_index(connection, spec: ProjectSpec) -> None:
    connection.execute(
        """
        insert into project_specs (id, title, status, rel_path, tags, created_at, updated_at)
        values (?, ?, ?, ?, ?, ?, ?)
        on conflict(id) do update set
            title = excluded.title,
            status = excluded.status,
            rel_path = excluded.rel_path,
            tags = excluded.tags,
            updated_at = excluded.updated_at
        """,
        (
            spec.id,
            spec.title,
            spec.status,
            spec.rel_path,
            json.dumps(spec.tags),
            spec.created_at,
            spec.updated_at,
        ),
    )


def list_project_specs(
    project_id_or_name: str,
    *,
    include_archived: bool = False,
    limit: int = 100,
) -> list[ProjectSpec]:
    project, specs_dir = _specs_dir_for(project_id_or_name)
    initialize_project_database(project.database_path)
    reconcile_spec_index(project_id_or_name)
    clauses: list[str] = []
    params: list[Any] = []
    if not include_archived:
        clauses.append("status != 'archived'")
    cap = max(1, min(500, int(limit)))
    where = f"where {' and '.join(clauses)}" if clauses else ""
    with db_connection(project.database_path) as connection:
        rows = connection.execute(
            f"select {_COLUMNS} from project_specs {where} order by updated_at desc limit ?",
            [*params, cap],
        ).fetchall()
    return [_row_to_spec(row, include_body=False, specs_root=specs_dir) for row in rows]


def read_project_spec(
    project_id_or_name: str,
    spec_id: str,
    *,
    include_body: bool = True,
) -> ProjectSpec | None:
    project, specs_dir = _specs_dir_for(project_id_or_name)
    initialize_project_database(project.database_path)
    reconcile_spec_index(project_id_or_name)
    with db_connection(project.database_path) as connection:
        row = connection.execute(
            f"select {_COLUMNS} from project_specs where id = ?",
            (spec_id,),
        ).fetchone()
    if row is None:
        return None
    return _row_to_spec(row, include_body=include_body, specs_root=specs_dir)


def create_project_spec(
    project_id_or_name: str,
    title: str,
    *,
    body: str = "",
    tags: Iterable[str] | None = None,
    status: str = DEFAULT_STATUS,
) -> ProjectSpec:
    clean_title = (title or "").strip() or "Untitled spec"
    project, specs_dir = _specs_dir_for(project_id_or_name)
    initialize_project_database(project.database_path)
    specs_dir.mkdir(parents=True, exist_ok=True)

    now = _now_iso()
    spec_id = slugify_spec(clean_title)
    base = spec_id
    counter = 1
    with db_connection(project.database_path) as connection:
        while connection.execute("select 1 from project_specs where id = ?", (spec_id,)).fetchone() is not None:
            counter += 1
            spec_id = f"{base}-{counter}"

    rel_path = f"specs/{spec_id}.md"
    abs_path = project.metadata_path.parent / rel_path
    spec = ProjectSpec(
        id=spec_id,
        title=clean_title,
        status=_normalize_status(status),
        rel_path=rel_path,
        tags=_normalize_tags(tags),
        created_at=now,
        updated_at=now,
        body=(body or "").strip(),
    )
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(_render_spec_file(spec), encoding="utf-8")
    with db_connection(project.database_path) as connection:
        _upsert_index(connection, spec)
    return spec


def update_project_spec(
    project_id_or_name: str,
    spec_id: str,
    *,
    title: str | None = None,
    body: str | None = None,
    tags: Iterable[str] | None = None,
    status: str | None = None,
) -> ProjectSpec | None:
    project, specs_dir = _specs_dir_for(project_id_or_name)
    initialize_project_database(project.database_path)
    with db_connection(project.database_path) as connection:
        row = connection.execute(
            f"select {_COLUMNS} from project_specs where id = ?",
            (spec_id,),
        ).fetchone()
    if row is None:
        return None
    existing = _row_to_spec(row, include_body=False, specs_root=specs_dir)

    new_title = existing.title if title is None else (title or "").strip() or existing.title
    new_status = _normalize_status(status) if status is not None else existing.status
    new_tags = existing.tags if tags is None else _normalize_tags(tags)
    new_body = existing.body if body is None else (body or "").strip()

    # Refresh body from disk in case it was hand-edited since indexing.
    abs_path = project.metadata_path.parent / existing.rel_path
    if body is None and abs_path.is_file():
        _, disk_body = _parse_spec_file(abs_path)
        new_body = disk_body

    now = _now_iso()
    updated = ProjectSpec(
        id=existing.id,
        title=new_title,
        status=new_status,
        rel_path=existing.rel_path,
        tags=new_tags,
        created_at=existing.created_at,
        updated_at=now,
        body=new_body,
    )
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(_render_spec_file(updated), encoding="utf-8")
    with db_connection(project.database_path) as connection:
        _upsert_index(connection, updated)
    return updated


def archive_project_spec(project_id_or_name: str, spec_id: str) -> ProjectSpec | None:
    return update_project_spec(project_id_or_name, spec_id, status="archived")


def active_project_specs(project_id_or_name: str, *, limit: int = 3, include_body: bool = True) -> list[ProjectSpec]:
    project, specs_dir = _specs_dir_for(project_id_or_name)
    initialize_project_database(project.database_path)
    reconcile_spec_index(project_id_or_name)
    cap = max(1, min(20, int(limit)))
    with db_connection(project.database_path) as connection:
        rows = connection.execute(
            f"select {_COLUMNS} from project_specs where status = 'active' order by updated_at desc limit ?",
            (cap,),
        ).fetchall()
    specs = [_row_to_spec(row, include_body=include_body, specs_root=specs_dir) for row in rows]
    if not include_body:
        return specs

    truncated: list[ProjectSpec] = []
    for spec in specs:
        if len(spec.body) > ACTIVE_BODY_LIMIT:
            truncated.append(
                ProjectSpec(
                    id=spec.id,
                    title=spec.title,
                    status=spec.status,
                    rel_path=spec.rel_path,
                    tags=spec.tags,
                    created_at=spec.created_at,
                    updated_at=spec.updated_at,
                    body=spec.body[:ACTIVE_BODY_LIMIT].rstrip() + "\n\n... spec body truncated for context ...",
                )
            )
        else:
            truncated.append(spec)
    return truncated


def reconcile_spec_index(project_id_or_name: str) -> int:
    """Add index rows for spec files added to the specs/ folder outside this module."""
    project, specs_dir = _specs_dir_for(project_id_or_name)
    if not specs_dir.exists():
        return 0
    with db_connection(project.database_path) as connection:
        known = {str(row[0]) for row in connection.execute("select rel_path from project_specs").fetchall()}
    added = 0
    for path in sorted(specs_dir.rglob("*.md")):
        rel_path = path.relative_to(project.metadata_path.parent).as_posix()
        if rel_path in known:
            continue
        front, body = _parse_spec_file(path)
        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        spec = ProjectSpec(
            id=str(front.get("id") or slugify_spec(str(front.get("title") or path.stem))),
            title=str(front.get("title") or path.stem.replace("-", " ").title()),
            status=_normalize_status(str(front.get("status") or DEFAULT_STATUS)),
            rel_path=rel_path,
            tags=_normalize_tags(front.get("tags") if isinstance(front.get("tags"), list) else []),
            created_at=str(front.get("created_at") or mtime),
            updated_at=str(front.get("updated_at") or mtime),
            body=body,
        )
        with db_connection(project.database_path) as connection:
            _upsert_index(connection, spec)
        added += 1
    return added


def spec_to_json(spec: ProjectSpec, *, include_body: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": spec.id,
        "title": spec.title,
        "status": spec.status,
        "rel_path": spec.rel_path,
        "tags": spec.tags,
        "created_at": spec.created_at,
        "updated_at": spec.updated_at,
    }
    if include_body:
        payload["body"] = spec.body
    return payload
