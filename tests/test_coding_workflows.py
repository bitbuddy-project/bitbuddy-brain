from __future__ import annotations

import tempfile
import sys
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-coding-workflows-test-")

from bitbuddy.config import ProviderConfig
from bitbuddy.interactions import parse_question_request, question_answers_tool_result, validate_question_answers
from bitbuddy.toolbox.registry import default_tool_registry
from bitbuddy.toolbox.base import ToolRegistry
from bitbuddy.coding import runs
from bitbuddy.coding import workflows
from bitbuddy.coding import orchestrator
from bitbuddy.coding.workflows import CodingStage, CodingWorkflow


def provider(key: str, model: str) -> ProviderConfig:
    return ProviderConfig(type=key, key=key, url=f"https://{key}.test", model=model, reasoning_effort="high", api_key="key")


class CodingWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "bitbuddy.sqlite"
        self.providers = (provider("anthropic", "claude-fable-5"), provider("openai", "gpt-test"), provider("z.ai", "glm-test"))
        self.config = SimpleNamespace(provider=self.providers[0], providers=self.providers)
        self.patches = [
            patch.object(workflows, "GLOBAL_DB_PATH", self.db_path),
            patch.object(workflows, "load_config", return_value=self.config),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_default_and_multi_provider_flow_round_trip(self) -> None:
        seeded = workflows.list_workflows()
        self.assertEqual(len(seeded), 1)
        self.assertTrue(seeded[0].is_default)

        saved = workflows.save_workflow(
            name="Three providers",
            stages=[
                stage("plan", "anthropic", "claude-fable-5", gate=True),
                stage("plan", "openai", "gpt-test"),
                stage("build", "openai", "gpt-test"),
                stage("review", "z.ai", "glm-test"),
                stage("test", "anthropic", "claude-fable-5", recipes=["unit"]),
            ],
        )
        self.assertEqual([item.provider_key for item in saved.stages], ["anthropic", "openai", "openai", "z.ai", "anthropic"])
        self.assertEqual(saved.stages[-1].validation_recipes, ("unit",))

    def test_flow_requires_one_build_and_role_boundaries(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly one Build"):
            workflows.save_workflow(name="No build", stages=[stage("plan", "openai", "gpt-test")])
        with self.assertRaisesRegex(ValueError, "Only Plan"):
            workflows.save_workflow(name="Review first", stages=[stage("review", "z.ai", "glm-test"), stage("build", "openai", "gpt-test")])

    def test_flow_rejects_missing_provider_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "configured provider"):
            workflows.save_workflow(name="Missing", stages=[stage("build", "missing", "model")])


class StructuredQuestionTests(unittest.TestCase):
    def test_request_validation_and_answer_tool_result(self) -> None:
        request = parse_question_request(
            {
                "questions": [
                    {
                        "id": "scope",
                        "header": "Scope",
                        "question": "Which part should change?",
                        "options": [
                            {"label": "Backend", "description": "Change the service."},
                            {"label": "Frontend", "description": "Change the interface."},
                        ],
                    }
                ]
            }
        )
        answers = validate_question_answers(request, {"scope": "Frontend"})
        result = question_answers_tool_result(request, answers)
        self.assertIn('"answer": "Frontend"', result)

    def test_request_rejects_unfocused_shapes(self) -> None:
        with self.assertRaisesRegex(ValueError, "one and three"):
            parse_question_request({"questions": []})
        with self.assertRaisesRegex(ValueError, "two or three"):
            parse_question_request({"questions": [{"id": "x", "question": "?", "options": [{"label": "Only", "description": "one"}]}]})

    def test_registry_exposes_shared_question_schema(self) -> None:
        registry = default_tool_registry()
        definition = registry.definition("request_user_input")
        self.assertIsNotNone(definition)
        self.assertEqual(definition.arguments_schema["properties"]["questions"]["maxItems"], 3)  # type: ignore[index]


class OrchestratorStageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "bitbuddy.sqlite"
        self.run_patch = patch.object(runs, "GLOBAL_DB_PATH", self.db_path)
        self.orchestrator_run_patch = patch.object(orchestrator, "get_coding_run", runs.get_coding_run)
        self.run_patch.start()
        self.orchestrator_run_patch.start()

    def tearDown(self) -> None:
        self.orchestrator_run_patch.stop()
        self.run_patch.stop()
        self.temp.cleanup()

    def test_stage_uses_its_snapshotted_provider_model_and_records_output(self) -> None:
        stage_config = CodingStage("review-1", "review", "Review", "z.ai", "glm-review", "max", "Review it.", False, ())
        workflow = CodingWorkflow("flow", "Flow", (stage_config,), False, "", "")
        coding_run = runs.start_coding_run(chat_id="", run_id="runtime", project_id="project", user_request="Review the change", metadata={"source": "workflow"})
        active = orchestrator.ActiveCodingWorkflow(
            coding_run.id,
            "project",
            "Review the change",
            workflow,
            [{"id": "image-1", "name": "layout.png", "mime_type": "image/png", "size": 12, "kind": "image", "data": "aW1hZ2U="}],
        )
        selected = provider("z.ai", "glm-default")
        clients: list[ProviderConfig] = []
        sent_messages: list[list[dict[str, object]]] = []

        class FakeClient:
            def __init__(self, config: ProviderConfig) -> None:
                clients.append(config)

            def supports_native_tools(self, model: str | None = None) -> bool:
                return False

            def stream_chat(self, messages, **kwargs):  # type: ignore[no-untyped-def]
                sent_messages.append(messages)
                yield SimpleNamespace(kind="response", text="Everything matches the request.\nVERDICT: PASS")

        with patch.object(orchestrator, "load_config", return_value=SimpleNamespace(providers=(selected,))), \
             patch.object(orchestrator, "ProviderClient", FakeClient), \
             patch.object(orchestrator, "default_tool_registry", return_value=ToolRegistry()):
            output = orchestrator._execute_stage(active, stage_config, "Inspect the implementation")

        self.assertIn("VERDICT: PASS", output)
        self.assertEqual(clients[0].model, "glm-review")
        self.assertEqual(clients[0].reasoning_effort, "max")
        self.assertEqual(sent_messages[0][1]["attachments"][0]["name"], "layout.png")  # type: ignore[index]
        persisted = runs.get_coding_run(coding_run.id)
        self.assertEqual(persisted.steps[-1].metadata["stage_id"], "review-1")
        self.assertIn("Everything matches", persisted.steps[-1].metadata["output"])

    def test_attachment_normalization_and_text_context(self) -> None:
        attachments = orchestrator._normalize_attachments(
            [
                {"id": "notes", "name": "notes.md", "mime_type": "text/markdown", "size": "8", "kind": "text", "text": "Keep the chat layout."},
                {"name": "ignored.exe", "kind": "unknown"},
            ]
        )
        active = orchestrator.ActiveCodingWorkflow(
            "run",
            "project",
            "Update the view",
            CodingWorkflow("flow", "Flow", (), False, "", ""),
            attachments,
        )
        context = orchestrator._stage_context(active, CodingStage("plan", "plan", "Plan", "openai", "gpt-test", "high", "", False, ()), [], "", [])
        self.assertIn("Attached text file notes.md", context)
        self.assertIn("Keep the chat layout.", context)
        self.assertEqual(attachments[1]["kind"], "file")


def stage(kind: str, provider_key: str, model: str, *, gate: bool = False, recipes: list[str] | None = None) -> dict[str, object]:
    return {
        "kind": kind,
        "name": kind.title(),
        "provider_key": provider_key,
        "model": model,
        "reasoning_effort": "high",
        "instructions": f"Do {kind} work.",
        "approval_gate": gate,
        "validation_recipes": recipes or [],
    }


if __name__ == "__main__":
    unittest.main()
