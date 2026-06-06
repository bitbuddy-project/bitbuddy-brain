from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..database import db_connection
from ..paths import GLOBAL_DB_PATH, ensure_app_dirs

LOCAL_PROVIDER = "local"
DEFAULT_ACCOUNT_LABEL = "My Calendar"
DEFAULT_CALENDAR_NAME = "Personal"
EVENT_STATUSES = ("confirmed", "tentative", "cancelled")


@dataclass(frozen=True)
class CalendarAccount:
    id: str
    provider: str
    label: str
    timezone: str
    credentials_ref: str | None
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Calendar:
    id: str
    account_id: str
    name: str
    color: str
    is_default: bool
    provider_calendar_id: str | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class CalendarEvent:
    id: str
    calendar_id: str
    provider_event_id: str | None
    title: str
    description: str
    location: str
    start_at: str
    end_at: str
    all_day: bool
    timezone: str
    rrule: str | None
    status: str
    attendees: list[str]
    source: str
    etag: str | None
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #


def ensure_calendar_database() -> None:
    ensure_app_dirs()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            create table if not exists calendar_accounts (
                id text primary key,
                provider text not null default 'local',
                label text not null default 'My Calendar',
                timezone text not null default '',
                credentials_ref text,
                metadata text not null default '{}',
                created_at text default current_timestamp,
                updated_at text default current_timestamp
            )
            """
        )
        connection.execute(
            """
            create table if not exists calendars (
                id text primary key,
                account_id text not null,
                name text not null default 'Personal',
                color text not null default '',
                is_default integer not null default 0,
                provider_calendar_id text,
                metadata text not null default '{}'
            )
            """
        )
        connection.execute(
            """
            create table if not exists calendar_events (
                id text primary key,
                calendar_id text not null,
                provider_event_id text,
                title text not null,
                description text not null default '',
                location text not null default '',
                start_at text not null,
                end_at text not null,
                all_day integer not null default 0,
                timezone text not null default '',
                rrule text,
                status text not null default 'confirmed',
                attendees text not null default '[]',
                source text not null default 'user',
                etag text,
                metadata text not null default '{}',
                created_at text default current_timestamp,
                updated_at text default current_timestamp
            )
            """
        )
        connection.execute(
            """
            create table if not exists calendar_permissions (
                account_id text not null,
                scope text not null,
                state text not null default 'ask',
                updated_at text default current_timestamp,
                primary key (account_id, scope)
            )
            """
        )
        connection.execute(
            """
            create table if not exists calendar_reminders (
                id text primary key,
                event_id text not null,
                kind text not null,
                fire_at text not null,
                fired_at text,
                metadata text not null default '{}'
            )
            """
        )
        connection.execute("create index if not exists idx_calendar_events_calendar on calendar_events(calendar_id, start_at)")
        connection.execute("create index if not exists idx_calendar_events_start on calendar_events(start_at)")
        connection.execute("create index if not exists idx_calendar_reminders_event on calendar_reminders(event_id, kind)")


# --------------------------------------------------------------------------- #
# Datetime helpers
# --------------------------------------------------------------------------- #


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_utc_iso(value: str | datetime, *, fallback_tz: str = "UTC") -> str:
    """Normalize a datetime/ISO string to a timezone-aware UTC ISO8601 string."""
    dt = parse_datetime(value, fallback_tz=fallback_tz)
    return dt.astimezone(timezone.utc).isoformat()


def parse_datetime(value: str | datetime, *, fallback_tz: str = "UTC") -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value or "").strip()
        if not raw:
            raise ValueError("A start/end time is required.")
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError as error:
            raise ValueError(f"Could not parse datetime: {value!r}. Use ISO8601, e.g. 2026-06-05T14:30.") from error
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_zone(fallback_tz))
    return dt


def local_label(iso: str, tz: str) -> str:
    """Human-friendly local time label for a stored UTC ISO string."""
    try:
        dt = parse_datetime(iso, fallback_tz="UTC").astimezone(_zone(tz))
    except ValueError:
        return iso
    return dt.strftime("%a %b %d, %I:%M %p").replace(" 0", " ")


def _zone(name: str):
    from datetime import timezone as _tz

    clean = (name or "").strip()
    if not clean or clean.upper() == "UTC":
        return _tz.utc
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(clean)
    except Exception:
        return _tz.utc


# --------------------------------------------------------------------------- #
# Accounts and calendars
# --------------------------------------------------------------------------- #


def ensure_default_calendar(timezone_name: str = "UTC") -> tuple[CalendarAccount, Calendar]:
    """Bootstrap the single local-first account + default calendar on first use."""
    ensure_calendar_database()
    accounts = list_accounts()
    account = next((a for a in accounts if a.provider == LOCAL_PROVIDER), None)
    if account is None:
        account = _insert_account(provider=LOCAL_PROVIDER, label=DEFAULT_ACCOUNT_LABEL, timezone_name=timezone_name)
    calendars = list_calendars(account.id)
    default = next((c for c in calendars if c.is_default), calendars[0] if calendars else None)
    if default is None:
        default = _insert_calendar(account.id, DEFAULT_CALENDAR_NAME, is_default=True)
    return account, default


def _insert_account(*, provider: str, label: str, timezone_name: str) -> CalendarAccount:
    account_id = str(uuid.uuid4())
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            "insert into calendar_accounts (id, provider, label, timezone, metadata) values (?, ?, ?, ?, ?)",
            (account_id, provider, label, timezone_name, "{}"),
        )
    return get_account(account_id)


def _insert_calendar(account_id: str, name: str, *, is_default: bool = False, color: str = "") -> Calendar:
    calendar_id = str(uuid.uuid4())
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            "insert into calendars (id, account_id, name, color, is_default) values (?, ?, ?, ?, ?)",
            (calendar_id, account_id, name, color, 1 if is_default else 0),
        )
    return _get_calendar(calendar_id)


def list_accounts() -> list[CalendarAccount]:
    ensure_calendar_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            "select id, provider, label, timezone, credentials_ref, metadata, created_at, updated_at from calendar_accounts order by created_at"
        ).fetchall()
    return [_account_from_row(row) for row in rows]


def get_account(account_id: str) -> CalendarAccount:
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute(
            "select id, provider, label, timezone, credentials_ref, metadata, created_at, updated_at from calendar_accounts where id = ?",
            (account_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"Unknown calendar account: {account_id}")
    return _account_from_row(row)


def list_calendars(account_id: str | None = None) -> list[Calendar]:
    ensure_calendar_database()
    clause = "where account_id = ?" if account_id else ""
    params = (account_id,) if account_id else ()
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            f"select id, account_id, name, color, is_default, provider_calendar_id, metadata from calendars {clause} order by is_default desc, name",
            params,
        ).fetchall()
    return [_calendar_from_row(row) for row in rows]


def _get_calendar(calendar_id: str) -> Calendar:
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute(
            "select id, account_id, name, color, is_default, provider_calendar_id, metadata from calendars where id = ?",
            (calendar_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"Unknown calendar: {calendar_id}")
    return _calendar_from_row(row)


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #


def insert_event(
    *,
    calendar_id: str,
    title: str,
    start_at: str,
    end_at: str,
    description: str = "",
    location: str = "",
    all_day: bool = False,
    timezone_name: str = "",
    rrule: str | None = None,
    status: str = "confirmed",
    attendees: list[str] | None = None,
    source: str = "user",
    metadata: dict[str, Any] | None = None,
) -> CalendarEvent:
    ensure_calendar_database()
    event_id = str(uuid.uuid4())
    clean_status = status if status in EVENT_STATUSES else "confirmed"
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            insert into calendar_events
                (id, calendar_id, title, description, location, start_at, end_at, all_day, timezone, rrule, status, attendees, source, metadata)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                calendar_id,
                title.strip() or "Untitled event",
                description,
                location,
                start_at,
                end_at,
                1 if all_day else 0,
                timezone_name,
                rrule,
                clean_status,
                json.dumps(attendees or []),
                source,
                json.dumps(metadata or {}),
            ),
        )
    return get_event(event_id)


def find_duplicate_event(
    *,
    calendar_id: str,
    title: str,
    start_at: str,
    end_at: str,
    location: str = "",
    all_day: bool = False,
) -> CalendarEvent | None:
    ensure_calendar_database()
    wanted_title = _identity_text(title)
    wanted_location = _identity_text(location)
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            _EVENT_SELECT + " where calendar_id = ? and start_at = ? and end_at = ? and all_day = ? and status != 'cancelled'",
            (calendar_id, start_at, end_at, 1 if all_day else 0),
        ).fetchall()
    for row in rows:
        event = _event_from_row(row)
        if _identity_text(event.title) == wanted_title and _identity_text(event.location) == wanted_location:
            return event
    return None


def _identity_text(value: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", str(value or "").casefold()).split())


def get_event(event_id: str) -> CalendarEvent:
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute(_EVENT_SELECT + " where id = ?", (event_id,)).fetchone()
    if row is None:
        raise ValueError(f"Unknown calendar event: {event_id}")
    return _event_from_row(row)


def find_event(event_id: str) -> CalendarEvent | None:
    try:
        return get_event(event_id)
    except ValueError:
        return None


def list_events_between(start_utc_iso: str, end_utc_iso: str, *, calendar_ids: list[str] | None = None) -> list[CalendarEvent]:
    ensure_calendar_database()
    clauses = ["end_at >= ?", "start_at <= ?", "status != 'cancelled'"]
    params: list[Any] = [start_utc_iso, end_utc_iso]
    if calendar_ids:
        placeholders = ",".join("?" for _ in calendar_ids)
        clauses.append(f"calendar_id in ({placeholders})")
        params.extend(calendar_ids)
    where = " and ".join(clauses)
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(f"{_EVENT_SELECT} where {where} order by start_at", params).fetchall()
    return [_event_from_row(row) for row in rows]


def update_event_fields(event_id: str, fields: dict[str, Any]) -> CalendarEvent:
    allowed = {
        "title",
        "description",
        "location",
        "start_at",
        "end_at",
        "all_day",
        "timezone",
        "rrule",
        "status",
        "attendees",
    }
    sets: list[str] = []
    params: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        if key == "all_day":
            value = 1 if value else 0
        elif key == "attendees":
            value = json.dumps(value or [])
        sets.append(f"{key} = ?")
        params.append(value)
    if not sets:
        return get_event(event_id)
    sets.append("updated_at = ?")
    params.append(_iso_now())
    params.append(event_id)
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(f"update calendar_events set {', '.join(sets)} where id = ?", params)
    return get_event(event_id)


def delete_event_row(event_id: str) -> bool:
    with db_connection(GLOBAL_DB_PATH) as connection:
        cursor = connection.execute("delete from calendar_events where id = ?", (event_id,))
        connection.execute("delete from calendar_reminders where event_id = ?", (event_id,))
    return bool(cursor.rowcount)


# --------------------------------------------------------------------------- #
# Reminders (fired-once bookkeeping for the scheduler)
# --------------------------------------------------------------------------- #


def reminder_already_fired(event_id: str, kind: str) -> bool:
    ensure_calendar_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute(
            "select 1 from calendar_reminders where event_id = ? and kind = ? and fired_at is not null limit 1",
            (event_id, kind),
        ).fetchone()
    return row is not None


def record_fired_reminder(event_id: str, kind: str, fire_at: str, metadata: dict[str, Any] | None = None) -> None:
    ensure_calendar_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            "insert into calendar_reminders (id, event_id, kind, fire_at, fired_at, metadata) values (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), event_id, kind, fire_at, _iso_now(), json.dumps(metadata or {})),
        )


# --------------------------------------------------------------------------- #
# Row mapping
# --------------------------------------------------------------------------- #

_EVENT_SELECT = (
    "select id, calendar_id, provider_event_id, title, description, location, start_at, end_at, all_day, "
    "timezone, rrule, status, attendees, source, etag, metadata, created_at, updated_at from calendar_events"
)


def _json_dict(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _json_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
        return [str(item) for item in parsed] if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []


def _account_from_row(row: tuple[Any, ...]) -> CalendarAccount:
    return CalendarAccount(
        id=str(row[0]),
        provider=str(row[1] or LOCAL_PROVIDER),
        label=str(row[2] or DEFAULT_ACCOUNT_LABEL),
        timezone=str(row[3] or ""),
        credentials_ref=str(row[4]) if row[4] else None,
        metadata=_json_dict(row[5]),
        created_at=str(row[6] or ""),
        updated_at=str(row[7] or ""),
    )


def _calendar_from_row(row: tuple[Any, ...]) -> Calendar:
    return Calendar(
        id=str(row[0]),
        account_id=str(row[1]),
        name=str(row[2] or DEFAULT_CALENDAR_NAME),
        color=str(row[3] or ""),
        is_default=bool(row[4]),
        provider_calendar_id=str(row[5]) if row[5] else None,
        metadata=_json_dict(row[6]),
    )


def _event_from_row(row: tuple[Any, ...]) -> CalendarEvent:
    return CalendarEvent(
        id=str(row[0]),
        calendar_id=str(row[1]),
        provider_event_id=str(row[2]) if row[2] else None,
        title=str(row[3] or ""),
        description=str(row[4] or ""),
        location=str(row[5] or ""),
        start_at=str(row[6] or ""),
        end_at=str(row[7] or ""),
        all_day=bool(row[8]),
        timezone=str(row[9] or ""),
        rrule=str(row[10]) if row[10] else None,
        status=str(row[11] or "confirmed"),
        attendees=_json_list(row[12]),
        source=str(row[13] or "user"),
        etag=str(row[14]) if row[14] else None,
        metadata=_json_dict(row[15]),
        created_at=str(row[16] or ""),
        updated_at=str(row[17] or ""),
    )


def event_to_json(event: CalendarEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "calendar_id": event.calendar_id,
        "title": event.title,
        "description": event.description,
        "location": event.location,
        "start_at": event.start_at,
        "end_at": event.end_at,
        "all_day": event.all_day,
        "timezone": event.timezone,
        "rrule": event.rrule,
        "status": event.status,
        "attendees": event.attendees,
        "source": event.source,
        "metadata": event.metadata,
        "created_at": event.created_at,
        "updated_at": event.updated_at,
    }


def calendar_to_json(calendar: Calendar) -> dict[str, Any]:
    return {
        "id": calendar.id,
        "account_id": calendar.account_id,
        "name": calendar.name,
        "color": calendar.color,
        "is_default": calendar.is_default,
    }
