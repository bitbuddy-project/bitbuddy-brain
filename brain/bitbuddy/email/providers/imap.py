from __future__ import annotations

import email
import imaplib
import re
from email.header import decode_header, make_header
from email.message import Message

from ...calendar.secrets import get_credentials
from ...config import EmailConfig
from ..models import EmailMessage, EmailMessagePage, Mailbox


class ImapProvider:
    def __init__(self, config: EmailConfig) -> None:
        self.config = config

    def list_mailboxes(self) -> list[Mailbox]:
        with self._connect() as client:
            status, rows = client.list()
            if status != "OK":
                raise ValueError("Could not list IMAP mailboxes.")
            return [box for row in rows or [] if (box := parse_mailbox(row)) is not None]

    def list_messages(self, *, mailbox: str, limit: int = 20) -> list[EmailMessage]:
        return self.list_messages_page(mailbox=mailbox, limit=limit).messages


    def list_messages_page(self, *, mailbox: str, limit: int = 20, page_token: str = "") -> EmailMessagePage:
        with self._connect() as client:
            self._select(client, mailbox)
            all_uids = self._search_uids(client, "ALL")
            all_uids.reverse()
            offset = parse_offset_token(page_token)
            clean_limit = max(1, limit)
            uids = all_uids[offset:offset + clean_limit]
            next_offset = offset + clean_limit
            next_token = str(next_offset) if next_offset < len(all_uids) else ""
            return EmailMessagePage(
                messages=[self._fetch_message(client, mailbox, uid, include_body=False) for uid in uids],
                next_page_token=next_token,
                result_size_estimate=len(all_uids),
            )

    def search_messages(self, *, query: str, mailbox: str, limit: int = 20) -> list[EmailMessage]:
        return self.search_messages_page(query=query, mailbox=mailbox, limit=limit).messages


    def search_messages_page(self, *, query: str, mailbox: str, limit: int = 20, page_token: str = "") -> EmailMessagePage:
        clean = query.strip().casefold()
        if not clean:
            return self.list_messages_page(mailbox=mailbox, limit=limit, page_token=page_token)
        with self._connect() as client:
            self._select(client, mailbox)
            uids = self._search_uids(client, "ALL")[-100:]
            uids.reverse()
            matches: list[EmailMessage] = []
            offset = parse_offset_token(page_token)
            matched_count = 0
            for uid in uids:
                message = self._fetch_message(client, mailbox, uid, include_body=False)
                haystack = " ".join([message.subject, message.from_addr, message.snippet]).casefold()
                if clean not in haystack:
                    continue
                if matched_count < offset:
                    matched_count += 1
                    continue
                matches.append(message)
                matched_count += 1
                if len(matches) >= max(1, limit):
                    break
            next_token = str(offset + len(matches)) if len(matches) >= max(1, limit) else ""
            return EmailMessagePage(messages=matches, next_page_token=next_token)

    def read_message(self, *, mailbox: str, message_id: str) -> EmailMessage:
        with self._connect() as client:
            self._select(client, mailbox)
            return self._fetch_message(client, mailbox, message_id.encode("ascii", errors="ignore"), include_body=True)

    def trash_message(self, *, mailbox: str, message_id: str) -> EmailMessage:
        uid = message_id.encode("ascii", errors="ignore")
        with self._connect() as client:
            self._select(client, mailbox, readonly=False)
            message = self._fetch_message(client, mailbox, uid, include_body=False)
            trash_mailbox = self._trash_mailbox(client)
            status, _data = client.uid("COPY", uid, trash_mailbox)
            if status != "OK":
                raise ValueError(f"Could not move email message {message_id} to Trash.")
            client.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
            return message

    def delete_message(self, *, mailbox: str, message_id: str) -> EmailMessage:
        uid = message_id.encode("ascii", errors="ignore")
        with self._connect() as client:
            self._select(client, mailbox or self._trash_mailbox(client), readonly=False)
            message = self._fetch_message(client, mailbox, uid, include_body=False)
            status, _data = client.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
            if status != "OK":
                raise ValueError(f"Could not permanently delete email message {message_id}.")
            client.expunge()
            return message

    def empty_trash(self) -> int:
        with self._connect() as client:
            trash_mailbox = self._trash_mailbox(client)
            self._select(client, trash_mailbox, readonly=False)
            uids = self._search_uids(client, "ALL")
            if not uids:
                return 0
            uid_set = b",".join(uids)
            status, _data = client.uid("STORE", uid_set, "+FLAGS", "(\\Deleted)")
            if status != "OK":
                raise ValueError("Could not mark Trash messages for deletion.")
            client.expunge()
            return len(uids)

    def _connect(self) -> imaplib.IMAP4:
        if not self.config.imap_host:
            raise ValueError("IMAP host is not configured.")
        username = self.config.username or self.config.email_address
        password = get_credentials(self.config.credentials_ref).get("password", "")
        if not username or not password:
            raise ValueError("IMAP username/password is not configured.")
        if self.config.imap_security == "ssl":
            client: imaplib.IMAP4 = imaplib.IMAP4_SSL(self.config.imap_host, self.config.imap_port, timeout=20)
        else:
            client = imaplib.IMAP4(self.config.imap_host, self.config.imap_port, timeout=20)
            if self.config.imap_security == "starttls":
                client.starttls()
        client.login(username, password)
        return client

    def _select(self, client: imaplib.IMAP4, mailbox: str, *, readonly: bool = True) -> None:
        status, _data = client.select(mailbox or self.config.default_mailbox or "INBOX", readonly=readonly)
        if status != "OK":
            raise ValueError(f"Could not open mailbox: {mailbox}")

    def _trash_mailbox(self, client: imaplib.IMAP4) -> str:
        mailboxes = self.list_mailboxes()
        names = [mailbox.name for mailbox in mailboxes]
        for candidate in ("Trash", "Deleted Messages", "Deleted", "[Gmail]/Trash", "TRASH"):
            if candidate in names:
                return candidate
        raise ValueError("Could not find an IMAP Trash mailbox.")

    def _search_uids(self, client: imaplib.IMAP4, criteria: str) -> list[bytes]:
        status, data = client.uid("SEARCH", None, criteria)
        if status != "OK" or not data:
            return []
        return [uid for uid in data[0].split() if uid]

    def _fetch_message(self, client: imaplib.IMAP4, mailbox: str, uid: bytes, *, include_body: bool) -> EmailMessage:
        status, data = client.uid("FETCH", uid, "(FLAGS RFC822)")
        if status != "OK" or not data:
            raise ValueError(f"Could not fetch email message {uid.decode(errors='ignore')}.")
        raw = next((part[1] for part in data if isinstance(part, tuple) and len(part) > 1), b"")
        parsed = email.message_from_bytes(raw)
        body = extract_body(parsed)
        snippet = compact(body)[:260]
        return EmailMessage(
            id=uid.decode("ascii", errors="ignore"),
            mailbox=mailbox,
            subject=decode_value(parsed.get("Subject", "")),
            from_addr=decode_value(parsed.get("From", "")),
            to_addrs=[decode_value(addr.strip()) for addr in str(parsed.get("To", "")).split(",") if addr.strip()],
            date=str(parsed.get("Date", "")),
            snippet=snippet,
            flags=parse_flags(data),
            body=body if include_body else "",
        )


def parse_mailbox(row: bytes | str) -> Mailbox | None:
    text = row.decode("utf-8", errors="replace") if isinstance(row, bytes) else str(row)
    match = re.match(r"(?P<flags>\([^)]*\))\s+\"?(?P<delimiter>.*?)\"?\s+(?P<name>.+)$", text)
    if not match:
        return None
    name = match.group("name").strip().strip('"')
    flags = [flag.strip("\\") for flag in match.group("flags").strip("()").split() if flag]
    return Mailbox(name=name, flags=flags, delimiter=match.group("delimiter") or "/")


def parse_flags(data: list[object]) -> list[str]:
    flags: set[str] = set()
    for part in data:
        if isinstance(part, tuple) and part:
            header = part[0].decode("utf-8", errors="ignore") if isinstance(part[0], bytes) else str(part[0])
            match = re.search(r"FLAGS \(([^)]*)\)", header)
            if match:
                flags.update(flag.strip("\\") for flag in match.group(1).split() if flag)
    return sorted(flags)


def parse_offset_token(value: str) -> int:
    try:
        return max(0, int(value or "0"))
    except ValueError:
        return 0


def decode_value(value: str) -> str:
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:
        return str(value or "").strip()


def extract_body(message: Message) -> str:
    if message.is_multipart():
        text_parts: list[str] = []
        for part in message.walk():
            if part.get_content_maintype() == "multipart" or part.get_filename():
                continue
            content_type = part.get_content_type()
            if content_type not in {"text/plain", "text/html"}:
                continue
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if content_type == "text/plain":
                return text.strip()
            text_parts.append(strip_html(text))
        return "\n\n".join(part for part in text_parts if part).strip()
    payload = message.get_payload(decode=True) or b""
    charset = message.get_content_charset() or "utf-8"
    text = payload.decode(charset, errors="replace")
    return strip_html(text) if message.get_content_type() == "text/html" else text.strip()


def strip_html(value: str) -> str:
    return compact(re.sub(r"<[^>]+>", " ", value))


def compact(value: str) -> str:
    return " ".join(str(value or "").split())
