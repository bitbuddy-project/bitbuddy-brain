from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from .database import db_connection
from .paths import GLOBAL_DB_PATH, ensure_app_dirs
from .utils import log_activity


MAX_LESSONS = 3
MAX_LESSON_TEXT = 360


@dataclass(frozen=True)
class LoopLesson:
    id: int
    provider: str
    model: str
    reason: str
    tool: str
    lesson: str
    evidence_count: int


def ensure_loop_learning_database() -> None:
    ensure_app_dirs()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            create table if not exists loop_incidents (
                id integer primary key autoincrement,
                provider text not null default '',
                model text not null default '',
                mode text not null default '',
                reason text not null default '',
                tools text not null default '[]',
                recovery text not null default '',
                chat_id text not null default '',
                run_id text not null default '',
                metadata text not null default '{}',
                created_at text default current_timestamp
            )
            """
        )
        connection.execute(
            """
            create table if not exists loop_lessons (
                id integer primary key autoincrement,
                provider text not null default '',
                model text not null default '',
                reason text not null default '',
                tool text not null default '',
                lesson text not null,
                evidence_count integer not null default 1,
                updated_at text default current_timestamp,
                unique(provider, model, reason, tool, lesson)
            )
            """
        )
        connection.execute("create index if not exists idx_loop_lessons_lookup on loop_lessons(provider, model, reason, tool, updated_at desc)")


def record_loop_incident(
    *,
    provider: str,
    model: str,
    mode: str,
    reason: str,
    tools: list[str] | tuple[str, ...] = (),
    recovery: str = "",
    chat_id: str = "",
    run_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> None:
    ensure_loop_learning_database()
    clean_tools = [tool for tool in (str(item).strip() for item in tools) if tool]
    clean_reason = clean_label(reason)
    clean_provider = clean_label(provider)
    clean_model = clean_label(model)
    clean_recovery = str(recovery or "").strip()[:160]
    clean_metadata = metadata if isinstance(metadata, dict) else {}
    with sqlite3.connect(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            insert into loop_incidents (provider, model, mode, reason, tools, recovery, chat_id, run_id, metadata)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_provider,
                clean_model,
                clean_label(mode),
                clean_reason,
                json.dumps(clean_tools),
                clean_recovery,
                str(chat_id or "")[:120],
                str(run_id or "")[:120],
                json.dumps(clean_metadata),
            ),
        )

    lesson = lesson_for_incident(clean_reason, clean_tools, clean_recovery)
    if lesson:
        upsert_loop_lesson(provider=clean_provider, model=clean_model, reason=clean_reason, tool=clean_tools[0] if clean_tools else "", lesson=lesson)

    log_activity(
        "loop.incident",
        f"Recovered from model tool loop issue: {clean_reason}",
        {"provider": clean_provider, "model": clean_model, "mode": mode, "tools": clean_tools, "recovery": clean_recovery},
    )


def upsert_loop_lesson(*, provider: str, model: str, reason: str, tool: str, lesson: str) -> None:
    ensure_loop_learning_database()
    clean_lesson = " ".join(str(lesson or "").split())[:MAX_LESSON_TEXT]
    if not clean_lesson:
        return
    params = (clean_label(provider), clean_label(model), clean_label(reason), clean_label(tool), clean_lesson)
    with sqlite3.connect(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            insert into loop_lessons (provider, model, reason, tool, lesson)
            values (?, ?, ?, ?, ?)
            on conflict(provider, model, reason, tool, lesson) do update set
                evidence_count = evidence_count + 1,
                updated_at = current_timestamp
            """,
            params,
        )


def select_loop_lessons(provider: str, model: str, *, reason: str = "", tools: list[str] | tuple[str, ...] = (), limit: int = MAX_LESSONS) -> list[LoopLesson]:
    ensure_loop_learning_database()
    clean_provider = clean_label(provider)
    clean_model = clean_label(model)
    clean_reason = clean_label(reason)
    clean_tools = {clean_label(tool) for tool in tools if clean_label(tool)}
    with sqlite3.connect(GLOBAL_DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            select id, provider, model, reason, tool, lesson, evidence_count
            from loop_lessons
            where provider in ('', ?) and model in ('', ?)
            order by evidence_count desc, updated_at desc, id desc
            limit 12
            """,
            (clean_provider, clean_model),
        ).fetchall()

    lessons: list[LoopLesson] = []
    for row in rows:
        row_reason = str(row["reason"] or "")
        row_tool = str(row["tool"] or "")
        if clean_reason and row_reason and row_reason != clean_reason:
            continue
        if clean_tools and row_tool and row_tool not in clean_tools:
            continue
        lessons.append(
            LoopLesson(
                id=int(row["id"]),
                provider=str(row["provider"] or ""),
                model=str(row["model"] or ""),
                reason=row_reason,
                tool=row_tool,
                lesson=str(row["lesson"] or ""),
                evidence_count=int(row["evidence_count"] or 1),
            )
        )
        if len(lessons) >= max(1, limit):
            break
    return lessons


def loop_lessons_prompt(provider: str, model: str) -> str:
    lessons = select_loop_lessons(provider, model, limit=MAX_LESSONS)
    if not lessons:
        return ""
    lines = [
        "[BitBuddy Loop Lessons]",
        "Private runtime lessons from previous tool-loop recoveries. Use only to avoid repeating known tool-use mistakes; current user request wins.",
    ]
    for lesson in lessons:
        scope = "/".join(part for part in (lesson.reason, lesson.tool) if part)
        prefix = f"- {scope}: " if scope else "- "
        lines.append(prefix + lesson.lesson)
    return "\n".join(lines)


def lesson_for_incident(reason: str, tools: list[str], recovery: str) -> str:
    tool = tools[0] if tools else "the same tool"
    if reason == "duplicate_tool_call":
        return f"If `{tool}` was already called with the same arguments, use the existing result or choose a different next step instead of repeating it."
    if reason == "malformed_tool_call":
        return "When using tools, emit exactly valid tool-call JSON in the supported format; otherwise answer normally from available context."
    if reason == "unsupported_tool_syntax":
        return "Avoid XML/function-call/prose tool syntax. Use the supported tool-call format or answer without tools."
    if reason == "missing_required_args":
        return f"Before calling `{tool}`, include every required argument with a non-empty value; ask a concise clarification if required inputs are unknown."
    if reason == "tool_round_limit":
        return "When tool work reaches the round limit, stop calling tools and synthesize from completed results."
    if reason == "post_result_nonsense":
        return "After a useful tool result, synthesize a normal answer from that result instead of emitting more tool-like or unrelated text."
    if recovery:
        return f"If a tool loop stalls, recover by {recovery}."
    return ""


def clean_label(value: object) -> str:
    return " ".join(str(value or "").strip().split())[:120]
