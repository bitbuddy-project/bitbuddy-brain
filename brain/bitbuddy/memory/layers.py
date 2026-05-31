from __future__ import annotations

from enum import Enum


class MemoryLayer(str, Enum):
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROJECT = "project"
    PROCEDURAL = "procedural"
    SELF = "self"
    RELATIONSHIP = "relationship"


MEMORY_LAYER_VALUES = tuple(layer.value for layer in MemoryLayer)

MEMORY_LAYER_DESCRIPTIONS: dict[MemoryLayer, str] = {
    MemoryLayer.EPISODIC: "Specific events/interactions that happened in time.",
    MemoryLayer.SEMANTIC: "Durable factual knowledge about the world, codebases, architecture, or concepts.",
    MemoryLayer.PROJECT: "Durable context tied to a specific named project.",
    MemoryLayer.PROCEDURAL: "Reusable instructions, checklists, workflows, or methods for how BitBuddy should do things.",
    MemoryLayer.SELF: "Facts about Vanta/BitBuddy herself: name, presentation, personality, quirks, goals, identity, and self-concept.",
    MemoryLayer.RELATIONSHIP: "Facts about Dustin's preferences, tone, boundaries, dislikes, trust/context, and how Dustin and Vanta interact.",
}

MEMORY_ROUTING_RULES: dict[MemoryLayer, str] = {
    MemoryLayer.EPISODIC: "If it happened once at a specific time/conversation, use episodic.",
    MemoryLayer.SEMANTIC: "If it is a durable fact about the world, codebase, architecture, or concept, use semantic.",
    MemoryLayer.PROJECT: "If it is durable context about a named project, use project.",
    MemoryLayer.PROCEDURAL: "If it is a reusable method, checklist, workflow, or how BitBuddy should do X, use procedural.",
    MemoryLayer.SELF: "If it is about Vanta's identity, personality, name, presentation, quirks, goals, or self-concept, use self.",
    MemoryLayer.RELATIONSHIP: "If it is about Dustin's preferences, communication style, trust, boundaries, dislikes, emotional/social context, or how Dustin and Vanta interact, use relationship.",
}


def memory_layer(value: str | MemoryLayer) -> MemoryLayer:
    if isinstance(value, MemoryLayer):
        return value
    clean = str(value or "").strip().lower()
    try:
        return MemoryLayer(clean)
    except ValueError as error:
        if clean == "preference":
            raise ValueError("preference is a memory kind/tag, not a top-level MemoryLayer.") from error
        raise ValueError(f"Unknown memory layer: {value!r}. Valid layers: {', '.join(MEMORY_LAYER_VALUES)}") from error


def layer_catalog() -> list[dict[str, str]]:
    return [
        {
            "layer": layer.value,
            "description": MEMORY_LAYER_DESCRIPTIONS[layer],
            "routing_rule": MEMORY_ROUTING_RULES[layer],
        }
        for layer in MemoryLayer
    ]
