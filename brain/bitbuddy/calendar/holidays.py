"""Read-only holiday overlay.

Holidays are computed on the fly (offline, via the `holidays` package) and merged
into calendar reads as synthetic all-day events with ``source="holiday"``. They are
never stored, so they are inert for create/modify/delete, and being all-day they are
ignored by conflict detection and the reminder scheduler.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone

from .store import CalendarEvent, _zone, parse_datetime

HOLIDAY_CALENDAR_ID = "holidays"
HOLIDAY_SOURCE = "holiday"


def resolve_country(config) -> str:
    """Country (ISO-3166 alpha-2) for holidays: explicit override, else from locale."""
    override = (getattr(config.calendar, "holidays_country", "") or "").strip().upper()
    if override:
        return override
    locale = (getattr(config.user_context, "locale", "") or "").strip()
    for sep in ("-", "_"):
        if sep in locale:
            region = locale.split(sep)[-1].strip().upper()
            if len(region) == 2 and region.isalpha():
                return region
    return "US"


def holiday_events(start_utc_iso: str, end_utc_iso: str, country: str, tz: str) -> list[CalendarEvent]:
    if not country:
        return []
    try:
        import holidays as holidays_lib
    except Exception:  # package missing — degrade gracefully
        return []

    zone = _zone(tz)
    start_local = parse_datetime(start_utc_iso, fallback_tz="UTC").astimezone(zone).date()
    end_local = parse_datetime(end_utc_iso, fallback_tz="UTC").astimezone(zone).date()
    years = list(range(start_local.year, end_local.year + 1))

    try:
        table = holidays_lib.country_holidays(country, years=years)
    except (NotImplementedError, KeyError):
        return []
    except Exception as error:
        print(f"BitBuddy holiday lookup failed for {country!r}: {error}", file=sys.stderr)
        return []

    events: list[CalendarEvent] = []
    for date, name in sorted(table.items()):
        if date < start_local or date > end_local:
            continue
        day_start = datetime(date.year, date.month, date.day, tzinfo=zone)
        start_at = day_start.astimezone(timezone.utc).isoformat()
        end_at = (day_start + timedelta(days=1)).astimezone(timezone.utc).isoformat()
        events.append(
            CalendarEvent(
                id=f"holiday:{country}:{date.isoformat()}",
                calendar_id=HOLIDAY_CALENDAR_ID,
                provider_event_id=None,
                title=str(name),
                description="",
                location="",
                start_at=start_at,
                end_at=end_at,
                all_day=True,
                timezone=tz,
                rrule=None,
                status="confirmed",
                attendees=[],
                source=HOLIDAY_SOURCE,
                etag=None,
                metadata={"country": country, "holiday": True},
                created_at="",
                updated_at="",
            )
        )
    return events
