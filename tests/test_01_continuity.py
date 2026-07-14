from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-continuity-test-")

from bitbuddy.chats.repository import create_chat, recent_continuity_context, replace_chat_messages, update_tool_event, create_tool_event  # noqa: E402
from bitbuddy.prompt_builder import build_chat_messages, conversation_messages_for_provider  # noqa: E402


class ConversationContinuityTest(unittest.TestCase):
    def test_recent_continuity_includes_previous_chat_and_excludes_current_chat(self) -> None:
        previous = create_chat("Anchorbox follow-up", "chat")
        replace_chat_messages(
            previous.id,
            [
                {"role": "user", "content": "We were reviewing Anchorbox onboarding."},
                {"role": "assistant", "content": "Next step was to tighten the personality setup flow."},
            ],
            "chat",
        )
        current = create_chat("Current unrelated chat", "chat")
        replace_chat_messages(
            current.id,
            [{"role": "user", "content": "This should not appear as continuity."}],
            "chat",
        )

        context = recent_continuity_context(current.id)

        self.assertIn("[BitBuddy Conversation Continuity]", context)
        self.assertIn("Anchorbox follow-up", context)
        self.assertIn("We were reviewing Anchorbox onboarding.", context)
        self.assertIn("tighten the personality setup flow", context)
        self.assertNotIn("This should not appear as continuity.", context)

    def test_prompt_builder_injects_continuity_system_message(self) -> None:
        previous = create_chat("Continuity prompt source", "chat")
        replace_chat_messages(
            previous.id,
            [{"role": "user", "content": "Remember that the daemon restart was the next action."}],
            "chat",
        )
        current = create_chat("New chat", "chat")

        messages = build_chat_messages(
            [{"role": "user", "content": "Where did we leave off?"}],
            "chat",
            chat_id=current.id,
        )

        continuity_messages = [message for message in messages if "[BitBuddy Conversation Continuity]" in message.get("content", "")]
        self.assertEqual(len(continuity_messages), 1)
        self.assertIn("daemon restart was the next action", continuity_messages[0]["content"])

    def test_continuity_includes_tool_summaries(self) -> None:
        previous = create_chat("Tool context", "chat")
        event = create_tool_event(previous.id, "get_project_brief", {"project_id": "anchorbox-fa44bda3"}, "Running get_project_brief...")
        update_tool_event(
            int(event["id"]),
            "completed",
            "Loaded project brief for anchorbox-fa44bda3.",
            {"tool": "get_project_brief", "result_summary": "Loaded project brief for anchorbox-fa44bda3."},
        )

        context = recent_continuity_context("")

        self.assertIn("tool get_project_brief completed", context)
        self.assertIn("Loaded project brief for anchorbox-fa44bda3", context)

    def test_provider_conversation_compacts_older_long_history(self) -> None:
        messages = []
        for index in range(60):
            messages.append({"role": "user", "content": f"old request {index} " + ("details " * 120)})
            messages.append({"role": "assistant", "content": f"old answer {index} " + ("result " * 120)})
        messages.append({"role": "user", "content": "recent exact request should stay raw"})

        provider_messages = conversation_messages_for_provider(messages)

        self.assertLess(len(provider_messages), len(messages))
        self.assertEqual(provider_messages[0]["role"], "system")
        self.assertIn("[Compacted Chat History]", provider_messages[0]["content"])
        self.assertIn("old request 0", provider_messages[0]["content"])
        self.assertEqual(provider_messages[-1], {"role": "user", "content": "recent exact request should stay raw"})

    def test_provider_conversation_does_not_compact_short_history(self) -> None:
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]

        self.assertEqual(conversation_messages_for_provider(messages), messages)

    def test_provider_conversation_uses_context_window_before_static_thresholds(self) -> None:
        messages = []
        for index in range(20):
            messages.append({"role": "user", "content": f"request {index} " + ("details " * 20)})
            messages.append({"role": "assistant", "content": f"answer {index} " + ("result " * 20)})
        messages.append({"role": "user", "content": "latest request"})

        large_window = conversation_messages_for_provider(messages, context_window_tokens=10000)
        small_window = conversation_messages_for_provider(messages, context_window_tokens=1000)

        self.assertEqual(large_window, messages)
        self.assertLess(len(small_window), len(messages))
        self.assertEqual(small_window[0]["role"], "system")
        self.assertIn("[Compacted Chat History]", small_window[0]["content"])
        self.assertEqual(small_window[-1], {"role": "user", "content": "latest request"})


if __name__ == "__main__":
    unittest.main()
