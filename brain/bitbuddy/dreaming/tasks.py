from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..autonomy.intentions import cleanup_intention_queue
from ..self_model import goal_review_summary, personality_evolution_review
from ..self_notes import cleanup_self_notes


@dataclass(frozen=True)
class DreamTaskResult:
    kind: str
    summary: str
    changes: dict[str, Any] = field(default_factory=dict)


def minidream_tasks() -> list[str]:
    return ["queue_cleanup", "self_note_cleanup", "goal_review", "personality_evolution_review"]


def run_dream_task(kind: str, *, now: datetime | None = None) -> DreamTaskResult:
    if kind == "queue_cleanup":
        changes = cleanup_intention_queue(now=now)
        count = sum(len(value) for value in changes.values() if isinstance(value, list))
        return DreamTaskResult(kind, f"Cleaned {count} stale, expired, or duplicate queued intention(s).", changes)
    if kind == "self_note_cleanup":
        expired = cleanup_self_notes(now=now)
        return DreamTaskResult(kind, f"Expired {expired} self note(s).", {"expired": expired})
    if kind == "goal_review":
        changes = goal_review_summary()
        return DreamTaskResult(kind, "Reviewed BitBuddy's self-growth goals and seeded/clarified next actions.", changes)
    if kind == "personality_evolution_review":
        changes = personality_evolution_review()
        return DreamTaskResult(kind, "Reviewed emergent personality traits and project affinities.", changes)
    return DreamTaskResult(kind, "Unknown dream task skipped.", {"skipped": True})
