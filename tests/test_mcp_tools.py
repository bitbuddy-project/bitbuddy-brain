from __future__ import annotations

import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="bitbuddy-mcp-test-")

from bitbuddy.config import ProviderConfig, load_config, update_mcp_config, update_model_runtime_config, upsert_mcp_server, write_config  # noqa: E402
from bitbuddy import cli  # noqa: E402
from bitbuddy.managed_tools import ManagedToolStatus, resolve_managed_command  # noqa: E402
from bitbuddy.mcp_client import close_mcp_clients  # noqa: E402
from bitbuddy.paths import CONFIG_PATH  # noqa: E402
from bitbuddy.tools import ToolCall, ToolDefinition, ToolExecutor, needs_permission  # noqa: E402
from bitbuddy.toolbox.registry import default_tool_registry  # noqa: E402


class McpToolsTest(unittest.TestCase):
    def tearDown(self) -> None:
        close_mcp_clients()
        if CONFIG_PATH.exists():
            CONFIG_PATH.unlink()

    def test_mcp_config_round_trip(self) -> None:
        config = upsert_mcp_server("computer-use-linux", "computer-use-linux", ["mcp"])

        self.assertEqual(config.mcp_servers[0].name, "computer_use_linux")
        self.assertEqual(config.mcp_servers[0].command, "computer-use-linux")
        self.assertEqual(config.mcp_servers[0].args, ("mcp",))
        self.assertEqual(load_config().mcp_servers[0].name, "computer_use_linux")

    def test_default_config_keeps_mcp_opt_in(self) -> None:
        config = load_config()

        self.assertFalse(config.mcp.enabled)
        self.assertEqual(config.mcp_servers, ())
        self.assertTrue(resolve_managed_command("managed:computer-use-linux").endswith("computer-use-linux"))

    def test_provision_computer_use_linux_installs_managed_binary(self) -> None:
        missing = ManagedToolStatus("computer-use-linux", False, "/tmp/missing", "missing", "missing")
        installed = ManagedToolStatus("computer-use-linux", True, "/tmp/computer-use-linux", "managed", "installed")

        with (
            patch.object(cli.sys, "platform", "linux"),
            patch("bitbuddy.cli.computer_use_linux_status", return_value=missing),
            patch("bitbuddy.cli.install_computer_use_linux", return_value=installed) as install,
        ):
            ok, message = cli.provision_computer_use_linux()

        self.assertTrue(ok)
        self.assertEqual(message, "installed")
        install.assert_called_once()
        server = next(server for server in load_config().mcp_servers if server.name == "computer_use_linux")
        self.assertEqual(server.command, "managed:computer-use-linux")
        self.assertTrue(load_config().mcp.enabled)

    def test_setup_skip_preserves_existing_provider(self) -> None:
        class ExistingConfig:
            provider = ProviderConfig(type="ollama", url="http://127.0.0.1:11434", model="llama3")

        provider, preserved = cli.provider_config_from_setup_choice("Skip for now", "Modify current setup", ExistingConfig())

        self.assertTrue(preserved)
        self.assertEqual(provider.type, "ollama")
        self.assertEqual(provider.url, "http://127.0.0.1:11434")
        self.assertEqual(provider.model, "llama3")

    def test_preserve_existing_config_keeps_custom_mcp_servers(self) -> None:
        write_config("ollama", "http://127.0.0.1:11434", "llama3")
        upsert_mcp_server("custom-server", sys.executable, ["-u", "server.py"], timeout=9, connect_timeout=3)

        write_config("ollama", "http://127.0.0.1:11434", "llama3", name="Renamed", preserve_existing=True)
        config = load_config()

        self.assertEqual(config.name, "Renamed")
        self.assertTrue(any(server.name == "custom_server" for server in config.mcp_servers))

    def test_selective_preserve_keeps_provider_registry_and_scan_interval(self) -> None:
        write_config("ollama", "http://127.0.0.1:11434", "llama3")
        update_model_runtime_config(
            {
                "providers": [
                    {"type": "ollama", "url": "http://127.0.0.1:11434", "model": "llama3"},
                    {"type": "llama.cpp", "url": "http://127.0.0.1:8080", "model": "qwen"},
                ],
                "active_provider": "ollama",
                "project_scan_interval_seconds": 120,
            }
        )

        write_config(
            "ollama",
            "http://127.0.0.1:11434",
            "llama3",
            60,
            name="Renamed",
            preserve_existing=True,
            update_provider=False,
            update_project_scan_interval=False,
        )
        config = load_config()

        self.assertEqual(config.name, "Renamed")
        self.assertEqual({provider.type for provider in config.providers}, {"ollama", "llama.cpp"})
        self.assertEqual(config.project_scan_interval_seconds, 120)

    def test_mcp_tools_are_discovered_and_callable(self) -> None:
        server_script = write_fake_mcp_server()
        update_mcp_config({"enabled": True})
        upsert_mcp_server("fake", sys.executable, ["-u", str(server_script)], timeout=5, connect_timeout=5)

        registry = default_tool_registry()
        definitions = {definition.name: definition for definition in registry.definitions()}

        self.assertIn("mcp_fake_list_windows", definitions)
        self.assertIn("mcp_fake_click", definitions)
        self.assertTrue(definitions["mcp_fake_list_windows"].annotations["readOnlyHint"])
        self.assertFalse(definitions["mcp_fake_click"].annotations["readOnlyHint"])

        result = ToolExecutor(registry).execute(ToolCall("mcp_fake_list_windows", {}))

        self.assertTrue(result.ok)
        self.assertIn("Fake Window", result.content)
        self.assertEqual(result.arguments_summary["mcp_server"], "fake")
        self.assertEqual(result.arguments_summary["mcp_tool"], "list_windows")

    def test_mcp_tools_are_not_discovered_when_mcp_disabled(self) -> None:
        server_script = write_fake_mcp_server()
        upsert_mcp_server("fake", sys.executable, ["-u", str(server_script)], timeout=5, connect_timeout=5)

        definitions = {definition.name for definition in default_tool_registry().definitions()}

        self.assertNotIn("mcp_fake_list_windows", definitions)

    def test_mcp_permissions_and_mode_boundaries_use_annotations(self) -> None:
        read_only = ToolDefinition(
            "mcp_fake_list_windows",
            "List windows.",
            {"type": "object"},
            1000,
            annotations={"mcp": True, "mcp_server": "fake", "mcp_tool": "list_windows", "readOnlyHint": True},
        )
        mutating = ToolDefinition(
            "mcp_fake_click",
            "Click.",
            {"type": "object"},
            1000,
            annotations={
                "mcp": True,
                "mcp_server": "fake",
                "mcp_tool": "click",
                "readOnlyHint": False,
                "destructiveHint": True,
                "openWorldHint": True,
            },
        )

        self.assertEqual(needs_permission(ToolCall(read_only.name, {}), read_only), (False, ""))
        required, reason = needs_permission(ToolCall(mutating.name, {}), mutating)
        self.assertTrue(required)
        self.assertIn("control external app", reason)

        registry = default_tool_registry()
        registry.register(read_only, lambda _args, definition: None)  # type: ignore[arg-type]
        registry.register(mutating, lambda _args, definition: None)  # type: ignore[arg-type]
        executor = ToolExecutor(registry, mode="plan")

        self.assertEqual(executor.check_mode_restrictions(ToolCall(read_only.name, {})), "")
        self.assertIn("Plan mode is strictly read-only", executor.check_mode_restrictions(ToolCall(mutating.name, {})))


def write_fake_mcp_server() -> Path:
    path = Path(tempfile.mkdtemp(prefix="bitbuddy-fake-mcp-")) / "fake_mcp.py"
    path.write_text(
        textwrap.dedent(
            r'''
            import json
            import sys

            def send(payload):
                sys.stdout.write(json.dumps(payload) + "\n")
                sys.stdout.flush()

            for line in sys.stdin:
                message = json.loads(line)
                method = message.get("method")
                request_id = message.get("id")
                if request_id is None:
                    continue
                if method == "initialize":
                    send({"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "fake", "version": "1"}}})
                elif method == "tools/list":
                    send({"jsonrpc": "2.0", "id": request_id, "result": {"tools": [
                        {"name": "list_windows", "description": "List fake windows.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}, "annotations": {"readOnlyHint": True}},
                        {"name": "click", "description": "Click fake UI.", "inputSchema": {"type": "object", "properties": {"selector": {"type": "string"}}}, "annotations": {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True}}
                    ]}})
                elif method == "tools/call":
                    send({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": "Fake Window"}], "isError": False}})
            '''
        ),
        encoding="utf-8",
    )
    return path


if __name__ == "__main__":
    unittest.main()
