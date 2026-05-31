from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .database import db_connection
from .memory.episodic import create_episode, episodic_memory_context
from .memory.layers import MemoryLayer
from .memory.store import MemoryRecord, get_memory, search_memories
from .paths import GLOBAL_DB_PATH, ensure_app_dirs


MEANINGFUL_EVENT_TYPES = {
    "user_message_received",
    "assistant_response_completed",
    "tool_run_completed",
    "intention_created",
    "intention_shown",
    "autonomy_completed",
    "memory_consolidation_completed",
    "dream_run_completed",
    "lifecycle_state_changed",
}

MEMORY_WRITE_TOOLS = {
    "record_memory",
    "update_memory",
    "archive_memory",
    "move_memory",
    "merge_memory",
    "record_project_memory",
    "update_project_memory",
}

MEANINGFUL_MARKERS = (
    "active project",
    "architecture",
    "bitbuddy",
    "continuity",
    "corrected",
    "correction",
    "current focus",
    "decided",
    "decision",
    "going forward",
    "implement",
    "memory",
    "next step",
    "plan",
    "project",
    "remember",
    "should",
    "task",
    "vanta",
    "we need",
    "we should",
    "we want",
    "what happened",
)


@dataclass(frozen=True)
class ContinuityEvent:
    id: int
    event_type: str
    source: str
    chat_id: str
    run_id: str
    project_id: str
    topic: str
    summary: str
    metadata: dict[str, Any]
    created_at: str


def ensure_continuity_database() -> None:
    ensure_app_dirs()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            create table if not exists continuity_events (
                id integer primary key autoincrement,
                event_type text not null,
                source text not null default 'system',
                chat_id text not null default '',
                run_id text not null default '',
                project_id text not null default '',
                topic text not null default '',
                summary text not null,
                metadata text not null default '{}',
                created_at text default current_timestamp
            )
            """
        )
        connection.execute("create index if not exists idx_continuity_events_created on continuity_events(created_at desc, id desc)")
        connection.execute("create index if not exists idx_continuity_events_chat on continuity_events(chat_id, id desc)")
        connection.execute(
            """
            create table if not exists continuity_state (
                id integer primary key check (id = 1),
                active_project_id text not null default '',
                active_topic text not null default '',
                last_chat_id text not null default '',
                last_user_message_at text not null default '',
                last_assistant_message_at text not null default '',
                last_user_summary text not null default '',
                last_assistant_action_summary text not null default '',
                last_tool_result_summary text not null default '',
                last_autonomy_summary text not null default '',
                last_memory_update_summary text not null default '',
                last_meaningful_turn_at text not null default '',
                last_meaningful_turn_summary text not null default '',
                unresolved_threads_json text not null default '[]',
                updated_at text default current_timestamp
            )
            """
        )
        connection.execute(
            """
            insert or ignore into continuity_state (id, unresolved_threads_json)
            values (1, '[]')
            """
        )
        connection.execute(
            """
            create table if not exists episodic_memory_capture_log (
                id integer primary key autoincrement,
                source_event_id integer,
                decision text not null,
                target_memory_id text not null default '',
                target_layer text not null default '',
                reason text not null default '',
                created_at text default current_timestamp
            )
            """
        )
        connection.execute("create index if not exists idx_episodic_capture_event on episodic_memory_capture_log(source_event_id)")


def record_continuity_event(
    event_type: str,
    summary: str,
    *,
    source: str = "system",
    chat_id: str = "",
    run_id: str = "",
    project_id: str = "",
    topic: str = "",
    metadata: dict[str, Any] | None = None,
) -> ContinuityEvent:
    ensure_continuity_database()
    clean_summary = compact_text(summary, 1200)
    clean_topic = compact_text(topic or infer_topic(clean_summary), 120)
    with db_connection(GLOBAL_DB_PATH) as connection:
        cursor = connection.execute(
            """
            insert into continuity_events (event_type, source, chat_id, run_id, project_id, topic, summary, metadata)
            values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_type.strip() or "event",
                source.strip() or "system",
                chat_id.strip(),
                run_id.strip(),
                project_id.strip(),
                clean_topic,
                clean_summary,
                json.dumps(metadata or {}),
            ),
        )
        event_id = int(cursor.lastrowid)
        row = connection.execute(
            """
            select id, event_type, source, chat_id, run_id, project_id, topic, summary, metadata, created_at
            from continuity_events where id = ?
            """,
            (event_id,),
        ).fetchone()

    event = event_from_row(row)
    update_continuity_state(event)
    return event


def update_continuity_state(event: ContinuityEvent) -> None:
    ensure_continuity_database()
    state = continuity_state()
    updates: dict[str, Any] = {
        "last_chat_id": event.chat_id or state.get("last_chat_id", ""),
        "active_project_id": event.project_id or state.get("active_project_id", ""),
        "active_topic": event.topic or state.get("active_topic", ""),
        "updated_at": event.created_at,
    }

    if event.event_type == "user_message_received":
        updates["last_user_message_at"] = event.created_at
        updates["last_user_summary"] = event.summary
    elif event.event_type in {"assistant_response_completed", "intention_shown"}:
        updates["last_assistant_message_at"] = event.created_at
        updates["last_assistant_action_summary"] = event.summary
    elif event.event_type == "tool_run_completed":
        updates["last_tool_result_summary"] = event.summary
    elif event.event_type == "autonomy_completed":
        updates["last_autonomy_summary"] = event.summary
    elif event.event_type == "memory_consolidation_completed":
        updates["last_memory_update_summary"] = event.summary
    elif event.event_type == "lifecycle_state_changed":
        updates["last_autonomy_summary"] = event.summary

    if event.event_type in MEANINGFUL_EVENT_TYPES and meaningful_continuity_text(event.summary, event.metadata):
        updates["last_meaningful_turn_at"] = event.created_at
        updates["last_meaningful_turn_summary"] = event.summary

    unresolved = state.get("unresolved_threads", [])
    if not isinstance(unresolved, list):
        unresolved = []
    if event.event_type in {"user_message_received", "assistant_response_completed", "intention_created"} and unresolved_thread_text(event.summary):
        unresolved = [compact_text(event.summary, 280), *[str(item) for item in unresolved if str(item) != event.summary]][:5]
        updates["unresolved_threads_json"] = json.dumps(unresolved)

    assignments = ", ".join(f"{key} = ?" for key in updates)
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            f"update continuity_state set {assignments} where id = 1",
            tuple(updates.values()),
        )


def continuity_state() -> dict[str, Any]:
    ensure_continuity_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute("select * from continuity_state where id = 1").fetchone()
    if row is None:
        return {}
    unresolved = safe_json(row[13], [])
    return {
        "active_project_id": str(row[1] or ""),
        "active_topic": str(row[2] or ""),
        "last_chat_id": str(row[3] or ""),
        "last_user_message_at": str(row[4] or ""),
        "last_assistant_message_at": str(row[5] or ""),
        "last_user_summary": str(row[6] or ""),
        "last_assistant_action_summary": str(row[7] or ""),
        "last_tool_result_summary": str(row[8] or ""),
        "last_autonomy_summary": str(row[9] or ""),
        "last_memory_update_summary": str(row[10] or ""),
        "last_meaningful_turn_at": str(row[11] or ""),
        "last_meaningful_turn_summary": str(row[12] or ""),
        "unresolved_threads": unresolved if isinstance(unresolved, list) else [],
        "updated_at": str(row[14] or ""),
    }


def build_continuity_digest(
    *,
    chat_id: str = "",
    latest_user_text: str = "",
    project_id: str = "",
    source: str = "chat",
    max_chars: int = 2600,
) -> str:
    ensure_continuity_database()
    state = continuity_state()
    events = recent_continuity_events(chat_id=chat_id, limit=8)
    active_project = project_id or str(state.get("active_project_id") or "")
    query = " ".join(part for part in (latest_user_text, state.get("active_topic", ""), state.get("last_meaningful_turn_summary", "")) if part)

    lines = [
        "[Continuity Digest]",
        "Deterministic short-term continuity. Use this to stay oriented; current user message wins over stale context.",
        f"source: {source}",
    ]

    try:
        from .lifecycle import lifecycle_status

        lifecycle = lifecycle_status()
        lines.append(f"lifecycle: {lifecycle.get('state')} quiet_mode={lifecycle.get('quiet_mode')}")
    except Exception:
        pass

    if active_project:
        lines.append(f"active_project_id: {active_project}")
    if state.get("active_topic"):
        lines.append(f"active_topic: {state['active_topic']}")
    if state.get("last_meaningful_turn_summary"):
        lines.append(f"last_meaningful_turn: {state['last_meaningful_turn_summary']}")
    if state.get("last_assistant_action_summary"):
        lines.append(f"last_assistant_action: {state['last_assistant_action_summary']}")
    if state.get("last_tool_result_summary"):
        lines.append(f"last_tool_result: {state['last_tool_result_summary']}")
    if state.get("last_autonomy_summary"):
        lines.append(f"last_autonomy: {state['last_autonomy_summary']}")
    if state.get("last_memory_update_summary"):
        lines.append(f"last_memory_update: {state['last_memory_update_summary']}")

    unresolved = [str(item) for item in state.get("unresolved_threads", []) if str(item).strip()]
    if unresolved:
        lines.append("unresolved_threads:")
        lines.extend(f"- {compact_text(item, 260)}" for item in unresolved[:4])

    if events:
        lines.append("recent_continuity_events:")
        for event in events[:6]:
            project = f" project={event.project_id}" if event.project_id else ""
            lines.append(f"- {event.created_at} {event.event_type}{project}: {compact_text(event.summary, 260)}")

    episodes = compact_episodic_lines(query=query, project_id=active_project, limit=4)
    if episodes:
        lines.append("recent_or_relevant_episodes:")
        lines.extend(episodes)

    intentions = compact_intention_lines(limit=4)
    if intentions:
        lines.append("pending_questions_or_comments:")
        lines.extend(intentions)

    notes = compact_self_note_lines(query=query, project_id=active_project, limit=3)
    if notes:
        lines.append("active_self_notes:")
        lines.extend(notes)

    memory_updates = compact_recent_memory_lines(limit=3)
    if memory_updates:
        lines.append("recent_memory_updates:")
        lines.extend(memory_updates)

    content = "\n".join(lines)
    if len(content) > max_chars:
        content = content[:max_chars].rstrip() + "\n..."
    return content


def capture_post_chat_episodic_fallback(
    *,
    chat_id: str,
    run_id: str = "",
    latest_user_text: str = "",
    assistant_text: str = "",
    tool_results: list[Any] | None = None,
    project_id: str = "",
) -> MemoryRecord | None:
    event = record_continuity_event(
        "assistant_response_completed",
        post_chat_summary(latest_user_text, assistant_text, tool_results or []),
        source="chat",
        chat_id=chat_id,
        run_id=run_id,
        project_id=project_id,
        topic=infer_topic("\n".join([latest_user_text, assistant_text])),
        metadata={"tool_count": len(tool_results or [])},
    )

    if not meaningful_post_chat(latest_user_text, assistant_text, tool_results or []):
        log_episodic_capture(event.id, "skipped", reason="Turn did not contain enough continuity value.")
        return None

    if durable_memory_write_present(tool_results or []):
        log_episodic_capture(event.id, "promoted_directly", target_layer="durable", reason="A durable memory write already covered this turn.")
        return None

    summary = post_chat_summary(latest_user_text, assistant_text, tool_results or [])
    if duplicate_recent_episode(summary):
        log_episodic_capture(event.id, "skipped", target_layer="episodic", reason="Similar episodic memory already exists.")
        return None

    episode = create_episode(
        title=episode_title(latest_user_text, assistant_text),
        summary=summary,
        type="continuity",
        importance=3,
        conversation_id=chat_id,
        project_id=project_id or None,
        source="post_chat_continuity",
        tags=["continuity", "post_chat"],
        metadata={"run_id": run_id, "source_event_id": event.id},
    )
    log_episodic_capture(event.id, "saved", target_memory_id=episode.id, target_layer="episodic", reason="Meaningful turn had no clearer durable memory capture.")
    return get_memory(episode.id)


def log_episodic_capture(
    source_event_id: int | None,
    decision: str,
    *,
    target_memory_id: str = "",
    target_layer: str = "",
    reason: str = "",
) -> None:
    ensure_continuity_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            insert into episodic_memory_capture_log (source_event_id, decision, target_memory_id, target_layer, reason)
            values (?, ?, ?, ?, ?)
            """,
            (source_event_id, decision, target_memory_id, target_layer, reason),
        )


def recent_continuity_events(chat_id: str = "", limit: int = 8) -> list[ContinuityEvent]:
    ensure_continuity_database()
    clean_limit = max(1, min(50, int(limit)))
    with db_connection(GLOBAL_DB_PATH) as connection:
        if chat_id:
            rows = connection.execute(
                """
                select id, event_type, source, chat_id, run_id, project_id, topic, summary, metadata, created_at
                from continuity_events
                where chat_id = ? or chat_id = ''
                order by id desc
                limit ?
                """,
                (chat_id, clean_limit),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                select id, event_type, source, chat_id, run_id, project_id, topic, summary, metadata, created_at
                from continuity_events
                order by id desc
                limit ?
                """,
                (clean_limit,),
            ).fetchall()
    return [event_from_row(row) for row in rows]


def event_from_row(row: Any) -> ContinuityEvent:
    return ContinuityEvent(
        id=int(row[0]),
        event_type=str(row[1] or ""),
        source=str(row[2] or ""),
        chat_id=str(row[3] or ""),
        run_id=str(row[4] or ""),
        project_id=str(row[5] or ""),
        topic=str(row[6] or ""),
        summary=str(row[7] or ""),
        metadata=safe_json(row[8], {}),
        created_at=str(row[9] or ""),
    )


def compact_episodic_lines(query: str, project_id: str = "", limit: int = 4) -> list[str]:
    context = episodic_memory_context(query=query, limit=limit, include_baseline=True, baseline_limit=2)
    if not context:
        return []
    return [line for line in context.splitlines() if line.startswith("-")][:limit]


def compact_intention_lines(limit: int = 4) -> list[str]:
    try:
        from .autonomy.intentions import list_pending_intentions

        return [f"- {item.kind}: {compact_text(item.content, 220)}" for item in list_pending_intentions(limit=limit)]
    except Exception:
        return []


def compact_self_note_lines(query: str, project_id: str = "", limit: int = 3) -> list[str]:
    try:
        from .self_notes import select_self_notes_for_context

        notes = select_self_notes_for_context(query=query, project_id=project_id, limit=limit, mark_injected=False)
        return [f"- {note.kind} priority={note.priority}: {compact_text(note.text, 220)}" for note in notes]
    except Exception:
        return []


def compact_recent_memory_lines(limit: int = 3) -> list[str]:
    try:
        memories = search_memories(limit=limit)
    except Exception:
        return []
    lines = []
    for memory in memories:
        if memory.layer == MemoryLayer.EPISODIC.value:
            continue
        lines.append(f"- {memory.layer}: {compact_text(memory.title + ': ' + memory.summary, 220)}")
        if len(lines) >= limit:
            break
    return lines


def meaningful_post_chat(latest_user_text: str, assistant_text: str, tool_results: list[Any]) -> bool:
    if tool_results:
        return True
    text = "\n".join([latest_user_text, assistant_text])
    return meaningful_continuity_text(text, {})


def meaningful_continuity_text(text: str, metadata: dict[str, Any] | None = None) -> bool:
    clean = compact_text(text, 4000)
    lowered = clean.lower()
    if len(clean) >= 120:
        return True
    if any(marker in lowered for marker in MEANINGFUL_MARKERS):
        return True
    if metadata and any(key in metadata for key in ("project_id", "activity", "tool", "intention_id", "memory_id")):
        return True
    return False


def unresolved_thread_text(text: str) -> bool:
    lowered = text.lower()
    return "?" in text or any(marker in lowered for marker in ("next", "todo", "to do", "need to", "should", "plan", "unresolved", "current focus"))


def durable_memory_write_present(tool_results: list[Any]) -> bool:
    for result in tool_results:
        tool = str(getattr(result, "tool", "") or "")
        ok = bool(getattr(result, "ok", False))
        if ok and tool in MEMORY_WRITE_TOOLS:
            return True
    return False


def duplicate_recent_episode(summary: str) -> bool:
    terms = " ".join(normalized_terms(summary)[:8])
    if not terms:
        return False
    try:
        memories = search_memories(query=terms, layer=MemoryLayer.EPISODIC, limit=5)
    except Exception:
        return False
    source_terms = set(normalized_terms(summary))
    if len(source_terms) < 5:
        return False
    for memory in memories:
        memory_terms = set(normalized_terms(f"{memory.title} {memory.summary}"))
        if len(source_terms.intersection(memory_terms)) >= min(7, len(source_terms)):
            return True
    return False


def post_chat_summary(latest_user_text: str, assistant_text: str, tool_results: list[Any]) -> str:
    parts = []
    if latest_user_text.strip():
        parts.append("User context/request: " + compact_text(latest_user_text, 420))
    if assistant_text.strip():
        parts.append("Vanta response/action: " + compact_text(assistant_text, 520))
    useful_tools = []
    for result in tool_results[-4:]:
        tool = str(getattr(result, "tool", "") or "tool")
        summary = str(getattr(result, "summary", "") or "").strip()
        if summary:
            useful_tools.append(f"{tool}: {compact_text(summary, 180)}")
    if useful_tools:
        parts.append("Tool results: " + "; ".join(useful_tools))
    return compact_text(" ".join(parts), 1200)


def episode_title(latest_user_text: str, assistant_text: str) -> str:
    topic = infer_topic("\n".join([latest_user_text, assistant_text]))
    if topic:
        return f"Continuity: {topic[:70]}"
    words = compact_text(latest_user_text or assistant_text, 70)
    return f"Continuity: {words}" if words else "Continuity event"


def infer_topic(text: str) -> str:
    clean = compact_text(text, 600)
    lowered = clean.lower()
    if "continuity" in lowered or "memory" in lowered:
        return "memory continuity"
    if "dream" in lowered:
        return "dreaming lifecycle"
    if "autonomy" in lowered or "intention" in lowered or "question" in lowered:
        return "autonomy and intentions"
    project_match = re.search(r"\b(?:project|repo|codebase)\s+([a-zA-Z0-9_-]{3,80})", clean)
    if project_match:
        return project_match.group(1)
    words = [word for word in re.findall(r"[A-Za-z0-9_-]+", clean) if len(word) > 3]
    return " ".join(words[:5])[:120]


def compact_text(text: str, limit: int) -> str:
    clean = " ".join(str(text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[:limit].rstrip() + "..."


def normalized_terms(text: str) -> list[str]:
    stopwords = {"about", "after", "again", "also", "because", "before", "could", "from", "have", "into", "should", "that", "the", "this", "want", "when", "with", "would", "your"}
    return [term for term in re.findall(r"[a-z0-9]+", text.lower()) if len(term) > 2 and term not in stopwords]


def safe_json(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        parsed = json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return fallback
    return parsed
