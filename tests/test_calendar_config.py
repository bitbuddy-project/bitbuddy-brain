from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "brain"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-calendar-config-test-")

from bitbuddy.config import load_config, parse_calendar_config, update_calendar_config, write_config  # noqa: E402


class CalendarConfigTest(unittest.TestCase):
    def setUp(self) -> None:
        write_config("none", "", "")

    def test_update_calendar_config_preserves_unspecified_fields(self) -> None:
        update_calendar_config(
            {
                "enabled": True,
                "scheduler_tick_seconds": 30,
                "holidays_enabled": True,
                "holidays_country": "gb",
            }
        )

        update_calendar_config({"reminder_upcoming_minutes": 45})

        calendar = load_config().calendar
        self.assertTrue(calendar.enabled)
        self.assertEqual(calendar.scheduler_tick_seconds, 30)
        self.assertTrue(calendar.holidays_enabled)
        self.assertEqual(calendar.holidays_country, "GB")
        self.assertEqual(calendar.reminder_upcoming_minutes, 45)

    def test_calendar_config_normalizes_minimums_and_country(self) -> None:
        calendar = parse_calendar_config(
            {
                "reminder_upcoming_minutes": 0,
                "reminder_starting_soon_minutes": -5,
                "scheduler_tick_seconds": 1,
                "holidays_country": " us ",
            }
        )

        self.assertEqual(calendar.reminder_upcoming_minutes, 1)
        self.assertEqual(calendar.reminder_starting_soon_minutes, 1)
        self.assertEqual(calendar.scheduler_tick_seconds, 15)
        self.assertEqual(calendar.holidays_country, "US")


if __name__ == "__main__":
    unittest.main()
