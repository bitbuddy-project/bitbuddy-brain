from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "brain"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-question-surfacing-test-")

from bitbuddy.activity import ensure_activity_database  # noqa: E402
from bitbuddy.activity import list_activity  # noqa: E402
from bitbuddy.autonomy.delivery_scheduler import run_intention_delivery_check, schedule_startup_intention_delivery  # noqa: E402
from bitbuddy.autonomy.intentions import create_intention, ensure_intentions_database, list_pending_intentions  # noqa: E402
from bitbuddy.chats.repository import create_chat, ensure_chat_database, get_chat  # noqa: E402
from bitbuddy.chats.runtime import start_chat_run  # noqa: E402
from bitbuddy.chats.state import ActiveChatRun  # noqa: E402
from bitbuddy.continuity import ensure_continuity_database, recent_continuity_events, record_continuity_event  # noqa: E402
from bitbuddy.lifecycle import ensure_lifecycle_database  # noqa: E402
from bitbuddy.paths import GLOBAL_DB_PATH  # noqa: E402
from bitbuddy.providers import StreamChunk  # noqa: E402


class FakeClient:
    def __init__(self, text: str = "Here is the normal answer about apples.") -> None:
        self.text = text

    def stream_chat(self, _messages, model=None, should_cancel=None, thinking_enabled=True):
        yield StreamChunk("response", self.text)

    def count_tokens(self, messages, model=None):
        return {"used_tokens": 10, "source": "fake"}

    def context_window(self, model=None):
        return {"provider": "fake", "model": "fake", "context_window_tokens": 4096, "source": "fake"}


class FakeTimer:
    def __init__(self, delay, target, args=(), kwargs=None) -> None:
        self.delay = delay
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True


def fake_config() -> SimpleNamespace:
    return SimpleNamespace(
        provider=SimpleNamespace(type="fake", url="", model=""),
        autonomy=SimpleNamespace(max_pending_questions=12, max_pending_comments=12, max_new_questions_per_cycle=1, max_autonomous_deliveries_per_day=10),
        dreaming=SimpleNamespace(self_note_injection_enabled=False),
    )


class QuestionQueueSurfacingTest(unittest.TestCase):
    def setUp(self) -> None:
        ensure_activity_database()
        ensure_chat_database()
        ensure_intentions_database()
        ensure_lifecycle_database()
        ensure_continuity_database()
        with sqlite3.connect(GLOBAL_DB_PATH) as connection:
            connection.execute("delete from activity")
            connection.execute("delete from continuity_events")
            connection.execute("delete from episodic_memory_capture_log")
            connection.execute("delete from intention_surfaces")
            connection.execute("delete from intentions")
            connection.execute("delete from chat_messages")
            connection.execute("delete from chats")
            connection.execute("delete from lifecycle_state")
            connection.execute(
                """
                update continuity_state
                set active_project_id = '', active_topic = '', last_chat_id = '',
                    last_user_message_at = '', last_assistant_message_at = '',
                    last_user_summary = '', last_assistant_action_summary = '',
                    last_tool_result_summary = '', last_autonomy_summary = '',
                    last_memory_update_summary = '', last_meaningful_turn_at = '',
                    last_meaningful_turn_summary = '', unresolved_threads_json = '[]'
                where id = 1
                """
            )
        ensure_lifecycle_database()

    def run_chat(self, chat_id: str, text: str = "Can we talk about apples?") -> ActiveChatRun:
        run = ActiveChatRun(
            chat_id=chat_id,
            mode="chat",
            model=None,
            prompt_messages=[{"role": "user", "content": text}],
        )
        with patch("bitbuddy.chats.runtime.ProviderClient", return_value=FakeClient()), \
             patch("bitbuddy.chats.runtime.load_config", return_value=fake_config()), \
             patch("bitbuddy.chats.runtime.schedule_memory_consolidation", return_value=None), \
             patch("bitbuddy.chats.runtime.cancel_memory_consolidation", return_value=None), \
             patch("bitbuddy.chats.runtime.lifecycle_quiet_mode", return_value=False):
            start_chat_run(run)
            assert run.thread is not None
            run.thread.join(timeout=2)
        self.assertEqual(run.status, "complete")
        return run

    def test_chat_runtime_surfaces_one_item_after_successful_response(self) -> None:
        chat = create_chat("Question surfacing", "chat")
        create_intention("question", "Do you want to revisit apples?", metadata={"priority": 3})

        self.run_chat(chat.id)
        persisted = get_chat(chat.id)
        assistant_text = "\n".join(str(message["content"]) for message in persisted["messages"] if message["role"] == "assistant")

        self.assertIn("Here is the normal answer", assistant_text)
        self.assertIn("Also, I had a question saved from earlier", assistant_text)
        self.assertIn("Do you want to revisit apples?", assistant_text)
        self.assertEqual(list_pending_intentions(), [])

    def test_cooldown_prevents_repeated_surfacing_in_same_chat(self) -> None:
        chat = create_chat("Question cooldown", "chat")
        create_intention("question", "Do you want to revisit apples?", metadata={"priority": 5})
        self.run_chat(chat.id)
        create_intention("question", "Should we talk about apples again?", metadata={"priority": 5})

        self.run_chat(chat.id)
        persisted = get_chat(chat.id)
        assistant_text = "\n".join(str(message["content"]) for message in persisted["messages"] if message["role"] == "assistant")

        self.assertEqual(assistant_text.count("Also, I had a question saved from earlier"), 1)
        self.assertEqual(len(list_pending_intentions()), 1)

    def test_autonomy_does_not_need_to_complete_for_delivery(self) -> None:
        chat = create_chat("No autonomy delivery", "chat")
        create_intention("question", "Do you want to talk about apples without autonomy?", metadata={"priority": 5})

        self.run_chat(chat.id)
        activity_kinds = []
        with sqlite3.connect(GLOBAL_DB_PATH) as connection:
            activity_kinds = [row[0] for row in connection.execute("select kind from activity").fetchall()]

        self.assertIn("intention.surfaced", activity_kinds)
        self.assertFalse(any(kind == "autonomy.completed" for kind in activity_kinds))

    def test_delivery_check_appends_question_without_user_prompt(self) -> None:
        chat = create_chat("Autonomous question", "chat")
        create_intention("question", "Should we revisit the continuity queue?", metadata={"priority": 3})

        with patch("bitbuddy.autonomy.delivery_scheduler.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.ProviderClient", return_value=FakeClient("Should we revisit the continuity queue now?")):
            delivered = run_intention_delivery_check(reason="test", chat_id=chat.id)

        persisted = get_chat(chat.id)
        assistant_text = "\n".join(str(message["content"]) for message in persisted["messages"] if message["role"] == "assistant")
        self.assertIsNotNone(delivered)
        self.assertIn("Should we revisit the continuity queue now?", assistant_text)
        self.assertEqual(list_pending_intentions(), [])
        self.assertTrue(any(event.event_type == "intention_shown" for event in recent_continuity_events(limit=5)))

    def test_delivery_check_respects_global_cooldown(self) -> None:
        chat = create_chat("Autonomous cooldown", "chat")
        create_intention("question", "First autonomous question?", metadata={"priority": 5})

        with patch("bitbuddy.autonomy.delivery_scheduler.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.ProviderClient", return_value=FakeClient("First autonomous question.")):
            first = run_intention_delivery_check(reason="test", chat_id=chat.id)

        create_intention("question", "Second autonomous question?", metadata={"priority": 5})
        with patch("bitbuddy.autonomy.delivery_scheduler.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.ProviderClient", return_value=FakeClient("Second autonomous question.")):
            second = run_intention_delivery_check(reason="test", chat_id=chat.id)

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(list_pending_intentions()), 1)

    def test_scheduled_delivery_reschedules_after_cooldown_skip(self) -> None:
        chat = create_chat("Autonomous retry", "chat")
        create_intention("question", "First autonomous question?", metadata={"priority": 5})

        with patch("bitbuddy.autonomy.delivery_scheduler.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.ProviderClient", return_value=FakeClient("First autonomous question.")):
            first = run_intention_delivery_check(reason="test", chat_id=chat.id)

        create_intention("question", "Second autonomous question?", metadata={"priority": 5})
        with patch("bitbuddy.autonomy.delivery_scheduler.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.ProviderClient", return_value=FakeClient("Second autonomous question.")), \
             patch("bitbuddy.autonomy.delivery_scheduler.threading.Timer", FakeTimer):
            second = run_intention_delivery_check(reason="scheduled:test", chat_id=chat.id, reschedule_on_pending=True)

        self.assertIsNotNone(first)
        self.assertIsNone(second)
        scheduled = [item for item in list_activity() if item["kind"] == "autonomy.delivery_scheduled"]
        self.assertTrue(any(item["metadata"].get("reason") == "retry_after_global_cooldown" for item in scheduled))

    def test_delivery_check_respects_quiet_mode_for_priority_three(self) -> None:
        chat = create_chat("Quiet delivery", "chat")
        create_intention("question", "Low priority quiet question?", metadata={"priority": 3})
        with sqlite3.connect(GLOBAL_DB_PATH) as connection:
            connection.execute("update lifecycle_state set state = 'NightEligible', quiet_mode = 1 where id = 1")

        with patch("bitbuddy.autonomy.delivery_scheduler.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.ProviderClient", return_value=FakeClient("Quiet question.")):
            delivered = run_intention_delivery_check(reason="test", chat_id=chat.id)

        self.assertIsNone(delivered)
        self.assertEqual(len(list_pending_intentions()), 1)

    def test_delivery_uses_last_chat_from_continuity_state(self) -> None:
        chat = create_chat("Continuity target", "chat")
        record_continuity_event("user_message_received", "Current active chat for queued questions.", source="chat", chat_id=chat.id)
        create_intention("question", "Should this land in the continuity target chat?", metadata={"priority": 5})

        with patch("bitbuddy.autonomy.delivery_scheduler.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.ProviderClient", return_value=FakeClient("This lands in the continuity target chat.")):
            delivered = run_intention_delivery_check(reason="test")

        assistant_text = "\n".join(str(message["content"]) for message in get_chat(chat.id)["messages"] if message["role"] == "assistant")
        self.assertIsNotNone(delivered)
        self.assertIn("continuity target chat", assistant_text)

    def test_startup_schedules_pending_intention_check(self) -> None:
        create_chat("Startup target", "chat")
        create_intention("question", "Startup pending question?", metadata={"priority": 5})

        with patch("bitbuddy.autonomy.delivery_scheduler.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery_scheduler.threading.Timer", FakeTimer):
            scheduled = schedule_startup_intention_delivery()

        self.assertTrue(scheduled)


if __name__ == "__main__":
    unittest.main()
