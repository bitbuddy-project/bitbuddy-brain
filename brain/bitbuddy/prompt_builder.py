from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .chats.repository import list_recent_chats, recent_continuity_context
from .continuity import build_continuity_digest
from .chats.state import (
    LAST_PROMPT_USAGE_BY_CHAT_ID,
    LAST_PROMPT_USAGE_LOCK,
    active_chat_run,
)
from .config import load_config
from .autonomy.intentions import list_pending_intentions
from .librarian import build_advisory_whisper_message
from .personality import build_personality_prompt, load_selected_personality
from .memory.project import load_project, project_list_context
from .memory.store import layered_memory_context
from .providers import ProviderClient
from .self_notes import select_self_notes_for_context
from .self_model import self_context_prompt
from .skills import skill_catalog_prompt
from .tools import default_tool_registry, normalize_mode, tool_instruction_message


def session_gap_note(current_chat_id: str = "") -> str:
    """Return a one-line note about how long ago the last conversation was."""
    try:
        from datetime import timezone, timedelta
        chats = list_recent_chats(limit=6)
        other = next((c for c in chats if c.id != current_chat_id), None)
        if not other or not other.updated_at:
            return ""
        last_str = str(other.updated_at).replace("Z", "+00:00")
        try:
            last_dt = datetime.fromisoformat(last_str)
        except ValueError:
            return ""
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - last_dt
        hours = delta.total_seconds() / 3600
        title = str(other.title or "").strip()
        title_note = f' (last: "{title[:60]}")' if title else ""
        if hours < 0.5:
            return ""
        if hours < 4:
            return f"Last session was a few hours ago{title_note}."
        if hours < 24:
            return f"Returning after ~{int(hours)} hours{title_note}."
        days = int(delta.days)
        if days == 1:
            return f"It's been 1 day since your last conversation{title_note}."
        if days <= 3:
            return f"It's been {days} days since your last conversation{title_note}."
        return f"It's been {days} days — a notable gap{title_note}."
    except Exception:
        return ""


TOOLS_WITH_USEFUL_RESULT_CONTENT = {"get_project_brief", "get_project_memory", "search_memory", "list_memory", "read_file", "write_file", "patch_file", "run_shell_command", "load_skill"}
MAX_RAW_TOOL_HISTORY_EVENTS = 3
PREVIOUS_TOOL_RESULT_CONTENT_CHARS = 24000
PREVIOUS_TOOL_SUMMARY_CHARS = 4000
MAX_CACHED_TOOL_RESULTS_PER_CHAT = 6

_RECENT_TOOL_RESULT_CONTEXT_LOCK = threading.Lock()
_RECENT_TOOL_RESULT_CONTEXT_BY_CHAT_ID: dict[str, list[dict[str, Any]]] = {}
_RECENT_TOOL_RESULT_CONTEXT_GLOBAL: list[dict[str, Any]] = []
MAX_GLOBAL_CACHED_TOOL_RESULTS = 20


def remember_tool_result_context(chat_id: str, result: Any) -> None:
    """Keep recent successful tool results available even if the frontend omits tool events.

    The normal path is still persisted tool-event metadata. This in-process cache is a
    safety net for follow-up turns where the UI only sends visible chat bubbles back to
    the backend. It lets Vanta answer "what did you learn?" from the actual file/tool
    result instead of from a receipt message.
    """
    if not getattr(result, "ok", False):
        return

    tool = str(getattr(result, "tool", "") or "")
    if tool not in TOOLS_WITH_USEFUL_RESULT_CONTENT and not tool.startswith("mcp_"):
        return

    content = str(getattr(result, "content", "") or "").strip()
    if not content:
        return

    arguments = getattr(result, "arguments_summary", {})
    if not isinstance(arguments, dict):
        arguments = {}

    entry = {
        "tool": tool,
        "status": "completed",
        "arguments_summary": dict(arguments),
        "result_summary": str(getattr(result, "summary", "") or ""),
        "result_content": content,
        "truncated": bool(getattr(result, "truncated", False)),
    }

    signature = cached_tool_signature(entry)

    with _RECENT_TOOL_RESULT_CONTEXT_LOCK:
        if chat_id:
            entries = _RECENT_TOOL_RESULT_CONTEXT_BY_CHAT_ID.setdefault(chat_id, [])
            entries[:] = [old for old in entries if cached_tool_signature(old) != signature]
            entries.append(entry)
            del entries[:-MAX_CACHED_TOOL_RESULTS_PER_CHAT]

        # Backup path: some chat-history/API paths rebuild prompts without passing
        # chat_id or without returning hidden tool-event metadata. Keep a small
        # process-local index and only inject from it when the visible transcript
        # matches the specific tool result (for example README.md + project id).
        _RECENT_TOOL_RESULT_CONTEXT_GLOBAL[:] = [
            old for old in _RECENT_TOOL_RESULT_CONTEXT_GLOBAL if cached_tool_signature(old) != signature
        ]
        _RECENT_TOOL_RESULT_CONTEXT_GLOBAL.append(entry)
        del _RECENT_TOOL_RESULT_CONTEXT_GLOBAL[:-MAX_GLOBAL_CACHED_TOOL_RESULTS]


def cached_tool_signature(entry: dict[str, Any]) -> str:
    arguments = entry.get("arguments_summary") if isinstance(entry.get("arguments_summary"), dict) else {}
    return json.dumps(
        {
            "tool": entry.get("tool", ""),
            "project_id": arguments.get("project_id", ""),
            "file_path": arguments.get("file_path", ""),
            "command": arguments.get("command", ""),
            "mcp_server": arguments.get("mcp_server", ""),
            "mcp_tool": arguments.get("mcp_tool", ""),
        },
        sort_keys=True,
    )



def chat_context_usage(body: dict[str, Any]) -> dict[str, Any]:
    messages = body.get("messages")
    if not isinstance(messages, list):
        messages = []

    mode = body.get("mode") if isinstance(body.get("mode"), str) else "chat"
    model = body.get("model") if isinstance(body.get("model"), str) else None
    chat_id = body.get("chat_id") if isinstance(body.get("chat_id"), str) else ""

    client = ProviderClient(load_config().provider)
    context = client.context_window(model=model)
    base_prompt_messages = build_chat_messages(messages, mode, chat_id=chat_id)
    token_count = client.count_tokens(base_prompt_messages, model=model)

    base_usage = {
        "provider": context.get("provider"),
        "model": context.get("model"),
        "used_tokens": token_count.get("used_tokens"),
        "context_window_tokens": context.get("context_window_tokens"),
        "usage_source": token_count.get("source"),
        "window_source": context.get("source"),
        "message_count": len(base_prompt_messages),
        "measurement": "base_estimate",
    }

    runtime_usage: dict[str, Any] | None = None

    if chat_id:
        active = active_chat_run(chat_id)
        if active is not None and active.context_usage:
            runtime_usage = active.context_usage
        else:
            with LAST_PROMPT_USAGE_LOCK:
                previous = LAST_PROMPT_USAGE_BY_CHAT_ID.get(chat_id)
                runtime_usage = dict(previous) if previous else None

    selected_usage = runtime_usage or base_usage

    return {
        "provider": selected_usage.get("provider", base_usage.get("provider")),
        "model": selected_usage.get("model", base_usage.get("model")),
        "used_tokens": selected_usage.get("used_tokens"),
        "context_window_tokens": selected_usage.get(
            "context_window_tokens",
            base_usage.get("context_window_tokens"),
        ),
        "usage_source": selected_usage.get("usage_source"),
        "window_source": selected_usage.get("window_source", base_usage.get("window_source")),
        "measurement": selected_usage.get("measurement", "base_estimate"),
        "label": selected_usage.get("label", "base_prompt"),
        "message_count": selected_usage.get("message_count", base_usage.get("message_count")),
        "base_usage": base_usage,
        "runtime_usage": runtime_usage,
    }


def build_chat_messages(messages: list[dict[str, Any]], mode: str, chat_id: str = "") -> list[dict[str, Any]]:
    config = load_config()
    personality = load_selected_personality(config.personality)
    mode = normalize_mode(mode)

    project_registry = project_list_context(max_projects=10, max_chars=1200)

    system_parts = [
        build_personality_prompt(config.name, config.presentation, config.personality, personality),
        user_local_context_prompt(config.user_context),
        "You are model-first: there is no fixed backend route for how the conversation must go.",
        "Use the available tools when they genuinely help, and answer directly when they do not.",
        "Choose the next move naturally: answer, ask a question, call a tool, or acknowledge uncertainty based on the user’s message and the context you already have.",
        "Do not ask low-value filler questions. Ask only when the answer materially affects the task, safety, preferences, blocked work, or a meaningful ongoing thread.",
        "Playful comments are allowed when the user/context clearly welcomes fun; keep important questions clear and useful.",
        "Memory retrieval is runtime-supplied, not a thing you must route through as a tool call. Relevant project cards, layered memories, continuity, and recent tool results may appear below as private context; treat those blocks as your memory surfaces.",
        "Automatic memory writes are handled after your visible answer by BitBuddy’s backend memory broker. Use explicit memory-write tools only when the user clearly asks you to remember/save something or when a visible memory action is essential to this turn.",
        mode_boundary_prompt(mode),
        "Keep private reasoning and tool markup out of normal chat replies.",
        "If the user asks you to create, save, write, generate, export, update, edit, modify, or tweak a file/artifact, do not merely show code or claim a path. In Chat mode, actually create or update it with write_file/patch_file, or create a generator script with write_file and execute it with run_shell_command, then verify it exists.",
    ]

    if project_registry:
        system_parts.append(project_registry)

    try:
        system_parts.append(self_context_prompt())
    except Exception:
        pass

    skill_catalog = skill_catalog_prompt()
    if skill_catalog:
        system_parts.append(skill_catalog)

    result: list[dict[str, str]] = [{"role": "system", "content": "\n\n".join(system_parts)}]

    registry = default_tool_registry()
    result.append(tool_instruction_message(registry))

    latest_text = latest_user_message(messages)

    gap_note = session_gap_note(chat_id)
    continuity = recent_continuity_context(chat_id)
    if continuity or gap_note:
        content = continuity or ""
        if gap_note:
            content = f"[Session gap] {gap_note}\n\n{content}" if content else f"[Session gap] {gap_note}"
        result.append({"role": "system", "content": content.strip()})

    active_project_ids = recent_project_ids_from_messages(messages)
    continuity_digest = build_continuity_digest(
        chat_id=chat_id,
        latest_user_text=latest_text,
        project_id=active_project_ids[0] if active_project_ids else "",
        source="chat",
    )
    if continuity_digest:
        result.append({"role": "system", "content": continuity_digest})

    pending_intentions = pending_intentions_context()
    if pending_intentions:
        result.append({"role": "system", "content": pending_intentions})

    # Advisory librarian whisper — compact, relevant, explicitly optional
    librarian_whisper = build_advisory_whisper_message(
        latest_text,
        max_cards=2,
        max_chars=1200,
        active_project_ids=active_project_ids,
    )
    if librarian_whisper:
        result.append(librarian_whisper)

    layered_memory = layered_memory_context(query=latest_text, project_id=active_project_ids[0] if active_project_ids else None, max_chars=2400)
    if layered_memory:
        result.append({"role": "system", "content": layered_memory})

    self_notes = self_notes_context(latest_text, active_project_ids[0] if active_project_ids else "")
    if self_notes:
        result.append({"role": "system", "content": self_notes})

    result.extend(cached_tool_context_messages(chat_id, messages))
    result.extend(conversation_messages_for_provider(messages))

    return result


def mode_boundary_prompt(mode: str) -> str:
    if mode == "plan":
        return (
            "[Current Mode: Plan]\n"
            "Plan mode is strictly read-only. You may inspect, search, and read. Do not write, create, update, archive, move, merge, delete, install, run tests/builds, or otherwise mutate files, memory, projects, or system state."
        )
    if mode == "debug":
        return (
            "[Current Mode: Debug]\n"
            "Debug mode allows reading and allows write/create/update/archive/move/merge/delete operations only when they are directly related to diagnosing, reproducing, testing, or fixing a bug/error/failure. Do not use Debug mode for unrelated feature work or general cleanup."
        )
    return (
        "[Current Mode: Chat]\n"
        "Chat mode is unrestricted by mode boundaries. Normal permission checks still apply for sensitive tool actions."
    )


def pending_intentions_context() -> str:
    intentions = list_pending_intentions(limit=5)
    if not intentions:
        return ""
    lines = [
        "[Pending BitBuddy Intentions]",
        "These are BitBuddy-owned questions/comments generated during safe idle autonomy.",
        "If you have not mentioned any recently, consider bringing one up naturally.",
    ]
    for intention in intentions:
        lines.append(f"- id {intention.id} {intention.kind}: {intention.content}")
        project_context = intention_project_context(intention.metadata)
        if project_context:
            lines.append(f"  project: {project_context}")
        if intention.reason:
            lines.append(f"  reason: {intention.reason}")
    return "\n".join(lines)


def self_notes_context(query: str, project_id: str = "") -> str:
    config = load_config()
    if not config.dreaming.self_note_injection_enabled:
        return ""
    notes = select_self_notes_for_context(query=query, project_id=project_id, limit=3, mark_injected=True)
    if not notes:
        return ""
    lines = [
        "[BitBuddy SelfNotes]",
        "Small, relevant reminders BitBuddy left for her future self. Use only if helpful; current user message wins.",
    ]
    for note in notes:
        lines.append(f"- {note.kind} priority={note.priority}: {note.text}")
    return "\n".join(lines)


def intention_project_context(metadata: dict[str, Any]) -> str:
    if not isinstance(metadata, dict):
        return ""
    project_id = str(metadata.get("project_id") or "").strip()
    if not project_id:
        return ""
    try:
        project = load_project(project_id)
    except Exception:
        return project_id
    paths = ", ".join(str(path) for path in project.paths[:2])
    return f"{project.name} ({project.id})" + (f" paths={paths}" if paths else "")


def user_local_context_prompt(user_context: Any) -> str:
    timezone = str(getattr(user_context, "timezone", "UTC") or "UTC")
    now = datetime.now(ZoneInfo(timezone))
    hour = now.strftime("%I").lstrip("0") or "0"
    current_time = (
        f"{now.strftime('%A')}, {now.strftime('%B')} {now.day}, {now.year}, "
        f"{hour}:{now.strftime('%M')} {now.strftime('%p')} {now.tzname()}"
    )

    lines = [
        "[User Local Context]",
        f"Timezone: {timezone}",
        f"Current local date/time: {current_time}",
    ]
    location = str(getattr(user_context, "location_label", "") or "").strip()
    locale = str(getattr(user_context, "locale", "") or "").strip()
    if location:
        lines.insert(1, f"Location: {location}")
    if locale:
        lines.append(f"Locale: {locale}")

    return "\n".join(lines)


def message_metadata(message: dict[str, Any]) -> dict[str, Any]:
    """Return metadata whether the caller provided it as a dict or JSON string.

    Some frontend/API paths may serialize tool metadata before sending chat
    history back to the backend. If result_content is present, this keeps it
    available to the model as private prompt context on follow-up turns.
    """
    metadata = message.get("metadata")
    if isinstance(metadata, dict):
        return metadata
    if isinstance(metadata, str) and metadata.strip():
        try:
            parsed = json.loads(metadata)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def recent_project_ids_from_messages(messages: list[dict[str, Any]], limit: int = 2) -> list[str]:
    """Return recent project ids from tool events for active-chat affinity."""
    result: list[str] = []
    seen: set[str] = set()

    for message in reversed(messages):
        metadata = message_metadata(message)
        arguments = metadata.get("arguments_summary") if isinstance(metadata.get("arguments_summary"), dict) else {}
        project_id = str(arguments.get("project_id") or metadata.get("project_id") or "").strip()
        if not project_id or project_id in seen:
            continue
        seen.add(project_id)
        result.append(project_id)
        if len(result) >= limit:
            break

    return result


def cached_tool_context_messages(chat_id: str, messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Return cached private tool-result context not already present in message history."""
    if not chat_id:
        return []

    represented_signatures: set[str] = set()
    for message in messages:
        if message.get("kind", "message") != "tool":
            continue
        metadata = message_metadata(message)
        if isinstance(metadata.get("result_content"), str) and metadata.get("result_content", "").strip():
            represented_signatures.add(
                cached_tool_signature(
                    {
                        "tool": metadata.get("tool", ""),
                        "arguments_summary": metadata.get("arguments_summary", {})
                        if isinstance(metadata.get("arguments_summary"), dict)
                        else {},
                    }
                )
            )

    visible_text = json.dumps(messages, ensure_ascii=False).lower()

    with _RECENT_TOOL_RESULT_CONTEXT_LOCK:
        cached = [dict(entry) for entry in _RECENT_TOOL_RESULT_CONTEXT_BY_CHAT_ID.get(chat_id, [])] if chat_id else []

        # Backup if the caller forgot chat_id or the frontend omitted tool events.
        # Only include globally cached entries whose project/file/command appears
        # in the visible transcript so unrelated chats do not get random context.
        global_matches = [
            dict(entry)
            for entry in _RECENT_TOOL_RESULT_CONTEXT_GLOBAL
            if cached_tool_signature(entry) not in represented_signatures
            and cached_tool_signature(entry) not in {cached_tool_signature(c) for c in cached}
            and cached_entry_matches_visible_history(entry, visible_text)
        ]

    result: list[dict[str, str]] = []
    for entry in [*cached, *global_matches]:
        if cached_tool_signature(entry) in represented_signatures:
            continue
        result.append(tool_context_entry_message(entry, source="cached"))
    return result


def cached_entry_matches_visible_history(entry: dict[str, Any], visible_text: str) -> bool:
    """Conservative guard for global cache fallback injection."""
    arguments = entry.get("arguments_summary") if isinstance(entry.get("arguments_summary"), dict) else {}
    tool = str(entry.get("tool") or "").lower()
    project_id = str(arguments.get("project_id") or "").strip().lower()
    file_path = str(arguments.get("file_path") or "").strip().lower()
    command = str(arguments.get("command") or "").strip().lower()

    if tool == "read_file":
        if project_id and file_path:
            return project_id in visible_text and file_path in visible_text
        if file_path:
            return file_path in visible_text
        return False

    if tool in {"get_project_brief", "get_project_memory"}:
        return bool(project_id and project_id in visible_text)

    if tool == "run_shell_command":
        # Do not globally inject arbitrary shell output unless the command itself
        # is clearly represented in the current transcript.
        return bool(command and command in visible_text)

    return False

def tool_context_entry_message(entry: dict[str, Any], source: str = "history") -> dict[str, str]:
    tool = str(entry.get("tool") or "")
    status = str(entry.get("status") or "completed")
    arguments = entry.get("arguments_summary") if isinstance(entry.get("arguments_summary"), dict) else {}
    summary = str(entry.get("result_summary") or "")
    result_content = str(entry.get("result_content") or "")

    lines = [
        "[Previous Tool Result Working Context]",
        "This message is private working context for the assistant, not a new user request.",
        f"source: {source}",
        f"tool: {tool}",
        f"status: {status}",
    ]

    project_id = arguments.get("project_id")
    file_path = arguments.get("file_path")
    command = arguments.get("command")
    if project_id:
        lines.append(f"project_id: {project_id}")
    if file_path:
        lines.append(f"file_path: {file_path}")
    if command:
        lines.append(f"command: {command}")
    if summary:
        lines.append(f"summary: {clipped_text(summary, PREVIOUS_TOOL_SUMMARY_CHARS)}")

    guidance = (
        "This is private working context from a tool that already completed. Use it to answer follow-up questions. "
        "Do not paste raw/full contents unless the user explicitly asks for raw output."
    )
    if tool == "read_file":
        guidance += (
            " The file has already been read. If the user asks what you learned, what it says, or whether you actually read it, "
            "answer from this content directly. Do not call read_file again for the same file unless the user asks to refresh/re-read it."
        )

    lines.extend(["", "result_content_private_working_context:", guidance, clipped_text(result_content, PREVIOUS_TOOL_RESULT_CONTENT_CHARS)])
    return {"role": "user", "content": "\n".join(lines)}


def conversation_messages_for_provider(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    raw_tool_history_indexes = recent_raw_tool_history_indexes(messages)

    for index, message in enumerate(messages):
        kind = message.get("kind", "message") or "message"
        role = message.get("role", "")
        content = message.get("content", "")

        if kind == "tool":
            tool_history = tool_history_message_for_provider(
                message,
                include_result_content=index in raw_tool_history_indexes,
            )
            if tool_history is not None:
                result.append(tool_history)
            continue

        if kind != "message" or role not in {"user", "assistant", "system"} or not isinstance(content, str):
            continue

        if role == "assistant" and not content.strip() and not str(message.get("thinking", "")).strip():
            continue

        if role == "system" and not content.strip():
            continue

        result.append(provider_message_with_attachments(message, role, content))

    return result


def provider_message_with_attachments(message: dict[str, Any], role: str, content: str) -> dict[str, Any]:
    attachments = normalized_attachments(message)
    if role != "user" or not attachments:
        return {"role": role, "content": content}

    text_parts = [content.strip()] if content.strip() else ["Please process the uploaded attachment(s)."]
    images: list[dict[str, str]] = []

    for attachment in attachments:
        kind = str(attachment.get("kind") or "file")
        name = str(attachment.get("name") or "uploaded file")
        mime_type = str(attachment.get("mime_type") or "application/octet-stream")

        if kind == "text":
            text = str(attachment.get("text") or "")
            text_parts.append(
                "\n\n[Uploaded Text Attachment]\n"
                f"filename: {name}\n"
                f"mime_type: {mime_type}\n"
                "content:\n"
                f"{clipped_text(text, 24000)}"
            )
        elif kind == "image":
            data = str(attachment.get("data") or "")
            if data:
                images.append({"name": name, "mime_type": mime_type, "data": data})
            text_parts.append(f"\n\n[Uploaded Image Attachment]\nfilename: {name}\nmime_type: {mime_type}")
        else:
            size = attachment.get("size")
            text_parts.append(f"\n\n[Uploaded File Attachment]\nfilename: {name}\nmime_type: {mime_type}\nsize_bytes: {size}")

    result: dict[str, Any] = {"role": role, "content": "\n".join(part for part in text_parts if part)}
    if images:
        result["attachments"] = images
    return result


def normalized_attachments(message: dict[str, Any]) -> list[dict[str, Any]]:
    attachments = message.get("attachments")
    if not isinstance(attachments, list):
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        attachments = metadata.get("attachments") if isinstance(metadata.get("attachments"), list) else []

    result: list[dict[str, Any]] = []
    for attachment in attachments:
        if isinstance(attachment, dict):
            result.append(attachment)
    return result


def recent_raw_tool_history_indexes(messages: list[dict[str, str]]) -> set[int]:
    """Return indexes of recent tool events whose full result text should stay in prompt history.

    Tool event summaries are enough for old routine calls, but read_file/project-memory
    follow-ups like "what does it say?" need the actual result text on the next turn.
    Keeping only the latest few raw results avoids ballooning every prompt forever.
    """
    indexes: set[int] = set()

    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get("kind", "message") != "tool":
            continue

        metadata = message_metadata(message)
        tool = str(metadata.get("tool") or "")
        status = str(message.get("status") or "")
        result_content = metadata.get("result_content")

        if tool not in TOOLS_WITH_USEFUL_RESULT_CONTENT:
            continue
        if status != "completed":
            continue
        if not isinstance(result_content, str) or not result_content.strip():
            continue

        indexes.add(index)
        if len(indexes) >= MAX_RAW_TOOL_HISTORY_EVENTS:
            break

    return indexes


def clipped_text(text: str, limit: int) -> str:
    clean = text.strip()
    if len(clean) <= limit:
        return clean

    omitted = len(clean) - limit
    suffix = f"\n\n[truncated in prompt history: omitted {omitted} characters]"
    keep = max(0, limit - len(suffix))
    return clean[:keep].rstrip() + suffix


def tool_history_message_for_provider(
    message: dict[str, Any],
    include_result_content: bool = False,
) -> dict[str, str] | None:
    metadata = message_metadata(message)
    tool = metadata.get("tool") or ""

    if tool not in {"get_project_brief", "get_project_memory", "get_episode_memory", "read_file", "run_shell_command", "record_episode", "update_episode", "forget_episode", "record_project_memory", "update_project_memory"} and not tool.startswith("mcp_"):
        return None

    status = str(message.get("status", ""))
    arguments = metadata.get("arguments_summary", {})
    summary = metadata.get("result_summary") or message.get("content", "")
    result_content = metadata.get("result_content")

    lines = [
        "[Previous Tool Event]",
        "This message is private working context for the assistant, not a new user request.",
        f"tool: {tool}",
        f"status: {status}",
    ]

    if isinstance(arguments, dict):
        project_id = arguments.get("project_id")
        file_path = arguments.get("file_path")
        command = arguments.get("command")
        mcp_server = arguments.get("mcp_server")
        mcp_tool = arguments.get("mcp_tool")

        if project_id:
            lines.append(f"project_id: {project_id}")
        if file_path:
            lines.append(f"file_path: {file_path}")
        if command:
            lines.append(f"command: {command}")
        if mcp_server:
            lines.append(f"mcp_server: {mcp_server}")
        if mcp_tool:
            lines.append(f"mcp_tool: {mcp_tool}")

    if summary:
        lines.append(f"summary: {clipped_text(str(summary), PREVIOUS_TOOL_SUMMARY_CHARS)}")

    if include_result_content and isinstance(result_content, str) and result_content.strip():
        guidance = (
            "The content below is already available so you can answer follow-up questions from the previous result. "
            "Do not paste raw/full contents unless the user explicitly asks for raw output."
        )
        if tool == "read_file":
            guidance += (
                " If the user asks whether you actually read it, what you learned, or what it says, "
                "answer from this content directly. Do not call read_file again for the same file unless the user asks to refresh/re-read it."
            )

        lines.extend(
            [
                "",
                "result_content_private_working_context:",
                guidance,
                clipped_text(result_content, PREVIOUS_TOOL_RESULT_CONTENT_CHARS),
            ]
        )

    return {"role": "user", "content": "\n".join(lines)}


def is_tool_working_context_message(content: str) -> bool:
    stripped = str(content or "").lstrip()
    return stripped.startswith(
        (
            "[Tool Result Working Context]",
            "[Previous Tool Result Working Context]",
            "[Previous Tool Event]",
        )
    )


def latest_user_message(messages: list[dict[str, Any]]) -> str:
    """Return the latest real user message, skipping injected tool context.

    Tool results are intentionally injected as role='user' working-context
    messages for provider compatibility. They must not replace the actual
    user's request when routing, synthesizing, or titling a chat.
    """
    for message in reversed(messages):
        content = message.get("content", "")
        if message.get("role") != "user" or not isinstance(content, str) or is_tool_working_context_message(content):
            continue
        if content.strip():
            return content
        attachments = normalized_attachments(message)
        if attachments:
            names = ", ".join(str(attachment.get("name") or "uploaded file") for attachment in attachments[:3])
            return f"Uploaded attachment(s): {names}"

    return ""


def title_from_text(text: str) -> str:
    content = " ".join(text.split())
    if not content:
        return "Untitled chat"

    content = strip_title_preamble(content)
    words = content.split()
    if not words:
        return "Untitled chat"

    title_words: list[str] = []
    for word in words:
        candidate = " ".join([*title_words, word]) if title_words else word
        if len(candidate) > 44:
            break
        title_words.append(word)
        if len(title_words) >= 7:
            break

    title = " ".join(title_words).strip(" ,.;:!?-_")
    if len(title) < 12 and len(content) > len(title):
        title = content[:44].rsplit(" ", 1)[0].strip(" ,.;:!?-_") or content[:44].strip(" ,.;:!?-_")
    return title or "Untitled chat"


def strip_title_preamble(text: str) -> str:
    lowered = text.lower()
    preambles = (
        "can you ",
        "could you ",
        "please ",
        "help me ",
        "i need to ",
        "i want to ",
        "let's ",
        "lets ",
    )
    for preamble in preambles:
        if lowered.startswith(preamble):
            return text[len(preamble):].strip()
    return text
