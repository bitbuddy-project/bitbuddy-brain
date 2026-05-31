from __future__ import annotations

import sqlite3

from ..activity import log_activity
from ..database import db_connection
from .project_helpers import (
    create_scan,
    file_is_current,
    finish_scan,
    iter_project_files,
    mark_deleted_files,
    rebuild_project_layers,
    relative_to_any,
    replace_symbols,
    summarize_file,
    upsert_file,
)
from .project_registry import load_project
from .project_schema import initialize_project_database
from .project_types import IndexResult

def index_project(project_id_or_name: str, record_activity: bool = True) -> IndexResult:
    project = load_project(project_id_or_name)
    initialize_project_database(project.database_path)
    seen: set[str] = set()
    scanned = 0
    changed = 0
    skipped = 0
    changed_paths: list[str] = []
    skipped_paths: list[str] = []

    with db_connection(project.database_path) as connection:
        scan_id = create_scan(connection)
        for root in project.paths:
            for file_path in iter_project_files(root):
                relative_path = relative_to_any(file_path, project.paths)
                seen.add(str(file_path))
                scanned += 1
                stat = file_path.stat()
                if file_is_current(connection, file_path, stat):
                    continue
                summary = summarize_file(file_path, relative_path)
                if summary is None:
                    skipped += 1
                    skipped_paths.append(relative_path)
                    continue
                if upsert_file(connection, file_path, relative_path, summary):
                    changed += 1
                    changed_paths.append(relative_path)
                replace_symbols(connection, file_path, summary.symbols)
        deleted_paths = mark_deleted_files(connection, seen)
        deleted = len(deleted_paths)
        rebuild_project_layers(connection, project)
        finish_scan(connection, scan_id, scanned, changed, deleted, skipped)

    result = IndexResult(
        project=project,
        scanned=scanned,
        changed=changed,
        deleted=deleted,
        skipped=skipped,
        roots=tuple(str(path) for path in project.paths),
        changed_paths=tuple(changed_paths),
        deleted_paths=tuple(deleted_paths),
        skipped_paths=tuple(skipped_paths),
    )
    if record_activity:
        log_activity(
            "project.indexed",
            f"Indexed project memory {project.name}",
            {
                "project_id": project.id,
                "scanned": scanned,
                "changed": changed,
                "deleted": deleted,
                "skipped": skipped,
                "roots": result.roots,
                "changed_paths": result.changed_paths[:25],
                "deleted_paths": result.deleted_paths[:25],
                "skipped_paths": result.skipped_paths[:25],
            },
        )
    return result


def project_has_completed_scan(project_id_or_name: str) -> bool:
    try:
        project = load_project(project_id_or_name)
        if not project.database_path.exists():
            return False
        initialize_project_database(project.database_path)
        with db_connection(project.database_path) as connection:
            row = connection.execute("select 1 from scans where finished_at is not null limit 1").fetchone()
        return row is not None
    except (sqlite3.Error, OSError):
        return False
