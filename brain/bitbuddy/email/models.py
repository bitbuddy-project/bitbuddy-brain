from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Mailbox:
    name: str
    flags: list[str] = field(default_factory=list)
    delimiter: str = "/"


@dataclass(frozen=True)
class EmailMessage:
    id: str
    mailbox: str
    subject: str
    from_addr: str
    to_addrs: list[str]
    date: str
    snippet: str
    flags: list[str] = field(default_factory=list)
    body: str = ""


@dataclass(frozen=True)
class EmailRule:
    id: int
    account_id: str
    kind: str
    value: str
    action: str
    enabled: bool
    created_at: str = ""
    updated_at: str = ""


def mailbox_to_json(mailbox: Mailbox) -> dict[str, object]:
    return {"name": mailbox.name, "flags": mailbox.flags, "delimiter": mailbox.delimiter}


def message_to_json(message: EmailMessage, *, include_body: bool = False) -> dict[str, object]:
    data: dict[str, object] = {
        "id": message.id,
        "mailbox": message.mailbox,
        "subject": message.subject,
        "from_addr": message.from_addr,
        "to_addrs": message.to_addrs,
        "date": message.date,
        "snippet": message.snippet,
        "flags": message.flags,
    }
    if include_body:
        data["body"] = message.body
    return data


def rule_to_json(rule: EmailRule) -> dict[str, object]:
    return {
        "id": rule.id,
        "account_id": rule.account_id,
        "kind": rule.kind,
        "value": rule.value,
        "action": rule.action,
        "enabled": rule.enabled,
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
    }
