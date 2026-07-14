from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from bitbuddy.provider_capabilities import provider_capability_profile  # noqa: E402


class ProviderCapabilityProfileTest(unittest.TestCase):
    def test_zai_glm5_supports_high_and_max(self) -> None:
        profile = provider_capability_profile("z.ai-coding", "glm-5.2", context_window_tokens=1000000)

        self.assertTrue(profile["supports_reasoning_effort"])
        self.assertEqual(profile["reasoning_efforts"], ["off", "high", "max"])
        self.assertEqual(profile["default_reasoning_effort"], "high")
        self.assertEqual(profile["context_window_tokens"], 1000000)

    def test_zai_older_model_only_supports_off(self) -> None:
        profile = provider_capability_profile("z.ai", "glm-4.7")

        self.assertFalse(profile["supports_reasoning_effort"])
        self.assertEqual(profile["reasoning_efforts"], ["off"])

    def test_openai_and_codex_include_xhigh_but_not_max(self) -> None:
        for provider in ("openai", "codex"):
            with self.subTest(provider=provider):
                profile = provider_capability_profile(provider, "gpt-5.5")

                self.assertIn("xhigh", profile["reasoning_efforts"])
                self.assertNotIn("max", profile["reasoning_efforts"])

    def test_openai_and_codex_gpt_5_6_include_max(self) -> None:
        for provider in ("openai", "codex"):
            with self.subTest(provider=provider):
                profile = provider_capability_profile(provider, "gpt-5.6-sol")

                self.assertEqual(profile["reasoning_efforts"], ["off", "low", "medium", "high", "xhigh", "max"])

    def test_anthropic_capability_levels_are_model_aware(self) -> None:
        opus = provider_capability_profile("anthropic", "claude-opus-4-8")
        haiku = provider_capability_profile("anthropic", "claude-haiku-4-5")

        self.assertEqual(opus["reasoning_efforts"], ["off", "low", "medium", "high", "xhigh", "max"])
        self.assertFalse(haiku["supports_reasoning_effort"])

    def test_fable_5_requires_adaptive_thinking(self) -> None:
        profile = provider_capability_profile("anthropic", "claude-fable-5")

        self.assertTrue(profile["requires_thinking"])
        self.assertEqual(profile["reasoning_efforts"], ["low", "medium", "high", "xhigh", "max"])


if __name__ == "__main__":
    unittest.main()
