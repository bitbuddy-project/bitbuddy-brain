from __future__ import annotations

import queue
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from bitbuddy.chats.state import ActiveChatRun


class PermissionRequestTest(unittest.TestCase):
    def test_subscribe_replays_pending_permission_request(self) -> None:
        run = ActiveChatRun(chat_id="chat-1", mode="chat", model=None, prompt_messages=[])
        run.permission_request = {
            "tool": "run_shell_command",
            "reason": "Shell command changes system state.",
            "arguments": {"command": "touch demo.txt"},
        }

        subscriber = run.subscribe()
        events = []
        while True:
            try:
                events.append(subscriber.get_nowait())
            except queue.Empty:
                break

        permission_events = [event for event in events if event.get("kind") == "permission_request"]
        self.assertEqual(len(permission_events), 1)
        self.assertEqual(permission_events[0]["tool"], "run_shell_command")
        self.assertEqual(permission_events[0]["arguments"], {"command": "touch demo.txt"})


if __name__ == "__main__":
    unittest.main()
