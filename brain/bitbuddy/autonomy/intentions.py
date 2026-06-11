from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import load_config
from ..database import db_connection
from ..paths import GLOBAL_DB_PATH, ensure_app_dirs


ACTIVE_STATUSES = {"pending", "queued", "eligible"}
FINAL_STATUSES = {"shown", "answered", "resolved_indirectly", "stale", "dismissed", "expired", "used"}
SURFACE_COOLDOWN_MINUTES = 45


@dataclass(frozen=True)
class Intention:
    id: int
    kind: str
    content: str
    reason: str
    source: str
    source_cycle_id: str | None
    status: str
    created_at: str
    used_at: str | None
    eligible_at: str | None
    shown_at: str | None
    answered_at: str | None
    resolved_at: str | None
    expires_at: str | None
    updated_at: str | None
    metadata: dict[str, Any]


def ensure_intentions_database() -> None:
    ensure_app_dirs()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            create table if not exists intentions (
                id integer primary key autoincrement,
                kind text not null,
                content text not null,
                reason text not null default '',
                source text not null default 'autonomy',
                source_cycle_id text,
                status text not null default 'queued',
                metadata text not null default '{}',
                created_at text default current_timestamp,
                used_at text
            )
            """
        )
        for column, definition in (
            ("eligible_at", "text"),
            ("shown_at", "text"),
            ("answered_at", "text"),
            ("resolved_at", "text"),
            ("expires_at", "text"),
            ("updated_at", "text"),
        ):
            ensure_column(connection, "intentions", column, definition)
        connection.execute("update intentions set status = 'queued' where status = 'pending'")
        connection.execute("update intentions set updated_at = coalesce(updated_at, created_at)")
        connection.execute("create index if not exists idx_intentions_status on intentions(status, kind, created_at desc)")
        connection.execute(
            """
            create table if not exists intention_surfaces (
                id integer primary key autoincrement,
                chat_id text not null,
                intention_id integer not null,
                run_id text not null default '',
                surfaced_at text default current_timestamp,
                metadata text not null default '{}'
            )
            """
        )
        connection.execute("create index if not exists idx_intention_surfaces_chat on intention_surfaces(chat_id, surfaced_at desc)")


def create_intention(
    kind: str,
    content: str,
    reason: str = "",
    source_cycle_id: str | None = None,
    source: str = "autonomy",
    metadata: dict[str, Any] | None = None,
) -> Intention:
    clean_kind = kind.strip() or "comment"
    clean_content = content.strip()
    if clean_kind not in {"question", "comment", "suggestion", "curiosity", "follow_up"}:
        clean_kind = "comment"
    if not clean_content:
        raise ValueError("content is required.")

    ensure_intentions_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        existing = find_similar_pending_intention(connection, clean_kind, clean_content)
        if existing is not None:
            metadata_patch = {**existing.metadata, **(metadata or {}), "deduped": True}
            connection.execute(
                """
                update intentions
                set reason = case when reason = '' then ? else reason end,
                    source_cycle_id = coalesce(source_cycle_id, ?),
                    metadata = ?,
                    updated_at = current_timestamp
                where id = ?
                """,
                (reason.strip(), source_cycle_id, json.dumps(metadata_patch), existing.id),
            )
            row = connection.execute(
                """
                select id, kind, content, reason, source, source_cycle_id, status, created_at, used_at, metadata,
                       eligible_at, shown_at, answered_at, resolved_at, expires_at, updated_at
                from intentions where id = ?
                """,
                (existing.id,),
            ).fetchone()
            intention = intention_from_row(row)
            record_intention_continuity(intention, deduped=True)
            return intention

        if intention_queue_is_full(connection, clean_kind):
            raise ValueError(f"Intention queue is full for {clean_kind}.")

        cursor = connection.execute(
            """
            insert into intentions (kind, content, reason, source, source_cycle_id, status, metadata, updated_at)
            values (?, ?, ?, ?, ?, 'queued', ?, current_timestamp)
            """,
            (clean_kind, clean_content, reason.strip(), source, source_cycle_id, json.dumps(metadata or {})),
        )
        row = connection.execute(
            """
            select id, kind, content, reason, source, source_cycle_id, status, created_at, used_at, metadata,
                   eligible_at, shown_at, answered_at, resolved_at, expires_at, updated_at
            from intentions where id = ?
            """,
            (int(cursor.lastrowid),),
        ).fetchone()
    intention = intention_from_row(row)
    record_intention_continuity(intention)
    return intention


def record_intention_continuity(intention: Intention, deduped: bool = False) -> None:
    try:
        from ..continuity import record_continuity_event

        project_id = str(intention.metadata.get("project_id") or "") if isinstance(intention.metadata, dict) else ""
        record_continuity_event(
            "intention_created",
            f"Queued {intention.kind}: {intention.content}",
            source=intention.source or "autonomy",
            run_id=intention.source_cycle_id or "",
            project_id=project_id,
            topic=project_id,
            metadata={"intention_id": intention.id, "kind": intention.kind, "deduped": deduped},
        )
    except Exception:
        return


def find_similar_pending_intention(connection: Any, kind: str, content: str) -> Intention | None:
    normalized = normalize_intention_content(content)
    rows = connection.execute(
        """
        select id, kind, content, reason, source, source_cycle_id, status, created_at, used_at, metadata,
               eligible_at, shown_at, answered_at, resolved_at, expires_at, updated_at
        from intentions
        where status in ('pending', 'queued', 'eligible')
        order by id desc
        limit 100
        """
    ).fetchall()
    for row in rows:
        intention = intention_from_row(row)
        if intention.kind != kind:
            continue
        existing_normalized = normalize_intention_content(intention.content)
        if existing_normalized == normalized:
            return intention
        shorter, longer = sorted((existing_normalized, normalized), key=len)
        if len(shorter) >= 40 and shorter in longer:
            return intention
    return None


def normalize_intention_content(content: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", content.lower()))


def list_pending_intentions(limit: int = 20) -> list[Intention]:
    ensure_intentions_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            """
            select id, kind, content, reason, source, source_cycle_id, status, created_at, used_at, metadata,
                   eligible_at, shown_at, answered_at, resolved_at, expires_at, updated_at
            from intentions
            where status in ('pending', 'queued', 'eligible')
            order by id desc
            limit ?
            """,
            (max(1, min(100, int(limit))),),
        ).fetchall()
    return [intention_from_row(row) for row in rows]


def mark_intention_used(intention_id: int) -> bool:
    return mark_intention_shown(intention_id)


def mark_intention_shown(intention_id: int) -> bool:
    return update_intention_status(intention_id, "shown")


def dismiss_intention(intention_id: int) -> bool:
    return update_intention_status(intention_id, "dismissed")


def update_intention_status(intention_id: int, status: str) -> bool:
    if status not in FINAL_STATUSES | {"queued", "eligible"}:
        raise ValueError("Unsupported intention status.")
    ensure_intentions_database()
    timestamp_column = "shown_at" if status in {"shown", "used"} else "resolved_at" if status in {"resolved_indirectly", "stale", "dismissed", "expired"} else "updated_at"
    with db_connection(GLOBAL_DB_PATH) as connection:
        cursor = connection.execute(
            f"""
            update intentions
            set status = ?, used_at = current_timestamp, {timestamp_column} = current_timestamp, updated_at = current_timestamp
            where id = ? and status in ('pending', 'queued', 'eligible')
            """,
            ("shown" if status == "used" else status, int(intention_id)),
        )
        return cursor.rowcount > 0


def intention_queue_is_full(connection: Any, kind: str) -> bool:
    config = load_config()
    if kind == "question":
        limit = config.autonomy.max_pending_questions
        kinds = ("question",)
    elif kind in {"comment", "suggestion", "curiosity", "follow_up"}:
        limit = config.autonomy.max_pending_comments
        kinds = ("comment", "suggestion", "curiosity", "follow_up")
    else:
        return False
    placeholders = ",".join("?" for _ in kinds)
    row = connection.execute(
        f"select count(*) from intentions where status in ('pending', 'queued', 'eligible') and kind in ({placeholders})",
        kinds,
    ).fetchone()
    return int(row[0] or 0) >= limit


def cleanup_intention_queue(now: datetime | None = None) -> dict[str, Any]:
    ensure_intentions_database()
    config = load_config()
    current = now or datetime.now(timezone.utc)
    expired_ids: list[int] = []
    stale_ids: list[int] = []
    duplicate_ids: list[int] = []
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            """
            select id, kind, content, reason, source, source_cycle_id, status, created_at, used_at, metadata,
                   eligible_at, shown_at, answered_at, resolved_at, expires_at, updated_at
            from intentions
            where status in ('pending', 'queued', 'eligible')
            order by id asc
            """
        ).fetchall()
        seen: set[tuple[str, str]] = set()
        for row in rows:
            intention = intention_from_row(row)
            signature = (intention.kind, normalize_intention_content(intention.content))
            if signature in seen:
                duplicate_ids.append(intention.id)
                continue
            seen.add(signature)

            expires_at = parse_timestamp(intention.expires_at)
            if expires_at is not None and expires_at <= current:
                expired_ids.append(intention.id)
                continue

            created_at = parse_timestamp(intention.created_at)
            if created_at is None:
                continue
            age = current - created_at
            priority = int_value(intention.metadata.get("priority"), 3)
            if priority <= 1 and age >= timedelta(days=config.dreaming.low_priority_stale_intention_days):
                stale_ids.append(intention.id)
            elif age >= timedelta(days=config.dreaming.stale_intention_days) and priority <= 2:
                stale_ids.append(intention.id)

        mark_ids(connection, duplicate_ids, "stale")
        mark_ids(connection, expired_ids, "expired")
        mark_ids(connection, stale_ids, "stale")
    return {"duplicates_staled": duplicate_ids, "expired": expired_ids, "stale": stale_ids}


def next_eligible_intention(
    chat_id: str,
    latest_user_text: str = "",
    active_project_id: str = "",
    *,
    response_text: str = "",
    mode: str = "chat",
    quiet_mode: bool = False,
    now: datetime | None = None,
    cooldown_minutes: int = SURFACE_COOLDOWN_MINUTES,
) -> Intention | None:
    ensure_intentions_database()
    current = now or datetime.now(timezone.utc)
    if chat_id and recent_intention_surface_for_chat(chat_id, now=current, cooldown_minutes=cooldown_minutes):
        return None

    query_text = f"{latest_user_text}\n{response_text}".strip()
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            """
            select id, kind, content, reason, source, source_cycle_id, status, created_at, used_at, metadata,
                   eligible_at, shown_at, answered_at, resolved_at, expires_at, updated_at
            from intentions
            where status in ('queued', 'eligible')
            """
        ).fetchall()
    candidates = [intention_from_row(row) for row in rows]
    ranked: list[tuple[tuple[int, int, datetime, datetime, int], Intention]] = []
    for intention in candidates:
        if intention_is_expired(intention, current):
            continue
        if not intention_quality_allows_surface(intention):
            continue
        priority = intention_priority(intention)
        relevance = intention_relevance(intention, query_text, active_project_id)
        if relevance <= 0 and priority < 4:
            continue
        if quiet_mode and priority < 4:
            continue
        if mode == "debug" and relevance <= 0 and priority < 5:
            continue
        eligible_at = parse_timestamp(intention.eligible_at) or parse_timestamp(intention.created_at) or current
        created_at = parse_timestamp(intention.created_at) or current
        ranked.append(((-relevance, -priority, eligible_at, created_at, intention.id), intention))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1]


def intention_quality_allows_surface(intention: Intention) -> bool:
    """Respect quality metadata for newly generated intentions while preserving old rows.

    An item that passed creation-time quality (``intention_quality``) is deliverable here:
    re-imposing an importance>=4 bar dead-letters everything queued at importance 3 (the
    common case), which is why questions stopped reaching the user. Throttling lives where
    it belongs instead — ``effective_min_autonomous_priority`` + cooldowns for autonomous
    delivery, and the relevance/priority/quiet-mode gates in ``next_eligible_intention`` for
    in-chat surfacing.
    """
    quality = intention.metadata.get("quality") if isinstance(intention.metadata, dict) else None
    if not isinstance(quality, dict):
        return legacy_intention_content_allows_surface(intention)
    return quality.get("accepted") is not False


def legacy_intention_content_allows_surface(intention: Intention) -> bool:
    """Apply a conservative gate to older queued rows that predate quality metadata."""
    text = f"{intention.content}\n{intention.reason}".lower()
    priority = int_value(intention.metadata.get("priority"), 3) if isinstance(intention.metadata, dict) else 3
    if priority >= 4 and intention.kind == "question" and intention.content.strip().endswith("?"):
        return True
    filler_patterns = (
        "want to talk about", "want to revisit", "should we talk about", "should we revisit", "do you want to talk",
        "do you want to revisit", "what do you think about", "any thoughts on", "want to peek", "want to take a look",
        "i left a note", "left a note", "i worked on", "i was thinking about", "thought this was interesting",
        "just wanted to", "checking in", "worth mentioning later", "might be fun to", "could be interesting",
    )
    if any(pattern in text for pattern in filler_patterns):
        return False
    if intention.kind == "question":
        return intention.content.strip().endswith("?")
    if intention.kind in {"comment", "suggestion", "curiosity", "follow_up"}:
        signal_markers = (
            "found", "noticed", "discovered", "learned", "confirmed", "evidence", "source", "risk", "tradeoff",
            "blocked", "blocking", "decision", "changed", "regression", "bug", "failure", "architecture", "project",
            "requirement", "preference", "goal", "next action", "open question", "caveat", "recommend",
        )
        return any(marker in text for marker in signal_markers)
    return False


def record_intention_surface(chat_id: str, intention_id: int, run_id: str = "", metadata: dict[str, Any] | None = None) -> None:
    ensure_intentions_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            insert into intention_surfaces (chat_id, intention_id, run_id, metadata)
            values (?, ?, ?, ?)
            """,
            (chat_id, int(intention_id), run_id, json.dumps(metadata or {})),
        )


def has_intention_with_metadata(
    *,
    source_activity: str = "",
    metadata_key: str = "",
    metadata_value: Any = None,
    within_hours: float | None = None,
    now: datetime | None = None,
    limit: int = 200,
) -> bool:
    """Whether any intention (any status) matches the given metadata filters.

    Used for once-per-day / once-per-document gating (e.g. show-and-tell) without a
    schema migration — the intentions table itself is the ledger of what she has raised.
    """
    ensure_intentions_database()
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(hours=within_hours) if within_hours is not None else None
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            "select created_at, metadata from intentions order by created_at desc limit ?",
            (int(limit),),
        ).fetchall()
    for created_at, metadata_text in rows:
        if cutoff is not None:
            created = parse_timestamp(str(created_at or ""))
            if created is not None and created < cutoff:
                break
        try:
            meta = json.loads(metadata_text or "{}")
        except (ValueError, TypeError):
            continue
        if not isinstance(meta, dict):
            continue
        if source_activity and str(meta.get("source_activity") or "") != source_activity:
            continue
        if metadata_key and str(meta.get(metadata_key) or "") != str(metadata_value):
            continue
        return True
    return False


def recent_spontaneous_remark(*, now: datetime | None = None, cooldown_minutes: int = SURFACE_COOLDOWN_MINUTES) -> bool:
    """True if a spontaneous (queued-while-working) remark was created within the window.

    Gates the social channel so she can speak up while working without flooding the
    queue, independent of how fast the work loop runs.
    """
    if cooldown_minutes <= 0:
        return False
    ensure_intentions_database()
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(minutes=int(cooldown_minutes))
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            "select created_at, metadata from intentions order by created_at desc limit 25"
        ).fetchall()
    for created_at, metadata_text in rows:
        created = parse_timestamp(str(created_at or ""))
        if created is None:
            continue
        if created < cutoff:
            break  # rows are newest-first; nothing older can be in-window
        try:
            meta = json.loads(metadata_text or "{}")
        except (ValueError, TypeError):
            meta = {}
        if isinstance(meta, dict) and meta.get("spontaneous"):
            return True
    return False


def recent_intention_surface_for_chat(chat_id: str, *, now: datetime | None = None, cooldown_minutes: int = SURFACE_COOLDOWN_MINUTES) -> bool:
    if not chat_id:
        return False
    ensure_intentions_database()
    current = now or datetime.now(timezone.utc)
    cutoff = current - timedelta(minutes=max(0, int(cooldown_minutes)))
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            "select surfaced_at from intention_surfaces where chat_id = ? order by surfaced_at desc limit 5",
            (chat_id,),
        ).fetchall()
    for row in rows:
        surfaced_at = parse_timestamp(str(row[0] or ""))
        if surfaced_at is not None and surfaced_at >= cutoff:
            return True
    return False


def intention_priority(intention: Intention) -> int:
    quality = intention.metadata.get("quality") if isinstance(intention.metadata, dict) else None
    if isinstance(quality, dict) and "importance" in quality:
        return max(1, min(5, int_value(quality.get("importance"), 3)))
    return max(1, min(5, int_value(intention.metadata.get("priority"), 3)))


def intention_relevance(intention: Intention, query_text: str, active_project_id: str = "") -> int:
    score = 0
    project_id = str(intention.metadata.get("project_id") or "").strip()
    if project_id and active_project_id and project_id == active_project_id:
        score += 3
    query_terms = set(normalize_terms(query_text))
    if query_terms:
        intention_terms = set(normalize_terms(f"{intention.content}\n{intention.reason}"))
        overlap = query_terms.intersection(intention_terms)
        if overlap:
            score += min(2, len(overlap))
    return score


def intention_is_expired(intention: Intention, now: datetime) -> bool:
    expires_at = parse_timestamp(intention.expires_at)
    return expires_at is not None and expires_at <= now


def normalize_terms(text: str) -> list[str]:
    stopwords = {"about", "after", "again", "also", "because", "before", "could", "from", "have", "should", "that", "the", "this", "want", "what", "when", "with", "would", "your"}
    return [term for term in re.findall(r"[a-z0-9]+", text.lower()) if len(term) > 2 and term not in stopwords]


def intention_to_json(intention: Intention) -> dict[str, Any]:
    return {
        "id": intention.id,
        "kind": intention.kind,
        "content": intention.content,
        "reason": intention.reason,
        "source": intention.source,
        "source_cycle_id": intention.source_cycle_id,
        "status": intention.status,
        "created_at": intention.created_at,
        "used_at": intention.used_at,
        "eligible_at": intention.eligible_at,
        "shown_at": intention.shown_at,
        "answered_at": intention.answered_at,
        "resolved_at": intention.resolved_at,
        "expires_at": intention.expires_at,
        "updated_at": intention.updated_at,
        "metadata": intention.metadata,
    }


def intention_from_row(row: Any) -> Intention:
    metadata: dict[str, Any]
    try:
        metadata = json.loads(row[9] or "{}")
    except json.JSONDecodeError:
        metadata = {}
    return Intention(
        id=int(row[0]),
        kind=str(row[1]),
        content=str(row[2]),
        reason=str(row[3] or ""),
        source=str(row[4] or "autonomy"),
        source_cycle_id=str(row[5]) if row[5] else None,
        status=str(row[6] or "pending"),
        created_at=str(row[7] or ""),
        used_at=str(row[8]) if row[8] else None,
        eligible_at=str(row[10]) if len(row) > 10 and row[10] else None,
        shown_at=str(row[11]) if len(row) > 11 and row[11] else None,
        answered_at=str(row[12]) if len(row) > 12 and row[12] else None,
        resolved_at=str(row[13]) if len(row) > 13 and row[13] else None,
        expires_at=str(row[14]) if len(row) > 14 and row[14] else None,
        updated_at=str(row[15]) if len(row) > 15 and row[15] else None,
        metadata=metadata,
    )


def select_intention_sql() -> str:
    return """
    select id, kind, content, reason, source, source_cycle_id, status, created_at, used_at, metadata,
           eligible_at, shown_at, answered_at, resolved_at, expires_at, updated_at
    from intentions
    """


def mark_ids(connection: Any, ids: list[int], status: str) -> None:
    for intention_id in ids:
        connection.execute(
            """
            update intentions
            set status = ?, resolved_at = current_timestamp, updated_at = current_timestamp
            where id = ? and status in ('pending', 'queued', 'eligible')
            """,
            (status, intention_id),
        )


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    clean = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(clean)
    except ValueError:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def int_value(value: object, fallback: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def ensure_column(connection: Any, table: str, column: str, definition: str) -> None:
    columns = {row[1] for row in connection.execute(f"pragma table_info({table})")}
    if column not in columns:
        connection.execute(f"alter table {table} add column {column} {definition}")
