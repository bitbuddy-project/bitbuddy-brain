from __future__ import annotations

from ..store import CalendarAccount
from .base import CalendarProvider, EventDraft, EventPatch
from .local import LocalCalendarProvider


def get_provider(account: CalendarAccount) -> CalendarProvider:
    """Resolve the provider implementation for a calendar account.

    Phase 0 ships only the local provider. Google/CalDAV register here later
    keyed on ``account.provider`` with no change to callers.
    """
    if account.provider == "local":
        return LocalCalendarProvider(account)
    raise ValueError(f"No calendar provider registered for '{account.provider}'.")


__all__ = ["CalendarProvider", "EventDraft", "EventPatch", "get_provider", "LocalCalendarProvider"]
