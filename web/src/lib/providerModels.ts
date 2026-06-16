import type { SelectOption } from '$lib/components/ui/SelectMenu.svelte';

type ModelCatalogEntry = { value: string; description?: string; disabled?: boolean };

// Recommended models surfaced even before a live /v1/models fetch. Live-discovered
// models are merged in on top of these. `disabled` entries appear in the picker but
// can't be selected yet (e.g. Fable 5 needs always-on thinking / refusal-fallback /
// 30-day-retention handling BitBuddy doesn't implement).
export const PROVIDER_MODEL_CATALOG: Record<string, ModelCatalogEntry[]> = {
	openai: [
		{ value: 'gpt-5.5', description: 'Latest flagship' },
		{ value: 'gpt-5.4' },
		{ value: 'gpt-5.4-mini', description: 'Lower latency and cost' }
	],
	codex: [
		{ value: 'gpt-5.5', description: 'ChatGPT Codex default' },
		{ value: 'gpt-5.4' },
		{ value: 'gpt-5.4-mini', description: 'Lower latency' }
	],
	anthropic: [
		{ value: 'claude-opus-4-8', description: 'Most capable Opus' },
		{ value: 'claude-sonnet-4-6', description: 'Balanced speed and intelligence' },
		{ value: 'claude-haiku-4-5', description: 'Fastest, most cost-effective' },
		{ value: 'claude-fable-5', description: 'Not yet supported in BitBuddy', disabled: true }
	]
};

// Build a model dropdown for a provider: the current selection first, then any
// live-discovered models, then catalog entries not already present. Catalog
// `disabled` flags win (except for the active selection, which must stay shown).
export function buildProviderModelOptions(
	type: string,
	liveModels: string[],
	currentModel: string
): SelectOption[] {
	const current = (currentModel || '').trim();
	const catalog = PROVIDER_MODEL_CATALOG[type] ?? [];
	const meta = new Map(catalog.map((entry) => [entry.value, entry]));

	const values: string[] = [];
	const push = (value: string) => {
		if (value && !values.includes(value)) values.push(value);
	};
	if (current) push(current);
	for (const model of liveModels) push(model);
	for (const entry of catalog) push(entry.value);

	return values.map((value) => {
		const entry = meta.get(value);
		return {
			value,
			label: value,
			description: entry?.description,
			// Never disable the active selection, or the picker can't render it as chosen.
			disabled: value !== current && Boolean(entry?.disabled)
		};
	});
}

// Providers that expose a reasoning-effort knob. Local backends (ollama,
// llama.cpp) don't, so the chat-bar control stays hidden for them.
export const PROVIDER_SUPPORTS_EFFORT = new Set(['openai', 'codex', 'anthropic']);

export const REASONING_EFFORT_OPTIONS: SelectOption[] = [
	{ value: 'off', label: 'Off', description: 'No extended reasoning' },
	{ value: 'low', label: 'Low', description: 'Quick, shallow reasoning' },
	{ value: 'medium', label: 'Medium', description: 'Balanced reasoning' },
	{ value: 'high', label: 'High', description: 'Deepest reasoning' }
];
