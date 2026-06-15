from __future__ import annotations

from typing import Any

from ..activity import list_activity
from ..config import load_config
from ..lifecycle import lifecycle_status
from .runner import autonomy_status


PHASE_ORDER = [
    "scheduled",
    "starting",
    "checking_stale",
    "building_context",
    "deciding_activity",
    "executing_activity",
    "recording_memory",
    "completed",
    "scheduling_repeat",
]


def autonomy_timeline() -> dict[str, Any]:
    status = autonomy_status()
    lifecycle = lifecycle_status()
    events = autonomy_timeline_events(limit=160)
    active_job = active_autonomy_job(status)
    return {
        "status": status,
        "lifecycle": lifecycle,
        "steps": current_timeline_steps(status, lifecycle, events, active_job),
        "recent_cycles": recent_cycles(events),
        "recent_events": events[:60],
    }


def autonomy_timeline_events(limit: int = 160) -> list[dict[str, Any]]:
    prefixes = (
        "autonomy.",
        "memory_consolidation.",
        "lifecycle.",
    )
    return [item for item in list_activity(limit=limit) if str(item.get("kind") or "").startswith(prefixes)]


def active_autonomy_job(status: dict[str, Any]) -> dict[str, Any] | None:
    jobs = status.get("jobs") if isinstance(status.get("jobs"), list) else []
    for job in jobs:
        if isinstance(job, dict) and job.get("phase") != "scheduled":
            return job
    for job in jobs:
        if isinstance(job, dict):
            return job
    return None


def current_timeline_steps(
    status: dict[str, Any],
    lifecycle: dict[str, Any],
    events: list[dict[str, Any]],
    job: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    current_phase = str(job.get("phase") or "") if job else ""
    current_index = PHASE_ORDER.index(current_phase) if current_phase in PHASE_ORDER else -1
    latest_by_kind = latest_events_by_kind(events)
    config = load_config()

    steps = [
        base_step(
            "user_activity",
            "User activity",
            "Chat activity creates the idle window and cancels stale work if the user returns.",
            status="completed" if latest_by_kind.get("lifecycle.transition") else "pending",
            event=latest_by_kind.get("lifecycle.transition"),
        ),
        base_step(
            "memory_consolidation",
            "Memory consolidation",
            "Private idle review extracts durable memory before autonomy runs.",
            status=memory_consolidation_status(latest_by_kind),
            event=latest_memory_event(latest_by_kind),
        ),
        phase_step("scheduled", "Autonomy delay", "Idle autonomy is scheduled after the user has been away long enough.", current_phase, current_index, job),
        lifecycle_gate_step(status, lifecycle, job),
        phase_step("checking_stale", "Staleness check", "BitBuddy verifies no newer chat activity invalidated this cycle.", current_phase, current_index, job),
        phase_step("building_context", "Build context", "Safe context is assembled from recent chat, memory, projects, and lifecycle state.", current_phase, current_index, job),
        phase_step("deciding_activity", "Choose activity", "The model chooses one allowed autonomy activity from the fixed menu.", current_phase, current_index, job),
        phase_step("executing_activity", "Run activity", "BitBuddy runs the selected branch without mutating user projects or system state.", current_phase, current_index, job),
        phase_step("recording_memory", "Record useful memory", "Useful autonomy outcomes can become self, project, semantic, or queued intention memory.", current_phase, current_index, job),
        output_step(current_phase, current_index, latest_by_kind, job),
        delivery_step(latest_by_kind),
        phase_step("scheduling_repeat", "Repeat decision", "If repeat autonomy is enabled and the user is still away, another cycle is scheduled with backoff.", current_phase, current_index, job),
    ]

    if status.get("state") == "disabled" and config.provider.type == "none":
        steps[2]["status"] = "blocked"
        steps[2]["message"] = "No model provider is configured."
    elif status.get("state") == "disabled" and not status.get("enabled"):
        steps[2]["status"] = "blocked"
        steps[2]["message"] = "Idle autonomy is disabled in settings."

    return steps


def base_step(
    step_id: str,
    label: str,
    description: str,
    *,
    status: str = "pending",
    message: str = "",
    event: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event_metadata = event.get("metadata") if isinstance(event, dict) and isinstance(event.get("metadata"), dict) else {}
    return {
        "id": step_id,
        "label": label,
        "description": description,
        "status": status,
        "message": message or (str(event.get("message") or "") if isinstance(event, dict) else ""),
        "timestamp": str(event.get("created_at") or "") if isinstance(event, dict) else "",
        "metadata": {**event_metadata, **(metadata or {})},
    }


def phase_step(
    phase: str,
    label: str,
    description: str,
    current_phase: str,
    current_index: int,
    job: dict[str, Any] | None,
) -> dict[str, Any]:
    phase_index = PHASE_ORDER.index(phase) if phase in PHASE_ORDER else -1
    if not job:
        return base_step(phase, label, description)
    if current_phase in {"failed", "stale", "cancelled"} and phase_index >= current_index:
        status = "failed" if current_phase == "failed" else "skipped"
    elif phase == current_phase:
        status = "active"
    elif phase_index >= 0 and current_index >= 0 and phase_index < current_index:
        status = "completed"
    else:
        status = "pending"
    message = str(job.get("phase_message") or "") if phase == current_phase else ""
    return base_step(
        phase,
        label,
        description,
        status=status,
        message=message,
        metadata={
            "chat_id": job.get("chat_id") or "",
            "job_id": job.get("job_id") or "",
            "activity": job.get("activity") or "",
            "repeat_index": job.get("repeat_index") or 0,
            "delay_seconds": job.get("delay_seconds") or 0,
        },
    )


def lifecycle_gate_step(status: dict[str, Any], lifecycle: dict[str, Any], job: dict[str, Any] | None) -> dict[str, Any]:
    if not status.get("lifecycle_allows_autonomy"):
        step_status = "blocked"
        message = "Autonomy is paused while BitBuddy is dreaming or sleeping."
    elif job:
        step_status = "completed"
        message = "Lifecycle allows this autonomy cycle."
    else:
        step_status = "pending"
        message = str(status.get("message") or "")
    return base_step(
        "lifecycle_gate",
        "Lifecycle gate",
        "Awake and NightEligible allow autonomy; Dreaming and Sleep pause it.",
        status=step_status,
        message=message,
        metadata={
            "state": lifecycle.get("state") or "",
            "quiet_mode": bool(lifecycle.get("quiet_mode")),
            "transition_reason": lifecycle.get("transition_reason") or "",
        },
    )


def output_step(current_phase: str, current_index: int, latest_by_kind: dict[str, dict[str, Any]], job: dict[str, Any] | None) -> dict[str, Any]:
    event = latest_by_kind.get("autonomy.activity_completed") or latest_by_kind.get("autonomy.activity_skipped") or latest_by_kind.get("autonomy.no_memory_or_intention")
    status = "pending"
    if current_phase == "completed" or (current_index > PHASE_ORDER.index("recording_memory")):
        status = "completed"
    elif current_phase in {"failed", "stale", "cancelled"}:
        status = "skipped"
    return base_step(
        "outputs",
        "Outputs",
        "The cycle may create queued questions, memory updates, web curiosity notes, or no durable output.",
        status=status,
        event=event,
        metadata={"job_id": job.get("job_id") if job else ""},
    )


def delivery_step(latest_by_kind: dict[str, dict[str, Any]]) -> dict[str, Any]:
    event = (
        latest_by_kind.get("autonomy.delivery_completed")
        or latest_by_kind.get("autonomy.delivery_scheduled")
        or latest_by_kind.get("autonomy.delivery_skipped")
        or latest_by_kind.get("autonomy.delivery_schedule_failed")
    )
    kind = str(event.get("kind") or "") if event else ""
    if kind.endswith("delivery_completed"):
        status = "completed"
    elif kind.endswith("delivery_scheduled"):
        status = "active"
    elif kind.endswith("delivery_skipped") or kind.endswith("delivery_schedule_failed"):
        status = "skipped"
    else:
        status = "pending"
    return base_step(
        "delivery",
        "Delivery",
        "Queued questions/comments can be surfaced later if cooldown, lifecycle, and target-chat gates pass.",
        status=status,
        event=event,
    )


def latest_events_by_kind(events: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for event in events:
        kind = str(event.get("kind") or "")
        if kind and kind not in result:
            result[kind] = event
    return result


def latest_memory_event(latest_by_kind: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for kind in (
        "memory_consolidation.completed",
        "memory_consolidation.started",
        "memory_consolidation.scheduled",
        "memory_consolidation.stale",
        "memory_consolidation.cancelled",
        "memory_consolidation.failed",
        "memory_consolidation.skipped",
    ):
        if kind in latest_by_kind:
            return latest_by_kind[kind]
    return None


def memory_consolidation_status(latest_by_kind: dict[str, dict[str, Any]]) -> str:
    event = latest_memory_event(latest_by_kind)
    if not event:
        return "pending"
    kind = str(event.get("kind") or "")
    if kind.endswith(".completed"):
        return "completed"
    if kind.endswith(".started") or kind.endswith(".scheduled"):
        return "active"
    if kind.endswith(".failed"):
        return "failed"
    return "skipped"


def recent_cycles(events: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    cycles: dict[str, dict[str, Any]] = {}
    for event in events:
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        cycle_id = str(metadata.get("job_id") or metadata.get("cycle_id") or metadata.get("next_job_id") or metadata.get("previous_job_id") or "")
        if not cycle_id:
            continue
        cycle = cycles.setdefault(
            cycle_id,
            {
                "id": cycle_id,
                "chat_id": str(metadata.get("chat_id") or ""),
                "activity": str(metadata.get("activity") or ""),
                "status": "active",
                "started_at": str(event.get("created_at") or ""),
                "updated_at": str(event.get("created_at") or ""),
                "events": [],
            },
        )
        if not cycle.get("activity") and metadata.get("activity"):
            cycle["activity"] = str(metadata.get("activity") or "")
        cycle["events"].append(event)
        if not cycle.get("updated_at") or str(event.get("created_at") or "") > str(cycle.get("updated_at") or ""):
            cycle["updated_at"] = str(event.get("created_at") or "")
        event_status = status_from_event_kind(str(event.get("kind") or ""))
        if event_status in {"completed", "failed", "skipped"}:
            cycle["status"] = event_status
    return list(cycles.values())[:limit]


def status_from_event_kind(kind: str) -> str:
    if kind.endswith(".completed") or kind.endswith(".activity_completed") or kind.endswith(".delivery_completed"):
        return "completed"
    if kind.endswith(".failed") or kind.endswith(".delivery_schedule_failed"):
        return "failed"
    if any(kind.endswith(suffix) for suffix in (".stale", ".cancelled", ".skipped", ".activity_skipped", ".no_memory_or_intention")):
        return "skipped"
    return "active"
