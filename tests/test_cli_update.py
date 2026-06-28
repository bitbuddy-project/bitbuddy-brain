from __future__ import annotations

import argparse
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-cli-test-")

from bitbuddy import cli  # noqa: E402
from bitbuddy import __version__  # noqa: E402


class CliUpdateTest(unittest.TestCase):
    def test_parser_exposes_update_command(self) -> None:
        args = cli.build_parser().parse_args(["update", "--branch", "release", "--skip-doctor"])

        self.assertIs(args.handler, cli.update_command)
        self.assertEqual(args.branch, "release")
        self.assertTrue(args.skip_doctor)

    def test_dashboard_targets_backend_port(self) -> None:
        args = cli.build_parser().parse_args(["dashboard"])

        self.assertIs(args.handler, cli.run_dashboard)
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8787)
        self.assertFalse(hasattr(args, "api_port"))

    def test_update_builds_web_ui(self) -> None:
        from bitbuddy import web_build

        with patch.object(web_build, "ensure_web_build", return_value=True) as build, patch.object(
            cli, "source_checkout_root"
        ) as root, patch.object(
            cli, "checkout_has_local_changes", return_value=False
        ), patch.object(cli, "run_update_step"), patch("subprocess.run") as run, patch(
            "shutil.which", return_value="/usr/bin/tool"
        ):
            checkout = Path(tempfile.mkdtemp(prefix="bitbuddy-update-root-"))
            (checkout / ".git").mkdir()
            (checkout / "web").mkdir()
            (checkout / "web" / "package.json").write_text("{}", encoding="utf-8")
            root.return_value = checkout
            run.return_value = subprocess.CompletedProcess([], 0)

            result = cli.update_command(
                argparse.Namespace(branch="stable", no_autostash=False, skip_doctor=True)
            )

        self.assertEqual(result, 0)
        build.assert_called_once_with(force=True)

    def test_update_defaults_to_stable_branch(self) -> None:
        args = cli.build_parser().parse_args(["update", "--skip-doctor"])

        self.assertEqual(args.branch, "stable")

    def test_completion_includes_update(self) -> None:
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            cli.completion_command(argparse.Namespace(shell="bash"))

        self.assertIn("update", output.getvalue())

    def test_version_command_prints_package_version(self) -> None:
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            result = cli.version_command(argparse.Namespace())

        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().strip(), f"BitBuddy {__version__}")

    def test_global_version_flag_prints_package_version(self) -> None:
        output = io.StringIO()

        with self.assertRaises(SystemExit) as caught, contextlib.redirect_stdout(output):
            cli.build_parser().parse_args(["--version"])

        self.assertEqual(caught.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), f"BitBuddy {__version__}")

    def test_short_version_flag_prints_package_version(self) -> None:
        output = io.StringIO()

        with self.assertRaises(SystemExit) as caught, contextlib.redirect_stdout(output):
            cli.build_parser().parse_args(["-V"])

        self.assertEqual(caught.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), f"BitBuddy {__version__}")

    def test_source_checkout_root_finds_src_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_dir = root / "src" / "bitbuddy"
            package_dir.mkdir(parents=True)
            (root / "pyproject.toml").write_text("[project]\nname = 'bitbuddy'\n", encoding="utf-8")
            fake_cli = package_dir / "cli.py"
            fake_cli.write_text("", encoding="utf-8")

            with patch.object(cli, "__file__", str(fake_cli)):
                self.assertEqual(cli.source_checkout_root(), root)

    def test_update_requires_git_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            with patch("bitbuddy.cli.source_checkout_root", return_value=root):
                with self.assertRaisesRegex(ValueError, "requires a Git source checkout"):
                    cli.update_command(argparse.Namespace(branch="main", no_autostash=False, skip_doctor=True))

    def test_update_refuses_dirty_checkout_when_autostash_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()
            (root / "web").mkdir()
            (root / "web" / "package.json").write_text("{}", encoding="utf-8")

            status = subprocess.CompletedProcess(["git"], 0, stdout=" M src/bitbuddy/cli.py\n")
            with patch("bitbuddy.cli.source_checkout_root", return_value=root), \
                 patch("bitbuddy.cli.shutil.which", return_value="/usr/bin/tool"), \
                 patch("bitbuddy.cli.subprocess.run", return_value=status) as run:
                with self.assertRaisesRegex(ValueError, "checkout has local changes"):
                    cli.update_command(argparse.Namespace(branch="main", no_autostash=True, skip_doctor=True))

            run.assert_called_once_with(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True)

    def test_update_autostashes_dirty_checkout_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()
            (root / "web").mkdir()
            (root / "web" / "package.json").write_text("{}", encoding="utf-8")

            def fake_run(command, **kwargs):
                if command[:4] == ["git", "-C", str(root), "status"]:
                    return subprocess.CompletedProcess(command, 0, stdout=" M README.md\n")
                return subprocess.CompletedProcess(command, 0)

            with patch("bitbuddy.cli.source_checkout_root", return_value=root), \
                 patch("bitbuddy.cli.shutil.which", return_value="/usr/bin/tool"), \
                 patch("bitbuddy.cli.subprocess.run", side_effect=fake_run) as run:
                result = cli.update_command(argparse.Namespace(branch="main", no_autostash=False, skip_doctor=True))

        self.assertEqual(result, 0)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[1][:6], ["git", "-C", str(root), "stash", "push", "--include-untracked"])
        self.assertIn(["git", "-C", str(root), "stash", "apply", "stash@{0}"], commands)
        self.assertIn(["git", "-C", str(root), "stash", "drop", "stash@{0}"], commands)

    def test_update_runs_expected_steps(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()
            (root / "web").mkdir()
            (root / "web" / "package.json").write_text("{}", encoding="utf-8")

            def fake_run(command, **kwargs):
                if command[:4] == ["git", "-C", str(root), "status"]:
                    return subprocess.CompletedProcess(command, 0, stdout="")
                return subprocess.CompletedProcess(command, 0)

            with patch("bitbuddy.cli.source_checkout_root", return_value=root), \
                 patch("bitbuddy.cli.shutil.which", return_value="/usr/bin/tool"), \
                 patch("bitbuddy.web_build.ensure_web_build", return_value=True) as build, \
                 patch("bitbuddy.cli.subprocess.run", side_effect=fake_run) as run:
                result = cli.update_command(argparse.Namespace(branch="main", no_autostash=False, skip_doctor=False))

        self.assertEqual(result, 0)
        build.assert_called_once_with(force=True)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(
            commands,
            [
                ["git", "-C", str(root), "status", "--porcelain"],
                ["git", "-C", str(root), "fetch", "--prune", "origin", "main"],
                ["git", "-C", str(root), "pull", "--ff-only", "origin", "main"],
                [sys.executable, "-m", "pip", "install", "-e", str(root)],
                [sys.executable, "-m", "bitbuddy", "--help"],
                [sys.executable, "-m", "bitbuddy", "doctor"],
            ],
        )


if __name__ == "__main__":
    unittest.main()
