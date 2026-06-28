from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-project-specs-test-")

from bitbuddy.auth import API_TOKEN_HEADER, get_api_token  # noqa: E402
from bitbuddy.http_api import BitBuddyRequestHandler  # noqa: E402
from bitbuddy.memory.project import index_project, register_project, unregister_project  # noqa: E402
from bitbuddy.memory.project_specs import (  # noqa: E402
    ACTIVE_BODY_LIMIT,
    archive_project_spec,
    create_project_spec,
    list_project_specs,
    read_project_spec,
    reconcile_spec_index,
    update_project_spec,
)
from bitbuddy.memory.project_views import project_model  # noqa: E402
from bitbuddy.projects.context import build_project_context_pack  # noqa: E402


class ProjectSpecsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_dir = Path(tempfile.mkdtemp(prefix="bitbuddy-specs-repo-"))
        (self.repo_dir / "README.md").write_text("# Demo project\n", encoding="utf-8")
        self.project = register_project("demo", [str(self.repo_dir)])
        index_project(self.project.id)

    def tearDown(self) -> None:
        unregister_project(self.project.id)

    def test_create_spec_writes_markdown_file_and_returns_body(self) -> None:
        spec = create_project_spec(
            self.project.id,
            "Auth Redesign",
            body="# Purpose\n\nBetter auth.\n",
            tags=["backend", "security"],
            status="active",
        )

        self.assertEqual(spec.title, "Auth Redesign")
        self.assertEqual(spec.status, "active")
        self.assertEqual(spec.tags, ["backend", "security"])
        self.assertTrue(spec.id.startswith("auth-redesign"))

        spec_file = self.project.metadata_path.parent / spec.rel_path
        self.assertTrue(spec_file.is_file())
        text = spec_file.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---"))
        self.assertIn("title: Auth Redesign", text)
        self.assertIn("# Purpose", text)
        self.assertIn("Better auth.", text)

    def test_list_excludes_archived_by_default(self) -> None:
        kept = create_project_spec(self.project.id, "Kept Spec", body="x", status="active")
        archived = create_project_spec(self.project.id, "To Archive", body="y", status="active")
        archive_project_spec(self.project.id, archived.id)

        default_list = list_project_specs(self.project.id)
        ids = [spec.id for spec in default_list]
        self.assertIn(kept.id, ids)
        self.assertNotIn(archived.id, ids)

        with_archived = list_project_specs(self.project.id, include_archived=True)
        all_ids = [spec.id for spec in with_archived]
        self.assertIn(archived.id, all_ids)

    def test_read_spec_includes_body(self) -> None:
        created = create_project_spec(self.project.id, "Readable", body="## Goals\n\n- ship it\n")
        spec = read_project_spec(self.project.id, created.id)
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertIn("ship it", spec.body)

    def test_update_spec_changes_fields_and_timestamps(self) -> None:
        original = create_project_spec(self.project.id, "Rename Me", body="old", status="draft")
        updated = update_project_spec(
            self.project.id,
            original.id,
            title="Renamed",
            body="new body",
            status="active",
            tags=["x"],
        )
        self.assertIsNotNone(updated)
        assert updated is not None
        self.assertEqual(updated.title, "Renamed")
        self.assertEqual(updated.status, "active")
        self.assertEqual(updated.tags, ["x"])
        self.assertIn("new body", updated.body)

        disk = (self.project.metadata_path.parent / original.rel_path).read_text(encoding="utf-8")
        self.assertIn("title: Renamed", disk)
        self.assertIn("status: active", disk)

    def test_status_is_normalized_to_known_values(self) -> None:
        spec = create_project_spec(self.project.id, "Weird Status", body="z", status="bogus")
        self.assertEqual(spec.status, "draft")

    def test_duplicate_titles_get_unique_ids(self) -> None:
        first = create_project_spec(self.project.id, "Dup Title", body="a")
        second = create_project_spec(self.project.id, "Dup Title", body="b")
        self.assertNotEqual(first.id, second.id)

    def test_active_specs_cap_body_for_context(self) -> None:
        long_body = "\n\n".join(f"Paragraph {i}." for i in range(800))
        long_spec = create_project_spec(self.project.id, "Long Spec", body=long_body, status="active")
        model = project_model(self.project.id, limit=20)
        specs = {spec["id"]: spec for spec in model.get("project_specs", [])}
        self.assertIn(long_spec.id, specs, "active long spec should appear in project model")
        body = specs[long_spec.id]["body"]
        self.assertLessEqual(len(body), ACTIVE_BODY_LIMIT + 80)
        self.assertIn("truncated", body)

    def test_draft_specs_are_not_in_project_model(self) -> None:
        draft = create_project_spec(self.project.id, "Hidden Draft", body="secret", status="draft")
        model = project_model(self.project.id, limit=4)
        ids = [spec["id"] for spec in model.get("project_specs", [])]
        self.assertNotIn(draft.id, ids)

    def test_reindexing_does_not_drop_specs(self) -> None:
        spec = create_project_spec(self.project.id, "Survives Reindex", body="persistent", status="active")
        index_project(self.project.id)
        spec_after = read_project_spec(self.project.id, spec.id)
        self.assertIsNotNone(spec_after)
        assert spec_after is not None
        self.assertEqual(spec_after.status, "active")

    def test_context_pack_includes_active_spec_section(self) -> None:
        create_project_spec(
            self.project.id,
            "Context Pack Spec",
            body="# Purpose\n\nThe grand plan.\n\n## Requirements\n- ship it",
            status="active",
        )
        pack = build_project_context_pack(
            [{"role": "user", "content": f"how should we refactor the {self.project.name} backend?"}],
            "chat",
            max_chars=9000,
        )
        self.assertIsNotNone(pack)
        assert pack is not None
        self.assertIn("Active specs", pack)
        self.assertIn("Context Pack Spec", pack)

    def test_reconcile_picks_up_hand_edited_spec_file(self) -> None:
        specs_dir = self.project.metadata_path.parent / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        path = specs_dir / "hand-edited.md"
        path.write_text(
            "---\nid: hand-edited\ntitle: Hand Edited\nstatus: active\ntags: [manual]\n---\n\nbody from disk\n",
            encoding="utf-8",
        )
        added = reconcile_spec_index(self.project.id)
        self.assertGreaterEqual(added, 1)
        spec = read_project_spec(self.project.id, "hand-edited")
        self.assertIsNotNone(spec)
        assert spec is not None
        self.assertEqual(spec.title, "Hand Edited")
        self.assertIn("body from disk", spec.body)


class ProjectSpecsHttpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_dir = Path(tempfile.mkdtemp(prefix="bitbuddy-specs-http-repo-"))
        (cls.repo_dir / "README.md").write_text("# HTTP demo\n", encoding="utf-8")
        cls.project = register_project("httpdemo", [str(cls.repo_dir)])

    def _request(self, base_url: str, method: str, path: str, payload: object | None = None) -> tuple[int, dict]:
        data = None
        headers = {API_TOKEN_HEADER: get_api_token()}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(f"{base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return int(response.status), json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8")
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = {"raw": body}
            return int(error.code), parsed

    def test_post_then_get_then_patch_then_archive_endpoints(self) -> None:
        with running_api_server() as base_url:
            project_id = urllib.parse.quote(self.project.id)

            status, body = self._request(
                base_url,
                "POST",
                f"/projects/{project_id}/specs",
                {"title": "HTTP Spec", "body": "initial", "status": "active", "tags": ["api"]},
            )
            self.assertEqual(status, 201, body)
            spec = body["spec"]
            self.assertEqual(spec["title"], "HTTP Spec")
            self.assertEqual(spec["status"], "active")
            spec_id = urllib.parse.quote(spec["id"])

            status, body = self._request(base_url, "GET", f"/projects/{project_id}/specs")
            self.assertEqual(status, 200, body)
            self.assertGreaterEqual(len(body["specs"]), 1)

            status, body = self._request(base_url, "GET", f"/projects/{project_id}/specs/{spec_id}")
            self.assertEqual(status, 200, body)
            self.assertIn("initial", body["spec"]["body"])

            status, body = self._request(
                base_url,
                "PATCH",
                f"/projects/{project_id}/specs/{spec_id}",
                {"title": "HTTP Spec v2", "body": "updated body", "status": "active"},
            )
            self.assertEqual(status, 200, body)
            self.assertEqual(body["spec"]["title"], "HTTP Spec v2")
            self.assertIn("updated body", body["spec"]["body"])

            status, body = self._request(
                base_url,
                "POST",
                f"/projects/{project_id}/specs/{spec_id}/archive",
            )
            self.assertEqual(status, 200, body)
            self.assertEqual(body["spec"]["status"], "archived")

            status, _body = self._request(base_url, "GET", f"/projects/{project_id}/specs")
            self.assertEqual(status, 200)
            self.assertEqual(_body["specs"], [])

            status, body = self._request(
                base_url,
                "GET",
                f"/projects/{project_id}/specs?include_archived=true",
            )
            self.assertEqual(status, 200)
            self.assertGreaterEqual(len(body["specs"]), 1)

    def test_create_requires_title(self) -> None:
        with running_api_server() as base_url:
            project_id = urllib.parse.quote(self.project.id)
            status, body = self._request(
                base_url,
                "POST",
                f"/projects/{project_id}/specs",
                {"body": "no title"},
            )
            self.assertEqual(status, 400, body)
            self.assertIn("title", body.get("error", ""))


class running_api_server:
    def __enter__(self) -> str:
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), BitBuddyRequestHandler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return f"http://127.0.0.1:{self.server.server_port}"

    def __exit__(self, *_args: object) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
