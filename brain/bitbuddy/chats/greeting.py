from __future__ import annotations

from datetime import datetime
from typing import Any

from ..lifecycle import local_now, parse_local_datetime


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
    previous = parse_local_datetime(previous_activity_at, config)
    if previous is None:
        return ""
    current = now or local_now(config)
    idle_minutes = (current - previous).total_seconds() / 60
    threshold = max(1, int(getattr(chat_config, "return_greeting_idle_minutes", 60)))
    if idle_minutes < threshold:
        return ""

    phrases = list(getattr(chat_config, "return_greeting_phrases", ()) or ())
    if not phrases:
        phrases = ["Hey, welcome back."]
    text = latest_user_text.strip().lower()
    if text.startswith(("hi", "hey", "hello")):
        return phrases[0]
    return phrases[0]
