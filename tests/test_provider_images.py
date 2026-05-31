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


if __name__ == "__main__":
    unittest.main()
