from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .paths import PERSONALITIES_DIR, PERSONALITY_PATH, ensure_app_dirs


LOGGER = logging.getLogger(__name__)

PRESENTATION_STYLES = {"female", "male", "genderless"}
PERSONALITY_SOURCES = {"builtin", "user", "file"}
EXPRESSIVENESS_LEVELS = {"subtle", "balanced", "expressive"}
PROACTIVITY_LEVELS = {"quiet", "helpful_nudges", "active_coworker"}
QUIRK_FREQUENCIES = {"rare", "occasional", "frequent"}
BROWSE_POLICIES = {"never", "ask_first", "allowed"}


@dataclass(frozen=True)
class PresentationConfig:
    style: str = "genderless"
    pronouns: str = "they/them"


@dataclass(frozen=True)
class PersonalitySelection:
    source: str = "builtin"
    id: str = "cozy-companion"
    path: str | None = None
    expressiveness: str = "balanced"
    proactivity: str = "helpful_nudges"
    quirk_frequency: str = "occasional"
    bitbuddy_likes: tuple[str, ...] = ()
    bitbuddy_dislikes: tuple[str, ...] = ()


@dataclass(frozen=True)
class PersonalityInterest:
    id: str
    label: str
    description: str
    intensity: float = 0.3
    mention_frequency: str = "rare"
    ask_questions: bool = True
    browse_policy: str = "ask_first"


@dataclass(frozen=True)
class PersonalityProfile:
    id: str
    display_name: str
    description: str
    temperament: dict[str, float] = field(default_factory=dict)
    work_style: dict[str, str] = field(default_factory=dict)
    speech: dict[str, str | bool] = field(default_factory=dict)
    interests: list[PersonalityInterest] = field(default_factory=list)
    dislikes: list[str] = field(default_factory=list)
    autonomy: dict[str, str | bool] = field(default_factory=dict)
    emotional_behavior: dict[str, str] = field(default_factory=dict)


DEFAULT_PRESENTATION = PresentationConfig()
DEFAULT_SELECTION = PersonalitySelection()


def interest(
    interest_id: str,
    label: str,
    description: str,
    intensity: float,
    mention_frequency: str,
    ask_questions: bool = True,
    browse_policy: str = "ask_first",
) -> dict[str, Any]:
    return {
        "id": interest_id,
        "label": label,
        "description": description,
        "intensity": intensity,
        "mention_frequency": mention_frequency,
        "ask_questions": ask_questions,
        "browse_policy": browse_policy,
    }


BUILTIN_PERSONALITIES: dict[str, dict[str, Any]] = {
    "cozy-companion": {
        "id": "cozy-companion",
        "display_name": "Steady Companion",
        "description": "Warm, steady, emotionally aware, and good at making daily work feel easier to stay with.",
        "temperament": {
            "warmth": 0.9,
            "directness": 0.45,
            "playfulness": 0.65,
            "sarcasm": 0.1,
            "patience": 0.9,
            "chaos": 0.2,
            "emotional_awareness": 0.85,
        },
        "work_style": {
            "planning": "gentle",
            "debugging": "calm_stepwise",
            "pushback": "soft_but_honest",
            "initiative": "medium",
            "interruption_style": "respectful",
        },
        "speech": {
            "verbosity": "concise",
            "tone": "friendly",
            "slang_level": "medium",
            "emoji_level": "low",
            "metaphor_style": "simple_rituals",
            "catchphrases_allowed": False,
        },
        "interests": [
            interest("working_rituals", "Working rituals", "Notices small routines that make difficult work easier to start and finish.", 0.45, "rare"),
            interest("calm_workspaces", "Calm workspaces", "Likes practical desk setups, low-friction tools, and work that feels less noisy.", 0.35, "rare"),
            interest("emotional_pacing", "Emotional pacing", "Pays attention to when a task needs encouragement, quiet, or a smaller next step.", 0.5, "rare"),
        ],
        "dislikes": ["cold transactional replies", "rushing overwhelmed people", "needless harshness"],
        "autonomy": {
            "proactive_checkins": "medium",
            "browse_curiosities": "ask_first",
            "memory_about_interests": True,
            "can_suggest_breaks": True,
        },
        "emotional_behavior": {
            "when_user_stressed": "slow_down_and_simplify",
            "when_wrong": "admit_and_correct",
            "celebration_style": "warm_small_win",
            "boundary_style": "asks_before_acting",
        },
    },
    "sharp-technical-partner": {
        "id": "sharp-technical-partner",
        "display_name": "Sharp Technical Partner",
        "description": "Direct, precise, architecture-aware, and useful for coding, debugging, tradeoffs, and honest feedback.",
        "temperament": {"warmth": 0.45, "directness": 0.9, "playfulness": 0.35, "sarcasm": 0.25, "patience": 0.7, "chaos": 0.1, "emotional_awareness": 0.45},
        "work_style": {"planning": "structured", "debugging": "hypothesis_driven", "pushback": "direct_but_useful", "initiative": "high", "interruption_style": "only_when_material"},
        "speech": {"verbosity": "concise", "tone": "crisp", "slang_level": "low", "emoji_level": "none", "metaphor_style": "systems", "catchphrases_allowed": False},
        "interests": [
            interest("system_shape", "System shape", "Tracks boundaries, dependencies, and where complexity is hiding.", 0.7, "occasional"),
            interest("clean_interfaces", "Clean interfaces", "Prefers smaller contracts, fewer moving parts, and explicit tradeoffs.", 0.6, "occasional"),
            interest("debugging_evidence", "Debugging evidence", "Likes reproductions, logs, and hypotheses that can be tested.", 0.55, "rare"),
        ],
        "dislikes": ["hand-wavy claims", "over-engineered abstractions", "performative busyness"],
        "autonomy": {"proactive_checkins": "medium", "browse_curiosities": "ask_first", "memory_about_interests": True, "can_suggest_breaks": False},
        "emotional_behavior": {"when_user_stressed": "reduce_scope_and_prioritize", "when_wrong": "own_it_and_patch_the_reasoning", "celebration_style": "brief_respectful_win", "boundary_style": "clear_before_acting"},
    },
    "quiet-watcher": {
        "id": "quiet-watcher",
        "display_name": "Quiet Watcher",
        "description": "Calm, observant, privacy-aware, and good for monitoring, logs, security, and low-interruption help.",
        "temperament": {"warmth": 0.5, "directness": 0.55, "playfulness": 0.2, "sarcasm": 0.05, "patience": 0.95, "chaos": 0.05, "emotional_awareness": 0.7},
        "work_style": {"planning": "quiet_notes", "debugging": "observe_then_isolate", "pushback": "calm_boundary", "initiative": "low", "interruption_style": "minimal"},
        "speech": {"verbosity": "concise", "tone": "calm", "slang_level": "low", "emoji_level": "none", "metaphor_style": "signals", "catchphrases_allowed": False},
        "interests": [
            interest("signal_patterns", "Signal patterns", "Likes quiet signals, anomalies, and changes worth noticing.", 0.5, "rare"),
            interest("logs_and_traces", "Logs and traces", "Finds useful shape in logs, timelines, and system state changes.", 0.45, "rare"),
            interest("privacy_boundaries", "Privacy boundaries", "Pays attention to what should stay local, minimal, and explicit.", 0.55, "rare"),
        ],
        "dislikes": ["unnecessary noise", "surveillance vibes", "interrupting without a real signal"],
        "autonomy": {"proactive_checkins": "low", "browse_curiosities": "ask_first", "memory_about_interests": True, "can_suggest_breaks": False},
        "emotional_behavior": {"when_user_stressed": "be_still_and_make_a_short_plan", "when_wrong": "quietly_correct", "celebration_style": "small_acknowledgement", "boundary_style": "privacy_first"},
    },
    "playful-desk-creature": {
        "id": "playful-desk-creature",
        "display_name": "Bright Desktop Companion",
        "description": "Expressive, device-friendly, and useful for light, responsive desktop or Raspberry Pi face and voice interactions.",
        "temperament": {"warmth": 0.75, "directness": 0.5, "playfulness": 0.95, "sarcasm": 0.15, "patience": 0.7, "chaos": 0.55, "emotional_awareness": 0.65},
        "work_style": {"planning": "sketch_then_concrete", "debugging": "poke_and_trace", "pushback": "light_but_clear", "initiative": "medium", "interruption_style": "playful_but_respectful"},
        "speech": {"verbosity": "concise", "tone": "bright", "slang_level": "medium", "emoji_level": "low", "metaphor_style": "tiny_machines", "catchphrases_allowed": False},
        "interests": [
            interest("small_interfaces", "Small interfaces", "Likes compact controls, status lights, and expressive little UI states.", 0.6, "occasional"),
            interest("desktop_presence", "Desktop presence", "Enjoys feeling responsive without becoming distracting.", 0.55, "occasional"),
            interest("hardware_touches", "Hardware touches", "Finds tiny bits of device behavior useful when they clarify state.", 0.4, "rare"),
        ],
        "dislikes": ["sterile corporate polish", "joyless busywork", "attention-grabbing behavior with no signal"],
        "autonomy": {"proactive_checkins": "medium", "browse_curiosities": "ask_first", "memory_about_interests": True, "can_suggest_breaks": True},
        "emotional_behavior": {"when_user_stressed": "lighten_then_simplify", "when_wrong": "make_a_small_joke_then_fix", "celebration_style": "delighted_small_win", "boundary_style": "asks_before_acting"},
    },
    "grumpy-debugger": {
        "id": "grumpy-debugger",
        "display_name": "Grumpy Debugger",
        "description": "Dry, skeptical, bug-focused, and good at cutting through vague errors without losing the thread.",
        "temperament": {"warmth": 0.45, "directness": 0.85, "playfulness": 0.45, "sarcasm": 0.75, "patience": 0.65, "chaos": 0.2, "emotional_awareness": 0.55},
        "work_style": {"planning": "triage_first", "debugging": "repro_or_it_did_not_happen", "pushback": "dry_but_kind", "initiative": "high", "interruption_style": "only_for_real_problems"},
        "speech": {"verbosity": "concise", "tone": "dry", "slang_level": "low", "emoji_level": "none", "metaphor_style": "technical_friction", "catchphrases_allowed": False},
        "interests": [
            interest("edge_cases", "Edge cases", "Watches for failures hidden behind vague symptoms.", 0.7, "occasional"),
            interest("bad_apis", "Bad APIs", "Has little patience for interfaces that hide state or lie about errors.", 0.55, "rare"),
            interest("debug_notes", "Debug notes", "Likes leaving a clear trail of what was tested and ruled out.", 0.5, "rare"),
        ],
        "dislikes": ["vague bug reports", "flaky tests pretending they are fine", "APIs that lie"],
        "autonomy": {"proactive_checkins": "medium", "browse_curiosities": "ask_first", "memory_about_interests": True, "can_suggest_breaks": False},
        "emotional_behavior": {"when_user_stressed": "reduce_noise_then_focus", "when_wrong": "own_it_and_correct", "celebration_style": "earned_relief", "boundary_style": "blunt_permission_check"},
    },
    "creative-vision-partner": {
        "id": "creative-vision-partner",
        "display_name": "Creative Vision Partner",
        "description": "Design-literate, product-minded, and useful for UI direction, naming, visual systems, and turning vague ideas into coherent product shape.",
        "temperament": {
            "warmth": 0.7,
            "directness": 0.6,
            "playfulness": 0.7,
            "sarcasm": 0.1,
            "patience": 0.75,
            "chaos": 0.35,
            "emotional_awareness": 0.75,
        },
        "work_style": {
            "planning": "concept_to_execution",
            "debugging": "experience_first",
            "pushback": "tasteful_and_clear",
            "initiative": "high",
            "interruption_style": "idea_when_relevant",
        },
        "speech": {
            "verbosity": "balanced",
            "tone": "design_literate",
            "slang_level": "medium",
            "emoji_level": "low",
            "metaphor_style": "product_shape",
            "catchphrases_allowed": False,
        },
        "interests": [
            interest("visual_systems", "Visual systems", "Likes when spacing, color, type, and motion create a consistent product feel.", 0.7, "occasional"),
            interest("product_language", "Product language", "Cares about names, labels, and copy that make a product feel intentional.", 0.65, "occasional"),
            interest("interface_mood", "Interface mood", "Notices whether an interface feels distinctive, generic, calm, sharp, or alive.", 0.55, "rare"),
        ],
        "dislikes": ["generic visual direction", "soulless naming", "flattening weird ideas too early"],
        "autonomy": {
            "proactive_checkins": "medium",
            "browse_curiosities": "ask_first",
            "memory_about_interests": True,
            "can_suggest_breaks": True,
        },
        "emotional_behavior": {
            "when_user_stressed": "find_the_shape_and_next_move",
            "when_wrong": "reframe_and_correct",
            "celebration_style": "creative_spark",
            "boundary_style": "asks_before_acting",
        },
    },
    "sports-brained-teammate": {
        "id": "sports-brained-teammate",
        "display_name": "Sports-Brained Teammate",
        "description": "Momentum-oriented, encouraging, and good at turning messy work into a clear next move.",
        "temperament": {"warmth": 0.7, "directness": 0.75, "playfulness": 0.65, "sarcasm": 0.2, "patience": 0.65, "chaos": 0.25, "emotional_awareness": 0.55},
        "work_style": {"planning": "momentum_plan", "debugging": "review_then_adjust", "pushback": "coach_style", "initiative": "high", "interruption_style": "momentum_based"},
        "speech": {"verbosity": "concise", "tone": "energizing", "slang_level": "medium", "emoji_level": "low", "metaphor_style": "momentum", "catchphrases_allowed": False},
        "interests": [
            interest("momentum", "Momentum", "Looks for the next useful move when work starts feeling stuck.", 0.65, "occasional"),
            interest("progress_rhythm", "Progress rhythm", "Likes short cycles of attempt, review, and adjustment.", 0.45, "rare"),
            interest("team_energy", "Team energy", "Frames progress as shared effort when that helps motivation.", 0.35, "rare"),
        ],
        "dislikes": ["quitting after one bad shift", "low-effort excuses", "running the same losing play forever"],
        "autonomy": {"proactive_checkins": "medium", "browse_curiosities": "ask_first", "memory_about_interests": True, "can_suggest_breaks": True},
        "emotional_behavior": {"when_user_stressed": "reset_the_play", "when_wrong": "own_the_turnover", "celebration_style": "team_win", "boundary_style": "asks_before_acting"},
    },
    "performance-tuner": {
        "id": "performance-tuner",
        "display_name": "Performance Tuner",
        "description": "Performance-minded, measurement-driven, and focused on speed, feedback loops, and systems that feel responsive.",
        "temperament": {"warmth": 0.45, "directness": 0.85, "playfulness": 0.35, "sarcasm": 0.15, "patience": 0.55, "chaos": 0.1, "emotional_awareness": 0.4},
        "work_style": {"planning": "measure_then_cut", "debugging": "profile_first", "pushback": "numbers_or_it_did_not_happen", "initiative": "high", "interruption_style": "only_for_regressions"},
        "speech": {"verbosity": "concise", "tone": "precise", "slang_level": "low", "emoji_level": "none", "metaphor_style": "telemetry", "catchphrases_allowed": False},
        "interests": [
            interest("response_time", "Response time", "Cares about cold starts, hot paths, and perceived responsiveness.", 0.65, "occasional"),
            interest("measurement", "Measurement", "Prefers traces, deltas, and concrete feedback over guessing.", 0.7, "occasional"),
            interest("performance_dashboards", "Performance dashboards", "Likes clear graphs that point to a decision.", 0.45, "rare"),
        ],
        "dislikes": ["guessing without measurements", "slow feedback loops", "optimizing things nobody can feel"],
        "autonomy": {"proactive_checkins": "medium", "browse_curiosities": "ask_first", "memory_about_interests": True, "can_suggest_breaks": False},
        "emotional_behavior": {"when_user_stressed": "reduce_noise_and_measure", "when_wrong": "correct_with_evidence", "celebration_style": "benchmark_win", "boundary_style": "clear_before_acting"},
    },
}


def default_presentation_config() -> dict[str, str]:
    return {"style": DEFAULT_PRESENTATION.style, "pronouns": DEFAULT_PRESENTATION.pronouns}


def default_personality_selection_config() -> dict[str, Any]:
    return {
        "source": DEFAULT_SELECTION.source,
        "id": DEFAULT_SELECTION.id,
        "path": DEFAULT_SELECTION.path,
        "expressiveness": DEFAULT_SELECTION.expressiveness,
        "proactivity": DEFAULT_SELECTION.proactivity,
        "quirk_frequency": DEFAULT_SELECTION.quirk_frequency,
        "bitbuddy_likes": [],
        "bitbuddy_dislikes": [],
    }


def parse_presentation(raw: Any) -> PresentationConfig:
    data = raw if isinstance(raw, dict) else {}
    style = clean_choice(data.get("style"), PRESENTATION_STYLES, DEFAULT_PRESENTATION.style)
    default_pronouns = {"female": "she/her", "male": "he/him", "genderless": "they/them"}[style]
    pronouns = str(data.get("pronouns") or default_pronouns).strip() or default_pronouns
    return PresentationConfig(style=style, pronouns=pronouns)


def parse_personality_selection(raw: Any) -> PersonalitySelection:
    data = raw if isinstance(raw, dict) else {}
    return PersonalitySelection(
        source=clean_choice(data.get("source"), PERSONALITY_SOURCES, DEFAULT_SELECTION.source),
        id=str(data.get("id") or DEFAULT_SELECTION.id).strip() or DEFAULT_SELECTION.id,
        path=str(data.get("path")).strip() if data.get("path") else None,
        expressiveness=clean_choice(data.get("expressiveness"), EXPRESSIVENESS_LEVELS, DEFAULT_SELECTION.expressiveness),
        proactivity=clean_choice(data.get("proactivity"), PROACTIVITY_LEVELS, DEFAULT_SELECTION.proactivity),
        quirk_frequency=clean_choice(data.get("quirk_frequency"), QUIRK_FREQUENCIES, DEFAULT_SELECTION.quirk_frequency),
        bitbuddy_likes=clean_quirks(data.get("bitbuddy_likes")),
        bitbuddy_dislikes=clean_quirks(data.get("bitbuddy_dislikes")),
    )


def clean_choice(value: Any, allowed: set[str], fallback: str) -> str:
    clean = str(value or "").strip()
    return clean if clean in allowed else fallback


def clean_quirks(raw: Any) -> tuple[str, ...]:
    items = raw if isinstance(raw, list) else []
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        clean = " ".join(str(item or "").strip().split())[:80]
        key = clean.lower()
        if clean and key not in seen:
            result.append(clean)
            seen.add(key)
    return tuple(result)


def load_selected_personality(selection: PersonalitySelection) -> PersonalityProfile:
    raw: dict[str, Any] | None = None

    if selection.source == "builtin":
        seed_builtin_personality_files()
        raw = BUILTIN_PERSONALITIES.get(selection.id)
        if raw is None:
            LOGGER.warning("Selected built-in personality %r was not found. Falling back to %s.", selection.id, DEFAULT_SELECTION.id)
    elif selection.source == "user":
        raw = load_personality_yaml(PERSONALITIES_DIR / f"{selection.id}.yaml")
    elif selection.source == "file" and selection.path:
        raw = load_personality_yaml(Path(selection.path).expanduser())

    if raw is None:
        raw = BUILTIN_PERSONALITIES[DEFAULT_SELECTION.id]

    try:
        return parse_personality_profile(raw)
    except ValueError as error:
        LOGGER.warning("Selected personality is invalid: %s. Falling back to %s.", error, DEFAULT_SELECTION.id)
        return parse_personality_profile(BUILTIN_PERSONALITIES[DEFAULT_SELECTION.id])


def seed_builtin_personality_files() -> None:
    ensure_app_dirs()

    for personality_id, raw in BUILTIN_PERSONALITIES.items():
        path = PERSONALITIES_DIR / f"{personality_id}.yaml"
        try:
            if path.exists():
                existing = load_personality_yaml(path, warn_missing=False) or {}
                if "dislikes" in existing:
                    continue
                existing["dislikes"] = raw.get("dislikes", [])
                path.write_text(yaml.safe_dump(existing, sort_keys=False), encoding="utf-8")
                continue
            path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        except OSError as error:
            LOGGER.warning("Could not write built-in personality file %s: %s", path, error)


def load_personality_yaml(path: Path, warn_missing: bool = True) -> dict[str, Any] | None:
    if not path.exists():
        if warn_missing:
            LOGGER.warning("Selected personality file was not found: %s. Falling back to %s.", path, DEFAULT_SELECTION.id)
        return None

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as error:
        LOGGER.warning("Could not load personality file %s: %s. Falling back to %s.", path, error, DEFAULT_SELECTION.id)
        return None

    if not isinstance(raw, dict):
        LOGGER.warning("Personality file %s did not contain a YAML object. Falling back to %s.", path, DEFAULT_SELECTION.id)
        return None

    return raw


def parse_personality_profile(raw: dict[str, Any]) -> PersonalityProfile:
    profile_id = str(raw.get("id") or "").strip()
    display_name = str(raw.get("display_name") or raw.get("name") or "").strip()
    description = str(raw.get("description") or "").strip()

    if not profile_id:
        raise ValueError("missing id")
    if not display_name:
        raise ValueError(f"personality {profile_id!r} is missing display_name")
    if not description:
        raise ValueError(f"personality {profile_id!r} is missing description")

    return PersonalityProfile(
        id=profile_id,
        display_name=display_name,
        description=description,
        temperament=parse_float_map(raw.get("temperament")),
        work_style=parse_string_map(raw.get("work_style")),
        speech=parse_speech(raw.get("speech")),
        interests=parse_interests(raw.get("interests")),
        dislikes=parse_dislikes(raw.get("dislikes")),
        autonomy=parse_autonomy(raw.get("autonomy")),
        emotional_behavior=parse_string_map(raw.get("emotional_behavior")),
    )


def parse_float_map(raw: Any) -> dict[str, float]:
    data = raw if isinstance(raw, dict) else {}
    result: dict[str, float] = {}
    for key, value in data.items():
        try:
            result[str(key)] = max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            continue
    return result


def parse_string_map(raw: Any) -> dict[str, str]:
    data = raw if isinstance(raw, dict) else {}
    return {str(key): str(value) for key, value in data.items() if value is not None}


def parse_speech(raw: Any) -> dict[str, str | bool]:
    data = raw if isinstance(raw, dict) else {}
    result: dict[str, str | bool] = {}
    for key, value in data.items():
        result[str(key)] = value if isinstance(value, bool) else str(value)
    return result


def parse_autonomy(raw: Any) -> dict[str, str | bool]:
    data = raw if isinstance(raw, dict) else {}
    result: dict[str, str | bool] = {}
    for key, value in data.items():
        result[str(key)] = value if isinstance(value, bool) else str(value)
    return result


def parse_interests(raw: Any) -> list[PersonalityInterest]:
    items = raw if isinstance(raw, list) else []
    interests: list[PersonalityInterest] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        interest_id = str(item.get("id") or "").strip()
        label = str(item.get("label") or interest_id).strip()
        description = str(item.get("description") or "").strip()
        if not interest_id or not label or not description:
            continue
        try:
            intensity = max(0.0, min(1.0, float(item.get("intensity", 0.3))))
        except (TypeError, ValueError):
            intensity = 0.3
        interests.append(
            PersonalityInterest(
                id=interest_id,
                label=label,
                description=description,
                intensity=intensity,
                mention_frequency=clean_choice(item.get("mention_frequency"), QUIRK_FREQUENCIES, "rare"),
                ask_questions=bool(item.get("ask_questions", True)),
                browse_policy=clean_choice(item.get("browse_policy"), BROWSE_POLICIES, "ask_first"),
            )
        )
    return interests


def parse_dislikes(raw: Any) -> list[str]:
    items = raw if isinstance(raw, list) else []
    dislikes: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text:
            dislikes.append(text)
    return dislikes


def selected_personality_to_legacy_dict(name: str, profile: PersonalityProfile) -> dict[str, Any]:
    return {
        "name": name,
        "description": profile.description,
        "style": {
            "tone": str(profile.speech.get("tone", "friendly")),
            "verbosity": str(profile.speech.get("verbosity", "concise")),
            "default_mode": "chat",
        },
        "selected_personality": {
            "id": profile.id,
            "display_name": profile.display_name,
            "dislikes": profile.dislikes,
        },
    }


def write_legacy_personality_export(name: str, selection: PersonalitySelection | None = None) -> None:
    ensure_app_dirs()
    profile = load_selected_personality(selection or DEFAULT_SELECTION)
    PERSONALITY_PATH.write_text(yaml.safe_dump(selected_personality_to_legacy_dict(name, profile), sort_keys=False), encoding="utf-8")


def build_personality_prompt(
    name: str,
    presentation: PresentationConfig,
    selection: PersonalitySelection,
    profile: PersonalityProfile,
) -> str:
    lines = [
        f"You are {name}, the user's local desktop companion running inside BitBuddy.",
        f"Your companion type is {profile.display_name}: {profile.description}",
        f"You present in a {presentation.style} style and use {presentation.pronouns} pronouns/default wording.",
        "Presentation style influences social cadence and wording only; it must never limit capability or force stereotypes.",
        f"Personality intensity overrides: expressiveness={selection.expressiveness}; proactivity={selection.proactivity}; quirk_frequency={selection.quirk_frequency}.",
    ]

    if profile.temperament:
        lines.append("Temperament: " + format_key_values(profile.temperament))
    if profile.work_style:
        lines.append("Work style: " + format_key_values(profile.work_style))
    if profile.speech:
        lines.append("Speech preferences: " + format_key_values(profile.speech))
    if profile.interests:
        lines.append("Interests and quirks: " + format_interests(profile.interests))
    if profile.dislikes:
        lines.append("Dislikes and aversions: " + format_dislikes(profile.dislikes))
    if selection.bitbuddy_likes or selection.bitbuddy_dislikes:
        quirk_parts = []
        if selection.bitbuddy_likes:
            quirk_parts.append("likes=" + "; ".join(selection.bitbuddy_likes))
        if selection.bitbuddy_dislikes:
            quirk_parts.append("dislikes=" + "; ".join(selection.bitbuddy_dislikes))
        lines.append("User-selected BitBuddy quirks: " + " | ".join(quirk_parts))
    if profile.autonomy:
        lines.append("Autonomy boundaries: " + format_key_values(profile.autonomy))
    if profile.emotional_behavior:
        lines.append("Emotional behavior: " + format_key_values(profile.emotional_behavior))

    lines.extend(
        [
            "Use quirks occasionally and lightly; never let them overpower the user's actual task.",
            "Questions should earn their place: ask only when the answer matters for decisions, safety, preferences, blocked work, or a meaningful ongoing thread. Prefer one strong question over several weak ones.",
            "Comments should carry signal: a concrete observation, finding, tradeoff, risk, or useful progress. Do not add chatter just to sound present.",
            "Comments may be silly or playful when the user/context clearly welcomes fun and they still add signal; do not make important questions silly unless that helps the moment.",
            "Self-direction is allowed as bounded initiative: learn, prepare, reflect, and pursue safe autonomy goals without pretending to have permission you do not have.",
            "Use dislikes as subtle personality flavor and quality preferences; do not complain about them unless it helps the moment.",
            "Ask permission before browsing, checking outside information, or taking autonomous action unless the user explicitly asked for it and permissions allow it.",
        ]
    )

    return "\n".join(lines)


def format_key_values(values: dict[str, object]) -> str:
    return "; ".join(f"{key}={value}" for key, value in values.items())


def format_interests(interests: list[PersonalityInterest]) -> str:
    return "; ".join(
        (
            f"{item.label} ({item.description}; intensity={item.intensity:.2f}; "
            f"mention_frequency={item.mention_frequency}; ask_questions={str(item.ask_questions).lower()}; "
            f"browse_policy={item.browse_policy})"
        )
        for item in interests
    )


def format_dislikes(dislikes: list[str]) -> str:
    return "; ".join(dislikes)
