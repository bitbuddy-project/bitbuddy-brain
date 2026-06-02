from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from ..chats.repository import get_chat_summary, list_recent_chats
from ..chats.state import active_chat_run
from ..config import load_config
from ..continuity import continuity_state
from ..database import db_connection
from ..lifecycle import get_lifecycle_state
from ..notifications import notify_user
from ..paths import GLOBAL_DB_PATH
from .delivery import deliver_intention
from .intentions import (
    Intention,
    cleanup_intention_queue,
    intention_is_expired,
    intention_priority,
    intention_quality_allows_surface,
    list_pending_intentions,
    parse_timestamp,
    recent_intention_surface_for_chat,
)
from .log import log_autonomy


DEFAULT_DELIVERY_DELAY_SECONDS = 120.0
STARTUP_DELIVERY_DELAY_SECONDS = 180.0
WAKE_DELIVERY_DELAY_SECONDS = 60.0
RETRY_DELIVERY_DELAY_SECONDS = 300.0
COOLDOWN_RETRY_DELAY_SECONDS = 900.0
MIN_AUTONOMOUS_PRIORITY = 3
AUTONOMOUS_DELIVERY_COOLDOWN_MINUTES = 45
_DELIVERY_LOCK = threading.Lock()
_DELIVERY_TIMER: threading.Timer | None = None

# Active-chat tracking: the UI periodically reports which chat the user is viewing.
_ACTIVE_CHAT_ID: str = ""
_ACTIVE_CHAT_LOCK = threading.Lock()

# Notifications for autonomous deliveries that land outside the active chat.
# Keyed by chat_id, value is a count of unread deliveries.
_BACKGROUND_DELIVERIES: dict[str, int] = {}
_BACKGROUND_DELIVERIES_LOCK = threading.Lock()


def set_active_visible_chat(chat_id: str) -> None:
    with _ACTIVE_CHAT_LOCK:
        global _ACTIVE_CHAT_ID
        _ACTIVE_CHAT_ID = chat_id


def get_active_visible_chat() -> str:
    with _ACTIVE_CHAT_LOCK:
        return _ACTIVE_CHAT_ID


def notify_background_delivery(chat_id: str) -> None:
    with _BACKGROUND_DELIVERIES_LOCK:
        _BACKGROUND_DELIVERIES[chat_id] = _BACKGROUND_DELIVERIES.get(chat_id, 0) + 1


def unread_background_deliveries() -> dict[str, int]:
    with _BACKGROUND_DELIVERIES_LOCK:
        return dict(_BACKGROUND_DELIVERIES)


def clear_background_delivery_notifications(chat_id: str) -> None:
    with _BACKGROUND_DELIVERIES_LOCK:
        _BACKGROUND_DELIVERIES.pop(chat_id, None)


def schedule_intention_delivery(
    reason: str,
    *,
    chat_id: str = "",
    delay_seconds: float | None = None,
    model: str | None = None,
) -> bool:
    config = load_config()
    if config.provider.type == "none":
        log_autonomy("delivery_skipped", "Skipped intention delivery scheduling because no provider is configured", {"reason": reason})
        return False
    if not list_pending_intentions(limit=1):
        return False

    delay = delivery_delay(reason, delay_seconds)
    timer = threading.Timer(delay, run_intention_delivery_check, kwargs={"reason": reason, "chat_id": chat_id, "model": model, "reschedule_on_pending": True})
    timer.daemon = True
    with _DELIVERY_LOCK:
        global _DELIVERY_TIMER
        if _DELIVERY_TIMER is not None:
            _DELIVERY_TIMER.cancel()
        _DELIVERY_TIMER = timer
    timer.start()
    log_autonomy("delivery_scheduled", "Scheduled queued question/comment delivery check", {"reason": reason, "chat_id": chat_id, "delay_seconds": delay})
    return True


def schedule_startup_intention_delivery(model: str | None = None) -> bool:
    return schedule_intention_delivery("startup", delay_seconds=STARTUP_DELIVERY_DELAY_SECONDS, model=model)


def run_intention_delivery_check(
    *,
    reason: str = "manual",
    chat_id: str = "",
    model: str | None = None,
    now: datetime | None = None,
    reschedule_on_pending: bool = False,
) -> Intention | None:
    clear_current_delivery_timer()
    current = now or datetime.now(timezone.utc)
    cleanup_intention_queue(now=current)
    config = load_config()
    if config.provider.type == "none":
        log_autonomy("delivery_skipped", "Skipped queued intention delivery because no provider is configured", {"reason": reason})
        return None

    lifecycle = get_lifecycle_state()
    if lifecycle.state in {"Dreaming", "Sleep"}:
        log_autonomy("delivery_skipped", "Skipped queued intention delivery while dreaming or sleeping", {"reason": reason, "state": lifecycle.state})
        maybe_reschedule_pending_delivery("retry_after_lifecycle_block", chat_id=chat_id, model=model, enabled=reschedule_on_pending)
        return None

    target_chat_id = target_chat_for_delivery(chat_id)
    if not target_chat_id:
        log_autonomy("delivery_skipped", "Skipped queued intention delivery because no target chat exists", {"reason": reason})
        maybe_reschedule_pending_delivery("retry_after_missing_target_chat", chat_id=chat_id, model=model, enabled=reschedule_on_pending)
        return None
    if active_chat_run(target_chat_id) is not None:
        log_autonomy("delivery_skipped", "Skipped queued intention delivery because a chat response is running", {"reason": reason, "chat_id": target_chat_id})
        maybe_reschedule_pending_delivery("retry_after_active_chat_run", chat_id=target_chat_id, model=model, enabled=reschedule_on_pending, delay_seconds=RETRY_DELIVERY_DELAY_SECONDS)
        return None
    if global_delivery_cooldown_active(now=current):
        log_autonomy("delivery_skipped", "Skipped queued intention delivery due to global cooldown", {"reason": reason, "chat_id": target_chat_id})
        maybe_reschedule_pending_delivery("retry_after_global_cooldown", chat_id=target_chat_id, model=model, enabled=reschedule_on_pending, delay_seconds=COOLDOWN_RETRY_DELAY_SECONDS)
        return None
    if autonomous_daily_cap_reached(now=current):
        log_autonomy("delivery_skipped", "Skipped queued intention delivery due to daily cap", {"reason": reason, "chat_id": target_chat_id})
        maybe_reschedule_pending_delivery("retry_after_daily_cap", chat_id=target_chat_id, model=model, enabled=reschedule_on_pending, delay_seconds=COOLDOWN_RETRY_DELAY_SECONDS)
        return None
    if recent_intention_surface_for_chat(target_chat_id, now=current, cooldown_minutes=AUTONOMOUS_DELIVERY_COOLDOWN_MINUTES):
        log_autonomy("delivery_skipped", "Skipped queued intention delivery due to per-chat cooldown", {"reason": reason, "chat_id": target_chat_id})
        maybe_reschedule_pending_delivery("retry_after_chat_cooldown", chat_id=target_chat_id, model=model, enabled=reschedule_on_pending, delay_seconds=COOLDOWN_RETRY_DELAY_SECONDS)
        return None

    intention = select_autonomous_intention(target_chat_id, quiet_mode=bool(lifecycle.quiet_mode), now=current)
    if intention is None:
        log_autonomy("delivery_skipped", "No queued intention passed autonomous delivery gates", {"reason": reason, "chat_id": target_chat_id})
        maybe_reschedule_pending_delivery("retry_after_no_eligible_intention", chat_id=target_chat_id, model=model, enabled=reschedule_on_pending)
        return None

    delivered = deliver_intention(target_chat_id, intention, model=model, delivery_source=f"scheduled:{reason}")
    if delivered is not None:
        log_autonomy(
            "delivery_completed",
            "Delivered queued question/comment without waiting for a user prompt",
            {"reason": reason, "chat_id": target_chat_id, "intention_id": delivered.id, "kind": delivered.kind},
        )
        active = get_active_visible_chat()
        if active != target_chat_id:
            if active:
                notify_background_delivery(target_chat_id)
            notify_user(
                category="autonomy",
                severity="info",
                title="BitBuddy added a message",
                body=f"A queued {delivered.kind} was delivered in the background.",
                source_kind="autonomy.delivery_completed",
                chat_id=target_chat_id,
                action_url=f"/?chat_id={target_chat_id}",
                metadata={"reason": reason, "intention_id": delivered.id, "kind": delivered.kind},
            )
    return delivered


def clear_current_delivery_timer() -> None:
    with _DELIVERY_LOCK:
        global _DELIVERY_TIMER
        _DELIVERY_TIMER = None


def maybe_reschedule_pending_delivery(
    reason: str,
    *,
    chat_id: str = "",
    model: str | None = None,
    enabled: bool = False,
    delay_seconds: float = RETRY_DELIVERY_DELAY_SECONDS,
) -> bool:
    if not enabled:
        return False
    if not list_pending_intentions(limit=1):
        return False
    return schedule_intention_delivery(reason, chat_id=chat_id, model=model, delay_seconds=delay_seconds)


def select_autonomous_intention(chat_id: str, *, quiet_mode: bool = False, now: datetime | None = None) -> Intention | None:
    current = now or datetime.now(timezone.utc)
    candidates = []
    for intention in list_pending_intentions(limit=50):
        if intention_is_expired(intention, current):
            continue
        if not intention_quality_allows_surface(intention):
            continue
        priority = intention_priority(intention)
        if priority < MIN_AUTONOMOUS_PRIORITY:
            continue
        if quiet_mode and priority < 4:
            continue
        eligible_at = parse_timestamp(intention.eligible_at) or parse_timestamp(intention.created_at) or current
        if eligible_at > current:
            continue
        project_bonus = 1 if intention_project_matches_active_context(intention) else 0
        candidates.append(((-priority, -project_bonus, eligible_at, intention.id), intention))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def target_chat_for_delivery(chat_id: str = "") -> str:
    if chat_id and chat_exists(chat_id):
        return chat_id
    active = get_active_visible_chat()
    if active and chat_exists(active):
        return active
    state_chat = str(continuity_state().get("last_chat_id") or "").strip()
    if state_chat and chat_exists(state_chat):
        return state_chat
    chats = list_recent_chats(limit=1)
    return chats[0].id if chats else ""


def chat_exists(chat_id: str) -> bool:
    try:
        get_chat_summary(chat_id)
        return True
    except Exception:
        return False


def intention_project_matches_active_context(intention: Intention) -> bool:
    project_id = str(intention.metadata.get("project_id") or "") if isinstance(intention.metadata, dict) else ""
    if not project_id:
        return False
    return project_id == str(continuity_state().get("active_project_id") or "")


def global_delivery_cooldown_active(*, now: datetime) -> bool:
    cutoff = now - timedelta(minutes=AUTONOMOUS_DELIVERY_COOLDOWN_MINUTES)
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute("select surfaced_at from intention_surfaces order by surfaced_at desc limit 10").fetchall()
    for row in rows:
        surfaced_at = parse_timestamp(str(row[0] or ""))
        if surfaced_at is not None and surfaced_at >= cutoff:
            return True
    return False


def autonomous_daily_cap_reached(*, now: datetime) -> bool:
    config = load_config()
    daily_cap = config.autonomy.max_autonomous_deliveries_per_day
    cutoff = now - timedelta(hours=24)
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute("select surfaced_at from intention_surfaces order by surfaced_at desc limit 50").fetchall()
    count = 0
    for row in rows:
        surfaced_at = parse_timestamp(str(row[0] or ""))
        if surfaced_at is not None and surfaced_at >= cutoff:
            count += 1
    return count >= daily_cap


def delivery_delay(reason: str, override: float | None) -> float:
    if override is not None:
        return max(0.0, float(override))
    if reason == "startup":
        return STARTUP_DELIVERY_DELAY_SECONDS
    if reason == "lifecycle_awake":
        return WAKE_DELIVERY_DELAY_SECONDS
    if reason.startswith("retry_after_"):
        return RETRY_DELIVERY_DELAY_SECONDS
    return DEFAULT_DELIVERY_DELAY_SECONDS
