# BitBuddy Agent

BitBuddy is your local companion that learns your projects, grows with you, and keeps its memory close to home.

## Setup

Install the Python package in editable mode:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Run the interactive setup:

```bash
bitbuddy setup
```

Setup creates `~/.bitbuddy`, asks what to name your BitBuddy, writes `config.yaml` and `personality.yaml`, configures Ollama or llama.cpp, tries to detect and pre-fill the model name from the provider URL, and optionally creates a project memory. It does not install web dependencies or desktop-control tools.

If `~/.bitbuddy/config.yaml` already exists, setup asks whether to modify the current setup, keep it, or start a new setup. The project memory scan interval is configurable during setup; `60` seconds is the default and `0` disables the monitor.

## Server

Start the BitBuddy backend server:

```bash
bitbuddy serve
```

Defaults are equivalent to:

```bash
bitbuddy serve --host 127.0.0.1 --port 8787
```

The server exposes the local BitBuddy API, including health, config, provider, project memory, indexing, project map, and streaming chat endpoints.

While running, the server monitors registered project memories on the configured timer and writes activity events into `~/.bitbuddy/bitbuddy.sqlite`.

`bitbuddy serve` also starts BitBuddy's managed local SearxNG-compatible web search backend when web search is enabled. The LLM uses this backend through the `web_search` tool; users do not need to start a separate SearxNG process for the default setup.

## Providers

BitBuddy stores local model provider settings in `~/.bitbuddy/config.yaml`.

Check provider connectivity:

```bash
bitbuddy provider check
```

List models reported by the provider:

```bash
bitbuddy provider models
```

Run a diagnostic streaming call that separates thinking from response output:

```bash
bitbuddy provider stream-test --prompt "Say hello briefly."
```

Ollama uses `/api/chat`. llama.cpp uses the OpenAI-compatible `/v1/chat/completions` stream. BitBuddy separates explicit `reasoning_content` fields and `<think>...</think>` text from normal response text.

## Web App

Start the SvelteKit/Vite dev server:

```bash
cd web
npm install
cd ..
bitbuddy web
```

The chat page streams through `bitbuddy serve` at `http://127.0.0.1:8787`, including separate thinking and response chunks.

Defaults are equivalent to:

```bash
bitbuddy web --host 127.0.0.1 --port 5173
```

## Project Memories

Project memories are named, read-only project paths with per-project SQLite databases under `~/.bitbuddy/projects`.

```bash
bitbuddy projects add my-project /path/to/project
bitbuddy projects index my-project
bitbuddy projects map my-project
bitbuddy projects list
```

BitBuddy does not receive broad home-directory access by default. Project paths are explicit and read-only; BitBuddy only writes its own config and SQLite files under `~/.bitbuddy`.

Generated artifacts default to `~/.bitbuddy/artifacts`. BitBuddy has first-class `write_file`, `patch_file`, and `make_directory` tools for creating deterministic files there, then `run_shell_command` with `working_directory` for validation/export commands. Writes outside the managed artifacts workspace require approval.

## MCP And Desktop Control

BitBuddy can discover tools from local stdio MCP servers. MCP discovery is opt-in from Settings. Built-in web search is separate and remains enabled by default when web search is enabled.

Linux desktop control is self-contained and managed under `~/.bitbuddy/tools/bin` only when you install it explicitly from Settings or the CLI.

CLI install/configure/repair commands:

```bash
bitbuddy mcp add-computer-use-linux
bitbuddy mcp doctor-computer-use-linux
bitbuddy mcp list
```

The managed setup exposes tools such as `mcp_computer_use_linux_list_windows`, `mcp_computer_use_linux_get_app_state`, `mcp_computer_use_linux_perform_action`, `mcp_computer_use_linux_set_value`, `mcp_computer_use_linux_click`, `mcp_computer_use_linux_type_text`, and `mcp_computer_use_linux_press_key` when the MCP server is reachable.

You can also install or update only the bundled desktop-control binary:

```bash
bitbuddy mcp install-computer-use-linux
```

Read-only MCP tools can run in Plan mode. Mutating MCP tools are blocked in Plan mode and require approval in Chat mode before BitBuddy can control external apps or system state.

## Skills

BitBuddy skills are reusable procedures stored under `~/.bitbuddy/skills/<skill-name>/SKILL.md`. Each skill is a Markdown file with YAML frontmatter plus optional supporting files under `references/`, `templates/`, `scripts/`, or `assets/`.

On first use, BitBuddy seeds starter skills such as `skill-authoring`, `skill-curation`, `systematic-debugging`, `frontend-svelte-workflow`, and `bitbuddy-development`. The model can list, load, create, patch, archive, validate, and add support files for skills through dedicated safe tools that are confined to `~/.bitbuddy/skills/`.
