import type { SelectOption } from '$lib/components/ui/SelectMenu.svelte';

type ModelCatalogEntry = { value: string; description?: string; disabled?: boolean; availableUntil?: string };

// Recommended models surfaced even before a live /v1/models fetch. Live-discovered
// models are merged in on top of these. A live model listing is the source of truth
// for whether a limited preview is available to this API account right now.
export const PROVIDER_MODEL_CATALOG: Record<string, ModelCatalogEntry[]> = {
	openai: [
		{ value: 'gpt-5.6-sol', description: 'Latest flagship' },
		{ value: 'gpt-5.6-terra', description: 'Balanced intelligence and cost' },
		{ value: 'gpt-5.6-luna', description: 'Fast, efficient high-volume model' },
		{ value: 'gpt-5.5', description: 'Previous-generation frontier model' },
		{ value: 'gpt-5.4' },
		{ value: 'gpt-5.4-mini', description: 'Lower latency and cost' }
	],
	codex: [
		{ value: 'gpt-5.6-sol', description: 'ChatGPT Codex default' },
		{ value: 'gpt-5.6-terra', description: 'Everyday Codex workhorse' },
		{ value: 'gpt-5.6-luna', description: 'Fast, efficient repeatable work' },
		{ value: 'gpt-5.5', description: 'Previous-generation frontier model' },
		{ value: 'gpt-5.4' },
		{ value: 'gpt-5.4-mini', description: 'Lower latency' },
		{ value: 'gpt-5.3-codex-spark', description: 'Pro text-only research preview' }
	],
	anthropic: [
		{ value: 'claude-opus-4-8', description: 'Most capable Opus' },
		{ value: 'claude-sonnet-4-6', description: 'Balanced speed and intelligence' },
		{ value: 'claude-haiku-4-5', description: 'Fastest, most cost-effective' },
		{ value: 'claude-fable-5', description: 'Limited preview through Jul 19, 2026 (unless Anthropic extends it)', availableUntil: '2026-07-19' }
	],
	'z.ai': [
		{ value: 'glm-5.2', description: 'Strongest coding model, 1M context' },
		{ value: 'glm-5.1' },
		{ value: 'glm-5-turbo', description: 'Fast GLM-5 family model' },
		{ value: 'glm-5v-turbo', description: 'Vision-capable GLM model' },
		{ value: 'glm-4.7', description: 'Routine coding and chat' },
		{ value: 'glm-4.5-air', description: 'Lower latency coding model' }
	],
	'z.ai-coding': [
		{ value: 'glm-5.2', description: 'Best Coding Plan model' },
		{ value: 'glm-5.1' },
		{ value: 'glm-5-turbo', description: 'Fast GLM-5 family model' },
		{ value: 'glm-5v-turbo', description: 'Vision-capable coding model' },
		{ value: 'glm-4.7', description: 'Recommended for routine tasks' },
		{ value: 'glm-4.5-air', description: 'Lower latency coding model' }
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
		const listedLive = liveModels.includes(value);
		const previewExpired = Boolean(entry?.availableUntil && new Date(`${entry.availableUntil}T23:59:59Z`).getTime() < Date.now());
		const availabilityDescription = entry?.availableUntil
			? listedLive
				? 'Limited preview currently available to this API account'
				: previewExpired
					? `Limited preview ended ${formatAvailabilityDate(entry.availableUntil)}; check Anthropic for an extension`
					: entry.description
			: entry?.description;
		return {
			value,
			label: value,
			description: availabilityDescription,
			// Never disable the active selection, or the picker can't render it as chosen.
			disabled: value !== current && (Boolean(entry?.disabled) || (previewExpired && !listedLive))
		};
	});
}

function formatAvailabilityDate(value: string): string {
	const date = new Date(`${value}T00:00:00Z`);
	return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
}

// Providers that expose a reasoning-effort knob. Local backends (ollama,
// llama.cpp) don't, so the chat-bar control stays hidden for them.
export const PROVIDER_SUPPORTS_EFFORT = new Set(['openai', 'codex', 'anthropic', 'z.ai', 'z.ai-coding']);

const BASE_REASONING_EFFORT_OPTIONS: SelectOption[] = [
	{ value: 'off', label: 'Off', description: 'No extended reasoning' },
	{ value: 'low', label: 'Low', description: 'Quick, shallow reasoning' },
	{ value: 'medium', label: 'Medium', description: 'Balanced reasoning' },
	{ value: 'high', label: 'High', description: 'Deep reasoning' }
];

const OPENAI_REASONING_OPTIONS: SelectOption[] = [
	...BASE_REASONING_EFFORT_OPTIONS,
	{ value: 'xhigh', label: 'XHigh', description: 'Extra-high reasoning where supported' }
];

const OPENAI_56_REASONING_OPTIONS: SelectOption[] = [
	...OPENAI_REASONING_OPTIONS,
	{ value: 'max', label: 'Max', description: 'Maximum GPT-5.6 reasoning' }
];

const ANTHROPIC_MAX_OPTIONS: SelectOption[] = [
	...BASE_REASONING_EFFORT_OPTIONS,
	{ value: 'max', label: 'Max', description: 'Maximum Claude effort where supported' }
];

const ANTHROPIC_XHIGH_OPTIONS: SelectOption[] = [
	...BASE_REASONING_EFFORT_OPTIONS,
	{ value: 'xhigh', label: 'XHigh', description: 'Extended long-horizon effort' },
	{ value: 'max', label: 'Max', description: 'Maximum Claude effort' }
];

const REASONING_OPTION_META = new Map(
	[
		...BASE_REASONING_EFFORT_OPTIONS,
		{ value: 'xhigh', label: 'XHigh', description: 'Extra-high reasoning where supported' },
		{ value: 'max', label: 'Max', description: 'Maximum reasoning where supported' }
	].map((option) => [option.value, option])
);

const OPTIONS_BY_PROVIDER: Record<string, SelectOption[]> = {
	openai: OPENAI_REASONING_OPTIONS,
	codex: OPENAI_REASONING_OPTIONS,
	'z.ai': [
		BASE_REASONING_EFFORT_OPTIONS[0],
		{ value: 'high', label: 'High', description: 'Z.ai default enhanced reasoning' },
		{ value: 'max', label: 'Max', description: 'Maximum GLM-5.2 reasoning' }
	],
	'z.ai-coding': [
		BASE_REASONING_EFFORT_OPTIONS[0],
		{ value: 'high', label: 'High', description: 'Recommended Coding Plan reasoning' },
		{ value: 'max', label: 'Max', description: 'Deepest Coding Plan reasoning' }
	]
};

export function providerSupportsReasoningEffort(provider: string, model = ''): boolean {
	if (!PROVIDER_SUPPORTS_EFFORT.has(provider)) return false;
	if (provider !== 'anthropic') return true;
	if (!model) return true;
	return anthropicModelSupportsEffort(model);
}

export function reasoningEffortOptionsForProvider(provider: string, model = ''): SelectOption[] {
	if ((provider === 'openai' || provider === 'codex') && model.toLowerCase().startsWith('gpt-5.6')) {
		return OPENAI_56_REASONING_OPTIONS;
	}
	if (provider === 'anthropic') {
		if (anthropicModelRequiresThinking(model)) return ANTHROPIC_XHIGH_OPTIONS.filter((option) => option.value !== 'off');
		if (anthropicModelSupportsXHigh(model)) return ANTHROPIC_XHIGH_OPTIONS;
		if (anthropicModelSupportsMax(model)) return ANTHROPIC_MAX_OPTIONS;
		return BASE_REASONING_EFFORT_OPTIONS;
	}
	return OPTIONS_BY_PROVIDER[provider] ?? BASE_REASONING_EFFORT_OPTIONS;
}

export function reasoningEffortOptionsFromValues(values: string[], provider = ''): SelectOption[] {
	const options = values
		.map((value) => {
			const meta = REASONING_OPTION_META.get(value);
			if (meta) return meta;
			return { value, label: value.toUpperCase(), description: '' };
		})
		.filter((option, index, all) => all.findIndex((candidate) => candidate.value === option.value) === index);
	if (provider === 'z.ai' || provider === 'z.ai-coding') {
		return options.map((option) => {
			if (option.value === 'high') return { ...option, description: 'Z.ai default enhanced reasoning' };
			if (option.value === 'max') return { ...option, description: 'Maximum GLM reasoning' };
			return option;
		});
	}
	return options;
}

export function clampReasoningEffortForProvider(provider: string, effort: string, model = ''): string {
	const options = reasoningEffortOptionsForProvider(provider, model);
	return options.some((option) => option.value === effort) ? effort : 'high';
}

function anthropicModelSupportsEffort(model: string): boolean {
	const name = model.toLowerCase();
	return (
		name.includes('fable-5') ||
		name.includes('mythos-5') ||
		name.includes('opus-4-8') ||
		name.includes('opus-4-7') ||
		name.includes('opus-4-6') ||
		name.includes('sonnet-5') ||
		name.includes('sonnet-4-6') ||
		name.includes('opus-4-5')
	);
}

export function anthropicModelRequiresThinking(model: string): boolean {
	return model.toLowerCase().includes('fable-5');
}

function anthropicModelSupportsMax(model: string): boolean {
	const name = model.toLowerCase();
	return (
		name.includes('fable-5') ||
		name.includes('mythos-5') ||
		name.includes('opus-4-8') ||
		name.includes('opus-4-7') ||
		name.includes('opus-4-6') ||
		name.includes('sonnet-5') ||
		name.includes('sonnet-4-6')
	);
}

function anthropicModelSupportsXHigh(model: string): boolean {
	const name = model.toLowerCase();
	return (
		name.includes('fable-5') ||
		name.includes('mythos-5') ||
		name.includes('opus-4-8') ||
		name.includes('opus-4-7') ||
		name.includes('sonnet-5')
	);
}
