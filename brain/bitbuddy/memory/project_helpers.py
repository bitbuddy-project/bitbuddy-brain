from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..database import db_connection
from .layers import MemoryLayer
from .store import create_memory
from .project_types import MAX_FILE_BYTES, SKIP_DIRS, SKIP_SUFFIXES, SYMBOL_PATTERNS, Project


def load_project(project_id_or_name: str) -> Project:
    from .project_registry import load_project as _load_project
    return _load_project(project_id_or_name)


def initialize_project_database(db_path: Path) -> None:
    from .project_schema import initialize_project_database as _initialize_project_database
    _initialize_project_database(db_path)


@dataclass(frozen=True)
class FileSummary:
    kind: str
    extension: str
    size_bytes: int
    mtime_ns: int
    content_hash: str
    summary: str
    symbols: tuple[tuple[str, str, int, int | None], ...]


def summarize_file(file_path: Path, relative_path: str) -> FileSummary | None:
    stat = file_path.stat()
    if stat.st_size > MAX_FILE_BYTES or file_path.suffix.lower() in SKIP_SUFFIXES:
        return None
    raw = file_path.read_bytes()
    if b"\x00" in raw[:4096]:
        return None
    text = raw.decode("utf-8", errors="replace")
    kind = classify_file(file_path)
    content_hash = hashlib.sha256(raw).hexdigest()
    symbols = tuple(sorted((*detect_symbols(text, kind), *detect_contract_symbols(file_path, relative_path, text, kind)), key=lambda symbol: symbol[2]))
    first_lines = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith(("//", "#"))]
    preview = " ".join(first_lines[:3])[:240]
    symbol_names = ", ".join(symbol[0] for symbol in symbols[:10])
    if symbol_names and preview:
        summary = f"symbols: {symbol_names}; preview: {preview}"
    elif symbol_names:
        summary = f"symbols: {symbol_names}"
    elif preview:
        summary = f"preview: {preview}"
    else:
        summary = "empty or comment-only file"

    return FileSummary(
        kind=kind,
        extension=file_path.suffix.lower(),
        size_bytes=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        content_hash=content_hash,
        summary=f"{relative_path}: {summary}",
        symbols=symbols,
    )


def detect_symbols(text: str, file_kind: str) -> tuple[tuple[str, str, int, int | None], ...]:
    symbols: list[tuple[str, str, int, int | None]] = []
    for kind, pattern in SYMBOL_PATTERNS.get(file_kind, []):
        for match in pattern.finditer(text):
            line_start = text.count("\n", 0, match.start()) + 1
            symbols.append((match.group(1), kind, line_start, None))
    return tuple(sorted(symbols, key=lambda symbol: symbol[2]))


def detect_contract_symbols(file_path: Path, relative_path: str, text: str, file_kind: str) -> tuple[tuple[str, str, int, int | None], ...]:
    symbols: list[tuple[str, str, int, int | None]] = []
    name = file_path.name
    if name == "package.json":
        try:
            package = json.loads(text)
        except json.JSONDecodeError:
            package = {}
        scripts = package.get("scripts") if isinstance(package, dict) else None
        if isinstance(scripts, dict):
            symbols.extend((f"npm run {script}", "command", line_number(text, f'"{script}"'), None) for script in scripts)
        for section in ("dependencies", "devDependencies", "peerDependencies"):
            dependencies = package.get(section) if isinstance(package, dict) else None
            if isinstance(dependencies, dict):
                symbols.extend((dependency, "package", line_number(text, f'"{dependency}"'), None) for dependency in dependencies)
    elif name == "pyproject.toml":
        try:
            pyproject = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            pyproject = {}
        project = pyproject.get("project") if isinstance(pyproject, dict) else None
        if isinstance(project, dict):
            scripts = project.get("scripts")
            if isinstance(scripts, dict):
                symbols.extend((command, "command", line_number(text, command), None) for command in scripts)
            for field in ("name", "version", "requires-python"):
                if field in project:
                    symbols.append((field, "config-field", line_number(text, field), None))
        tool = pyproject.get("tool") if isinstance(pyproject, dict) else None
        if isinstance(tool, dict):
            symbols.extend((f"tool.{key}", "config-field", line_number(text, key), None) for key in tool.keys())
    elif file_kind == "config":
        for key in top_level_config_keys(text, file_path.suffix.lower()):
            symbols.append((key, "config-field", line_number(text, key), None))

    if relative_path.endswith(("+page.svelte", "+layout.svelte", "+server.ts", "+server.js")):
        symbols.append((route_from_svelte_path(relative_path), "route", 1, None))
    if "server" in relative_path.lower() or "api" in relative_path.lower():
        for route in re.findall(r"path\.(?:startswith|endswith|removeprefix|removesuffix)\(['\"]([^'\"]+)", text):
            symbols.append((route, "api-route", line_number(text, route), None))
        for route in re.findall(r"path\s*==\s*['\"]([^'\"]+)", text):
            symbols.append((route, "api-route", line_number(text, route), None))
    return tuple(dedupe_symbols(symbols))


def dedupe_symbols(symbols: list[tuple[str, str, int, int | None]]) -> tuple[tuple[str, str, int, int | None], ...]:
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str, int, int | None]] = []
    for name, kind, line_start, line_end in symbols:
        key = (name, kind)
        if key in seen:
            continue
        seen.add(key)
        unique.append((name, kind, line_start, line_end))
    return tuple(unique)


def upsert_file(connection: sqlite3.Connection, file_path: Path, relative_path: str, summary: FileSummary) -> bool:
    existing = connection.execute("select content_hash from files where path = ?", (str(file_path),)).fetchone()
    changed = existing is None or existing[0] != summary.content_hash
    connection.execute(
        """
        insert into files (
            path, relative_path, kind, extension, size_bytes, mtime_ns, content_hash, summary, is_deleted
        ) values (?, ?, ?, ?, ?, ?, ?, ?, 0)
        on conflict(path) do update set
            relative_path = excluded.relative_path,
            kind = excluded.kind,
            extension = excluded.extension,
            size_bytes = excluded.size_bytes,
            mtime_ns = excluded.mtime_ns,
            content_hash = excluded.content_hash,
            summary = excluded.summary,
            is_deleted = 0,
            last_seen_at = current_timestamp,
            last_indexed_at = current_timestamp,
            last_verified_at = current_timestamp
        """,
        (
            str(file_path),
            relative_path,
            summary.kind,
            summary.extension,
            summary.size_bytes,
            summary.mtime_ns,
            summary.content_hash,
            summary.summary,
        ),
    )
    return changed


def replace_symbols(connection: sqlite3.Connection, file_path: Path, symbols: tuple[tuple[str, str, int, int | None], ...]) -> None:
    relative_path = connection.execute("select relative_path from files where path = ?", (str(file_path),)).fetchone()[0]
    connection.execute("delete from file_symbols where file_path = ?", (relative_path,))
    connection.executemany(
        "insert or ignore into file_symbols (file_path, name, kind, line_start, line_end) values (?, ?, ?, ?, ?)",
        [(relative_path, name, kind, line_start, line_end) for name, kind, line_start, line_end in symbols],
    )


def file_is_current(connection: sqlite3.Connection, file_path: Path, stat: os.stat_result) -> bool:
    row = connection.execute(
        "select size_bytes, mtime_ns, is_deleted from files where path = ?",
        (str(file_path),),
    ).fetchone()
    if row is None:
        return False
    size_bytes, mtime_ns, is_deleted = row
    return int(size_bytes) == stat.st_size and int(mtime_ns) == stat.st_mtime_ns and int(is_deleted) == 0


def mark_deleted_files(connection: sqlite3.Connection, seen: set[str]) -> list[str]:
    rows = connection.execute("select path, relative_path from files where is_deleted = 0").fetchall()
    deleted: list[str] = []
    for path, relative_path in rows:
        if path not in seen:
            connection.execute("update files set is_deleted = 1, last_indexed_at = current_timestamp where path = ?", (path,))
            deleted.append(relative_path)
    return deleted


def create_scan(connection: sqlite3.Connection) -> int:
    cursor = connection.execute("insert into scans default values")
    return int(cursor.lastrowid)


def finish_scan(connection: sqlite3.Connection, scan_id: int, scanned: int, changed: int, deleted: int, skipped: int) -> None:
    connection.execute(
        """
        update scans
        set finished_at = current_timestamp, scanned = ?, changed = ?, deleted = ?, skipped = ?
        where id = ?
        """,
        (scanned, changed, deleted, skipped, scan_id),
    )


def rebuild_project_layers(connection: sqlite3.Connection, project: Project) -> None:
    files = connection.execute(
        """
        select relative_path, kind, extension, content_hash, mtime_ns, summary, last_verified_at
        from files
        where is_deleted = 0
        order by relative_path
        """
    ).fetchall()
    paths = [row[0] for row in files]
    stack = infer_stack(files)
    repo_path = common_repo_path(project)
    verified_facts = verified_project_facts(project, files, stack)
    inferred_facts = inferred_project_facts(paths)
    repo_structure_snapshot = "\n".join(build_tree_snapshot(paths))
    needs_read = "Exact component behavior, route handlers, data mutations, side effects, and line-level logic require reading source files before edits."
    connection.execute(
        """
        insert into project_profile (id, name, repo_path, stack, purpose, current_status, verified_facts, inferred_facts, needs_read, repo_structure_snapshot)
        values (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        on conflict(id) do update set
            name = excluded.name,
            repo_path = excluded.repo_path,
            stack = excluded.stack,
            purpose = excluded.purpose,
            current_status = excluded.current_status,
            verified_facts = excluded.verified_facts,
            inferred_facts = excluded.inferred_facts,
            needs_read = excluded.needs_read,
            repo_structure_snapshot = excluded.repo_structure_snapshot,
            updated_at = current_timestamp
        """,
        (
            project.name,
            repo_path,
            stack,
            infer_purpose(paths),
            f"Operational memory indexed {len(files)} active files. Memory is role/contract/staleness only; exact logic requires reads.",
            verified_facts,
            inferred_facts,
            needs_read,
            repo_structure_snapshot,
        ),
    )
    connection.execute(
        """
        insert into architecture_summary (id, backend_layout, frontend_layout, important_packages, major_responsibilities)
        values (1, ?, ?, ?, ?)
        on conflict(id) do update set
            backend_layout = excluded.backend_layout,
            frontend_layout = excluded.frontend_layout,
            important_packages = excluded.important_packages,
            major_responsibilities = excluded.major_responsibilities,
            updated_at = current_timestamp
        """,
        (
            describe_layout(paths, {"backend", "server", "api", "brain", "src"}),
            describe_layout(paths, {"frontend", "web", "client", "ui", "routes", "components"}),
            important_packages(paths),
            major_responsibilities(files),
        ),
    )
    connection.execute("delete from file_index")
    symbol_rows = connection.execute("select file_path, name, kind, line_start from file_symbols order by file_path, line_start").fetchall()
    symbols_by_file: dict[str, list[tuple[str, str]]] = {}
    for file_path, name, kind, _line_start in symbol_rows:
        symbols_by_file.setdefault(file_path, []).append((name, kind))
    connection.executemany(
        """
        insert into file_index (path, role, key_responsibilities, when_to_read, related_files, important, content_hash, mtime_ns, last_verified_at, stale)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """,
        [
            (
                relative_path,
                file_role(relative_path, kind),
                key_responsibilities(relative_path, kind, symbols_by_file.get(relative_path, [])),
                when_to_read(relative_path, kind),
                related_files(relative_path, paths),
                1 if is_important_file(relative_path, kind) else 0,
                content_hash,
                mtime_ns,
                last_verified_at,
            )
            for relative_path, kind, _extension, content_hash, mtime_ns, _summary, last_verified_at in files
        ],
    )
    connection.execute("delete from symbol_contracts")
    connection.executemany(
        "insert or ignore into symbol_contracts (file_path, name, kind, contract, related_files) values (?, ?, ?, ?, ?)",
        [
            (
                file_path,
                name,
                kind,
                symbol_contract(kind, name),
                related_files(file_path, paths),
            )
            for file_path, name, kind, _line_start in symbol_rows
        ],
    )
    seed_decisions(connection)
    seed_current_task(connection)
    rebuild_read_rules(connection, paths)


def infer_stack(files: list[tuple]) -> str:
    extensions = {row[2] for row in files}
    stack: list[str] = []
    if ".py" in extensions:
        stack.append("Python")
    if ".svelte" in extensions:
        stack.append("Svelte")
    if ".ts" in extensions or ".tsx" in extensions:
        stack.append("TypeScript")
    if ".js" in extensions:
        stack.append("JavaScript")
    if ".rs" in extensions:
        stack.append("Rust")
    if ".go" in extensions:
        stack.append("Go")
    return ", ".join(stack) or "Unknown from indexed files"


def build_tree_snapshot(paths: list[str]) -> list[str]:
    # Group by directory to create a compact tree representation
    dirs = {}
    for p in paths:
        parent = str(Path(p).parent)
        if parent == ".":
            parent = ""
        dirs.setdefault(parent, []).append(Path(p).name)

    lines = []
    for d in sorted(dirs.keys()):
        if d:
            lines.append(f"{d}/")
            for f in sorted(dirs[d])[:10]: # limit to 10 files per dir to keep it compact
                lines.append(f"  {f}")
            if len(dirs[d]) > 10:
                lines.append(f"  ... and {len(dirs[d]) - 10} more")
        else:
            for f in sorted(dirs[d]):
                lines.append(f"{f}")
    return lines


def common_repo_path(project: Project) -> str:
    if len(project.paths) == 1:
        return str(project.paths[0])
    return ", ".join(str(path) for path in project.paths)


def verified_project_facts(project: Project, files: list[tuple], stack: str) -> str:
    paths = [row[0] for row in files]
    package_files = [path for path in paths if Path(path).name in {"README.md", "package.json", "pyproject.toml", "Cargo.toml", "go.mod", "vite.config.ts", "svelte.config.js"}]
    top_dirs = sorted({path.split("/", 1)[0] for path in paths if "/" in path})[:12]
    facts = [
        f"repo_path={common_repo_path(project)}",
        f"stack={stack}",
        f"indexed_file_count={len(files)}",
    ]
    if top_dirs:
        facts.append(f"top_dirs={', '.join(top_dirs)}")
    if package_files:
        facts.append(f"known_config_or_docs={', '.join(package_files[:12])}")
    return "; ".join(facts)


def inferred_project_facts(paths: list[str]) -> str:
    guesses: list[str] = []
    roles = {generic_file_role(path, classify_file(Path(path))) for path in paths}
    if any(role.startswith("frontend route") for role in roles):
        guesses.append("frontend routing likely exists")
    if any(role.startswith("UI component") for role in roles):
        guesses.append("componentized UI likely exists")
    if any(role.startswith("API") or role.startswith("backend") for role in roles):
        guesses.append("backend/API behavior likely exists")
    if any(role.startswith("model/type") for role in roles):
        guesses.append("shared data contracts likely exist")
    if any(role.startswith("state/store") for role in roles):
        guesses.append("client or application state modules likely exist")
    return "; ".join(guesses) or "No behavior-level inference beyond indexed paths. Read README/source before stating product intent."


def infer_purpose(paths: list[str]) -> str:
    if "README.md" in paths:
        return "See README.md for project purpose. Memory stores structure only until README is read."
    return "Purpose not explicitly known yet. Use compact memory as orientation, then inspect relevant docs/source."


def describe_layout(paths: list[str], markers: set[str]) -> str:
    matches = sorted({path.split("/")[0] for path in paths if any(marker in path.lower().split("/") for marker in markers)})
    return ", ".join(matches[:12]) if matches else "No clear layout detected yet"


def important_packages(paths: list[str]) -> str:
    package_files = [path for path in paths if Path(path).name in {"package.json", "pyproject.toml", "Cargo.toml", "go.mod", "requirements.txt", "svelte.config.js", "vite.config.ts"}]
    return ", ".join(package_files[:20]) or "No package/config files indexed yet"


def major_responsibilities(files: list[tuple]) -> str:
    kinds = sorted({row[1] for row in files})
    return ", ".join(kinds) if kinds else "No responsibilities inferred yet"


def file_role(path: str, kind: str) -> str:
    return generic_file_role(path, kind)


def generic_file_role(path: str, kind: str) -> str:
    name = Path(path).name
    lowered_name = name.lower()
    lowered_path = path.lower()
    if name in {"models.rs", "model.rs", "models.py", "schema.ts", "types.ts"}:
        return "model/type contract definitions"
    if name in {"README.md", "readme.md"}:
        return "Human-facing project overview and usage notes"
    if name in {"pyproject.toml", "package.json", "Cargo.toml", "go.mod"}:
        return "Project/package configuration and commands"
    if name in {"vite.config.ts", "vite.config.js", "svelte.config.js", "next.config.js", "tsconfig.json"} or "config" in lowered_name or kind == "config":
        return "Configuration"
    if path.endswith(("+page.svelte", "+layout.svelte", "+server.ts", "+server.js")) or "/routes/" in lowered_path:
        return "frontend route/page composition"
    if "store" in lowered_name or "/stores/" in lowered_path:
        return "state/store module"
    if "api" in lowered_name or "/api/" in lowered_path or "client" in lowered_name:
        return "API/client helper"
    if "component" in lowered_path or kind == "svelte":
        return "UI component"
    if "server" in lowered_path or kind in {"python", "rust", "go"}:
        return "backend/source behavior"
    return f"{kind} source file"


def key_responsibilities(path: str, kind: str, symbols: list[tuple[str, str]]) -> str:
    responsibilities: list[str] = []
    role = generic_file_role(path, kind)
    if role == "model/type contract definitions":
        responsibilities.extend(["data shape/contracts", "serialized fields or public types", "dependent call-site expectations"])
    elif role == "Project/package configuration and commands":
        responsibilities.extend(["dependencies", "commands/scripts", "runtime/tooling assumptions"])
    elif role == "Configuration":
        responsibilities.extend(["runtime/build configuration", "tooling assumptions", "environment-sensitive defaults"])
    elif role == "frontend route/page composition":
        responsibilities.extend(["route/page composition", "UI rendering boundaries", "route-local state/events"])
    elif role == "UI component":
        responsibilities.extend(["UI rendering", "component state/events", "props or local interaction boundaries"])
    elif role == "state/store module":
        responsibilities.extend(["shared state shape", "state mutations", "consumers that depend on this state"])
    elif role == "API/client helper":
        responsibilities.extend(["request/response contract", "client/server boundary", "call-site expectations"])
    elif role == "backend/source behavior":
        responsibilities.extend(["backend behavior", "API/service contracts", "side effects and persistence boundaries"])
    else:
        responsibilities.append(f"{kind} behavior or configuration")

    symbol_names = [name for name, symbol_kind in symbols if symbol_kind not in {"package"}][:6]
    if symbol_names:
        responsibilities.append("known symbols: " + ", ".join(symbol_names))
    return "; ".join(dict.fromkeys(responsibilities))


def when_to_read(path: str, kind: str) -> str:
    name = Path(path).name
    role = generic_file_role(path, kind)
    if name in {"models.rs", "model.rs", "models.py", "schema.ts", "types.ts"}:
        return "Read before changing public fields, serialized shapes, generated types, or dependent call-site contracts."
    if name in {"pyproject.toml", "package.json", "Cargo.toml", "go.mod"}:
        return "Read before changing dependencies, commands, packaging, or runtime assumptions."
    if role in {"frontend route/page composition", "UI component"}:
        return "Read before changing UI behavior, layout, styling, or route flow."
    if role == "state/store module":
        return "Read before changing shared state shape, mutation behavior, or consumer expectations."
    if role == "API/client helper":
        return "Read before changing request/response shape, endpoint use, or client/server boundary assumptions."
    if kind in {"python", "typescript", "javascript", "rust", "go"}:
        return "Read before editing related behavior; memory is not a substitute for exact logic."
    return "Read when this file is directly relevant to the task."


def related_files(path: str, paths: list[str]) -> str:
    current = Path(path)
    stem = current.stem
    directory = str(current.parent)
    related = [candidate for candidate in paths if candidate != path and (Path(candidate).stem == stem or str(Path(candidate).parent) == directory)]
    return ", ".join(related[:8])


def is_important_file(path: str, kind: str) -> bool:
    name = Path(path).name
    return (
        name in {"README.md", "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "vite.config.ts", "svelte.config.js"}
        or kind in {"python", "typescript", "javascript", "svelte", "rust", "go"}
    )


def symbol_contract(kind: str, name: str) -> str:
    if kind == "command":
        return f"Command `{name}` is declared. Read the package/config file before running or changing it."
    if kind in {"route", "api-route"}:
        return f"Route `{name}` is declared. Read the route/server file before changing request or UI behavior."
    if kind == "config-field":
        return f"Config field `{name}` is declared. Read the config file before changing runtime assumptions."
    if kind == "package":
        return f"Package `{name}` is declared. Read dependency config before adding, removing, or assuming API availability."
    return f"{kind} `{name}` exists in memory. Read the file before relying on exact arguments, fields, or line-level behavior."


def refresh_staleness(connection: sqlite3.Connection) -> None:
    rows = connection.execute("select path, relative_path, mtime_ns, content_hash from files where is_deleted = 0").fetchall()
    for absolute_path, relative_path, remembered_mtime_ns, _content_hash in rows:
        path = Path(absolute_path)
        stale = 1
        if path.exists():
            try:
                stale = 0 if path.stat().st_mtime_ns == int(remembered_mtime_ns) else 1
            except OSError:
                stale = 1
        connection.execute("update file_index set stale = ? where path = ?", (stale, relative_path))


def top_level_config_keys(text: str, suffix: str) -> tuple[str, ...]:
    if suffix == ".json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return ()
        return tuple(str(key) for key in data.keys()) if isinstance(data, dict) else ()
    if suffix == ".toml":
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return ()
        return tuple(str(key) for key in data.keys()) if isinstance(data, dict) else ()
    if suffix in {".yaml", ".yml"}:
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            return ()
        return tuple(str(key) for key in data.keys()) if isinstance(data, dict) else ()
    return ()


def route_from_svelte_path(relative_path: str) -> str:
    parts = list(Path(relative_path).parts)
    if "routes" in parts:
        parts = parts[parts.index("routes") + 1 :]
    if not parts:
        return "/"
    route_parts = parts[:-1]
    cleaned = [part for part in route_parts if not part.startswith("(")]
    return "/" + "/".join(cleaned) if cleaned else "/"


def line_number(text: str, needle: str) -> int:
    index = text.find(needle)
    if index < 0:
        return 1
    return text.count("\n", 0, index) + 1


def row_dict(row: tuple | None, keys: list[str]) -> dict[str, object]:
    if row is None:
        return {}
    return {key: row[index] for index, key in enumerate(keys)}


def split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def seed_decisions(connection: sqlite3.Connection) -> None:
    connection.executemany(
        "insert or ignore into decisions_preferences (decision, constraint_text) values (?, ?)",
        [
            ("Project paths are read-only", "BitBuddy may index and summarize but must not write/delete project files."),
            ("No exact logic claims from memory alone", "Read source files before line-level claims or edits."),
            ("Keep memory compact", "Load project model first, retrieve exact files/snippets only when needed."),
        ],
    )


def seed_current_task(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        update current_task_memory
        set task = ?, status = ?, notes = ?, updated_at = current_timestamp
        where task = ?
        """,
        (
            "No active project-specific task recorded",
            "needs-input",
            "Record the current task before using memory to resume project work.",
            "Maintain compact project memory",
        ),
    )
    connection.execute(
        "insert or ignore into current_task_memory (task, status, notes) values (?, ?, ?)",
        (
            "No active project-specific task recorded",
            "needs-input",
            "Record the current task before using memory to resume project work.",
        ),
    )


def rebuild_read_rules(connection: sqlite3.Connection, paths: list[str]) -> None:
    rules: dict[str, tuple[str, str]] = {}

    # 1. Self-referential memory system rules (if BitBuddy project)
    if any("brain/bitbuddy" in str(p) for p in paths):
        rules["project-memory"] = ("brain/bitbuddy/memory/project.py", "Before changing project memory behavior, read the implementation logic.")
        rules["memory-storage"] = ("brain/bitbuddy/paths.py, brain/bitbuddy/memory/project.py", "Read config/storage files that control memory paths or SQLite.")
        rules["memory-api"] = ("brain/bitbuddy/server.py", "Read server.py if memory is exposed through the backend API.")
        rules["memory-frontend"] = ("web/src/lib/api/bitbuddy.ts", "Read bitbuddy.ts if the frontend consumes memory.")

    role_groups: dict[str, list[str]] = {}
    for path in paths:
        role_groups.setdefault(generic_file_role(path, classify_file(Path(path))), []).append(path)

    config_files = sorted(role_groups.get("Project/package configuration and commands", []) + role_groups.get("Configuration", []), key=rule_file_priority)
    ui_files = sorted(role_groups.get("frontend route/page composition", []) + role_groups.get("UI component", []), key=rule_file_priority)
    backend_files = sorted(role_groups.get("backend/source behavior", []) + role_groups.get("API/client helper", []), key=rule_file_priority)
    model_files = sorted(role_groups.get("model/type contract definitions", []), key=rule_file_priority)
    state_files = sorted(role_groups.get("state/store module", []), key=rule_file_priority)

    if config_files:
        rules["dependencies/config"] = (", ".join(config_files[:10]), "Config files determine available packages, scripts, and runtime assumptions.")
    if model_files:
        files = minimal_rule_files(model_files, backend_files, ui_files, state_files, limit=10)
        rules["model/type contracts"] = (", ".join(files), "Before changing shared data contracts, inspect model/type definitions, dependent routes/services, and UI/API consumers.")
    if ui_files:
        files = minimal_rule_files(ui_files, state_files, backend_files, limit=10)
        rules["frontend/ui"] = (", ".join(files), "UI changes should start from route/component files, then related state/API helpers in the same area.")
    if backend_files:
        files = minimal_rule_files(backend_files, model_files, config_files, limit=10)
        rules["backend/api"] = (", ".join(files), "Backend changes require reading service/API files, then model/type contracts and config files that shape behavior.")
    for area, area_files in feature_area_groups(paths).items():
        files = minimal_rule_files(area_files, model_files, state_files, backend_files, limit=8)
        if len(files) >= 2:
            rules[f"area:{area}"] = (", ".join(files), "Before editing this area, inspect the local cluster plus nearby state/API/model companions.")
    connection.execute("delete from read_before_editing_rules")
    connection.executemany(
        "insert or ignore into read_before_editing_rules (area, files_to_read, reason) values (?, ?, ?)",
        [(area, files, reason) for area, (files, reason) in rules.items()],
    )


def minimal_rule_files(*groups: list[str], limit: int) -> list[str]:
    selected: list[str] = []
    for group in groups:
        for path in sorted(group, key=rule_file_priority):
            if path not in selected:
                selected.append(path)
            if len(selected) >= limit:
                return selected
    return selected


def rule_file_priority(path: str) -> tuple[int, str]:
    lowered = path.lower()
    role = generic_file_role(path, classify_file(Path(path)))
    priority = 10
    if role == "model/type contract definitions":
        priority = 0
    elif role in {"frontend route/page composition", "backend/source behavior", "API/client helper"}:
        priority = 1
    elif role == "state/store module":
        priority = 2
    elif role == "UI component":
        priority = 3
    elif "config" in lowered:
        priority = 4
    return (priority, path)


def feature_area_groups(paths: list[str]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for path in paths:
        area = feature_area(path)
        if not area:
            continue
        groups.setdefault(area, []).append(path)
    return {area: sorted(files, key=rule_file_priority) for area, files in groups.items() if len(files) >= 2}


def feature_area(path: str) -> str:
    parts = list(Path(path).parts)
    if len(parts) < 2:
        return ""
    generic_dirs = {"src", "lib", "components", "routes", "pages", "app", "api", "stores", "store", "types", "models", "server", "client"}
    meaningful = [part for part in parts[:-1] if part not in generic_dirs and not part.startswith("(")]
    if meaningful:
        return "/".join(meaningful[-2:])
    parent = str(Path(path).parent)
    return parent if parent not in {".", ""} else ""


def ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in connection.execute(f"pragma table_info({table})")}
    if column not in columns:
        try:
            connection.execute(f"alter table {table} add column {column} {definition}")
        except sqlite3.OperationalError as error:
            if "non-constant default" not in str(error).lower() or "current_timestamp" not in definition.lower():
                raise
            column_type = definition.split("default", 1)[0].strip() or "text"
            connection.execute(f"alter table {table} add column {column} {column_type}")
            connection.execute(f"update {table} set {column} = current_timestamp where {column} is null")


def iter_project_files(root: Path):
    if root.is_file():
        yield root
        return
    for current_root, dirnames, filenames in os.walk(root):
        dirnames[:] = [dirname for dirname in dirnames if dirname not in SKIP_DIRS]
        for filename in filenames:
            yield Path(current_root) / filename


def resolve_allowed_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"Project path does not exist: {path}")
    if path == Path.home():
        raise ValueError("Refusing broad home-directory access. Add a specific project directory or file instead.")
    return path


def relative_to_any(file_path: Path, roots: tuple[Path, ...]) -> str:
    for root in roots:
        try:
            return str(file_path.relative_to(root if root.is_dir() else root.parent))
        except ValueError:
            continue
    return file_path.name


def classify_file(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix in {".py"}:
        return "python"
    if suffix in {".js", ".mjs", ".cjs"}:
        return "javascript"
    if suffix in {".ts", ".tsx"}:
        return "typescript"
    if suffix == ".svelte":
        return "svelte"
    if suffix in {".md", ".mdx"}:
        return "markdown"
    if suffix in {".json", ".yaml", ".yml", ".toml"}:
        return "config"
    if suffix in {".css", ".scss", ".sass"}:
        return "stylesheet"
    if suffix in {".rs"}:
        return "rust"
    if suffix in {".go"}:
        return "go"
    return "text"


def record_decision(project_id: str, decision: str, constraint: str, source: str = "user") -> None:
    project = load_project(project_id)
    with db_connection(project.database_path) as connection:
        connection.execute(
            "insert into decisions_preferences (decision, constraint_text, source) values (?, ?, ?)",
            (decision, constraint, source)
        )

def update_task(project_id: str, task: str, status: str, notes: str = "") -> None:
    project = load_project(project_id)
    with db_connection(project.database_path) as connection:
        connection.execute(
            """
            insert into current_task_memory (task, status, notes)
            values (?, ?, ?)
            on conflict(task) do update set
                status = excluded.status,
                notes = excluded.notes,
                updated_at = current_timestamp
            """,
            (task, status, notes)
        )

def set_verified_fact(project_id: str, fact_key: str, fact_value: str) -> None:
    project = load_project(project_id)
    with db_connection(project.database_path) as connection:
        profile = connection.execute("select verified_facts from project_profile where id = 1").fetchone()
        facts = {}
        if profile and profile[0]:
            for part in profile[0].split("; "):
                if "=" in part:
                    k, v = part.split("=", 1)
                    facts[k] = v
        facts[fact_key] = fact_value
        verified_str = "; ".join(f"{k}={v}" for k, v in sorted(facts.items()))
        connection.execute("update project_profile set verified_facts = ?, updated_at = current_timestamp where id = 1", (verified_str,))


def update_project_profile_field(project_id: str, field: str, value: str) -> None:
    """Update a single column on project_profile (row id=1)."""
    project = load_project(project_id)
    initialize_project_database(project.database_path)
    with db_connection(project.database_path) as connection:
        connection.execute(
            f"update project_profile set {field} = ?, updated_at = current_timestamp where id = 1",
            (value,),
        )
    try:
        from ..librarian import regenerate_card
        regenerate_card(project_id)
    except Exception:
        pass


def update_project_purpose(project_id: str, purpose: str) -> None:
    """Update the purpose field of a project's profile."""
    update_project_profile_field(project_id, "purpose", purpose)


def slugify(value: str) -> str:
    slug = "".join(character.lower() if character.isalnum() else "-" for character in value).strip("-")
    return "-".join(part for part in slug.split("-") if part) or "project"


def stable_project_id(name: str, path: str | Path) -> str:
    canonical_path = Path(path).expanduser().resolve()
    slug = slugify(name or canonical_path.name)
    digest = hashlib.sha256(str(canonical_path).encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}"
