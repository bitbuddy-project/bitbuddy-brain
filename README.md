<p align="center">
  <img src="assets/bitbuddy-app.png" alt="BitBuddy app icon" width="180" />
  <br />
  <img src="assets/bitbuddy-text.png" alt="BitBuddy" width="320" />
</p>

BitBuddy is your local companion that learns your projects, grows with you, and keeps its memory close to home.

## Setup

Requirements: Python 3.11+ and, for the web UI, Node.js 18+ (LTS recommended) with npm.

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

## Update

If BitBuddy was installed from the public source installer, update the local checkout and dependencies with:

```bash
bitbuddy update
```

`bitbuddy update` follows the `stable` release branch by default. It requires a Git checkout, stashes and restores local uncommitted changes by default, reinstalls the Python package, refreshes web dependencies, rebuilds the static web UI, smoke-checks the CLI, and runs `bitbuddy doctor` when it finishes. Use `--branch main` for development builds, or `--no-autostash` if you prefer the update to refuse local changes instead.

## Server

Start the BitBuddy local server:

```bash
bitbuddy serve
```

Defaults are equivalent to:

```bash
bitbuddy serve --host 127.0.0.1 --port 8787
```

The server hosts both the local BitBuddy API and the built web UI on the same origin. API endpoints include health, config, provider, project memory, indexing, project map, tasks, and streaming chat.

While running, the server monitors registered project memories on the configured timer and writes activity events into `~/.bitbuddy/bitbuddy.sqlite`.

`bitbuddy serve` also starts BitBuddy's managed local SearxNG-compatible web search backend when web search is enabled. The LLM uses this backend through the `web_search` tool; users do not need to start a separate SearxNG process for the default setup.

## Dashboard

Open the local web UI:

```bash
bitbuddy dashboard
```

`bitbuddy dashboard` ensures `bitbuddy serve` is running, then opens the backend-hosted dashboard in your browser. If the server is already running on loopback, you can also visit `http://127.0.0.1:8787` directly.

## Background Service

On Linux systems with user systemd, BitBuddy can keep the backend running after login. `bitbuddy setup` can install and enable this near the end of setup, or you can manage it later from the CLI:

```bash
bitbuddy service install
bitbuddy service enable
bitbuddy service status
bitbuddy service logs -f
bitbuddy service restart
bitbuddy service disable
```

The service runs `bitbuddy serve --host 127.0.0.1 --port 8787`, which hosts both the API and built web UI. Open the UI with `bitbuddy dashboard` when you want to use the app.

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

For dashboard development, start the SvelteKit/Vite dev server:

```bash
cd web
npm install
cd ..
bitbuddy web
```

The dev web app streams through `bitbuddy serve` at `http://127.0.0.1:8787`, including separate thinking and response chunks. Normal users do not need this command; `bitbuddy serve` hosts the built dashboard.

Defaults are equivalent to:

```bash
bitbuddy web --host 127.0.0.1 --port 5173
```

## Remote Access and the API Token

By default the backend binds to `127.0.0.1` (loopback only), so it is reachable only from the same machine. On first run BitBuddy generates a local API token at `~/.bitbuddy/api_token` (file permissions `0600`). The web UI uses it automatically through the tokenized localhost URL; any other client must send it as the `X-BitBuddy-Token` header.

Print or rotate the token:

```bash
bitbuddy auth token     # print the current token (creates one if missing)
bitbuddy auth rotate    # generate a new token, invalidating the old one
```

To reach BitBuddy from another device on your network, start the backend with `--allow-lan` (`bitbuddy serve --allow-lan`). LAN access requires the API token. For exposure beyond your LAN, put BitBuddy behind a reverse proxy that terminates TLS (for example nginx or Caddy) and forwards to the loopback port — do not expose the plain HTTP port directly to the internet.

## Self-Hosted Gmail OAuth

BitBuddy does not ship a Google OAuth client ID or client secret. For Gmail access, each self-hosted user creates their own Google OAuth client and stores those credentials locally.

Recommended setup:

1. Create or open a Google Cloud project.
2. Enable the Gmail API.
3. Configure Google Auth Platform for external/testing use.
4. Add your Google account as a test user while the app is in testing mode.
5. Add the Gmail scope `https://www.googleapis.com/auth/gmail.modify` in Data Access. If you want BitBuddy to permanently delete messages or empty Trash, enable Full Gmail access in BitBuddy and add `https://mail.google.com/` instead.
6. Create an OAuth client with application type `Desktop app`.
7. Paste the Desktop client ID and client secret into BitBuddy Settings -> Email.
8. Save email settings, then connect Gmail.

The client secret and Gmail tokens are stored in BitBuddy's local secret store under `~/.bitbuddy`; they are not written into `config.yaml` and are not bundled with BitBuddy.

Browser extensions can break Google OAuth before BitBuddy receives a callback. URL-cleaning extensions such as ClearURLs, redirect cleaners, tracking-parameter strippers, and container extensions may remove Google OAuth parameters such as `state`, `code`, `redirect_uri`, or Google warning-page parameters. If OAuth fails with Google's generic "Something went wrong" page, disable those extensions or whitelist `accounts.google.com`, `oauth2.googleapis.com`, `google.com`, `127.0.0.1`, and `localhost`. BitBuddy's clean browser OAuth action opens a disposable browser profile to bypass normal extension/profile state.

## Troubleshooting

Run BitBuddy Doctor first when setup, startup, storage, the web UI, autonomy, or web search is not behaving:

```bash
bitbuddy doctor
```

If Doctor reports safe automatic repairs, run:

```bash
bitbuddy doctor fix
```

Doctor checks setup, storage, SQLite, provider configuration, web dependencies, backend/web ports, autonomy, and web search. `bitbuddy doctor` is read-only. `bitbuddy doctor fix` only performs safe repairs such as creating missing BitBuddy-owned directories, creating a default config when missing, initializing missing SQLite tables, and installing local web dependencies with `npm install` in `web/`. It does not delete memories, reset databases, change provider keys, modify project files, open firewall ports, or install global system packages.

## Project Memories

Project memories are named, read-only project paths with per-project SQLite databases under `~/.bitbuddy/projects`.

```bash
bitbuddy projects add my-project /path/to/project
bitbuddy projects index my-project
bitbuddy projects map my-project
bitbuddy projects list
```

BitBuddy does not receive broad home-directory access by default. Project paths are explicit and read-only; BitBuddy only writes its own config and SQLite files under `~/.bitbuddy`.

Project Specs are Markdown notes attached to a registered project. Create and edit specs from the Projects dashboard, mark active specs when they should guide future work, and archive old specs without deleting their history. Active specs are included in project context for chat and autonomous work.

Generated artifacts default to `~/.bitbuddy/artifacts`. BitBuddy has first-class `write_file`, `patch_file`, and `make_directory` tools for creating deterministic files there, then `run_shell_command` with `working_directory` for validation/export commands. Writes outside the managed artifacts workspace require approval.

## Tasks And Reminders

Ask BitBuddy to remember a task or reminder, such as "remind me to call the dentist at 4pm". Tasks are stored locally, can be managed from the Tasks page, and can trigger desktop notifications when reminders come due.

## MCP And Desktop Control

BitBuddy can discover tools from local stdio MCP servers. MCP discovery is opt-in from Settings. Built-in web search is separate and remains enabled by default when web search is enabled.

Linux desktop control is self-contained and managed under `~/.bitbuddy/tools/bin` only when you install it explicitly from Settings or the CLI.

CLI install/configure/repair commands:

```bash
bitbuddy mcp add-computer-use-linux
bitbuddy mcp setup-computer-use-linux
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
