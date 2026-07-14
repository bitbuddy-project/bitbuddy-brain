from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-project-validation-test-")

from bitbuddy.memory.project import index_project, project_brief, project_model, register_project, unregister_project  # noqa: E402
from bitbuddy.memory.project_validation import (  # noqa: E402
    delete_validation_recipe,
    list_validation_recipes,
    recipe_to_json,
    run_validation_recipe,
    upsert_validation_recipe,
)
from bitbuddy.tools import ToolCall, ToolExecutor, default_tool_registry, needs_permission  # noqa: E402


class ProjectValidationRecipeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_dir = Path(tempfile.mkdtemp(prefix="bitbuddy-validation-repo-"))
        (self.repo_dir / "pyproject.toml").write_text("[project]\nname = \"demo\"\n", encoding="utf-8")
        self.project = register_project("validation-demo", [str(self.repo_dir)])
        index_project(self.project.id)

    def tearDown(self) -> None:
        unregister_project(self.project.id)

    def test_upsert_list_run_and_delete_validation_recipe(self) -> None:
        recipe = upsert_validation_recipe(
            self.project.id,
            name="Unit Tests",
            command="python -c 'print(\"ok\")'",
            kind="test",
            description="Fast unit test check.",
        )

        self.assertEqual(recipe.name, "unit-tests")
        self.assertEqual(recipe.kind, "test")

        recipes = list_validation_recipes(self.project.id)
        self.assertEqual([item.name for item in recipes], ["unit-tests"])

        run = run_validation_recipe(self.project.id, "unit-tests")
        self.assertEqual(run.exit_code, 0)
        self.assertEqual(run.status, "passed")
        self.assertIn("ok", run.stdout)

        refreshed = list_validation_recipes(self.project.id)[0]
        self.assertEqual(refreshed.last_status, "passed")
        self.assertEqual(refreshed.last_exit_code, 0)

        self.assertTrue(delete_validation_recipe(self.project.id, "unit-tests"))
        self.assertEqual(list_validation_recipes(self.project.id), [])

    def test_suggestions_and_project_model_include_validation_recipes(self) -> None:
        package_json = self.repo_dir / "package.json"
        package_json.write_text('{"scripts":{"test":"vitest","build":"vite build"}}', encoding="utf-8")
        upsert_validation_recipe(self.project.id, name="lint", command="npm run lint", kind="lint")

        recipes = list_validation_recipes(self.project.id, include_suggestions=True)
        names = {recipe.name: recipe.source for recipe in recipes}
        self.assertEqual(names["lint"], "stored")
        self.assertEqual(names["test"], "suggested")
        self.assertEqual(names["build"], "suggested")

        model = project_model(self.project.id)
        model_recipes = {item["name"]: item for item in model["validation_recipes"]}
        self.assertIn("lint", model_recipes)
        self.assertIn("test", model_recipes)

        brief = project_brief(self.project.id)
        self.assertIn("Validation recipes", brief)
        self.assertIn("npm run lint", brief)

    def test_tooling_saves_lists_and_runs_recipe(self) -> None:
        executor = ToolExecutor(default_tool_registry(), mode="chat")
        saved = executor.execute(
            ToolCall(
                "upsert_project_validation",
                {"project_id": self.project.id, "name": "smoke", "command": "python -c 'print(123)'", "kind": "smoke"},
            )
        )
        self.assertTrue(saved.ok, saved.error)

        listed = executor.execute(ToolCall("list_project_validation", {"project_id": self.project.id}))
        self.assertTrue(listed.ok, listed.error)
        self.assertIn("smoke", listed.content)

        call = ToolCall("run_project_validation", {"project_id": self.project.id, "name": "smoke"})
        required, reason = needs_permission(call, default_tool_registry().definition(call.tool))
        self.assertTrue(required)
        self.assertIn("permission", reason)

        result = executor.execute(call)
        self.assertTrue(result.ok, result.error)
        self.assertIn("123", result.content)
        self.assertEqual(result.metadata["validation"]["status"], "passed")

    def test_recipe_json_is_stable(self) -> None:
        recipe = upsert_validation_recipe(self.project.id, name="build", command="python -m compileall .", kind="build")
        data = recipe_to_json(recipe)
        self.assertEqual(data["name"], "build")
        self.assertEqual(data["source"], "stored")
        self.assertIn("last_status", data)


if __name__ == "__main__":
    unittest.main()
