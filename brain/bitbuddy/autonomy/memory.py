from __future__ import annotations

from typing import Any

from ..memory.layers import MemoryLayer
from ..memory.store import MemoryRecord, create_memory, search_memories, update_memory


AUTONOMY_SELF_TITLE = "BitBuddy idle autonomy capabilities"
AUTONOMY_ACTIVITY_LABELS = {
    "web_curiosity": "web curiosity",
    "project_familiarization": "project familiarization",
    "generate_user_prompts": "future intention generation",
    "self_reflection": "self-model reflection",
    "network_observation": "network observation placeholder",
    "do_nothing": "safe no-op decisions",
}


def record_autonomy_self_memory(
    *,
    cycle_id: str,
    activity: str,
    status: str,
    summary: str,
    metadata: dict[str, Any] | None = None,
) -> MemoryRecord | None:
    """Record durable self knowledge about autonomy without per-cycle spam."""
    if activity in {"do_nothing", "network_observation"} and status != "completed":
        return None

    existing = autonomy_self_memory()
    observed = set()
    if existing is not None:
        raw_observed = existing.metadata.get("observed_activities")
        if isinstance(raw_observed, list):
            observed = {str(item) for item in raw_observed}

    if activity in observed and existing is not None:
        return None

    observed.add(activity)
    labels = [AUTONOMY_ACTIVITY_LABELS.get(item, item.replace("_", " ")) for item in sorted(observed)]
    durable_summary = (
        "BitBuddy has safe idle autonomy cycles that can develop context while Dustin is away. "
        f"Observed durable autonomy behaviors include: {', '.join(labels)}. "
        "Autonomy may create queued questions/comments, perform web curiosity, and familiarize itself with registered projects without destructive work."
    )
    durable_metadata = {
        "observed_activities": sorted(observed),
        "last_persistent_cycle_id": cycle_id,
        "last_persistent_activity": activity,
        "last_persistent_status": status,
        "last_persistent_summary": summary[:500],
        **(metadata or {}),
    }

    if existing is None:
        return create_memory(
            layer=MemoryLayer.SELF,
            kind="capability",
            title=AUTONOMY_SELF_TITLE,
            summary=durable_summary,
            importance=4,
            source="autonomy_self_memory",
            tags=["autonomy", "self", "capability"],
            metadata=durable_metadata,
        )

    return update_memory(
        existing.id,
        summary=durable_summary,
        tags=sorted({*existing.tags, "autonomy", "self", "capability"}),
        metadata_patch=durable_metadata,
    )


def autonomy_self_memory() -> MemoryRecord | None:
    for memory in search_memories(query="idle autonomy capabilities", layer=MemoryLayer.SELF, limit=5):
        if memory.title == AUTONOMY_SELF_TITLE or "autonomy" in memory.tags:
            return memory
    return None
