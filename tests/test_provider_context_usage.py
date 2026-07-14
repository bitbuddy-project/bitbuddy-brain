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
    def test_codex_catalog_uses_explicit_gpt_5_6_tiers(self) -> None:
        client = ProviderClient(ProviderConfig(type="codex", url="codex://chatgpt", model="gpt-5.6-sol"))

        models = client.models()

        self.assertEqual(
            models,
            [
                "gpt-5.6-sol",
                "gpt-5.6-terra",
                "gpt-5.6-luna",
                "gpt-5.5",
                "gpt-5.4",
                "gpt-5.4-mini",
                "gpt-5.3-codex-spark",
            ],
        )

    def test_openai_gpt_5_6_uses_documented_context_window(self) -> None:
        client = ProviderClient(ProviderConfig(type="openai", url="https://api.openai.com", model="gpt-5.6-sol", api_key="key"))

        usage = client.context_window()

        self.assertEqual(usage["context_window_tokens"], 1050000)

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

    def test_zai_context_window_uses_model_metadata(self) -> None:
        client = ProviderClient(ProviderConfig(type="z.ai-coding", url="https://api.z.ai/api/coding/paas/v4", model="glm-5.2"))

        usage = client.context_window()

        self.assertEqual(usage["context_window_tokens"], 1000000)
        self.assertEqual(usage["source"], "Z.ai model metadata")
        self.assertEqual(usage["capabilities"]["reasoning_efforts"], ["off", "high", "max"])
        self.assertEqual(usage["capabilities"]["context_window_tokens"], 1000000)

    def test_zai_older_models_report_200k_context(self) -> None:
        client = ProviderClient(ProviderConfig(type="z.ai", url="https://api.z.ai/api/paas/v4", model="glm-4.7"))

        usage = client.context_window()

        self.assertEqual(usage["context_window_tokens"], 200000)


if __name__ == "__main__":
    unittest.main()
