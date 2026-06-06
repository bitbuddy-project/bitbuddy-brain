from __future__ import annotations

from ..config import EmailConfig, load_config
from ..calendar.secrets import get_credentials
from .models import EmailMessage, EmailRule, Mailbox
from .permissions import EmailPermissionRequired, account_id, all_permissions, require_permission
from .providers import get_provider
from .store import delete_rule as delete_rule_store, list_rules as list_rules_store, upsert_rule


def email_account_id(config: EmailConfig | None = None) -> str:
    cfg = config or load_config().email
    return account_id(cfg.email_address or cfg.username)


def email_overview() -> dict[str, object]:
    config = load_config().email
    return {
        "enabled": config.enabled,
        "provider": config.provider,
        "account_id": email_account_id(config),
        "account_label": config.account_label,
        "email_address": config.email_address,
        "imap_host": config.imap_host,
        "imap_port": config.imap_port,
        "imap_security": config.imap_security,
        "username": config.username,
        "gmail_client_id": config.gmail_client_id,
        "gmail_redirect_uri": config.gmail_redirect_uri,
        "default_mailbox": config.default_mailbox,
        "max_preview_messages": config.max_preview_messages,
        "has_password": bool(config.credentials_ref),
        "has_gmail_client_secret": bool(get_credentials(config.gmail_credentials_ref).get("client_secret")),
        "gmail_connected": bool(get_credentials(config.gmail_token_ref).get("refresh_token")),
        "permissions": all_permissions(email_account_id(config)),
    }


def list_mailboxes(*, enforce: bool = True) -> list[Mailbox]:
    config = require_enabled_config()
    if enforce:
        require_permission(email_account_id(config), "read")
    return get_provider(config).list_mailboxes()


def list_messages(*, mailbox: str = "", limit: int = 20, enforce: bool = True) -> list[EmailMessage]:
    config = require_enabled_config()
    if enforce:
        require_permission(email_account_id(config), "read")
    clean_mailbox = mailbox.strip() or config.default_mailbox or "INBOX"
    provider = get_provider(config)
    if should_auto_apply_rules(clean_mailbox):
        try:
            apply_trash_rules(config=config, provider=provider)
        except ValueError:
            pass
    return provider.list_messages(mailbox=clean_mailbox, limit=max(1, min(100, limit)))


def search_messages(*, query: str, mailbox: str = "", limit: int = 20, enforce: bool = True) -> list[EmailMessage]:
    config = require_enabled_config()
    if enforce:
        require_permission(email_account_id(config), "search")
    clean_mailbox = mailbox.strip() or config.default_mailbox or "INBOX"
    return get_provider(config).search_messages(query=query, mailbox=clean_mailbox, limit=max(1, min(100, limit)))


def read_message(*, message_id: str, mailbox: str = "", enforce: bool = True) -> EmailMessage:
    config = require_enabled_config()
    if enforce:
        require_permission(email_account_id(config), "read")
    clean_mailbox = mailbox.strip() or config.default_mailbox or "INBOX"
    clean_id = str(message_id or "").strip()
    if not clean_id:
        raise ValueError("message_id is required.")
    return get_provider(config).read_message(mailbox=clean_mailbox, message_id=clean_id)


def trash_message(*, message_id: str, mailbox: str = "", enforce: bool = True) -> EmailMessage:
    config = require_enabled_config()
    if enforce:
        require_permission(email_account_id(config), "trash")
    clean_mailbox = mailbox.strip() or config.default_mailbox or "INBOX"
    clean_id = str(message_id or "").strip()
    if not clean_id:
        raise ValueError("message_id is required.")
    return get_provider(config).trash_message(mailbox=clean_mailbox, message_id=clean_id)


def list_rules() -> list[EmailRule]:
    config = require_enabled_config()
    return list_rules_store(email_account_id(config))


def create_sender_trash_rule(*, sender: str, apply_existing: bool = False, mailbox: str = "INBOX") -> tuple[EmailRule, int]:
    config = require_enabled_config()
    require_permission(email_account_id(config), "trash")
    clean_sender = sender_address(sender)
    if not clean_sender:
        raise ValueError("sender is required.")
    rule = upsert_rule(email_account_id(config), kind="sender", value=clean_sender, action="trash", enabled=True)
    applied = apply_trash_rules(config=config, provider=get_provider(config), limit=100, mailbox=mailbox) if apply_existing else 0
    return rule, applied


def delete_rule(rule_id: int) -> bool:
    config = require_enabled_config()
    return delete_rule_store(email_account_id(config), rule_id)


def apply_trash_rules(*, config: EmailConfig | None = None, provider: object | None = None, limit: int = 50, mailbox: str = "INBOX") -> int:
    cfg = config or require_enabled_config()
    account = email_account_id(cfg)
    try:
        require_permission(account, "trash")
    except EmailPermissionRequired:
        return 0
    rules = [rule for rule in list_rules_store(account) if rule.enabled and rule.action == "trash"]
    if not rules:
        return 0
    email_provider = provider or get_provider(cfg)
    messages = email_provider.list_messages(mailbox=mailbox or cfg.default_mailbox or "INBOX", limit=max(1, min(100, limit)))
    applied = 0
    for message in messages:
        if not any(rule_matches_message(rule, message) for rule in rules):
            continue
        try:
            email_provider.trash_message(mailbox=message.mailbox or mailbox, message_id=message.id)
            applied += 1
        except ValueError:
            raise
    return applied


def should_auto_apply_rules(mailbox: str) -> bool:
    return (mailbox or "INBOX").strip().casefold() in {"inbox", "inbox".casefold()}


def rule_matches_message(rule: EmailRule, message: EmailMessage) -> bool:
    sender = sender_address(message.from_addr)
    if rule.kind == "sender":
        return sender == rule.value.casefold()
    if rule.kind == "domain" and "@" in sender:
        return sender.rsplit("@", 1)[1] == rule.value.casefold().lstrip("@")
    return False


def sender_address(value: str) -> str:
    raw = str(value or "").strip().casefold()
    if not raw:
        return ""
    if "<" in raw and ">" in raw:
        raw = raw.split("<", 1)[1].split(">", 1)[0].strip()
    return raw


def require_enabled_config() -> EmailConfig:
    config = load_config().email
    if not config.enabled:
        raise ValueError("Email is not enabled. Configure an IMAP account in Settings first.")
    if config.provider not in {"imap", "gmail"}:
        raise ValueError(f"Email provider '{config.provider}' is not implemented yet.")
    return config
