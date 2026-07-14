from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..lifecycle import local_now, parse_local_datetime


EMOTIONAL_ACKNOWLEDGMENT_MINUTES = 12 * 60


@dataclass(frozen=True)
class ConversationGap:
    minutes: int
    label: str


def conversation_gap(
    previous_user_message_at: str,
    config: Any,
    *,
    now: datetime | None = None,
) -> ConversationGap | None:
    """Describe the time since the last chat message without making it user-visible."""
    previous = parse_conversation_datetime(previous_user_message_at, config)
    if previous is None:
        return None
    current = now or local_now(config)
    minutes = max(0, int((current - previous).total_seconds() // 60))
    return ConversationGap(minutes=minutes, label=humanize_gap(minutes))


def parse_conversation_datetime(value: str, config: Any) -> datetime | None:
    """Parse chat timestamps, including SQLite's UTC timestamps without an offset."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed
    # continuity_events uses SQLite CURRENT_TIMESTAMP (UTC), while lifecycle values
    # are written as local ISO timestamps with a T and offset.
    if "T" not in value:
        return parsed.replace(tzinfo=timezone.utc)
    return parse_local_datetime(value, config)


def return_greeting_text(
    previous_activity_at: str,
    latest_user_text: str,
    config: Any,
    *,
    now: datetime | None = None,
) -> str:
    chat_config = getattr(config, "chat", None)
    if chat_config is None or not bool(getattr(chat_config, "return_greeting_enabled", True)):
        return ""
    gap = conversation_gap(previous_activity_at, config, now=now)
    if gap is None:
        return ""
    threshold = max(1, int(getattr(chat_config, "return_greeting_idle_minutes", 60)))
    # A private timing context is present on every reply, but a proactive welcome
    # should feel earned. Keep short absences from turning into repetitive small talk.
    if gap.minutes < max(threshold, EMOTIONAL_ACKNOWLEDGMENT_MINUTES):
        return ""

    phrases = list(getattr(chat_config, "return_greeting_phrases", ()) or ())
    if not phrases:
        phrases = ["Hey, welcome back."]
    text = latest_user_text.strip().lower()
    if text.startswith(("hi", "hey", "hello")):
        return phrases[0]
    return phrases[0]


def humanize_gap(minutes: int) -> str:
    if minutes < 2:
        return "a moment"
    if minutes < 60:
        return f"{minutes} minutes"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour" if hours == 1 else f"{hours} hours"
    days = hours // 24
    if days < 14:
        return f"{days} day" if days == 1 else f"{days} days"
    weeks = days // 7
    return f"{weeks} week" if weeks == 1 else f"{weeks} weeks"
