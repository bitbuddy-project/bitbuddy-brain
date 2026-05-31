from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..chats.repository import chat_activity_token, chat_window_token
from ..config import load_config
from ..continuity import record_continuity_event
from ..lifecycle import lifecycle_allows_autonomy, lifecycle_quiet_mode
from ..providers import ProviderClient
from .activities import run_autonomy_activity
from .context import build_autonomy_context
from .decision import AutonomyActivityType, AutonomyDecision, choose_autonomy_activity
from .log import log_autonomy
from .memory import record_autonomy_self_memory


@dataclass
class AutonomyJob:
    chat_id: str
    job_id: str
    model: str | None
    scheduled_token: dict[str, object]
    delay_seconds: float
    consolidation_result: dict[str, object] | None = None
    repeat_index: int = 0
    phase: str = "scheduled"
    phase_message: str = "Scheduled idle autonomy cycle."
    activity: str = ""
    created_at: str = field(default_factory=lambda: utc_now_iso())
    started_at: str = ""
    updated_at: str = field(default_factory=lambda: utc_now_iso())
    cancel_event: threading.Event = field(default_factory=threading.Event)
    timer: threading.Timer | None = None
    thread: threading.Thread | None = None


_JOBS_LOCK = threading.Lock()
_JOBS_BY_CHAT_ID: dict[str, AutonomyJob] = {}
STARTUP_IDLE_CHAT_ID = "__startup_idle__"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def set_autonomy_phase(job: AutonomyJob, phase: str, message: str = "", activity: str = "") -> None:
    should_log = False
    logged_message = message
    logged_activity = activity
    with _JOBS_LOCK:
        if _JOBS_BY_CHAT_ID.get(job.chat_id) is not job:
            return
        job.phase = phase
        if message:
            job.phase_message = message
        if activity:
            job.activity = activity
        logged_message = job.phase_message
        logged_activity = job.activity
        if phase != "scheduled" and not job.started_at:
            job.started_at = utc_now_iso()
        job.updated_at = utc_now_iso()
        should_log = True
    if should_log:
        log_autonomy(
            "phase",
            logged_message or f"Autonomy phase: {phase}",
            {
                "chat_id": job.chat_id,
                "job_id": job.job_id,
                "phase": phase,
                "activity": logged_activity,
                "repeat_index": job.repeat_index,
            },
        )


def autonomy_status() -> dict[str, Any]:
    config = load_config()
    lifecycle_allowed = lifecycle_allows_autonomy()
    with _JOBS_LOCK:
        jobs = [autonomy_job_status(job) for job in _JOBS_BY_CHAT_ID.values()]

    if jobs:
        state = "running" if any(job["phase"] != "scheduled" for job in jobs) else "scheduled"
        message = next((str(job["phase_message"]) for job in jobs if job["phase"] != "scheduled"), str(jobs[0]["phase_message"]))
    elif not config.autonomy.enabled or not config.autonomy.run_after_idle_consolidation:
        state = "disabled"
        message = "Idle autonomy is disabled."
    elif not lifecycle_allowed:
        state = "blocked_by_lifecycle"
        message = "Autonomy is paused while BitBuddy is dreaming or sleeping."
    elif config.provider.type == "none":
        state = "disabled"
        message = "No model provider is configured for autonomy."
    else:
        state = "idle"
        message = "No autonomy cycle is currently scheduled or running."

    return {
        "state": state,
        "message": message,
        "enabled": bool(config.autonomy.enabled and config.autonomy.run_after_idle_consolidation),
        "lifecycle_allows_autonomy": lifecycle_allowed,
        "jobs": jobs,
    }


def autonomy_job_status(job: AutonomyJob) -> dict[str, Any]:
    return {
        "chat_id": job.chat_id,
        "job_id": job.job_id,
        "phase": job.phase,
        "phase_message": job.phase_message,
        "activity": job.activity,
        "delay_seconds": job.delay_seconds,
        "repeat_index": job.repeat_index,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "updated_at": job.updated_at,
    }


def schedule_idle_autonomy(
    chat_id: str,
    scheduled_token: dict[str, object],
    model: str | None = None,
    consolidation_result: dict[str, object] | None = None,
    repeat_index: int = 0,
    delay_seconds: float | None = None,
    cancel_existing: bool = True,
) -> str | None:
    config = load_config()
    if not config.autonomy.enabled or not config.autonomy.run_after_idle_consolidation:
        log_autonomy("disabled", "Idle autonomy is disabled", {"chat_id": chat_id})
        return None
    if not lifecycle_allows_autonomy():
        log_autonomy("skipped", "Idle autonomy skipped because lifecycle is dreaming or sleeping", {"chat_id": chat_id})
        return None
    if config.provider.type == "none":
        log_autonomy("skipped", "No model provider configured for idle autonomy", {"chat_id": chat_id})
        return None

    if cancel_existing:
        cancel_idle_autonomy(chat_id, reason="debounced by newer idle wake")
    delay = max(0.0, float(delay_seconds)) if delay_seconds is not None else idle_autonomy_delay(config.autonomy, repeat_index)
    job = AutonomyJob(
        chat_id=chat_id,
        job_id=str(uuid.uuid4()),
        model=model,
        scheduled_token=scheduled_token,
        delay_seconds=delay,
        consolidation_result=consolidation_result,
        repeat_index=max(0, int(repeat_index)),
    )
    job.phase_message = f"Scheduled idle autonomy cycle in {round(job.delay_seconds, 1)} second(s)."
    timer = threading.Timer(job.delay_seconds, _start_job_thread, args=(job,))
    timer.daemon = True
    job.timer = timer
    with _JOBS_LOCK:
        _JOBS_BY_CHAT_ID[chat_id] = job
    log_autonomy(
        "scheduled",
        "Scheduled idle autonomy cycle",
        {"chat_id": chat_id, "job_id": job.job_id, "delay_seconds": job.delay_seconds, "repeat_index": job.repeat_index},
    )
    timer.start()
    return job.job_id


def schedule_startup_idle_autonomy(model: str | None = None, delay_seconds: float | None = None) -> str | None:
    return schedule_idle_autonomy(
        STARTUP_IDLE_CHAT_ID,
        scheduled_token=chat_activity_token(),
        model=model,
        delay_seconds=delay_seconds,
    )


def cancel_idle_autonomy(chat_id: str, reason: str = "cancelled") -> None:
    with _JOBS_LOCK:
        job = _JOBS_BY_CHAT_ID.pop(chat_id, None)
    if job is None:
        return
    job.phase = "cancelled"
    job.phase_message = f"Cancelled idle autonomy cycle: {reason}."
    job.updated_at = utc_now_iso()
    job.cancel_event.set()
    if job.timer is not None:
        job.timer.cancel()
    log_autonomy("cancelled", "Cancelled idle autonomy cycle", {"chat_id": chat_id, "job_id": job.job_id, "reason": reason})


def _start_job_thread(job: AutonomyJob) -> None:
    if job.cancel_event.is_set():
        return
    set_autonomy_phase(job, "starting", "Starting idle autonomy cycle.")
    thread = threading.Thread(target=run_idle_autonomy_job, args=(job,), name=f"bitbuddy-autonomy-{job.chat_id}", daemon=True)
    job.thread = thread
    thread.start()


def run_idle_autonomy_job(job: AutonomyJob) -> None:
    started = time.monotonic()
    try:
        set_autonomy_phase(job, "checking_stale", "Checking whether the idle autonomy cycle is still current.")
        if autonomy_job_is_stale(job):
            set_autonomy_phase(job, "stale", "Skipped stale idle autonomy cycle.")
            log_autonomy("stale", "Skipped stale idle autonomy cycle", {"chat_id": job.chat_id, "job_id": job.job_id})
            return
        result = run_autonomy_cycle(
            job.chat_id,
            job.model,
            job.consolidation_result,
            cycle_id=job.job_id,
            phase_callback=lambda phase, message, activity="": set_autonomy_phase(job, phase, message, activity),
        )
        set_autonomy_phase(job, "completed", "Completed idle autonomy cycle.", str(result.get("activity") or ""))
        log_autonomy(
            "completed",
            "Completed idle autonomy cycle",
            {"chat_id": job.chat_id, "job_id": job.job_id, "repeat_index": job.repeat_index, "result": result, "elapsed_seconds": round(time.monotonic() - started, 3)},
        )
        set_autonomy_phase(job, "scheduling_repeat", "Checking whether another idle autonomy cycle should be scheduled.")
        schedule_next_idle_autonomy(job)
    except Exception as error:
        set_autonomy_phase(job, "failed", f"Idle autonomy cycle failed: {error}")
        log_autonomy("failed", "Idle autonomy cycle failed", {"chat_id": job.chat_id, "job_id": job.job_id, "error": str(error)})
    finally:
        with _JOBS_LOCK:
            if _JOBS_BY_CHAT_ID.get(job.chat_id) is job:
                _JOBS_BY_CHAT_ID.pop(job.chat_id, None)


def run_autonomy_cycle(
    chat_id: str,
    model: str | None = None,
    consolidation_result: dict[str, object] | None = None,
    cycle_id: str | None = None,
    phase_callback: Callable[[str, str, str], None] | None = None,
) -> dict[str, Any]:
    def phase(phase_name: str, message: str, activity: str = "") -> None:
        if phase_callback is not None:
            phase_callback(phase_name, message, activity)

    config = load_config()
    if not config.autonomy.enabled:
        return {"status": "skipped", "reason": "autonomy disabled"}
    cycle_id = cycle_id or str(uuid.uuid4())
    client = ProviderClient(config.provider)
    phase("building_context", "Building safe idle autonomy context.")
    context = build_autonomy_context(chat_id, consolidation_result)
    phase("deciding_activity", "Choosing one safe autonomy activity.")
    decision = choose_autonomy_activity(client, context, model=model)
    if lifecycle_quiet_mode() and decision.activity == AutonomyActivityType.GENERATE_USER_PROMPTS:
        decision = AutonomyDecision(AutonomyActivityType.DO_NOTHING, "Quiet mode after bedtime blocks low-priority prompt generation.", decision.inputs)
    if decision.activity == AutonomyActivityType.NETWORK_OBSERVATION:
        # Explicit placeholder: network metadata observer is not implemented yet.
        decision = AutonomyDecision(decision.activity, decision.reason or "Network observer is not implemented yet.", decision.inputs)
    log_autonomy(
        "decision",
        "Idle autonomy selected an activity",
        {"chat_id": chat_id, "cycle_id": cycle_id, "activity": decision.activity.value, "reason": decision.reason},
    )
    phase("executing_activity", f"Running {decision.activity.value}.", decision.activity.value)
    result = run_autonomy_activity(decision, cycle_id, client, model=model)
    self_memory = None
    if result.status == "completed":
        phase("recording_memory", "Recording autonomy self-memory if useful.", result.activity.value)
        self_memory = record_autonomy_self_memory(
            cycle_id=cycle_id,
            activity=result.activity.value,
            status=result.status,
            summary=result.summary,
            metadata={"chat_id": chat_id},
        )
    if result.status != "completed":
        log_autonomy(
            "no_memory_or_intention",
            "Autonomy cycle produced no durable memory or queued intention because the selected activity skipped",
            {"chat_id": chat_id, "cycle_id": cycle_id, "activity": result.activity.value, "summary": result.summary},
        )
    log_autonomy(
        "activity_completed" if result.status == "completed" else "activity_skipped",
        result.summary,
        {
            "chat_id": chat_id,
            "cycle_id": cycle_id,
            "activity": result.activity.value,
            "status": result.status,
            "self_memory_id": self_memory.id if self_memory is not None else "",
            **result.metadata,
        },
    )
    record_continuity_event(
        "autonomy_completed",
        result.summary,
        source="autonomy",
        chat_id=chat_id,
        run_id=cycle_id,
        project_id=str(result.metadata.get("project_id") or "") if isinstance(result.metadata, dict) else "",
        metadata={"activity": result.activity.value, "status": result.status, **result.metadata},
    )
    try:
        from .delivery_scheduler import schedule_intention_delivery

        schedule_intention_delivery("autonomy_completed", chat_id=chat_id, model=model)
    except Exception as error:
        log_autonomy("delivery_schedule_failed", "Failed to schedule queued question/comment delivery after autonomy", {"chat_id": chat_id, "cycle_id": cycle_id, "error": str(error)})
    return {
        "cycle_id": cycle_id,
        "activity": result.activity.value,
        "status": result.status,
        "summary": result.summary,
        "metadata": result.metadata,
    }


def autonomy_job_is_stale(job: AutonomyJob) -> bool:
    if job.cancel_event.is_set():
        return True
    try:
        if job.scheduled_token.get("scope") == "global_chat_activity":
            current_token = chat_activity_token()
            changed = global_chat_activity_advanced(job.scheduled_token, current_token)
        else:
            current_token = chat_window_token(job.chat_id)
            changed = current_token != job.scheduled_token
        if changed:
            log_autonomy(
                "stale_detail",
                "Idle autonomy token changed before execution",
                {"chat_id": job.chat_id, "job_id": job.job_id, "scheduled_token": job.scheduled_token, "current_token": current_token},
            )
            return True
        return False
    except Exception:
        return True


def global_chat_activity_advanced(scheduled_token: dict[str, object], current_token: dict[str, object]) -> bool:
    """Treat new chat activity as stale without letting chat deletion look like activity."""
    numeric_keys = ("chat_count", "message_count", "max_message_id", "max_sequence")
    for key in numeric_keys:
        if int(current_token.get(key) or 0) > int(scheduled_token.get(key) or 0):
            return True
    return str(current_token.get("latest_chat_updated_at") or "") > str(scheduled_token.get("latest_chat_updated_at") or "")


def schedule_next_idle_autonomy(job: AutonomyJob) -> str | None:
    config = load_config()
    if not config.autonomy.enabled or not config.autonomy.repeat_idle_cycles:
        log_autonomy("repeat_stopped", "Idle autonomy repeat scheduling is disabled", {"chat_id": job.chat_id, "job_id": job.job_id})
        return None
    if job.cancel_event.is_set() or autonomy_job_is_stale(job):
        log_autonomy("repeat_stopped", "Idle autonomy repeat stopped because user activity resumed or job was cancelled", {"chat_id": job.chat_id, "job_id": job.job_id})
        return None
    next_repeat_index = job.repeat_index + 1
    delay = idle_autonomy_delay(config.autonomy, next_repeat_index)
    next_job_id = schedule_idle_autonomy(
        job.chat_id,
        scheduled_token=job.scheduled_token,
        model=job.model,
        consolidation_result=None,
        repeat_index=next_repeat_index,
        delay_seconds=delay,
        cancel_existing=False,
    )
    if next_job_id:
        log_autonomy(
            "repeat_scheduled",
            "Scheduled next idle autonomy cycle while user remains away",
            {
                "chat_id": job.chat_id,
                "previous_job_id": job.job_id,
                "next_job_id": next_job_id,
                "repeat_index": next_repeat_index,
                "delay_seconds": delay,
            },
        )
    return next_job_id


def idle_autonomy_delay(autonomy_config: Any, repeat_index: int = 0) -> float:
    base_delay = max(0.0, float(getattr(autonomy_config, "idle_delay_seconds", 300)))
    multiplier = max(1.0, float(getattr(autonomy_config, "idle_backoff_multiplier", 2.0)))
    max_delay = max(base_delay, float(getattr(autonomy_config, "idle_max_delay_seconds", 3600)))
    delay = base_delay * (multiplier ** max(0, int(repeat_index)))
    return min(delay, max_delay)
