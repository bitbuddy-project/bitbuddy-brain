from __future__ import annotations

from ..database import db_connection
from .project_helpers import refresh_staleness, row_dict, split_csv
from .project_overrides import apply_project_memory_overrides, load_project_memory_overrides
from .project_registry import load_project
from .project_schema import initialize_project_database

def project_brief(project_id_or_name: str) -> str:
    """Provides a high-level project briefing. Compact enough for permanent context injection."""
    project = load_project(project_id_or_name)
    model = project_model(project.id, limit=12)
    card = model.get("project_card") if isinstance(model.get("project_card"), dict) else {}
    architecture = model.get("architecture_summary") if isinstance(model.get("architecture_summary"), dict) else {}
    rules = model.get("read_before_editing_rules") if isinstance(model.get("read_before_editing_rules"), list) else []
    files = model.get("file_index") if isinstance(model.get("file_index"), list) else []
    decisions = model.get("decisions_preferences") if isinstance(model.get("decisions_preferences"), list) else []
    tasks = model.get("current_task_memory") if isinstance(model.get("current_task_memory"), list) else []
    project_notes = model.get("project_notes") if isinstance(model.get("project_notes"), list) else []

    lines = [f"# {project.name} (Brief)", "", "Project overview from BitBuddy operational memory.", ""]
    if card:
        lines.extend(
            [
                "## Project card",
                f"- path: {card.get('repo_path', '')}",
                f"- stack: {card.get('stack', '')}",
                f"- purpose: {card.get('purpose', '')}",
                f"- status: {card.get('current_status', '')}",
                f"- verified facts: {card.get('verified_facts', '')}",
                f"- needs read: {card.get('needs_read', '')}",
                "",
            ]
        )
    if architecture:
        lines.extend(
            [
                "## Architecture summary",
                f"- backend: {architecture.get('backend_layout', '')}",
                f"- frontend: {architecture.get('frontend_layout', '')}",
                f"- responsibilities: {architecture.get('major_responsibilities', '')}",
                "",
            ]
        )
    if rules:
        lines.append("## Read-before-editing rules")
        for rule in rules[:8]:
            files_to_read = ", ".join(rule.get("files_to_read", [])) if isinstance(rule, dict) else ""
            lines.append(f"- {rule.get('area', '')}: read {files_to_read}. Reason: {rule.get('reason', '')}")
        lines.append("")

    if files:
        lines.append("## Important entry points/configs")
        for item in files[:12]:
            lines.append(f"- {item.get('path', '')}: {item.get('role', '')}")
        lines.append("")

    if decisions:
        lines.append("## Recent decisions/preferences")
        for decision in decisions[:6]:
            lines.append(f"- {decision.get('decision', '')}: {decision.get('constraint', '')}")
        lines.append("")

    if tasks:
        lines.append("## Current task memory")
        for task in tasks[:5]:
            lines.append(f"- {task.get('task', '')} [{task.get('status', '')}]: {task.get('notes', '')}")
        lines.append("")

    if project_notes:
        lines.append("## Project notes")
        for note in project_notes[:8]:
            lines.append(f"- {note.get('category', '')} ({note.get('created_at', '')}): {note.get('content', '')}")
        lines.append("")

    lines.append("Note: BitBuddy has a deeper indexed file map. Ask for details on specific paths or areas if needed.")

    return "\n".join(lines)


def project_map(project_id_or_name: str, detail_level: str = "deep", limit: int = 200) -> str:
    project = load_project(project_id_or_name)
    initialize_project_database(project.database_path)
    lines = [f"# {project.name}", "", "Read-only project memory map. Exact line-level behavior requires reading source files first.", ""]
    with db_connection(project.database_path) as connection:
        refresh_staleness(connection)
        overrides = load_project_memory_overrides(connection)

        # 1. Project card and snapshot (included in all levels)
        card = connection.execute(
            "select repo_path, stack, purpose, current_status, verified_facts, inferred_facts, needs_read, repo_structure_snapshot from project_profile where id = 1"
        ).fetchone()
        if card:
            repo_path, stack, purpose, current_status, verified_facts, inferred_facts, needs_read, repo_structure_snapshot = card
            profile = overrides.get("project_overview", {}).get("profile", {})
            stack = profile.get("stack", stack)
            purpose = profile.get("purpose", purpose)
            current_status = profile.get("current_status", current_status)
            verified_facts = profile.get("verified_facts", verified_facts)
            inferred_facts = profile.get("inferred_facts", inferred_facts)
            needs_read = profile.get("needs_read", needs_read)
            repo_structure_snapshot = profile.get("repo_structure_snapshot", repo_structure_snapshot)
            lines.extend(
                [
                    "## Project card",
                    f"- name: {project.name}",
                    f"- repo path: {repo_path}",
                    f"- stack: {stack}",
                    f"- purpose: {purpose}",
                    f"- current status: {current_status}",
                    f"- verified: {verified_facts}",
                    f"- inferred: {inferred_facts}",
                    f"- needs read: {needs_read}",
                    "",
                ]
            )
            if detail_level in ("briefing", "operational", "task", "deep"):
                lines.extend([
                    "## Repository Structure Snapshot",
                    repo_structure_snapshot,
                    "",
                ])

        if detail_level == "identity":
            return "\n".join(lines)

        # 2. Architecture summary
        architecture = connection.execute(
            "select backend_layout, frontend_layout, important_packages, major_responsibilities from architecture_summary where id = 1"
        ).fetchone()
        if architecture:
            backend_layout, frontend_layout, important_packages, major_responsibilities = architecture
            architecture_override = overrides.get("architecture_summary", {}).get("summary", {})
            backend_layout = architecture_override.get("backend_layout", backend_layout)
            frontend_layout = architecture_override.get("frontend_layout", frontend_layout)
            important_packages = architecture_override.get("important_packages", important_packages)
            major_responsibilities = architecture_override.get("major_responsibilities", major_responsibilities)
            lines.extend(
                [
                    "## Architecture summary",
                    f"- backend: {backend_layout}",
                    f"- frontend: {frontend_layout}",
                    f"- important packages: {important_packages}",
                    f"- responsibilities: {major_responsibilities}",
                    "",
                ]
            )

        if detail_level == "briefing":
            return "\n".join(lines)

        # 3. Read-before-editing rules
        rules = connection.execute(
            "select area, files_to_read, reason from read_before_editing_rules order by area limit 12"
        ).fetchall()
        if rules:
            lines.append("## Read-before-editing rules")
            for area, files_to_read, reason in rules:
                lines.append(f"- {area}: read {files_to_read} first. Reason: {reason}")
            lines.append("")

        # 4. Decisions/preferences
        decisions = connection.execute("select decision, constraint_text from decisions_preferences order by id limit 12").fetchall()
        if decisions:
            lines.extend(["## Decisions/preferences"])
            for decision, constraint in decisions:
                lines.append(f"- {decision}: {constraint}")
            lines.append("")

        # 5. Current task memory
        tasks = connection.execute("select task, status, notes from current_task_memory order by id limit 8").fetchall()
        if tasks:
            lines.extend(["## Current task memory"])
            for task, status, notes in tasks:
                lines.append(f"- {task} [{status}]: {notes}")
            lines.append("")

        project_notes = connection.execute(
            "select category, content, created_at from project_notes order by id desc limit 16"
        ).fetchall()
        if project_notes:
            lines.extend(["## Project notes"])
            for category, content, created_at in project_notes:
                lines.append(f"- {category} ({created_at}): {content}")
            lines.append("")

        if detail_level == "operational":
            return "\n".join(lines)

        # 6. File index (limited for task, full for deep)
        file_limit = limit if detail_level == "deep" else min(limit, 20)

        lines.extend(
            [
                "## File index",
                "These are compact memories. Verify exact logic from files before making line-level claims or edits.",
            ]
        )
        rows = connection.execute(
            """
            select path, role, key_responsibilities, when_to_read, related_files, stale, last_verified_at, content_hash, mtime_ns
            from file_index
            where important = 1
            order by path
            limit ?
            """,
            (file_limit,),
        ).fetchall()
        for relative_path, role, key_responsibilities, when_to_read, related_files, stale, last_verified_at, content_hash, mtime_ns in rows:
            stale_text = "stale" if stale else f"verified {last_verified_at}"
            lines.append(f"- {relative_path} ({stale_text})")
            lines.append(f"  role: {role}")
            lines.append(f"  responsibilities: {key_responsibilities}")
            lines.append(f"  related: {related_files}")
            lines.append(f"  read before editing: {when_to_read}")
            lines.append(f"  staleness: hash={str(content_hash)[:12]}, mtime_ns={mtime_ns}, last_verified={last_verified_at}")
            symbols = connection.execute(
                """
                select name, kind, contract
                from symbol_contracts
                where file_path = ?
                order by name
                limit 8
                """,
                (relative_path,),
            ).fetchall()
            if symbols:
                symbol_text = ", ".join(f"{name}:{kind} ({contract})" for name, kind, contract in symbols)
                lines.append(f"  contracts: {symbol_text}")

    return "\n".join(lines)


def project_model(project_id_or_name: str, limit: int = 80) -> dict[str, object]:
    project = load_project(project_id_or_name)
    initialize_project_database(project.database_path)
    with db_connection(project.database_path) as connection:
        refresh_staleness(connection)
        card = connection.execute(
            "select name, repo_path, stack, purpose, current_status, verified_facts, inferred_facts, needs_read, repo_structure_snapshot, updated_at from project_profile where id = 1"
        ).fetchone()
        architecture = connection.execute(
            "select backend_layout, frontend_layout, important_packages, major_responsibilities, updated_at from architecture_summary where id = 1"
        ).fetchone()
        files = connection.execute(
            """
            select path, role, key_responsibilities, when_to_read, related_files, stale, content_hash, mtime_ns, last_verified_at
            from file_index
            where important = 1
            order by path
            limit ?
            """,
            (limit,),
        ).fetchall()
        symbols = connection.execute(
            """
            select file_path, name, kind, contract, related_files
            from symbol_contracts
            order by file_path, kind, name
            limit ?
            """,
            (limit,),
        ).fetchall()
        decisions = connection.execute("select decision, constraint_text, source from decisions_preferences order by id limit 24").fetchall()
        tasks = connection.execute("select task, status, notes, updated_at from current_task_memory order by id limit 16").fetchall()
        rules = connection.execute("select area, files_to_read, reason from read_before_editing_rules order by area limit 16").fetchall()
        project_notes = connection.execute(
            "select category, content, source_chat_id, created_at, memory_id, layer, kind, tags from project_notes order by id desc limit 24"
        ).fetchall()
        overrides = load_project_memory_overrides(connection)

    model = {
        "project_card": row_dict(
            card,
            ["name", "repo_path", "stack", "purpose", "current_status", "verified_facts", "inferred_facts", "needs_read", "repo_structure_snapshot", "updated_at"],
        ),
        "architecture_summary": row_dict(
            architecture,
            ["backend_layout", "frontend_layout", "important_packages", "major_responsibilities", "updated_at"],
        ),
        "file_index": [
            {
                "path": path,
                "role": role,
                "key_responsibilities": split_csv(responsibilities),
                "when_to_read": when,
                "related_files": split_csv(related),
                "stale": bool(stale),
                "content_hash": content_hash,
                "mtime_ns": mtime_ns,
                "last_verified_at": last_verified_at,
            }
            for path, role, responsibilities, when, related, stale, content_hash, mtime_ns, last_verified_at in files
        ],
        "symbol_contracts": [
            {"file_path": file_path, "name": name, "kind": kind, "contract": contract, "related_files": split_csv(related)}
            for file_path, name, kind, contract, related in symbols
        ],
        "decisions_preferences": [
            {"decision": decision, "constraint": constraint, "source": source} for decision, constraint, source in decisions
        ],
        "current_task_memory": [
            {"task": task, "status": status, "notes": notes, "updated_at": updated_at} for task, status, notes, updated_at in tasks
        ],
        "read_before_editing_rules": [
            {"area": area, "files_to_read": split_csv(files_to_read), "reason": reason} for area, files_to_read, reason in rules
        ],
        "project_notes": [
            {
                "category": category,
                "content": content,
                "source_chat_id": source_chat_id,
                "created_at": created_at,
                "memory_id": memory_id,
                "layer": layer,
                "kind": kind,
                "tags": split_csv(tags),
            }
            for category, content, source_chat_id, created_at, memory_id, layer, kind, tags in project_notes
        ],
        "retrieval_policy": "Load this small model first. Before editing or making exact line-level claims, read the relevant source files listed by read_before_editing_rules and file_index. Project notes are durable user/model-added deltas that may clarify purpose, architecture, decisions, or current tasks.",
    }
    apply_project_memory_overrides(model, overrides)
    return model
