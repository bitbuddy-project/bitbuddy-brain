"""BitBuddy calendar capability (local-first foundation).

This package owns calendar persistence, a provider abstraction (local for now,
Google/CalDAV later), a permission-gated service facade, and a time-based
reminder scheduler. The rest of the brain should import from
``bitbuddy.calendar.service`` rather than touching the store or providers
directly so permission checks and memory hooks stay centralized.
"""

from __future__ import annotations

from .store import (
    Calendar,
    CalendarAccount,
    CalendarEvent,
    ensure_calendar_database,
)

__all__ = [
    "Calendar",
    "CalendarAccount",
    "CalendarEvent",
    "ensure_calendar_database",
]
