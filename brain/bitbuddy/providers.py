from __future__ import annotations

import json
import base64
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from collections.abc import Callable
from typing import Any, Iterable, Literal

from .config import ProviderConfig
from .calendar.secrets import get_credentials


StreamKind = Literal["thinking", "response", "tool_call"]
STREAM_READ_TIMEOUT_SECONDS = 900
NATIVE_TOOL_PROBE_TIMEOUT_SECONDS = 30
CODEX_SECRET_REF = "provider:codex:oauth"
CODEX_BACKEND_URL = "https://chatgpt.com/backend-api/codex/responses"
CODEX_DEFAULT_MODEL = "gpt-5.5"
CODEX_CHATGPT_MODELS = ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini"]
NO_THINKING_SYSTEM_MESSAGE = (
    "Thinking/reasoning mode is disabled for this request. "
    "Do not emit hidden reasoning, reasoning_content, or <think> blocks; answer directly."
)


def reasoning_budget_tokens() -> int:
    """Configured reasoning budget for thinking turns (-1 = unlimited)."""
    try:
        from .config import load_config

        return load_config().chat.reasoning_budget_tokens
    except Exception:
        return -1


@dataclass(frozen=True)
class StreamToolCall:
    """A complete native (function-calling) tool call assembled from the stream."""

    name: str
    arguments: str  # raw JSON string as emitted by the provider
    call_id: str = ""


@dataclass(frozen=True)
class StreamChunk:
    kind: StreamKind
    text: str
    tool_call: "StreamToolCall | None" = None


# Per-process cache for native-tool capability, keyed by (type, url, model).
_native_tools_cache: dict[tuple[str, str, str], bool] = {}


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
        if self.config.type in {"openai", "anthropic"} and not self.config.api_key:
            return False, f"{self.config.type} API key is not configured."
        if self.config.type == "codex":
            return codex_health()
        last_error = ""
        for endpoint in provider_health_endpoints(self.config):
            try:
                request = urllib.request.Request(endpoint, headers=provider_headers(self.config, accept="application/json"))
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
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> Iterable[StreamChunk]:
        if self.config.type == "ollama":
            yield from self._stream_ollama(messages, model or self.config.model, should_cancel, thinking_enabled, tools, tool_choice)
            return
        if self.config.type == "llama.cpp":
            yield from self._stream_llama_cpp(messages, model or self.config.model, should_cancel, thinking_enabled, tools, tool_choice)
            return
        if self.config.type == "openai":
            yield from self._stream_openai(messages, model or self.config.model, should_cancel, thinking_enabled, tools, tool_choice)
            return
        if self.config.type == "anthropic":
            yield from self._stream_anthropic(messages, model or self.config.model, should_cancel, thinking_enabled, tools)
            return
        if self.config.type == "codex":
            yield from self._stream_codex(messages, model or self.config.model, should_cancel)
            return
        raise ValueError("No model provider configured.")

    def supports_native_tools(self, model: str | None = None) -> bool:
        """Whether the provider reliably supports OpenAI-style native tool calling.

        Honors config.provider.native_tools ("auto" | "on" | "off"). On "auto" this
        runs one cheap probe and caches the result for the process lifetime; on any
        failure it returns False so callers fall back to the text tool protocol.
        """
        setting = str(getattr(self.config, "native_tools", "auto") or "auto").lower()
        if setting == "off" or self.config.type not in ("llama.cpp", "ollama", "openai", "anthropic"):
            return False
        if self.config.type in {"openai", "anthropic"}:
            return True
        if setting == "on":
            return True
        selected = model or self.config.model
        key = (self.config.type, self.config.url, selected)
        if key not in _native_tools_cache:
            _native_tools_cache[key] = self._probe_native_tools(selected)
        return _native_tools_cache[key]

    def _probe_native_tools(self, model: str) -> bool:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "_probe",
                    "description": "Capability probe. Call it once to confirm tool support.",
                    "parameters": {
                        "type": "object",
                        "properties": {"ok": {"type": "boolean"}},
                        "required": ["ok"],
                    },
                },
            }
        ]
        messages = [{"role": "user", "content": "Call the _probe tool with ok=true now."}]
        try:
            if self.config.type == "llama.cpp":
                payload: dict[str, object] = {"messages": messages, "tools": tools, "tool_choice": "auto", "stream": False, "max_tokens": 64}
                if model:
                    payload["model"] = model
                data = post_json(f"{self.config.url.rstrip('/')}/v1/chat/completions", payload, timeout=NATIVE_TOOL_PROBE_TIMEOUT_SECONDS)
                choices = data.get("choices") or []
                message = (choices[0].get("message") if choices else {}) or {}
                return bool(message.get("tool_calls"))
            payload = {"model": model, "messages": messages, "tools": tools, "stream": False}
            data = post_json(f"{self.config.url.rstrip('/')}/api/chat", payload, timeout=NATIVE_TOOL_PROBE_TIMEOUT_SECONDS)
            message = data.get("message") or {}
            return bool(message.get("tool_calls"))
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, ValueError, KeyError, IndexError):
            return False

    def models(self) -> list[str]:
        if self.config.type == "ollama":
            data = get_json(f"{self.config.url.rstrip('/')}/api/tags")
            return sorted(str(model.get("name")) for model in data.get("models", []) if model.get("name"))
        if self.config.type == "llama.cpp":
            data = get_json(f"{self.config.url.rstrip('/')}/v1/models")
            return sorted(str(model.get("id")) for model in data.get("data", []) if model.get("id"))
        if self.config.type == "openai":
            data = get_json(f"{self.config.url.rstrip('/')}/v1/models", headers=provider_headers(self.config))
            return sorted(str(model.get("id")) for model in data.get("data", []) if model.get("id"))
        if self.config.type == "anthropic":
            data = get_json(f"{self.config.url.rstrip('/')}/v1/models", headers=provider_headers(self.config))
            rows = data.get("data") or data.get("models") or []
            return sorted(str(model.get("id")) for model in rows if isinstance(model, dict) and model.get("id"))
        if self.config.type == "codex":
            return CODEX_CHATGPT_MODELS
        raise ValueError("No model provider configured.")

    def context_window(self, model: str | None = None) -> dict[str, object]:
        selected_model = model or self.config.model
        if self.config.type == "codex":
            selected_model = codex_model(selected_model)
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
        if self.config.type == "codex":
            result["context_window_tokens"] = codex_context_window(codex_model(self.config.model))
            result["source"] = "Codex model metadata"
            return result
        if self.config.type == "openai":
            result["context_window_tokens"] = openai_context_window(self.config.model)
            result["source"] = "OpenAI model metadata" if result["context_window_tokens"] else "OpenAI context metadata unavailable"
            return result
        if self.config.type == "anthropic":
            result["context_window_tokens"] = 200000
            result["source"] = "Anthropic model metadata"
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
        if self.config.type in {"openai", "codex", "anthropic"}:
            result["source"] = f"{self.config.type} token count unavailable"
            return result
        return result

    def embedding_model_name(self, model: str | None = None) -> str:
        return (model or getattr(self.config, "embedding_model", "") or "").strip()

    def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """Return embedding vectors for texts. Empty list when unavailable (caller falls back to FTS)."""
        clean_texts = [str(text or "").strip() for text in texts]
        if not clean_texts or all(not text for text in clean_texts):
            return []
        selected_model = self.embedding_model_name(model)
        base_url = (getattr(self.config, "embedding_url", "") or self.config.url).rstrip("/")

        if self.config.type == "ollama":
            if not selected_model:
                return []
            vectors: list[list[float]] = []
            for text in clean_texts:
                try:
                    data = post_json(f"{base_url}/api/embeddings", {"model": selected_model, "prompt": text})
                except (OSError, urllib.error.URLError, urllib.error.HTTPError):
                    return []
                embedding = data.get("embedding")
                if not isinstance(embedding, list) or not embedding:
                    return []
                vectors.append([float(value) for value in embedding])
            return vectors

        if self.config.type == "llama.cpp":
            payload: dict[str, object] = {"input": clean_texts}
            if selected_model:
                payload["model"] = selected_model
            try:
                data = post_json(f"{base_url}/v1/embeddings", payload)
            except (OSError, urllib.error.URLError, urllib.error.HTTPError):
                return []
            rows = data.get("data")
            if not isinstance(rows, list) or not rows:
                return []
            vectors = []
            for row in rows:
                embedding = row.get("embedding") if isinstance(row, dict) else None
                if not isinstance(embedding, list) or not embedding:
                    return []
                vectors.append([float(value) for value in embedding])
            return vectors

        return []

    def _stream_ollama(
        self,
        messages: list[dict[str, Any]],
        model: str,
        should_cancel: Callable[[], bool] | None = None,
        thinking_enabled: bool = True,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
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
        if tools:
            payload["tools"] = tools
        splitter = ThinkingSplitter(emit_thinking=thinking_enabled)
        try:
            for data in post_json_lines(f"{self.config.url.rstrip('/')}/api/chat", payload):
                if should_cancel and should_cancel():
                    break
                message = data.get("message") or {}
                thinking = data.get("thinking") or message.get("thinking") or data.get("reasoning")
                if thinking and thinking_enabled:
                    yield StreamChunk("thinking", str(thinking))
                # Ollama returns fully-formed tool calls (arguments as an object), not fragments.
                for call in message.get("tool_calls") or []:
                    function = call.get("function") or {} if isinstance(call, dict) else {}
                    name = str(function.get("name") or "").strip()
                    if not name:
                        continue
                    raw_arguments = function.get("arguments")
                    arguments = json.dumps(raw_arguments) if isinstance(raw_arguments, (dict, list)) else str(raw_arguments or "{}")
                    yield StreamChunk("tool_call", "", StreamToolCall(name=name, arguments=arguments))
                content = message.get("content") or data.get("response") or ""
                if content:
                    yield from splitter.feed(str(content))
        except urllib.error.HTTPError as error:
            if provider_image_error(error, messages):
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
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
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
        else:
            # Explicitly request a generous reasoning budget so the server does not
            # truncate mid-plan and inject a forced "answer now" continuation, which
            # pushes the model into narrating work instead of issuing tool calls.
            budget = reasoning_budget_tokens()
            payload["thinking_budget_tokens"] = budget
            payload["reasoning_budget_tokens"] = budget
        if model:
            payload["model"] = model
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        splitter = ThinkingSplitter(emit_thinking=thinking_enabled)
        tool_accumulator: dict[int, dict[str, str]] = {}
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
                for fragment in delta.get("tool_calls") or []:
                    accumulate_tool_call_fragment(tool_accumulator, fragment)
                content = delta.get("content") or ""
                if content:
                    yield from splitter.feed(str(content))
        except urllib.error.HTTPError as error:
            if provider_image_error(error, messages):
                yield StreamChunk("response", image_rejected_message(self.config.type, model, error))
                return
            raise
        if not should_cancel or not should_cancel():
            yield from splitter.flush()
            yield from emit_accumulated_tool_calls(tool_accumulator)

    def _stream_openai(
        self,
        messages: list[dict[str, Any]],
        model: str,
        should_cancel: Callable[[], bool] | None = None,
        thinking_enabled: bool = True,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
    ) -> Iterable[StreamChunk]:
        if not model:
            raise ValueError("OpenAI requires a model name.")
        if not self.config.api_key:
            raise ValueError("OpenAI API key is not configured.")
        payload: dict[str, object] = {
            "model": model,
            "messages": openai_messages(provider_messages(messages, thinking_enabled=thinking_enabled)),
            "stream": True,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice
        splitter = ThinkingSplitter(emit_thinking=thinking_enabled)
        tool_accumulator: dict[int, dict[str, str]] = {}
        try:
            for data in post_sse_json(f"{self.config.url.rstrip('/')}/v1/chat/completions", payload, headers=provider_headers(self.config, accept="text/event-stream")):
                if should_cancel and should_cancel():
                    break
                choices = data.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                if reasoning and thinking_enabled:
                    yield StreamChunk("thinking", str(reasoning))
                for fragment in delta.get("tool_calls") or []:
                    accumulate_tool_call_fragment(tool_accumulator, fragment)
                content = delta.get("content") or ""
                if content:
                    yield from splitter.feed(str(content))
        except urllib.error.HTTPError as error:
            if provider_image_error(error, messages):
                yield StreamChunk("response", image_rejected_message(self.config.type, model, error))
                return
            raise
        if not should_cancel or not should_cancel():
            yield from splitter.flush()
            yield from emit_accumulated_tool_calls(tool_accumulator)

    def _stream_anthropic(
        self,
        messages: list[dict[str, Any]],
        model: str,
        should_cancel: Callable[[], bool] | None = None,
        thinking_enabled: bool = True,
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterable[StreamChunk]:
        if not model:
            raise ValueError("Anthropic requires a model name.")
        if not self.config.api_key:
            raise ValueError("Anthropic API key is not configured.")
        system, anthropic_turns = anthropic_messages(provider_messages(messages, thinking_enabled=thinking_enabled))
        payload: dict[str, object] = {
            "model": model,
            "max_tokens": 4096,
            "stream": True,
            "messages": anthropic_turns,
        }
        if system:
            payload["system"] = system
        anthropic_tools = anthropic_tool_schema(tools or [])
        if anthropic_tools:
            payload["tools"] = anthropic_tools
            payload["tool_choice"] = {"type": "auto"}
        splitter = ThinkingSplitter(emit_thinking=thinking_enabled)
        tool_blocks: dict[int, dict[str, str]] = {}
        active_block_index = -1
        try:
            for event in post_anthropic_sse(f"{self.config.url.rstrip('/')}/v1/messages", payload, headers=provider_headers(self.config, accept="text/event-stream")):
                if should_cancel and should_cancel():
                    break
                kind = str(event.get("type") or "")
                if kind == "content_block_start":
                    index = int(event.get("index") or 0)
                    block = event.get("content_block") if isinstance(event.get("content_block"), dict) else {}
                    if block.get("type") == "tool_use":
                        active_block_index = index
                        tool_blocks[index] = {
                            "id": str(block.get("id") or ""),
                            "name": str(block.get("name") or ""),
                            "arguments": "",
                        }
                    continue
                if kind == "content_block_delta":
                    delta = event.get("delta") if isinstance(event.get("delta"), dict) else {}
                    delta_type = str(delta.get("type") or "")
                    if delta_type == "text_delta" and delta.get("text"):
                        yield from splitter.feed(str(delta.get("text")))
                    elif delta_type == "thinking_delta" and thinking_enabled and delta.get("thinking"):
                        yield StreamChunk("thinking", str(delta.get("thinking")))
                    elif delta_type == "input_json_delta":
                        index = int(event.get("index") if isinstance(event.get("index"), int) else active_block_index)
                        if index in tool_blocks:
                            tool_blocks[index]["arguments"] += str(delta.get("partial_json") or "")
                    continue
                if kind == "message_stop":
                    break
        except urllib.error.HTTPError as error:
            if provider_image_error(error, messages):
                yield StreamChunk("response", image_rejected_message(self.config.type, model, error))
                return
            raise
        if not should_cancel or not should_cancel():
            yield from splitter.flush()
            for index in sorted(tool_blocks):
                block = tool_blocks[index]
                if block.get("name"):
                    yield StreamChunk("tool_call", "", StreamToolCall(name=block["name"], arguments=block.get("arguments", ""), call_id=block.get("id", "")))

    def _stream_codex(
        self,
        messages: list[dict[str, Any]],
        model: str,
        should_cancel: Callable[[], bool] | None = None,
    ) -> Iterable[StreamChunk]:
        ok, message = codex_health()
        if not ok:
            raise ValueError(message)
        credentials = get_credentials(CODEX_SECRET_REF)
        access_token = credentials.get("access_token", "")
        account_id = credentials.get("account_id") or "ChatGPT"
        instructions, input_items = codex_response_payload(messages)
        payload = {
            "model": codex_model(model),
            "store": False,
            "stream": True,
            "instructions": instructions,
            "input": input_items,
            "text": {"verbosity": "medium"},
            "include": ["reasoning.encrypted_content"],
            "prompt_cache_key": str(uuid.uuid4()),
        }
        headers = {
            "Authorization": f"Bearer {access_token}",
            "chatgpt-account-id": account_id,
            "originator": "bitbuddy",
            "OpenAI-Beta": "responses=experimental",
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "session_id": str(uuid.uuid4()),
            "User-Agent": "BitBuddy/0.1",
        }
        try:
            for event in post_sse_json(CODEX_BACKEND_URL, payload, headers=headers):
                if should_cancel and should_cancel():
                    break
                text = codex_event_text(event)
                if text:
                    yield StreamChunk("response", text)
        except urllib.error.HTTPError as error:
            raise ValueError(codex_http_error_message(error)) from error


def accumulate_tool_call_fragment(accumulator: dict[int, dict[str, str]], fragment: dict[str, Any]) -> None:
    """Merge one streamed OpenAI tool_call delta fragment into the accumulator.

    Streamed tool calls arrive in pieces: the first fragment for an index carries
    the id and function name, later fragments append argument-string chunks.
    """
    if not isinstance(fragment, dict):
        return
    index = fragment.get("index")
    index = int(index) if isinstance(index, int) else 0
    slot = accumulator.setdefault(index, {"id": "", "name": "", "arguments": ""})
    call_id = fragment.get("id")
    if isinstance(call_id, str) and call_id:
        slot["id"] = call_id
    function = fragment.get("function") or {}
    if isinstance(function, dict):
        name = function.get("name")
        if isinstance(name, str) and name:
            slot["name"] = name
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            slot["arguments"] += arguments


def emit_accumulated_tool_calls(accumulator: dict[int, dict[str, str]]) -> Iterable[StreamChunk]:
    """Yield one tool_call StreamChunk per fully-assembled call, in index order."""
    for index in sorted(accumulator):
        slot = accumulator[index]
        if not slot.get("name"):
            continue
        yield StreamChunk(
            "tool_call",
            "",
            StreamToolCall(name=slot["name"], arguments=slot.get("arguments", ""), call_id=slot.get("id", "")),
        )


def provider_supports_native_tools(config: ProviderConfig, model: str | None = None) -> bool:
    """Convenience wrapper so prompt building and the runtime share the cached probe."""
    return ProviderClient(config).supports_native_tools(model)


def provider_health_endpoints(config: ProviderConfig) -> list[str]:
    if config.type == "ollama":
        return [f"{config.url.rstrip('/')}/api/tags"]
    if config.type == "llama.cpp":
        return [f"{config.url.rstrip('/')}/health", f"{config.url.rstrip('/')}/v1/models"]
    if config.type in {"openai", "anthropic"}:
        return [f"{config.url.rstrip('/')}/v1/models"]
    return [config.url]


def provider_headers(config: ProviderConfig, *, accept: str = "application/json") -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": accept}
    if config.type == "openai" and config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    elif config.type == "anthropic" and config.api_key:
        headers["x-api-key"] = config.api_key
        headers["anthropic-version"] = "2023-06-01"
    return headers


def post_json_lines(url: str, payload: dict[str, object], headers: dict[str, str] | None = None) -> Iterable[dict[str, object]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers or {"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=STREAM_READ_TIMEOUT_SECONDS) as response:
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if line:
                yield json.loads(line)


def post_json(url: str, payload: dict[str, object], timeout: int = 10, headers: dict[str, str] | None = None) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers or {"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8") or "{}")


def get_json(url: str, headers: dict[str, str] | None = None) -> dict[str, object]:
    request = urllib.request.Request(url, headers=headers or {"Accept": "application/json"})
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


def post_sse_json(url: str, payload: dict[str, object], headers: dict[str, str] | None = None) -> Iterable[dict[str, object]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers or {"Content-Type": "application/json", "Accept": "text/event-stream"},
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


def post_anthropic_sse(url: str, payload: dict[str, object], headers: dict[str, str]) -> Iterable[dict[str, object]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=STREAM_READ_TIMEOUT_SECONDS) as response:
        event_name = ""
        data_lines: list[str] = []
        for raw_line in response:
            line = raw_line.decode("utf-8").strip()
            if not line:
                if data_lines:
                    try:
                        event = json.loads("\n".join(data_lines))
                    except json.JSONDecodeError:
                        event = {}
                    if event_name and isinstance(event, dict) and "type" not in event:
                        event["type"] = event_name
                    yield event
                event_name = ""
                data_lines = []
                continue
            if line.startswith("event:"):
                event_name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data = line.removeprefix("data:").strip()
                if data and data != "[DONE]":
                    data_lines.append(data)


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


def anthropic_messages(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    system_parts: list[str] = []
    turns: list[dict[str, Any]] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = str(message.get("content") or "")
        if role == "system":
            if content.strip():
                system_parts.append(content.strip())
            continue
        if role not in {"user", "assistant"}:
            role = "user"
        parts: list[dict[str, Any]] = []
        if content.strip():
            parts.append({"type": "text", "text": content})
        for image in image_attachments(message):
            data = str(image.get("data") or "")
            if not data:
                continue
            parts.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": str(image.get("mime_type") or "image/png"),
                        "data": data,
                    },
                }
            )
        if not parts:
            continue
        turns.append({"role": role, "content": parts})
    if not turns:
        turns.append({"role": "user", "content": [{"type": "text", "text": "Hello."}]})
    return "\n\n".join(system_parts), merge_anthropic_turns(turns)


def merge_anthropic_turns(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for turn in turns:
        if merged and merged[-1].get("role") == turn.get("role"):
            previous = merged[-1].get("content")
            current = turn.get("content")
            if isinstance(previous, list) and isinstance(current, list):
                previous.extend(current)
                continue
        merged.append(turn)
    return merged


def anthropic_tool_schema(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        schema = function.get("parameters") if isinstance(function.get("parameters"), dict) else {"type": "object", "properties": {}}
        result.append(
            {
                "name": name,
                "description": str(function.get("description") or ""),
                "input_schema": schema,
            }
        )
    return result


def codex_health() -> tuple[bool, str]:
    credentials = get_credentials(CODEX_SECRET_REF)
    if credentials.get("access_token") and credentials.get("refresh_token"):
        account = credentials.get("account_id") or "ChatGPT"
        return True, f"Codex authorized for BitBuddy as {account}."
    return False, "Codex is not authorized for BitBuddy. Use Settings to connect Codex."


def codex_response_payload(messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    instructions: list[str] = [
        "You are BitBuddy's Codex-backed model provider.",
        "Answer directly unless the user asks for code changes.",
    ]
    input_items: list[dict[str, Any]] = []
    message_index = 0
    for message in messages:
        role = str(message.get("role") or "user")
        content = str(message.get("content") or "")
        if role == "system":
            if content.strip():
                instructions.append(content.strip())
            continue
        if role not in {"user", "assistant"}:
            role = "user"
        parts: list[dict[str, Any]] = []
        if content.strip():
            parts.append({"type": "input_text" if role == "user" else "output_text", "text": content, **({"annotations": []} if role == "assistant" else {})})
        for image in image_attachments(message):
            data = str(image.get("data") or "")
            if not data or role != "user":
                continue
            mime_type = str(image.get("mime_type") or "image/png")
            parts.append({"type": "input_image", "detail": "auto", "image_url": f"data:{mime_type};base64,{data}"})
        if parts:
            if role == "assistant":
                input_items.append({"type": "message", "role": "assistant", "status": "completed", "id": f"msg_{message_index}", "content": parts})
            else:
                input_items.append({"role": "user", "content": parts})
            message_index += 1
    if not input_items:
        input_items.append({"role": "user", "content": [{"type": "input_text", "text": "Hello."}]})
    return "\n\n".join(instructions), input_items


def codex_event_text(event: dict[str, Any]) -> str:
    event_type = str(event.get("type") or "")
    if event_type in {"response.output_text.delta", "response.refusal.delta"}:
        return str(event.get("delta") or "")
    if event_type in {"response.failed", "error"}:
        error = event.get("error") if isinstance(event.get("error"), dict) else event
        message = error.get("message") if isinstance(error, dict) else ""
        raise ValueError(str(message or "Codex response failed."))
    if event_type in {"response.completed", "response.done", "response.incomplete"}:
        return ""
    return ""


def codex_http_error_message(error: urllib.error.HTTPError) -> str:
    detail = http_error_detail(error)
    suffix = f": {detail}" if detail else ""
    return f"Codex request failed ({error.code}){suffix}"


def codex_model(model: str) -> str:
    clean = (model or "").strip()
    if clean in CODEX_CHATGPT_MODELS:
        return clean
    if clean.endswith("-mini"):
        return "gpt-5.4-mini"
    if "gpt-5.5" in clean:
        return "gpt-5.5"
    if "gpt-5" in clean:
        return CODEX_DEFAULT_MODEL
    return CODEX_DEFAULT_MODEL


def codex_context_window(model: str) -> int:
    if codex_model(model) in CODEX_CHATGPT_MODELS:
        return 272000
    return 272000


def openai_context_window(model: str) -> int | None:
    name = (model or "").lower()
    if "gpt-4.1" in name or "gpt-5" in name:
        return 1000000
    if "gpt-4o" in name or "o3" in name or "o4" in name:
        return 128000
    return None


def text_from_response_output(output: Any) -> str:
    if not isinstance(output, list):
        return ""
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
    return "".join(parts)


def image_attachments(message: dict[str, Any]) -> list[dict[str, Any]]:
    attachments = message.get("attachments") if isinstance(message.get("attachments"), list) else []
    return [attachment for attachment in attachments if isinstance(attachment, dict)]


def messages_have_image_attachments(messages: list[dict[str, Any]]) -> bool:
    return any(image_attachments(message) for message in messages)


def provider_image_error(error: urllib.error.HTTPError, messages: list[dict[str, Any]]) -> bool:
    return error.code in {400, 413, 415, 422, 500, 501} and messages_have_image_attachments(messages)


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
