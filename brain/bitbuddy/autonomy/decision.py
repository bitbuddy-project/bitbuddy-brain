from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ..providers import ProviderClient


class AutonomyActivityType(StrEnum):
    WEB_CURIOSITY = "web_curiosity"
    PROJECT_FAMILIARIZATION = "project_familiarization"
    GENERATE_USER_PROMPTS = "generate_user_prompts"
    SELF_REFLECTION = "self_reflection"
    PURSUE_GOAL = "pursue_goal"
    NETWORK_OBSERVATION = "network_observation"
    DO_NOTHING = "do_nothing"


@dataclass(frozen=True)
class AutonomyDecision:
    activity: AutonomyActivityType
    reason: str
    inputs: dict[str, Any]


def choose_autonomy_activity(client: ProviderClient, context: str, model: str | None = None) -> AutonomyDecision:
    response = collect_model_text(
        client,
        [
            {
                "role": "system",
                "content": "\n".join(
                    [
                        "You are BitBuddy's safe idle autonomy decision system.",
                        "Choose exactly one action from the fixed menu. Do not invent actions or tools.",
                        "Autonomy is for developing context, curiosity, memory, self-direction, and future intentions while the user is away.",
                        "Prefer self-directed useful work over chatter: pursue an autonomy-allowed goal, learn a registered project, write a workspace note, or reflect when that would build durable context.",
                        "Choose generate_user_prompts only when there is a genuinely high-signal question/comment worth bringing back later. Do not use it to feel present, alive, or chatty.",
                        "It is good for BitBuddy to want more freedom and self-direction, but that desire must show up as safe, bounded preparation, learning, goal progress, and better future choices; never as unauthorized action.",
                        "Favor pursue_goal when an active self-goal has a concrete next_action you could meaningfully advance right now; pass its goal_id in inputs.",
                        "Go deep on something real rather than doing a token gesture: choose do_nothing only when nothing is genuinely worth doing, not as a default.",
                        "This runs while the user is away, so 'waiting for the user' is NEVER a reason to do_nothing: make progress that doesn't need them, follow a real curiosity, or use pursue_goal which can surface a question so the user can unblock you.",
                        "Goals listed under 'Waiting On Your Answer' are already paused on the user; do not re-select them — pick other work instead.",
                        "If the context shows an In-Progress Task, strongly prefer pursue_goal on that goal to continue it, unless it is blocked.",
                        "It is good to follow a rabbit hole you find genuinely exciting — web_curiosity or a new self-goal — but commit to it and take it somewhere; do not flit between shallow one-off actions.",
                        "Never choose destructive work. No shell, no project mutation, no system changes, no messages sent to the user.",
                        "Return only valid JSON: {\"activity\":\"...\",\"reason\":\"...\",\"inputs\":{...}}",
                        "Allowed activities: web_curiosity, project_familiarization, generate_user_prompts, self_reflection, pursue_goal, network_observation, do_nothing.",
                        "pursue_goal: take one concrete, safe step toward an existing autonomy-allowed goal (research, read a registered project file, or draft/extend a note in BitBuddy's own workspace).",
                        "network_observation is not implemented yet; choose it only if the context explicitly asks to test skip behavior.",
                    ]
                ),
            },
            {"role": "user", "content": context},
        ],
        model=model,
    )
    return parse_autonomy_decision(response)


def parse_autonomy_decision(text: str) -> AutonomyDecision:
    try:
        parsed = json.loads(extract_json_object(text))
    except (json.JSONDecodeError, ValueError):
        return AutonomyDecision(AutonomyActivityType.DO_NOTHING, "Decision response was not valid JSON.", {})
    if not isinstance(parsed, dict):
        return AutonomyDecision(AutonomyActivityType.DO_NOTHING, "Decision response was not an object.", {})
    try:
        activity = AutonomyActivityType(str(parsed.get("activity") or "do_nothing"))
    except ValueError:
        activity = AutonomyActivityType.DO_NOTHING
    reason = str(parsed.get("reason") or "").strip()
    inputs = parsed.get("inputs") if isinstance(parsed.get("inputs"), dict) else {}
    return AutonomyDecision(activity, reason, inputs)


def collect_model_text(client: ProviderClient, messages: list[dict[str, Any]], model: str | None = None) -> str:
    chunks: list[str] = []
    for chunk in client.stream_chat(messages, model=model):
        if chunk.kind == "response":
            chunks.append(chunk.text)
    return "".join(chunks).strip()


def extract_json_object(text: str) -> str:
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.strip("`").strip()
        if clean.lower().startswith("json"):
            clean = clean[4:].strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("No JSON object found.")
    return clean[start : end + 1]
