# Changelog

## v0.2.0

- Default the OpenAI provider to `gpt-5.5` and the Anthropic provider to `claude-opus-4-8` (was `gpt-4.1` / `claude-sonnet-4-6`).
- Settings model picker now surfaces recommended models per provider even before a live fetch; Claude Fable 5 is listed but disabled (not yet supported).
- Sidebar provider switcher now lets you pick any of the active provider's models, not just the saved one.
- Per-provider reasoning level (off / low / medium / high), set from a chat-bar dropdown shown only for cloud providers (OpenAI, Codex, Claude) — applied via OpenAI/Codex `reasoning.effort` and Anthropic `output_config.effort`.
