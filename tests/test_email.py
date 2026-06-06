from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "brain"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-email-test-")

from bitbuddy.config import parse_email_config  # noqa: E402
from bitbuddy.email.permissions import EmailPermissionRequired, all_permissions, permission_state, require_permission, set_permission  # noqa: E402
from bitbuddy.email.providers.gmail import gmail_message_to_email, normalize_gmail_label  # noqa: E402
from bitbuddy.email.store import ensure_email_database, list_rules, upsert_rule  # noqa: E402
from bitbuddy.paths import GLOBAL_DB_PATH  # noqa: E402
from bitbuddy.prompt_builder import email_capability_context  # noqa: E402
from bitbuddy.projects.routing import clean_model_thinking_text  # noqa: E402


class EmailTest(unittest.TestCase):
    def setUp(self) -> None:
        ensure_email_database()
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

    def test_email_config_parses_gmail_oauth_fields(self) -> None:
        config = parse_email_config(
            {
                "enabled": True,
                "provider": "gmail",
                "email_address": "me@example.com",
                "gmail_client_id": "client-id.apps.googleusercontent.com",
                "gmail_credentials_ref": "email:gmail:me@example.com:client",
                "gmail_token_ref": "email:gmail:me@example.com:tokens",
            }
        )

        self.assertEqual(config.provider, "gmail")
        self.assertEqual(config.gmail_client_id, "client-id.apps.googleusercontent.com")
        self.assertEqual(config.gmail_credentials_ref, "email:gmail:me@example.com:client")
        self.assertEqual(config.gmail_token_ref, "email:gmail:me@example.com:tokens")

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
