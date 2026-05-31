from __future__ import annotations

import sqlite3
from pathlib import Path

from ..database import db_connection
from .project_helpers import ensure_column

def initialize_project_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with db_connection(db_path) as connection:
        connection.execute(
            """
            create table if not exists files (
                path text primary key,
                relative_path text not null,
                kind text not null,
                extension text not null,
                size_bytes integer not null,
                mtime_ns integer not null,
                content_hash text not null,
                summary text not null,
                is_deleted integer not null default 0,
                first_seen_at text default current_timestamp,
                last_seen_at text default current_timestamp,
                last_verified_at text default current_timestamp,
                last_indexed_at text default current_timestamp
            )
            """
        )
        ensure_column(connection, "files", "relative_path", "text not null default ''")
        ensure_column(connection, "files", "extension", "text not null default ''")
        ensure_column(connection, "files", "mtime_ns", "integer not null default 0")
        ensure_column(connection, "files", "content_hash", "text not null default ''")
        ensure_column(connection, "files", "is_deleted", "integer not null default 0")
        ensure_column(connection, "files", "first_seen_at", "text default current_timestamp")
        ensure_column(connection, "files", "last_seen_at", "text default current_timestamp")
        ensure_column(connection, "files", "last_verified_at", "text default current_timestamp")
        connection.execute(
            """
            create table if not exists file_symbols (
                id integer primary key autoincrement,
                file_path text not null,
                name text not null,
                kind text not null,
                line_start integer not null,
                line_end integer,
                unique(file_path, name, kind, line_start)
            )
            """
        )
        connection.execute(
            """
            create table if not exists project_profile (
                id integer primary key check (id = 1),
                name text not null,
                repo_path text not null,
                stack text not null,
                purpose text not null,
                current_status text not null,
                verified_facts text not null default '',
                inferred_facts text not null default '',
                needs_read text not null default '',
                updated_at text default current_timestamp
            )
            """
        )
        ensure_column(connection, "project_profile", "verified_facts", "text not null default ''")
        ensure_column(connection, "project_profile", "inferred_facts", "text not null default ''")
        ensure_column(connection, "project_profile", "needs_read", "text not null default ''")
        ensure_column(connection, "project_profile", "repo_structure_snapshot", "text not null default ''")
        connection.execute(
            """
            create table if not exists architecture_summary (
                id integer primary key check (id = 1),
                backend_layout text not null,
                frontend_layout text not null,
                important_packages text not null,
                major_responsibilities text not null,
                updated_at text default current_timestamp
            )
            """
        )
        connection.execute(
            """
            create table if not exists file_index (
                path text primary key,
                role text not null,
                key_responsibilities text not null default '',
                when_to_read text not null,
                related_files text not null,
                important integer not null default 0,
                content_hash text not null,
                mtime_ns integer not null,
                last_verified_at text default current_timestamp,
                stale integer not null default 0
            )
            """
        )
        ensure_column(connection, "file_index", "key_responsibilities", "text not null default ''")
        connection.execute(
            """
            create table if not exists symbol_contracts (
                id integer primary key autoincrement,
                file_path text not null,
                name text not null,
                kind text not null,
                contract text not null,
                related_files text not null default '',
                unique(file_path, name, kind)
            )
            """
        )
        connection.execute(
            """
            create table if not exists decisions_preferences (
                id integer primary key autoincrement,
                decision text not null,
                constraint_text text not null,
                source text not null default 'system',
                created_at text default current_timestamp,
                unique(decision, constraint_text)
            )
            """
        )
        connection.execute(
            """
            create table if not exists current_task_memory (
                id integer primary key autoincrement,
                task text not null,
                status text not null,
                notes text not null default '',
                updated_at text default current_timestamp,
                unique(task)
            )
            """
        )
        connection.execute(
            """
            create table if not exists read_before_editing_rules (
                id integer primary key autoincrement,
                area text not null,
                files_to_read text not null,
                reason text not null,
                updated_at text default current_timestamp,
                unique(area)
            )
            """
        )
        connection.execute(
            """
            create table if not exists project_notes (
                id integer primary key autoincrement,
                category text not null,
                content text not null,
                source_chat_id text,
                memory_id text,
                layer text not null default 'project',
                kind text not null default 'fact',
                tags text not null default '',
                metadata text not null default '{}',
                created_at text default current_timestamp
            )
            """
        )
        connection.execute(
            """
            create table if not exists project_memory_overrides (
                id integer primary key autoincrement,
                section text not null,
                item_key text not null,
                data text not null,
                source_chat_id text,
                updated_at text default current_timestamp,
                unique(section, item_key)
            )
            """
        )
        ensure_column(connection, "project_notes", "memory_id", "text")
        ensure_column(connection, "project_notes", "layer", "text not null default 'project'")
        ensure_column(connection, "project_notes", "kind", "text not null default 'fact'")
        ensure_column(connection, "project_notes", "tags", "text not null default ''")
        connection.execute(
            """
            create table if not exists scans (
                id integer primary key autoincrement,
                started_at text default current_timestamp,
                finished_at text,
                scanned integer default 0,
                changed integer default 0,
                deleted integer default 0,
                skipped integer default 0
            )
            """
        )
