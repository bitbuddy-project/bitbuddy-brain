from __future__ import annotations

from dataclasses import replace

from .. import store
from ..store import Calendar, CalendarAccount, CalendarEvent
from .base import EventDraft, EventPatch


class LocalCalendarProvider:
    """Local-first provider: BitBuddy's own SQLite tables are the source of truth."""

    def __init__(self, account: CalendarAccount) -> None:
        self.account = account

    def _default_calendar_id(self) -> str:
        calendars = store.list_calendars(self.account.id)
        if not calendars:
            _, calendar = store.ensure_default_calendar(self.account.timezone or "UTC")
            return calendar.id
        default = next((c for c in calendars if c.is_default), calendars[0])
        return default.id

    def list_calendars(self) -> list[Calendar]:
        return store.list_calendars(self.account.id)

    def list_events(self, *, start: str, end: str, calendar_ids: list[str] | None = None) -> list[CalendarEvent]:
        start_utc = store.to_utc_iso(start, fallback_tz=self.account.timezone or "UTC")
        end_utc = store.to_utc_iso(end, fallback_tz=self.account.timezone or "UTC")
        ids = calendar_ids or [c.id for c in self.list_calendars()]
        return store.list_events_between(start_utc, end_utc, calendar_ids=ids)

    def create_event(self, draft: EventDraft) -> CalendarEvent:
        tz = draft.timezone or self.account.timezone or "UTC"
        calendar_id = draft.calendar_id or self._default_calendar_id()
        start_at = store.to_utc_iso(draft.start_at, fallback_tz=tz)
        end_at = store.to_utc_iso(draft.end_at, fallback_tz=tz)
        existing = store.find_duplicate_event(
            calendar_id=calendar_id,
            title=draft.title,
            start_at=start_at,
            end_at=end_at,
            location=draft.location,
            all_day=draft.all_day,
        )
        if existing is not None:
            return replace(existing, metadata={**existing.metadata, "bitbuddy_existing_event": True})
        return store.insert_event(
            calendar_id=calendar_id,
            title=draft.title,
            start_at=start_at,
            end_at=end_at,
            description=draft.description,
            location=draft.location,
            all_day=draft.all_day,
            timezone_name=tz,
            rrule=draft.rrule,
            attendees=draft.attendees,
            source=draft.source,
        )

    def update_event(self, event_id: str, patch: EventPatch) -> CalendarEvent:
        existing = store.get_event(event_id)
        tz = existing.timezone or self.account.timezone or "UTC"
        fields = patch.to_fields()
        if "start_at" in fields:
            fields["start_at"] = store.to_utc_iso(str(fields["start_at"]), fallback_tz=tz)
        if "end_at" in fields:
            fields["end_at"] = store.to_utc_iso(str(fields["end_at"]), fallback_tz=tz)
        return store.update_event_fields(event_id, fields)

    def delete_event(self, event_id: str) -> None:
        store.delete_event_row(event_id)
