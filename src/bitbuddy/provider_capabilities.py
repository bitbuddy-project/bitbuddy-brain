from __future__ import annotations

from typing import Any


def provider_capability_profile(
    provider_type: str,
    model: str,
    *,
    context_window_tokens: int | None = None,
    native_tools: bool | None = None,
) -> dict[str, Any]:
    provider = (provider_type or "none").strip()
    name = (model or "").strip()
    lower = name.lower()
    reasoning_efforts = reasoning_efforts_for_model(provider, name)
    supports_thinking = provider in {"ollama", "llama.cpp", "openai", "codex", "anthropic", "z.ai", "z.ai-coding"}
    supports_reasoning_effort = any(effort != "off" for effort in reasoning_efforts)
    return {
        "provider": provider,
        "model": name,
        "context_window_tokens": context_window_tokens,
        "streaming_protocol": streaming_protocol(provider),
        "supports_native_tools": bool(native_tools) if native_tools is not None else provider in {"openai", "codex", "anthropic", "z.ai", "z.ai-coding"},
        "supports_vision": supports_vision(provider, lower),
        "supports_thinking": supports_thinking,
        "requires_thinking": provider == "anthropic" and anthropic_model_requires_thinking(lower),
        "supports_reasoning_effort": supports_reasoning_effort,
        "reasoning_efforts": reasoning_efforts,
        "default_reasoning_effort": default_reasoning_effort(provider, reasoning_efforts),
    }


def streaming_protocol(provider: str) -> str:
    if provider == "ollama":
        return "ollama-json-lines"
    if provider == "anthropic":
        return "anthropic-messages-sse"
    if provider in {"openai", "codex"}:
        return "openai-responses-sse"
    if provider in {"llama.cpp", "z.ai", "z.ai-coding"}:
        return "openai-chat-completions-sse"
    return "none"


def supports_vision(provider: str, model: str) -> bool:
    if provider in {"z.ai", "z.ai-coding"}:
        return "5v" in model
    if provider == "openai":
        return "gpt-4o" in model or "gpt-4.1" in model or "gpt-5" in model or "vision" in model
    if provider == "anthropic":
        return model.startswith("claude-") and "haiku-3" not in model
    if provider == "ollama":
        return any(marker in model for marker in ("vision", "llava", "bakllava", "moondream", "gemma3"))
    return False


def reasoning_efforts_for_model(provider: str, model: str) -> list[str]:
    name = (model or "").lower()
    if provider in {"openai", "codex"}:
        efforts = ["off", "low", "medium", "high", "xhigh"]
        if name.startswith("gpt-5.6"):
            efforts.append("max")
        return efforts
    if provider in {"z.ai", "z.ai-coding"}:
        return ["off", "high", "max"] if name.startswith("glm-5") else ["off"]
    if provider == "anthropic":
        if anthropic_model_requires_thinking(name):
            return ["low", "medium", "high", "xhigh", "max"]
        if anthropic_model_supports_xhigh(name):
            return ["off", "low", "medium", "high", "xhigh", "max"]
        if anthropic_model_supports_max(name):
            return ["off", "low", "medium", "high", "max"]
        if anthropic_model_supports_effort(name):
            return ["off", "low", "medium", "high"]
    return []


def anthropic_model_requires_thinking(model: str) -> bool:
    """Whether the model only accepts Anthropic's adaptive-thinking path."""
    return "fable-5" in (model or "").lower()


def anthropic_model_supports_effort(model: str) -> bool:
    return any(
        marker in model
        for marker in (
            "fable-5",
            "mythos-5",
            "opus-4-8",
            "opus-4-7",
            "opus-4-6",
            "sonnet-5",
            "sonnet-4-6",
            "opus-4-5",
        )
    )


def anthropic_model_supports_max(model: str) -> bool:
    return any(
        marker in model
        for marker in (
            "fable-5",
            "mythos-5",
            "opus-4-8",
            "opus-4-7",
            "opus-4-6",
            "sonnet-5",
            "sonnet-4-6",
        )
    )


def anthropic_model_supports_xhigh(model: str) -> bool:
    return any(marker in model for marker in ("fable-5", "mythos-5", "opus-4-8", "opus-4-7", "sonnet-5"))


def default_reasoning_effort(provider: str, efforts: list[str]) -> str:
    if not efforts:
        return ""
    if provider in {"z.ai", "z.ai-coding"}:
        return "high" if "high" in efforts else efforts[0]
    return "medium" if "medium" in efforts else efforts[0]
