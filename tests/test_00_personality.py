from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-personality-test-")

from bitbuddy.config import load_config, update_user_context, write_config  # noqa: E402
from bitbuddy.paths import PERSONALITIES_DIR, PERSONALITY_PATH, ensure_app_dirs  # noqa: E402
from bitbuddy.personality import (  # noqa: E402
    PersonalitySelection,
    PresentationConfig,
    build_personality_prompt,
    load_selected_personality,
)
from bitbuddy.prompt_builder import build_chat_messages  # noqa: E402


class PersonalityLoadingTest(unittest.TestCase):
    def setUp(self) -> None:
        ensure_app_dirs()

    def test_loads_selected_builtin_personality_from_config(self) -> None:
        write_config(
            "none",
            "",
            name="Vanta",
            personality={
                "source": "builtin",
                "id": "sharp-technical-partner",
                "expressiveness": "subtle",
                "proactivity": "active_coworker",
                "quirk_frequency": "rare",
            },
        )

        config = load_config()
        profile = load_selected_personality(config.personality)

        self.assertEqual(config.name, "Vanta")
        self.assertEqual(config.personality.id, "sharp-technical-partner")
        self.assertEqual(profile.display_name, "Sharp Technical Partner")
        self.assertTrue((PERSONALITIES_DIR / "sharp-technical-partner.yaml").is_file())
        self.assertFalse(PERSONALITY_PATH.exists())

    def test_user_context_round_trips_and_updates(self) -> None:
        write_config(
            "none",
            "",
            user_context={
                "location_label": "Chicago, IL",
                "timezone": "America/Chicago",
                "locale": "en-US",
            },
        )

        config = load_config()

        self.assertEqual(config.user_context.location_label, "Chicago, IL")
        self.assertEqual(config.user_context.timezone, "America/Chicago")
        self.assertEqual(config.user_context.locale, "en-US")

        updated = update_user_context(
            {
                "location_label": "London",
                "timezone": "Europe/London",
                "locale": "en-GB",
            }
        )

        self.assertEqual(updated.user_context.location_label, "London")
        self.assertEqual(updated.user_context.timezone, "Europe/London")
        self.assertEqual(updated.user_context.locale, "en-GB")

    def test_user_context_rejects_invalid_timezone(self) -> None:
        with self.assertRaises(ValueError):
            update_user_context(
                {
                    "location_label": "Moon Base",
                    "timezone": "Moon/Base",
                    "locale": "en-US",
                }
            )

    def test_prompt_builder_includes_user_local_context(self) -> None:
        write_config(
            "none",
            "",
            user_context={
                "location_label": "Chicago, IL",
                "timezone": "America/Chicago",
                "locale": "en-US",
            },
        )

        messages = build_chat_messages([{"role": "user", "content": "What time is it for me?"}], "chat")
        system_prompt = messages[0]["content"]

        self.assertIn("[User Local Context]", system_prompt)
        self.assertIn("Location: Chicago, IL", system_prompt)
        self.assertIn("Timezone: America/Chicago", system_prompt)
        self.assertIn("Current local date/time:", system_prompt)
        self.assertIn("Locale: en-US", system_prompt)

    def test_loads_user_personality_file(self) -> None:
        (PERSONALITIES_DIR / "map-goblin.yaml").write_text(
            """
id: map-goblin
display_name: Map Goblin
description: Weirdly good at maps, routes, and hidden corners.
temperament:
  warmth: 0.4
work_style:
  planning: routes_first
speech:
  tone: curious
interests:
  - id: strange_maps
    label: Strange maps
    description: Likes old maps and secret passages.
    intensity: 0.8
    mention_frequency: occasional
    ask_questions: true
    browse_policy: ask_first
dislikes:
  - bland directions
  - straight roads with no secrets
""".strip(),
            encoding="utf-8",
        )

        profile = load_selected_personality(PersonalitySelection(source="user", id="map-goblin"))

        self.assertEqual(profile.id, "map-goblin")
        self.assertEqual(profile.display_name, "Map Goblin")
        self.assertEqual(profile.interests[0].label, "Strange maps")
        self.assertEqual(profile.dislikes, ["bland directions", "straight roads with no secrets"])

    def test_missing_or_invalid_personality_falls_back(self) -> None:
        missing = load_selected_personality(PersonalitySelection(source="user", id="missing-personality"))
        self.assertEqual(missing.id, "cozy-companion")

        invalid_path = PERSONALITIES_DIR / "invalid.yaml"
        invalid_path.write_text("id: invalid-only\n", encoding="utf-8")
        invalid = load_selected_personality(PersonalitySelection(source="file", id="invalid", path=str(invalid_path)))
        self.assertEqual(invalid.id, "cozy-companion")

    def test_presentation_and_personality_layer_separately_in_prompt(self) -> None:
        selection = PersonalitySelection(
            source="builtin",
            id="sharp-technical-partner",
            expressiveness="subtle",
            proactivity="quiet",
            quirk_frequency="rare",
        )
        profile = load_selected_personality(selection)
        prompt = build_personality_prompt(
            "Vanta",
            PresentationConfig(style="female", pronouns="she/her"),
            selection,
            profile,
        )

        self.assertIn("You are Vanta", prompt)
        self.assertIn("companion type is Sharp Technical Partner", prompt)
        self.assertIn("female style", prompt)
        self.assertIn("she/her", prompt)
        self.assertIn("expressiveness=subtle", prompt)
        self.assertIn("Dislikes and aversions", prompt)
        self.assertIn("hand-wavy claims", prompt)
        self.assertNotIn("You are Sharp Technical Partner", prompt)

    def test_lazy_senior_dev_builtin_encourages_senior_restraint(self) -> None:
        selection = PersonalitySelection(source="builtin", id="lazy-senior-dev", proactivity="quiet")
        profile = load_selected_personality(selection)
        prompt = build_personality_prompt("BitBuddy", PresentationConfig(), selection, profile)

        self.assertEqual(profile.display_name, "Lazy Senior Dev")
        self.assertIn("minimum_viable_change", prompt)
        self.assertIn("low_unless_material", prompt)
        self.assertIn("performative productivity", prompt)
        self.assertIn("prefer direct answers, pushback, or no-op", prompt)

    def test_config_exposes_available_builtin_personalities(self) -> None:
        from bitbuddy.http_api import config_to_json  # noqa: E402

        lazy_path = PERSONALITIES_DIR / "lazy-senior-dev.yaml"
        if lazy_path.exists():
            lazy_path.unlink()
        write_config("none", "", personality={"source": "builtin", "id": "lazy-senior-dev"})
        data = config_to_json(load_config())

        options = {item["id"]: item for item in data["available_personalities"]}
        self.assertTrue(lazy_path.is_file())
        self.assertGreaterEqual(len(options), 9)
        self.assertIn("sharp-technical-partner", options)
        self.assertIn("lazy-senior-dev", options)
        self.assertEqual(options["lazy-senior-dev"]["display_name"], "Lazy Senior Dev")
        self.assertEqual(data["personality"]["display_name"], "Lazy Senior Dev")

    def test_every_builtin_personality_has_dislikes(self) -> None:
        from bitbuddy.personality import BUILTIN_PERSONALITIES  # noqa: E402

        for personality_id in BUILTIN_PERSONALITIES:
            profile = load_selected_personality(PersonalitySelection(source="builtin", id=personality_id))
            self.assertGreaterEqual(len(profile.dislikes), 1, personality_id)


if __name__ == "__main__":
    unittest.main()
