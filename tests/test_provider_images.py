from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "brain"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-provider-images-test-")

from bitbuddy.config import ProviderConfig  # noqa: E402
from bitbuddy.providers import ProviderClient  # noqa: E402


class ProviderImageTest(unittest.TestCase):
    def test_ollama_image_bad_request_becomes_chat_message(self) -> None:
        client = ProviderClient(ProviderConfig(type="ollama", url="http://provider.test", model="text-only"))
        messages = [
            {
                "role": "user",
                "content": "What is in this image?",
                "attachments": [{"name": "screen.png", "mime_type": "image/png", "data": "abc123"}],
            }
        ]

        with patch("bitbuddy.providers.post_json_lines", side_effect=HTTPError("http://provider.test/api/chat", 400, "Bad Request", {}, None)):
            chunks = list(client.stream_chat(messages))

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].kind, "response")
        self.assertIn("could not load the uploaded image data", chunks[0].text)
        self.assertIn("PNG, JPEG, or WebP", chunks[0].text)

    def test_ollama_thinking_can_be_disabled(self) -> None:
        client = ProviderClient(ProviderConfig(type="ollama", url="http://provider.test", model="reasoning-model"))
        payloads = []

        def fake_post_json_lines(_url, payload):
            payloads.append(payload)
            return iter([
                {"message": {"thinking": "private", "content": "<think>hidden</think>visible"}},
            ])

        with patch("bitbuddy.providers.post_json_lines", side_effect=fake_post_json_lines):
            chunks = list(client.stream_chat([{"role": "user", "content": "Hi"}], thinking_enabled=False))

        self.assertEqual(payloads[0]["think"], False)
        self.assertIn("Thinking/reasoning mode is disabled", payloads[0]["messages"][0]["content"])
        self.assertEqual([(chunk.kind, chunk.text) for chunk in chunks], [("response", "visible")])

    def test_llama_cpp_thinking_can_be_disabled(self) -> None:
        client = ProviderClient(ProviderConfig(type="llama.cpp", url="http://provider.test", model="reasoning-model"))
        payloads = []

        def fake_post_sse_json(_url, payload):
            payloads.append(payload)
            return iter([
                {"choices": [{"delta": {"reasoning_content": "private", "content": "<think>hidden</think>visible"}}]},
            ])

        with patch("bitbuddy.providers.post_sse_json", side_effect=fake_post_sse_json):
            chunks = list(client.stream_chat([{"role": "user", "content": "Hi"}], thinking_enabled=False))

        self.assertEqual(payloads[0]["chat_template_kwargs"], {"enable_thinking": False})
        self.assertEqual(payloads[0]["reasoning_format"], "none")
        self.assertEqual(payloads[0]["thinking_budget_tokens"], 0)
        self.assertEqual(payloads[0]["reasoning_budget_tokens"], 0)
        self.assertIn("Thinking/reasoning mode is disabled", payloads[0]["messages"][0]["content"])
        self.assertEqual([(chunk.kind, chunk.text) for chunk in chunks], [("response", "visible")])

    def test_llama_cpp_thinking_enabled_sends_reasoning_budget(self) -> None:
        client = ProviderClient(ProviderConfig(type="llama.cpp", url="http://provider.test", model="reasoning-model"))
        payloads = []

        def fake_post_sse_json(_url, payload):
            payloads.append(payload)
            return iter([
                {"choices": [{"delta": {"reasoning_content": "plan", "content": "answer"}}]},
            ])

        with patch("bitbuddy.providers.post_sse_json", side_effect=fake_post_sse_json), \
                patch("bitbuddy.providers.reasoning_budget_tokens", return_value=-1):
            chunks = list(client.stream_chat([{"role": "user", "content": "Hi"}], thinking_enabled=True))

        self.assertEqual(payloads[0]["chat_template_kwargs"], {"enable_thinking": True})
        self.assertNotIn("reasoning_format", payloads[0])
        self.assertEqual(payloads[0]["thinking_budget_tokens"], -1)
        self.assertEqual(payloads[0]["reasoning_budget_tokens"], -1)
        self.assertEqual([(chunk.kind, chunk.text) for chunk in chunks], [("thinking", "plan"), ("response", "answer")])

    def test_anthropic_thinking_enabled_requests_extended_thinking_for_supported_models(self) -> None:
        client = ProviderClient(ProviderConfig(type="anthropic", url="https://anthropic.test", model="claude-sonnet-4-6", api_key="key"))
        payloads = []

        def fake_post_anthropic_sse(_url, payload, headers):
            payloads.append(payload)
            return iter([
                {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "plan"}},
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "answer"}},
                {"type": "message_stop"},
            ])

        with patch("bitbuddy.providers.post_anthropic_sse", side_effect=fake_post_anthropic_sse), \
                patch("bitbuddy.providers.reasoning_budget_tokens", return_value=-1):
            chunks = list(client.stream_chat([{"role": "user", "content": "Hi"}], thinking_enabled=True))

        self.assertEqual(payloads[0]["thinking"], {"type": "enabled", "budget_tokens": 2048})
        self.assertEqual([(chunk.kind, chunk.text) for chunk in chunks], [("thinking", "plan"), ("response", "answer")])

    def test_anthropic_thinking_enabled_does_not_request_extended_thinking_for_unknown_models(self) -> None:
        client = ProviderClient(ProviderConfig(type="anthropic", url="https://anthropic.test", model="claude-test", api_key="key"))
        payloads = []

        def fake_post_anthropic_sse(_url, payload, headers):
            payloads.append(payload)
            return iter([
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "answer"}},
                {"type": "message_stop"},
            ])

        with patch("bitbuddy.providers.post_anthropic_sse", side_effect=fake_post_anthropic_sse):
            chunks = list(client.stream_chat([{"role": "user", "content": "Hi"}], thinking_enabled=True))

        self.assertNotIn("thinking", payloads[0])
        self.assertEqual([(chunk.kind, chunk.text) for chunk in chunks], [("response", "answer")])

    def test_codex_reasoning_summary_streams_as_thinking(self) -> None:
        client = ProviderClient(ProviderConfig(type="codex", url="codex://chatgpt", model="gpt-5.5"))

        with patch("bitbuddy.providers.codex_health", return_value=(True, "ok")), \
                patch("bitbuddy.providers.get_credentials", return_value={"access_token": "token", "account_id": "acct"}), \
                patch("bitbuddy.providers.post_sse_json", return_value=iter([
                    {"type": "response.reasoning_summary_text.delta", "delta": "plan"},
                    {"type": "response.output_text.delta", "delta": "answer"},
                    {"type": "response.completed"},
                ])):
            chunks = list(client.stream_chat([{"role": "user", "content": "Hi"}], thinking_enabled=True))

        self.assertEqual([(chunk.kind, chunk.text) for chunk in chunks], [("thinking", "plan"), ("response", "answer")])

    def test_openai_responses_reasoning_summary_streams_as_thinking(self) -> None:
        client = ProviderClient(ProviderConfig(type="openai", url="https://api.openai.com", model="gpt-5.5", api_key="key"))
        payloads = []

        def fake_post_sse_json(url, payload, headers=None):
            payloads.append((url, payload, headers))
            return iter([
                {"type": "response.reasoning_summary_text.delta", "delta": "plan"},
                {"type": "response.output_text.delta", "delta": "answer"},
                {"type": "response.completed"},
            ])

        with patch("bitbuddy.providers.post_sse_json", side_effect=fake_post_sse_json):
            chunks = list(client.stream_chat([{"role": "user", "content": "Hi"}], thinking_enabled=True))

        self.assertEqual(payloads[0][0], "https://api.openai.com/v1/responses")
        self.assertEqual(payloads[0][1]["store"], False)
        self.assertEqual(payloads[0][1]["include"], ["reasoning.encrypted_content"])
        self.assertIn("prompt_cache_key", payloads[0][1])
        self.assertEqual(payloads[0][1]["reasoning"], {"effort": "medium", "summary": "auto"})
        self.assertEqual([(chunk.kind, chunk.text) for chunk in chunks], [("thinking", "plan"), ("response", "answer")])

    def test_openai_responses_reasoning_item_streams_as_thinking(self) -> None:
        client = ProviderClient(ProviderConfig(type="openai", url="https://api.openai.com", model="gpt-5.5", api_key="key"))

        with patch("bitbuddy.providers.post_sse_json", return_value=iter([
            {"type": "response.output_item.done", "item": {"type": "reasoning", "summary": [{"type": "summary_text", "text": "summarized plan"}]}},
            {"type": "response.output_text.delta", "delta": "answer"},
            {"type": "response.completed"},
        ])):
            chunks = list(client.stream_chat([{"role": "user", "content": "Hi"}], thinking_enabled=True))

        self.assertEqual([(chunk.kind, chunk.text) for chunk in chunks], [("thinking", "summarized plan"), ("response", "answer")])

    def test_codex_requests_reasoning_summary(self) -> None:
        client = ProviderClient(ProviderConfig(type="codex", url="codex://chatgpt", model="gpt-5.5"))
        payloads = []

        def fake_post_sse_json(_url, payload, headers=None):
            payloads.append(payload)
            return iter([
                {"type": "response.output_item.done", "item": {"type": "reasoning", "summary": [{"type": "summary_text", "text": "plan"}]}},
                {"type": "response.output_text.delta", "delta": "answer"},
                {"type": "response.completed"},
            ])

        with patch("bitbuddy.providers.codex_health", return_value=(True, "ok")), \
                patch("bitbuddy.providers.get_credentials", return_value={"access_token": "token", "account_id": "acct"}), \
                patch("bitbuddy.providers.post_sse_json", side_effect=fake_post_sse_json):
            chunks = list(client.stream_chat([{"role": "user", "content": "Hi"}], thinking_enabled=True))

        self.assertEqual(payloads[0]["reasoning"], {"effort": "medium", "summary": "auto"})
        self.assertEqual(payloads[0]["include"], ["reasoning.encrypted_content"])
        self.assertEqual([(chunk.kind, chunk.text) for chunk in chunks], [("thinking", "plan"), ("response", "answer")])

    def test_codex_supports_native_tools(self) -> None:
        client = ProviderClient(ProviderConfig(type="codex", url="codex://chatgpt", model="gpt-5.5"))

        self.assertTrue(client.supports_native_tools())

    def test_codex_function_call_streams_as_tool_call(self) -> None:
        client = ProviderClient(ProviderConfig(type="codex", url="codex://chatgpt", model="gpt-5.5"))
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file.",
                    "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]},
                },
            }
        ]
        payloads = []

        def fake_post_sse_json(_url, payload, headers=None):
            payloads.append(payload)
            return iter([
                {"type": "response.output_item.added", "output_index": 0, "item": {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "read_file"}},
                {"type": "response.function_call_arguments.delta", "output_index": 0, "delta": '{"file_'},
                {"type": "response.function_call_arguments.delta", "output_index": 0, "delta": 'path":"README.md"}'},
                {"type": "response.completed"},
            ])

        with patch("bitbuddy.providers.codex_health", return_value=(True, "ok")), \
                patch("bitbuddy.providers.get_credentials", return_value={"access_token": "token", "account_id": "acct"}), \
                patch("bitbuddy.providers.post_sse_json", side_effect=fake_post_sse_json):
            chunks = list(client.stream_chat([{"role": "user", "content": "Read README"}], tools=tools))

        self.assertEqual(payloads[0]["tools"][0]["name"], "read_file")
        self.assertEqual(payloads[0]["tool_choice"], "auto")
        tool_chunks = [chunk for chunk in chunks if chunk.kind == "tool_call"]
        self.assertEqual(len(tool_chunks), 1)
        self.assertEqual(tool_chunks[0].tool_call.name, "read_file")
        self.assertEqual(tool_chunks[0].tool_call.arguments, '{"file_path":"README.md"}')
        self.assertEqual(tool_chunks[0].tool_call.call_id, "call_1")

    def test_openai_responses_function_call_streams_as_tool_call(self) -> None:
        client = ProviderClient(ProviderConfig(type="openai", url="https://api.openai.com", model="gpt-5.5", api_key="key"))
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file.",
                    "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}}, "required": ["file_path"]},
                },
            }
        ]
        payloads = []

        def fake_post_sse_json(url, payload, headers=None):
            payloads.append(payload)
            return iter([
                {"type": "response.output_item.added", "output_index": 0, "item": {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "read_file"}},
                {"type": "response.function_call_arguments.delta", "output_index": 0, "delta": '{"file_'},
                {"type": "response.function_call_arguments.delta", "output_index": 0, "delta": 'path":"README.md"}'},
                {"type": "response.completed"},
            ])

        with patch("bitbuddy.providers.post_sse_json", side_effect=fake_post_sse_json):
            chunks = list(client.stream_chat([{"role": "user", "content": "Read README"}], thinking_enabled=True, tools=tools))

        self.assertEqual(payloads[0]["tools"][0]["name"], "read_file")
        tool_chunks = [chunk for chunk in chunks if chunk.kind == "tool_call"]
        self.assertEqual(len(tool_chunks), 1)
        self.assertEqual(tool_chunks[0].tool_call.name, "read_file")
        self.assertEqual(tool_chunks[0].tool_call.arguments, '{"file_path":"README.md"}')
        self.assertEqual(tool_chunks[0].tool_call.call_id, "call_1")


if __name__ == "__main__":
    unittest.main()
