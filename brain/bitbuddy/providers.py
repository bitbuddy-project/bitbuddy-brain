from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Iterable, Literal

from .config import ProviderConfig


StreamKind = Literal["thinking", "response"]
STREAM_READ_TIMEOUT_SECONDS = 900
NO_THINKING_SYSTEM_MESSAGE = (
    "Thinking/reasoning mode is disabled for this request. "
    "Do not emit hidden reasoning, reasoning_content, or <think> blocks; answer directly."
)


@dataclass(frozen=True)
class StreamChunk:
    kind: StreamKind
    text: str


class ThinkingSplitter:
    """Separates <think>...</think> content from normal model output."""

    def __init__(self, *, emit_thinking: bool = True) -> None:
        self.emit_thinking = emit_thinking
        self.in_thinking = False
        self.buffer = ""

    def feed(self, text: str) -> list[StreamChunk]:
        self.buffer += text
        chunks: list[StreamChunk] = []

        while self.buffer:
            if self.in_thinking:
                end = self.buffer.find("</think>")
                if end == -1:
                    if self.emit_thinking:
                        chunks.append(StreamChunk("thinking", self.buffer))
                    self.buffer = ""
                    break
                if end > 0:
                    if self.emit_thinking:
                        chunks.append(StreamChunk("thinking", self.buffer[:end]))
                self.buffer = self.buffer[end + len("</think>") :]
                self.in_thinking = False
                continue

            start = self.buffer.find("<think>")
            if start == -1:
                keep = longest_tag_prefix(self.buffer, "<think>")
                emit = self.buffer[: len(self.buffer) - keep]
                self.buffer = self.buffer[len(self.buffer) - keep :]
                if emit:
                    chunks.append(StreamChunk("response", emit))
                break
            if start > 0:
                chunks.append(StreamChunk("response", self.buffer[:start]))
            self.buffer = self.buffer[start + len("<think>") :]
            self.in_thinking = True

        return chunks

    def flush(self) -> list[StreamChunk]:
        if not self.buffer:
            return []
        kind: StreamKind = "thinking" if self.in_thinking else "response"
        if kind == "thinking" and not self.emit_thinking:
            self.buffer = ""
            return []
        chunk = StreamChunk(kind, self.buffer)
        self.buffer = ""
        return [chunk]


class ProviderClient:
    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    def health(self) -> tuple[bool, str]:
        if self.config.type == "none":
            return False, "No provider configured."
        last_error = ""
        for endpoint in provider_health_endpoints(self.config):
            try:
                request = urllib.request.Request(endpoint, headers={"Accept": "application/json"})
                with urllib.request.urlopen(request, timeout=2) as response:
                    if response.status < 400:
                        return True, f"{self.config.type} reachable at {self.config.url}"
            except (OSError, urllib.error.URLError) as error:
                last_error = str(error)
        detail = f": {last_error}" if last_error else ""
        return False, f"{self.config.type} not reachable at {self.config.url}{detail}"

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        should_cancel: Callable[[], bool] | None = None,
        thinking_enabled: bool = True,
    ) -> Iterable[StreamChunk]:
        if self.config.type == "ollama":
            yield from self._stream_ollama(messages, model or self.config.model, should_cancel, thinking_enabled)
            return
        if self.config.type == "llama.cpp":
            yield from self._stream_llama_cpp(messages, model or self.config.model, should_cancel, thinking_enabled)
            return
        raise ValueError("No model provider configured.")

    def models(self) -> list[str]:
        if self.config.type == "ollama":
            data = get_json(f"{self.config.url.rstrip('/')}/api/tags")
            return sorted(str(model.get("name")) for model in data.get("models", []) if model.get("name"))
        if self.config.type == "llama.cpp":
            data = get_json(f"{self.config.url.rstrip('/')}/v1/models")
            return sorted(str(model.get("id")) for model in data.get("data", []) if model.get("id"))
        raise ValueError("No model provider configured.")

    def context_window(self, model: str | None = None) -> dict[str, object]:
        selected_model = model or self.config.model
        result: dict[str, object] = {
            "provider": self.config.type,
            "model": selected_model,
            "context_window_tokens": None,
            "source": "unknown",
        }
        if self.config.type == "ollama":
            if not selected_model:
                return result
            try:
                data = post_json(f"{self.config.url.rstrip('/')}/api/show", {"model": selected_model})
            except (OSError, urllib.error.URLError):
                return result
            tokens = first_int(
                nested_get(data, ["model_info", "llama.context_length"]),
                nested_get(data, ["model_info", "general.context_length"]),
                nested_get(data, ["model_info", "qwen2.context_length"]),
                nested_get(data, ["model_info", "gemma3.context_length"]),
                data.get("parameters"),
            )
            result["context_window_tokens"] = tokens
            result["source"] = "ollama /api/show" if tokens else "ollama /api/show unavailable"
            return result
        if self.config.type == "llama.cpp":
            try:
                data = get_json(f"{self.config.url.rstrip('/')}/props")
            except (OSError, urllib.error.URLError):
                return result
            tokens = first_int(
                data.get("n_ctx"),
                nested_get(data, ["default_generation_settings", "n_ctx"]),
                nested_get(data, ["default_generation_settings", "ctx_size"]),
            )
            result["context_window_tokens"] = tokens
            result["source"] = "llama.cpp /props" if tokens else "llama.cpp /props unavailable"
            return result
        return result

    def count_tokens(self, messages: list[dict[str, str]], model: str | None = None) -> dict[str, object]:
        selected_model = model or self.config.model
        result: dict[str, object] = {
            "provider": self.config.type,
            "model": selected_model,
            "used_tokens": None,
            "source": "unknown",
        }
        prompt = serialize_messages_for_token_count(messages)
        if self.config.type == "ollama":
            if not selected_model:
                return result
            try:
                data = post_json(f"{self.config.url.rstrip('/')}/api/tokenize", {"model": selected_model, "prompt": prompt})
            except (OSError, urllib.error.URLError, urllib.error.HTTPError):
                return result
            tokens = data.get("tokens")
            result["used_tokens"] = len(tokens) if isinstance(tokens, list) else first_int(data.get("count"), data.get("token_count"))
            result["source"] = "ollama /api/tokenize" if result["used_tokens"] is not None else "ollama token count unavailable"
            return result
        if self.config.type == "llama.cpp":
            try:
                data = post_json(f"{self.config.url.rstrip('/')}/tokenize", {"content": prompt})
            except (OSError, urllib.error.URLError, urllib.error.HTTPError):
                return result
            tokens = data.get("tokens")
            result["used_tokens"] = len(tokens) if isinstance(tokens, list) else first_int(data.get("count"), data.get("token_count"))
            result["source"] = "llama.cpp /tokenize" if result["used_tokens"] is not None else "llama.cpp token count unavailable"
            return result
        return result

    def _stream_ollama(
        self,
        messages: list[dict[str, Any]],
        model: str,
        should_cancel: Callable[[], bool] | None = None,
        thinking_enabled: bool = True,
    ) -> Iterable[StreamChunk]:
        if not model:
            raise ValueError("Ollama requires a model name.")
        payload = {
            "model": model,
            "messages": ollama_messages(provider_messages(messages, thinking_enabled=thinking_enabled)),
            "stream": True,
            "think": thinking_enabled,
            "options": {
                "num_ctx": 16384,
            },
        }
        splitter = ThinkingSplitter(emit_thinking=thinking_enabled)
        try:
            for data in post_json_lines(f"{self.config.url.rstrip('/')}/api/chat", payload):
                if should_cancel and should_cancel():
                    break
                message = data.get("message") or {}
                thinking = data.get("thinking") or message.get("thinking") or data.get("reasoning")
                if thinking and thinking_enabled:
                    yield StreamChunk("thinking", str(thinking))
                content = message.get("content") or data.get("response") or ""
                if content:
                    yield from splitter.feed(str(content))
        except urllib.error.HTTPError as error:
            if error.code == 400 and messages_have_image_attachments(messages):
                yield StreamChunk("response", image_rejected_message(self.config.type, model, error))
                return
            raise
        if not should_cancel or not should_cancel():
            yield from splitter.flush()

    def _stream_llama_cpp(
        self,
        messages: list[dict[str, Any]],
        model: str,
        should_cancel: Callable[[], bool] | None = None,
        thinking_enabled: bool = True,
    ) -> Iterable[StreamChunk]:
        payload = {
            "messages": openai_messages(provider_messages(messages, thinking_enabled=thinking_enabled)),
            "stream": True,
            "chat_template_kwargs": {
                "enable_thinking": thinking_enabled,
            },
        }
        if not thinking_enabled:
            payload["reasoning_format"] = "none"
            payload["thinking_budget_tokens"] = 0
            payload["reasoning_budget_tokens"] = 0
        if model:
            payload["model"] = model
        splitter = ThinkingSplitter(emit_thinking=thinking_enabled)
        try:
            for data in post_sse_json(f"{self.config.url.rstrip('/')}/v1/chat/completions", payload):
                if should_cancel and should_cancel():
                    break
                choices = data.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                if reasoning and thinking_enabled:
                    yield StreamChunk("thinking", str(reasoning))
                content = delta.get("content") or ""
                if content:
                    yield from splitter.feed(str(content))
        except urllib.error.HTTPError as error:
            if error.code == 400 and messages_have_image_attachments(messages):
                yield StreamChunk("response", image_rejected_message(self.config.type, model, error))
                return
            raise
        if not should_cancel or not should_cancel():
            yield from splitter.flush()


def provider_health_endpoints(config: ProviderConfig) -> list[str]:
    if config.type == "ollama":
        return [f"{config.url.rstrip('/')}/api/tags"]
    if config.type == "llama.cpp":
        return [f"{config.url.rstrip('/')}/health", f"{config.url.rstrip('/')}/v1/models"]
    return [config.url]


def post_json_lines(url: str, payload: dict[str, object]) -> Iterable[dict[str, object]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=STREAM_READ_TIMEOUT_SECONDS) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if line:
                yield json.loads(line)


def post_json(url: str, payload: dict[str, object]) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def get_json(url: str) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def nested_get(data: dict[str, object], path: list[str]) -> object:
    value: object = data
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def first_int(*values: object) -> int | None:
    for value in values:
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str):
            for part in value.replace("=", " ").split():
                try:
                    parsed = int(part)
                except ValueError:
                    continue
                if parsed > 0:
                    return parsed
    return None


def post_sse_json(url: str, payload: dict[str, object]) -> Iterable[dict[str, object]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=STREAM_READ_TIMEOUT_SECONDS) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            data = line.removeprefix("data:").strip()
            if data == "[DONE]":
                break
            yield json.loads(data)


def ollama_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in messages:
        clean = {"role": message.get("role", "user"), "content": str(message.get("content", ""))}
        images = [str(image.get("data") or "") for image in image_attachments(message) if image.get("data")]
        if images:
            clean["images"] = images
        result.append(clean)
    return result


def provider_messages(messages: list[dict[str, Any]], *, thinking_enabled: bool) -> list[dict[str, Any]]:
    if thinking_enabled:
        return messages
    return [{"role": "system", "content": NO_THINKING_SYSTEM_MESSAGE}, *messages]


def openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for message in messages:
        images = image_attachments(message)
        if not images:
            result.append({"role": message.get("role", "user"), "content": str(message.get("content", ""))})
            continue

        content: list[dict[str, Any]] = [{"type": "text", "text": str(message.get("content", ""))}]
        for image in images:
            data = str(image.get("data") or "")
            if not data:
                continue
            mime_type = str(image.get("mime_type") or "image/png")
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{data}"}})
        result.append({"role": message.get("role", "user"), "content": content})
    return result


def image_attachments(message: dict[str, Any]) -> list[dict[str, Any]]:
    attachments = message.get("attachments") if isinstance(message.get("attachments"), list) else []
    return [attachment for attachment in attachments if isinstance(attachment, dict)]


def messages_have_image_attachments(messages: list[dict[str, Any]]) -> bool:
    return any(image_attachments(message) for message in messages)


def image_rejected_message(provider: str, model: str, error: urllib.error.HTTPError) -> str:
    detail = http_error_detail(error)
    suffix = f" Provider detail: {detail}" if detail else ""
    model_label = f" `{model}`" if model else ""
    return (
        f"I couldn't inspect that image because {provider}{model_label} could not load the uploaded image data. "
        "The model may support vision, but this image still needs to be a decodable PNG, JPEG, or WebP."
        f"{suffix}"
    )


def http_error_detail(error: urllib.error.HTTPError) -> str:
    try:
        raw = error.read().decode("utf-8", errors="replace").strip()
    except Exception:
        return ""
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:500]
    if isinstance(parsed, dict):
        for key in ("error", "message", "detail"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:500]
    return raw[:500]


def serialize_messages_for_token_count(messages: list[dict[str, Any]]) -> str:
    return "\n\n".join(f"{message.get('role', 'user')}:\n{message.get('content', '')}" for message in messages)


def longest_tag_prefix(text: str, tag: str) -> int:
    max_len = min(len(text), len(tag) - 1)
    for size in range(max_len, 0, -1):
        if tag.startswith(text[-size:]):
            return size
    return 0
