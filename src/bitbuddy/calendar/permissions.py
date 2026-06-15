from __future__ import annotations

from ..database import db_connection
from ..paths import GLOBAL_DB_PATH
from .store import ensure_calendar_database

CALENDAR_SCOPES = ("read", "create", "modify", "delete")
PERMISSION_STATES = ("granted", "denied", "ask")

# Viewing a local calendar you created in this same app is low-risk, so reads
# default to granted. Mutations are gated until the user explicitly allows them.
DEFAULT_SCOPE_STATE = {
    "read": "granted",
    "create": "ask",
    "modify": "ask",
    "delete": "ask",
}


class CalendarPermissionRequired(Exception):
    """Raised when a calendar operation needs a scope the user has not granted."""

    def __init__(self, scope: str, state: str) -> None:
        self.scope = scope
        self.state = state
        verb = {
            "read": "view your calendar",
            "create": "create calendar events",
            "modify": "modify calendar events",
            "delete": "delete calendar events",
        }.get(scope, f"perform calendar action '{scope}'")
        if state == "denied":
            message = f"Permission to {verb} is currently denied. Enable the '{scope}' scope on the Permissions page to allow it."
        else:
            message = f"I need your permission to {verb}. Enable the '{scope}' scope on the Permissions page (or say it's okay) and I'll proceed."
        super().__init__(message)


def permission_state(account_id: str, scope: str) -> str:
    if scope not in CALENDAR_SCOPES:
        return "denied"
    ensure_calendar_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute(
            "select state from calendar_permissions where account_id = ? and scope = ?",
            (account_id, scope),
        ).fetchone()
    if row is None:
        return DEFAULT_SCOPE_STATE.get(scope, "ask")
    state = str(row[0] or "ask")
    return state if state in PERMISSION_STATES else "ask"


def require_permission(account_id: str, scope: str) -> None:
    state = permission_state(account_id, scope)
    if state != "granted":
        raise CalendarPermissionRequired(scope, state)


def set_permission(account_id: str, scope: str, state: str) -> dict[str, str]:
    if scope not in CALENDAR_SCOPES:
        raise ValueError(f"Unknown calendar scope: {scope}")
    if state not in PERMISSION_STATES:
        raise ValueError(f"Unknown permission state: {state}")
    ensure_calendar_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            insert into calendar_permissions (account_id, scope, state, updated_at)
            values (?, ?, ?, current_timestamp)
            on conflict(account_id, scope) do update set state = excluded.state, updated_at = current_timestamp
            """,
            (account_id, scope, state),
        )
    return all_permissions(account_id)


def all_permissions(account_id: str) -> dict[str, str]:
    return {scope: permission_state(account_id, scope) for scope in CALENDAR_SCOPES}
