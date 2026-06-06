from __future__ import annotations

from ..database import db_connection
from ..paths import GLOBAL_DB_PATH
from .store import ensure_email_database

EMAIL_SCOPES = ("read", "search", "watch", "trash")
PERMISSION_STATES = ("granted", "denied", "ask")
DEFAULT_SCOPE_STATE = {"read": "ask", "search": "ask", "watch": "ask", "trash": "ask"}


class EmailPermissionRequired(Exception):
    def __init__(self, scope: str, state: str) -> None:
        self.scope = scope
        self.state = state
        verb = {
            "read": "read your email",
            "search": "search your email",
            "watch": "watch your email for rules",
            "trash": "move email messages to Trash",
        }.get(scope, f"use email scope '{scope}'")
        if state == "denied":
            message = f"Permission to {verb} is currently denied. Enable the '{scope}' email scope on the Permissions page to allow it."
        else:
            message = f"I need your permission to {verb}. Enable the '{scope}' email scope on the Permissions page (or say it's okay) and I'll proceed."
        super().__init__(message)


def account_id(email_address: str = "") -> str:
    clean = str(email_address or "").strip().casefold()
    return clean or "default"


def permission_state(account: str, scope: str) -> str:
    if scope not in EMAIL_SCOPES:
        return "denied"
    ensure_email_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        row = connection.execute(
            "select state from email_permissions where account_id = ? and scope = ?",
            (account, scope),
        ).fetchone()
    if row is None:
        return DEFAULT_SCOPE_STATE.get(scope, "ask")
    state = str(row[0] or "ask")
    return state if state in PERMISSION_STATES else "ask"


def require_permission(account: str, scope: str) -> None:
    state = permission_state(account, scope)
    if state != "granted":
        raise EmailPermissionRequired(scope, state)


def set_permission(account: str, scope: str, state: str) -> dict[str, str]:
    if scope not in EMAIL_SCOPES:
        raise ValueError(f"Unknown email scope: {scope}")
    if state not in PERMISSION_STATES:
        raise ValueError(f"Unknown permission state: {state}")
    ensure_email_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            insert into email_permissions (account_id, scope, state, updated_at)
            values (?, ?, ?, current_timestamp)
            on conflict(account_id, scope) do update set state = excluded.state, updated_at = current_timestamp
            """,
            (account, scope, state),
        )
    return all_permissions(account)


def all_permissions(account: str) -> dict[str, str]:
    return {scope: permission_state(account, scope) for scope in EMAIL_SCOPES}
