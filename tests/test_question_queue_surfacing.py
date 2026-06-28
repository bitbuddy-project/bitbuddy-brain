from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-question-surfacing-test-")

from bitbuddy.activity import ensure_activity_database  # noqa: E402
from bitbuddy.activity import list_activity  # noqa: E402
from bitbuddy.autonomy.delivery_scheduler import (  # noqa: E402
    clear_current_delivery_timer,
    run_intention_delivery_check,
    schedule_intention_delivery,
    schedule_startup_intention_delivery,
    set_active_visible_chat,
    start_delivery_heartbeat,
)
from bitbuddy.autonomy.intentions import create_intention, ensure_intentions_database, list_pending_intentions  # noqa: E402
from bitbuddy.chats.repository import create_chat, ensure_chat_database, get_chat, list_recent_chats  # noqa: E402
from bitbuddy.chats.runtime import start_chat_run  # noqa: E402
from bitbuddy.chats.state import ActiveChatRun  # noqa: E402
from bitbuddy.continuity import ensure_continuity_database, recent_continuity_events, record_continuity_event  # noqa: E402
from bitbuddy.lifecycle import ensure_lifecycle_database  # noqa: E402
from bitbuddy.notifications import ensure_notification_database, list_notifications  # noqa: E402
from bitbuddy.paths import GLOBAL_DB_PATH  # noqa: E402
from bitbuddy.providers import StreamChunk  # noqa: E402


class FakeClient:
    def __init__(self, text: str = "Here is the normal answer about apples.") -> None:
        self.text = text

    def stream_chat(self, _messages, model=None, should_cancel=None, thinking_enabled=True, tools=None, tool_choice="auto"):
        yield StreamChunk("response", self.text)

    def supports_native_tools(self, model=None):
        return False

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

    def is_alive(self) -> bool:
        return self.started and not self.cancelled


def fake_config() -> SimpleNamespace:
    return SimpleNamespace(
        provider=SimpleNamespace(type="fake", url="", model=""),
        chat=SimpleNamespace(max_tool_rounds=99, reasoning_budget_tokens=-1),
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
        ensure_notification_database()
        with closing(sqlite3.connect(GLOBAL_DB_PATH)) as connection, connection:
            connection.execute("delete from activity")
            connection.execute("delete from continuity_events")
            connection.execute("delete from episodic_memory_capture_log")
            connection.execute("delete from intention_surfaces")
            connection.execute("delete from intentions")
            connection.execute("delete from notifications")
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
        clear_current_delivery_timer()
        set_active_visible_chat("")

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
        create_intention("question", "Should we preserve the apples decision before editing?", metadata={"priority": 4})

        self.run_chat(chat.id)
        persisted = get_chat(chat.id)
        assistant_text = "\n".join(str(message["content"]) for message in persisted["messages"] if message["role"] == "assistant")

        self.assertIn("Here is the normal answer", assistant_text)
        self.assertIn("Here is the normal answer about apples.\n\nAlso, I had a question saved from earlier", assistant_text)
        self.assertIn("Also, I had a question saved from earlier", assistant_text)
        self.assertIn("Should we preserve the apples decision before editing?", assistant_text)
        self.assertEqual(list_pending_intentions(), [])

    def test_chat_runtime_keeps_paragraph_break_before_saved_comment(self) -> None:
        chat = create_chat("Comment spacing", "chat")
        create_intention(
            "comment",
            "Confirmed useful apple project context from the morning brief.",
            metadata={"quality": {"accepted": True, "importance": 5}, "priority": 5},
        )

        self.run_chat(chat.id)
        assistant_text = "\n".join(str(message["content"]) for message in get_chat(chat.id)["messages"] if message["role"] == "assistant")

        self.assertIn("Here is the normal answer about apples.\n\nAlso, I had a comment saved from earlier", assistant_text)
        self.assertNotIn("answer.Also", assistant_text)
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
        with closing(sqlite3.connect(GLOBAL_DB_PATH)) as connection, connection:
            activity_kinds = [row[0] for row in connection.execute("select kind from activity").fetchall()]

        self.assertIn("intention.surfaced", activity_kinds)
        self.assertFalse(any(kind == "autonomy.completed" for kind in activity_kinds))

    def test_delivery_check_appends_question_without_user_prompt(self) -> None:
        chat = create_chat("Autonomous question", "chat")
        create_intention("question", "Should we schedule the continuity queue review now?", metadata={"priority": 4})

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

    def test_delivery_stales_self_researchable_technical_question(self) -> None:
        chat = create_chat("Autonomous technical question", "chat")
        create_intention(
            "question",
            "How does the Halley cluster tile animation system integrate with the compositor render loop?",
            reason="This asks about calloop handles, frame presentation sync, and compositor performance.",
            metadata={"quality": {"accepted": True, "importance": 5}, "priority": 5, "project_id": "halley-wl"},
        )

        with patch("bitbuddy.autonomy.delivery_scheduler.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.load_config", return_value=fake_config()):
            delivered = run_intention_delivery_check(reason="test", chat_id=chat.id)

        persisted = get_chat(chat.id)
        assistant_text = "\n".join(str(message["content"]) for message in persisted["messages"] if message["role"] == "assistant")
        self.assertIsNone(delivered)
        self.assertEqual(assistant_text, "")
        self.assertEqual(list_pending_intentions(), [])

    def test_delivery_check_creates_chat_when_none_exists(self) -> None:
        create_intention("question", "Should we schedule the continuity queue review now?", metadata={"priority": 4})

        with patch("bitbuddy.autonomy.delivery_scheduler.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.ProviderClient", return_value=FakeClient("Should we revisit the continuity queue now?")):
            delivered = run_intention_delivery_check(reason="test")

        chats = list_recent_chats(limit=2)
        self.assertIsNotNone(delivered)
        self.assertEqual(len(chats), 1)
        self.assertEqual(chats[0].title, "Autonomous messages")
        assistant_text = "\n".join(str(message["content"]) for message in get_chat(chats[0].id)["messages"] if message["role"] == "assistant")
        self.assertIn("Should we revisit the continuity queue now?", assistant_text)
        notifications = list_notifications()
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0].category, "autonomy")
        self.assertEqual(notifications[0].chat_id, chats[0].id)
        self.assertEqual(list_pending_intentions(), [])

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
        with closing(sqlite3.connect(GLOBAL_DB_PATH)) as connection, connection:
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
        self.assertEqual([item.id for item in list_recent_chats(limit=2)], [chat.id])
        notifications = list_notifications()
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0].category, "autonomy")
        self.assertEqual(notifications[0].chat_id, chat.id)
        self.assertEqual(notifications[0].action_url, f"/?chat_id={chat.id}")

    def test_startup_schedules_pending_intention_check(self) -> None:
        create_chat("Startup target", "chat")
        create_intention("question", "Startup pending question?", metadata={"priority": 5})

        with patch("bitbuddy.autonomy.delivery_scheduler.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery_scheduler.threading.Timer", FakeTimer):
            scheduled = schedule_startup_intention_delivery()

        self.assertTrue(scheduled)

    def test_importance_three_accepted_question_surfaces_in_chat(self) -> None:
        # Regression: a question accepted at creation with importance 3 used to be
        # dead-lettered by the delivery gate. It must surface in-chat when relevant.
        chat = create_chat("Importance three", "chat")
        create_intention(
            "question",
            "Should we cache the apples lookup before editing?",
            metadata={"quality": {"accepted": True, "importance": 3}, "priority": 3},
        )

        self.run_chat(chat.id)
        assistant_text = "\n".join(str(message["content"]) for message in get_chat(chat.id)["messages"] if message["role"] == "assistant")

        self.assertIn("Also, I had a question saved from earlier", assistant_text)
        self.assertIn("Should we cache the apples lookup before editing?", assistant_text)
        self.assertEqual(list_pending_intentions(), [])

    def test_importance_three_accepted_question_delivers_autonomously(self) -> None:
        chat = create_chat("Importance three autonomous", "chat")
        create_intention(
            "question",
            "Should we cache the apples lookup before editing?",
            metadata={"quality": {"accepted": True, "importance": 3}, "priority": 3},
        )

        with patch("bitbuddy.autonomy.delivery_scheduler.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.ProviderClient", return_value=FakeClient("Should we cache the apples lookup before editing?")):
            delivered = run_intention_delivery_check(reason="test", chat_id=chat.id)

        self.assertIsNotNone(delivered)
        self.assertEqual(list_pending_intentions(), [])

    def test_rejected_quality_question_never_surfaces(self) -> None:
        chat = create_chat("Rejected quality", "chat")
        create_intention(
            "question",
            "Should we talk about the apples decision?",
            metadata={"quality": {"accepted": False, "importance": 5}, "priority": 5},
        )

        self.run_chat(chat.id)
        assistant_text = "\n".join(str(message["content"]) for message in get_chat(chat.id)["messages"] if message["role"] == "assistant")
        self.assertNotIn("Also, I had a question saved from earlier", assistant_text)

        with patch("bitbuddy.autonomy.delivery_scheduler.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.ProviderClient", return_value=FakeClient("Rejected.")):
            delivered = run_intention_delivery_check(reason="test", chat_id=chat.id)
        self.assertIsNone(delivered)
        self.assertEqual(len(list_pending_intentions()), 0)

    def test_legacy_row_without_quality_uses_content_gate(self) -> None:
        # Rows that predate quality metadata still pass through the conservative content
        # gate, so filler questions stay suppressed.
        chat = create_chat("Legacy gate", "chat")
        create_intention("question", "Do you want to revisit apples?", metadata={"priority": 3})

        self.run_chat(chat.id)
        assistant_text = "\n".join(str(message["content"]) for message in get_chat(chat.id)["messages"] if message["role"] == "assistant")
        self.assertNotIn("Also, I had a question saved from earlier", assistant_text)
        self.assertEqual(len(list_pending_intentions()), 1)

    def test_successful_delivery_reschedules_heartbeat(self) -> None:
        chat = create_chat("Heartbeat after delivery", "chat")
        create_intention("question", "First autonomous question?", metadata={"priority": 5})
        create_intention("question", "Second autonomous question?", metadata={"priority": 5})

        with patch("bitbuddy.autonomy.delivery_scheduler.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery.ProviderClient", return_value=FakeClient("First autonomous question.")), \
             patch("bitbuddy.autonomy.delivery_scheduler.threading.Timer", FakeTimer):
            delivered = run_intention_delivery_check(reason="scheduled:test", chat_id=chat.id, reschedule_on_pending=True)

        self.assertIsNotNone(delivered)
        scheduled = [item for item in list_activity() if item["kind"] == "autonomy.delivery_scheduled"]
        self.assertTrue(any(item["metadata"].get("reason") == "heartbeat_after_delivery" for item in scheduled))

    def test_heartbeat_does_not_push_out_nearer_timer(self) -> None:
        create_chat("Anti starvation", "chat")
        create_intention("question", "Pending question?", metadata={"priority": 5})

        with patch("bitbuddy.autonomy.delivery_scheduler.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery_scheduler.threading.Timer", FakeTimer):
            # A sooner timer (90s) armed first must survive a later heartbeat (idle cadence).
            schedule_intention_delivery("intention_created", delay_seconds=90)
            schedule_intention_delivery("heartbeat")
            scheduled = [item for item in list_activity() if item["kind"] == "autonomy.delivery_scheduled"]
            reasons = [item["metadata"].get("reason") for item in scheduled]
            self.assertIn("intention_created", reasons)
            self.assertNotIn("heartbeat", reasons)

            clear_current_delivery_timer()

            # Reverse: a later timer armed first is replaced by a sooner one.
            schedule_intention_delivery("heartbeat")
            schedule_intention_delivery("intention_created", delay_seconds=90)
            scheduled = [item for item in list_activity() if item["kind"] == "autonomy.delivery_scheduled"]
            reasons = [item["metadata"].get("reason") for item in scheduled]
            self.assertEqual(reasons.count("intention_created"), 2)

    def test_start_delivery_heartbeat_arms_and_stops_when_empty(self) -> None:
        with patch("bitbuddy.autonomy.delivery_scheduler.load_config", return_value=fake_config()), \
             patch("bitbuddy.autonomy.delivery_scheduler.threading.Timer", FakeTimer):
            empty = start_delivery_heartbeat()
            self.assertFalse(empty)

            create_intention("question", "Pending heartbeat question?", metadata={"priority": 5})
            armed = start_delivery_heartbeat()
            self.assertTrue(armed)


if __name__ == "__main__":
    unittest.main()
