"""Activity-level presets for autonomy.

BitBuddy's "how active is she" dial is a single ``activity_level`` (low / medium /
high). Each level resolves to an :class:`ActivityProfile` that bundles every knob
the dial should move at once: cycle cadence, how deep a work session goes, how many
unprompted messages she may send per day, and how freely she may speak up while
working. Individual numeric config fields still act as advanced overrides — see
``parse_autonomy_config`` in ``config.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ACTIVITY_LEVELS: tuple[str, ...] = ("low", "medium", "high")
DEFAULT_ACTIVITY_LEVEL = "medium"


@dataclass(frozen=True)
class ActivityProfile:
    idle_delay_seconds: float  # base cadence between idle cycles
    idle_max_delay_seconds: float  # cap once backoff stretches out
    idle_backoff_multiplier: float  # exponential backoff per repeat while idle
    max_steps_per_session: int  # depth: safe steps a single pursue_goal cycle may take
    max_autonomous_deliveries_per_day: int  # ceiling on unprompted messages / 24h
    surface_cooldown_minutes: int  # min gap between surfaced questions/comments
    min_autonomous_priority: int  # background-push priority floor (1-5)
    spontaneous_remark_cooldown_minutes: int  # min gap between "spoke up while working" remarks


LEVEL_PROFILES: dict[str, ActivityProfile] = {
    "low": ActivityProfile(
        idle_delay_seconds=900.0,
        idle_max_delay_seconds=3600.0,
        idle_backoff_multiplier=1.8,
        max_steps_per_session=1,
        max_autonomous_deliveries_per_day=4,
        surface_cooldown_minutes=90,
        min_autonomous_priority=4,
        spontaneous_remark_cooldown_minutes=180,
    ),
    "medium": ActivityProfile(
        idle_delay_seconds=300.0,
        idle_max_delay_seconds=1800.0,
        idle_backoff_multiplier=1.5,
        max_steps_per_session=2,
        max_autonomous_deliveries_per_day=8,
        surface_cooldown_minutes=45,
        min_autonomous_priority=3,
        spontaneous_remark_cooldown_minutes=90,
    ),
    "high": ActivityProfile(
        idle_delay_seconds=180.0,
        idle_max_delay_seconds=900.0,
        idle_backoff_multiplier=1.2,
        max_steps_per_session=4,
        max_autonomous_deliveries_per_day=16,
        surface_cooldown_minutes=25,
        min_autonomous_priority=3,
        spontaneous_remark_cooldown_minutes=45,
    ),
}


def normalize_activity_level(value: Any) -> str:
    level = str(value or "").strip().lower()
    return level if level in LEVEL_PROFILES else DEFAULT_ACTIVITY_LEVEL


def profile_for_level(level: Any) -> ActivityProfile:
    """The base profile for a level name, falling back to medium for anything unknown."""
    return LEVEL_PROFILES[normalize_activity_level(level)]


def resolve_profile(autonomy_config: Any) -> ActivityProfile:
    """Effective profile for a parsed ``AutonomyConfig``.

    ``parse_autonomy_config`` already materializes each tunable onto the config
    (using the level profile as the default and honoring explicit overrides), so
    this simply reads those concrete fields back into one :class:`ActivityProfile`.
    Missing attributes fall back to the level's base profile, which keeps older
    callers and tests that pass partial stand-ins working.
    """
    base = profile_for_level(getattr(autonomy_config, "activity_level", DEFAULT_ACTIVITY_LEVEL))
    return ActivityProfile(
        idle_delay_seconds=float(getattr(autonomy_config, "idle_delay_seconds", base.idle_delay_seconds)),
        idle_max_delay_seconds=float(getattr(autonomy_config, "idle_max_delay_seconds", base.idle_max_delay_seconds)),
        idle_backoff_multiplier=float(getattr(autonomy_config, "idle_backoff_multiplier", base.idle_backoff_multiplier)),
        max_steps_per_session=int(getattr(autonomy_config, "max_steps_per_session", base.max_steps_per_session)),
        max_autonomous_deliveries_per_day=int(
            getattr(autonomy_config, "max_autonomous_deliveries_per_day", base.max_autonomous_deliveries_per_day)
        ),
        surface_cooldown_minutes=int(getattr(autonomy_config, "surface_cooldown_minutes", base.surface_cooldown_minutes)),
        min_autonomous_priority=int(getattr(autonomy_config, "min_autonomous_priority", base.min_autonomous_priority)),
        spontaneous_remark_cooldown_minutes=int(
            getattr(autonomy_config, "spontaneous_remark_cooldown_minutes", base.spontaneous_remark_cooldown_minutes)
        ),
    )
