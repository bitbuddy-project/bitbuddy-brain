from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .chats.repository import chat_activity_token
from .config import BitBuddyConfig, load_config
from .database import db_connection
from .paths import GLOBAL_DB_PATH, ensure_app_dirs
from .utils import log_activity


LIFECYCLE_STATES = {"Awake", "NightEligible", "Dreaming", "Sleep"}


@dataclass(frozen=True)
class LifecycleState:
    state: str
    previous_state: str
    transition_reason: str
    night_reason: str
    quiet_mode: bool
    last_user_activity_at: str
    dream_allowed_after: str
    current_dream_id: str
    updated_at: str
    metadata: dict[str, Any]


_TIMER_LOCK = threading.Lock()
_DREAM_TIMER: threading.Timer | None = None
_MONITOR_TIMER: threading.Timer | None = None


def ensure_lifecycle_database() -> None:
    ensure_app_dirs()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            create table if not exists lifecycle_state (
                id integer primary key check (id = 1),
                state text not null default 'Awake',
                previous_state text not null default '',
                transition_reason text not null default '',
                night_reason text not null default '',
                quiet_mode integer not null default 0,
                last_user_activity_at text not null default '',
                dream_allowed_after text not null default '',
                current_dream_id text not null default '',
                updated_at text default current_timestamp,
                metadata text not null default '{}'
            )
            """
        )
        connection.execute(
            """
            insert or ignore into lifecycle_state (
                id, state, previous_state, transition_reason, night_reason,
                quiet_mode, last_user_activity_at, dream_allowed_after, current_dream_id, metadata
            ) values (1, 'Awake', '', 'initialized', '', 0, '', '', '', '{}')
            """
        )


def lifecycle_status() -> dict[str, Any]:
    return asdict(get_lifecycle_state())


def get_lifecycle_state() -> LifecycleState:
    ensure_lifecycle_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute(
            """
            select state, previous_state, transition_reason, night_reason, quiet_mode,
                   last_user_activity_at, dream_allowed_after, current_dream_id, updated_at, metadata
            from lifecycle_state where id = 1
            """
        ).fetchone()
    if row is None:
        raise RuntimeError("Lifecycle state row was not initialized.")
    try:
        metadata = json.loads(row[9] or "{}")
    except json.JSONDecodeError:
        metadata = {}
    return LifecycleState(
        state=str(row[0] or "Awake"),
        previous_state=str(row[1] or ""),
        transition_reason=str(row[2] or ""),
        night_reason=str(row[3] or ""),
        quiet_mode=bool(row[4]),
        last_user_activity_at=str(row[5] or ""),
        dream_allowed_after=str(row[6] or ""),
        current_dream_id=str(row[7] or ""),
        updated_at=str(row[8] or ""),
        metadata=metadata if isinstance(metadata, dict) else {},
    )


def transition_lifecycle(
    state: str,
    *,
    reason: str,
    night_reason: str | None = None,
    quiet_mode: bool | None = None,
    last_user_activity_at: str | None = None,
    dream_allowed_after: str | None = None,
    current_dream_id: str | None = None,
    metadata_patch: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> LifecycleState:
    if state not in LIFECYCLE_STATES:
        raise ValueError(f"Unsupported lifecycle state: {state}")
    config = load_config()
    current = get_lifecycle_state()
    timestamp = iso_local(now or local_now(config))
    metadata = {**current.metadata, **(metadata_patch or {})}
    new_night_reason = current.night_reason if night_reason is None else night_reason
    new_quiet_mode = current.quiet_mode if quiet_mode is None else quiet_mode
    new_last_activity = current.last_user_activity_at if last_user_activity_at is None else last_user_activity_at
    new_dream_after = current.dream_allowed_after if dream_allowed_after is None else dream_allowed_after
    new_dream_id = current.current_dream_id if current_dream_id is None else current_dream_id

    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            update lifecycle_state
            set state = ?, previous_state = ?, transition_reason = ?, night_reason = ?,
                quiet_mode = ?, last_user_activity_at = ?, dream_allowed_after = ?,
                current_dream_id = ?, updated_at = ?, metadata = ?
            where id = 1
            """,
            (
                state,
                current.state,
                reason,
                new_night_reason,
                1 if new_quiet_mode else 0,
                new_last_activity,
                new_dream_after,
                new_dream_id,
                timestamp,
                json.dumps(metadata),
            ),
        )
    log_activity(
        "lifecycle.transition",
        f"Lifecycle {current.state} -> {state}: {reason}",
        {
            "previous_state": current.state,
            "state": state,
            "transition_reason": reason,
            "night_reason": new_night_reason,
            "quiet_mode": new_quiet_mode,
            "dream_allowed_after": new_dream_after,
            "current_dream_id": new_dream_id,
        },
    )
    try:
        from .continuity import record_continuity_event

        record_continuity_event(
            "lifecycle_state_changed",
            f"Lifecycle {current.state} -> {state}: {reason}",
            source="system",
            metadata={"previous_state": current.state, "state": state, "night_reason": new_night_reason, "quiet_mode": new_quiet_mode},
        )
    except Exception:
        pass
    if state == "Awake" and current.state != "Awake":
        try:
            from .autonomy.delivery_scheduler import schedule_intention_delivery

            schedule_intention_delivery("lifecycle_awake")
        except Exception:
            pass
    return get_lifecycle_state()


def record_user_activity(chat_id: str = "", text: str = "", now: datetime | None = None) -> LifecycleState:
    config = load_config()
    current_time = now or local_now(config)
    current_iso = iso_local(current_time)
    cancel_pending_dream_timer("user activity")

    try:
        from .dreaming.runtime import request_dream_interrupt

        request_dream_interrupt("user activity")
    except Exception as error:
        log_activity("lifecycle.interrupt_failed", "Failed to request dream interruption", {"error": str(error)})

    state = get_lifecycle_state()
    in_window = is_night_window(current_time, config)
    text_lower = text.strip().lower()
    goodnight = any(trigger and trigger in text_lower for trigger in config.dreaming.goodnight_triggers)
    goodmorning = any(trigger and trigger in text_lower for trigger in config.dreaming.goodmorning_triggers)

    if goodmorning or (not in_window and not goodnight):
        next_state = transition_lifecycle(
            "Awake",
            reason="user activity outside night window" if not goodmorning else "good morning trigger",
            night_reason="",
            quiet_mode=False,
            last_user_activity_at=current_iso,
            dream_allowed_after="",
            current_dream_id="" if state.state != "Dreaming" else None,
            metadata_patch={"last_chat_id": chat_id, "last_activity_token": chat_activity_token()},
            now=current_time,
        )
        return next_state

    if in_window or goodnight or state.state == "Sleep":
        night_reason = "goodnight" if goodnight else (state.night_reason or "bedtime")
        dream_after = iso_local(current_time + timedelta(minutes=config.dreaming.idle_before_dream_minutes))
        next_state = transition_lifecycle(
            "NightEligible",
            reason="user activity during night window" if state.state == "Sleep" else "night activity postponed dreaming",
            night_reason=night_reason,
            quiet_mode=config.dreaming.quiet_mode_after_bedtime,
            last_user_activity_at=current_iso,
            dream_allowed_after=dream_after,
            current_dream_id="" if state.state != "Dreaming" else None,
            metadata_patch={"last_chat_id": chat_id, "last_activity_token": chat_activity_token()},
            now=current_time,
        )
        schedule_dream_timer_for_state(next_state, config, now=current_time)
        return next_state

    return transition_lifecycle(
        "Awake",
        reason="user activity",
        last_user_activity_at=current_iso,
        metadata_patch={"last_chat_id": chat_id, "last_activity_token": chat_activity_token()},
        now=current_time,
    )


def evaluate_lifecycle(now: datetime | None = None) -> LifecycleState:
    config = load_config()
    current_time = now or local_now(config)
    state = get_lifecycle_state()
    if not config.dreaming.enabled:
        cancel_pending_dream_timer("dreaming disabled")
        if state.state != "Awake":
            return transition_lifecycle("Awake", reason="dreaming disabled", night_reason="", quiet_mode=False, dream_allowed_after="", current_dream_id="", now=current_time)
        return state

    if not is_night_window(current_time, config):
        cancel_pending_dream_timer("outside night window")
        if state.state != "Awake":
            return transition_lifecycle("Awake", reason="wake time or outside night window", night_reason="", quiet_mode=False, dream_allowed_after="", current_dream_id="", now=current_time)
        return state

    if state.state == "Awake":
        dream_after = iso_local(current_time + timedelta(minutes=config.dreaming.idle_before_dream_minutes))
        state = transition_lifecycle(
            "NightEligible",
            reason="bedtime window opened",
            night_reason="bedtime",
            quiet_mode=config.dreaming.quiet_mode_after_bedtime,
            dream_allowed_after=dream_after,
            now=current_time,
        )

    if state.state == "NightEligible":
        schedule_dream_timer_for_state(state, config, now=current_time)
    return state


def start_lifecycle_monitor(interval_seconds: float = 60.0) -> None:
    evaluate_lifecycle()

    def tick() -> None:
        try:
            evaluate_lifecycle()
        finally:
            with _TIMER_LOCK:
                global _MONITOR_TIMER
                _MONITOR_TIMER = threading.Timer(interval_seconds, tick)
                _MONITOR_TIMER.daemon = True
                _MONITOR_TIMER.start()

    with _TIMER_LOCK:
        global _MONITOR_TIMER
        if _MONITOR_TIMER is not None:
            _MONITOR_TIMER.cancel()
        _MONITOR_TIMER = threading.Timer(interval_seconds, tick)
        _MONITOR_TIMER.daemon = True
        _MONITOR_TIMER.start()


def cancel_pending_dream_timer(reason: str = "cancelled") -> None:
    with _TIMER_LOCK:
        global _DREAM_TIMER
        timer = _DREAM_TIMER
        _DREAM_TIMER = None
    if timer is not None:
        timer.cancel()
        log_activity("lifecycle.dream_timer_cancelled", "Cancelled pending dream timer", {"reason": reason})


def schedule_dream_timer_for_state(state: LifecycleState, config: BitBuddyConfig | None = None, now: datetime | None = None) -> None:
    if state.state != "NightEligible" or not state.dream_allowed_after:
        return
    config = config or load_config()
    current_time = now or local_now(config)
    allowed_after = parse_local_datetime(state.dream_allowed_after, config)
    if allowed_after is None:
        return
    delay = max(0.0, (allowed_after - current_time).total_seconds())

    with _TIMER_LOCK:
        global _DREAM_TIMER
        if _DREAM_TIMER is not None:
            _DREAM_TIMER.cancel()
        _DREAM_TIMER = threading.Timer(delay, start_minidream_if_allowed)
        _DREAM_TIMER.daemon = True
        _DREAM_TIMER.start()
    log_activity("lifecycle.dream_timer_scheduled", "Scheduled MiniDream idle timer", {"delay_seconds": delay, "dream_allowed_after": state.dream_allowed_after})


def start_minidream_if_allowed(now: datetime | None = None) -> str | None:
    config = load_config()
    current_time = now or local_now(config)
    state = get_lifecycle_state()
    if state.state != "NightEligible":
        return None
    if not is_night_window(current_time, config):
        evaluate_lifecycle(now=current_time)
        return None
    allowed_after = parse_local_datetime(state.dream_allowed_after, config)
    if allowed_after is not None and current_time < allowed_after:
        schedule_dream_timer_for_state(state, config, now=current_time)
        return None

    from .dreaming.runtime import start_minidream

    return start_minidream(reason=state.night_reason or "bedtime", now=current_time)


def lifecycle_allows_autonomy() -> bool:
    state = get_lifecycle_state()
    return state.state in {"Awake", "NightEligible"}


def lifecycle_quiet_mode() -> bool:
    state = get_lifecycle_state()
    return state.state == "NightEligible" and state.quiet_mode


def is_night_window(now: datetime, config: BitBuddyConfig | None = None) -> bool:
    config = config or load_config()
    bedtime_hour, bedtime_minute = parse_hhmm(config.dreaming.bedtime)
    wake_hour, wake_minute = parse_hhmm(config.dreaming.wake_time)
    current = now.time()
    bedtime = current.replace(hour=bedtime_hour, minute=bedtime_minute, second=0, microsecond=0)
    wake = current.replace(hour=wake_hour, minute=wake_minute, second=0, microsecond=0)
    if bedtime < wake:
        return bedtime <= current < wake
    return current >= bedtime or current < wake


def local_now(config: BitBuddyConfig | None = None) -> datetime:
    config = config or load_config()
    timezone = getattr(config.user_context, "timezone", "UTC") or "UTC"
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("UTC")
    return datetime.now(zone)


def iso_local(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat()


def parse_hhmm(value: str) -> tuple[int, int]:
    hour, minute = value.split(":", 1)
    return int(hour), int(minute)


def parse_local_datetime(value: str, config: BitBuddyConfig | None = None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed
    return parsed.replace(tzinfo=local_now(config).tzinfo)
