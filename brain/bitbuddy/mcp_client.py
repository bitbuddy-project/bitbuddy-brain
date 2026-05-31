from __future__ import annotations

import atexit
import json
import os
import queue
import subprocess
import threading
from dataclasses import dataclass
from typing import Any

from .config import McpServerConfig
from .managed_tools import resolve_managed_command


class McpError(RuntimeError):
    pass


@dataclass(frozen=True)
class McpToolInfo:
    name: str
    description: str
    input_schema: dict[str, object]
    annotations: dict[str, object]


class McpStdioClient:
    def __init__(self, config: McpServerConfig) -> None:
        self.config = config
        self._process: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self._messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self._lock = threading.Lock()
        self._next_id = 1
        self._initialized = False

    def tools(self) -> list[McpToolInfo]:
        response = self.request("tools/list", {}, timeout=self.config.connect_timeout)
        raw_tools = response.get("tools") if isinstance(response, dict) else None
        if not isinstance(raw_tools, list):
            return []
        tools: list[McpToolInfo] = []
        for raw_tool in raw_tools:
            if not isinstance(raw_tool, dict):
                continue
            name = str(raw_tool.get("name") or "").strip()
            if not name:
                continue
            input_schema = raw_tool.get("inputSchema") if isinstance(raw_tool.get("inputSchema"), dict) else {}
            annotations = raw_tool.get("annotations") if isinstance(raw_tool.get("annotations"), dict) else {}
            tools.append(
                McpToolInfo(
                    name=name,
                    description=str(raw_tool.get("description") or f"MCP tool {name}"),
                    input_schema=dict(input_schema),
                    annotations=dict(annotations),
                )
            )
        return tools

    def call_tool(self, tool_name: str, arguments: dict[str, object]) -> dict[str, Any]:
        return self.request(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
            timeout=self.config.timeout,
        )

    def request(self, method: str, params: dict[str, object], timeout: float) -> dict[str, Any]:
        self.ensure_started()
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            self._write_message({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})

            while True:
                try:
                    message = self._messages.get(timeout=timeout)
                except queue.Empty as error:
                    raise McpError(f"MCP server `{self.config.name}` timed out during {method}.") from error
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    raise McpError(format_mcp_error(message["error"]))
                result = message.get("result")
                return result if isinstance(result, dict) else {}

    def ensure_started(self) -> None:
        if self._process is not None and self._process.poll() is None and self._initialized:
            return
        self.close()
        env = os.environ.copy()
        env.update(self.config.env)
        command = resolve_managed_command(self.config.command)
        try:
            self._process = subprocess.Popen(
                [command, *self.config.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                env=env,
            )
        except OSError as error:
            raise McpError(f"Could not start MCP server `{self.config.name}`: {error}") from error

        self._reader = threading.Thread(target=self._read_loop, name=f"mcp-{self.config.name}-reader", daemon=True)
        self._reader.start()
        self._initialize()

    def _initialize(self) -> None:
        with self._lock:
            request_id = self._next_id
            self._next_id += 1
            self._write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "bitbuddy", "version": "0.1.0"},
                    },
                }
            )
            while True:
                try:
                    message = self._messages.get(timeout=self.config.connect_timeout)
                except queue.Empty as error:
                    raise McpError(f"MCP server `{self.config.name}` did not initialize.") from error
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    raise McpError(format_mcp_error(message["error"]))
                self._write_message({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
                self._initialized = True
                return

    def _write_message(self, message: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            raise McpError(f"MCP server `{self.config.name}` is not running.")
        process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        process.stdin.flush()

    def _read_loop(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            clean = line.strip()
            if not clean:
                continue
            try:
                message = json.loads(clean)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                self._messages.put(message)

    def close(self) -> None:
        process = self._process
        self._process = None
        self._reader = None
        self._initialized = False
        if process is None:
            return
        for stream in (process.stdin, process.stdout):
            try:
                if stream is not None:
                    stream.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()


_CLIENTS: dict[str, McpStdioClient] = {}
_CLIENTS_LOCK = threading.Lock()


def get_mcp_client(config: McpServerConfig) -> McpStdioClient:
    with _CLIENTS_LOCK:
        client = _CLIENTS.get(config.name)
        if client is None or client.config != config:
            if client is not None:
                client.close()
            client = McpStdioClient(config)
            _CLIENTS[config.name] = client
        return client


def close_mcp_clients() -> None:
    with _CLIENTS_LOCK:
        clients = list(_CLIENTS.values())
        _CLIENTS.clear()
    for client in clients:
        client.close()


def format_mcp_error(error: object) -> str:
    if isinstance(error, dict):
        message = error.get("message")
        code = error.get("code")
        if message and code is not None:
            return f"MCP error {code}: {message}"
        if message:
            return str(message)
    return str(error)


atexit.register(close_mcp_clients)
