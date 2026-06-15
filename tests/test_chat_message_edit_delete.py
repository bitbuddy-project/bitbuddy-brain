from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ.setdefault("HOME", tempfile.mkdtemp(prefix="bitbuddy-chat-message-test-"))

from bitbuddy.chats.repository import (  # noqa: E402
    append_chat_message,
    create_chat,
    create_tool_event,
    delete_chat_message_turn,
    get_chat,
    trim_chat_from_message,
)


class ChatMessageEditDeleteTest(unittest.TestCase):
    def test_delete_user_turn_removes_reply_until_next_user_message(self) -> None:
        chat = create_chat("Turn delete", "chat")
        append_chat_message(chat.id, "user", "First question", mode="chat")
        append_chat_message(chat.id, "assistant", "First answer", mode="chat")
        create_tool_event(chat.id, "read_file", {}, "Read file", mode="chat")
        append_chat_message(chat.id, "user", "Second question", mode="chat")
        append_chat_message(chat.id, "assistant", "Second answer", mode="chat")
        first_user_id = int(get_chat(chat.id)["messages"][0]["id"])

        result = delete_chat_message_turn(chat.id, first_user_id)

        remaining = [(message["role"], message["content"], message["kind"]) for message in result["chat"]["messages"]]
        self.assertEqual(
            remaining,
            [
                ("user", "Second question", "message"),
                ("assistant", "Second answer", "message"),
            ],
        )

    def test_trim_chat_from_user_message_removes_message_and_everything_after(self) -> None:
        chat = create_chat("Edit trim", "chat")
        append_chat_message(chat.id, "user", "Original first", mode="chat")
        append_chat_message(chat.id, "assistant", "First answer", mode="chat")
        append_chat_message(chat.id, "user", "Original second", mode="chat")
        append_chat_message(chat.id, "assistant", "Second answer", mode="chat")
        second_user_id = int(get_chat(chat.id)["messages"][2]["id"])

        result = trim_chat_from_message(chat.id, second_user_id)

        remaining = [(message["role"], message["content"]) for message in result["chat"]["messages"]]
        self.assertEqual(remaining, [("user", "Original first"), ("assistant", "First answer")])


if __name__ == "__main__":
    unittest.main()
