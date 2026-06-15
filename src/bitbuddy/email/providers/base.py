from __future__ import annotations

from typing import Protocol

from ..models import EmailMessage, Mailbox


class EmailProvider(Protocol):
    def list_mailboxes(self) -> list[Mailbox]: ...

    def list_messages(self, *, mailbox: str, limit: int = 20) -> list[EmailMessage]: ...

    def search_messages(self, *, query: str, mailbox: str, limit: int = 20) -> list[EmailMessage]: ...

    def read_message(self, *, mailbox: str, message_id: str) -> EmailMessage: ...

    def trash_message(self, *, mailbox: str, message_id: str) -> EmailMessage: ...
