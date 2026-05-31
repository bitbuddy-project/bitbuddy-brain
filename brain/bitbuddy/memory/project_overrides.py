from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..database import db_connection
from .layers import MemoryLayer
from .store import create_memory
from .project_registry import load_project
from .project_schema import initialize_project_database

def record_project_note(project_id: str, category: str, content: str, source_chat_id: str | None = None, metadata: dict[str, Any] | None = None) -> int:
    """Add a new note to a project's memory database."""
    project = load_project(project_id)
    initialize_project_database(project.database_path)
    clean_category = category.strip() or "fact"
    tags = ["project", clean_category]
    memory = create_memory(
        layer=MemoryLayer.PROJECT,
        kind=clean_category,
        title=f"{project.name}: {clean_category} note",
        summary=content,
        importance=4 if clean_category in {"decision", "architecture"} else 3,
        conversation_id=source_chat_id,
        project_id=project.id,
        source="project_note",
        tags=tags,
        metadata={**(metadata or {}), "project_name": project.name},
    )
    with db_connection(project.database_path) as connection:
        cursor = connection.execute(
            """
            insert into project_notes (category, content, source_chat_id, memory_id, layer, kind, tags, metadata)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (clean_category, content, source_chat_id, memory.id, memory.layer, memory.kind, ",".join(tags), json.dumps(metadata or {})),
        )
        return int(cursor.lastrowid)


PROJECT_OVERVIEW_FIELDS = {
    "stack",
    "purpose",
    "current_status",
    "verified_facts",
    "inferred_facts",
    "needs_read",
    "repo_structure_snapshot",
}
ARCHITECTURE_FIELDS = {"backend_layout", "frontend_layout", "important_packages", "major_responsibilities"}


def load_project_memory_overrides(connection: sqlite3.Connection) -> dict[str, dict[str, dict[str, Any]]]:
    rows = connection.execute("select section, item_key, data from project_memory_overrides").fetchall()
    overrides: dict[str, dict[str, dict[str, Any]]] = {}
    for section, item_key, raw_data in rows:
        try:
            data = json.loads(raw_data or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        overrides.setdefault(str(section), {})[str(item_key)] = data
    return overrides


def apply_project_memory_overrides(model: dict[str, object], overrides: dict[str, dict[str, dict[str, Any]]]) -> None:
    profile = overrides.get("project_overview", {}).get("profile")
    if profile:
        card = model.setdefault("project_card", {})
        if isinstance(card, dict):
            card.update(profile)

    architecture = overrides.get("architecture_summary", {}).get("summary")
    if architecture:
        summary = model.setdefault("architecture_summary", {})
        if isinstance(summary, dict):
            summary.update(architecture)

    apply_list_overrides(model, "read_before_editing_rules", overrides.get("read_rule", {}), "area")
    apply_list_overrides(model, "file_index", overrides.get("file_info", {}), "path")
    apply_symbol_overrides(model, overrides.get("symbol_contract", {}))


def apply_list_overrides(model: dict[str, object], model_key: str, overrides: dict[str, dict[str, Any]], identity_key: str) -> None:
    if not overrides:
        return
    rows = model.get(model_key)
    if not isinstance(rows, list):
        rows = []
        model[model_key] = rows
    by_key = {str(row.get(identity_key, "")): row for row in rows if isinstance(row, dict)}
    for item_key, data in overrides.items():
        target = by_key.get(item_key)
        if target is None:
            target = {identity_key: item_key}
            rows.append(target)
            by_key[item_key] = target
        target.update(data)


def apply_symbol_overrides(model: dict[str, object], overrides: dict[str, dict[str, Any]]) -> None:
    if not overrides:
        return
    rows = model.get("symbol_contracts")
    if not isinstance(rows, list):
        rows = []
        model["symbol_contracts"] = rows
    by_key = {symbol_contract_key(row): row for row in rows if isinstance(row, dict)}
    for item_key, data in overrides.items():
        target = by_key.get(item_key)
        if target is None:
            target = {
                "file_path": data.get("file_path", ""),
                "name": data.get("name", ""),
                "kind": data.get("kind", ""),
            }
            rows.append(target)
            by_key[item_key] = target
        target.update(data)


def symbol_contract_key(row: dict[str, Any]) -> str:
    return "\u001f".join(str(row.get(key, "")).strip() for key in ("file_path", "name", "kind"))


def update_structured_project_memory(
    project_id: str,
    section: str,
    data: dict[str, Any],
    source_chat_id: str | None = None,
) -> dict[str, Any]:
    project = load_project(project_id)
    initialize_project_database(project.database_path)
    clean_section = section.strip()
    if not clean_section:
        raise ValueError("section is required.")
    if not isinstance(data, dict) or not data:
        raise ValueError("data must be a non-empty object.")

    if clean_section == "note":
        category = str(data.get("category") or "fact").strip() or "fact"
        content = required_text(data, "content")
        note_id = record_project_note(project_id, category, content, source_chat_id=source_chat_id)
        try:
            from ..librarian import regenerate_card
            regenerate_card(project_id)
        except Exception:
            pass
        return {"project_id": project.id, "section": clean_section, "summary": f"Added project note {note_id}."}

    with db_connection(project.database_path) as connection:
        if clean_section == "project_overview":
            updated = project_overview_update(data)
            save_project_memory_override(connection, clean_section, "profile", updated, source_chat_id)
            summary = f"Updated project overview fields: {', '.join(sorted(updated))}."
        elif clean_section == "architecture_summary":
            updated = filtered_text_fields(data, ARCHITECTURE_FIELDS)
            save_project_memory_override(connection, clean_section, "summary", updated, source_chat_id)
            summary = f"Updated architecture summary fields: {', '.join(sorted(updated))}."
        elif clean_section == "read_rule":
            area = required_text(data, "area")
            updated = {
                "area": area,
                "files_to_read": string_list(data.get("files_to_read")),
                "reason": str(data.get("reason") or "").strip(),
            }
            if not updated["files_to_read"] and not updated["reason"]:
                raise ValueError("read_rule requires files_to_read or reason.")
            save_project_memory_override(connection, clean_section, area, updated, source_chat_id)
            summary = f"Updated read-before-editing rule for {area}."
        elif clean_section == "file_info":
            path = required_text(data, "path")
            updated = {
                "path": path,
                "role": str(data.get("role") or "").strip(),
                "key_responsibilities": string_list(data.get("key_responsibilities")),
                "when_to_read": str(data.get("when_to_read") or "").strip(),
                "related_files": string_list(data.get("related_files")),
            }
            if "important" in data:
                updated["important"] = bool(data.get("important"))
            save_project_memory_override(connection, clean_section, path, updated, source_chat_id)
            summary = f"Updated important file memory for {path}."
        elif clean_section == "symbol_contract":
            updated = {
                "file_path": required_text(data, "file_path"),
                "name": required_text(data, "name"),
                "kind": required_text(data, "kind"),
                "contract": str(data.get("contract") or "").strip(),
                "related_files": string_list(data.get("related_files")),
            }
            if not updated["contract"]:
                raise ValueError("symbol_contract requires contract.")
            save_project_memory_override(connection, clean_section, symbol_contract_key(updated), updated, source_chat_id)
            summary = f"Updated symbol contract for {updated['name']}."
        elif clean_section == "decision":
            decision = required_text(data, "decision")
            constraint = str(data.get("constraint") or data.get("constraint_text") or "").strip()
            connection.execute(
                "insert or ignore into decisions_preferences (decision, constraint_text, source) values (?, ?, ?)",
                (decision, constraint, "model"),
            )
            summary = f"Recorded project decision: {decision}."
        elif clean_section == "task":
            task = required_text(data, "task")
            status = required_text(data, "status")
            notes = str(data.get("notes") or "").strip()
            connection.execute(
                """
                insert into current_task_memory (task, status, notes)
                values (?, ?, ?)
                on conflict(task) do update set
                    status = excluded.status,
                    notes = excluded.notes,
                    updated_at = current_timestamp
                """,
                (task, status, notes),
            )
            summary = f"Updated project task: {task}."
        else:
            raise ValueError(f"Unsupported project memory section: {clean_section}")

    try:
        from ..librarian import regenerate_card
        regenerate_card(project_id)
    except Exception:
        pass

    return {"project_id": project.id, "section": clean_section, "summary": summary}


def save_project_memory_override(
    connection: sqlite3.Connection,
    section: str,
    item_key: str,
    data: dict[str, Any],
    source_chat_id: str | None,
) -> None:
    connection.execute(
        """
        insert into project_memory_overrides (section, item_key, data, source_chat_id)
        values (?, ?, ?, ?)
        on conflict(section, item_key) do update set
            data = excluded.data,
            source_chat_id = excluded.source_chat_id,
            updated_at = current_timestamp
        """,
        (section, item_key, json.dumps(data, sort_keys=True), source_chat_id),
    )


def project_overview_update(data: dict[str, Any]) -> dict[str, str]:
    if "status" in data and "current_status" not in data:
        data = {**data, "current_status": data["status"]}
    updated = filtered_text_fields(data, PROJECT_OVERVIEW_FIELDS)
    if not updated:
        raise ValueError("project_overview requires at least one supported field.")
    return updated


def filtered_text_fields(data: dict[str, Any], allowed: set[str]) -> dict[str, str]:
    unknown = sorted(key for key in data if key not in allowed and not (key == "status" and "current_status" in allowed))
    if unknown:
        raise ValueError(f"Unsupported field(s): {', '.join(unknown)}")
    updated = {key: str(data[key]).strip() for key in allowed if key in data and str(data[key]).strip()}
    if not updated:
        raise ValueError("At least one supported non-empty field is required.")
    return updated


def required_text(data: dict[str, Any], key: str) -> str:
    value = str(data.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required.")
    return value


def string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []
