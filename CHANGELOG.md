# Changelog

All notable changes to this project will be documented in this file.

## [v0.3.0] - 2026-06-28

### Added
- Add `bitbuddy version`, `bitbuddy --version`, and `bitbuddy -V` output backed by the package version.
- Add a user-facing tasks & reminders system. Ask BitBuddy to remember a task ("remind me to call the dentist at 4pm", "add a task to review the PR Friday") and it stores it; a background scheduler pops a toast notification when a reminder comes due (clicking it opens the Tasks page). Times you give in plain language are interpreted in your configured timezone. Tasks are managed via new `create_task` / `list_tasks` / `update_task` / `complete_task` / `delete_task` tools, a `/tasks` HTTP API, and a Tasks page in the dashboard.
- Add Project Specs: project-scoped Markdown specs with draft, active, and archived states; the Projects dashboard can create, edit, and archive specs, and active specs are injected into project context.
- Add a guided Linux desktop-control setup flow with `bitbuddy mcp setup-computer-use-linux`, the `enable_desktop_control` tool, and an HTTP enable endpoint that reports capabilities and remediation steps.

### Changed
- `bitbuddy serve` now hosts the built web UI on its own port (same origin as the API), making it the single local hub all first-party clients connect to. The static SPA is auto-built (and rebuilt when stale) on startup, degrading to API-only with a warning if no build tooling is present.
- `bitbuddy dashboard` now just ensures the backend is running (auto-starting `bitbuddy serve` if needed) and opens the browser at it, instead of spawning a separate Vite dev server. `bitbuddy web` remains for development with hot-reload.
- `bitbuddy update` now rebuilds the static web UI (via pnpm/npm) so the freshly pulled version is what `serve` hosts.
- Polish the chat UI with bounded thinking-stream scrolling, a more compact steering card, and clearer permission request wording.

### Fixed
- Fix the web UI reporting "backend not running" when opened directly at `http://127.0.0.1:8787` instead of via `bitbuddy dashboard`: the backend now hands the page its API token when serving `index.html` to a loopback client, so a direct local visit authenticates without the `?bitbuddy_token` query param. LAN clients (`--allow-lan`) are unaffected and still use the tokenized dashboard URL.
- Reduce repetitive autonomous questions by rejecting project implementation questions BitBuddy should answer through self-research and suppressing near-duplicate question topics.
- Fix Gmail (and Codex) OAuth sign-in returning a 404 after the same-port web UI move: the browser's redirect to `/email/gmail/callback` is a navigation, so the SPA fallback was serving `index.html` (which has no such client route, hence the 404) before the callback handler ran. Public API paths are now exempt from the SPA fallback so OAuth callbacks reach their handlers.

## [v0.2.1] - 2026-06-15

### Changed
- Change `bitbuddy update` to follow the `stable` release branch by default instead of `main`; use `--branch main` for development builds.

## [v0.2.0] - 2026-06-15

### Added
- Add per-provider reasoning effort (off / low / medium / high), set from a chat-bar dropdown shown only for cloud providers (OpenAI, Codex, Claude) and applied via OpenAI/Codex `reasoning.effort` and Anthropic `output_config.effort`.
- Add curated recommended model catalogs for Settings and the sidebar model picker, including Codex defaults and a disabled Claude Fable 5 entry until BitBuddy supports its requirements.
- Add cloud provider context usage estimates so Codex, OpenAI, and Anthropic prompts show local used-token estimates instead of `unknown`.

### Changed
- Default the OpenAI provider to `gpt-5.5` and the Anthropic provider to `claude-opus-4-8` (was `gpt-4.1` / `claude-sonnet-4-6`).
- Let the sidebar provider switcher pick from live model lists for the selected provider instead of only showing the saved model.
- Size the chat-bar reasoning-level control to its label on desktop while using compact tablet and mobile sizing.

### Fixed
- Keep sidebar provider/model dropdowns open when choosing portaled options, avoid first-open layout jumps, and stabilize dropdown positioning before rendering the option list.
- Preserve cloud provider model options while live model fetches are in flight so the sidebar select text does not churn while opening.
