from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "brain"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-activity-levels-test-")

from bitbuddy.autonomy.levels import LEVEL_PROFILES, profile_for_level, resolve_profile  # noqa: E402
from bitbuddy.config import load_config, parse_autonomy_config, update_autonomy_config, write_config  # noqa: E402


class ActivityLevelTest(unittest.TestCase):
    def setUp(self) -> None:
        write_config("none", "", "")

    def test_each_level_resolves_to_its_profile(self) -> None:
        for level, profile in LEVEL_PROFILES.items():
            cfg = parse_autonomy_config({"activity_level": level})
            self.assertEqual(cfg.activity_level, level)
            self.assertEqual(cfg.idle_delay_seconds, profile.idle_delay_seconds)
            self.assertEqual(cfg.max_steps_per_session, profile.max_steps_per_session)
            self.assertEqual(cfg.max_autonomous_deliveries_per_day, profile.max_autonomous_deliveries_per_day)
            self.assertEqual(cfg.surface_cooldown_minutes, profile.surface_cooldown_minutes)
            self.assertEqual(cfg.min_autonomous_priority, profile.min_autonomous_priority)
            resolved = resolve_profile(cfg)
            self.assertEqual(resolved, profile)

    def test_unknown_level_falls_back_to_medium(self) -> None:
        cfg = parse_autonomy_config({"activity_level": "ludicrous"})
        self.assertEqual(cfg.activity_level, "medium")
        self.assertEqual(resolve_profile(cfg), profile_for_level("medium"))

    def test_higher_level_is_livelier_than_lower(self) -> None:
        low = parse_autonomy_config({"activity_level": "low"})
        high = parse_autonomy_config({"activity_level": "high"})
        self.assertLess(high.idle_delay_seconds, low.idle_delay_seconds)
        self.assertGreater(high.max_steps_per_session, low.max_steps_per_session)
        self.assertGreater(high.max_autonomous_deliveries_per_day, low.max_autonomous_deliveries_per_day)
        self.assertLess(high.surface_cooldown_minutes, low.surface_cooldown_minutes)

    def test_explicit_numeric_override_beats_profile(self) -> None:
        cfg = parse_autonomy_config({"activity_level": "high", "idle_delay_seconds": 42, "max_steps_per_session": 1})
        self.assertEqual(cfg.idle_delay_seconds, 42.0)
        self.assertEqual(cfg.max_steps_per_session, 1)
        # untouched knobs still follow the level
        self.assertEqual(cfg.surface_cooldown_minutes, LEVEL_PROFILES["high"].surface_cooldown_minutes)

    def test_explicit_numeric_in_payload_preserved_with_level(self) -> None:
        # Posting the whole object (level + numerics): the explicit numeric
        # override must be preserved (settings UI sends the whole autonomy object
        # and user-tweaked knobs must survive).
        update_autonomy_config({"activity_level": "low", "idle_delay_seconds": 5000, "max_autonomous_deliveries_per_day": 10})
        self.assertEqual(load_config().autonomy.idle_delay_seconds, 5000.0)
        self.assertEqual(load_config().autonomy.max_autonomous_deliveries_per_day, 10)

    def test_pinning_override_without_level_then_level_resets_it(self) -> None:
        update_autonomy_config({"activity_level": "low"})
        # An override set without a level is honored...
        update_autonomy_config({"idle_delay_seconds": 5000})
        self.assertEqual(load_config().autonomy.idle_delay_seconds, 5000.0)
        # ...until a preset is chosen again, which resets it.
        update_autonomy_config({"activity_level": "high"})
        autonomy = load_config().autonomy
        self.assertEqual(autonomy.activity_level, "high")
        self.assertEqual(autonomy.idle_delay_seconds, LEVEL_PROFILES["high"].idle_delay_seconds)


if __name__ == "__main__":
    unittest.main()
