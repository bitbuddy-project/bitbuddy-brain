from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-provider-context-test-")

from bitbuddy.config import ProviderConfig  # noqa: E402
from bitbuddy.providers import ProviderClient  # noqa: E402


class ProviderContextUsageTest(unittest.TestCase):
    def test_codex_context_window_reports_zero_used_for_provider_only(self) -> None:
        client = ProviderClient(ProviderConfig(type="codex", url="codex://chatgpt", model="gpt-5.5"))

        usage = client.context_window()

        self.assertEqual(usage["used_tokens"], 0)
        self.assertEqual(usage["context_window_tokens"], 272000)

    def test_cloud_count_tokens_uses_estimate(self) -> None:
        client = ProviderClient(ProviderConfig(type="codex", url="codex://chatgpt", model="gpt-5.5"))

        usage = client.count_tokens([
            {"role": "system", "content": "You are BitBuddy."},
            {"role": "user", "content": "Please summarize this context."},
        ])

        self.assertIsInstance(usage["used_tokens"], int)
        self.assertGreater(usage["used_tokens"], 0)
        self.assertEqual(usage["source"], "codex token estimate")


if __name__ == "__main__":
    unittest.main()
