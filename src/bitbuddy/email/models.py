from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Mailbox:
    name: str
    flags: list[str] = field(default_factory=list)
    delimiter: str = "/"
    messages_total: int | None = None
    messages_unread: int | None = None
    threads_total: int | None = None
    threads_unread: int | None = None


@dataclass(frozen=True)
class EmailMessagePage:
    messages: list["EmailMessage"]
    next_page_token: str = ""
    result_size_estimate: int | None = None


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
    return {
        "name": mailbox.name,
        "flags": mailbox.flags,
        "delimiter": mailbox.delimiter,
        "messages_total": mailbox.messages_total,
        "messages_unread": mailbox.messages_unread,
        "threads_total": mailbox.threads_total,
        "threads_unread": mailbox.threads_unread,
    }


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


def message_page_to_json(page: EmailMessagePage) -> dict[str, object]:
    return {
        "messages": [message_to_json(message) for message in page.messages],
        "next_page_token": page.next_page_token,
        "result_size_estimate": page.result_size_estimate,
    }


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
