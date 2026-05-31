<script lang="ts">
	import { onMount } from 'svelte';
	import { setTimePreferences } from '$lib/stores/time.svelte';
	import { theme, type ThemeVariant } from '$lib/stores/theme.svelte';
	import { chatBehavior, type ReplyAnimation } from '$lib/stores/chat-behavior.svelte';
	import {
		configureComputerUseLinux,
		getConfig,
		getMcpStatus,
		getProviderContext,
		getProviderHealth,
		getProviderModels,
		installComputerUseLinux,
		doctorComputerUseLinux,
		updateAutonomyConfig,
		updateDreamingConfig,
		updateMcpConfig,
		updateModelRuntimeConfig,
		updateUserContext,
		type AutonomyConfig,
		type DreamingConfig,
		type McpConfig,
		type McpStatus,
		type ModelRuntimeConfig,
		type ProviderContext,
		type UserContextConfig
	} from '$lib/api/bitbuddy';
	import SunIcon from 'phosphor-svelte/lib/SunIcon';
	import MoonIcon from 'phosphor-svelte/lib/MoonIcon';
	import DesktopIcon from 'phosphor-svelte/lib/DesktopIcon';
	import CaretRightIcon from 'phosphor-svelte/lib/CaretRightIcon';

	const themes: { label: ThemeVariant; icon: any; description: string }[] = [
		{ label: 'Auto', icon: DesktopIcon, description: 'Follow system preference' },
		{ label: 'Light', icon: SunIcon, description: 'Clean and bright' },
		{ label: 'Dark', icon: MoonIcon, description: 'Easy on the eyes' }
	];

	const replyAnimations: { label: ReplyAnimation; description: string }[] = [
		{ label: 'Off', description: 'Show replies immediately' },
		{ label: 'Balanced', description: 'Readable typing pace' },
		{ label: 'Slow', description: 'More visible character-by-character reveal' }
	];

	const providerTypes = [
		{ value: 'none', label: 'None' },
		{ value: 'ollama', label: 'Ollama' },
		{ value: 'llama.cpp', label: 'llama.cpp' }
	];

	let userContext = $state<UserContextConfig>({
		location_label: '',
		timezone: 'UTC',
		locale: 'en-US'
	});
	let contextLoading = $state(true);
	let contextSaving = $state(false);
	let contextError = $state('');
	let contextStatus = $state('');
	let localContextOpen = $state(false);
	let chatBehaviorOpen = $state(false);
	let modelRuntimeOpen = $state(false);
	let mcpOpen = $state(false);
	let autonomyControlsOpen = $state(false);
	let dreamingOpen = $state(false);
	let modelRuntime = $state<ModelRuntimeConfig>({
		provider: {
			type: 'none',
			url: '',
			model: ''
		},
		project_scan_interval_seconds: 60
	});
	let modelSaving = $state(false);
	let modelChecking = $state(false);
	let modelLoadingModels = $state(false);
	let modelError = $state('');
	let modelStatus = $state('');
	let providerModels = $state<string[]>([]);
	let providerContext = $state<ProviderContext | null>(null);
	let mcp = $state<McpConfig>({ enabled: false });
	let mcpStatus = $state<McpStatus | null>(null);
	let mcpSaving = $state(false);
	let mcpWorking = $state(false);
	let mcpError = $state('');
	let mcpMessage = $state('');
	let autonomySaving = $state(false);
	let autonomyError = $state('');
	let autonomyStatus = $state('');
	let autonomy = $state<AutonomyConfig>({
		enabled: true,
		run_after_idle_consolidation: true,
		idle_delay_seconds: 300,
		repeat_idle_cycles: true,
		idle_backoff_multiplier: 1.5,
		idle_max_delay_seconds: 1800,
		max_actions_per_cycle: 1,
		max_pending_questions: 12,
		max_pending_comments: 12,
		max_new_questions_per_cycle: 1,
		max_autonomous_deliveries_per_day: 10,
		web_search: {
			enabled: true,
			provider: 'searxng',
			url: 'http://127.0.0.1:8888',
			startup_command: 'managed',
			max_results: 5
		}
	});
	let dreamingSaving = $state(false);
	let dreamingError = $state('');
	let dreamingStatus = $state('');
	let goodnightTriggers = $state('goodnight, good night');
	let goodmorningTriggers = $state('good morning, morning');
	let dreaming = $state<DreamingConfig>({
		enabled: true,
		bedtime: '23:00',
		wake_time: '08:00',
		goodnight_triggers: ['goodnight', 'good night'],
		goodmorning_triggers: ['good morning', 'morning'],
		idle_before_dream_minutes: 30,
		minimum_dream_window_minutes: 45,
		max_dream_tasks_per_night: 3,
		allow_post_dream_autonomy_rounds: 0,
		soft_delete_memories: true,
		quiet_mode_after_bedtime: true,
		goodnight_immediate_winddown: false,
		stale_intention_days: 14,
		low_priority_stale_intention_days: 7,
		self_note_injection_enabled: false
	});

	onMount(() => {
		void loadUserContext();
	});

	async function loadUserContext() {
		contextLoading = true;
		try {
			const config = await getConfig();
			userContext = config.user_context ?? userContext;
			modelRuntime = {
				provider: config.provider,
				project_scan_interval_seconds: config.runtime?.project_scan_interval_seconds ?? modelRuntime.project_scan_interval_seconds
			};
			if (config.autonomy) {
				autonomy = config.autonomy;
			}
			if (config.dreaming) {
				dreaming = config.dreaming;
				goodnightTriggers = config.dreaming.goodnight_triggers.join(', ');
				goodmorningTriggers = config.dreaming.goodmorning_triggers.join(', ');
			}
			if (config.mcp) {
				mcp = config.mcp;
			}
			await refreshMcpStatus();
			contextError = '';
			modelError = '';
			mcpError = '';
			autonomyError = '';
			dreamingError = '';
		} catch (caught) {
			contextError = caught instanceof Error ? caught.message : 'Could not load local context.';
			modelError = caught instanceof Error ? caught.message : 'Could not load model and runtime settings.';
			autonomyError = caught instanceof Error ? caught.message : 'Could not load autonomy settings.';
			dreamingError = caught instanceof Error ? caught.message : 'Could not load dreaming settings.';
			mcpError = caught instanceof Error ? caught.message : 'Could not load MCP settings.';
		} finally {
			contextLoading = false;
		}
	}

	async function refreshMcpStatus() {
		try {
			mcpStatus = await getMcpStatus();
			mcp = mcpStatus.mcp;
			mcpError = '';
		} catch (caught) {
			mcpError = caught instanceof Error ? caught.message : 'Could not load MCP status.';
		}
	}

	async function saveMcpSettings() {
		mcpSaving = true;
		try {
			const config = await updateMcpConfig(mcp);
			mcp = config.mcp ?? mcp;
			await refreshMcpStatus();
			mcpMessage = mcp.enabled ? 'MCP discovery enabled for external tools.' : 'MCP discovery disabled. Built-in web search remains available.';
			mcpError = '';
		} catch (caught) {
			mcpError = caught instanceof Error ? caught.message : 'Could not save MCP settings.';
			mcpMessage = '';
		} finally {
			mcpSaving = false;
		}
	}

	async function runMcpAction(action: 'install' | 'configure' | 'doctor') {
		mcpWorking = true;
		try {
			if (action === 'install') mcpStatus = await installComputerUseLinux();
			else if (action === 'configure') mcpStatus = await configureComputerUseLinux();
			else mcpStatus = await doctorComputerUseLinux();
			mcp = mcpStatus.mcp;
			mcpMessage = mcpStatus.message ?? 'MCP status updated.';
			mcpError = '';
		} catch (caught) {
			mcpError = caught instanceof Error ? caught.message : 'MCP action failed.';
			mcpMessage = '';
			await refreshMcpStatus();
		} finally {
			mcpWorking = false;
		}
	}

	function triggerList(value: string): string[] {
		const result: string[] = [];
		for (const item of value.split(',')) {
			const clean = item.trim().toLowerCase();
			if (clean && !result.includes(clean)) result.push(clean);
		}
		return result;
	}

	function validTime(value: string): boolean {
		return /^([01]\d|2[0-3]):[0-5]\d$/.test(value);
	}

	async function saveDreamingConfig() {
		if (!validTime(dreaming.bedtime) || !validTime(dreaming.wake_time)) {
			dreamingError = 'Use 24-hour HH:MM times, like 23:00 and 08:00.';
			dreamingStatus = '';
			return;
		}

		const next: DreamingConfig = {
			...dreaming,
			goodnight_triggers: triggerList(goodnightTriggers),
			goodmorning_triggers: triggerList(goodmorningTriggers),
			idle_before_dream_minutes: Math.max(0, Number(dreaming.idle_before_dream_minutes) || 0),
			minimum_dream_window_minutes: Math.max(0, Number(dreaming.minimum_dream_window_minutes) || 0),
			max_dream_tasks_per_night: Math.max(1, Number(dreaming.max_dream_tasks_per_night) || 1),
			allow_post_dream_autonomy_rounds: Math.max(0, Number(dreaming.allow_post_dream_autonomy_rounds) || 0),
			stale_intention_days: Math.max(1, Number(dreaming.stale_intention_days) || 1),
			low_priority_stale_intention_days: Math.max(1, Number(dreaming.low_priority_stale_intention_days) || 1)
		};

		dreamingSaving = true;
		try {
			const config = await updateDreamingConfig(next);
			dreaming = config.dreaming ?? next;
			goodnightTriggers = dreaming.goodnight_triggers.join(', ');
			goodmorningTriggers = dreaming.goodmorning_triggers.join(', ');
			dreamingStatus = 'Dreaming settings saved. The lifecycle controller will use them for new night windows.';
			dreamingError = '';
		} catch (caught) {
			dreamingError = caught instanceof Error ? caught.message : 'Could not save dreaming settings.';
			dreamingStatus = '';
		} finally {
			dreamingSaving = false;
		}
	}

	function useDeviceContext() {
		const resolved = Intl.DateTimeFormat().resolvedOptions();
		userContext.timezone = resolved.timeZone || userContext.timezone || 'UTC';
		userContext.locale = navigator.language || resolved.locale || userContext.locale || 'en-US';
		contextStatus = 'Detected timezone and locale from this device. Add a location label if you want one.';
		contextError = '';
	}

	async function saveUserContext() {
		const next = {
			location_label: userContext.location_label.trim(),
			timezone: userContext.timezone.trim() || 'UTC',
			locale: userContext.locale.trim() || 'en-US'
		};

		try {
			Intl.DateTimeFormat(undefined, { timeZone: next.timezone });
		} catch {
			contextError = 'Use a valid IANA timezone, like America/Chicago or Europe/London.';
			contextStatus = '';
			return;
		}

		contextSaving = true;
		try {
			const config = await updateUserContext(next);
			userContext = config.user_context ?? next;
			setTimePreferences(userContext.timezone, userContext.locale);
			contextStatus = 'Local context saved. BitBuddy will include it in new chat turns and UI timestamps.';
			contextError = '';
		} catch (caught) {
			contextError = caught instanceof Error ? caught.message : 'Could not save local context.';
			contextStatus = '';
		} finally {
			contextSaving = false;
		}
	}

	async function saveModelRuntime() {
		const next: ModelRuntimeConfig = {
			provider: {
				type: modelRuntime.provider.type,
				url: modelRuntime.provider.url.trim(),
				model: modelRuntime.provider.model.trim()
			},
			project_scan_interval_seconds: Math.max(0, Number(modelRuntime.project_scan_interval_seconds) || 0)
		};

		if (next.provider.type !== 'none' && !next.provider.url) {
			modelError = 'Provider URL is required unless provider type is None.';
			modelStatus = '';
			return;
		}

		modelSaving = true;
		try {
			const config = await updateModelRuntimeConfig(next);
			modelRuntime = {
				provider: config.provider,
				project_scan_interval_seconds: config.runtime?.project_scan_interval_seconds ?? next.project_scan_interval_seconds
			};
			providerModels = [];
			providerContext = null;
			modelStatus = 'Model and runtime settings saved. New chat turns will use this provider.';
			modelError = '';
		} catch (caught) {
			modelError = caught instanceof Error ? caught.message : 'Could not save model and runtime settings.';
			modelStatus = '';
		} finally {
			modelSaving = false;
		}
	}

	async function checkProvider() {
		modelChecking = true;
		try {
			const [health, context] = await Promise.all([getProviderHealth(), getProviderContext().catch(() => null)]);
			providerContext = context;
			modelStatus = health.message;
			modelError = health.ok ? '' : health.message;
		} catch (caught) {
			modelError = caught instanceof Error ? caught.message : 'Could not check provider connection.';
			modelStatus = '';
		} finally {
			modelChecking = false;
		}
	}

	async function loadProviderModels() {
		modelLoadingModels = true;
		try {
			providerModels = await getProviderModels();
			modelStatus = providerModels.length ? `Loaded ${providerModels.length} model(s) from provider.` : 'Provider did not report any models.';
			modelError = '';
		} catch (caught) {
			modelError = caught instanceof Error ? caught.message : 'Could not list provider models.';
			modelStatus = '';
		} finally {
			modelLoadingModels = false;
		}
	}

	async function saveAutonomyConfig() {
		const idleDelay = Math.max(0, Number(autonomy.idle_delay_seconds) || 0);
		const next: AutonomyConfig = {
			...autonomy,
			idle_delay_seconds: idleDelay,
			idle_backoff_multiplier: Math.max(1, Number(autonomy.idle_backoff_multiplier) || 1),
			idle_max_delay_seconds: Math.max(idleDelay, Number(autonomy.idle_max_delay_seconds) || idleDelay),
			max_actions_per_cycle: Math.max(1, Number(autonomy.max_actions_per_cycle) || 1),
			max_pending_questions: Math.max(1, Number(autonomy.max_pending_questions) || 1),
			max_pending_comments: Math.max(1, Number(autonomy.max_pending_comments) || 1),
			max_new_questions_per_cycle: Math.max(0, Number(autonomy.max_new_questions_per_cycle) || 0),
			max_autonomous_deliveries_per_day: Math.max(1, Number(autonomy.max_autonomous_deliveries_per_day) || 10),
			web_search: {
				...autonomy.web_search,
				provider: autonomy.web_search.provider.trim() || 'searxng',
				url: autonomy.web_search.url.trim() || 'http://127.0.0.1:8888',
				startup_command: autonomy.web_search.startup_command?.trim() || 'managed',
				max_results: Math.max(1, Math.min(10, Number(autonomy.web_search.max_results) || 5))
			}
		};

		autonomySaving = true;
		try {
			const config = await updateAutonomyConfig(next);
			autonomy = config.autonomy ?? next;
			autonomyStatus = 'Autonomy settings saved. New idle cycles will use these limits and gates.';
			autonomyError = '';
		} catch (caught) {
			autonomyError = caught instanceof Error ? caught.message : 'Could not save autonomy settings.';
			autonomyStatus = '';
		} finally {
			autonomySaving = false;
		}
	}
</script>

<div class="settings-page">
	<header class="settings-header">
		<h1>Settings</h1>
	</header>

	<div class="settings-content">
		<section class="settings-section">
			<h2>Appearance</h2>
			<p class="section-intro">Customize how BitBuddy looks on your device.</p>

			<div class="theme-grid">
				{#each themes as t}
					<button
						class="theme-card"
						class:active={theme.variant === t.label}
						onclick={() => theme.setVariant(t.label)}
					>
						<div class="theme-icon">
							<t.icon size={24} />
						</div>
						<div class="theme-info">
							<span class="theme-label">{t.label}</span>
							<span class="theme-desc">{t.description}</span>
						</div>
						{#if theme.variant === t.label}
							<div class="active-indicator"></div>
						{/if}
					</button>
				{/each}
			</div>
		</section>

		<section class="settings-section">
			<div class="section-header">
				<h2>General</h2>
			</div>

			<div class="settings-list">
				<button
					class="mock-item settings-row"
					class:open={localContextOpen}
					onclick={() => (localContextOpen = !localContextOpen)}
					aria-expanded={localContextOpen}
				>
					<span>
						Local context
						<small>Location, timezone, and locale for date-aware replies</small>
					</span>
					<div class="row-meta">
						{#if contextLoading}
							<span class="badge">Loading</span>
						{/if}
						<span class="row-caret"><CaretRightIcon size={18} /></span>
					</div>
				</button>

				{#if localContextOpen}
					<div class="collapsible-panel">
						<p class="section-intro">Let BitBuddy know your local date, time, and place when it answers.</p>

						{#if contextError}
							<div class="inline-error">{contextError}</div>
						{/if}

						<div class="context-panel">
							<label class="mock-item field-row">
								<span>
									Location
									<small>Optional city or region label</small>
								</span>
								<input bind:value={userContext.location_label} placeholder="Chicago, IL" disabled={contextLoading} />
							</label>
							<label class="mock-item field-row">
								<span>
									Timezone
									<small>IANA timezone used for local date and time</small>
								</span>
								<input bind:value={userContext.timezone} placeholder="America/Chicago" disabled={contextLoading} />
							</label>
							<label class="mock-item field-row">
								<span>
									Locale
									<small>Language and regional formatting preference</small>
								</span>
								<input bind:value={userContext.locale} placeholder="en-US" disabled={contextLoading} />
							</label>
						</div>

						<div class="context-actions">
							<button class="secondary-action" onclick={useDeviceContext} disabled={contextLoading}>Use this device</button>
							<button class="primary-action" onclick={saveUserContext} disabled={contextLoading || contextSaving}>
								{contextSaving ? 'Saving...' : 'Save local context'}
							</button>
						</div>

						{#if contextStatus}
							<p class="save-status">{contextStatus}</p>
						{/if}
					</div>
				{/if}

				<button
					class="mock-item settings-row"
					class:open={chatBehaviorOpen}
					onclick={() => (chatBehaviorOpen = !chatBehaviorOpen)}
					aria-expanded={chatBehaviorOpen}
				>
					<span>
						Chat behavior
						<small>Typing speed and response display preferences</small>
					</span>
					<div class="row-meta">
						<span class="badge">{chatBehavior.replyAnimation}</span>
						<span class="row-caret"><CaretRightIcon size={18} /></span>
					</div>
				</button>

				{#if chatBehaviorOpen}
					<div class="collapsible-panel">
						<p class="section-intro">Choose how assistant replies appear while they stream into chat.</p>

						<div class="animation-grid">
							{#each replyAnimations as option}
								<button
									class="animation-card"
									class:active={chatBehavior.replyAnimation === option.label}
									onclick={() => chatBehavior.setReplyAnimation(option.label)}
								>
									<span>{option.label}</span>
									<small>{option.description}</small>
									{#if chatBehavior.replyAnimation === option.label}
										<i aria-hidden="true"></i>
									{/if}
								</button>
							{/each}
						</div>
					</div>
				{/if}
			</div>
		</section>

		<section class="settings-section">
			<div class="section-header">
				<h2>Model & Runtime</h2>
			</div>

			<div class="settings-list">
				<button
					class="mock-item settings-row"
					class:open={modelRuntimeOpen}
					onclick={() => (modelRuntimeOpen = !modelRuntimeOpen)}
					aria-expanded={modelRuntimeOpen}
				>
					<span>
						Provider setup
						<small>Model provider, endpoint, selected model, and project scan interval</small>
					</span>
					<div class="row-meta">
						{#if contextLoading}
							<span class="badge">Loading</span>
						{:else}
							<span class="badge">{modelRuntime.provider.type}</span>
							{#if modelRuntime.provider.model}<span class="badge">{modelRuntime.provider.model}</span>{/if}
						{/if}
						<span class="row-caret"><CaretRightIcon size={18} /></span>
					</div>
				</button>

				{#if modelRuntimeOpen}
					<div class="collapsible-panel">
						<p class="section-intro">Change the same local model connection values created during setup. These are stored in your BitBuddy config.</p>

						{#if modelError}
							<div class="inline-error">{modelError}</div>
						{/if}

						<div class="context-panel">
							<label class="mock-item field-row">
								<span>
									Provider
									<small>Runtime API BitBuddy uses for chat completions</small>
								</span>
								<select bind:value={modelRuntime.provider.type} disabled={contextLoading}>
									{#each providerTypes as provider}
										<option value={provider.value}>{provider.label}</option>
									{/each}
								</select>
							</label>
							<label class="mock-item field-row">
								<span>
									Provider URL
									<small>Example: http://127.0.0.1:11434 or http://127.0.0.1:8080</small>
								</span>
								<input bind:value={modelRuntime.provider.url} placeholder="http://127.0.0.1:11434" disabled={contextLoading || modelRuntime.provider.type === 'none'} />
							</label>
							<label class="mock-item field-row">
								<span>
									Model
									<small>Optional for llama.cpp, required by most Ollama setups</small>
								</span>
								<input list="provider-models" bind:value={modelRuntime.provider.model} placeholder="qwen2.5-coder:14b" disabled={contextLoading || modelRuntime.provider.type === 'none'} />
								<datalist id="provider-models">
									{#each providerModels as model}
										<option value={model}></option>
									{/each}
								</datalist>
							</label>
							<label class="mock-item field-row">
								<span>
									Project scan interval
									<small>Seconds between project memory scans; 0 disables monitoring</small>
								</span>
								<input type="number" min="0" bind:value={modelRuntime.project_scan_interval_seconds} disabled={contextLoading} />
							</label>
						</div>

						{#if providerContext}
							<div class="diagnostic-card">
								<span>Context window</span>
								<strong>{providerContext.context_window_tokens ? `${providerContext.context_window_tokens.toLocaleString()} tokens` : 'Unknown'}</strong>
								<small>{providerContext.source ?? 'No source reported'}</small>
							</div>
						{/if}

						<div class="context-actions">
							<button class="secondary-action" onclick={checkProvider} disabled={contextLoading || modelChecking || modelRuntime.provider.type === 'none'}>
								{modelChecking ? 'Checking...' : 'Check connection'}
							</button>
							<button class="secondary-action" onclick={loadProviderModels} disabled={contextLoading || modelLoadingModels || modelRuntime.provider.type === 'none'}>
								{modelLoadingModels ? 'Loading...' : 'List models'}
							</button>
							<button class="primary-action" onclick={saveModelRuntime} disabled={contextLoading || modelSaving}>
								{modelSaving ? 'Saving...' : 'Save model settings'}
							</button>
						</div>

						{#if modelStatus}
							<p class="save-status">{modelStatus}</p>
						{/if}
					</div>
				{/if}
			</div>
		</section>

		<section class="settings-section">
			<div class="section-header">
				<h2>MCP & Desktop Control</h2>
			</div>

			<div class="settings-list">
				<button
					class="mock-item settings-row"
					class:open={mcpOpen}
					onclick={() => (mcpOpen = !mcpOpen)}
					aria-expanded={mcpOpen}
				>
					<span>
						External MCP tools
						<small>Opt-in discovery for MCP servers such as Linux desktop control</small>
					</span>
					<div class="row-meta">
						<span class="badge">{mcp.enabled ? 'Enabled' : 'Off'}</span>
						{#if mcpStatus?.computer_use_linux.configured}<span class="badge">Desktop configured</span>{/if}
						{#if mcpStatus?.computer_use_linux.available}<span class="badge">Installed</span>{/if}
						<span class="row-caret"><CaretRightIcon size={18} /></span>
					</div>
				</button>

				{#if mcpOpen}
					<div class="collapsible-panel">
						<p class="section-intro">MCP is off by default. Built-in web search stays available separately. Enable MCP only when you want BitBuddy to discover external local tool servers.</p>

						{#if mcpError}
							<div class="inline-error">{mcpError}</div>
						{/if}

						<div class="context-panel">
							<label class="mock-item toggle-row">
								<span>
									Enable MCP discovery
									<small>External MCP tools appear in chat only when this is on</small>
								</span>
								<input type="checkbox" bind:checked={mcp.enabled} />
							</label>
							<div class="mock-item status-row">
								<span>
									Linux desktop control
									<small>{mcpStatus?.computer_use_linux.message ?? 'Not checked yet.'}</small>
								</span>
								<div class="row-meta">
									<span class="badge">{mcpStatus?.computer_use_linux.configured ? 'Configured' : 'Not configured'}</span>
									<span class="badge">{mcpStatus?.computer_use_linux.available ? 'Installed' : 'Missing'}</span>
								</div>
							</div>
							{#if mcpStatus?.computer_use_linux.path}
								<div class="mock-item status-row">
									<span>
										Binary path
										<small>{mcpStatus.computer_use_linux.source}</small>
									</span>
									<code>{mcpStatus.computer_use_linux.path}</code>
								</div>
							{/if}
						</div>

						<div class="context-actions">
							<button class="secondary-action" onclick={refreshMcpStatus} disabled={mcpWorking || mcpSaving}>Refresh status</button>
							<button class="secondary-action" onclick={() => runMcpAction('install')} disabled={mcpWorking || mcpSaving}>{mcpWorking ? 'Working...' : 'Install Linux control'}</button>
							<button class="secondary-action" onclick={() => runMcpAction('configure')} disabled={mcpWorking || mcpSaving}>Configure Linux control</button>
							<button class="secondary-action" onclick={() => runMcpAction('doctor')} disabled={mcpWorking || mcpSaving || !mcpStatus?.computer_use_linux.available}>Run doctor</button>
							<button class="primary-action" onclick={saveMcpSettings} disabled={mcpWorking || mcpSaving}>{mcpSaving ? 'Saving...' : 'Save MCP settings'}</button>
						</div>

						{#if mcpStatus?.doctor}
							<div class="diagnostic-card">
								<span>Doctor result</span>
								<strong>{mcpStatus.doctor.ok ? 'Ready' : 'Needs attention'}</strong>
								<small>{mcpStatus.doctor.stderr || mcpStatus.doctor.stdout || `Exit code ${mcpStatus.doctor.returncode}`}</small>
							</div>
						{/if}

						{#if mcpMessage}
							<p class="save-status">{mcpMessage}</p>
						{/if}
					</div>
				{/if}
			</div>
		</section>

		<section class="settings-section">
			<div class="section-header">
				<h2>Autonomy</h2>
			</div>

			<div class="settings-list">
				<button
					class="mock-item settings-row"
					class:open={autonomyControlsOpen}
					onclick={() => (autonomyControlsOpen = !autonomyControlsOpen)}
					aria-expanded={autonomyControlsOpen}
				>
					<span>
						Idle autonomy
						<small>Scheduling, repeat behavior, queue limits, and web search tools</small>
					</span>
					<div class="row-meta">
						<span class="badge">{autonomy.enabled && autonomy.run_after_idle_consolidation ? 'Enabled' : 'Off'}</span>
						<span class="badge">{Math.round(Number(autonomy.idle_delay_seconds) || 0)}s delay</span>
						<span class="row-caret"><CaretRightIcon size={18} /></span>
					</div>
				</button>

				{#if autonomyControlsOpen}
					<div class="collapsible-panel">
						<p class="section-intro">Control what BitBuddy is allowed to do while you are away. These settings affect newly scheduled idle cycles.</p>

						{#if autonomyError}
							<div class="inline-error">{autonomyError}</div>
						{/if}

						<div class="context-panel">
							<label class="mock-item toggle-row">
								<span>
									Enable autonomy
									<small>Master switch for idle autonomous behavior</small>
								</span>
								<input type="checkbox" bind:checked={autonomy.enabled} />
							</label>
							<label class="mock-item toggle-row">
								<span>
									Run after memory consolidation
									<small>Schedule autonomy after private idle memory review finishes</small>
								</span>
								<input type="checkbox" bind:checked={autonomy.run_after_idle_consolidation} />
							</label>
							<label class="mock-item field-row">
								<span>
									Idle delay
									<small>Seconds before an idle autonomy cycle starts</small>
								</span>
								<input type="number" min="0" bind:value={autonomy.idle_delay_seconds} />
							</label>
							<label class="mock-item toggle-row">
								<span>
									Repeat idle cycles
									<small>Allow another cycle while you remain away</small>
								</span>
								<input type="checkbox" bind:checked={autonomy.repeat_idle_cycles} />
							</label>
							<label class="mock-item field-row">
								<span>
									Backoff multiplier
									<small>Delay multiplier for repeat cycles; minimum 1</small>
								</span>
								<input type="number" min="1" step="0.1" bind:value={autonomy.idle_backoff_multiplier} />
							</label>
							<label class="mock-item field-row">
								<span>
									Max repeat delay
									<small>Maximum seconds between repeat cycles</small>
								</span>
								<input type="number" min="0" bind:value={autonomy.idle_max_delay_seconds} />
							</label>
							<label class="mock-item field-row">
								<span>
									Max actions per cycle
									<small>Upper bound for autonomy work in a single cycle</small>
								</span>
								<input type="number" min="1" bind:value={autonomy.max_actions_per_cycle} />
							</label>
							<label class="mock-item field-row">
								<span>
									Pending questions cap
									<small>Maximum queued questions BitBuddy may keep</small>
								</span>
								<input type="number" min="1" bind:value={autonomy.max_pending_questions} />
							</label>
							<label class="mock-item field-row">
								<span>
									Pending comments cap
									<small>Maximum queued comments BitBuddy may keep</small>
								</span>
								<input type="number" min="1" bind:value={autonomy.max_pending_comments} />
							</label>
							<label class="mock-item field-row">
								<span>
									New questions per cycle
									<small>Limit question generation during one autonomy pass</small>
								</span>
								<input type="number" min="0" bind:value={autonomy.max_new_questions_per_cycle} />
							</label>
							<label class="mock-item field-row">
								<span>
									Daily autonomous deliveries
									<small>Max times per day BitBuddy spontaneously speaks up without a prompt</small>
								</span>
								<input type="number" min="1" max="50" bind:value={autonomy.max_autonomous_deliveries_per_day} />
							</label>
							<label class="mock-item toggle-row">
								<span>
									Web search
									<small>Allow safe web curiosity through the local search backend</small>
								</span>
								<input type="checkbox" bind:checked={autonomy.web_search.enabled} />
							</label>
							<label class="mock-item field-row">
								<span>
									Search URL
									<small>Local SearxNG-compatible backend URL</small>
								</span>
								<input bind:value={autonomy.web_search.url} placeholder="http://127.0.0.1:8888" disabled={!autonomy.web_search.enabled} />
							</label>
							<label class="mock-item field-row">
								<span>
									Search results
									<small>Maximum results per web curiosity search, 1-10</small>
								</span>
								<input type="number" min="1" max="10" bind:value={autonomy.web_search.max_results} disabled={!autonomy.web_search.enabled} />
							</label>
						</div>

						<div class="context-actions">
							<button class="primary-action" onclick={saveAutonomyConfig} disabled={autonomySaving || contextLoading}>
								{autonomySaving ? 'Saving...' : 'Save autonomy settings'}
							</button>
						</div>

						{#if autonomyStatus}
							<p class="save-status">{autonomyStatus}</p>
						{/if}
					</div>
				{/if}

				<button
					class="mock-item settings-row"
					class:open={dreamingOpen}
					onclick={() => (dreamingOpen = !dreamingOpen)}
					aria-expanded={dreamingOpen}
				>
					<span>
						Dreaming mode
						<small>Night eligibility, MiniDream cleanup, and quiet-mode behavior</small>
					</span>
					<div class="row-meta">
						<span class="badge">{dreaming.enabled ? 'Enabled' : 'Off'}</span>
						<span class="badge">{dreaming.bedtime} - {dreaming.wake_time}</span>
						<span class="row-caret"><CaretRightIcon size={18} /></span>
					</div>
				</button>

				{#if dreamingOpen}
					<div class="collapsible-panel">
						<p class="section-intro">Bedtime only opens a night-eligible window. BitBuddy starts MiniDream after user inactivity, and user activity always wins.</p>

						{#if dreamingError}
							<div class="inline-error">{dreamingError}</div>
						{/if}

						<div class="context-panel">
							<label class="mock-item toggle-row">
								<span>
									Enable dreaming
									<small>Allow NightEligible, MiniDream cleanup, and Sleep lifecycle states</small>
								</span>
								<input type="checkbox" bind:checked={dreaming.enabled} />
							</label>
							<label class="mock-item toggle-row">
								<span>
									Quiet mode after bedtime
									<small>Reduce low-priority autonomy while the user may be winding down</small>
								</span>
								<input type="checkbox" bind:checked={dreaming.quiet_mode_after_bedtime} />
							</label>
							<label class="mock-item field-row">
								<span>
									Bedtime
									<small>Local 24-hour time that opens NightEligible</small>
								</span>
								<input type="time" bind:value={dreaming.bedtime} />
							</label>
							<label class="mock-item field-row">
								<span>
									Wake time
									<small>Local 24-hour time that returns to daytime Awake</small>
								</span>
								<input type="time" bind:value={dreaming.wake_time} />
							</label>
							<label class="mock-item field-row">
								<span>
									Idle before dream
									<small>Minutes after last user activity before MiniDream can run</small>
								</span>
								<input type="number" min="0" bind:value={dreaming.idle_before_dream_minutes} />
							</label>
							<label class="mock-item field-row">
								<span>
									Minimum dream window
									<small>Reserved for deeper dream scheduling; MiniDream remains cheap</small>
								</span>
								<input type="number" min="0" bind:value={dreaming.minimum_dream_window_minutes} />
							</label>
							<label class="mock-item field-row">
								<span>
									Stale queue days
									<small>Conservative age threshold for low-value queued items</small>
								</span>
								<input type="number" min="1" bind:value={dreaming.stale_intention_days} />
							</label>
							<label class="mock-item field-row">
								<span>
									Low-priority stale days
									<small>Age threshold for priority 1 queued items</small>
								</span>
								<input type="number" min="1" bind:value={dreaming.low_priority_stale_intention_days} />
							</label>
							<label class="mock-item field-row">
								<span>
									Goodnight triggers
									<small>Comma-separated phrases that open night eligibility</small>
								</span>
								<input bind:value={goodnightTriggers} placeholder="goodnight, good night" />
							</label>
							<label class="mock-item field-row">
								<span>
									Good morning triggers
									<small>Comma-separated phrases that return to Awake</small>
								</span>
								<input bind:value={goodmorningTriggers} placeholder="good morning, morning" />
							</label>
							<label class="mock-item toggle-row">
								<span>
									SelfNote injection
									<small>Experimental: selectively inject a few relevant SelfNotes into prompts</small>
								</span>
								<input type="checkbox" bind:checked={dreaming.self_note_injection_enabled} />
							</label>
						</div>

						<div class="context-actions">
							<button class="primary-action" onclick={saveDreamingConfig} disabled={dreamingSaving || contextLoading}>
								{dreamingSaving ? 'Saving...' : 'Save dreaming settings'}
							</button>
						</div>

						{#if dreamingStatus}
							<p class="save-status">{dreamingStatus}</p>
						{/if}
					</div>
				{/if}
			</div>
		</section>
	</div>
</div>

<style>
	.settings-page {
		box-sizing: border-box;
		width: 100%;
		max-width: 90rem;
		min-width: 0;
		height: 100%;
		min-height: 0;
		overflow-y: auto;
		overflow-x: hidden;
		padding: 0 1rem;
		margin: 0 auto;
		animation: fade-in 0.3s ease-out;
		scrollbar-color: var(--scrollbar-thumb) transparent;
	}

	@keyframes fade-in {
		from { opacity: 0; transform: translateY(10px); }
		to { opacity: 1; transform: translateY(0); }
	}

	.settings-header {
		margin-bottom: 2.5rem;
	}

	h1 {
		font-size: 2.25rem;
		font-weight: 900;
		letter-spacing: -0.02em;
	}

	.settings-content {
		display: grid;
		gap: 3rem;
		min-width: 0;
		padding-bottom: 2rem;
	}

	.settings-section,
	.settings-list,
	.context-panel,
	.collapsible-panel {
		min-width: 0;
	}

	.settings-section h2 {
		font-size: 1.25rem;
		font-weight: 700;
		margin-bottom: 0.5rem;
	}

	.section-intro {
		color: var(--text-soft);
		font-size: 0.95rem;
		margin-bottom: 1.5rem;
	}

	.theme-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
		gap: 1rem;
	}

	.theme-card {
		position: relative;
		display: flex;
		align-items: center;
		gap: 1rem;
		padding: 1.25rem;
		border: 1px solid var(--border);
		border-radius: 1.25rem;
		background: var(--panel);
		text-align: left;
		transition: all 200ms cubic-bezier(0.4, 0, 0.2, 1);
	}

	.theme-card:hover {
		border-color: var(--border-strong);
		background: var(--panel-raised);
		transform: translateY(-2px);
		box-shadow: var(--shadow-panel);
	}

	.theme-card.active {
		border-color: var(--accent);
		background: var(--accent-soft);
		box-shadow: 0 8px 24px rgba(121, 184, 255, 0.12);
	}

	.theme-icon {
		width: 3rem;
		height: 3rem;
		min-width: 3rem;
		flex: 0 0 3rem;
		display: grid;
		place-items: center;
		border-radius: 0.85rem;
		background: var(--surface-glass);
		color: var(--text-muted);
	}

	.active .theme-icon {
		background: var(--accent);
		color: var(--on-accent);
	}

	.theme-info {
		display: flex;
		flex-direction: column;
	}

	.theme-label {
		font-weight: 700;
		font-size: 1.05rem;
	}

	.theme-desc {
		font-size: 0.82rem;
		color: var(--text-soft);
	}

	.active .theme-desc {
		color: var(--accent-strong);
		opacity: 0.8;
	}

	.active-indicator {
		position: absolute;
		top: 0.75rem;
		right: 0.75rem;
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 999px;
		background: var(--accent);
		box-shadow: 0 0 10px var(--accent);
	}

	.section-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 0.75rem;
		margin-bottom: 1rem;
	}

	.badge {
		padding: 0.2rem 0.5rem;
		border-radius: 0.5rem;
		background: var(--bg-soft);
		color: var(--text-soft);
		font-size: 0.7rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.mock-item {
		display: flex;
		align-items: center;
		justify-content: space-between;
		min-width: 0;
		padding: 1.25rem;
		border-bottom: 1px solid var(--border);
		color: var(--text-muted);
	}

	.settings-list {
		overflow: hidden;
		border: 1px solid var(--border);
		border-radius: 1.25rem;
		background: var(--panel);
	}

	.settings-row {
		width: 100%;
		border-top: none;
		border-right: none;
		border-left: none;
		background: transparent;
		font: inherit;
		text-align: left;
		transition: background 180ms ease;
	}

	.settings-row:hover {
		background: var(--panel-raised);
	}

	.settings-row > span {
		display: flex;
		min-width: 0;
		flex-direction: column;
		color: var(--text);
		font-weight: 700;
	}

	.settings-row small {
		margin-top: 0.2rem;
		color: var(--text-soft);
		font-size: 0.78rem;
		font-weight: 500;
	}

	.row-meta {
		display: inline-flex;
		align-items: center;
		flex: 0 0 auto;
		gap: 0.75rem;
	}

	.row-caret {
		transition: transform 180ms ease;
	}

	.settings-row.open .row-caret {
		transform: rotate(90deg);
	}

	.collapsible-panel {
		padding: 1.25rem;
		border-bottom: 1px solid var(--border);
		background: linear-gradient(180deg, var(--panel-raised), var(--panel));
	}

	.context-panel {
		overflow: hidden;
		border: 1px solid var(--border);
		border-radius: 1.25rem;
		background: var(--panel);
	}

	.animation-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
		gap: 0.8rem;
	}

	.animation-card {
		position: relative;
		display: flex;
		min-height: 6.5rem;
		flex-direction: column;
		align-items: flex-start;
		justify-content: center;
		gap: 0.35rem;
		padding: 1rem;
		border: 1px solid var(--border);
		border-radius: 1rem;
		background: var(--panel);
		color: var(--text);
		font: inherit;
		text-align: left;
		transition: all 180ms ease;
	}

	.animation-card:hover {
		border-color: var(--border-strong);
		background: var(--panel-raised);
		transform: translateY(-1px);
	}

	.animation-card.active {
		border-color: var(--accent);
		background: var(--accent-soft);
		box-shadow: 0 8px 24px rgba(121, 184, 255, 0.1);
	}

	.animation-card span {
		font-weight: 800;
	}

	.animation-card small {
		max-width: 18rem;
		color: var(--text-soft);
		font-size: 0.8rem;
		line-height: 1.35;
	}

	.animation-card i {
		position: absolute;
		top: 0.85rem;
		right: 0.85rem;
		width: 0.52rem;
		height: 0.52rem;
		border-radius: 999px;
		background: var(--accent);
		box-shadow: 0 0 10px var(--accent);
	}

	.field-row {
		gap: 1rem;
		color: var(--text);
	}

	.field-row span {
		display: flex;
		min-width: 10rem;
		flex-direction: column;
		font-weight: 700;
	}

	.field-row small {
		margin-top: 0.2rem;
		color: var(--text-soft);
		font-size: 0.78rem;
		font-weight: 500;
	}

	.field-row input,
	.field-row select {
		width: min(20rem, 52vw);
		min-width: 0;
		max-width: 100%;
		border: 1px solid var(--border);
		border-radius: 0.8rem;
		background: var(--bg-soft);
		color: var(--text);
		font: inherit;
		padding: 0.75rem 0.9rem;
	}

	.field-row select {
		appearance: none;
	}

	.toggle-row {
		gap: 1rem;
		color: var(--text);
	}

	.toggle-row span {
		display: flex;
		min-width: 10rem;
		flex-direction: column;
		font-weight: 700;
	}

	.toggle-row small {
		margin-top: 0.2rem;
		color: var(--text-soft);
		font-size: 0.78rem;
		font-weight: 500;
	}

	.toggle-row input {
		width: 1.2rem;
		height: 1.2rem;
		accent-color: var(--accent);
		flex: 0 0 auto;
	}

	.status-row {
		gap: 1rem;
		color: var(--text);
	}

	.status-row span {
		display: flex;
		min-width: 10rem;
		flex-direction: column;
		font-weight: 700;
	}

	.status-row small {
		margin-top: 0.2rem;
		color: var(--text-soft);
		font-size: 0.78rem;
		font-weight: 500;
	}

	.status-row code {
		max-width: min(32rem, 50vw);
		overflow-wrap: anywhere;
		border: 1px solid var(--border);
		border-radius: 0.6rem;
		background: var(--bg-soft);
		padding: 0.45rem 0.6rem;
		color: var(--text-soft);
		font-size: 0.78rem;
	}

	.field-row input:focus,
	.field-row select:focus {
		outline: none;
		border-color: var(--accent);
		box-shadow: 0 0 0 3px var(--accent-soft);
	}

	.diagnostic-card {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
		margin-top: 1rem;
		padding: 0.9rem 1rem;
		border: 1px solid var(--border);
		border-radius: 1rem;
		background: var(--surface-card);
		color: var(--text-soft);
	}

	.diagnostic-card span,
	.diagnostic-card strong,
	.diagnostic-card small {
		min-width: 0;
	}

	.diagnostic-card strong {
		color: var(--text);
	}

	.context-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.75rem;
		justify-content: flex-end;
		margin-top: 1rem;
	}

	.primary-action,
	.secondary-action {
		border: 1px solid var(--border);
		border-radius: 999px;
		font-weight: 800;
		padding: 0.75rem 1rem;
		transition: all 180ms ease;
	}

	.primary-action {
		border-color: var(--accent);
		background: var(--accent);
		color: var(--on-accent);
	}

	.secondary-action {
		background: var(--panel);
		color: var(--text);
	}

	.primary-action:hover:not(:disabled),
	.secondary-action:hover:not(:disabled) {
		transform: translateY(-1px);
		box-shadow: var(--shadow-panel);
	}

	.primary-action:disabled,
	.secondary-action:disabled,
	.field-row input:disabled,
	.field-row select:disabled {
		cursor: not-allowed;
		opacity: 0.6;
	}

	.inline-error,
	.save-status {
		margin-bottom: 1rem;
		border-radius: 0.9rem;
		padding: 0.8rem 1rem;
		font-size: 0.9rem;
	}

	.inline-error {
		border: 1px solid rgba(248, 113, 113, 0.35);
		background: rgba(248, 113, 113, 0.1);
		color: var(--danger);
	}

	.save-status {
		margin-top: 1rem;
		margin-bottom: 0;
		border: 1px solid rgba(110, 231, 183, 0.35);
		background: rgba(110, 231, 183, 0.1);
		color: var(--text-soft);
	}

	.mock-item:last-child {
		border-bottom: none;
	}

	@media (max-width: 640px) {
		.field-row {
			align-items: stretch;
			flex-direction: column;
		}

		.toggle-row {
			align-items: flex-start;
		}

		.status-row {
			align-items: stretch;
			flex-direction: column;
		}

		.field-row span {
			min-width: 0;
		}

		.toggle-row span {
			min-width: 0;
		}

		.status-row span {
			min-width: 0;
		}

		.status-row code {
			max-width: 100%;
		}

		.field-row input,
		.field-row select {
			width: 100%;
		}

		.diagnostic-card {
			align-items: flex-start;
			flex-direction: column;
		}

		.context-actions {
			justify-content: stretch;
		}

		.primary-action,
		.secondary-action {
			width: 100%;
		}
	}
</style>
