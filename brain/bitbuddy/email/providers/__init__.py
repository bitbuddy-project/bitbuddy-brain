from __future__ import annotations

from ...config import EmailConfig
from .base import EmailProvider
from .gmail import GmailProvider
from .imap import ImapProvider


def get_provider(config: EmailConfig) -> EmailProvider:
    if config.provider == "gmail":
        return GmailProvider(config)
    if config.provider != "imap":
        raise ValueError(f"Email provider '{config.provider}' is not implemented yet.")
    return ImapProvider(config)
