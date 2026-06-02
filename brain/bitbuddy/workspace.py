from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from .database import db_connection
from .paths import GLOBAL_DB_PATH, WORKSPACE_DIR, WORKSPACE_KINDS, ensure_app_dirs


DEFAULT_KIND = "notes"


@dataclass(frozen=True)
class WorkspaceDocument:
    id: str
    rel_path: str
    title: str
    kind: str
    summary: str
    source: str
    goal_id: str
    cycle_id: str
    tags: list[str]
    pinned: bool
    status: str
    created_at: str
    updated_at: str
    body: str = ""


def ensure_workspace_database() -> None:
    ensure_app_dirs()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            create table if not exists workspace_documents (
                id text primary key,
                rel_path text not null unique,
                title text not null default '',
                kind text not null default 'notes',
                summary text not null default '',
                source text not null default '',
                goal_id text not null default '',
                cycle_id text not null default '',
                tags text not null default '[]',
                pinned integer not null default 0,
                status text not null default 'active',
                created_at text default current_timestamp,
                updated_at text default current_timestamp
            )
            """
        )
        connection.execute("create index if not exists idx_workspace_kind on workspace_documents(kind, status, updated_at desc)")
        connection.execute("create index if not exists idx_workspace_goal on workspace_documents(goal_id, status, updated_at desc)")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalize_kind(kind: str) -> str:
    clean = (kind or "").strip().lower()
    return clean if clean in WORKSPACE_KINDS else DEFAULT_KIND


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")
    return slug[:60] or "untitled"


def _normalize_tags(tags: Iterable[str] | None) -> list[str]:
    if not tags:
        return []
    result: list[str] = []
    for tag in tags:
        clean = str(tag).strip()
        if clean and clean not in result:
            result.append(clean)
    return result[:12]


def _render_document(document: WorkspaceDocument) -> str:
    frontmatter = {
        "id": document.id,
        "title": document.title,
        "kind": document.kind,
        "summary": document.summary,
        "source": document.source,
        "goal_id": document.goal_id,
        "cycle_id": document.cycle_id,
        "tags": document.tags,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
    }
    front = yaml.safe_dump({key: value for key, value in frontmatter.items() if value not in ("", [], None)}, sort_keys=False).strip()
    return f"---\n{front}\n---\n\n{document.body.strip()}\n"


def _parse_document_file(path: Path) -> tuple[dict[str, Any], str]:
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


def _path_for(kind: str, slug: str) -> tuple[str, Path]:
    rel_path = f"{kind}/{slug}.md"
    return rel_path, WORKSPACE_DIR / rel_path


def write_workspace_document(
    kind: str,
    title: str,
    body: str,
    *,
    summary: str = "",
    source: str = "",
    goal_id: str = "",
    cycle_id: str = "",
    tags: Iterable[str] | None = None,
    doc_id: str | None = None,
) -> WorkspaceDocument:
    clean_title = (title or "").strip() or "Untitled"
    clean_kind = _normalize_kind(kind)
    ensure_workspace_database()

    rel_path, abs_path = _path_for(clean_kind, slugify(clean_title))
    now = _now_iso()

    with db_connection(GLOBAL_DB_PATH) as connection:
        existing = connection.execute(
            "select id, created_at from workspace_documents where rel_path = ?", (rel_path,)
        ).fetchone()
    created_at = str(existing[1]) if existing else now
    resolved_id = doc_id or (str(existing[0]) if existing else str(uuid.uuid4()))

    document = WorkspaceDocument(
        id=resolved_id,
        rel_path=rel_path,
        title=clean_title,
        kind=clean_kind,
        summary=(summary or "").strip(),
        source=(source or "").strip(),
        goal_id=(goal_id or "").strip(),
        cycle_id=(cycle_id or "").strip(),
        tags=_normalize_tags(tags),
        pinned=False,
        status="active",
        created_at=created_at,
        updated_at=now,
        body=(body or "").strip(),
    )

    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_text(_render_document(document), encoding="utf-8")
    _upsert_index(document)
    return document


def append_to_workspace_document(doc_id: str, text: str, *, heading: str = "") -> WorkspaceDocument:
    document = read_workspace_document(doc_id)
    if document is None:
        raise ValueError(f"Unknown workspace document: {doc_id}")
    addition = text.strip()
    if heading.strip():
        addition = f"## {heading.strip()}\n\n{addition}"
    new_body = f"{document.body.strip()}\n\n{addition}".strip()
    return write_workspace_document(
        document.kind,
        document.title,
        new_body,
        summary=document.summary,
        source=document.source,
        goal_id=document.goal_id,
        cycle_id=document.cycle_id,
        tags=document.tags,
        doc_id=document.id,
    )


def _upsert_index(document: WorkspaceDocument) -> None:
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            insert into workspace_documents (
                id, rel_path, title, kind, summary, source, goal_id, cycle_id,
                tags, pinned, status, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(rel_path) do update set
                title = excluded.title,
                kind = excluded.kind,
                summary = excluded.summary,
                source = excluded.source,
                goal_id = excluded.goal_id,
                cycle_id = excluded.cycle_id,
                tags = excluded.tags,
                status = 'active',
                updated_at = excluded.updated_at
            """,
            (
                document.id,
                document.rel_path,
                document.title,
                document.kind,
                document.summary,
                document.source,
                document.goal_id,
                document.cycle_id,
                json.dumps(document.tags),
                1 if document.pinned else 0,
                document.status,
                document.created_at,
                document.updated_at,
            ),
        )


def _row_to_document(row: Any, *, include_body: bool = False) -> WorkspaceDocument:
    try:
        tags = json.loads(row[8] or "[]")
    except json.JSONDecodeError:
        tags = []
    body = ""
    if include_body:
        abs_path = WORKSPACE_DIR / str(row[1])
        if abs_path.is_file():
            _, body = _parse_document_file(abs_path)
    return WorkspaceDocument(
        id=str(row[0]),
        rel_path=str(row[1]),
        title=str(row[2] or ""),
        kind=str(row[3] or DEFAULT_KIND),
        summary=str(row[4] or ""),
        source=str(row[5] or ""),
        goal_id=str(row[6] or ""),
        cycle_id=str(row[7] or ""),
        tags=tags if isinstance(tags, list) else [],
        pinned=bool(row[9]),
        status=str(row[10] or "active"),
        created_at=str(row[11] or ""),
        updated_at=str(row[12] or ""),
        body=body,
    )


_COLUMNS = "id, rel_path, title, kind, summary, source, goal_id, cycle_id, tags, pinned, status, created_at, updated_at"


def list_workspace_documents(kind: str = "", status: str = "active", limit: int = 100) -> list[WorkspaceDocument]:
    reconcile_workspace_index()
    clauses = ["status = ?"]
    params: list[Any] = [status or "active"]
    if kind:
        clauses.append("kind = ?")
        params.append(_normalize_kind(kind))
    params.append(max(1, min(500, int(limit))))
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            f"select {_COLUMNS} from workspace_documents where {' and '.join(clauses)} "
            "order by pinned desc, updated_at desc limit ?",
            params,
        ).fetchall()
    return [_row_to_document(row) for row in rows]


def read_workspace_document(doc_id: str) -> WorkspaceDocument | None:
    ensure_workspace_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute(
            f"select {_COLUMNS} from workspace_documents where id = ?", (doc_id,)
        ).fetchone()
    if row is None:
        return None
    return _row_to_document(row, include_body=True)


def latest_document_for_goal(goal_id: str) -> WorkspaceDocument | None:
    if not goal_id:
        return None
    ensure_workspace_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute(
            f"select {_COLUMNS} from workspace_documents where goal_id = ? and status = 'active' "
            "order by updated_at desc limit 1",
            (goal_id,),
        ).fetchone()
    if row is None:
        return None
    return _row_to_document(row)


def set_workspace_document_pinned(doc_id: str, pinned: bool) -> None:
    ensure_workspace_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            "update workspace_documents set pinned = ?, updated_at = ? where id = ?",
            (1 if pinned else 0, _now_iso(), doc_id),
        )


def archive_workspace_document(doc_id: str) -> bool:
    ensure_workspace_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        cursor = connection.execute(
            "update workspace_documents set status = 'archived', updated_at = ? where id = ?",
            (_now_iso(), doc_id),
        )
        return cursor.rowcount > 0


def reconcile_workspace_index() -> int:
    """Add index rows for any markdown files added to the workspace outside this module."""
    ensure_workspace_database()
    if not WORKSPACE_DIR.exists():
        return 0
    with db_connection(GLOBAL_DB_PATH) as connection:
        known = {str(row[0]) for row in connection.execute("select rel_path from workspace_documents").fetchall()}
    added = 0
    for path in sorted(WORKSPACE_DIR.rglob("*.md")):
        rel_path = path.relative_to(WORKSPACE_DIR).as_posix()
        if rel_path in known:
            continue
        front, _body = _parse_document_file(path)
        kind = _normalize_kind(path.parent.name)
        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        document = WorkspaceDocument(
            id=str(front.get("id") or uuid.uuid4()),
            rel_path=rel_path,
            title=str(front.get("title") or path.stem.replace("-", " ").title()),
            kind=str(front.get("kind") or kind),
            summary=str(front.get("summary") or ""),
            source=str(front.get("source") or "manual"),
            goal_id=str(front.get("goal_id") or ""),
            cycle_id=str(front.get("cycle_id") or ""),
            tags=_normalize_tags(front.get("tags") if isinstance(front.get("tags"), list) else []),
            pinned=False,
            status="active",
            created_at=str(front.get("created_at") or mtime),
            updated_at=str(front.get("updated_at") or mtime),
        )
        _upsert_index(document)
        added += 1
    return added


def workspace_document_to_json(document: WorkspaceDocument, *, include_body: bool = False) -> dict[str, Any]:
    payload = {
        "id": document.id,
        "rel_path": document.rel_path,
        "title": document.title,
        "kind": document.kind,
        "summary": document.summary,
        "source": document.source,
        "goal_id": document.goal_id,
        "cycle_id": document.cycle_id,
        "tags": document.tags,
        "pinned": document.pinned,
        "status": document.status,
        "created_at": document.created_at,
        "updated_at": document.updated_at,
    }
    if include_body:
        payload["body"] = document.body
    return payload
