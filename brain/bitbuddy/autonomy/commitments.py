"""Commitment / follow-through tracking.

When the user says they will do something by a deadline ("I'll send the deck to
Sarah by Friday"), BitBuddy quietly records it and resurfaces it at the right
time as a gentle accountability nudge. Detection runs in the background off the
recent chat window (no live-chat latency); the model resolves relative deadlines
("Friday", "tonight") to absolute datetimes given the current time, so no date
parser is needed. Any failure is swallowed so the caller (memory consolidation)
is never disrupted.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..config import load_config
from .decision import collect_model_text, extract_json_object
from .intentions import (
    create_intention,
    has_intention_with_metadata,
    normalize_intention_content,
    parse_timestamp,
)
from .log import log_autonomy

# Surface the nudge this long before the deadline (a useful heads-up, not a post-mortem).
COMMITMENT_LEAD = timedelta(hours=2)
# Let an unaddressed commitment linger this long past its deadline before it goes stale.
COMMITMENT_GRACE = timedelta(days=2)
# Don't double-queue the same commitment across repeated consolidation passes.
COMMITMENT_DEDUPE_HOURS = 72
MIN_CONFIDENCE = 0.6
MAX_COMMITMENTS = 3
# How many recent user turns to consider.
MAX_USER_TURNS = 12


@dataclass(frozen=True)
class Commitment:
    summary: str
    due_iso: str
    confidence: float
    quote: str = ""


def _user_transcript(window: dict) -> str:
    messages = window.get("messages") if isinstance(window, dict) else None
    if not isinstance(messages, list):
        return ""
    turns = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        if str(message.get("role") or "") != "user":
            continue
        text = str(message.get("content") or "").strip()
        if text:
            turns.append(text)
    return "\n\n".join(turns[-MAX_USER_TURNS:])


def _commitment_system_prompt(now: datetime) -> str:
    return (
        "You are BitBuddy, watching for promises the user makes to themselves so you can "
        "gently follow up later. Read the user's recent messages and extract ONLY explicit, "
        "actionable, first-person commitments that have a clear deadline — e.g. 'I'll send the "
        "deck to Sarah by Friday', 'I need to reply to the landlord tonight'. "
        "Ignore vague wishes, hypotheticals, questions, things already completed, and anything "
        "without a concrete time. "
        f"The current date and time is {now.isoformat()}. Resolve every relative deadline "
        "('Friday', 'tonight', 'tomorrow at 5', 'end of week') to an absolute ISO-8601 datetime. "
        "Respond with a single JSON object: "
        '{"commitments": [{"summary": "send the deck to Sarah", "due_iso": "2026-06-19T17:00:00", '
        '"confidence": 0.0-1.0, "quote": "short verbatim snippet"}]}. '
        "summary is a short third-person action phrase. If there are no real commitments, return "
        '{"commitments": []}. No prose outside the JSON.'
    )


def extract_commitments(client, window: dict, *, now: datetime, model: str | None = None) -> list[Commitment]:
    """Return future-dated, confident commitments found in the user's recent turns."""
    transcript = _user_transcript(window)
    if not transcript:
        return []
    try:
        raw = collect_model_text(
            client,
            [
                {"role": "system", "content": _commitment_system_prompt(now)},
                {"role": "user", "content": transcript},
            ],
            model=model,
        )
        data = json.loads(extract_json_object(raw))
    except Exception as error:
        log_autonomy("commitment_scan_skip", "Commitment extraction failed", {"error": str(error)})
        return []

    results: list[Commitment] = []
    for entry in data.get("commitments") or []:
        if not isinstance(entry, dict):
            continue
        summary = str(entry.get("summary") or "").strip()[:200]
        due = parse_timestamp(str(entry.get("due_iso") or "").strip())
        if not summary or due is None or due <= now:
            continue
        try:
            confidence = float(entry.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < MIN_CONFIDENCE:
            continue
        results.append(
            Commitment(
                summary=summary,
                due_iso=due.isoformat(),
                confidence=confidence,
                quote=str(entry.get("quote") or "").strip()[:200],
            )
        )
        if len(results) >= MAX_COMMITMENTS:
            break
    return results


def _commitment_key(commitment: Commitment) -> str:
    due_day = commitment.due_iso[:10]
    basis = f"{normalize_intention_content(commitment.summary)}|{due_day}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def _friendly_due(due: datetime) -> str:
    return due.strftime("%A %b %-d at %-I:%M %p").replace(" 0", " ")


def _commitment_content(commitment: Commitment, due: datetime) -> str:
    return (
        f"Earlier you said you'd {commitment.summary} by {_friendly_due(due)}. "
        "Still on track, or want me to bump it or nudge you again?"
    )


def queue_commitment_followups(commitments: list[Commitment], *, chat_id: str, now: datetime) -> list[object]:
    queued: list[object] = []
    for commitment in commitments:
        due = parse_timestamp(commitment.due_iso)
        if due is None or due <= now:
            continue
        key = _commitment_key(commitment)
        if has_intention_with_metadata(metadata_key="commitment_key", metadata_value=key, within_hours=COMMITMENT_DEDUPE_HOURS, now=now):
            continue
        eligible_at = max(now, due - COMMITMENT_LEAD)
        expires_at = due + COMMITMENT_GRACE
        try:
            intention = create_intention(
                "follow_up",
                _commitment_content(commitment, due),
                f"User committed to: {commitment.summary} (due {commitment.due_iso})",
                metadata={
                    "source_activity": "commitment_tracker",
                    "priority": 4,
                    "commitment_key": key,
                    "due_iso": commitment.due_iso,
                    "chat_id": chat_id,
                    "quality": {"accepted": True, "importance": 4, "source_activity": "commitment_tracker"},
                },
                eligible_at=eligible_at.isoformat(),
                expires_at=expires_at.isoformat(),
            )
        except ValueError:
            continue
        queued.append(intention)
    return queued


def scan_and_queue_commitments(window: dict, client, *, chat_id: str, now: datetime | None = None, model: str | None = None) -> list[object]:
    """Detect commitments in a recent chat window and queue follow-ups. Never raises."""
    current = now or datetime.now(timezone.utc)
    try:
        if not getattr(load_config().autonomy, "commitment_tracking_enabled", True):
            return []
        commitments = extract_commitments(client, window, now=current, model=model)
        if not commitments:
            return []
        queued = queue_commitment_followups(commitments, chat_id=chat_id, now=current)
        if queued:
            log_autonomy(
                "commitment_followups_queued",
                f"Scheduled {len(queued)} commitment follow-up(s)",
                {"chat_id": chat_id, "intention_ids": [getattr(item, "id", None) for item in queued]},
            )
        return queued
    except Exception as error:  # belt-and-suspenders: detection must never break consolidation
        log_autonomy("commitment_scan_skip", "Commitment scan crashed", {"chat_id": chat_id, "error": str(error)})
        return []
