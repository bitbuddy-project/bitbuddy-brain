from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..store import Calendar, CalendarEvent


@dataclass(frozen=True)
class EventDraft:
    title: str
    start_at: str
    end_at: str
    description: str = ""
    location: str = ""
    all_day: bool = False
    timezone: str = ""
    rrule: str | None = None
    attendees: list[str] = field(default_factory=list)
    calendar_id: str | None = None
    source: str = "user"


@dataclass(frozen=True)
class EventPatch:
    title: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    description: str | None = None
    location: str | None = None
    all_day: bool | None = None
    status: str | None = None
    attendees: list[str] | None = None

    def to_fields(self) -> dict[str, object]:
        fields: dict[str, object] = {}
        for key in ("title", "start_at", "end_at", "description", "location", "all_day", "status", "attendees"):
            value = getattr(self, key)
            if value is not None:
                fields[key] = value
        return fields


class CalendarProvider(Protocol):
    """The single seam every calendar backend implements.

    Tools, the service facade, and the reminder scheduler only ever talk to this
    interface, so adding Google/CalDAV later requires no changes above it.
    """

    def list_calendars(self) -> list[Calendar]: ...

    def list_events(self, *, start: str, end: str, calendar_ids: list[str] | None = None) -> list[CalendarEvent]: ...

    def create_event(self, draft: EventDraft) -> CalendarEvent: ...

    def update_event(self, event_id: str, patch: EventPatch) -> CalendarEvent: ...

    def delete_event(self, event_id: str) -> None: ...
