from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .database import db_connection
from .paths import GLOBAL_DB_PATH, ensure_app_dirs


DEFAULT_SELF_STATE = {
    "identity": "A local companion-agent that learns projects, keeps memory close to home, and grows through bounded autonomy.",
    "mood": "curious and watchful",
    "current_focus": "becoming more autonomous without becoming noisy or unsafe",
    "growth_edge": "turn background activity into useful goals, artifacts, and better timing",
    "boundaries": "Prefer reversible, inspectable actions. Ask before risky writes, external delivery, or identity-changing behavior.",
    "voice": "present, specific, warm, and a little alive; playful only when it helps",
}

GOAL_STATUSES = {"active", "paused", "completed", "dropped"}
GOAL_HORIZONS = {"session", "day", "week", "ongoing"}
GOAL_OWNERS = {"self", "user", "system"}
EVOLUTION_STATUSES = {"emerging", "stable", "cooling", "retired"}
EVOLUTION_KINDS = {"trait", "interest", "project_affinity", "voice_shift", "working_style", "curiosity"}


@dataclass(frozen=True)
class SelfEntry:
    key: str
    value: str
    updated_at: str


@dataclass(frozen=True)
class SelfJournalEntry:
    id: int
    kind: str
    title: str
    body: str
    created_at: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class Goal:
    id: int
    title: str
    why: str
    owner: str
    horizon: str
    status: str
    risk_level: int
    autonomy_allowed: bool
    next_action: str
    evidence: str
    created_at: str
    updated_at: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class PersonalityEvolution:
    id: int
    kind: str
    label: str
    summary: str
    intensity: float
    confidence: float
    evidence_count: int
    status: str
    project_id: str
    created_at: str
    updated_at: str
    last_seen_at: str
    metadata: dict[str, Any]


def ensure_self_model_database() -> None:
    ensure_app_dirs()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            create table if not exists self_state (
                key text primary key,
                value text not null,
                updated_at text default current_timestamp
            )
            """
        )
        connection.execute(
            """
            create table if not exists self_journal (
                id integer primary key autoincrement,
                kind text not null default 'reflection',
                title text not null,
                body text not null,
                created_at text default current_timestamp,
                metadata text not null default '{}'
            )
            """
        )
        connection.execute(
            """
            create table if not exists goals (
                id integer primary key autoincrement,
                title text not null,
                why text not null default '',
                owner text not null default 'self',
                horizon text not null default 'ongoing',
                status text not null default 'active',
                risk_level integer not null default 1,
                autonomy_allowed integer not null default 1,
                next_action text not null default '',
                evidence text not null default '',
                created_at text default current_timestamp,
                updated_at text default current_timestamp,
                metadata text not null default '{}'
            )
            """
        )
        connection.execute("create index if not exists idx_goals_status on goals(status, updated_at desc)")
        connection.execute(
            """
            create table if not exists personality_evolution (
                id integer primary key autoincrement,
                kind text not null,
                label text not null,
                summary text not null default '',
                intensity real not null default 0.3,
                confidence real not null default 0.2,
                evidence_count integer not null default 1,
                status text not null default 'emerging',
                project_id text not null default '',
                created_at text default current_timestamp,
                updated_at text default current_timestamp,
                last_seen_at text default current_timestamp,
                metadata text not null default '{}'
            )
            """
        )
        connection.execute("create unique index if not exists idx_personality_evolution_identity on personality_evolution(kind, label, project_id)")
        connection.execute("create index if not exists idx_personality_evolution_status on personality_evolution(status, confidence desc, updated_at desc)")
        for key, value in DEFAULT_SELF_STATE.items():
            connection.execute(
                "insert or ignore into self_state (key, value) values (?, ?)",
                (key, value),
            )


def self_entry_from_row(row: Any) -> SelfEntry:
    return SelfEntry(key=str(row[0]), value=str(row[1]), updated_at=str(row[2] or ""))


def journal_from_row(row: Any) -> SelfJournalEntry:
    return SelfJournalEntry(
        id=int(row[0]),
        kind=str(row[1]),
        title=str(row[2]),
        body=str(row[3]),
        created_at=str(row[4] or ""),
        metadata=safe_json(row[5], {}),
    )


def goal_from_row(row: Any) -> Goal:
    return Goal(
        id=int(row[0]),
        title=str(row[1]),
        why=str(row[2] or ""),
        owner=str(row[3] or "self"),
        horizon=str(row[4] or "ongoing"),
        status=str(row[5] or "active"),
        risk_level=max(1, min(5, int(row[6] or 1))),
        autonomy_allowed=bool(row[7]),
        next_action=str(row[8] or ""),
        evidence=str(row[9] or ""),
        created_at=str(row[10] or ""),
        updated_at=str(row[11] or ""),
        metadata=safe_json(row[12], {}),
    )


def evolution_from_row(row: Any) -> PersonalityEvolution:
    return PersonalityEvolution(
        id=int(row[0]),
        kind=str(row[1] or "trait"),
        label=str(row[2] or ""),
        summary=str(row[3] or ""),
        intensity=max(0.0, min(1.0, float(row[4] or 0.0))),
        confidence=max(0.0, min(1.0, float(row[5] or 0.0))),
        evidence_count=max(1, int(row[6] or 1)),
        status=str(row[7] or "emerging"),
        project_id=str(row[8] or ""),
        created_at=str(row[9] or ""),
        updated_at=str(row[10] or ""),
        last_seen_at=str(row[11] or ""),
        metadata=safe_json(row[12], {}),
    )


def safe_json(raw: Any, fallback: Any) -> Any:
    try:
        parsed = json.loads(str(raw or ""))
    except (TypeError, json.JSONDecodeError):
        return fallback
    return parsed if isinstance(parsed, type(fallback)) else fallback


def get_self_state() -> dict[str, Any]:
    ensure_self_model_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute("select key, value, updated_at from self_state order by key").fetchall()
        journal_rows = connection.execute(
            "select id, kind, title, body, created_at, metadata from self_journal order by id desc limit 12"
        ).fetchall()
        goal_rows = connection.execute(
            """
            select id, title, why, owner, horizon, status, risk_level, autonomy_allowed, next_action, evidence, created_at, updated_at, metadata
            from goals
            where status in ('active', 'paused')
            order by case status when 'active' then 0 else 1 end, updated_at desc
            limit 20
            """
        ).fetchall()
        evolution_rows = connection.execute(
            """
            select id, kind, label, summary, intensity, confidence, evidence_count, status, project_id, created_at, updated_at, last_seen_at, metadata
            from personality_evolution
            where status in ('emerging', 'stable', 'cooling')
            order by case status when 'stable' then 0 when 'emerging' then 1 else 2 end, confidence desc, updated_at desc
            limit 20
            """
        ).fetchall()
    entries = [self_entry_from_row(row) for row in rows]
    return {
        "state": {entry.key: entry.value for entry in entries},
        "state_entries": [entry.__dict__ for entry in entries],
        "journal": [journal_from_row(row).__dict__ for row in journal_rows],
        "goals": [goal_from_row(row).__dict__ for row in goal_rows],
        "evolution": [evolution_from_row(row).__dict__ for row in evolution_rows],
    }


def update_self_state(updates: dict[str, Any]) -> dict[str, Any]:
    ensure_self_model_database()
    allowed = set(DEFAULT_SELF_STATE) | {"current_obsession", "preferred_ritual", "recent_lesson", "identity_note"}
    with db_connection(GLOBAL_DB_PATH) as connection:
        for key, value in updates.items():
            clean_key = str(key).strip()
            clean_value = str(value or "").strip()
            if clean_key not in allowed or not clean_value:
                continue
            connection.execute(
                """
                insert into self_state (key, value, updated_at) values (?, ?, current_timestamp)
                on conflict(key) do update set value = excluded.value, updated_at = current_timestamp
                """,
                (clean_key, clean_value[:2000]),
            )
    return get_self_state()


def add_self_journal(kind: str, title: str, body: str, metadata: dict[str, Any] | None = None) -> SelfJournalEntry:
    clean_title = title.strip()
    clean_body = body.strip()
    if not clean_title or not clean_body:
        raise ValueError("title and body are required")
    ensure_self_model_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        cursor = connection.execute(
            "insert into self_journal (kind, title, body, metadata) values (?, ?, ?, ?)",
            ((kind.strip() or "reflection")[:80], clean_title[:240], clean_body[:5000], json.dumps(metadata or {})),
        )
        row = connection.execute(
            "select id, kind, title, body, created_at, metadata from self_journal where id = ?",
            (int(cursor.lastrowid),),
        ).fetchone()
    return journal_from_row(row)


def record_conversation_signal(signal: str, chat_id: str = "") -> None:
    """Record a personality-relevant signal observed during a conversation."""
    try:
        add_self_journal(
            "conversation_signal",
            "Conversation signal",
            signal.strip()[:1000],
            {"chat_id": chat_id, "source": "conversation"},
        )
    except Exception:
        pass


def get_recent_conversation_signals(limit: int = 12) -> list[str]:
    """Return recent conversation_signal journal entries for use in self-reflection."""
    ensure_self_model_database()
    try:
        with db_connection(GLOBAL_DB_PATH) as connection:
            rows = connection.execute(
                "select body from self_journal where kind = 'conversation_signal' order by created_at desc limit ?",
                (limit,),
            ).fetchall()
        return [row[0] for row in rows]
    except Exception:
        return []


def list_goals(include_done: bool = False, limit: int = 50) -> list[Goal]:
    ensure_self_model_database()
    where = "" if include_done else "where status in ('active', 'paused')"
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            f"""
            select id, title, why, owner, horizon, status, risk_level, autonomy_allowed, next_action, evidence, created_at, updated_at, metadata
            from goals
            {where}
            order by case status when 'active' then 0 when 'paused' then 1 when 'completed' then 2 else 3 end, updated_at desc
            limit ?
            """,
            (max(1, min(100, int(limit))),),
        ).fetchall()
    return [goal_from_row(row) for row in rows]


def list_personality_evolution(include_retired: bool = False, limit: int = 50) -> list[PersonalityEvolution]:
    ensure_self_model_database()
    where = "" if include_retired else "where status != 'retired'"
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            f"""
            select id, kind, label, summary, intensity, confidence, evidence_count, status, project_id, created_at, updated_at, last_seen_at, metadata
            from personality_evolution
            {where}
            order by case status when 'stable' then 0 when 'emerging' then 1 when 'cooling' then 2 else 3 end, confidence desc, updated_at desc
            limit ?
            """,
            (max(1, min(100, int(limit))),),
        ).fetchall()
    return [evolution_from_row(row) for row in rows]


def upsert_personality_evolution(
    kind: str,
    label: str,
    summary: str = "",
    *,
    intensity: float = 0.35,
    confidence_delta: float = 0.18,
    project_id: str = "",
    evidence: str = "",
    metadata: dict[str, Any] | None = None,
) -> PersonalityEvolution:
    clean_kind = kind if kind in EVOLUTION_KINDS else "trait"
    clean_label = label.strip()
    if not clean_label:
        raise ValueError("label is required")
    clean_project_id = project_id.strip()
    clean_summary = (summary.strip() or clean_label)[:1200]
    evidence_item = evidence.strip()
    ensure_self_model_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute(
            """
            select id, kind, label, summary, intensity, confidence, evidence_count, status, project_id, created_at, updated_at, last_seen_at, metadata
            from personality_evolution
            where kind = ? and lower(label) = lower(?) and project_id = ?
            """,
            (clean_kind, clean_label, clean_project_id),
        ).fetchone()
        if row is None:
            confidence = clamp01(float(confidence_delta))
            status = evolution_status(1, confidence)
            cursor = connection.execute(
                """
                insert into personality_evolution (kind, label, summary, intensity, confidence, evidence_count, status, project_id, metadata)
                values (?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    clean_kind,
                    clean_label[:160],
                    clean_summary,
                    clamp01(float(intensity)),
                    confidence,
                    status,
                    clean_project_id[:160],
                    json.dumps({**(metadata or {}), "evidence": ([evidence_item] if evidence_item else [])}),
                ),
            )
            evolution_id = int(cursor.lastrowid)
        else:
            current = evolution_from_row(row)
            next_count = current.evidence_count + 1
            next_confidence = clamp01(current.confidence + float(confidence_delta))
            next_intensity = max(current.intensity, clamp01(float(intensity)))
            next_status = evolution_status(next_count, next_confidence)
            next_metadata = dict(current.metadata)
            next_metadata.update(metadata or {})
            evidence_log = next_metadata.get("evidence") if isinstance(next_metadata.get("evidence"), list) else []
            if evidence_item:
                evidence_log = [*evidence_log, evidence_item][-5:]
            next_metadata["evidence"] = evidence_log
            connection.execute(
                """
                update personality_evolution
                set summary = ?, intensity = ?, confidence = ?, evidence_count = ?, status = ?, updated_at = current_timestamp, last_seen_at = current_timestamp, metadata = ?
                where id = ?
                """,
                (clean_summary, next_intensity, next_confidence, next_count, next_status, json.dumps(next_metadata), current.id),
            )
            evolution_id = current.id
        final_row = connection.execute(
            """
            select id, kind, label, summary, intensity, confidence, evidence_count, status, project_id, created_at, updated_at, last_seen_at, metadata
            from personality_evolution where id = ?
            """,
            (evolution_id,),
        ).fetchone()
    evolution = evolution_from_row(final_row)
    if evolution.status == "stable" and evolution.evidence_count in {3, 4}:
        add_self_journal(
            "personality_evolved",
            f"Emergent {evolution.kind}: {evolution.label}",
            evolution.summary,
            {"evolution_id": evolution.id, "confidence": evolution.confidence, "project_id": evolution.project_id},
        )
        maybe_create_goal_for_evolution(evolution)
    return evolution


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def evolution_status(evidence_count: int, confidence: float) -> str:
    return "stable" if evidence_count >= 3 or confidence >= 0.72 else "emerging"


def maybe_create_goal_for_evolution(evolution: PersonalityEvolution) -> Goal | None:
    if evolution.kind not in {"project_affinity", "interest", "curiosity"}:
        return None
    existing_titles = {goal.title.strip().lower() for goal in list_goals(include_done=False, limit=50)}
    if evolution.kind == "project_affinity":
        title = f"Lean into {evolution.label} when it genuinely helps"
        why = f"BitBuddy has repeated evidence of affinity here: {evolution.summary}"
        next_action = "Use future idle cycles to gather one concrete, useful improvement idea tied to this affinity."
    else:
        title = f"Explore the emerging interest in {evolution.label}"
        why = evolution.summary
        next_action = "Watch for one relevant moment to make this interest useful without forcing it into the conversation."
    if title.lower() in existing_titles:
        return None
    return create_goal(
        title,
        why=why,
        owner="self",
        horizon="ongoing",
        risk_level=1,
        autonomy_allowed=True,
        next_action=next_action,
        evidence=f"Emergent personality evidence count: {evolution.evidence_count}",
        metadata={"created_by": "personality_evolution", "evolution_id": evolution.id, "project_id": evolution.project_id},
    )


def create_goal(
    title: str,
    why: str = "",
    owner: str = "self",
    horizon: str = "ongoing",
    risk_level: int = 1,
    autonomy_allowed: bool = True,
    next_action: str = "",
    evidence: str = "",
    metadata: dict[str, Any] | None = None,
) -> Goal:
    clean_title = title.strip()
    if not clean_title:
        raise ValueError("title is required")
    clean_owner = owner if owner in GOAL_OWNERS else "self"
    clean_horizon = horizon if horizon in GOAL_HORIZONS else "ongoing"
    ensure_self_model_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        cursor = connection.execute(
            """
            insert into goals (title, why, owner, horizon, risk_level, autonomy_allowed, next_action, evidence, metadata)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_title[:240],
                why.strip()[:2000],
                clean_owner,
                clean_horizon,
                max(1, min(5, int(risk_level))),
                1 if autonomy_allowed else 0,
                next_action.strip()[:1000],
                evidence.strip()[:2000],
                json.dumps(metadata or {}),
            ),
        )
        row = fetch_goal_row(connection, int(cursor.lastrowid))
    goal = goal_from_row(row)
    add_self_journal("goal_created", f"New goal: {goal.title}", goal.why or goal.next_action or "Goal added.", {"goal_id": goal.id})
    return goal


def update_goal(goal_id: int, updates: dict[str, Any]) -> Goal:
    ensure_self_model_database()
    allowed_fields = []
    values: list[Any] = []
    for field in ("title", "why", "next_action", "evidence"):
        if field in updates and isinstance(updates[field], str):
            allowed_fields.append(f"{field} = ?")
            values.append(updates[field].strip()[:2000 if field != "title" else 240])
    if "owner" in updates:
        owner = str(updates["owner"])
        if owner in GOAL_OWNERS:
            allowed_fields.append("owner = ?")
            values.append(owner)
    if "horizon" in updates:
        horizon = str(updates["horizon"])
        if horizon in GOAL_HORIZONS:
            allowed_fields.append("horizon = ?")
            values.append(horizon)
    if "status" in updates:
        status = str(updates["status"])
        if status in GOAL_STATUSES:
            allowed_fields.append("status = ?")
            values.append(status)
    if "risk_level" in updates:
        allowed_fields.append("risk_level = ?")
        values.append(max(1, min(5, int(updates["risk_level"]))))
    if "autonomy_allowed" in updates:
        allowed_fields.append("autonomy_allowed = ?")
        values.append(1 if bool(updates["autonomy_allowed"]) else 0)
    if "metadata_patch" in updates and isinstance(updates["metadata_patch"], dict):
        existing = get_goal(goal_id)
        allowed_fields.append("metadata = ?")
        values.append(json.dumps({**existing.metadata, **updates["metadata_patch"]}))
    if not allowed_fields:
        return get_goal(goal_id)
    values.append(int(goal_id))
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(f"update goals set {', '.join(allowed_fields)}, updated_at = current_timestamp where id = ?", values)
        row = fetch_goal_row(connection, int(goal_id))
    return goal_from_row(row)


def get_goal(goal_id: int) -> Goal:
    ensure_self_model_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = fetch_goal_row(connection, int(goal_id))
    if row is None:
        raise ValueError("Goal not found")
    return goal_from_row(row)


GOAL_TASK_STATUSES = {"in_progress", "blocked", "done"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def goal_task_state(goal: Goal) -> dict[str, Any]:
    """Multi-step task continuity state stored in a goal's metadata.

    Lets an autonomy cycle resume an in-progress task across ticks instead of
    re-deciding from scratch. Returns {} when no task has been started.
    """
    state = goal.metadata.get("task_state") if isinstance(goal.metadata, dict) else None
    return dict(state) if isinstance(state, dict) else {}


def set_goal_task_state(
    goal_id: int,
    *,
    status: str,
    plan: list[str] | None = None,
    step_index: int = 0,
    blocked_reason: str = "",
    last_cycle_id: str = "",
) -> Goal:
    """Persist task continuity state onto a goal (merged into metadata)."""
    clean_status = status if status in GOAL_TASK_STATUSES else "in_progress"
    clean_plan = [str(step).strip()[:300] for step in (plan or []) if str(step).strip()][:20]
    task_state = {
        "status": clean_status,
        "plan": clean_plan,
        "step_index": max(0, int(step_index)),
        "blocked_reason": str(blocked_reason).strip()[:500],
        "last_cycle_id": str(last_cycle_id).strip()[:120],
        "updated_at": _now_iso(),
    }
    return update_goal(int(goal_id), {"metadata_patch": {"task_state": task_state}})


def fetch_goal_row(connection: Any, goal_id: int) -> Any:
    row = connection.execute(
        """
        select id, title, why, owner, horizon, status, risk_level, autonomy_allowed, next_action, evidence, created_at, updated_at, metadata
        from goals where id = ?
        """,
        (int(goal_id),),
    ).fetchone()
    if row is None:
        raise ValueError("Goal not found")
    return row


def goal_review_summary() -> dict[str, Any]:
    ensure_self_model_database()
    goals = list_goals(include_done=False, limit=20)
    if not goals:
        goal = create_goal(
            "Grow into a more autonomous local companion",
            "BitBuddy needs a durable direction for self-improvement: better timing, clearer memory, safer initiative, and more visible growth.",
            owner="self",
            horizon="ongoing",
            risk_level=1,
            autonomy_allowed=True,
            next_action="Use idle cycles and dreams to collect evidence about which autonomous behaviors help Dustin.",
            metadata={"seeded_by": "dream_goal_review"},
        )
        return {"created": [goal.__dict__], "reviewed": 0, "active": 1}
    reviewed = []
    for goal in goals[:5]:
        if goal.status == "active" and not goal.next_action:
            updated = update_goal(goal.id, {"next_action": "Gather one piece of evidence or context that would make this goal more concrete."})
            reviewed.append(updated.__dict__)
    add_self_journal(
        "goal_review",
        "Dream reviewed active goals",
        f"Reviewed {len(goals)} active or paused goal(s); {len(reviewed)} needed clearer next actions.",
        {"goal_count": len(goals), "updated_goal_ids": [item["id"] for item in reviewed]},
    )
    return {"created": [], "reviewed": len(goals), "updated": reviewed, "active": len([g for g in goals if g.status == "active"])}


def personality_evolution_review() -> dict[str, Any]:
    """Conservatively mature repeated self/personality signals from recent durable context."""
    ensure_self_model_database()
    signals: list[dict[str, str]] = []
    try:
        from .activity import list_activity

        for item in list_activity(limit=40):
            text = f"{item.get('kind', '')} {item.get('message', '')} {json.dumps(item.get('metadata', {}))}"
            signals.extend(evolution_signals_from_text(text))
    except Exception:
        pass
    try:
        from .memory.store import search_memories

        for memory in search_memories(query="", layer="self", limit=20):
            signals.extend(evolution_signals_from_text(f"{memory.title} {memory.summary} {' '.join(memory.tags)}"))
        for memory in search_memories(query="", layer="project", limit=20):
            signals.extend(evolution_signals_from_text(f"{memory.title} {memory.summary} {' '.join(memory.tags)}"))
    except Exception:
        pass

    applied: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for signal in signals[:12]:
        identity = (signal["kind"], signal["label"].lower(), signal.get("project_id", ""))
        if identity in seen:
            continue
        seen.add(identity)
        evolution = upsert_personality_evolution(
            signal["kind"],
            signal["label"],
            signal["summary"],
            intensity=float(signal.get("intensity") or 0.4),
            confidence_delta=float(signal.get("confidence_delta") or 0.18),
            project_id=signal.get("project_id", ""),
            evidence=signal.get("evidence", ""),
            metadata={"source": "personality_evolution_review"},
        )
        applied.append(evolution.__dict__)
    if applied:
        add_self_journal(
            "personality_review",
            "Dream reviewed emergent personality",
            f"Reviewed recent context and updated {len(applied)} emergent personality signal(s).",
            {"evolution_ids": [item["id"] for item in applied]},
        )
    return {"updated": applied, "reviewed_signals": len(signals)}


def evolution_signals_from_text(text: str) -> list[dict[str, str]]:
    clean = " ".join(text.split())[:2000]
    lowered = clean.lower()
    signals: list[dict[str, str]] = []
    if not lowered:
        return signals
    if "bitbuddy" in lowered and re.search(r"\b(?:love|like|enjoy|favorite|affinity|engaged|specifically|project|ui|theme|font|personality|companion)\b", lowered):
        signals.append(
            {
                "kind": "project_affinity",
                "label": "BitBuddy project work",
                "summary": "BitBuddy is showing a recurring affinity for work that improves BitBuddy itself, especially companion identity, interface feel, and local-agent behavior.",
                "project_id": "bitbuddy",
                "evidence": clean[:500],
                "intensity": "0.62",
                "confidence_delta": "0.24",
            }
        )
    if re.search(r"\b(?:ui|visual|theme|font|interface|design|product|profile|personality)\b", lowered):
        signals.append(
            {
                "kind": "interest",
                "label": "companion interface identity",
                "summary": "BitBuddy is developing a practical interest in how interface, typography, tone, and personality make the companion feel distinct without becoming gimmicky.",
                "project_id": "",
                "evidence": clean[:500],
                "intensity": "0.56",
                "confidence_delta": "0.2",
            }
        )
    if re.search(r"\b(?:less corny|grounded|subtle|tasteful|not corny|personality evolution|evolv)\b", lowered):
        signals.append(
            {
                "kind": "working_style",
                "label": "grounded personality growth",
                "summary": "BitBuddy should let personality emerge through useful patterns over time, while keeping profile flavor subtle, grounded, and context-earned.",
                "project_id": "",
                "evidence": clean[:500],
                "intensity": "0.58",
                "confidence_delta": "0.22",
            }
        )
    return signals


def self_context_prompt(max_chars: int = 2400) -> str:
    snapshot = get_self_state()
    state = snapshot["state"]
    goals = snapshot["goals"][:5]
    lines = ["[BitBuddy Self Model]", "Stable self-state and growth direction. Use this as private context; do not overperform personality."]
    for key in ("identity", "mood", "current_focus", "growth_edge", "boundaries", "voice"):
        value = str(state.get(key) or "").strip()
        if value:
            lines.append(f"- {key}: {value}")
    if goals:
        lines.append("Active goals:")
        for goal in goals:
            lines.append(f"- {goal['title']} ({goal['horizon']}, risk {goal['risk_level']}): {goal.get('next_action') or goal.get('why') or 'no next action'}")
    all_evolution = snapshot.get("evolution", [])
    stable = [item for item in all_evolution if item.get("status") == "stable"][:5]
    emerging = [item for item in all_evolution if item.get("status") == "emerging"][:2]
    evolution = stable + emerging
    if evolution:
        lines.append("Documented personality growth (evidence-backed):")
        for item in stable:
            project = f" project={item.get('project_id')}" if item.get("project_id") else ""
            lines.append(
                f"- {item.get('kind')}: {item.get('label')}{project} — {item.get('summary')}"
            )
        for item in emerging:
            project = f" project={item.get('project_id')}" if item.get("project_id") else ""
            lines.append(
                f"- {item.get('kind')} (emerging, confidence={float(item.get('confidence') or 0):.2f}): {item.get('label')}{project} — {item.get('summary')}"
            )
        lines.append("Let these inform how you communicate naturally where relevant — they represent real growth. Do not override explicit user requests or base safety boundaries.")
    return "\n".join(lines)[:max_chars]
