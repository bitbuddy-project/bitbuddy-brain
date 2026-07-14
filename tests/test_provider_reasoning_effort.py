from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-reasoning-effort-test-")

from bitbuddy.config import normalize_reasoning_effort, parse_provider_entry, provider_to_raw  # noqa: E402


class ReasoningEffortTest(unittest.TestCase):
    def test_normalize_defaults_and_clamps(self) -> None:
        self.assertEqual(normalize_reasoning_effort("high"), "high")
        self.assertEqual(normalize_reasoning_effort("MAX"), "max")
        self.assertEqual(normalize_reasoning_effort("XHIGH"), "xhigh")
        self.assertEqual(normalize_reasoning_effort("OFF"), "off")
        self.assertEqual(normalize_reasoning_effort("bogus"), "medium")
        self.assertEqual(normalize_reasoning_effort(None), "medium")

    def test_round_trip_persists_non_default(self) -> None:
        provider = parse_provider_entry(
            {"type": "llama.cpp", "url": "http://x", "model": "m", "reasoning_effort": "high"}
        )
        self.assertEqual(provider.reasoning_effort, "high")
        self.assertEqual(provider_to_raw(provider)["reasoning_effort"], "high")

    def test_default_is_medium_and_omitted_from_raw(self) -> None:
        provider = parse_provider_entry({"type": "llama.cpp", "url": "http://x", "model": "m"})
        self.assertEqual(provider.reasoning_effort, "medium")
        self.assertNotIn("reasoning_effort", provider_to_raw(provider))

    def test_zai_provider_defaults(self) -> None:
        provider = parse_provider_entry({"type": "z.ai", "api_key": "key"})
        self.assertEqual(provider.url, "https://api.z.ai/api/paas/v4")
        self.assertEqual(provider.model, "glm-5.2")
        self.assertEqual(provider.api_key_ref, "provider:z.ai:api_key")

    def test_zai_coding_provider_defaults(self) -> None:
        provider = parse_provider_entry({"type": "z.ai-coding", "api_key": "key"})
        self.assertEqual(provider.url, "https://api.z.ai/api/coding/paas/v4")
        self.assertEqual(provider.model, "glm-5.2")
        self.assertEqual(provider.api_key_ref, "provider:z.ai-coding:api_key")

    def test_openai_and_codex_default_to_gpt_5_6_sol(self) -> None:
        self.assertEqual(parse_provider_entry({"type": "openai"}).model, "gpt-5.6-sol")
        self.assertEqual(parse_provider_entry({"type": "codex"}).model, "gpt-5.6-sol")


if __name__ == "__main__":
    unittest.main()
