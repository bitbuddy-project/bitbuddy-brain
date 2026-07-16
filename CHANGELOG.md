# Changelog

All notable changes to this project will be documented in this file.

## [v0.4.1] - Unreleased

### Added
- Rebuild the Coding workspace as a focused conversation-style work surface: choose a saved flow and project from the header, submit the task from the familiar composer, and follow each stage, tool call, diff, report, and live reasoning in one timeline.
- Add compact menus for switching or editing coding flows and reopening or deleting recent coding runs without a persistent configuration sidebar.
- Add live stage-thinking events and persist each reasoning round beside the tool calls it led to, so active work remains visible and completed runs retain the useful trace.
- Add trusted coding flows and a per-run trust option to automatically approve tool permission requests when the user explicitly opts in.
- Add the ability to change a registered project's directories while preserving its project identity, memory, specs, validation recipes, and run history.
- Add deletion of completed coding runs from the UI and API; active runs remain protected until stopped.

### Changed
- Make the default Plan stage run without an approval gate, move flow editing into an on-demand overlay, and keep stage configuration available without taking over the workspace.
- Run all saved project validation recipes automatically in a Test stage when that stage has no recipes selected, and permit Review stages to run stored validation checks while otherwise remaining read-only.
- Increase the coding stage tool-round limit and ask the model for a final synthesis with tools disabled when that limit is reached.
- Strengthen stage instructions and file-tool guidance so plans and reviews stay within their read-only capabilities and edits favor targeted patches over full-file rewrites.
- Polish Coding's responsive message surface, status treatment, composer options, and diff rendering to match the rest of Chat.

## [v0.4.0] - 2026-07-14

### Added
- Add a full-width Coding workspace with reusable Plan/Build/Review/Test flows, independent provider and model selection per stage, approval gates, project validation, background runs, and one bounded repair pass.
- Add a shared structured-question interaction for Chat and Coding so OpenAI, Anthropic, and GLM models can pause a live run, offer focused choices plus a custom response, and resume with the user's answer.
- Add GPT-5.6 Sol, Terra, and Luna support to the OpenAI API and Codex model catalogs, including GPT-5.6 `max` reasoning effort and 1.05M-token OpenAI context metadata.
- Add `bitbuddy restart` to restart an active user systemd service or fall back to restarting/starting the detached backend process; setup now uses the same restart path after configuration changes.
- Add coding work-loop tracking with inspect, plan, edit, verify, and summarize phases, plus a `/coding/runs` API for recent coding-run telemetry.
- Add coding eval tasks and scoring APIs for comparing recorded coding runs against expected inspect/edit/verify/validation behavior.
- Add project validation recipes for canonical test/lint/typecheck/build/smoke commands. Recipes are stored in project memory, exposed through tools and HTTP APIs, suggested from project files, and runnable through the chat permission flow.
- Add Z.ai API and Z.ai Coding Plan providers with GLM model catalogs, Chat Completions streaming, native tool-call support, reasoning effort, API-key storage, and context-window metadata.
- Add provider capability profiles so the chat UI can show reasoning levels, native-tool support, vision support, streaming protocol, and context metadata from backend truth instead of hardcoded UI guesses.
- Add Claude Fable 5 preview support with required adaptive thinking and a Jul 19 availability notice that is superseded when the connected Anthropic account still lists the model.
- Render HTML email alternatives in a sandboxed preview instead of flattening newsletter markup into raw CSS text.
- Give BitBuddy private context for the time since the user's last chat message, with discretion to make a warm acknowledgment only after a substantial absence.

### Changed
- Default new OpenAI API and Codex providers to `gpt-5.6-sol` (was `gpt-5.5`).
- Compact older provider conversation turns against the active model's context window while keeping complete stored chat history and recent turns unchanged.
- Make `bitbuddy update` automatically stash and restore local changes by default, smoke-check the updated CLI, and run Doctor after reinstalling and rebuilding.
- Remove the standalone Tasks dashboard page while retaining task/reminder tools, the `/tasks` API, local storage, and desktop notifications; reminder notifications now return to Chat.
- Polish the chat UI with bounded thinking-stream scrolling, a more compact steering card, and clearer permission request wording.
- Clean up Settings provider setup so configured providers read as a simple list with clearer active/editing/unsaved states and less nested border noise.

### Fixed
- Fix HTML-only Gmail and IMAP messages showing stylesheet text instead of readable content.
- Keep provider-specific reasoning choices and required thinking behavior correct for GPT-5.6, Claude Fable 5, Codex, and GLM models.

## [v0.3.0] - 2026-06-28

### Release notes
- Add bitbuddy version, `bitbuddy --version`, and `bitbuddy -V` output backed by the package version.
- Add Tasks & Reminders with chat tools, `/tasks` API, dashboard Tasks page, timezone-aware reminder parsing, and due reminder notifications.
- Add Project Specs for project-scoped Markdown specs with draft, active, and archived states; active specs are included in project context.
- Add guided Linux desktop-control setup via CLI, tool, and HTTP enable flow with capability/remediation reporting.
- Serve the built dashboard from `bitbuddy serve` on the same origin as the API; `bitbuddy dashboard` now ensures the backend is running and opens it.
- Rebuild the static web UI during `bitbuddy update`.
- Fix direct local visits to `http://127.0.0.1:8787` by injecting loopback auth data into served `index.html`.
- Reduce repetitive autonomous questions and fix OAuth callback routes being swallowed by the SPA fallback.

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
