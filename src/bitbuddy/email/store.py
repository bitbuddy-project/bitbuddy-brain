from __future__ import annotations

from ..database import db_connection
from ..paths import GLOBAL_DB_PATH, ensure_app_dirs
from .models import EmailRule


def ensure_email_database() -> None:
    ensure_app_dirs()
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            create table if not exists email_permissions (
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
            create table if not exists email_rules (
                id integer primary key autoincrement,
                account_id text not null,
                kind text not null,
                value text not null,
                action text not null,
                enabled integer not null default 1,
                created_at text default current_timestamp,
                updated_at text default current_timestamp,
                unique(account_id, kind, value, action)
            )
            """
        )


def list_rules(account_id: str) -> list[EmailRule]:
    ensure_email_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        rows = connection.execute(
            """
            select id, account_id, kind, value, action, enabled, created_at, updated_at
            from email_rules
            where account_id = ?
            order by created_at desc, id desc
            """,
            (account_id,),
        ).fetchall()
    return [row_to_rule(row) for row in rows]


def upsert_rule(account_id: str, *, kind: str, value: str, action: str = "trash", enabled: bool = True) -> EmailRule:
    ensure_email_database()
    clean_kind = kind.strip().casefold()
    clean_value = value.strip().casefold()
    clean_action = action.strip().casefold()
    if clean_kind not in {"sender", "domain"}:
        raise ValueError("Rule kind must be sender or domain.")
    if clean_action != "trash":
        raise ValueError("Only trash rules are supported.")
    if not clean_value:
        raise ValueError("Rule value is required.")
    with db_connection(GLOBAL_DB_PATH) as connection:
        connection.execute(
            """
            insert into email_rules (account_id, kind, value, action, enabled, created_at, updated_at)
            values (?, ?, ?, ?, ?, current_timestamp, current_timestamp)
            on conflict(account_id, kind, value, action) do update set enabled = excluded.enabled, updated_at = current_timestamp
            """,
            (account_id, clean_kind, clean_value, clean_action, 1 if enabled else 0),
        )
        row = connection.execute(
            """
            select id, account_id, kind, value, action, enabled, created_at, updated_at
            from email_rules
            where account_id = ? and kind = ? and value = ? and action = ?
            """,
            (account_id, clean_kind, clean_value, clean_action),
        ).fetchone()
    if row is None:
        raise ValueError("Could not save email rule.")
    return row_to_rule(row)


def delete_rule(account_id: str, rule_id: int) -> bool:
    ensure_email_database()
    with db_connection(GLOBAL_DB_PATH) as connection:
        cursor = connection.execute("delete from email_rules where account_id = ? and id = ?", (account_id, rule_id))
        return cursor.rowcount > 0


def row_to_rule(row: object) -> EmailRule:
    values = list(row)  # sqlite Row and tuple both work here.
    return EmailRule(
        id=int(values[0]),
        account_id=str(values[1] or ""),
        kind=str(values[2] or ""),
        value=str(values[3] or ""),
        action=str(values[4] or ""),
        enabled=bool(values[5]),
        created_at=str(values[6] or ""),
        updated_at=str(values[7] or ""),
    )
