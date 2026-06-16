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


if __name__ == "__main__":
    unittest.main()
