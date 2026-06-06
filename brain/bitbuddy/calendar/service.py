"""Permission-gated facade over the calendar store + providers.

Everything above the provider layer (tools, HTTP API, reminder scheduler) goes
through here so permission checks and memory hooks stay in one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import load_config
from . import store
from .permissions import require_permission
from .providers import EventDraft, EventPatch, get_provider
from .store import CalendarEvent


@dataclass(frozen=True)
class ConflictPair:
    event: CalendarEvent
    conflicts_with: CalendarEvent


def _account_and_provider():
    config = load_config()
    tz = config.user_context.timezone or "UTC"
    account, _calendar = store.ensure_default_calendar(tz)
    return account, get_provider(account), tz


def user_timezone() -> str:
    return load_config().user_context.timezone or "UTC"


# --------------------------------------------------------------------------- #
# Window resolution
# --------------------------------------------------------------------------- #


def resolve_window(range_str: str, start: str, end: str, tz: str) -> tuple[str, str]:
    """Return (start_utc_iso, end_utc_iso) from either a named range or explicit bounds."""
    zone = store._zone(tz)
    now = datetime.now(zone)
    named = (range_str or "").strip().lower()

    if named in ("today", ""):
        if start or end:
            named = ""
        else:
            day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            return _utc(day), _utc(day + timedelta(days=1))
    if named == "tomorrow":
        day = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return _utc(day), _utc(day + timedelta(days=1))
    if named in ("week", "this_week", "this week"):
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return _utc(day), _utc(day + timedelta(days=7))
    if named in ("next_week", "next week"):
        day = (now + timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        return _utc(day), _utc(day + timedelta(days=7))
    if named in ("month", "this_month", "this month"):
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return _utc(day), _utc(day + timedelta(days=31))

    # Explicit bounds (ISO). Default to now .. now+7d when only one side given.
    start_iso = store.to_utc_iso(start, fallback_tz=tz) if start else _utc(now)
    end_iso = store.to_utc_iso(end, fallback_tz=tz) if end else _utc(now + timedelta(days=7))
    return start_iso, end_iso


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #


def view_events(*, range_str: str = "", start: str = "", end: str = "", enforce: bool = True) -> list[CalendarEvent]:
    account, provider, tz = _account_and_provider()
    if enforce:
        require_permission(account.id, "read")
    start_iso, end_iso = resolve_window(range_str, start, end, tz)
    events = provider.list_events(start=start_iso, end=end_iso)
    events.extend(_holiday_overlay(start_iso, end_iso, tz))
    events.sort(key=lambda event: event.start_at)
    return events


def _holiday_overlay(start_iso: str, end_iso: str, tz: str) -> list[CalendarEvent]:
    config = load_config()
    if not config.calendar.holidays_enabled:
        return []
    from .holidays import holiday_events, resolve_country

    return holiday_events(start_iso, end_iso, resolve_country(config), tz)


def find_free_slots(*, range_str: str = "", start: str = "", end: str = "", duration_minutes: int = 30, enforce: bool = True) -> list[dict[str, str]]:
    account, provider, tz = _account_and_provider()
    if enforce:
        require_permission(account.id, "read")
    start_iso, end_iso = resolve_window(range_str, start, end, tz)
    events = provider.list_events(start=start_iso, end=end_iso)
    busy = sorted(
        ((_parse(e.start_at), _parse(e.end_at)) for e in events if not e.all_day),
        key=lambda pair: pair[0],
    )
    window_start, window_end = _parse(start_iso), _parse(end_iso)
    duration = timedelta(minutes=max(1, duration_minutes))
    slots: list[dict[str, str]] = []
    cursor = window_start
    for busy_start, busy_end in busy:
        if busy_start > cursor and (busy_start - cursor) >= duration:
            slots.append({"start": _utc(cursor), "end": _utc(busy_start)})
        cursor = max(cursor, busy_end)
    if window_end > cursor and (window_end - cursor) >= duration:
        slots.append({"start": _utc(cursor), "end": _utc(window_end)})
    return slots


def detect_conflicts(events: list[CalendarEvent]) -> list[ConflictPair]:
    timed = [e for e in events if not e.all_day and e.status != "cancelled"]
    timed.sort(key=lambda e: e.start_at)
    pairs: list[ConflictPair] = []
    for i, current in enumerate(timed):
        c_start, c_end = _parse(current.start_at), _parse(current.end_at)
        for other in timed[i + 1 :]:
            o_start = _parse(other.start_at)
            if o_start >= c_end:
                break
            if o_start < c_end and c_start < _parse(other.end_at):
                pairs.append(ConflictPair(current, other))
    return pairs


# --------------------------------------------------------------------------- #
# Write (each gated by its own scope)
# --------------------------------------------------------------------------- #


def create_event(draft: EventDraft, *, enforce: bool = True) -> tuple[CalendarEvent, list[CalendarEvent]]:
    account, provider, tz = _account_and_provider()
    if enforce:
        require_permission(account.id, "create")
    event = provider.create_event(draft)
    conflicts = _conflicts_for(provider, event)
    return event, conflicts


def modify_event(event_id: str, patch: EventPatch, *, enforce: bool = True) -> tuple[CalendarEvent, list[CalendarEvent]]:
    account, provider, _tz = _account_and_provider()
    if enforce:
        require_permission(account.id, "modify")
    event = provider.update_event(event_id, patch)
    conflicts = _conflicts_for(provider, event)
    return event, conflicts


def delete_event(event_id: str, *, enforce: bool = True) -> CalendarEvent:
    account, provider, _tz = _account_and_provider()
    if enforce:
        require_permission(account.id, "delete")
    event = store.get_event(event_id)
    provider.delete_event(event_id)
    return event


def _conflicts_for(provider, event: CalendarEvent) -> list[CalendarEvent]:
    if event.all_day:
        return []
    same_day = provider.list_events(
        start=_utc(_parse(event.start_at) - timedelta(hours=12)),
        end=_utc(_parse(event.end_at) + timedelta(hours=12)),
    )
    e_start, e_end = _parse(event.start_at), _parse(event.end_at)
    out: list[CalendarEvent] = []
    for other in same_day:
        if other.id == event.id or other.all_day:
            continue
        if _parse(other.start_at) < e_end and e_start < _parse(other.end_at):
            out.append(other)
    return out


# --------------------------------------------------------------------------- #
# Memory hook
# --------------------------------------------------------------------------- #


def record_event_episode(event: CalendarEvent) -> None:
    """Write a low-importance episodic memory after an event has passed.

    Centralized here so every path that 'completes' an event records memory
    consistently. Relationship/project pattern learning rides the existing
    autonomy reflection loop and is intentionally out of scope for Phase 0.
    """
    from ..memory.episodic import create_episode

    when = event.start_at
    create_episode(
        title=f"Calendar: {event.title}",
        summary=f"Attended/observed calendar event '{event.title}' at {when}." + (f" Location: {event.location}." if event.location else ""),
        type="calendar_event",
        importance=2,
        source="calendar",
        tags=["calendar"],
        metadata={"calendar_event_id": event.id, "start_at": event.start_at, "end_at": event.end_at},
    )


def _parse(iso: str) -> datetime:
    return store.parse_datetime(iso, fallback_tz="UTC").astimezone(timezone.utc)


def calendar_overview() -> dict[str, Any]:
    """Lightweight snapshot for the HTTP API / UI status."""
    account, _provider, tz = _account_and_provider()
    from .permissions import all_permissions

    return {
        "account_id": account.id,
        "provider": account.provider,
        "timezone": tz,
        "permissions": all_permissions(account.id),
    }
