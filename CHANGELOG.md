# Changelog

All notable changes to this project will be documented in this file.

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
