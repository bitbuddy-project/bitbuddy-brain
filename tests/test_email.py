from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import urllib.parse
import urllib.error
import urllib.request
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "brain"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-email-test-")

from bitbuddy.config import load_config, parse_email_config, update_email_config, write_config  # noqa: E402
from bitbuddy.auth import API_TOKEN_HEADER, get_api_token  # noqa: E402
from bitbuddy.http_api import BitBuddyRequestHandler, GMAIL_AUTH_FLOWS, exchange_gmail_code, start_gmail_login  # noqa: E402
from bitbuddy.calendar.secrets import put_credentials  # noqa: E402
from bitbuddy.email.permissions import EmailPermissionRequired, all_permissions, permission_state, require_permission, set_permission  # noqa: E402
from bitbuddy.email.models import EmailMessage, mailbox_to_json, message_page_to_json  # noqa: E402
from bitbuddy.email.providers.gmail import GmailProvider, gmail_access_token, gmail_message_to_email, normalize_gmail_label  # noqa: E402
from bitbuddy.email.store import ensure_email_database, list_rules, upsert_rule  # noqa: E402
from bitbuddy.paths import GLOBAL_DB_PATH  # noqa: E402
from bitbuddy.prompt_builder import email_capability_context  # noqa: E402
from bitbuddy.projects.routing import clean_model_thinking_text  # noqa: E402
from bitbuddy.toolbox.base import ToolDefinition  # noqa: E402
from bitbuddy.toolbox.handlers import email_recent_messages_tool, email_tool_limit, email_trash_message_tool  # noqa: E402


class EmailTest(unittest.TestCase):
    def setUp(self) -> None:
        ensure_email_database()
        GMAIL_AUTH_FLOWS.clear()
        with sqlite3.connect(GLOBAL_DB_PATH) as connection:
            connection.execute("delete from email_permissions")
            connection.execute("delete from email_rules")

    def test_email_config_parses_imap_defaults(self) -> None:
        config = parse_email_config({"enabled": True, "email_address": "me@example.com", "imap_host": "imap.example.com"})

        self.assertTrue(config.enabled)
        self.assertEqual(config.provider, "imap")
        self.assertEqual(config.imap_port, 993)
        self.assertEqual(config.imap_security, "ssl")
        self.assertEqual(config.default_mailbox, "INBOX")
        self.assertEqual(config.tool_message_limit, 10)

    def test_email_config_allows_large_preview_and_tool_limits(self) -> None:
        config = parse_email_config({"max_preview_messages": 5000, "tool_message_limit": 750})

        self.assertEqual(config.max_preview_messages, 5000)
        self.assertEqual(config.tool_message_limit, 750)

    def test_update_email_config_persists_tool_message_limit(self) -> None:
        write_config("none", "", "")
        update_email_config({"enabled": True, "provider": "imap", "tool_message_limit": 25, "max_preview_messages": 250})

        config = load_config().email

        self.assertEqual(config.tool_message_limit, 25)
        self.assertEqual(config.max_preview_messages, 250)

    def test_email_tool_limit_returns_configured_limit(self) -> None:
        write_config("none", "", "")
        update_email_config({"enabled": True, "provider": "imap", "tool_message_limit": 3})

        self.assertEqual(email_tool_limit(99), 3)
        self.assertEqual(email_tool_limit(2), 3)
        self.assertEqual(email_tool_limit(), 3)

    def test_email_recent_messages_tool_uses_configured_limit(self) -> None:
        write_config("none", "", "")
        update_email_config({"enabled": True, "provider": "imap", "tool_message_limit": 2})
        seen: dict[str, int] = {}

        def fake_list_messages(*, mailbox: str = "", limit: int = 20) -> list[EmailMessage]:
            seen["limit"] = limit
            return [EmailMessage(id=str(index), mailbox="INBOX", subject=f"Message {index}", from_addr="a@example.com", to_addrs=[], date="", snippet="") for index in range(limit)]

        definition = ToolDefinition("email_recent_messages", "", {"type": "object"}, max_chars=4000)
        with patch("bitbuddy.toolbox.handlers.email_list_messages", fake_list_messages):
            result = email_recent_messages_tool({"limit": 99}, definition)

        self.assertTrue(result.ok)
        self.assertEqual(seen["limit"], 2)
        self.assertIn("Tool visibility limit is 2", result.summary)

    def test_email_trash_message_tool_says_trash_not_delete(self) -> None:
        message = EmailMessage(id="msg-1", mailbox="INBOX", subject="Old mail", from_addr="a@example.com", to_addrs=[], date="", snippet="")
        definition = ToolDefinition("email_trash_message", "", {"type": "object"}, max_chars=4000)

        with patch("bitbuddy.toolbox.handlers.email_trash_message", return_value=message):
            result = email_trash_message_tool({"message_id": "msg-1", "mailbox": "INBOX"}, definition)

        self.assertTrue(result.ok)
        self.assertIn("to Trash", result.content)
        self.assertIn("not permanent deletion", result.content)
        self.assertEqual(result.arguments_summary["action"], "trash_not_permanent_delete")

    def test_email_config_parses_gmail_oauth_fields(self) -> None:
        config = parse_email_config(
            {
                "enabled": True,
                "provider": "gmail",
                "email_address": "me@example.com",
                "gmail_oauth_mode": "web_secret",
                "gmail_client_id": "client-id.apps.googleusercontent.com",
                "gmail_credentials_ref": "email:gmail:me@example.com:client",
                "gmail_token_ref": "email:gmail:me@example.com:tokens",
            }
        )

        self.assertEqual(config.provider, "gmail")
        self.assertEqual(config.gmail_oauth_mode, "web_secret")
        self.assertEqual(config.gmail_client_id, "client-id.apps.googleusercontent.com")
        self.assertEqual(config.gmail_credentials_ref, "email:gmail:me@example.com:client")
        self.assertEqual(config.gmail_token_ref, "email:gmail:me@example.com:tokens")

    def test_gmail_oauth_mode_defaults_to_desktop_pkce(self) -> None:
        config = parse_email_config({"provider": "gmail"})

        self.assertEqual(config.gmail_oauth_mode, "desktop_pkce")
        self.assertEqual(config.gmail_redirect_uri, "http://127.0.0.1:8787/email/gmail/callback")

    def test_gmail_full_mail_access_defaults_off(self) -> None:
        config = parse_email_config({"provider": "gmail"})

        self.assertFalse(config.gmail_full_mail_access)

    def test_gmail_oauth_mode_preserves_legacy_web_secret_config(self) -> None:
        config = parse_email_config({"provider": "gmail", "gmail_credentials_ref": "email:gmail:me@example.com:client"})

        self.assertEqual(config.gmail_oauth_mode, "web_secret")

    def test_invalid_gmail_oauth_mode_falls_back_to_desktop_pkce(self) -> None:
        config = parse_email_config({"provider": "gmail", "gmail_oauth_mode": "server_secret"})

        self.assertEqual(config.gmail_oauth_mode, "desktop_pkce")

    def test_desktop_pkce_gmail_login_does_not_require_client_secret(self) -> None:
        write_config("none", "", "")
        update_email_config(
            {
                "enabled": True,
                "provider": "gmail",
                "email_address": "me@example.com",
                "gmail_oauth_mode": "desktop_pkce",
                "gmail_client_id": "client-id.apps.googleusercontent.com",
                "gmail_token_ref": "email:gmail:me@example.com:tokens",
            }
        )

        status = start_gmail_login(force=True)

        self.assertTrue(status["ok"])
        self.assertIn("auth_url", status)
        self.assertIn("code_challenge=", status["auth_url"])
        self.assertIn("code_challenge_method=S256", status["auth_url"])
        self.assertEqual(status["oauth_mode"], "desktop_pkce")
        params = urllib.parse.parse_qs(urllib.parse.urlparse(status["auth_url"]).query)
        self.assertEqual(params["redirect_uri"], ["http://127.0.0.1:8787/email/gmail/callback"])
        self.assertEqual(params["login_hint"], ["me@example.com"])
        self.assertEqual(params["prompt"], ["consent"])

    def test_gmail_login_can_request_full_mail_scope(self) -> None:
        write_config("none", "", "")
        update_email_config(
            {
                "enabled": True,
                "provider": "gmail",
                "email_address": "me@example.com",
                "gmail_oauth_mode": "desktop_pkce",
                "gmail_client_id": "client-id.apps.googleusercontent.com",
                "gmail_token_ref": "email:gmail:me@example.com:tokens",
                "gmail_full_mail_access": True,
            }
        )

        status = start_gmail_login(force=True)

        params = urllib.parse.parse_qs(urllib.parse.urlparse(status["auth_url"]).query)
        self.assertEqual(params["scope"], ["https://mail.google.com/"])

    def test_legacy_web_gmail_login_requires_client_secret(self) -> None:
        write_config("none", "", "")
        update_email_config(
            {
                "enabled": True,
                "provider": "gmail",
                "email_address": "me@example.com",
                "gmail_oauth_mode": "web_secret",
                "gmail_client_id": "client-id.apps.googleusercontent.com",
                "gmail_credentials_ref": "email:gmail:legacy-login@example.com:client",
                "gmail_token_ref": "email:gmail:legacy-login@example.com:tokens",
            }
        )

        status = start_gmail_login(force=True)

        self.assertFalse(status["ok"])
        self.assertIn("client secret", status["message"])

    def test_desktop_pkce_gmail_token_refresh_does_not_require_client_secret(self) -> None:
        config = parse_email_config(
            {
                "provider": "gmail",
                "gmail_oauth_mode": "desktop_pkce",
                "gmail_client_id": "client-id.apps.googleusercontent.com",
                "gmail_credentials_ref": "email:gmail:no-secret@example.com:client",
                "gmail_token_ref": "email:gmail:no-secret@example.com:tokens",
            }
        )
        put_credentials(config.gmail_token_ref, {"access_token": "expired-token", "refresh_token": "refresh-token", "expires_at": "0"})
        seen: dict[str, str] = {}

        class TokenResponse:
            def __enter__(self) -> "TokenResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b'{"access_token":"next-token","expires_in":3600}'

        def fake_urlopen(request: object, timeout: int = 0) -> TokenResponse:
            seen["payload"] = getattr(request, "data", b"").decode("utf-8")
            seen["timeout"] = str(timeout)
            return TokenResponse()

        with patch("bitbuddy.email.providers.gmail.urllib.request.urlopen", fake_urlopen):
            token = gmail_access_token(config)

        self.assertEqual(token, "next-token")
        payload = urllib.parse.parse_qs(seen["payload"])
        self.assertEqual(payload["grant_type"], ["refresh_token"])
        self.assertEqual(payload["client_id"], ["client-id.apps.googleusercontent.com"])
        self.assertEqual(payload["refresh_token"], ["refresh-token"])
        self.assertNotIn("client_secret", payload)

    def test_desktop_pkce_gmail_token_refresh_sends_saved_client_secret(self) -> None:
        config = parse_email_config(
            {
                "provider": "gmail",
                "gmail_oauth_mode": "desktop_pkce",
                "gmail_client_id": "client-id.apps.googleusercontent.com",
                "gmail_credentials_ref": "email:gmail:secret@example.com:client",
                "gmail_token_ref": "email:gmail:secret@example.com:tokens",
            }
        )
        put_credentials(config.gmail_credentials_ref, {"client_secret": "saved-secret"})
        put_credentials(config.gmail_token_ref, {"access_token": "expired-token", "refresh_token": "refresh-token", "expires_at": "0"})
        seen: dict[str, str] = {}

        class TokenResponse:
            def __enter__(self) -> "TokenResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b'{"access_token":"next-token","expires_in":3600}'

        def fake_urlopen(request: object, timeout: int = 0) -> TokenResponse:
            seen["payload"] = getattr(request, "data", b"").decode("utf-8")
            return TokenResponse()

        with patch("bitbuddy.email.providers.gmail.urllib.request.urlopen", fake_urlopen):
            token = gmail_access_token(config)

        self.assertEqual(token, "next-token")
        payload = urllib.parse.parse_qs(seen["payload"])
        self.assertEqual(payload["client_secret"], ["saved-secret"])

    def test_desktop_pkce_gmail_code_exchange_sends_saved_client_secret(self) -> None:
        write_config("none", "", "")
        update_email_config(
            {
                "enabled": True,
                "provider": "gmail",
                "email_address": "me@example.com",
                "gmail_oauth_mode": "desktop_pkce",
                "gmail_client_id": "client-id.apps.googleusercontent.com",
                "gmail_credentials_ref": "email:gmail:me@example.com:client",
                "gmail_token_ref": "email:gmail:me@example.com:tokens",
            }
        )
        put_credentials("email:gmail:me@example.com:client", {"client_secret": "saved-secret"})
        start_gmail_login(force=True)
        state = next(iter(GMAIL_AUTH_FLOWS.keys()))
        verifier = GMAIL_AUTH_FLOWS[state]["verifier"]
        seen: dict[str, str] = {}

        class TokenResponse:
            def __enter__(self) -> "TokenResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b'{"access_token":"access-token","refresh_token":"refresh-token","expires_in":3600}'

        def fake_urlopen(request: object, timeout: int = 0) -> TokenResponse:
            seen["payload"] = getattr(request, "data", b"").decode("utf-8")
            return TokenResponse()

        with patch("bitbuddy.http_api.urllib.request.urlopen", fake_urlopen):
            exchange_gmail_code("auth-code", state)

        payload = urllib.parse.parse_qs(seen["payload"])
        self.assertEqual(payload["code_verifier"], [verifier])
        self.assertEqual(payload["client_secret"], ["saved-secret"])

    def test_legacy_web_gmail_token_refresh_requires_client_secret(self) -> None:
        config = parse_email_config(
            {
                "provider": "gmail",
                "gmail_oauth_mode": "web_secret",
                "gmail_client_id": "client-id.apps.googleusercontent.com",
                "gmail_credentials_ref": "email:gmail:legacy@example.com:client",
                "gmail_token_ref": "email:gmail:legacy@example.com:tokens",
            }
        )
        put_credentials(config.gmail_token_ref, {"access_token": "expired-token", "refresh_token": "refresh-token", "expires_at": "0"})

        with self.assertRaisesRegex(ValueError, "client secret"):
            gmail_access_token(config)

    def test_legacy_web_gmail_token_refresh_sends_saved_client_secret(self) -> None:
        config = parse_email_config(
            {
                "provider": "gmail",
                "gmail_oauth_mode": "web_secret",
                "gmail_client_id": "client-id.apps.googleusercontent.com",
                "gmail_credentials_ref": "email:gmail:web@example.com:client",
                "gmail_token_ref": "email:gmail:web@example.com:tokens",
            }
        )
        put_credentials(config.gmail_credentials_ref, {"client_secret": "saved-secret"})
        put_credentials(config.gmail_token_ref, {"access_token": "expired-token", "refresh_token": "refresh-token", "expires_at": "0"})
        seen: dict[str, str] = {}

        class TokenResponse:
            def __enter__(self) -> "TokenResponse":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self) -> bytes:
                return b'{"access_token":"next-token","expires_in":3600}'

        def fake_urlopen(request: object, timeout: int = 0) -> TokenResponse:
            seen["payload"] = getattr(request, "data", b"").decode("utf-8")
            return TokenResponse()

        with patch("bitbuddy.email.providers.gmail.urllib.request.urlopen", fake_urlopen):
            token = gmail_access_token(config)

        self.assertEqual(token, "next-token")
        payload = urllib.parse.parse_qs(seen["payload"])
        self.assertEqual(payload["client_secret"], ["saved-secret"])

    def test_gmail_message_maps_to_email_message(self) -> None:
        message = gmail_message_to_email(
            {
                "id": "msg-1",
                "labelIds": ["INBOX"],
                "snippet": "Short snippet",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Appointment"},
                        {"name": "From", "value": "Clinic <clinic@example.com>"},
                        {"name": "To", "value": "me@example.com"},
                        {"name": "Date", "value": "Mon, 1 Jan 2026 10:00:00 +0000"},
                    ]
                },
            },
            mailbox="INBOX",
            include_body=False,
        )

        self.assertEqual(message.id, "msg-1")
        self.assertEqual(message.subject, "Appointment")
        self.assertEqual(message.from_addr, "Clinic <clinic@example.com>")
        self.assertEqual(message.snippet, "Short snippet")

    def test_gmail_label_aliases_accept_display_names(self) -> None:
        self.assertEqual(normalize_gmail_label("Inbox"), "INBOX")
        self.assertEqual(normalize_gmail_label("drafts"), "DRAFT")
        self.assertEqual(normalize_gmail_label("Sent Mail"), "SENT")
        self.assertEqual(normalize_gmail_label("Label_5"), "Label_5")

    def test_gmail_mailbox_counts_are_exposed(self) -> None:
        config = parse_email_config({"provider": "gmail", "gmail_client_id": "client", "gmail_token_ref": "tokens"})
        provider = GmailProvider(config)
        provider._request = lambda _method, _path, _payload=None: {  # type: ignore[method-assign]
            "labels": [
                {
                    "id": "INBOX",
                    "name": "Inbox",
                    "messagesTotal": 42,
                    "messagesUnread": 7,
                    "threadsTotal": 30,
                    "threadsUnread": 5,
                }
            ]
        }

        mailbox = provider.list_mailboxes()[0]
        data = mailbox_to_json(mailbox)

        self.assertEqual(data["messages_total"], 42)
        self.assertEqual(data["messages_unread"], 7)
        self.assertEqual(data["threads_total"], 30)
        self.assertEqual(data["threads_unread"], 5)

    def test_gmail_mailbox_counts_fall_back_to_label_detail(self) -> None:
        config = parse_email_config({"provider": "gmail", "gmail_client_id": "client", "gmail_token_ref": "tokens"})
        provider = GmailProvider(config)

        def fake_request(_method: str, path: str, _payload: object = None) -> dict[str, object]:
            if path == "/users/me/labels":
                return {"labels": [{"id": "INBOX", "name": "Inbox"}]}
            self.assertEqual(path, "/users/me/labels/INBOX")
            return {"id": "INBOX", "messagesTotal": 42, "messagesUnread": 7}

        provider._request = fake_request  # type: ignore[method-assign]

        mailbox = provider.list_mailboxes()[0]

        self.assertEqual(mailbox.messages_total, 42)
        self.assertEqual(mailbox.messages_unread, 7)

    def test_gmail_message_pages_use_next_page_token(self) -> None:
        config = parse_email_config({"provider": "gmail", "gmail_client_id": "client", "gmail_token_ref": "tokens"})
        provider = GmailProvider(config)
        paths: list[str] = []

        def fake_request(_method: str, path: str, _payload: object = None) -> dict[str, object]:
            paths.append(path)
            if path.startswith("/users/me/messages?"):
                return {"messages": [{"id": "msg-1"}], "nextPageToken": "next-token", "resultSizeEstimate": 123}
            return {
                "id": "msg-1",
                "labelIds": ["INBOX"],
                "snippet": "Snippet",
                "payload": {"headers": [{"name": "Subject", "value": "Hello"}]},
            }

        provider._request = fake_request  # type: ignore[method-assign]

        page = provider.list_messages_page(mailbox="INBOX", limit=50, page_token="page-2")
        data = message_page_to_json(page)

        self.assertIn("maxResults=50", paths[0])
        self.assertIn("labelIds=INBOX", paths[0])
        self.assertIn("pageToken=page-2", paths[0])
        self.assertEqual(data["next_page_token"], "next-token")
        self.assertEqual(data["result_size_estimate"], 123)
        self.assertEqual(len(data["messages"]), 1)

    def test_gmail_empty_trash_deletes_all_paged_trash_ids(self) -> None:
        config = parse_email_config({"provider": "gmail", "gmail_client_id": "client", "gmail_token_ref": "tokens"})
        provider = GmailProvider(config)
        deleted_batches: list[list[str]] = []

        def fake_request(_method: str, path: str, payload: object = None) -> dict[str, object]:
            if path == "/users/me/messages?maxResults=500&labelIds=TRASH":
                return {"messages": [{"id": "msg-1"}], "nextPageToken": "page-2"}
            if path == "/users/me/messages?maxResults=500&labelIds=TRASH&pageToken=page-2":
                return {"messages": [{"id": "msg-2"}]}
            self.assertEqual(path, "/users/me/messages/batchDelete")
            self.assertIsInstance(payload, dict)
            deleted_batches.append(list(payload.get("ids", [])))  # type: ignore[union-attr]
            return {}

        provider._request = fake_request  # type: ignore[method-assign]

        deleted = provider.empty_trash()

        self.assertEqual(deleted, 2)
        self.assertEqual(deleted_batches, [["msg-1", "msg-2"]])

    def test_gmail_delete_message_uses_permanent_delete_endpoint(self) -> None:
        config = parse_email_config({"provider": "gmail", "gmail_client_id": "client", "gmail_token_ref": "tokens"})
        provider = GmailProvider(config)
        paths: list[str] = []

        def fake_request(method: str, path: str, payload: object = None) -> dict[str, object]:
            paths.append(f"{method} {path}")
            if method == "GET":
                return {
                    "id": "msg-1",
                    "labelIds": ["TRASH"],
                    "snippet": "Trash",
                    "payload": {"headers": [{"name": "Subject", "value": "Delete me"}]},
                }
            self.assertEqual(method, "DELETE")
            self.assertEqual(path, "/users/me/messages/msg-1")
            return {}

        provider._request = fake_request  # type: ignore[method-assign]

        message = provider.delete_message(mailbox="TRASH", message_id="msg-1")

        self.assertEqual(message.id, "msg-1")
        self.assertEqual(paths, ["GET /users/me/messages/msg-1?format=full", "DELETE /users/me/messages/msg-1"])

    def test_http_api_requires_token_for_protected_routes(self) -> None:
        with running_api_server() as base_url:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(f"{base_url}/config", timeout=5)

            self.assertEqual(caught.exception.code, 401)

            request = urllib.request.Request(f"{base_url}/config", headers={API_TOKEN_HEADER: get_api_token()})
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertEqual(response.status, 200)

    def test_http_api_blocks_non_loopback_browser_origins(self) -> None:
        with running_api_server() as base_url:
            request = urllib.request.Request(
                f"{base_url}/config",
                headers={API_TOKEN_HEADER: get_api_token(), "Origin": "https://evil.example"},
            )
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=5)

            self.assertEqual(caught.exception.code, 403)

    def test_empty_trash_requires_server_side_confirmation(self) -> None:
        with running_api_server() as base_url:
            request = urllib.request.Request(
                f"{base_url}/email/trash/empty",
                data=b"{}",
                headers={API_TOKEN_HEADER: get_api_token(), "Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=5)

            self.assertEqual(caught.exception.code, 400)

    def test_thinking_cleanup_strips_system_reminders(self) -> None:
        clean = clean_model_thinking_text("before\n<system-reminder>secret\nmore</system-reminder>\nafter")

        self.assertNotIn("system-reminder", clean)
        self.assertNotIn("secret", clean)
        self.assertIn("before", clean)
        self.assertIn("after", clean)

    def test_prompt_email_context_mentions_connected_gmail(self) -> None:
        config = type(
            "Config",
            (),
            {
                "email": parse_email_config(
                    {
                        "enabled": True,
                        "provider": "gmail",
                        "email_address": "me@example.com",
                        "gmail_token_ref": "missing-test-token-ref",
                    }
                )
            },
        )()

        context = email_capability_context(config)

        self.assertIn("Email is enabled with provider gmail", context)

    def test_prompt_email_context_mentions_tool_limit_and_trash_semantics(self) -> None:
        config = type(
            "Config",
            (),
            {
                "email": parse_email_config(
                    {
                        "enabled": True,
                        "provider": "imap",
                        "email_address": "me@example.com",
                        "tool_message_limit": 7,
                    }
                )
            },
        )()

        context = email_capability_context(config)

        self.assertIn("at most 7 message(s)", context)
        self.assertIn("moves mail to Trash", context)
        self.assertIn("not permanent delete", context)

    def test_email_permissions_default_to_ask(self) -> None:
        self.assertEqual(permission_state("me@example.com", "read"), "ask")
        self.assertEqual(permission_state("me@example.com", "trash"), "ask")
        with self.assertRaises(EmailPermissionRequired):
            require_permission("me@example.com", "read")

    def test_email_permission_can_be_granted(self) -> None:
        permissions = set_permission("me@example.com", "read", "granted")

        self.assertEqual(permissions["read"], "granted")
        self.assertEqual(all_permissions("me@example.com")["search"], "ask")
        require_permission("me@example.com", "read")

    def test_email_sender_trash_rule_can_be_saved(self) -> None:
        rule = upsert_rule("me@example.com", kind="sender", value="Spam@Example.com", action="trash", enabled=True)

        self.assertEqual(rule.kind, "sender")
        self.assertEqual(rule.value, "spam@example.com")
        self.assertEqual(rule.action, "trash")
        self.assertTrue(rule.enabled)
        self.assertEqual(len(list_rules("me@example.com")), 1)


if __name__ == "__main__":
    unittest.main()


class running_api_server:
    def __enter__(self) -> str:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), BitBuddyRequestHandler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_port}"

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
