from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
import json
import re

from ..database import db_connection
from ..paths import GLOBAL_DB_PATH, ensure_app_dirs


@dataclass(frozen=True)
class ChatSummary:
    id: str
    title: str
    mode: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str
    created_at: str = ""


def ensure_chat_database() -> None:
    ensure_app_dirs()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            create table if not exists chats (
                id text primary key,
                title text not null,
                mode text not null,
                created_at text default current_timestamp,
                updated_at text default current_timestamp
            )
            """
        )
        connection.execute(
            """
            create table if not exists chat_messages (
                id integer primary key autoincrement,
                chat_id text not null,
                role text not null,
                content text not null,
                thinking_content text not null default '',
                created_at text default current_timestamp,
                foreign key(chat_id) references chats(id)
            )
            """
        )
        connection.execute(
            """
            create table if not exists chat_capsules (
                id integer primary key autoincrement,
                source_chat_id text not null unique,
                title text not null,
                mode text not null,
                chat_created_at text not null,
                chat_updated_at text not null,
                message_count integer not null default 0,
                summary text not null,
                metadata text not null default '{}',
                capsule_created_at text default current_timestamp
            )
            """
        )
        ensure_column(connection, "chat_messages", "thinking_content", "text not null default ''")
        ensure_column(connection, "chat_messages", "kind", "text not null default 'message'")
        ensure_column(connection, "chat_messages", "status", "text not null default ''")
        ensure_column(connection, "chat_messages", "metadata", "text not null default '{}'")
        ensure_column(connection, "chat_messages", "sequence", "integer not null default 0")
        ensure_column(connection, "chat_messages", "parent_message_id", "integer")
        ensure_column(connection, "chat_messages", "mode", "text not null default ''")
        connection.execute("update chat_messages set kind = 'message' where kind = ''")
        connection.execute("update chat_messages set metadata = '{}' where metadata = ''")
        connection.execute("update chat_messages set sequence = id * 1000 where sequence = 0")


def create_chat(title: str, mode: str) -> ChatSummary:
    ensure_chat_database()
    chat_id = str(uuid.uuid4())
    clean_title = title.strip()[:80] or "Untitled chat"
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            "insert into chats (id, title, mode) values (?, ?, ?)",
            (chat_id, clean_title, mode),
        )
    return get_chat_summary(chat_id)


def get_chat_summary(chat_id: str) -> ChatSummary:
    ensure_chat_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute(
            "select id, title, mode, created_at, updated_at from chats where id = ?",
            (chat_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"Unknown chat: {chat_id}")
    return ChatSummary(*row)


def list_recent_chats(limit: int = 20, search: str = "") -> list[ChatSummary]:
    ensure_chat_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        if search.strip():
            rows = connection.execute(
                "select id, title, mode, created_at, updated_at from chats where title like ? order by updated_at desc, created_at desc, rowid desc limit ?",
                (f"%{search.strip()}%", limit),
            ).fetchall()
        else:
            rows = connection.execute(
                "select id, title, mode, created_at, updated_at from chats order by updated_at desc, created_at desc, rowid desc limit ?",
                (limit,),
            ).fetchall()
    return [ChatSummary(*row) for row in rows]


def recent_continuity_context(
    current_chat_id: str = "",
    chat_limit: int = 5,
    messages_per_chat: int = 5,
    max_chars: int = 4000,
) -> str:
    """Build a bounded cross-chat continuity block from recent persisted chats."""
    ensure_chat_database()

    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            """
            select id, title, mode, created_at, updated_at
            from chats
            where id != ?
            order by updated_at desc, created_at desc, rowid desc
            limit ?
            """,
            (current_chat_id, chat_limit),
        ).fetchall()

        sections: list[str] = []
        for row in rows:
            chat = ChatSummary(*row)
            message_rows = connection.execute(
                """
                select role, content, kind, status, metadata
                from chat_messages
                where chat_id = ?
                  and (
                    (kind = 'message' and content != '')
                    or kind = 'tool'
                  )
                order by sequence desc, id desc
                limit ?
                """,
                (chat.id, messages_per_chat),
            ).fetchall()
            entries = [continuity_entry_from_row(message_row) for message_row in reversed(message_rows)]
            entries = [entry for entry in entries if entry]

            if not entries:
                continue

            lines = [f"Conversation: {chat.title} (mode={chat.mode}, updated={chat.updated_at})"]
            lines.extend(f"- {entry}" for entry in entries)
            sections.append("\n".join(lines))

        capsule_rows = connection.execute(
            """
            select title, mode, chat_created_at, chat_updated_at, message_count, summary, metadata, capsule_created_at
            from chat_capsules
            where source_chat_id != ?
            order by capsule_created_at desc, id desc
            limit ?
            """,
            (current_chat_id, chat_limit),
        ).fetchall()

        for row in capsule_rows:
            capsule = continuity_capsule_from_row(row)
            if capsule:
                sections.append(capsule)

    if not sections:
        return ""

    content = "\n\n".join(sections)
    if len(content) > max_chars:
        content = content[:max_chars].rstrip() + "\n..."

    return "\n".join(
        [
            "[BitBuddy Conversation Continuity]",
            "Recent conversation context from persisted chats and deletion-safe chat capsules. Use it to remember where you and the user left off.",
            "Treat this as potentially stale; the current user message always wins.",
            "Do not quote this block verbatim unless the user asks for chat history.",
            "",
            content,
        ]
    )


def continuity_entry_from_row(row: tuple[Any, ...]) -> str:
    role, content, kind, status, metadata = row
    clean_kind = str(kind or "message")

    if clean_kind == "tool":
        data = safe_json_object(str(metadata or "{}"))
        tool = str(data.get("tool") or "tool")
        summary = str(data.get("result_summary") or data.get("error") or content or "").strip()
        return truncate_continuity_text(f"tool {tool} {status}: {summary}", 420)

    clean_role = str(role or "message")
    return truncate_continuity_text(f"{clean_role}: {str(content or '').strip()}", 520)


def continuity_capsule_from_row(row: tuple[Any, ...]) -> str:
    title, mode, chat_created_at, chat_updated_at, message_count, summary, metadata, capsule_created_at = row
    clean_summary = str(summary or "").strip()
    if not clean_summary:
        return ""

    data = safe_json_object(str(metadata or "{}"))
    final_user_message = str(data.get("final_user_message") or "").strip()
    tool_names = data.get("tool_names") if isinstance(data.get("tool_names"), list) else []
    tool_text = ", ".join(str(tool) for tool in tool_names[:5] if tool)

    lines = [
        f"Deleted conversation capsule: {title} (mode={mode}, messages={message_count}, updated={chat_updated_at}, preserved={capsule_created_at})",
        truncate_continuity_text(clean_summary, 1800),
    ]
    if final_user_message:
        lines.append("Last user thread: " + truncate_continuity_text(final_user_message, 360))
    if tool_text:
        lines.append("Tools used: " + tool_text)

    return "\n".join(lines)


def truncate_continuity_text(text: str, limit: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[:limit].rstrip() + "..."


def get_chat(chat_id: str) -> dict[str, object]:
    summary = get_chat_summary(chat_id)
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            """
            select id, role, content, thinking_content, created_at, kind, status, metadata, sequence, parent_message_id, mode
            from chat_messages
            where chat_id = ?
            order by sequence asc, id asc
            """,
            (chat_id,),
        ).fetchall()
    return {
        "id": summary.id,
        "title": summary.title,
        "mode": summary.mode,
        "created_at": summary.created_at,
        "updated_at": summary.updated_at,
        "messages": [chat_message_to_json(row) for row in rows],
    }


def recent_chat_window(chat_id: str, limit: int = 30) -> dict[str, object]:
    """Return a bounded, consolidation-safe chat window and staleness token."""
    ensure_chat_database()
    clean_limit = max(1, min(200, int(limit)))
    with db_connection(GLOBAL_DB_PATH) as connection:
        chat = connection.execute("select updated_at from chats where id = ?", (chat_id,)).fetchone()
        if chat is None:
            raise ValueError(f"Unknown chat: {chat_id}")
        rows = connection.execute(
            """
            select id, role, content, kind, status, metadata, sequence, created_at
            from chat_messages
            where chat_id = ?
              and (
                (kind = 'message' and content != '')
                or kind = 'tool'
              )
            order by sequence desc, id desc
            limit ?
            """,
            (chat_id, clean_limit),
        ).fetchall()
        max_row = connection.execute(
            "select coalesce(max(chat_messages.id), 0), coalesce(max(chat_messages.sequence), 0), chats.updated_at from chat_messages join chats on chats.id = chat_messages.chat_id where chat_messages.chat_id = ?",
            (chat_id,),
        ).fetchone()

    messages = [consolidation_message_from_row(row) for row in reversed(rows)]
    messages = [message for message in messages if message]
    return {
        "chat_id": chat_id,
        "messages": messages,
        "token": {
            "max_message_id": int(max_row[0] or 0) if max_row else 0,
            "max_sequence": int(max_row[1] or 0) if max_row else 0,
            "chat_updated_at": str(max_row[2] or chat[0]),
        },
    }


def chat_window_token(chat_id: str) -> dict[str, object]:
    ensure_chat_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute(
            """
            select coalesce(max(chat_messages.id), 0), coalesce(max(chat_messages.sequence), 0), chats.updated_at
            from chats
            left join chat_messages on chats.id = chat_messages.chat_id
            where chats.id = ?
            group by chats.id
            """,
            (chat_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"Unknown chat: {chat_id}")
    return {"max_message_id": int(row[0] or 0), "max_sequence": int(row[1] or 0), "chat_updated_at": str(row[2] or "")}


def chat_activity_token() -> dict[str, object]:
    """Return a global token that changes when any chat activity is recorded."""
    ensure_chat_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute(
            """
            select
                (select count(*) from chats),
                (select count(*) from chat_messages),
                (select coalesce(max(id), 0) from chat_messages),
                (select coalesce(max(sequence), 0) from chat_messages),
                (select coalesce(max(updated_at), '') from chats)
            """
        ).fetchone()
    return {
        "scope": "global_chat_activity",
        "chat_count": int(row[0] or 0) if row else 0,
        "message_count": int(row[1] or 0) if row else 0,
        "max_message_id": int(row[2] or 0) if row else 0,
        "max_sequence": int(row[3] or 0) if row else 0,
        "latest_chat_updated_at": str(row[4] or "") if row else "",
    }


def consolidation_message_from_row(row: tuple[Any, ...]) -> dict[str, object] | None:
    message_id, role, content, kind, status, metadata, sequence, created_at = row
    clean_kind = str(kind or "message")
    if clean_kind == "tool":
        data = safe_json_object(str(metadata or "{}"))
        tool = str(data.get("tool") or "tool")
        summary = str(data.get("result_summary") or data.get("error") or content or "").strip()
        if not summary:
            return None
        return {
            "id": message_id,
            "role": "tool",
            "kind": "tool",
            "tool": tool,
            "status": status,
            "content": truncate_continuity_text(summary, 700),
            "sequence": sequence,
            "created_at": created_at,
        }
    if role not in {"user", "assistant"} or not str(content or "").strip():
        return None
    return {
        "id": message_id,
        "role": role,
        "kind": "message",
        "content": truncate_continuity_text(str(content or ""), 1600),
        "sequence": sequence,
        "created_at": created_at,
    }


def delete_chat(chat_id: str) -> bool:
    ensure_chat_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        existing = connection.execute("select id, title, mode, created_at, updated_at from chats where id = ?", (chat_id,)).fetchone()
        if existing is None:
            return False
        preserve_chat_capsule(connection, existing)
        connection.execute("delete from chat_messages where chat_id = ?", (chat_id,))
        connection.execute("delete from chats where id = ?", (chat_id,))
    return True


def delete_chat_message_turn(chat_id: str, message_id: int) -> dict[str, object]:
    ensure_chat_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute(
            "select sequence, role, kind from chat_messages where chat_id = ? and id = ?",
            (chat_id, message_id),
        ).fetchone()
        if row is None:
            raise ValueError("Unknown chat message.")
        sequence, role, kind = row
        if role != "user" or (kind or "message") != "message":
            raise ValueError("Only user messages can be deleted this way.")

        next_user = connection.execute(
            """
            select min(sequence)
            from chat_messages
            where chat_id = ? and role = 'user' and kind = 'message' and sequence > ?
            """,
            (chat_id, sequence),
        ).fetchone()
        next_sequence_value = int(next_user[0]) if next_user and next_user[0] is not None else None
        if next_sequence_value is None:
            cursor = connection.execute(
                "delete from chat_messages where chat_id = ? and sequence >= ?",
                (chat_id, sequence),
            )
        else:
            cursor = connection.execute(
                "delete from chat_messages where chat_id = ? and sequence >= ? and sequence < ?",
                (chat_id, sequence, next_sequence_value),
            )
        connection.execute("update chats set updated_at = current_timestamp where id = ?", (chat_id,))
        deleted = int(cursor.rowcount if cursor.rowcount is not None else 0)
    return {"deleted": deleted, "chat": get_chat(chat_id)}


def trim_chat_from_message(chat_id: str, message_id: int) -> dict[str, object]:
    ensure_chat_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute(
            "select sequence, role, kind from chat_messages where chat_id = ? and id = ?",
            (chat_id, message_id),
        ).fetchone()
        if row is None:
            raise ValueError("Unknown chat message.")
        sequence, role, kind = row
        if role != "user" or (kind or "message") != "message":
            raise ValueError("Only user messages can be edited this way.")

        cursor = connection.execute(
            "delete from chat_messages where chat_id = ? and sequence >= ?",
            (chat_id, sequence),
        )
        connection.execute("update chats set updated_at = current_timestamp where id = ?", (chat_id,))
        deleted = int(cursor.rowcount if cursor.rowcount is not None else 0)
    return {"deleted": deleted, "chat": get_chat(chat_id)}


def preserve_chat_capsule(connection: sqlite3.Connection, chat_row: tuple[Any, ...]) -> None:
    chat_id, title, mode, created_at, updated_at = chat_row
    rows = connection.execute(
        """
        select role, content, thinking_content, kind, status, metadata, sequence, created_at
        from chat_messages
        where chat_id = ?
        order by sequence asc, id asc
        """,
        (chat_id,),
    ).fetchall()
    if not rows:
        return

    summary, metadata = build_chat_capsule(str(title), str(mode), str(created_at or ""), str(updated_at or ""), rows)
    if not summary:
        return

    connection.execute("delete from chat_capsules where source_chat_id = ?", (chat_id,))
    connection.execute(
        """
        insert into chat_capsules (source_chat_id, title, mode, chat_created_at, chat_updated_at, message_count, summary, metadata)
        values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (chat_id, str(title), str(mode), str(created_at or ""), str(updated_at or ""), len(rows), summary, json.dumps(metadata)),
    )


def build_chat_capsule(title: str, mode: str, created_at: str, updated_at: str, rows: list[tuple[Any, ...]]) -> tuple[str, dict[str, object]]:
    entries: list[str] = []
    user_messages: list[str] = []
    assistant_messages: list[str] = []
    tool_names: list[str] = []

    for row in rows:
        role, content, thinking_content, kind, status, metadata, sequence, message_created_at = row
        clean_kind = str(kind or "message")
        clean_content = str(content or "").strip()
        if clean_kind == "tool":
            data = safe_json_object(str(metadata or "{}"))
            tool = str(data.get("tool") or "tool")
            if tool not in tool_names:
                tool_names.append(tool)
            summary = str(data.get("result_summary") or data.get("error") or clean_content or "").strip()
            if summary:
                entries.append(truncate_continuity_text(f"tool {tool} {status}: {summary}", 520))
            continue

        if str(role) == "user" and clean_content:
            user_messages.append(clean_content)
            entries.append(truncate_continuity_text(f"user: {clean_content}", 620))
        elif str(role) == "assistant" and clean_content:
            assistant_messages.append(clean_content)
            entries.append(truncate_continuity_text(f"assistant: {clean_content}", 520))

    if not entries:
        return "", {}

    recent_entries = entries[-12:]
    open_threads = [truncate_continuity_text(message, 360) for message in user_messages[-3:]]
    metadata: dict[str, object] = {
        "user_message_count": len(user_messages),
        "assistant_message_count": len(assistant_messages),
        "tool_names": tool_names,
        "final_user_message": user_messages[-1] if user_messages else "",
        "created_at": created_at,
        "updated_at": updated_at,
    }

    lines = [
        f"Conversation capsule for '{title}' in {mode} mode.",
        f"Preserved after deletion with {len(rows)} timeline item(s).",
    ]
    if open_threads:
        lines.append("Open/recent user threads:")
        lines.extend(f"- {thread}" for thread in open_threads)
    lines.append("Recent timeline highlights:")
    lines.extend(f"- {entry}" for entry in recent_entries)

    return truncate_continuity_text("\n".join(lines), 4000), metadata


def replace_chat_messages(chat_id: str, messages: list[dict[str, str]], mode: str) -> None:
    ensure_chat_database()
    clean_messages = []
    for index, message in enumerate(messages):
        kind = message.get("kind", "message") or "message"
        if kind != "message":
            continue

        role = message.get("role", "")
        content = message.get("content", "").strip()
        thinking_content = message.get("thinking", "").strip()
        if role == "assistant":
            content = strip_system_reminders(content)
            thinking_content = strip_system_reminders(thinking_content)
        sequence = int_value(message.get("sequence"), (index + 1) * 1000)
        msg_mode = message.get("mode", "") or mode

        metadata = {}
        attachments = normalized_message_attachments(message)
        if attachments:
            metadata["attachments"] = attachments

        if role == "user" and (content or attachments):
            clean_messages.append((role, content, thinking_content, sequence, msg_mode, json.dumps(metadata)))
        elif role == "assistant" and (content or thinking_content):
            clean_messages.append((role, content, thinking_content, sequence, msg_mode, json.dumps(metadata)))

    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute("delete from chat_messages where chat_id = ? and kind = 'message'", (chat_id,))
        connection.executemany(
            """
            insert into chat_messages (chat_id, role, content, thinking_content, kind, status, metadata, sequence, mode)
            values (?, ?, ?, ?, 'message', '', ?, ?, ?)
            """,
            [
                (chat_id, role, content, thinking_content, metadata, sequence, msg_mode)
                for role, content, thinking_content, sequence, msg_mode, metadata in clean_messages
            ],
        )
        connection.execute(
            "update chats set mode = ?, updated_at = current_timestamp where id = ?",
            (mode, chat_id),
        )


def append_chat_message(chat_id: str, role: str, content: str, thinking_content: str = "", mode: str = "", metadata: dict[str, object] | None = None) -> None:
    clean_content = content.strip()
    clean_thinking = thinking_content.strip()
    if role == "assistant":
        clean_content = strip_system_reminders(clean_content)
        clean_thinking = strip_system_reminders(clean_thinking)

    if role == "user" and not clean_content:
        return
    if role == "assistant" and not clean_content and not clean_thinking:
        return

    ensure_chat_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        sequence = next_sequence(connection, chat_id)
        connection.execute(
            """
            insert into chat_messages (chat_id, role, content, thinking_content, kind, status, metadata, sequence, mode)
            values (?, ?, ?, ?, 'message', '', ?, ?, ?)
            """,
            (chat_id, role, clean_content, clean_thinking, json.dumps(metadata or {}), sequence, mode),
        )
        connection.execute(
            "update chats set updated_at = current_timestamp where id = ?",
            (chat_id,),
        )


def create_assistant_message(chat_id: str, sequence: int | None = None, mode: str = "") -> int:
    ensure_chat_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        message_sequence = sequence if sequence is not None else next_sequence(connection, chat_id)
        cursor = connection.execute(
            """
            insert into chat_messages (chat_id, role, content, thinking_content, kind, status, metadata, sequence, mode)
            values (?, 'assistant', '', '', 'message', '', '{}', ?, ?)
            """,
            (chat_id, message_sequence, mode),
        )
        connection.execute(
            "update chats set updated_at = current_timestamp where id = ?",
            (chat_id,),
        )
        return int(cursor.lastrowid)


def create_tool_event(
    chat_id: str,
    tool: str,
    arguments_summary: dict[str, object],
    summary: str,
    sequence: int | None = None,
    parent_message_id: int | None = None,
    mode: str = "",
) -> dict[str, object]:
    ensure_chat_database()
    metadata = {
        "tool": tool,
        "arguments_summary": arguments_summary,
        "result_summary": "",
        "error": "",
        "truncated": False,
        "raw_result_visible": False,
    }
    with db_connection(GLOBAL_DB_PATH) as connection:
        event_sequence = sequence if sequence is not None else next_sequence(connection, chat_id)
        cursor = connection.execute(
            """
            insert into chat_messages (chat_id, role, content, thinking_content, kind, status, metadata, sequence, parent_message_id, mode)
            values (?, 'tool', ?, '', 'tool', 'running', ?, ?, ?, ?)
            """,
            (chat_id, summary.strip()[:500], json.dumps(metadata), event_sequence, parent_message_id, mode),
        )
        event_id = int(cursor.lastrowid)
        connection.execute("update chats set updated_at = current_timestamp where id = ?", (chat_id,))
        row = connection.execute(
            """
            select id, role, content, thinking_content, created_at, kind, status, metadata, sequence, parent_message_id, mode
            from chat_messages
            where id = ?
            """,
            (event_id,),
        ).fetchone()
    return chat_message_to_json(row)


def update_tool_event(
    event_id: int,
    status: str,
    summary: str,
    metadata_patch: dict[str, object] | None = None,
) -> dict[str, object]:
    ensure_chat_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        current = connection.execute("select metadata from chat_messages where id = ? and kind = 'tool'", (event_id,)).fetchone()
        metadata = safe_json_object(current[0] if current else "{}")
        metadata.update(metadata_patch or {})
        connection.execute(
            """
            update chat_messages
            set status = ?, content = ?, metadata = ?
            where id = ? and kind = 'tool'
            """,
            (status, summary.strip()[:500], json.dumps(metadata), event_id),
        )
        connection.execute(
            """
            update chats
            set updated_at = current_timestamp
            where id = (
                select chat_id
                from chat_messages
                where id = ?
            )
            """,
            (event_id,),
        )
        row = connection.execute(
            """
            select id, role, content, thinking_content, created_at, kind, status, metadata, sequence, parent_message_id, mode
            from chat_messages
            where id = ?
            """,
            (event_id,),
        ).fetchone()
    return chat_message_to_json(row)


def update_assistant_message(message_id: int, content: str, thinking_content: str = "") -> None:
    clean_content = strip_system_reminders(content.strip())
    clean_thinking = strip_system_reminders(thinking_content.strip())
    ensure_chat_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            update chat_messages
            set content = ?, thinking_content = ?
            where id = ? and role = 'assistant'
            """,
            (clean_content, clean_thinking, message_id),
        )
        connection.execute(
            """
            update chats
            set updated_at = current_timestamp
            where id = (
                select chat_id
                from chat_messages
                where id = ?
            )
            """,
            (message_id,),
        )


def chat_summary_to_json(chat: ChatSummary) -> dict[str, str]:
    return {
        "id": chat.id,
        "title": chat.title,
        "mode": chat.mode,
        "created_at": chat.created_at,
        "updated_at": chat.updated_at,
    }


def chat_message_to_json(row: tuple[Any, ...]) -> dict[str, object]:
    message_id, role, content, thinking_content, created_at, kind, status, metadata, sequence, parent_message_id, mode = row
    clean_kind = kind or "message"
    metadata_object = safe_json_object(metadata)
    clean_content = str(content or "")
    clean_thinking = str(thinking_content or "")
    if role == "assistant":
        clean_content = strip_system_reminders(clean_content)
        clean_thinking = strip_system_reminders(clean_thinking)
    return {
        "id": message_id,
        "kind": clean_kind,
        "role": role,
        "content": clean_content,
        "thinking": clean_thinking,
        "status": status or "",
        "metadata": metadata_object,
        "attachments": metadata_object.get("attachments", []) if isinstance(metadata_object.get("attachments"), list) else [],
        "sequence": sequence,
        "parent_message_id": parent_message_id,
        "mode": mode or "",
        "created_at": created_at,
    }


def strip_system_reminders(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"(?is)<system-reminder\b[^>]*>.*?(?:</system-reminder>|$)", "", text).strip()


def normalized_message_attachments(message: dict[str, Any]) -> list[dict[str, object]]:
    raw = message.get("attachments")
    if not isinstance(raw, list):
        return []

    result: list[dict[str, object]] = []
    for attachment in raw:
        if not isinstance(attachment, dict):
            continue
        name = str(attachment.get("name") or "uploaded file")[:240]
        kind = str(attachment.get("kind") or "file")
        if kind not in {"image", "text", "file"}:
            kind = "file"
        clean: dict[str, object] = {
            "id": str(attachment.get("id") or "")[:80],
            "name": name,
            "mime_type": str(attachment.get("mime_type") or "application/octet-stream")[:120],
            "size": int_value(attachment.get("size"), 0),
            "kind": kind,
        }
        if kind == "image" and isinstance(attachment.get("data"), str):
            clean["data"] = str(attachment.get("data"))
        if kind == "text" and isinstance(attachment.get("text"), str):
            clean["text"] = str(attachment.get("text"))
        result.append(clean)
    return result[:8]


def safe_json_object(value: str) -> dict[str, object]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def int_value(value: object, fallback: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def next_sequence(connection: sqlite3.Connection, chat_id: str) -> int:
    row = connection.execute("select coalesce(max(sequence), 0) from chat_messages where chat_id = ?", (chat_id,)).fetchone()
    return int(row[0] or 0) + 1000


def ensure_column(connection: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in connection.execute(f"pragma table_info({table})")}
    if column not in columns:
        connection.execute(f"alter table {table} add column {column} {definition}")
