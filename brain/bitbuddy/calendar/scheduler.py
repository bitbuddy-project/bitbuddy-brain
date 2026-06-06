"""Time-based calendar reminder scheduler.

The idle autonomy loop only runs when the user is away, so it cannot deliver
time-precise reminders. This lightweight daemon timer wakes on a fixed cadence,
computes due reminders, de-dupes them via ``calendar_reminders``, and creates
notification records immediately. Optional chat nudges still use the intention
pipeline, but the actual reminder does not wait for autonomy delivery gates.
"""

from __future__ import annotations

import sys
import threading
from datetime import datetime, timedelta, timezone

from ..config import load_config
from . import store
from .providers import get_provider
from .service import detect_conflicts

_TIMER_LOCK = threading.Lock()
_TIMER: threading.Timer | None = None


def start_calendar_scheduler() -> None:
    config = load_config()
    if not config.calendar.enabled:
        return
    _schedule_next(config.calendar.scheduler_tick_seconds, initial=True)


def _schedule_next(delay_seconds: int, *, initial: bool = False) -> None:
    delay = max(15, int(delay_seconds))
    timer = threading.Timer(delay, run_calendar_tick)
    timer.daemon = True
    with _TIMER_LOCK:
        global _TIMER
        if _TIMER is not None and not initial:
            _TIMER.cancel()
        _TIMER = timer
        timer.start()


def run_calendar_tick() -> None:
    try:
        config = load_config()
        if config.calendar.enabled:
            _process_reminders(config)
    except Exception as error:  # never let a tick kill the timer
        print(f"BitBuddy calendar scheduler tick failed: {error}", file=sys.stderr)
    finally:
        try:
            tick = load_config().calendar.scheduler_tick_seconds
        except Exception:
            tick = 60
        _schedule_next(tick)


def _process_reminders(config) -> None:
    cal = config.calendar
    tz = config.user_context.timezone or "UTC"
    account, _calendar = store.ensure_default_calendar(tz)
    provider = get_provider(account)

    now = datetime.now(timezone.utc)
    horizon = max(cal.reminder_upcoming_minutes, cal.reminder_starting_soon_minutes, 60)
    window_end = now + timedelta(minutes=horizon + 1)
    events = provider.list_events(start=_iso(now - timedelta(hours=1)), end=_iso(window_end))

    for event in events:
        if event.all_day or event.status == "cancelled":
            continue
        start = store.parse_datetime(event.start_at, fallback_tz="UTC").astimezone(timezone.utc)
        minutes_out = (start - now).total_seconds() / 60.0
        if minutes_out <= 0:
            continue
        if minutes_out <= cal.reminder_starting_soon_minutes:
            _fire(event.id, "starting_soon", event.start_at, cal,
                  title=f"Starting soon: {event.title}",
                  body=f"'{event.title}' starts at {_local(event.start_at, tz)}.",
                  event_id=event.id,
                  nudge=True)
        elif minutes_out <= cal.reminder_upcoming_minutes:
            _fire(event.id, "upcoming", event.start_at, cal,
                  title=f"Upcoming: {event.title}",
                  body=f"'{event.title}' is coming up at {_local(event.start_at, tz)}.",
                  event_id=event.id,
                  nudge=False)

    if cal.conflict_warnings_enabled:
        for pair in detect_conflicts(events):
            key = "::".join(sorted((pair.event.id, pair.conflicts_with.id)))
            _fire(key, "conflict", pair.event.start_at, cal,
                  title="Schedule conflict",
                  body=f"'{pair.event.title}' overlaps with '{pair.conflicts_with.title}'.",
                  nudge=True)


def _fire(dedupe_id: str, kind: str, fire_at: str, cal, *, title: str, body: str, nudge: bool, event_id: str = "") -> None:
    if store.reminder_already_fired(dedupe_id, kind):
        return
    store.record_fired_reminder(dedupe_id, kind, fire_at)

    from ..notifications import notify_user

    urgent = kind == "starting_soon" and bool(getattr(cal, "urgent_interrupts_enabled", True))
    metadata = {
        "calendar_reminder_kind": kind,
        "calendar_urgent": urgent,
        "persistent": urgent and bool(getattr(cal, "urgent_interrupt_persistent", True)),
        "calendar_event_start_at": fire_at,
    }
    if event_id:
        metadata["calendar_event_id"] = event_id

    notify_user(
        category="reminder",
        severity="warning" if urgent else "info",
        title=title,
        body=body,
        source_kind="calendar",
        action_url="/calendar",
        metadata=metadata,
    )

    if nudge and cal.chat_nudges_enabled:
        try:
            from ..autonomy.intentions import create_intention

            create_intention(
                kind="comment",
                content=body,
                reason="Calendar reminder",
                source="calendar",
                metadata={"calendar_reminder_kind": kind},
            )
        except Exception as error:
            print(f"BitBuddy calendar nudge failed: {error}", file=sys.stderr)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _local(iso: str, tz: str) -> str:
    return store.local_label(iso, tz)
