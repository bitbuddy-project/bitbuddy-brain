from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "brain"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-doctor-test-")

from bitbuddy.doctor.checks import http_search_results_ok, run_doctor_checks  # noqa: E402
from bitbuddy.doctor.fixers import fix_config_create_default, fix_db_init  # noqa: E402
from bitbuddy.doctor.report import DoctorCheckResult, doctor_exit_code, render_doctor_report  # noqa: E402
from bitbuddy.paths import APP_DIR, CONFIG_PATH, GLOBAL_DB_PATH  # noqa: E402


class FakeHttpResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self, _limit: int = -1) -> bytes:
        return self.body


class DoctorTest(unittest.TestCase):
    def setUp(self) -> None:
        if APP_DIR.exists():
            shutil.rmtree(APP_DIR)

    def test_doctor_missing_config_is_read_only(self) -> None:
        self.assertFalse(CONFIG_PATH.exists())

        results = run_doctor_checks()

        self.assertFalse(CONFIG_PATH.exists())
        missing = next(result for result in results if result.id == "config.exists")
        self.assertEqual(missing.status, "fail")
        self.assertEqual(missing.fix_id, "config.create_default")

    def test_config_fix_creates_default_config(self) -> None:
        self.assertFalse(CONFIG_PATH.exists())

        result = fix_config_create_default()

        self.assertTrue(result.ok)
        self.assertTrue(CONFIG_PATH.exists())

    def test_db_fix_initializes_key_tables(self) -> None:
        result = fix_db_init()

        self.assertTrue(result.ok)
        self.assertTrue(GLOBAL_DB_PATH.exists())
        with sqlite3.connect(GLOBAL_DB_PATH) as connection:
            tables = {row[0] for row in connection.execute("select name from sqlite_master where type = 'table'").fetchall()}
        self.assertIn("activity", tables)
        self.assertIn("chats", tables)
        self.assertIn("memories", tables)
        self.assertIn("intentions", tables)
        self.assertIn("workspace_documents", tables)

    def test_report_exit_codes_and_fix_hint(self) -> None:
        results = [
            DoctorCheckResult("ok", "System", "pass", "Python version OK"),
            DoctorCheckResult("warn", "Autonomy", "warn", "High usage", "Heads up."),
        ]
        self.assertEqual(doctor_exit_code(results), 0)

        failing = [*results, DoctorCheckResult("missing", "Config", "fail", "Config missing", fix_id="config.create_default")]
        self.assertEqual(doctor_exit_code(failing), 1)
        rendered = render_doctor_report(failing)
        self.assertIn("BitBuddy Doctor", rendered)
        self.assertIn("Run: bitbuddy doctor fix", rendered)

    def test_web_search_check_warns_on_empty_results(self) -> None:
        with patch("bitbuddy.doctor.checks.urllib.request.urlopen", return_value=FakeHttpResponse(b'{"results": []}')):
            ok, detail = http_search_results_ok("http://127.0.0.1:8888/search?q=bitbuddy+doctor")

        self.assertFalse(ok)
        self.assertIn("0 result", detail)


if __name__ == "__main__":
    unittest.main()
