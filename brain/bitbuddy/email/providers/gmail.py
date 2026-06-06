from __future__ import annotations

import base64
import concurrent.futures
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ...calendar.secrets import get_credentials, put_credentials
from ...config import EmailConfig
from ..models import EmailMessage, Mailbox

GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SYSTEM_LABEL_ALIASES = {
    "inbox": "INBOX",
    "sent": "SENT",
    "sent mail": "SENT",
    "draft": "DRAFT",
    "drafts": "DRAFT",
    "spam": "SPAM",
    "junk": "SPAM",
    "trash": "TRASH",
    "bin": "TRASH",
    "deleted": "TRASH",
    "important": "IMPORTANT",
    "starred": "STARRED",
    "unread": "UNREAD",
    "forums": "CATEGORY_FORUMS",
    "updates": "CATEGORY_UPDATES",
    "personal": "CATEGORY_PERSONAL",
    "promotions": "CATEGORY_PROMOTIONS",
    "social": "CATEGORY_SOCIAL",
}


class GmailProvider:
    def __init__(self, config: EmailConfig) -> None:
        self.config = config

    def list_mailboxes(self) -> list[Mailbox]:
        data = self._request("GET", "/users/me/labels")
        labels = data.get("labels") if isinstance(data, dict) else []
        if not isinstance(labels, list):
            return []
        mailboxes: list[Mailbox] = []
        for item in labels:
            if not isinstance(item, dict):
                continue
            label_id = str(item.get("id") or "")
            name = str(item.get("name") or label_id)
            if label_id:
                mailboxes.append(Mailbox(name=label_id, flags=[name], delimiter="/"))
        return mailboxes

    def list_messages(self, *, mailbox: str, limit: int = 20) -> list[EmailMessage]:
        label = normalize_gmail_label(mailbox or self.config.default_mailbox or "INBOX")
        query = urllib.parse.urlencode({"maxResults": max(1, min(100, limit)), "labelIds": label})
        data = self._request("GET", f"/users/me/messages?{query}")
        return self._messages_from_list(data, mailbox=label)

    def search_messages(self, *, query: str, mailbox: str, limit: int = 20) -> list[EmailMessage]:
        params: dict[str, object] = {"maxResults": max(1, min(100, limit)), "q": query.strip()}
        label = normalize_gmail_label(mailbox or self.config.default_mailbox or "INBOX")
        if label:
            params["labelIds"] = label
        data = self._request("GET", f"/users/me/messages?{urllib.parse.urlencode(params)}")
        return self._messages_from_list(data, mailbox=label)

    def read_message(self, *, mailbox: str, message_id: str) -> EmailMessage:
        if not message_id:
            raise ValueError("message_id is required.")
        label = normalize_gmail_label(mailbox or self.config.default_mailbox or "INBOX")
        data = self._request("GET", f"/users/me/messages/{urllib.parse.quote(message_id)}?format=full")
        return gmail_message_to_email(data, mailbox=label, include_body=True)

    def trash_message(self, *, mailbox: str, message_id: str) -> EmailMessage:
        if not message_id:
            raise ValueError("message_id is required.")
        label = normalize_gmail_label(mailbox or self.config.default_mailbox or "INBOX")
        try:
            data = self._request("POST", f"/users/me/messages/{urllib.parse.quote(message_id)}/trash")
        except ValueError as error:
            message = str(error)
            if "insufficientPermissions" in message or "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in message:
                raise ValueError("Gmail trash access requires reconnecting Gmail in Settings to grant the Gmail modify scope.") from error
            raise
        return gmail_message_to_email(data, mailbox=label, include_body=False)

    def _messages_from_list(self, data: dict[str, Any], *, mailbox: str) -> list[EmailMessage]:
        messages = data.get("messages") if isinstance(data, dict) else []
        if not isinstance(messages, list):
            return []
        message_ids: list[str] = []
        for item in messages:
            if not isinstance(item, dict):
                continue
            message_id = str(item.get("id") or "")
            if not message_id:
                continue
            message_ids.append(message_id)
        if not message_ids:
            return []
        worker_count = min(8, len(message_ids))
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            return list(executor.map(lambda message_id: self._fetch_message_metadata(message_id, mailbox=mailbox), message_ids))

    def _fetch_message_metadata(self, message_id: str, *, mailbox: str) -> EmailMessage:
        message = self._request("GET", f"/users/me/messages/{urllib.parse.quote(message_id)}?format=metadata&metadataHeaders=Subject&metadataHeaders=From&metadataHeaders=To&metadataHeaders=Date")
        return gmail_message_to_email(message, mailbox=mailbox, include_body=False)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        token = gmail_access_token(self.config)
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            f"{GMAIL_API}{path}",
            data=body,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            raise ValueError(f"Gmail API request failed: {detail or error}") from error
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"Gmail API request failed: {error}") from error


def normalize_gmail_label(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "INBOX"
    normalized = " ".join(raw.replace("_", " ").replace("-", " ").split()).casefold()
    return GMAIL_SYSTEM_LABEL_ALIASES.get(normalized, raw)


def gmail_access_token(config: EmailConfig) -> str:
    tokens = get_credentials(config.gmail_token_ref)
    access_token = tokens.get("access_token", "")
    expires_at = int(float(tokens.get("expires_at", "0") or 0))
    if access_token and expires_at > int(time.time()) + 60:
        return access_token
    refresh_token = tokens.get("refresh_token", "")
    if not refresh_token:
        raise ValueError("Gmail is not connected. Connect Gmail in Settings first.")
    client = get_credentials(config.gmail_credentials_ref)
    client_secret = client.get("client_secret", "")
    if not config.gmail_client_id or not client_secret:
        raise ValueError("Gmail OAuth client ID/secret is not configured.")
    payload_data = {
        "grant_type": "refresh_token",
        "client_id": config.gmail_client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }
    payload = urllib.parse.urlencode(payload_data).encode("utf-8")
    request = urllib.request.Request(GOOGLE_TOKEN_URL, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:500]
        raise ValueError(f"Gmail token refresh failed: {detail or error}") from error
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Gmail token refresh failed: {error}") from error
    next_access_token = str(data.get("access_token") or "")
    expires_in = int(data.get("expires_in") or 0)
    if not next_access_token:
        raise ValueError("Gmail token refresh did not return an access token.")
    put_credentials(
        config.gmail_token_ref,
        {
            **tokens,
            "access_token": next_access_token,
            "expires_at": str(int(time.time()) + max(0, expires_in)),
        },
    )
    return next_access_token


def gmail_message_to_email(data: dict[str, Any], *, mailbox: str, include_body: bool) -> EmailMessage:
    headers = gmail_headers(data)
    body = gmail_body(data.get("payload") if isinstance(data, dict) else {}) if include_body else ""
    snippet = str(data.get("snippet") or "")
    return EmailMessage(
        id=str(data.get("id") or ""),
        mailbox=mailbox,
        subject=headers.get("subject", ""),
        from_addr=headers.get("from", ""),
        to_addrs=[addr.strip() for addr in headers.get("to", "").split(",") if addr.strip()],
        date=headers.get("date", ""),
        snippet=snippet or body[:260],
        flags=[str(label) for label in data.get("labelIds", []) if isinstance(label, str)],
        body=body,
    )


def gmail_headers(data: dict[str, Any]) -> dict[str, str]:
    payload = data.get("payload") if isinstance(data, dict) else {}
    rows = payload.get("headers") if isinstance(payload, dict) else []
    headers: dict[str, str] = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                headers[str(row.get("name") or "").casefold()] = str(row.get("value") or "")
    return headers


def gmail_body(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    mime_type = str(payload.get("mimeType") or "")
    body = payload.get("body") if isinstance(payload.get("body"), dict) else {}
    data = body.get("data") if isinstance(body, dict) else None
    if data and mime_type in {"text/plain", "text/html"}:
        text = decode_gmail_data(str(data))
        return strip_html(text) if mime_type == "text/html" else text.strip()
    parts = payload.get("parts")
    if isinstance(parts, list):
        html_parts: list[str] = []
        for part in parts:
            text = gmail_body(part)
            if text and isinstance(part, dict) and str(part.get("mimeType") or "") == "text/plain":
                return text
            if text:
                html_parts.append(text)
        return "\n\n".join(html_parts).strip()
    return ""


def decode_gmail_data(value: str) -> str:
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")


def strip_html(value: str) -> str:
    import re

    return " ".join(re.sub(r"<[^>]+>", " ", value).split())
