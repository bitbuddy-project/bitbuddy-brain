from __future__ import annotations

import json
import difflib
import re
import subprocess
from pathlib import Path
from typing import Any

from ..database import db_connection
from ..config import load_config
from ..paths import ARTIFACTS_DIR
from ..autonomy.web_search import fetched_page_to_text, normalize_search_category, safe_web_fetch, safe_web_search, search_results_to_text
from ..calendar.permissions import CalendarPermissionRequired
from ..calendar.providers import EventDraft, EventPatch
from ..calendar.service import create_event as calendar_create_event, delete_event as calendar_delete_event, find_free_slots, modify_event as calendar_modify_event, user_timezone, view_events
from ..calendar.store import CalendarEvent, local_label
from ..email.models import EmailMessage
from ..email.permissions import EmailPermissionRequired
from ..email.service import create_sender_trash_rule as email_create_sender_trash_rule, list_mailboxes as email_list_mailboxes, list_messages as email_list_messages, read_message as email_read_message, search_messages as email_search_messages, trash_message as email_trash_message
from ..memory.episodic import create_episode, count_auto_episodes_for_conversation, delete_episode, get_episode, list_recent_episodes, search_episodes, update_episode
from ..memory.layers import MemoryLayer, memory_layer
from ..memory.project import MAX_FILE_BYTES, SKIP_DIRS, SKIP_SUFFIXES, list_projects, load_project, project_brief, project_model, record_project_note, update_structured_project_memory
from ..memory.project_validation import (
    delete_validation_recipe,
    list_validation_recipes,
    recipe_to_json,
    run_validation_recipe,
    upsert_validation_recipe,
    validation_run_to_json,
)
from ..memory.store import archive_memory, create_memory, memory_to_json, merge_memories, move_memory, search_memories, update_memory as update_generic_memory
from ..skills import archive_skill, create_skill, list_skills, load_skill, patch_skill, skill_to_json, validate_skill, write_skill_file
from ..tasks import store as task_store
from .base import ToolDefinition, ToolExecutionError, ToolResult, cap_text, invalid_tool_result

MAX_LIST_ENTRIES = 200
MAX_SEARCH_FILES = 200
MAX_SEARCH_MATCHES = 200
MAX_DIFF_CHARS = 20000


def glob_files_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    pattern = str(arguments.get("pattern") or "").strip()
    if not pattern:
        return invalid_tool_result("Missing required argument: pattern")
    base = resolve_tool_base_path(arguments)
    matches: list[str] = []
    for path in base.rglob("*"):
        if should_skip_path(path) or not path.is_file():
            continue
        relative = path.relative_to(base).as_posix()
        if path.match(pattern) or Path(relative).match(pattern):
            matches.append(relative)
        if len(matches) >= MAX_LIST_ENTRIES:
            break
    text = "\n".join(sorted(matches)) if matches else "No files matched."
    content, truncated = cap_text(text, definition.max_chars)
    return ToolResult(definition.name, True, content, f"Found {len(matches)} file(s) matching {pattern!r}.", summarize_file_tool_args(arguments, pattern=pattern), truncated=truncated)


def list_directory_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    path_arg = str(arguments.get("path") or ".").strip() or "."
    base_args = {key: value for key, value in arguments.items() if key != "path"}
    candidate = Path(path_arg).expanduser()
    if candidate.is_absolute() and not base_args.get("project_id") and not base_args.get("root_path"):
        directory = candidate.resolve()
    else:
        base = resolve_tool_base_path(base_args)
        directory = resolve_tool_child_path(base, path_arg)
    if not directory.exists():
        raise ToolExecutionError(f"Directory not found: {path_arg}")
    if not directory.is_dir():
        raise ToolExecutionError(f"Path is not a directory: {path_arg}")
    entries = []
    for child in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        if should_skip_path(child):
            continue
        suffix = "/" if child.is_dir() else ""
        entries.append(f"{child.name}{suffix}")
        if len(entries) >= MAX_LIST_ENTRIES:
            break
    text = "\n".join(entries) if entries else "Directory is empty."
    content, truncated = cap_text(text, definition.max_chars)
    return ToolResult(definition.name, True, content, f"Listed {len(entries)} entr{'y' if len(entries) == 1 else 'ies'} in {path_arg}.", summarize_file_tool_args(arguments, path=path_arg), truncated=truncated)


def read_file_range_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    project_id = arguments.get("project_id")
    file_path = str(arguments.get("file_path") or "").strip()
    if not file_path:
        return invalid_tool_result("Missing required argument: file_path")
    start_line = max(1, int_value(arguments.get("start_line"), 1))
    line_count = max(1, min(2000, int_value(arguments.get("line_count"), 200)))
    path = resolve_tool_file(arguments, file_path)
    text = safe_read_text_file(path)
    lines = text.splitlines()
    selected = lines[start_line - 1 : start_line - 1 + line_count]
    numbered = "\n".join(f"{idx}: {line}" for idx, line in enumerate(selected, start=start_line))
    content, truncated = cap_text(f"# {file_path}\n\n{numbered}", definition.max_chars)
    end_line = start_line + len(selected) - 1 if selected else start_line
    summary = f"Read {file_path} lines {start_line}-{end_line}."
    args = {"file_path": file_path, "start_line": start_line, "line_count": line_count}
    if isinstance(project_id, str) and project_id:
        args["project_id"] = project_id
    return ToolResult(definition.name, True, content, summary, args, truncated=truncated)


def search_text_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    pattern = str(arguments.get("pattern") or "").strip()
    if not pattern:
        return invalid_tool_result("Missing required argument: pattern")
    include = str(arguments.get("include") or "**/*").strip() or "**/*"
    base = resolve_tool_base_path(arguments)
    try:
        regex = re.compile(pattern)
    except re.error as error:
        raise ToolExecutionError(f"Invalid regex pattern: {error}")
    matches: list[str] = []
    scanned = 0
    for path in base.rglob("*"):
        if scanned >= MAX_SEARCH_FILES or len(matches) >= MAX_SEARCH_MATCHES:
            break
        if should_skip_path(path) or not path.is_file() or path.suffix.lower() in SKIP_SUFFIXES:
            continue
        relative = path.relative_to(base).as_posix()
        if not (path.match(include) or Path(relative).match(include)):
            continue
        scanned += 1
        try:
            text = safe_read_text_file(path)
        except ToolExecutionError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                matches.append(f"{relative}:{line_number}: {line[:500]}")
                if len(matches) >= MAX_SEARCH_MATCHES:
                    break
    text = "\n".join(matches) if matches else "No matches found."
    content, truncated = cap_text(text, definition.max_chars)
    return ToolResult(definition.name, True, content, f"Found {len(matches)} text match(es) for {pattern!r}.", summarize_file_tool_args(arguments, pattern=pattern, include=include), truncated=truncated)

def web_search_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    query = str(arguments.get("query") or "")
    if not query:
        return invalid_tool_result("Missing required argument: query")
    category = normalize_search_category(str(arguments.get("category") or "general"))
    config = load_config()
    try:
        results = safe_web_search(query, config.autonomy.web_search, category=category)
        text = search_results_to_text(results)
        return ToolResult(
            tool=definition.name,
            ok=True,
            content=text,
            summary=text.split("\n")[0] if text else "No results found.",
            arguments_summary={"query": query, "category": category},
        )
    except Exception as e:
        return ToolResult(
            tool=definition.name,
            ok=False,
            content="",
            summary="Web search failed.",
            arguments_summary={"query": query, "category": category},
            error=str(e),
        )


def web_fetch_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    url = str(arguments.get("url") or "")
    if not url.strip():
        return invalid_tool_result("Missing required argument: url")
    try:
        page = safe_web_fetch(url, max_chars=definition.max_chars)
        text = fetched_page_to_text(page)
        content, truncated = cap_text(text, definition.max_chars)
        return ToolResult(
            tool=definition.name,
            ok=True,
            content=content,
            summary=page.title or page.url,
            arguments_summary={"url": page.url},
            truncated=truncated,
        )
    except Exception as e:
        return ToolResult(
            tool=definition.name,
            ok=False,
            content="",
            summary="Web fetch failed.",
            arguments_summary={"url": url},
            error=str(e),
        )


def _calendar_permission_result(definition: ToolDefinition, error: CalendarPermissionRequired) -> ToolResult:
    return ToolResult(
        tool=definition.name,
        ok=False,
        content="",
        summary="Calendar permission required.",
        arguments_summary={"scope": error.scope, "state": error.state},
        error=str(error),
    )


def _format_calendar_events(events: list[CalendarEvent], tz: str) -> str:
    if not events:
        return "No events found in that range."
    lines: list[str] = []
    for event in events:
        when = "All day" if event.all_day else f"{local_label(event.start_at, tz)} - {local_label(event.end_at, tz)}"
        suffix = f" @ {event.location}" if event.location else ""
        lines.append(f"- [{event.id}] {event.title} ({when}){suffix}")
    return "\n".join(lines)


def _email_permission_result(definition: ToolDefinition, error: EmailPermissionRequired) -> ToolResult:
    return ToolResult(
        tool=definition.name,
        ok=False,
        content="",
        summary="Email permission required.",
        arguments_summary={"scope": error.scope, "state": error.state},
        error=str(error),
    )


def _format_email_messages(messages: list[EmailMessage]) -> str:
    if not messages:
        return "No email messages found."
    lines = []
    for message in messages:
        subject = message.subject or "(no subject)"
        sender = message.from_addr or "unknown sender"
        snippet = f" — {message.snippet}" if message.snippet else ""
        lines.append(f"- [{message.id}] {subject} from {sender} ({message.date}){snippet}")
    return "\n".join(lines)


def email_list_mailboxes_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    try:
        mailboxes = email_list_mailboxes()
    except EmailPermissionRequired as error:
        return _email_permission_result(definition, error)
    except ValueError as error:
        return invalid_tool_result(str(error))
    text = "\n".join(f"- {mailbox.name}" for mailbox in mailboxes) or "No mailboxes found."
    content, truncated = cap_text(text, definition.max_chars)
    return ToolResult(tool=definition.name, ok=True, content=content, summary=f"Found {len(mailboxes)} mailboxes.", truncated=truncated)


def email_recent_messages_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    mailbox = str(arguments.get("mailbox") or "").strip()
    limit = email_tool_limit()
    try:
        messages = email_list_messages(mailbox=mailbox, limit=limit)
    except EmailPermissionRequired as error:
        return _email_permission_result(definition, error)
    except ValueError as error:
        return invalid_tool_result(str(error))
    content, truncated = cap_text(_format_email_messages(messages), definition.max_chars)
    return ToolResult(tool=definition.name, ok=True, content=content, summary=f"Found {len(messages)} email messages. Tool visibility limit is {limit} message(s).", arguments_summary={"mailbox": mailbox or "default", "limit": limit}, truncated=truncated)


def email_search_messages_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    query = str(arguments.get("query") or "").strip()
    mailbox = str(arguments.get("mailbox") or "").strip()
    if not query:
        return invalid_tool_result("query is required.")
    limit = email_tool_limit()
    try:
        messages = email_search_messages(query=query, mailbox=mailbox, limit=limit)
    except EmailPermissionRequired as error:
        return _email_permission_result(definition, error)
    except ValueError as error:
        return invalid_tool_result(str(error))
    content, truncated = cap_text(_format_email_messages(messages), definition.max_chars)
    return ToolResult(tool=definition.name, ok=True, content=content, summary=f"Found {len(messages)} matching email messages. Tool visibility limit is {limit} message(s).", arguments_summary={"query": query, "mailbox": mailbox or "default", "limit": limit}, truncated=truncated)


def email_read_message_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    message_id = str(arguments.get("message_id") or "").strip()
    mailbox = str(arguments.get("mailbox") or "").strip()
    if not message_id:
        return invalid_tool_result("message_id is required.")
    try:
        message = email_read_message(message_id=message_id, mailbox=mailbox)
    except EmailPermissionRequired as error:
        return _email_permission_result(definition, error)
    except ValueError as error:
        return invalid_tool_result(str(error))
    body = message.body or message.snippet or "No readable body found."
    text = f"Subject: {message.subject or '(no subject)'}\nFrom: {message.from_addr}\nDate: {message.date}\n\n{body}"
    content, truncated = cap_text(text, definition.max_chars)
    return ToolResult(tool=definition.name, ok=True, content=content, summary=f"Read email '{message.subject or message.id}'.", arguments_summary={"message_id": message.id, "mailbox": mailbox or message.mailbox}, truncated=truncated)


def email_trash_message_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    message_id = str(arguments.get("message_id") or "").strip()
    mailbox = str(arguments.get("mailbox") or "").strip()
    if not message_id:
        return invalid_tool_result("message_id is required.")
    try:
        message = email_trash_message(message_id=message_id, mailbox=mailbox)
    except EmailPermissionRequired as error:
        return _email_permission_result(definition, error)
    except ValueError as error:
        return invalid_tool_result(str(error))
    subject = message.subject or message.id
    return ToolResult(
        tool=definition.name,
        ok=True,
        content=f"Moved email '{subject}' to Trash. This is a trash action, not permanent deletion; the user can still empty Trash later from their mail account or BitBuddy Trash UI.",
        summary=f"Moved email '{subject}' to Trash, not permanently deleted.",
        arguments_summary={"message_id": message.id, "mailbox": mailbox or message.mailbox, "action": "trash_not_permanent_delete"},
        truncated=False,
    )


def email_create_auto_trash_rule_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    sender = str(arguments.get("sender") or "").strip()
    mailbox = str(arguments.get("mailbox") or "INBOX").strip()
    apply_existing = bool(arguments.get("apply_existing", False))
    if not sender:
        return invalid_tool_result("sender is required.")
    try:
        rule, applied = email_create_sender_trash_rule(sender=sender, apply_existing=apply_existing, mailbox=mailbox)
    except EmailPermissionRequired as error:
        return _email_permission_result(definition, error)
    except ValueError as error:
        return invalid_tool_result(str(error))
    content = f"Auto-trash rule enabled for sender {rule.value}."
    if apply_existing:
        content += f" Moved {applied} existing matching email{'s' if applied != 1 else ''} to Trash, not permanent deletion."
    return ToolResult(tool=definition.name, ok=True, content=content, summary=f"Enabled auto-trash sender rule for {rule.value}.", arguments_summary={"sender": rule.value, "apply_existing": apply_existing, "applied": applied, "action": "trash_not_permanent_delete"}, truncated=False)


def email_tool_limit(value: object = None) -> int:
    from ..config import load_config

    return max(1, int(load_config().email.tool_message_limit))


def calendar_view_events_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    range_str = str(arguments.get("range") or "")
    start = str(arguments.get("start") or "")
    end = str(arguments.get("end") or "")
    try:
        events = view_events(range_str=range_str, start=start, end=end)
    except CalendarPermissionRequired as error:
        return _calendar_permission_result(definition, error)
    tz = user_timezone()
    content, truncated = cap_text(_format_calendar_events(events, tz), definition.max_chars)
    return ToolResult(
        tool=definition.name,
        ok=True,
        content=content,
        summary=f"Found {len(events)} event{'' if len(events) == 1 else 's'}.",
        arguments_summary={"range": range_str or f"{start}..{end}"},
        truncated=truncated,
    )


def calendar_find_free_time_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    range_str = str(arguments.get("range") or "")
    start = str(arguments.get("start") or "")
    end = str(arguments.get("end") or "")
    try:
        duration = max(1, int(arguments.get("duration_minutes", 30)))
    except (TypeError, ValueError):
        return invalid_tool_result("duration_minutes must be an integer.")
    try:
        slots = find_free_slots(range_str=range_str, start=start, end=end, duration_minutes=duration)
    except CalendarPermissionRequired as error:
        return _calendar_permission_result(definition, error)
    tz = user_timezone()
    if not slots:
        text = "No free slots of that length in the range."
    else:
        text = "\n".join(f"- {local_label(slot['start'], tz)} - {local_label(slot['end'], tz)}" for slot in slots)
    content, truncated = cap_text(text, definition.max_chars)
    return ToolResult(
        tool=definition.name,
        ok=True,
        content=content,
        summary=f"Found {len(slots)} free slot{'' if len(slots) == 1 else 's'}.",
        arguments_summary={"duration_minutes": duration},
        truncated=truncated,
    )


def calendar_create_event_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    title = str(arguments.get("title") or "").strip()
    start = str(arguments.get("start") or "").strip()
    end = str(arguments.get("end") or "").strip()
    if not title:
        return invalid_tool_result("title is required.")
    if not start or not end:
        return invalid_tool_result("start and end are required (ISO8601, e.g. 2026-06-05T14:30).")
    attendees = [str(a) for a in arguments.get("attendees", []) if isinstance(a, str)]
    draft = EventDraft(
        title=title,
        start_at=start,
        end_at=end,
        description=str(arguments.get("description") or ""),
        location=str(arguments.get("location") or ""),
        all_day=bool(arguments.get("all_day", False)),
        attendees=attendees,
        source="user",
    )
    try:
        event, conflicts = calendar_create_event(draft)
    except CalendarPermissionRequired as error:
        return _calendar_permission_result(definition, error)
    except ValueError as error:
        return invalid_tool_result(str(error))
    tz = user_timezone()
    reused_existing = bool(event.metadata.get("bitbuddy_existing_event"))
    summary = (
        f"Event already exists: '{event.title}' for {local_label(event.start_at, tz)}."
        if reused_existing
        else f"Created '{event.title}' for {local_label(event.start_at, tz)}."
    )
    content = summary
    if conflicts:
        names = ", ".join(f"'{c.title}'" for c in conflicts)
        content += f"\nHeads up: this overlaps with {names}."
    return ToolResult(
        tool=definition.name,
        ok=True,
        content=content,
        summary=summary,
        arguments_summary={"event_id": event.id, "title": event.title},
    )


def calendar_modify_event_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    event_id = str(arguments.get("event_id") or "").strip()
    if not event_id:
        return invalid_tool_result("event_id is required.")
    patch = EventPatch(
        title=str(arguments["title"]) if "title" in arguments else None,
        start_at=str(arguments["start"]) if "start" in arguments else None,
        end_at=str(arguments["end"]) if "end" in arguments else None,
        description=str(arguments["description"]) if "description" in arguments else None,
        location=str(arguments["location"]) if "location" in arguments else None,
        all_day=bool(arguments["all_day"]) if "all_day" in arguments else None,
        status=str(arguments["status"]) if "status" in arguments else None,
    )
    try:
        event, conflicts = calendar_modify_event(event_id, patch)
    except CalendarPermissionRequired as error:
        return _calendar_permission_result(definition, error)
    except ValueError as error:
        return invalid_tool_result(str(error))
    tz = user_timezone()
    summary = f"Updated '{event.title}' ({local_label(event.start_at, tz)})."
    content = summary
    if conflicts:
        names = ", ".join(f"'{c.title}'" for c in conflicts)
        content += f"\nHeads up: this now overlaps with {names}."
    return ToolResult(
        tool=definition.name,
        ok=True,
        content=content,
        summary=summary,
        arguments_summary={"event_id": event.id},
    )


def calendar_delete_event_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    event_id = str(arguments.get("event_id") or "").strip()
    if not event_id:
        return invalid_tool_result("event_id is required.")
    try:
        event = calendar_delete_event(event_id)
    except CalendarPermissionRequired as error:
        return _calendar_permission_result(definition, error)
    except ValueError as error:
        return invalid_tool_result(str(error))
    return ToolResult(
        tool=definition.name,
        ok=True,
        content=f"Deleted '{event.title}'.",
        summary=f"Deleted '{event.title}'.",
        arguments_summary={"event_id": event_id},
    )


def _format_task(task: task_store.Task, tz: str) -> str:
    bits = [f"[{task.id}] {task.title}"]
    if task.status != "open":
        bits.append(f"({task.status})")
    if task.remind_at:
        bits.append(f"remind {local_label(task.remind_at, tz)}")
    elif task.due_at:
        bits.append(f"due {local_label(task.due_at, tz)}")
    if task.priority >= 4:
        bits.append(f"!p{task.priority}")
    line = " ".join(bits)
    if task.notes:
        line += f"\n    {task.notes}"
    return line


def create_task_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    title = str(arguments.get("title") or "").strip()
    if not title:
        return invalid_tool_result("title is required.")
    try:
        task = task_store.create_task(
            title,
            notes=str(arguments.get("notes") or ""),
            due_at=str(arguments.get("due") or "") or None,
            remind_at=str(arguments.get("remind_at") or "") or None,
            priority=int(arguments.get("priority", 3) or 3),
            project_id=str(arguments.get("project_id") or ""),
        )
    except ValueError as error:
        return invalid_tool_result(str(error))
    tz = user_timezone()
    if task.remind_at:
        summary = f"Added task '{task.title}' — I'll remind you at {local_label(task.remind_at, tz)}."
    elif task.due_at:
        summary = f"Added task '{task.title}' (due {local_label(task.due_at, tz)})."
    else:
        summary = f"Added task '{task.title}'."
    return ToolResult(
        tool=definition.name,
        ok=True,
        content=summary,
        summary=summary,
        arguments_summary={"task_id": task.id, "title": task.title},
    )


def list_tasks_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    status = str(arguments.get("status") or "open").strip() or "open"
    project_id = str(arguments.get("project_id") or "").strip()
    tasks = task_store.list_tasks(status=status, project_id=project_id)
    tz = user_timezone()
    if not tasks:
        text = "No tasks." if status == "all" else f"No {status} tasks."
    else:
        text = "\n".join(_format_task(task, tz) for task in tasks)
    content, truncated = cap_text(text, definition.max_chars)
    return ToolResult(
        tool=definition.name,
        ok=True,
        content=content,
        summary=f"{len(tasks)} task{'' if len(tasks) == 1 else 's'} ({status}).",
        arguments_summary={"status": status},
        truncated=truncated,
    )


def update_task_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    task_id = str(arguments.get("task_id") or "").strip()
    if not task_id:
        return invalid_tool_result("task_id is required.")
    fields: dict[str, Any] = {}
    for key, arg in (("title", "title"), ("notes", "notes"), ("status", "status"), ("project_id", "project_id")):
        if arg in arguments:
            fields[key] = str(arguments[arg])
    if "due" in arguments:
        fields["due_at"] = str(arguments["due"]) or None
    if "remind_at" in arguments:
        fields["remind_at"] = str(arguments["remind_at"]) or None
    if "priority" in arguments:
        try:
            fields["priority"] = int(arguments["priority"])
        except (TypeError, ValueError):
            return invalid_tool_result("priority must be an integer 1-5.")
    try:
        task = task_store.update_task(task_id, **fields)
    except ValueError as error:
        return invalid_tool_result(str(error))
    summary = f"Updated task '{task.title}'."
    return ToolResult(
        tool=definition.name,
        ok=True,
        content=_format_task(task, user_timezone()),
        summary=summary,
        arguments_summary={"task_id": task.id},
    )


def complete_task_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    task_id = str(arguments.get("task_id") or "").strip()
    if not task_id:
        return invalid_tool_result("task_id is required.")
    try:
        task = task_store.complete_task(task_id)
    except ValueError as error:
        return invalid_tool_result(str(error))
    return ToolResult(
        tool=definition.name,
        ok=True,
        content=f"Marked '{task.title}' done.",
        summary=f"Marked '{task.title}' done.",
        arguments_summary={"task_id": task.id},
    )


def delete_task_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    task_id = str(arguments.get("task_id") or "").strip()
    if not task_id:
        return invalid_tool_result("task_id is required.")
    deleted = task_store.delete_task(task_id)
    if not deleted:
        return invalid_tool_result(f"Unknown task: {task_id}")
    return ToolResult(
        tool=definition.name,
        ok=True,
        content="Task deleted.",
        summary="Task deleted.",
        arguments_summary={"task_id": task_id},
    )


def get_project_memory_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    project_id = require_registered_project_id(arguments)
    model = project_model(project_id, limit=40)
    file_count = len(model.get("file_index", [])) if isinstance(model.get("file_index"), list) else 0
    symbol_count = len(model.get("symbol_contracts", [])) if isinstance(model.get("symbol_contracts"), list) else 0
    content, truncated = cap_text(json.dumps(model, indent=2), definition.max_chars)
    return ToolResult(
        tool=definition.name,
        ok=True,
        content=content,
        summary=f"Loaded project memory for {project_id}: {file_count} important file(s), {symbol_count} symbol contract(s).",
        arguments_summary={"project_id": project_id},
        truncated=truncated,
    )


def get_project_brief_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    project_id = require_registered_project_id(arguments)
    brief = project_brief(project_id)
    content, truncated = cap_text(brief, definition.max_chars)
    return ToolResult(
        tool=definition.name,
        ok=True,
        content=content,
        summary=f"Loaded project brief for {project_id}.",
        arguments_summary={"project_id": project_id},
        truncated=truncated,
    )


def list_project_validation_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    project_id = require_registered_project_id(arguments)
    include_suggestions = bool(arguments.get("include_suggestions", True))
    recipes = list_validation_recipes(project_id, include_suggestions=include_suggestions)
    data = {"project_id": project_id, "recipes": [recipe_to_json(recipe) for recipe in recipes]}
    content, truncated = cap_text(json.dumps(data, indent=2), definition.max_chars)
    stored = sum(1 for recipe in recipes if recipe.source == "stored")
    suggested = len(recipes) - stored
    return ToolResult(
        definition.name,
        True,
        content,
        f"Loaded {stored} stored validation recipe(s)" + (f" and {suggested} suggestion(s)." if suggested else "."),
        {"project_id": project_id, "include_suggestions": include_suggestions},
        truncated=truncated,
    )


def upsert_project_validation_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    project_id = require_registered_project_id(arguments)
    try:
        recipe = upsert_validation_recipe(
            project_id,
            name=str(arguments.get("name") or ""),
            command=str(arguments.get("command") or ""),
            kind=str(arguments.get("kind") or "custom"),
            working_directory=str(arguments.get("working_directory") or "."),
            description=str(arguments.get("description") or ""),
        )
    except ValueError as error:
        return invalid_tool_result(str(error))
    content, truncated = cap_text(json.dumps(recipe_to_json(recipe), indent=2), definition.max_chars)
    return ToolResult(
        definition.name,
        True,
        content,
        f"Saved validation recipe '{recipe.name}' for {project_id}.",
        {"project_id": project_id, "name": recipe.name, "kind": recipe.kind, "command": recipe.command},
        truncated=truncated,
    )


def delete_project_validation_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    project_id = require_registered_project_id(arguments)
    name = str(arguments.get("name") or "").strip()
    if not name:
        return invalid_tool_result("name is required.")
    try:
        deleted = delete_validation_recipe(project_id, name)
    except ValueError as error:
        return invalid_tool_result(str(error))
    if not deleted:
        return invalid_tool_result(f"Unknown validation recipe: {name}")
    return ToolResult(
        definition.name,
        True,
        f"Deleted validation recipe '{name}'.",
        f"Deleted validation recipe '{name}'.",
        {"project_id": project_id, "name": name},
    )


def run_project_validation_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    project_id = require_registered_project_id(arguments)
    name = str(arguments.get("name") or "").strip()
    if not name:
        return invalid_tool_result("name is required.")
    try:
        run = run_validation_recipe(
            project_id,
            name,
            timeout_seconds=int_value(arguments.get("timeout_seconds"), 300),
        )
    except (ValueError, subprocess.TimeoutExpired) as error:
        return invalid_tool_result(str(error))
    output = "\n".join(
        part
        for part in (
            f"$ {run.recipe.command}",
            f"cwd: {run.cwd}",
            f"exit_code: {run.exit_code}",
            "",
            run.stdout.strip(),
            run.stderr.strip(),
        )
        if part
    )
    content, truncated = cap_text(output, definition.max_chars)
    ok = run.exit_code == 0
    return ToolResult(
        definition.name,
        ok,
        content,
        f"Validation recipe '{run.recipe.name}' {run.status} with exit code {run.exit_code}.",
        {"project_id": project_id, "name": run.recipe.name, "kind": run.recipe.kind, "command": run.recipe.command},
        truncated=truncated,
        error="" if ok else content,
        metadata={"validation": validation_run_to_json(run)},
    )


def read_file_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    project_id = arguments.get("project_id")
    path_str = arguments.get("file_path")
    if not isinstance(path_str, str) or not path_str.strip():
        raise ToolExecutionError("A file_path string is required.")

    if project_id:
        if not isinstance(project_id, str):
             raise ToolExecutionError("project_id must be a string.")
        project = load_project(project_id)
        file_path = resolve_project_file(project.paths, path_str)
        display_path = path_str
        summary_suffix = f"from {project_id}"
    else:
        file_path = Path(path_str).expanduser().resolve()
        display_path = str(file_path)
        summary_suffix = ""

    if not file_path.exists():
        parent = file_path.parent
        try:
            if parent.exists() and parent.is_dir():
                entries = sorted(parent.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
                listing = "\n".join(f"{c.name}{'/' if c.is_dir() else ''}" for c in entries[:40])
                raise ToolExecutionError(f"File not found: {path_str}\n\nContents of {parent}:\n{listing}")
        except ToolExecutionError:
            raise
        except Exception:
            pass
        raise ToolExecutionError(f"File not found: {path_str}")
    if not file_path.is_file():
        raise ToolExecutionError(f"Path is not a file: {path_str}")

    if any(part in SKIP_DIRS for part in file_path.parts):
        raise ToolExecutionError("Refusing to read a skipped directory path.")
    if file_path.suffix.lower() in SKIP_SUFFIXES:
        raise ToolExecutionError(f"Refusing to read skipped file type: {file_path.suffix.lower()}")

    stat = file_path.stat()
    if stat.st_size > MAX_FILE_BYTES:
        raise ToolExecutionError(f"Refusing to read file larger than {MAX_FILE_BYTES} bytes.")

    raw = file_path.read_bytes()
    if b"\x00" in raw[:4096]:
        raise ToolExecutionError("Refusing to read binary-looking file content.")
    text = raw.decode("utf-8", errors="replace")
    content, truncated = cap_text(text, definition.max_chars)
    return ToolResult(
        tool=definition.name,
        ok=True,
        content=f"# {display_path}\n\n{content}",
        summary=f"Read {display_path} {summary_suffix} ({stat.st_size} bytes).".strip(),
        arguments_summary={"project_id": project_id, "file_path": path_str} if project_id else {"file_path": path_str},
        truncated=truncated,
    )


def write_file_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    file_path = require_writable_file_path(arguments)
    content = arguments.get("content")
    if not isinstance(content, str):
        return invalid_tool_result("Missing required argument: content")
    path = resolve_writable_path(arguments, file_path)
    previous_content: str | None = None
    file_existed = path.exists()
    if should_skip_path(path):
        raise ToolExecutionError("Refusing to write inside a skipped directory path.")
    if path.suffix.lower() in SKIP_SUFFIXES:
        raise ToolExecutionError(f"Refusing to write skipped file type: {path.suffix.lower()}")
    if path.exists() and not path.is_file():
        raise ToolExecutionError(f"Path exists but is not a file: {path}")
    if path.exists() and not bool(arguments.get("overwrite", True)):
        raise ToolExecutionError(f"File already exists and overwrite=false: {path}")
    if file_existed:
        try:
            previous_content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            previous_content = None
    if bool(arguments.get("create_dirs", True)):
        path.parent.mkdir(parents=True, exist_ok=True)
    elif not path.parent.exists():
        raise ToolExecutionError(f"Parent directory does not exist: {path.parent}")
    path.write_text(content, encoding="utf-8")
    content_preview, truncated = cap_text(content, definition.max_chars)
    diff_metadata = file_diff_metadata(
        path=str(path),
        old_text=previous_content or "",
        new_text=content,
        status="modified" if file_existed else "created",
    )
    return ToolResult(
        definition.name,
        True,
        f"# {path}\n\n{content_preview}",
        f"Wrote {len(content)} character(s) to {path}.",
        summarize_file_tool_args(arguments, file_path=file_path, path=str(path)),
        truncated=truncated,
        metadata=diff_metadata,
    )


def patch_file_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    file_path = require_writable_file_path(arguments)
    old_text = arguments.get("old_text")
    new_text = arguments.get("new_text")
    if not isinstance(old_text, str) or not isinstance(new_text, str):
        return invalid_tool_result("Missing required arguments: old_text and new_text")
    path = resolve_writable_path(arguments, file_path)
    current = safe_read_text_file(path)
    occurrences = current.count(old_text)
    if occurrences == 0:
        raise ToolExecutionError("old_text was not found in the target file.")
    if occurrences > 1 and not bool(arguments.get("replace_all", False)):
        raise ToolExecutionError("old_text appears multiple times. Set replace_all=true or provide a more specific old_text.")
    patched = current.replace(old_text, new_text) if bool(arguments.get("replace_all", False)) else current.replace(old_text, new_text, 1)
    path.write_text(patched, encoding="utf-8")
    preview, truncated = cap_text(make_patch_preview(old_text, new_text), definition.max_chars)
    diff_metadata = file_diff_metadata(path=str(path), old_text=current, new_text=patched, status="modified")
    return ToolResult(
        definition.name,
        True,
        preview,
        f"Patched {path} ({'all' if bool(arguments.get('replace_all', False)) else '1'} replacement{'s' if bool(arguments.get('replace_all', False)) else ''}).",
        summarize_file_tool_args(arguments, file_path=file_path, path=str(path)),
        truncated=truncated,
        metadata=diff_metadata,
    )


def make_directory_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    directory_path = arguments.get("path") or arguments.get("file_path")
    if not isinstance(directory_path, str) or not directory_path.strip():
        return invalid_tool_result("Missing required argument: path")
    clean_path = require_writable_path(str(directory_path), arguments)
    path = resolve_writable_path(arguments, clean_path)
    if path.exists() and not path.is_dir():
        raise ToolExecutionError(f"Path exists but is not a directory: {path}")
    path.mkdir(parents=bool(arguments.get("parents", True)), exist_ok=bool(arguments.get("exist_ok", True)))
    return ToolResult(
        definition.name,
        True,
        str(path),
        f"Created directory {path}.",
        summarize_file_tool_args(arguments, path=str(path)),
    )


def run_shell_command_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    command = arguments.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ToolExecutionError("A command string is required.")
    cwd = resolve_shell_working_directory(arguments)
    timeout = max(1, min(300, int_value(arguments.get("timeout_seconds"), 60)))

    try:
        result = subprocess.run(
            command.strip(),
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd is not None else None,
        )
        ok = result.returncode == 0
        content = result.stdout if ok else result.stderr
        summary = f"Executed: {command}"
        if not ok:
            summary += f" (failed with exit code {result.returncode})"

        content, truncated = cap_text(content, definition.max_chars)
        return ToolResult(
            tool=definition.name,
            ok=ok,
            content=content,
            summary=summary,
            arguments_summary={"command": command, **({"working_directory": str(cwd)} if cwd is not None else {}), "timeout_seconds": timeout},
            truncated=truncated,
            error="" if ok else content,
        )
    except Exception as error:
        raise ToolExecutionError(f"Failed to execute command: {error}")


def run_subagent_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    task = str(arguments.get("task") or "").strip()
    if not task:
        return invalid_tool_result("Missing required argument: task")
    allowed_tools = arguments.get("allowed_tools")
    clean_allowed = [str(item) for item in allowed_tools if isinstance(item, str)] if isinstance(allowed_tools, list) else None
    max_rounds = max(1, min(8, int_value(arguments.get("max_rounds"), 4)))
    agent_type = str(arguments.get("agent_type") or "general").strip() or "general"
    project_id = str(arguments.get("project_id") or "").strip()

    from ..config import load_config
    from ..providers import ProviderClient
    from ..subagents.runtime import run_subagent
    from .registry import default_tool_registry

    config = load_config()
    if config.provider.type == "none":
        return ToolResult(definition.name, False, "", "Subagent skipped: no provider configured.", {"task": task[:160]}, error="No model provider is configured.")
    result = run_subagent(
        task=task,
        agent_type=agent_type,
        registry=default_tool_registry(),
        client=ProviderClient(config.provider),
        model=config.provider.model or None,
        allowed_tools=clean_allowed,
        project_id=project_id,
        max_rounds=max_rounds,
    )
    if result.status != "completed":
        return ToolResult(definition.name, False, "", "Subagent failed.", {"run_id": result.run_id, "task": task[:160]}, error=result.error)
    content = {
        "run_id": result.run_id,
        "agent_type": agent_type,
        "report": result.report,
        "tools_used": [tool_result.tool for tool_result in result.tool_results],
    }
    text, truncated = cap_text(json.dumps(content, indent=2), definition.max_chars)
    return ToolResult(definition.name, True, text, f"Subagent completed: {result.report[:180]}", {"run_id": result.run_id, "agent_type": agent_type, "task": task[:160]}, truncated=truncated)


def request_user_input_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    """Runtime-intercepted tool; reaching this handler is a defensive error."""
    return ToolResult(
        definition.name,
        False,
        "",
        "User question was not intercepted by the active runtime.",
        {},
        error="request_user_input requires an interactive Chat or Coding run.",
    )


def list_skills_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    include_archived = bool(arguments.get("include_archived", False))
    skills = [skill_to_json(skill) for skill in list_skills(include_archived=include_archived)]
    content, truncated = cap_text(json.dumps({"skills": skills}, indent=2), definition.max_chars)
    return ToolResult(definition.name, True, content, f"Listed {len(skills)} skill(s).", {"include_archived": include_archived}, truncated=truncated)


def load_skill_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    name = str(arguments.get("name") or "").strip()
    if not name:
        return invalid_tool_result("Missing required argument: name")
    skill = load_skill(name)
    content, truncated = cap_text(skill_to_json(skill, include_content=True)["content"], definition.max_chars)
    return ToolResult(definition.name, True, content, f"Loaded skill: {skill.name}", {"name": skill.name}, truncated=truncated)


def validate_skill_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    name = str(arguments.get("name") or "").strip()
    if not name:
        return invalid_tool_result("Missing required argument: name")
    validation = validate_skill(name)
    data = {"ok": validation.ok, "errors": list(validation.errors), "warnings": list(validation.warnings)}
    return ToolResult(
        definition.name,
        validation.ok,
        json.dumps(data, indent=2),
        f"Skill validation {'passed' if validation.ok else 'failed'}: {name}",
        {"name": name},
        error="; ".join(validation.errors) if not validation.ok else "",
    )


def mcp_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    annotations = definition.annotations if isinstance(definition.annotations, dict) else {}
    server_name = str(annotations.get("mcp_server") or "").strip()
    tool_name = str(annotations.get("mcp_tool") or "").strip()
    if not server_name or not tool_name:
        raise ToolExecutionError("MCP tool metadata is missing.")

    from ..config import load_config
    from ..mcp_client import get_mcp_client

    server = next((item for item in load_config().mcp_servers if item.name == server_name and item.enabled), None)
    if server is None:
        raise ToolExecutionError(f"MCP server is not configured or enabled: {server_name}")

    response = get_mcp_client(server).call_tool(tool_name, arguments)
    is_error = bool(response.get("isError", False))
    text = format_mcp_tool_content(response)
    content, truncated = cap_text(text, definition.max_chars)
    summary = f"MCP tool {tool_name} {'failed' if is_error else 'completed'} on {server_name}."
    return ToolResult(
        definition.name,
        not is_error,
        content,
        summary,
        summarize_mcp_arguments(server_name, tool_name, arguments),
        truncated=truncated,
        error=content if is_error else "",
    )


def create_skill_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    name = str(arguments.get("name") or "").strip()
    description = str(arguments.get("description") or "").strip()
    body = str(arguments.get("body") or "").strip()
    metadata = arguments.get("metadata") if isinstance(arguments.get("metadata"), dict) else None
    skill = create_skill(name, description, body, metadata=metadata)
    content, truncated = cap_text(json.dumps(skill_to_json(skill), indent=2), definition.max_chars)
    return ToolResult(definition.name, True, content, f"Created skill: {skill.name}", {"name": skill.name}, truncated=truncated)


def patch_skill_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    name = str(arguments.get("name") or "").strip()
    old_text = str(arguments.get("old_text") or "")
    new_text = str(arguments.get("new_text") or "")
    skill = patch_skill(name, old_text, new_text)
    content, truncated = cap_text(json.dumps(skill_to_json(skill), indent=2), definition.max_chars)
    return ToolResult(definition.name, True, content, f"Patched skill: {skill.name}", {"name": skill.name}, truncated=truncated)


def archive_skill_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    name = str(arguments.get("name") or "").strip()
    skill = archive_skill(name)
    return ToolResult(definition.name, True, json.dumps(skill_to_json(skill), indent=2), f"Archived skill: {skill.name}", {"name": skill.name})


def write_skill_file_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    name = str(arguments.get("name") or "").strip()
    relative_path = str(arguments.get("relative_path") or "").strip()
    content = str(arguments.get("content") or "")
    path = write_skill_file(name, relative_path, content)
    return ToolResult(definition.name, True, str(path), f"Wrote support file for {name}: {relative_path}", {"name": name, "relative_path": relative_path})


def require_registered_project_id(arguments: dict[str, object]) -> str:
    project_id = arguments.get("project_id")
    if not isinstance(project_id, str) or not project_id.strip():
        raise ToolExecutionError("A registered project_id string is required.")
    clean_project_id = project_id.strip()
    if not any(project.id == clean_project_id for project in list_projects()):
        raise ToolExecutionError(f"Unknown registered project id: {clean_project_id}")
    return clean_project_id


def get_episode_memory_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    query = str(arguments.get("query", "")).strip()
    raw_limit = arguments.get("limit", 10)
    try:
        limit = max(1, min(20, int(raw_limit)))
    except (TypeError, ValueError):
        raise ToolExecutionError("limit must be an integer between 1 and 20.")

    episodes = search_episodes(query=query, limit=limit) if query else list_recent_episodes(limit=limit)
    if not episodes:
        return ToolResult(
            tool=definition.name,
            ok=True,
            content="No episodic memories matched.",
            summary="No episodic memories matched.",
            arguments_summary={"query": query, "limit": limit} if query else {"limit": limit},
        )

    lines = ["[Episodic Memories]", "Use episode_id for precise update_episode or forget_episode calls.", ""]
    for episode in episodes:
        tags = f" tags={episode.tags}" if episode.tags else ""
        project = f" project_id={episode.project_id}" if episode.project_id else ""
        lines.append(
            f"- episode_id={episode.id} title={episode.title!r} type={episode.type} importance={episode.importance}{tags}{project}\n"
            f"  summary: {episode.summary}"
        )

    content, truncated = cap_text("\n".join(lines), definition.max_chars)
    return ToolResult(
        tool=definition.name,
        ok=True,
        content=content,
        summary=f"Loaded {len(episodes)} episodic memor{'y' if len(episodes) == 1 else 'ies'}.",
        arguments_summary={"query": query, "limit": limit} if query else {"limit": limit},
        truncated=truncated,
    )


def record_memory_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    layer = memory_layer(str(arguments.get("layer", "")))
    title = str(arguments.get("title", "")).strip()
    summary = str(arguments.get("summary", "")).strip()
    kind = str(arguments.get("kind", "memory")).strip() or "memory"
    importance = int(arguments.get("importance", 3))
    tags = [str(tag) for tag in arguments.get("tags", []) if isinstance(tag, str)]
    project_id = str(arguments.get("project_id", "")).strip() or None
    source = str(arguments.get("source", "model_tool")).strip() or "model_tool"
    conversation_id = str(arguments.get("conversation_id", "")).strip() or None

    if not title:
        raise ToolExecutionError("title is required.")
    if not summary:
        raise ToolExecutionError("summary is required.")
    if layer == MemoryLayer.PROJECT and project_id:
        require_registered_project_id({"project_id": project_id})

    memory = create_memory(
        layer=layer,
        kind=kind,
        title=title,
        summary=summary,
        importance=importance,
        conversation_id=conversation_id,
        project_id=project_id,
        source=source,
        tags=tags,
        metadata={
            "created_by": "model",
            "creation_mode": "explicit_user_request" if bool(arguments.get("explicit_user_request", False)) else "auto",
        },
    )
    return ToolResult(
        tool=definition.name,
        ok=True,
        content=json.dumps(memory_to_json(memory), indent=2),
        summary=f"Saved {memory.layer} memory: {memory.title}",
        arguments_summary={"memory_id": memory.id, "layer": memory.layer, "title": memory.title},
    )


def search_memory_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    query = str(arguments.get("query", "")).strip()
    layer_arg = arguments.get("layer")
    layer = memory_layer(str(layer_arg)).value if isinstance(layer_arg, str) and layer_arg.strip() else None
    project_id = str(arguments.get("project_id", "")).strip() or None
    include_archived = bool(arguments.get("include_archived", False))
    try:
        limit = max(1, min(50, int(arguments.get("limit", 10))))
    except (TypeError, ValueError):
        raise ToolExecutionError("limit must be an integer between 1 and 50.")

    memories = search_memories(query=query, layer=layer, project_id=project_id, limit=limit, include_archived=include_archived)
    content, truncated = cap_text(format_memory_records(memories), definition.max_chars)
    return ToolResult(
        tool=definition.name,
        ok=True,
        content=content,
        summary=f"Loaded {len(memories)} memor{'y' if len(memories) == 1 else 'ies'}.",
        arguments_summary={"query": query, "layer": layer or "", "limit": limit},
        truncated=truncated,
    )


def list_memory_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    layer_arg = arguments.get("layer")
    layer = memory_layer(str(layer_arg)).value if isinstance(layer_arg, str) and layer_arg.strip() else None
    project_id = str(arguments.get("project_id", "")).strip() or None
    include_archived = bool(arguments.get("include_archived", False))
    try:
        limit = max(1, min(100, int(arguments.get("limit", 20))))
    except (TypeError, ValueError):
        raise ToolExecutionError("limit must be an integer between 1 and 100.")
    memories = search_memories(layer=layer, project_id=project_id, limit=limit, include_archived=include_archived)
    content, truncated = cap_text(format_memory_records(memories), definition.max_chars)
    return ToolResult(
        tool=definition.name,
        ok=True,
        content=content,
        summary=f"Listed {len(memories)} memor{'y' if len(memories) == 1 else 'ies'}.",
        arguments_summary={"layer": layer or "", "limit": limit},
        truncated=truncated,
    )


def update_memory_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    memory_id = str(arguments.get("memory_id", "")).strip()
    if not memory_id:
        raise ToolExecutionError("memory_id is required.")
    update_fields = {key for key in ("title", "summary", "kind", "importance", "tags", "project_id", "source") if key in arguments}
    if not update_fields:
        raise ToolExecutionError("At least one memory field to update is required.")
    tags = [str(tag) for tag in arguments.get("tags", []) if isinstance(tag, str)] if "tags" in arguments else None
    memory = update_generic_memory(
        memory_id,
        title=str(arguments["title"]).strip() if "title" in arguments else None,
        summary=str(arguments["summary"]).strip() if "summary" in arguments else None,
        kind=str(arguments["kind"]).strip() if "kind" in arguments else None,
        importance=int(arguments["importance"]) if "importance" in arguments else None,
        project_id=str(arguments["project_id"]).strip() if "project_id" in arguments else None,
        source=str(arguments["source"]).strip() if "source" in arguments else None,
        tags=tags,
        metadata_patch={"updated_by": "model"},
    )
    return ToolResult(
        tool=definition.name,
        ok=True,
        content=json.dumps(memory_to_json(memory), indent=2),
        summary=f"Updated {memory.layer} memory: {memory.title}",
        arguments_summary={"memory_id": memory.id, "layer": memory.layer, "title": memory.title},
    )


def archive_memory_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    memory_id = str(arguments.get("memory_id", "")).strip()
    reason = str(arguments.get("reason", "")).strip()
    if not memory_id:
        raise ToolExecutionError("memory_id is required.")
    if not reason:
        raise ToolExecutionError("reason is required.")
    memory = archive_memory(memory_id, reason=reason, source="model_tool")
    return ToolResult(
        tool=definition.name,
        ok=True,
        content=json.dumps(memory_to_json(memory), indent=2),
        summary=f"Archived {memory.layer} memory: {memory.title}",
        arguments_summary={"memory_id": memory.id, "layer": memory.layer, "title": memory.title},
    )


def move_memory_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    memory_id = str(arguments.get("memory_id", "")).strip()
    new_layer = str(arguments.get("new_layer", "")).strip()
    reason = str(arguments.get("reason", "")).strip()
    source = str(arguments.get("source", "model_tool")).strip() or "model_tool"
    if not memory_id:
        raise ToolExecutionError("memory_id is required.")
    memory = move_memory(
        memory_id,
        new_layer=new_layer,
        reason=reason,
        source=source,
        source_metadata={"tool": definition.name},
    )
    return ToolResult(
        tool=definition.name,
        ok=True,
        content=json.dumps(memory_to_json(memory), indent=2),
        summary=f"Moved memory to {memory.layer}: {memory.title}",
        arguments_summary={"memory_id": memory.id, "layer": memory.layer, "title": memory.title},
    )


def merge_memory_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    target_memory_id = str(arguments.get("target_memory_id", "")).strip()
    source_memory_ids = [str(memory_id) for memory_id in arguments.get("source_memory_ids", []) if isinstance(memory_id, str)]
    reason = str(arguments.get("reason", "")).strip()
    if not target_memory_id:
        raise ToolExecutionError("target_memory_id is required.")
    if not source_memory_ids:
        raise ToolExecutionError("source_memory_ids must contain at least one memory id.")
    if not reason:
        raise ToolExecutionError("reason is required.")
    tags = [str(tag) for tag in arguments.get("tags", []) if isinstance(tag, str)] if "tags" in arguments else None
    memory = merge_memories(
        target_memory_id=target_memory_id,
        source_memory_ids=source_memory_ids,
        reason=reason,
        title=str(arguments["title"]).strip() if "title" in arguments else None,
        summary=str(arguments["summary"]).strip() if "summary" in arguments else None,
        kind=str(arguments["kind"]).strip() if "kind" in arguments else None,
        tags=tags,
        source="model_tool",
        source_metadata={"tool": definition.name},
    )
    return ToolResult(
        tool=definition.name,
        ok=True,
        content=json.dumps(memory_to_json(memory), indent=2),
        summary=f"Merged memory into {memory.layer}: {memory.title}",
        arguments_summary={"memory_id": memory.id, "layer": memory.layer, "title": memory.title},
    )


def format_memory_records(memories: list[Any]) -> str:
    if not memories:
        return "No memories matched."
    lines = ["[Canonical Memories]", "Use memory_id for update_memory, archive_memory, or move_memory calls.", ""]
    for memory in memories:
        archived = f" archived_at={memory.archived_at}" if memory.archived_at else ""
        tags = f" tags={memory.tags}" if memory.tags else ""
        project = f" project_id={memory.project_id}" if memory.project_id else ""
        lines.append(
            f"- memory_id={memory.id} layer={memory.layer} kind={memory.kind} importance={memory.importance}{project}{tags}{archived}\n"
            f"  title: {memory.title}\n"
            f"  summary: {memory.summary}"
        )
    return "\n".join(lines)


def record_episode_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    title = str(arguments.get("title", "")).strip()
    summary = str(arguments.get("summary", "")).strip()
    episode_type = str(arguments.get("type", "episode")).strip() or "episode"
    importance = int(arguments.get("importance", 3))
    tags = [str(tag) for tag in arguments.get("tags", []) if isinstance(tag, str)]
    emotional_tone = str(arguments.get("emotional_tone", "")).strip() or None
    project_id = str(arguments.get("project_id", "")).strip() or None
    explicit_user_request = bool(arguments.get("explicit_user_request", False))
    conversation_id = str(arguments.get("conversation_id", "")).strip() or None

    if not title:
        raise ToolExecutionError("title is required.")
    if not summary:
        raise ToolExecutionError("summary is required.")

    # Anti-spam: max 2 auto-created per conversation
    if conversation_id and not explicit_user_request:
        auto_count = count_auto_episodes_for_conversation(conversation_id)
        if auto_count >= 2:
            return ToolResult(
                tool=definition.name,
                ok=False,
                content="",
                summary="Episode auto-save limit reached for this conversation.",
                arguments_summary={"title": title},
                error="Auto-save limit: max 2 auto-created episodic memories per conversation. Use explicit_user_request=true if the user explicitly asked to remember this.",
            )

    # Simple duplicate detection: same normalized title in last 24h
    normalized_title = title.lower().strip()
    recent = search_episodes(query=title, limit=10)
    for ep in recent:
        if ep.title.lower().strip() == normalized_title:
            return ToolResult(
                tool=definition.name,
                ok=False,
                content="",
                summary="Duplicate episode detected.",
                arguments_summary={"title": title},
                error=f"An episode with a very similar title already exists: \"{ep.title}\". If this is meaningfully different, adjust the title.",
            )

    creation_mode = "explicit_user_request" if explicit_user_request else "auto"
    metadata = {
        "created_by": "model",
        "creation_mode": creation_mode,
    }

    episode = create_episode(
        title=title,
        summary=summary,
        type=episode_type,
        importance=importance,
        conversation_id=conversation_id,
        project_id=project_id,
        emotional_tone=emotional_tone,
        tags=tags,
        metadata=metadata,
    )

    return ToolResult(
        tool=definition.name,
        ok=True,
        content=f"Saved episode: \"{episode.title}\" (importance {episode.importance})",
        summary=f"Saved episodic memory: {episode.title}",
        arguments_summary={"title": episode.title},
    )


def update_episode_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    episode = resolve_episode_by_id_or_query(arguments)

    update_fields = {
        key
        for key in ("title", "summary", "type", "importance", "tags", "emotional_tone", "project_id")
        if key in arguments
    }
    if not update_fields:
        raise ToolExecutionError("At least one memory field to update is required.")

    title = str(arguments["title"]).strip() if "title" in arguments else None
    summary = str(arguments["summary"]).strip() if "summary" in arguments else None
    episode_type = str(arguments["type"]).strip() if "type" in arguments else None
    importance = int(arguments["importance"]) if "importance" in arguments else None
    tags = [str(tag) for tag in arguments.get("tags", []) if isinstance(tag, str)] if "tags" in arguments else None
    emotional_tone = str(arguments["emotional_tone"]).strip() if "emotional_tone" in arguments else None
    project_id = str(arguments["project_id"]).strip() if "project_id" in arguments else None

    if title is not None and not title:
        raise ToolExecutionError("title cannot be empty when provided.")
    if summary is not None and not summary:
        raise ToolExecutionError("summary cannot be empty when provided.")

    updated = update_episode(
        episode.id,
        title=title,
        summary=summary,
        type=episode_type,
        importance=importance,
        tags=tags,
        emotional_tone=emotional_tone,
        project_id=project_id,
        metadata_patch={"updated_by": "model"},
    )

    return ToolResult(
        tool=definition.name,
        ok=True,
        content=f"Updated episode: \"{updated.title}\" (importance {updated.importance})",
        summary=f"Updated episodic memory: {updated.title}",
        arguments_summary={"episode_id": updated.id, "title": updated.title},
    )


def forget_episode_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    if arguments.get("explicit_user_request") is not True:
        raise ToolExecutionError("forget_episode requires explicit_user_request=true because memory deletion is destructive.")

    episode = resolve_episode_by_id_or_query(arguments)
    deleted = delete_episode(episode.id)

    return ToolResult(
        tool=definition.name,
        ok=True,
        content=f"Forgot episode: \"{deleted.title}\"",
        summary=f"Forgot episodic memory: {deleted.title}",
        arguments_summary={"episode_id": deleted.id, "title": deleted.title},
    )


def resolve_episode_by_id_or_query(arguments: dict[str, object]):
    episode_id = str(arguments.get("episode_id", "")).strip()
    if episode_id:
        try:
            return get_episode(episode_id)
        except ValueError as error:
            raise ToolExecutionError(str(error)) from error

    query = str(arguments.get("title_query", "")).strip()
    if not query:
        raise ToolExecutionError("episode_id or title_query is required.")

    matches = search_episodes(query=query, limit=5)
    exact = [episode for episode in matches if episode.title.strip().lower() == query.lower()]
    candidates = exact or matches
    if not candidates:
        raise ToolExecutionError(f"No episodic memory matched title_query: {query}")
    if len(candidates) > 1:
        titles = ", ".join(f'"{episode.title}"' for episode in candidates[:5])
        raise ToolExecutionError(f"title_query matched multiple episodic memories: {titles}. Use a more specific title_query.")
    return candidates[0]


def record_project_memory_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    project_id = require_registered_project_id(arguments)
    category = str(arguments.get("category", "")).strip()
    content = str(arguments.get("content", "")).strip()
    conversation_id = str(arguments.get("conversation_id", "")).strip() or None

    if not category:
        raise ToolExecutionError("category is required.")
    if not content:
        raise ToolExecutionError("content is required.")

    duplicate_note = find_similar_project_note(project_id, category, content)
    if duplicate_note:
        regenerate_librarian_card(project_id)
        return ToolResult(
            tool=definition.name,
            ok=True,
            content=f"Project memory already has a similar {category} note for {project_id}; skipped duplicate.",
            summary=f"Skipped duplicate {category} project memory for {project_id}.",
            arguments_summary={"project_id": project_id, "category": category},
        )

    note_id = record_project_note(
        project_id=project_id,
        category=category,
        content=content,
        source_chat_id=conversation_id,
    )

    # Lazily regenerate the librarian card so keyword-based whisper searches
    # pick up the new note without waiting for the next full project index.
    regenerate_librarian_card(project_id)

    return ToolResult(
        tool=definition.name,
        ok=True,
        content=f"Added {category} note to project {project_id} (note id: {note_id}).",
        summary=f"Recorded {category} in project memory for {project_id}.",
        arguments_summary={"project_id": project_id, "category": category},
    )


def update_project_memory_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    project_id = require_registered_project_id(arguments)
    section = str(arguments.get("section", "")).strip()
    data = arguments.get("data")
    conversation_id = str(arguments.get("conversation_id", "")).strip() or None

    if not section:
        raise ToolExecutionError("section is required.")
    if not isinstance(data, dict):
        raise ToolExecutionError("data must be an object.")

    try:
        result = update_structured_project_memory(
            project_id=project_id,
            section=section,
            data=data,
            source_chat_id=conversation_id,
        )
    except ValueError as error:
        raise ToolExecutionError(str(error)) from error

    return ToolResult(
        tool=definition.name,
        ok=True,
        content=json.dumps(result, indent=2),
        summary=str(result.get("summary") or f"Updated {section} project memory for {project_id}."),
        arguments_summary={"project_id": project_id, "section": section},
    )


def regenerate_librarian_card(project_id: str) -> None:
    try:
        from .librarian import regenerate_card
        regenerate_card(project_id)
    except Exception:
        pass


def find_similar_project_note(project_id: str, category: str, content: str) -> bool:
    """Best-effort duplicate guard for automatic memory stewardship.

    The steward may run after many useful tool calls. Exact duplicate and near-prefix
    checks keep it from adding the same durable project fact over and over while
    avoiding hard failures if the project database is unavailable.
    """
    normalized_content = normalize_memory_note(content)
    if not normalized_content:
        return False

    try:
        project = load_project(project_id)
        if not project.database_path.exists():
            return False
        with db_connection(project.database_path) as connection:
            rows = connection.execute(
                """
                select content from project_notes
                where category = ?
                order by id desc
                limit 50
                """,
                (category,),
            ).fetchall()
    except Exception:
        return False

    for (existing_content,) in rows:
        normalized_existing = normalize_memory_note(str(existing_content or ""))
        if not normalized_existing:
            continue
        if normalized_existing == normalized_content:
            return True
        shorter, longer = sorted((normalized_existing, normalized_content), key=len)
        if len(shorter) >= 80 and shorter in longer:
            return True

    return False


def normalize_memory_note(text: str) -> str:
    return " ".join(str(text or "").lower().split())


def format_mcp_tool_content(response: dict[str, object]) -> str:
    content = response.get("content")
    if not isinstance(content, list):
        return json.dumps(response, indent=2, default=str)
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            parts.append(str(item))
            continue
        kind = str(item.get("type") or "")
        if kind == "text" and isinstance(item.get("text"), str):
            parts.append(str(item["text"]))
        else:
            parts.append(json.dumps(item, indent=2, default=str))
    return "\n\n".join(part for part in parts if part).strip() or json.dumps(response, indent=2, default=str)


def summarize_mcp_arguments(server_name: str, tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
    summary = {"mcp_server": server_name, "mcp_tool": tool_name}
    for key in ("app_id", "window_id", "title", "name", "role", "text", "selector", "action", "keys"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            summary[key] = value[:240]
        elif isinstance(value, (int, float, bool)):
            summary[key] = value
        elif isinstance(value, dict):
            summary[key] = json.dumps(value, sort_keys=True, default=str)[:240]
    return summary


def require_relative_file_path(arguments: dict[str, object]) -> str:
    path = arguments.get("file_path")
    if not isinstance(path, str) or not path.strip():
        raise ToolExecutionError("A project-relative file_path string is required.")
    return require_relative_path(path)


def require_writable_file_path(arguments: dict[str, object]) -> str:
    path = arguments.get("file_path")
    if not isinstance(path, str) or not path.strip():
        raise ToolExecutionError("A file_path string is required.")
    return require_writable_path(path, arguments)


def require_writable_path(path: str, arguments: dict[str, object]) -> str:
    clean = path.strip()
    if ".." in Path(clean).parts:
        raise ToolExecutionError("Paths containing '..' are not allowed.")
    if explicit_path(clean) and not has_selected_write_root(arguments):
        return clean
    return require_relative_path(clean)


def require_relative_path(path: str) -> str:
    relative_path = path.strip()
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ToolExecutionError("Only relative paths without '..' are allowed.")
    return str(candidate)


def explicit_path(path: str) -> bool:
    return Path(path).expanduser().is_absolute()


def has_selected_write_root(arguments: dict[str, object]) -> bool:
    return bool(str(arguments.get("project_id") or "").strip() or str(arguments.get("root_path") or "").strip())


def resolve_writable_path(arguments: dict[str, object], writable_path: str) -> Path:
    project_id = arguments.get("project_id")
    if isinstance(project_id, str) and project_id.strip():
        project = load_project(project_id.strip())
        if not project.paths:
            raise ToolExecutionError(f"Project has no registered paths: {project_id}")
        base = project.paths[0] if project.paths[0].is_dir() else project.paths[0].parent
    else:
        root_path = arguments.get("root_path")
        if not isinstance(root_path, str) or not root_path.strip():
            candidate = Path(writable_path).expanduser()
            if candidate.is_absolute():
                return candidate.resolve()
        base = Path(str(root_path)).expanduser() if isinstance(root_path, str) and root_path.strip() else ARTIFACTS_DIR
        if not base.is_absolute():
            base = (Path.cwd() / base).resolve()
    return resolve_tool_child_path(base.resolve(), writable_path)


def resolve_shell_working_directory(arguments: dict[str, object]) -> Path | None:
    raw = arguments.get("working_directory")
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise ToolExecutionError("working_directory must be a non-empty string when provided.")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    path = path.resolve()
    if not path.exists():
        raise ToolExecutionError(f"working_directory does not exist: {path}")
    if not path.is_dir():
        raise ToolExecutionError(f"working_directory is not a directory: {path}")
    return path


def make_patch_preview(old_text: str, new_text: str) -> str:
    return "\n".join([
        "--- old_text",
        old_text,
        "+++ new_text",
        new_text,
    ])


def file_diff_metadata(path: str, old_text: str, new_text: str, status: str) -> dict[str, object]:
    display_path = diff_display_path(path)
    lines = list(
        difflib.unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile=f"a/{display_path}",
            tofile=f"b/{display_path}",
            lineterm="",
        )
    )
    added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
    unified = "\n".join(lines)
    truncated = len(unified) > MAX_DIFF_CHARS
    if truncated:
        unified = unified[:MAX_DIFF_CHARS].rstrip() + "\n... diff truncated ..."

    return {
        "diff": {
            "files": [
                {
                    "path": display_path,
                    "status": status,
                    "added": added,
                    "removed": removed,
                    "unified": unified,
                    "truncated": truncated,
                }
            ]
        }
    }


def diff_display_path(path: str) -> str:
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(f"{home}/"):
        return f"~/{path[len(home) + 1:]}"
    return path.lstrip("/") if path.startswith("/") else path


def resolve_tool_base_path(arguments: dict[str, object]) -> Path:
    project_id = arguments.get("project_id")
    if isinstance(project_id, str) and project_id.strip():
        project = load_project(project_id.strip())
        if not project.paths:
            raise ToolExecutionError(f"Project has no registered paths: {project_id}")
        first = project.paths[0]
        return (first if first.is_dir() else first.parent).resolve()

    root_path = str(arguments.get("root_path") or arguments.get("path") or ".").strip() or "."
    path = Path(root_path).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path.resolve()


def resolve_tool_child_path(base: Path, child_path: str) -> Path:
    candidate = Path(child_path).expanduser()
    if not candidate.is_absolute():
        candidate = (base / candidate).resolve()
    candidate = candidate.resolve()
    try:
        candidate.relative_to(base.resolve())
    except ValueError:
        raise ToolExecutionError("Path escapes the selected root.")
    return candidate


def resolve_tool_file(arguments: dict[str, object], file_path: str) -> Path:
    project_id = arguments.get("project_id")
    if isinstance(project_id, str) and project_id.strip():
        project = load_project(project_id.strip())
        return resolve_project_file(project.paths, file_path)
    return resolve_tool_child_path(resolve_tool_base_path(arguments), file_path)


def should_skip_path(path: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def safe_read_text_file(path: Path) -> str:
    if not path.exists():
        raise ToolExecutionError(f"File not found: {path}")
    if not path.is_file():
        raise ToolExecutionError(f"Path is not a file: {path}")
    if should_skip_path(path):
        raise ToolExecutionError("Refusing to read a skipped directory path.")
    if path.suffix.lower() in SKIP_SUFFIXES:
        raise ToolExecutionError(f"Refusing to read skipped file type: {path.suffix.lower()}")
    stat = path.stat()
    if stat.st_size > MAX_FILE_BYTES:
        raise ToolExecutionError(f"Refusing to read file larger than {MAX_FILE_BYTES} bytes.")
    raw = path.read_bytes()
    if b"\x00" in raw[:4096]:
        raise ToolExecutionError("Refusing to read binary-looking file content.")
    return raw.decode("utf-8", errors="replace")


def int_value(value: object, fallback: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def summarize_file_tool_args(arguments: dict[str, object], **extra: object) -> dict[str, object]:
    summary = dict(extra)
    for key in ("project_id", "root_path", "path", "file_path"):
        value = arguments.get(key)
        if isinstance(value, str) and value.strip():
            summary[key] = value[:240]
    return summary


def resolve_project_file(roots: tuple[Path, ...], relative_path: str) -> Path:
    for root in roots:
        base = root if root.is_dir() else root.parent
        candidate = (base / relative_path).resolve()
        try:
            candidate.relative_to(base.resolve())
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    raise ToolExecutionError(f"Project file not found: {relative_path}")


def enable_desktop_control_tool(arguments: dict[str, object], definition: ToolDefinition) -> ToolResult:
    from ..desktop_control import enable_desktop_control, render_report, report_to_json

    report = enable_desktop_control()
    content, truncated = cap_text(render_report(report), definition.max_chars)
    enabled = sum(1 for cap in report.capabilities if cap.status == "enabled")
    summary = (
        "Desktop control is ready." if report.ready
        else f"Desktop control partially enabled ({enabled}/{len(report.capabilities)} capabilities); see remediation."
    )
    return ToolResult(definition.name, True, content, summary, {}, truncated=truncated, metadata=report_to_json(report))
