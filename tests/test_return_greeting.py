from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "brain"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-return-greeting-test-")

from bitbuddy.activity import ensure_activity_database, list_activity  # noqa: E402
from bitbuddy.chats.greeting import return_greeting_text  # noqa: E402
from bitbuddy.chats.repository import create_chat, ensure_chat_database, get_chat  # noqa: E402
from bitbuddy.chats.runtime import start_chat_run  # noqa: E402
from bitbuddy.chats.state import ActiveChatRun  # noqa: E402
from bitbuddy.paths import GLOBAL_DB_PATH  # noqa: E402
from bitbuddy.providers import StreamChunk  # noqa: E402


class FakeClient:
    def __init__(self) -> None:
        self.messages = []

    def stream_chat(self, messages, model=None, should_cancel=None, thinking_enabled=True, tools=None, tool_choice="auto"):
        self.messages = messages
        yield StreamChunk("response", "Here is the answer.")

    def supports_native_tools(self, model=None):
        return False

    def count_tokens(self, messages, model=None):
        return {"used_tokens": 10, "source": "fake"}

    def context_window(self, model=None):
        return {"provider": "fake", "model": "fake", "context_window_tokens": 4096, "source": "fake"}


def fake_config() -> SimpleNamespace:
    return SimpleNamespace(
        provider=SimpleNamespace(type="fake", url="", model=""),
        user_context=SimpleNamespace(timezone="UTC"),
        chat=SimpleNamespace(
            return_greeting_enabled=True,
            return_greeting_idle_minutes=60,
            return_greeting_phrases=("Hey, welcome back.", "Hi, welcome back."),
            max_tool_rounds=99,
            reasoning_budget_tokens=-1,
        ),
        autonomy=SimpleNamespace(max_pending_questions=12, max_pending_comments=12, max_new_questions_per_cycle=1, max_autonomous_deliveries_per_day=10),
        dreaming=SimpleNamespace(self_note_injection_enabled=False),
    )


class ReturnGreetingTest(unittest.TestCase):
    def setUp(self) -> None:
        ensure_activity_database()
        ensure_chat_database()
        with sqlite3.connect(GLOBAL_DB_PATH) as connection:
            connection.execute("delete from activity")
            connection.execute("delete from chat_messages")
            connection.execute("delete from chats")

    def test_return_greeting_after_long_idle_gap(self) -> None:
        config = fake_config()
        now = datetime(2026, 5, 15, 14, 0, tzinfo=ZoneInfo("UTC"))
        previous = (now - timedelta(minutes=90)).isoformat()

        greeting = return_greeting_text(previous, "hey can we continue?", config, now=now)

        self.assertEqual(greeting, "Hey, welcome back.")

    def test_no_return_greeting_after_short_idle_gap(self) -> None:
        config = fake_config()
        now = datetime(2026, 5, 15, 14, 0, tzinfo=ZoneInfo("UTC"))
        previous = (now - timedelta(minutes=20)).isoformat()

        greeting = return_greeting_text(previous, "hey can we continue?", config, now=now)

        self.assertEqual(greeting, "")

    def test_chat_runtime_injects_return_greeting_as_private_context(self) -> None:
        chat = create_chat("Long running chat", "chat")
        fake_client = FakeClient()
        run = ActiveChatRun(
            chat_id=chat.id,
            mode="chat",
            model=None,
            prompt_messages=[{"role": "user", "content": "hey can we continue?"}],
            return_greeting_text="Hey, welcome back.",
        )

        with patch("bitbuddy.chats.runtime.ProviderClient", return_value=fake_client), \
             patch("bitbuddy.chats.runtime.load_config", return_value=fake_config()), \
             patch("bitbuddy.chats.runtime.schedule_memory_consolidation", return_value=None), \
             patch("bitbuddy.chats.runtime.cancel_memory_consolidation", return_value=None), \
             patch("bitbuddy.chats.runtime.lifecycle_quiet_mode", return_value=False):
            start_chat_run(run)
            assert run.thread is not None
            run.thread.join(timeout=2)

        assistant_text = "\n".join(str(message["content"]) for message in get_chat(chat.id)["messages"] if message["role"] == "assistant")
        self.assertEqual(assistant_text, "Here is the answer.")
        self.assertTrue(
            any(
                message["role"] == "system"
                and "[Return Greeting Context]" in message["content"]
                and "Hey, welcome back." in message["content"]
                and "do not stack it with a separate time-of-day greeting" in message["content"]
                for message in fake_client.messages
            )
        )
        self.assertTrue(any(item["kind"] == "chat.return_greeting" for item in list_activity()))


if __name__ == "__main__":
    unittest.main()
