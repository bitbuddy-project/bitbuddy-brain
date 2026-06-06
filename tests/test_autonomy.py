from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "brain"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-autonomy-test-")

from bitbuddy.activity import ensure_activity_database, list_activity  # noqa: E402
from bitbuddy.autonomy.activities import AutonomyActivityResult, create_autonomy_intentions, run_autonomy_activity, supported_project_update_fields  # noqa: E402
from bitbuddy.autonomy.decision import AutonomyActivityType, AutonomyDecision, parse_autonomy_decision  # noqa: E402
from bitbuddy.autonomy.intentions import create_intention, dismiss_intention, ensure_intentions_database, list_pending_intentions  # noqa: E402
from bitbuddy.autonomy.memory import record_autonomy_self_memory  # noqa: E402
from bitbuddy.autonomy.runner import STARTUP_IDLE_CHAT_ID, AutonomyJob, autonomy_job_is_stale, autonomy_status, cancel_idle_autonomy, idle_autonomy_delay, run_autonomy_cycle, schedule_idle_autonomy, schedule_next_idle_autonomy, schedule_startup_idle_autonomy  # noqa: E402
from bitbuddy.autonomy.web_search import SearchResult, parse_searxng_results, safe_result_url, search_results_to_text  # noqa: E402
from bitbuddy.autonomy.web_search_server import SearchProviderBlocked, parse_duckduckgo_html_results, parse_duckduckgo_image_results, search_response, should_use_managed_server  # noqa: E402
from bitbuddy.chats.repository import chat_activity_token, create_chat, ensure_chat_database  # noqa: E402
from bitbuddy.config import load_config  # noqa: E402
from bitbuddy.memory.store import create_memory, ensure_memory_database, search_memories  # noqa: E402
from bitbuddy.paths import GLOBAL_DB_PATH  # noqa: E402
from bitbuddy.prompt_builder import build_chat_messages  # noqa: E402
from bitbuddy.providers import StreamChunk  # noqa: E402


class FakeClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.messages = None

    def stream_chat(self, _messages, model=None, should_cancel=None, thinking_enabled=True):
        self.messages = _messages
        yield StreamChunk("response", self.response)


class FakeTimer:
    def __init__(self, delay, target, args=()) -> None:
        self.delay = delay
        self.target = target
        self.args = args
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True


class AutonomyTest(unittest.TestCase):
    def setUp(self) -> None:
        ensure_activity_database()
        ensure_intentions_database()
        ensure_memory_database()
        ensure_chat_database()
        with sqlite3.connect(GLOBAL_DB_PATH) as connection:
            connection.execute("delete from activity")
            connection.execute("delete from intentions")
            connection.execute("delete from chat_messages")
            connection.execute("delete from chats")
            connection.execute("delete from memory_reclassifications")
            connection.execute("delete from memory_merges")
            connection.execute("delete from memories")
            try:
                connection.execute("delete from memories_fts")
            except sqlite3.Error:
                pass

    def test_autonomy_enum_has_no_dreaming(self) -> None:
        values = {item.value for item in AutonomyActivityType}
        self.assertNotIn("dreaming", values)
        self.assertIn("web_curiosity", values)
        self.assertIn("project_familiarization", values)
        self.assertIn("generate_user_prompts", values)

    def test_autonomy_config_defaults_to_longer_idle_delay(self) -> None:
        config = load_config()
        self.assertTrue(config.autonomy.enabled)
        self.assertGreaterEqual(config.autonomy.idle_delay_seconds, 300)
        self.assertTrue(config.autonomy.repeat_idle_cycles)
        self.assertGreater(config.autonomy.idle_backoff_multiplier, 1)
        self.assertGreaterEqual(config.autonomy.idle_max_delay_seconds, config.autonomy.idle_delay_seconds)
        self.assertEqual(config.autonomy.web_search.provider, "searxng")
        self.assertEqual(config.autonomy.web_search.startup_command, "managed")

    def test_idle_autonomy_delay_uses_capped_backoff(self) -> None:
        autonomy = SimpleNamespace(idle_delay_seconds=300, idle_backoff_multiplier=2.0, idle_max_delay_seconds=1200)

        self.assertEqual(idle_autonomy_delay(autonomy, 0), 300)
        self.assertEqual(idle_autonomy_delay(autonomy, 1), 600)
        self.assertEqual(idle_autonomy_delay(autonomy, 2), 1200)
        self.assertEqual(idle_autonomy_delay(autonomy, 3), 1200)

    def test_completed_idle_autonomy_schedules_next_cycle_while_still_idle(self) -> None:
        token = {"message_count": 1}
        autonomy = SimpleNamespace(
            enabled=True,
            run_after_idle_consolidation=True,
            repeat_idle_cycles=True,
            idle_delay_seconds=300,
            idle_backoff_multiplier=2.0,
            idle_max_delay_seconds=1200,
        )
        config = SimpleNamespace(autonomy=autonomy, provider=SimpleNamespace(type="ollama"))
        job = AutonomyJob("chat-repeat", "job-one", None, token, 300, repeat_index=0)

        with patch("bitbuddy.autonomy.runner.load_config", return_value=config), \
             patch("bitbuddy.autonomy.runner.chat_window_token", return_value=token), \
             patch("bitbuddy.autonomy.runner.threading.Timer", FakeTimer):
            next_job_id = schedule_next_idle_autonomy(job)

        self.assertIsNotNone(next_job_id)
        cancel_idle_autonomy("chat-repeat", reason="test cleanup")

    def test_idle_autonomy_repeat_stops_when_chat_token_changes(self) -> None:
        token = {"message_count": 1}
        autonomy = SimpleNamespace(enabled=True, repeat_idle_cycles=True, idle_delay_seconds=300, idle_backoff_multiplier=2.0, idle_max_delay_seconds=1200)
        config = SimpleNamespace(autonomy=autonomy, provider=SimpleNamespace(type="ollama"))
        job = AutonomyJob("chat-stale", "job-one", None, token, 300, repeat_index=0)

        with patch("bitbuddy.autonomy.runner.load_config", return_value=config), \
             patch("bitbuddy.autonomy.runner.chat_window_token", return_value={"message_count": 2}), \
             patch("bitbuddy.autonomy.runner.threading.Timer", FakeTimer):
            next_job_id = schedule_next_idle_autonomy(job)

        self.assertIsNone(next_job_id)
        self.assertTrue(any(item["kind"] == "autonomy.repeat_stopped" for item in list_activity()))

    def test_startup_idle_autonomy_schedules_without_chat(self) -> None:
        autonomy = SimpleNamespace(
            enabled=True,
            run_after_idle_consolidation=True,
            repeat_idle_cycles=True,
            idle_delay_seconds=300,
            idle_backoff_multiplier=2.0,
            idle_max_delay_seconds=1200,
        )
        config = SimpleNamespace(autonomy=autonomy, provider=SimpleNamespace(type="ollama"))

        with patch("bitbuddy.autonomy.runner.load_config", return_value=config), \
             patch("bitbuddy.autonomy.runner.threading.Timer", FakeTimer):
            job_id = schedule_startup_idle_autonomy()

        self.assertIsNotNone(job_id)
        self.assertTrue(any(item["kind"] == "autonomy.scheduled" and item["metadata"].get("chat_id") == STARTUP_IDLE_CHAT_ID for item in list_activity()))
        cancel_idle_autonomy(STARTUP_IDLE_CHAT_ID, reason="test cleanup")

    def test_autonomy_status_reports_scheduled_job(self) -> None:
        autonomy = SimpleNamespace(
            enabled=True,
            run_after_idle_consolidation=True,
            repeat_idle_cycles=True,
            idle_delay_seconds=300,
            idle_backoff_multiplier=2.0,
            idle_max_delay_seconds=1200,
        )
        config = SimpleNamespace(autonomy=autonomy, provider=SimpleNamespace(type="ollama"))

        with patch("bitbuddy.autonomy.runner.load_config", return_value=config), \
             patch("bitbuddy.autonomy.runner.threading.Timer", FakeTimer):
            job_id = schedule_idle_autonomy("chat-status", scheduled_token={"message_count": 1}, delay_seconds=42)
            status = autonomy_status()

        self.assertIsNotNone(job_id)
        self.assertEqual(status["state"], "scheduled")
        self.assertEqual(len(status["jobs"]), 1)
        self.assertEqual(status["jobs"][0]["chat_id"], "chat-status")
        self.assertEqual(status["jobs"][0]["phase"], "scheduled")
        self.assertIn("42", status["jobs"][0]["phase_message"])
        cancel_idle_autonomy("chat-status", reason="test cleanup")

    def test_autonomy_cycle_reports_phase_callbacks(self) -> None:
        autonomy = SimpleNamespace(enabled=True)
        config = SimpleNamespace(autonomy=autonomy, provider=SimpleNamespace(type="ollama"))
        phases: list[tuple[str, str, str]] = []

        with patch("bitbuddy.autonomy.runner.load_config", return_value=config), \
             patch("bitbuddy.autonomy.runner.ProviderClient", return_value=FakeClient("")), \
             patch("bitbuddy.autonomy.runner.build_autonomy_context", return_value="context"), \
             patch("bitbuddy.autonomy.runner.choose_autonomy_activity", return_value=AutonomyDecision(AutonomyActivityType.PROJECT_FAMILIARIZATION, "learn project", {})), \
             patch("bitbuddy.autonomy.runner.run_autonomy_activity", return_value=AutonomyActivityResult(AutonomyActivityType.PROJECT_FAMILIARIZATION, "skipped", "No files.")):
            result = run_autonomy_cycle(
                "chat-status",
                cycle_id="cycle-status",
                phase_callback=lambda phase, message, activity="": phases.append((phase, message, activity)),
            )

        phase_names = [phase for phase, _, _ in phases]
        self.assertEqual(result["status"], "skipped")
        self.assertIn("building_context", phase_names)
        self.assertIn("deciding_activity", phase_names)
        self.assertIn("executing_activity", phase_names)
        self.assertEqual(phases[-1][2], "project_familiarization")

    def test_startup_idle_autonomy_stales_when_chat_activity_changes(self) -> None:
        token = chat_activity_token()
        job = AutonomyJob(STARTUP_IDLE_CHAT_ID, "job-one", None, token, 300)

        create_chat("New chat", "chat")

        self.assertTrue(autonomy_job_is_stale(job))

    def test_managed_web_search_accepts_legacy_default_command(self) -> None:
        self.assertTrue(should_use_managed_server("managed"))
        self.assertTrue(should_use_managed_server("searxng"))
        self.assertFalse(should_use_managed_server("docker run searxng"))

    def test_parse_unknown_decision_falls_back_to_do_nothing(self) -> None:
        decision = parse_autonomy_decision('{"activity":"dreaming","reason":"not yet","inputs":{}}')
        self.assertEqual(decision.activity, AutonomyActivityType.DO_NOTHING)

    def test_intention_queue_create_list_and_dismiss(self) -> None:
        created = create_intention("question", "Should I ask about project memory?", "Useful follow-up", "cycle-test")

        pending = list_pending_intentions()

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].id, created.id)
        self.assertTrue(dismiss_intention(created.id))
        self.assertEqual(list_pending_intentions(), [])

    def test_duplicate_queued_intentions_are_deduped(self) -> None:
        first = create_intention("question", "Should we talk about AI consciousness?", "one", "cycle-a")
        second = create_intention("question", "Should we talk about AI consciousness?", "two", "cycle-b")

        pending = list_pending_intentions()

        self.assertEqual(first.id, second.id)
        self.assertEqual(len(pending), 1)
        self.assertTrue(pending[0].metadata.get("deduped"))

    def test_generate_user_prompts_writes_intention_queue(self) -> None:
        result = run_autonomy_activity(
            AutonomyDecision(AutonomyActivityType.GENERATE_USER_PROMPTS, "surface project decision later", {}),
            cycle_id="cycle-prompts",
            client=FakeClient('{"intentions":[{"kind":"question","content":"Before we edit the project memory flow, should we keep questions limited to important blockers?","reason":"This affects autonomy behavior and user interruption policy.","importance":5}]}'),  # type: ignore[arg-type]
        )

        pending = list_pending_intentions()

        self.assertEqual(result.status, "completed")
        self.assertEqual(len(pending), 1)
        self.assertIn("important blockers", pending[0].content)

    def test_generate_user_prompts_includes_relevant_memory_before_model_call(self) -> None:
        create_memory(
            title="Question style",
            summary="Dustin prefers autonomy questions only when they are decision-relevant blockers.",
            layer="semantic",
            kind="preference",
            importance=5,
            tags=["autonomy", "questions"],
        )
        client = FakeClient('{"intentions":[]}')

        run_autonomy_activity(
            AutonomyDecision(AutonomyActivityType.GENERATE_USER_PROMPTS, "ask about autonomy question style", {}),
            cycle_id="cycle-memory-context",
            client=client,  # type: ignore[arg-type]
        )

        prompt = "\n".join(str(message.get("content", "")) for message in (client.messages or []))
        self.assertIn("Known memory/context", prompt)
        self.assertIn("decision-relevant blockers", prompt)

    def test_low_signal_generated_question_is_rejected(self) -> None:
        created = create_autonomy_intentions(
            [{"kind": "question", "content": "Want to talk about AI consciousness?", "reason": "It came up.", "importance": 2}],
            cycle_id="cycle-low-signal",
            source_activity="generate_user_prompts",
        )

        self.assertEqual(created, [])
        self.assertEqual(list_pending_intentions(), [])

    def test_generated_question_answered_by_memory_is_rejected(self) -> None:
        create_memory(
            title="Autonomy interruption policy",
            summary="Dustin wants BitBuddy questions limited to important blockers and decision-relevant project issues.",
            layer="semantic",
            kind="preference",
            importance=5,
            tags=["autonomy", "questions", "preference"],
        )

        created = create_autonomy_intentions(
            [
                {
                    "kind": "question",
                    "content": "Before we edit autonomy, should we keep questions limited to important blockers?",
                    "reason": "This affects autonomy behavior and user interruption policy.",
                    "importance": 5,
                }
            ],
            cycle_id="cycle-memory-known",
            source_activity="generate_user_prompts",
        )

        self.assertEqual(created, [])
        self.assertEqual(list_pending_intentions(), [])
        self.assertTrue(any(item["kind"] == "autonomy.intention_skipped" and "already appears to answer" in item["message"] for item in list_activity()))

    def test_playful_comment_requires_tone_support(self) -> None:
        rejected = create_autonomy_intentions(
            [{"kind": "comment", "content": "Tiny frog debugging vibes acquired.", "reason": "Random whim.", "playfulness": 4}],
            cycle_id="cycle-play-reject",
            source_activity="generate_user_prompts",
        )
        accepted = create_autonomy_intentions(
            [{"kind": "comment", "content": "Tiny frog debugging vibes acquired.", "reason": "User likes playful silly comments during debugging.", "playfulness": 4}],
            cycle_id="cycle-play-accept",
            source_activity="generate_user_prompts",
        )

        self.assertEqual(rejected, [])
        self.assertEqual(len(accepted), 1)

    def test_generate_user_prompts_logs_skip_when_no_useful_item(self) -> None:
        result = run_autonomy_activity(
            AutonomyDecision(AutonomyActivityType.GENERATE_USER_PROMPTS, "try later", {}),
            cycle_id="cycle-empty",
            client=FakeClient('{"intentions":[]}'),  # type: ignore[arg-type]
        )

        self.assertEqual(result.status, "skipped")
        self.assertTrue(any(item["kind"] == "autonomy.intention_skipped" for item in list_activity()))

    def test_autonomy_can_create_and_update_durable_self_memory(self) -> None:
        first = record_autonomy_self_memory(
            cycle_id="cycle-one",
            activity="generate_user_prompts",
            status="completed",
            summary="Created a queued prompt.",
        )
        second = record_autonomy_self_memory(
            cycle_id="cycle-two",
            activity="web_curiosity",
            status="completed",
            summary="Searched a curiosity topic.",
        )

        memories = search_memories(layer="self", limit=10)

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(len(memories), 1)
        self.assertEqual(first.id, second.id)
        self.assertIn("future intention generation", memories[0].summary)
        self.assertIn("web curiosity", memories[0].summary)

    def test_pending_intentions_are_available_to_chat_prompt(self) -> None:
        create_intention("question", "Should I ask about autonomy logs?", "Useful follow-up", "cycle-test")

        messages = build_chat_messages([{"role": "user", "content": "hello"}], "chat")
        content = "\n\n".join(message.get("content", "") for message in messages)

        self.assertIn("[Pending BitBuddy Intentions]", content)
        self.assertIn("Should I ask about autonomy logs?", content)

    def test_searxng_parser_filters_unsafe_urls(self) -> None:
        results = parse_searxng_results(
            {
                "results": [
                    {"title": "Local", "url": "http://localhost/admin", "content": "no"},
                    {"title": "Private", "url": "http://192.168.1.1", "content": "no"},
                    {"title": "Public", "url": "https://example.com/article", "content": "yes"},
                ]
            }
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Public")
        self.assertTrue(safe_result_url("https://example.com"))
        self.assertFalse(safe_result_url("file:///etc/passwd"))
        self.assertFalse(safe_result_url("http://172.31.0.10/status"))

    def test_searxng_parser_includes_image_urls(self) -> None:
        results = parse_searxng_results(
            {
                "results": [
                    {
                        "title": "Example image",
                        "url": "https://example.com/page",
                        "content": "image result",
                        "category": "images",
                        "img_src": "https://images.example.com/full.jpg",
                        "thumbnail_src": "https://images.example.com/thumb.jpg",
                    }
                ]
            },
            category="images",
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].category, "images")
        self.assertEqual(results[0].image_url, "https://images.example.com/full.jpg")
        self.assertIn("Image URL: https://images.example.com/full.jpg", search_results_to_text(results))

    def test_managed_search_parser_decodes_duckduckgo_results(self) -> None:
        html = """
        <div class="result">
          <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Farticle">Example title</a>
          <div class="result__snippet">Useful <b>snippet</b> text.</div>
        </div>
        """

        results = parse_duckduckgo_html_results(html)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Example title")
        self.assertEqual(results[0].url, "https://example.com/article")
        self.assertEqual(results[0].snippet, "Useful snippet text.")

    def test_managed_image_parser_decodes_duckduckgo_image_results(self) -> None:
        results = parse_duckduckgo_image_results(
            {
                "results": [
                    {
                        "title": "Example image",
                        "image": "https://images.example.com/full.jpg",
                        "thumbnail": "https://images.example.com/thumb.jpg",
                        "url": "https://example.com/page",
                        "source": "example.com",
                        "width": 1200,
                        "height": 800,
                    },
                    {"title": "Unsafe", "image": "http://127.0.0.1/image.jpg", "url": "https://example.com/unsafe"},
                ]
            }
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].category, "images")
        self.assertEqual(results[0].image_url, "https://images.example.com/full.jpg")
        self.assertEqual(results[0].thumbnail_url, "https://images.example.com/thumb.jpg")
        self.assertIn("1200x800", results[0].snippet)

    def test_managed_search_response_uses_searxng_shape(self) -> None:
        with patch(
            "bitbuddy.autonomy.web_search_server.search_duckduckgo_html",
            return_value=[SearchResult(title="Result", url="https://example.com", snippet="Snippet", source="duckduckgo")],
        ):
            response = search_response("  example query  ")

        self.assertEqual(response["query"], "example query")
        self.assertEqual(response["answers"], [])
        self.assertEqual(response["suggestions"], [])
        self.assertEqual(response["results"], [
            {
                "title": "Result",
                "url": "https://example.com",
                "content": "Snippet",
                "img_src": "",
                "thumbnail_src": "",
                "engine": "duckduckgo",
                "category": "general",
            }
        ])

    def test_managed_search_falls_back_to_mojeek_when_duckduckgo_blocked(self) -> None:
        with patch(
            "bitbuddy.autonomy.web_search_server.search_duckduckgo_html",
            side_effect=SearchProviderBlocked("blocked"),
        ), patch(
            "bitbuddy.autonomy.web_search_server.search_duckduckgo_lite",
            side_effect=SearchProviderBlocked("blocked"),
        ), patch(
            "bitbuddy.autonomy.web_search_server.search_mojeek_html",
            return_value=[SearchResult(title="Mojeek Result", url="https://example.com", snippet="Snippet", source="mojeek")],
        ):
            response = search_response("example query")

        self.assertEqual(response["results"][0]["title"], "Mojeek Result")
        self.assertEqual(response["results"][0]["engine"], "mojeek")

    def test_managed_search_response_supports_images_category(self) -> None:
        with patch(
            "bitbuddy.autonomy.web_search_server.search_duckduckgo_images",
            return_value=[SearchResult(title="Image", url="https://example.com/page", snippet="Snippet", source="duckduckgo", category="images", image_url="https://example.com/image.jpg", thumbnail_url="https://example.com/thumb.jpg")],
        ):
            response = search_response("example image", category="images")

        self.assertEqual(response["results"], [
            {
                "title": "Image",
                "url": "https://example.com/page",
                "content": "Snippet",
                "img_src": "https://example.com/image.jpg",
                "thumbnail_src": "https://example.com/thumb.jpg",
                "engine": "duckduckgo",
                "category": "images",
            }
        ])

    def test_safe_web_search_connection_refused_raises_descriptive_error(self) -> None:
        from bitbuddy.autonomy.web_search import safe_web_search
        from bitbuddy.config import WebSearchConfig

        config = WebSearchConfig(
            enabled=True,
            provider="searxng",
            url="http://127.0.0.1:1",  # Port 1 is likely refused
            startup_command="searxng",
            max_results=5
        )

        with self.assertRaisesRegex(ValueError, "Connection refused to SearxNG"):
            safe_web_search("test", config)

    def test_network_observation_is_safe_skipped_placeholder(self) -> None:
        result = run_autonomy_activity(
            AutonomyDecision(AutonomyActivityType.NETWORK_OBSERVATION, "future feature", {}),
            cycle_id="cycle-test",
            client=None,  # type: ignore[arg-type]
        )

        self.assertEqual(result.status, "skipped")
        self.assertIn("not implemented", result.summary)

    def test_project_familiarization_ignores_unsupported_update_fields(self) -> None:
        clean, ignored = supported_project_update_fields(
            "project_overview",
            {
                "name": "Should not be written",
                "repo_path": "/tmp/nope",
                "purpose": "Useful durable purpose.",
                "status": "Useful status alias.",
            },
        )

        self.assertEqual(clean, {"purpose": "Useful durable purpose.", "status": "Useful status alias."})
        self.assertEqual(ignored, ["name", "repo_path"])

    def test_schedule_idle_autonomy_skips_without_provider(self) -> None:
        autonomy = SimpleNamespace(enabled=True, run_after_idle_consolidation=True)
        config = SimpleNamespace(autonomy=autonomy, provider=SimpleNamespace(type="none"))

        with patch("bitbuddy.autonomy.runner.load_config", return_value=config):
            job_id = schedule_idle_autonomy("chat-test", scheduled_token={"message_count": 1})

        self.assertIsNone(job_id)
        self.assertTrue(any(item["kind"] == "autonomy.skipped" for item in list_activity()))


if __name__ == "__main__":
    unittest.main()
