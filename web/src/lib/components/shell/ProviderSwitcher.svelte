<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { chatSession, refreshContextUsage } from '$lib/stores/chat.svelte';
	import {
		getConfig,
		getProviderHealth,
		getProviderModels,
		updateModelRuntimeConfig,
		type ProviderEntry,
		type ProviderHealth
	} from '$lib/api/bitbuddy';
	import SelectMenu, { type SelectOption } from '$lib/components/ui/SelectMenu.svelte';
	import { buildProviderModelOptions } from '$lib/providerModels';
	import CaretUpIcon from 'phosphor-svelte/lib/CaretUpIcon';
	import CaretRightIcon from 'phosphor-svelte/lib/CaretRightIcon';
	import CpuIcon from 'phosphor-svelte/lib/CpuIcon';

	let { collapsed = false, onNavigate = () => {} } = $props<{
		collapsed?: boolean;
		onNavigate?: () => void;
	}>();

	let provider = $state<ProviderEntry>({ type: 'none', url: '', model: '' });
	let providers = $state<ProviderEntry[]>([]);
	let activeProvider = $state('none');
	let draftProvider = $state('none');
	let draftModel = $state('');
	let scanInterval = $state(60);
	let health = $state<ProviderHealth | null>(null);
	let liveModels = $state<string[]>([]);
	let modelLoadingModels = $state(false);
	let modelLoadKey = $state('');

	let open = $state(false);
	let loadingConfig = $state(false);
	let saving = $state(false);
	let error = $state('');

	let rootEl: HTMLDivElement | undefined;

	let active = $derived(provider.type !== 'none');
	let providerOptions = $derived.by<SelectOption[]>(() =>
		providers.map((entry) => ({
			value: providerKey(entry),
			label: `${providerLabel(entry.type)}${entry.model ? ` · ${entry.model}` : ''}`,
			description: entry.url
		}))
	);

	let selectedEntry = $derived(providers.find((entry) => providerKey(entry) === draftProvider) ?? null);
	let modelOptions = $derived.by<SelectOption[]>(() =>
		selectedEntry ? buildProviderModelOptions(selectedEntry.type, liveModels, draftModel || selectedEntry.model) : []
	);

	let typeLabel = $derived(providerLabel(provider.type));

	let label = $derived(active ? 'Model Provider' : 'No Model');

	let subtitle = $derived(
		active ? `${typeLabel} · ${provider.model || 'no model'}` : 'tap to set up'
	);
	let tone = $derived.by(() => {
		if (!active) return 'quiet';
		if (health?.ok) return 'ready';
		if (health && !health.ok) return 'offline';
		return 'pending';
	});

	let title = $derived(
		active
			? `${typeLabel} · ${provider.model || 'no model'}${health ? ` — ${health.ok ? 'connected' : 'unreachable'}` : ''}`
			: 'No model provider configured'
	);

	async function loadConfig() {
		if (!chatSession.serverAvailable) return;
		loadingConfig = true;
		try {
			const config = await getConfig();
			provider = { ...config.provider };
			providers = (config.providers?.length ? config.providers : config.provider.type !== 'none' ? [config.provider] : []).map((entry) => ({ ...entry }));
			activeProvider = config.active_provider ?? providerKey(provider);
			draftProvider = activeProvider;
			draftModel = modelForKey(activeProvider);
			liveModels = [];
			modelLoadingModels = false;
			modelLoadKey = '';
			scanInterval = config.runtime?.project_scan_interval_seconds ?? scanInterval;
		} catch {
			// Keep the last known display; the sidebar owns server availability.
		} finally {
			loadingConfig = false;
		}
	}

	async function refreshHealth() {
		if (!chatSession.serverAvailable || provider.type === 'none') {
			health = null;
			return;
		}
		try {
			health = await getProviderHealth();
		} catch {
			// Leave the previous health reading in place.
		}
	}

	async function toggleOpen() {
		// In the collapsed rail an inline popover would be clipped by the
		// sidebar's overflow, so jump straight to the full settings page.
		if (collapsed) {
			onNavigate();
			void goto('/settings');
			return;
		}
		if (open) {
			open = false;
			return;
		}

		error = '';
		await loadConfig();
		draftProvider = activeProvider;
		draftModel = modelForKey(activeProvider);
		open = true;
		void loadModelsForProvider(providers.find((entry) => providerKey(entry) === activeProvider) ?? null);
	}

	function modelForKey(key: string) {
		return providers.find((entry) => providerKey(entry) === key)?.model ?? '';
	}

	function selectProvider(value: string) {
		draftProvider = value;
		draftModel = modelForKey(value);
		void loadModelsForProvider(providers.find((entry) => providerKey(entry) === value) ?? null);
	}

	function selectModel(value: string) {
		draftModel = value;
	}

	function modelFetchKey(entry: ProviderEntry | null) {
		if (!entry) return '';
		return `${providerKey(entry)}|${entry.type}|${entry.url}|${entry.has_api_key ? 'saved-key' : 'no-key'}`;
	}

	async function loadModelsForProvider(entry: ProviderEntry | null) {
		const key = modelFetchKey(entry);
		modelLoadKey = key;
		if (!entry || !chatSession.serverAvailable) {
			modelLoadingModels = false;
			return;
		}

		modelLoadingModels = true;
		try {
			const models = await getProviderModels(entry);
			if (modelLoadKey === key) liveModels = models;
		} catch {
			if (modelLoadKey === key) liveModels = [];
		} finally {
			if (modelLoadKey === key) modelLoadingModels = false;
		}
	}

	async function save() {
		error = '';
		const selected = providers.find((entry) => providerKey(entry) === draftProvider);
		if (!selected) {
			error = 'Choose a configured provider.';
			return;
		}
		// Apply the chosen model onto the active provider; preserve every other field
		// (api key ref, reasoning effort, …) via spread.
		const nextProviders = providers.map((entry) =>
			providerKey(entry) === draftProvider ? { ...entry, model: draftModel || entry.model } : entry
		);
		const selectedUpdated = nextProviders.find((entry) => providerKey(entry) === draftProvider) ?? selected;
		const next = {
			provider: selectedUpdated,
			providers: nextProviders,
			active_provider: draftProvider,
			project_scan_interval_seconds: scanInterval
		};
		saving = true;
		try {
			const config = await updateModelRuntimeConfig(next);
			provider = { ...config.provider };
			providers = (config.providers?.length ? config.providers : [config.provider]).map((entry) => ({ ...entry }));
			activeProvider = config.active_provider ?? providerKey(provider);
			draftProvider = activeProvider;
			liveModels = [];
			modelLoadingModels = false;
			modelLoadKey = '';
			open = false;
			void refreshContextUsage('', { providerOnly: true });
			void refreshHealth();
		} catch (caught) {
			error = caught instanceof Error ? caught.message : 'Could not switch provider.';
		} finally {
			saving = false;
		}
	}

	function providerKey(entry: ProviderEntry) {
		return entry.key || entry.type;
	}

	function providerLabel(type: string) {
		if (type === 'ollama') return 'Ollama';
		if (type === 'llama.cpp') return 'llama.cpp';
		if (type === 'openai') return 'OpenAI API';
		if (type === 'codex') return 'Codex';
		if (type === 'anthropic') return 'Anthropic';
		return 'Provider';
	}

	function openSettings() {
		open = false;
		onNavigate();
		void goto('/settings');
	}

	function onPointerDown(event: PointerEvent) {
		if (!open) return;
		if (rootEl && !rootEl.contains(event.target as Node)) open = false;
	}

	function onKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') open = false;
	}

	// Load (and reload) provider config whenever the backend becomes reachable.
	// Previously this ran once on mount; if the server wasn't up yet the card got
	// stuck on "tap to set up" until the user clicked. Driving it off
	// serverAvailable means the live provider + model appear on their own — and
	// recover after a reconnect — without any interaction.
	$effect(() => {
		if (!chatSession.serverAvailable) return;
		void loadConfig().then(() => refreshHealth());
	});

	onMount(() => {
		const timer = setInterval(() => void refreshHealth(), 15000);
		window.addEventListener('pointerdown', onPointerDown);
		window.addEventListener('keydown', onKeydown);

		return () => {
			clearInterval(timer);
			window.removeEventListener('pointerdown', onPointerDown);
			window.removeEventListener('keydown', onKeydown);
		};
	});
</script>

<div class="switcher" class:collapsed bind:this={rootEl}>
	{#if open}
		<div class="popover" role="dialog" aria-label="Switch model provider">
			<div class="pop-field">
				<span class="field-label">Provider</span>
				<SelectMenu
					value={draftProvider}
					options={providerOptions}
					placeholder="Choose provider"
					disabled={loadingConfig || saving || providerOptions.length === 0}
					ariaLabel="Provider type"
					onChange={selectProvider}
				/>
				{#if providerOptions.length === 0}
					<small class="field-note">Add providers in full settings first.</small>
				{/if}
			</div>

			{#if selectedEntry}
				<div class="pop-field">
					<span class="field-label">Model</span>
					<SelectMenu
						value={draftModel}
						options={modelOptions}
						placeholder="Choose model"
						disabled={loadingConfig || saving || modelOptions.length === 0}
						ariaLabel="Model"
						onChange={selectModel}
					/>
				</div>
			{/if}

			{#if error}
				<p class="pop-error">{error}</p>
			{/if}

			<div class="pop-actions">
				<button type="button" class="save" onclick={save} disabled={saving}>
					{saving ? 'Saving…' : 'Save'}
				</button>
				<button type="button" class="link" onclick={openSettings}>
					Full settings <CaretRightIcon size={13} weight="bold" />
				</button>
			</div>
		</div>
	{/if}

	<button
		type="button"
		class="card"
		onclick={toggleOpen}
		aria-haspopup="dialog"
		aria-expanded={open}
		title={collapsed ? title : undefined}
	>
		<span class="card-mark">
			<CpuIcon size={22} weight="duotone" />
			<span class={`dot ${tone}`}></span>
		</span>
		<span class="card-copy">
			<strong>{label}</strong>
			<small>{subtitle}</small>
		</span>
		<span class="card-caret" aria-hidden="true"><CaretUpIcon size={18} weight="bold" /></span>
	</button>
</div>

<style>
	.switcher {
		position: relative;
	}

	.card {
		width: 100%;
		min-height: 3.2rem;
		padding: 0.58rem 0.64rem;
		display: flex;
		align-items: center;
		gap: 0.72rem;
		border: 1px solid color-mix(in srgb, var(--bg-soft) 54%, var(--border));
		border-radius: 0.92rem;
		background:
			linear-gradient(135deg, rgba(255, 255, 255, 0.07), transparent 58%),
			color-mix(in srgb, var(--panel-raised) 68%, transparent);
		color: var(--text-muted);
		text-align: left;
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
		transition:
			border-color 140ms ease,
			background 140ms ease,
			color 140ms ease;
	}

	.card:hover {
		border-color: color-mix(in srgb, var(--accent) 48%, var(--border));
		background:
			linear-gradient(135deg, rgba(255, 255, 255, 0.09), transparent 58%),
			color-mix(in srgb, var(--panel-raised) 82%, transparent);
		color: var(--text);
	}

	.card-mark {
		position: relative;
		width: 2rem;
		height: 2rem;
		flex: 0 0 auto;
		display: grid;
		place-items: center;
		border-radius: 0.72rem;
		background: color-mix(in srgb, var(--accent-soft) 72%, var(--surface-card));
		color: var(--accent-strong);
	}

	.dot {
		position: absolute;
		right: -2px;
		bottom: -2px;
		width: 0.6rem;
		height: 0.6rem;
		border-radius: 999px;
		border: 2px solid var(--panel);
		background: var(--success);
	}

	.dot.ready {
		background: var(--success);
		box-shadow: 0 0 10px color-mix(in srgb, var(--success) 60%, transparent);
	}

	.dot.pending {
		background: var(--accent);
	}

	.dot.offline {
		background: var(--danger);
	}

	.dot.quiet {
		background: var(--text-soft);
	}

	.card-copy {
		flex: 1;
		min-width: 0;
		display: grid;
		gap: 0.05rem;
	}

	.card-caret {
		width: 1.85rem;
		height: 1.85rem;
		flex: 0 0 auto;
		display: grid;
		place-items: center;
		border-radius: 0.64rem;
		background: color-mix(in srgb, var(--accent-soft) 54%, transparent);
		color: var(--accent-strong);
		transition: transform 140ms ease, background 140ms ease, color 140ms ease;
	}

	.card[aria-expanded='true'] .card-caret {
		transform: rotate(180deg);
	}

	.card-copy strong {
		display: block;
		font-weight: 700;
		letter-spacing: -0.01em;
		color: var(--text);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.card-copy small {
		display: block;
		color: var(--text-soft);
		font-size: 0.68rem;
		font-weight: 650;
		letter-spacing: 0.02em;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.popover {
		position: absolute;
		left: 0;
		right: 0;
		bottom: calc(100% + 0.5rem);
		z-index: 30;
		display: grid;
		gap: 0.78rem;
		padding: 0.9rem;
		border: 1px solid color-mix(in srgb, var(--bg-soft) 54%, var(--border-strong));
		border-radius: 1rem;
		background:
			linear-gradient(135deg, rgba(255, 255, 255, 0.075), transparent 68%),
			color-mix(in srgb, var(--panel-raised) 92%, #020713);
		box-shadow: 0 18px 44px rgba(0, 0, 0, 0.42), inset 0 1px 0 rgba(255, 255, 255, 0.06);
		backdrop-filter: blur(20px) saturate(1.2);
	}

	.pop-field {
		display: grid;
		gap: 0.4rem;
	}

	.field-label {
		color: var(--text-soft);
		font-size: 0.66rem;
		font-weight: 800;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.field-note {
		color: var(--text-soft);
		font-size: 0.7rem;
		line-height: 1.35;
	}

	.pop-error {
		color: var(--danger);
		font-size: 0.76rem;
		font-weight: 600;
	}

	.pop-actions {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.5rem;
	}

	.save {
		padding: 0.45rem 1rem;
		border: 1px solid color-mix(in srgb, var(--mode-color) 60%, var(--mode-border));
		border-radius: 0.72rem;
		background: color-mix(in srgb, var(--mode-color) 23%, transparent);
		color: var(--mode-color);
		font-size: 0.82rem;
		font-weight: 700;
	}

	.save:disabled {
		opacity: 0.6;
	}

	.link {
		display: inline-flex;
		align-items: center;
		gap: 0.2rem;
		color: var(--text-soft);
		font-size: 0.78rem;
		font-weight: 650;
	}

	.link:hover {
		color: var(--accent-strong);
	}

	.switcher.collapsed .card {
		width: 3.2rem;
		height: 3.2rem;
		min-height: 3.2rem;
		margin-inline: auto;
		padding: 0;
		justify-content: center;
	}

	.switcher.collapsed .card-copy {
		display: none;
	}

	.switcher.collapsed .card-caret {
		display: none;
	}
</style>
