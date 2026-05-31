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
                        "Autonomy is for developing context, curiosity, memory, and future intentions while the user is away.",
                        "Favor generate_user_prompts when the recent context suggests a useful question or comment could make BitBuddy feel more present, curious, or alive.",
                        "Never choose destructive work. No shell, no project mutation, no system changes, no messages sent to the user.",
                        "Return only valid JSON: {\"activity\":\"...\",\"reason\":\"...\",\"inputs\":{...}}",
                        "Allowed activities: web_curiosity, project_familiarization, generate_user_prompts, self_reflection, network_observation, do_nothing.",
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
