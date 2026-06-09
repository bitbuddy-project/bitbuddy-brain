<script lang="ts">
	import { onMount } from 'svelte';
	import { setTimePreferences } from '$lib/stores/time.svelte';
	import { theme, type ThemeVariant } from '$lib/stores/theme.svelte';
	import { chatBehavior, type ReplyAnimation } from '$lib/stores/chat-behavior.svelte';
	import { refreshContextUsage } from '$lib/stores/chat.svelte';
	import {
		clearGmailClientSecret,
		completeCodexLogin,
		completeGmailLogin,
		configureComputerUseLinux,
		getCodexStatus,
		getCalendarPermissions,
		getConfig,
		getEmailPermissions,
		getGmailStatus,
		getMcpStatus,
		getProviderContext,
		getProviderHealth,
		getProviderModels,
		installComputerUseLinux,
		logoutCodex,
		logoutGmail,
		openGmailCleanBrowser,
		doctorComputerUseLinux,
		startCodexLogin,
		setCalendarPermission,
		setEmailPermission,
		startGmailLogin,
		updateAutonomyConfig,
		updateCalendarConfig,
		updateChatConfig,
		updateDreamingConfig,
		updateEmailConfig,
		updateMcpConfig,
		updateModelRuntimeConfig,
		updatePersonalityConfig,
		updateUserContext,
		type AutonomyConfig,
		type CalendarConfig,
		type CalendarPermissionState,
		type CalendarScope,
		type ChatConfig,
		type DreamingConfig,
		type EmailConfig,
		type GmailOAuthStatus,
		type McpConfig,
		type McpStatus,
		type ModelRuntimeConfig,
		type ProviderEntry,
		type ProviderContext,
		type UserContextConfig
	} from '$lib/api/bitbuddy';
	import Checkbox from '$lib/components/ui/Checkbox.svelte';
	import Overlay from '$lib/components/ui/Overlay.svelte';
	import SelectMenu, { type SelectOption } from '$lib/components/ui/SelectMenu.svelte';
	import SunIcon from 'phosphor-svelte/lib/SunIcon';
	import MoonIcon from 'phosphor-svelte/lib/MoonIcon';
	import DesktopIcon from 'phosphor-svelte/lib/DesktopIcon';
	import CaretRightIcon from 'phosphor-svelte/lib/CaretRightIcon';
	import GearSixIcon from 'phosphor-svelte/lib/GearSixIcon';

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
		{ value: 'ollama', label: 'Ollama', description: 'Local Ollama runtime' },
		{ value: 'llama.cpp', label: 'llama.cpp', description: 'Local llama.cpp server' },
		{ value: 'openai', label: 'OpenAI API', description: 'OpenAI API key provider' },
		{ value: 'codex', label: 'Codex', description: 'ChatGPT/Codex authorization' },
		{ value: 'anthropic', label: 'Anthropic', description: 'Claude API key provider' }
	];
	const providerOptions: SelectOption[] = providerTypes;
	const emailProviderOptions: SelectOption[] = [
		{ value: 'imap', label: 'IMAP', description: 'Generic inbox server' },
		{ value: 'gmail', label: 'Gmail', description: 'Google Gmail API' }
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
	let personalityQuirksOpen = $state(false);
	let personalitySaving = $state(false);
	let personalityError = $state('');
	let personalityStatus = $state('');
	let personalityDisplayName = $state('');
	let personalityId = $state('');
	let bitbuddyLikes = $state<string[]>([]);
	let bitbuddyDislikes = $state<string[]>([]);
	let quirkAddOpen = $state(false);
	let chatConfigSaving = $state(false);
	let chatConfigError = $state('');
	let chatConfigStatus = $state('');
	let chatConfig = $state<ChatConfig>({
		return_greeting_enabled: true,
		return_greeting_idle_minutes: 60,
		return_greeting_phrases: ['Hey, welcome back.', 'Hi, welcome back.'],
		max_tool_rounds: 99
	});
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
		providers: [],
		active_provider: 'none',
		project_scan_interval_seconds: 60
	});
	let draftProvider = $state<ProviderEntry>({ type: 'ollama', url: 'http://127.0.0.1:11434', model: '' });
	let draftProviderKey = $state('');
	let editingProviderKey = $state('');
	let addProviderOpen = $state(false);
	let pendingAddedProviderKey = $state('');
	let providerPendingRemoval = $state<ProviderEntry | null>(null);
	let modelSaving = $state(false);
	let modelChecking = $state(false);
	let modelLoadingModels = $state(false);
	let modelError = $state('');
	let modelStatus = $state('');
	let providerModels = $state<string[]>([]);
	let providerContext = $state<ProviderContext | null>(null);
	let codexStatus = $state('');
	let codexLoggedIn = $state(false);
	let codexWorking = $state(false);
	let codexAuthUrl = $state('');
	let codexDeviceCode = $state('');
	let codexLoginDetail = $state('');
	let codexLoginLogPath = $state('');
	let codexManualInput = $state('');
	let codexCallbackMode = $state('');
	let providerModelLoadKey = $state('');
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
	let calendarOpen = $state(false);
	let calendarSaving = $state(false);
	let calendarError = $state('');
	let calendarStatus = $state('');
	let calendar = $state<CalendarConfig>({
		enabled: false,
		default_provider: 'local',
		reminder_upcoming_minutes: 60,
		reminder_starting_soon_minutes: 15,
		urgent_interrupts_enabled: true,
		urgent_interrupt_persistent: true,
		conflict_warnings_enabled: true,
		free_day_summary_enabled: true,
		chat_nudges_enabled: true,
		scheduler_tick_seconds: 60,
		holidays_enabled: true,
		holidays_country: ''
	});
	let emailOpen = $state(false);
	let emailAdvancedOpen = $state(false);
	let emailTroubleshootingOpen = $state(false);
	let emailSaving = $state(false);
	let emailError = $state('');
	let emailStatus = $state('');
	let emailPassword = $state('');
	let gmailClientSecret = $state('');
	let gmailManualInput = $state('');
	let gmailStatus = $state<GmailOAuthStatus | null>(null);
	let gmailWorking = $state(false);
	let email = $state<EmailConfig>({
		enabled: false,
		provider: 'imap',
		account_label: '',
		email_address: '',
		imap_host: '',
		imap_port: 993,
		imap_security: 'ssl',
		username: '',
		credentials_ref: '',
		gmail_oauth_mode: 'desktop_pkce',
		gmail_client_id: '',
		gmail_credentials_ref: '',
		gmail_token_ref: '',
		gmail_redirect_uri: 'http://127.0.0.1:8787/email/gmail/callback',
		default_mailbox: 'INBOX',
		max_preview_messages: 50,
		has_password: false,
		has_gmail_client_secret: false,
		gmail_connected: false
	});

	const SCOPE_LABELS: Record<CalendarScope, string> = {
		read: 'View events',
		create: 'Create events',
		modify: 'Modify events',
		delete: 'Delete events'
	};
	const SCOPE_STATES: CalendarPermissionState[] = ['granted', 'ask', 'denied'];
	const EMAIL_SCOPE_LABELS: Record<string, string> = {
		read: 'Read messages',
		search: 'Search messages',
		watch: 'Watch rules',
		trash: 'Move to Trash'
	};

	let calendarScopes = $state<CalendarScope[]>([]);
	let calendarPermissions = $state<Record<CalendarScope, CalendarPermissionState> | null>(null);
	let calendarPermError = $state('');
	let emailScopes = $state<string[]>([]);
	let emailPermissions = $state<Record<string, string> | null>(null);
	let emailPermError = $state('');

	function gmailTroubleshootingHint(status: GmailOAuthStatus | null): string {
		if (!status?.diagnostics) return 'Click Check status after a failed attempt to see whether Google reached BitBuddy.';
		const diagnostics = status.diagnostics;
		const lastError = diagnostics.last_error ?? '';
		if (lastError.includes('client_secret is missing')) return 'Google returned a code, but token exchange needs your Google OAuth client_secret. Paste the client_secret from your Desktop OAuth credentials JSON, save, then reconnect.';
		if (lastError.includes('provided client secret is invalid')) return 'Google rejected the saved client secret. Clear it, then paste the client_secret that belongs to the currently configured client ID.';
		if (diagnostics.last_callback_seen && diagnostics.last_token_exchange_status === 'http_error:400') return lastError || 'Google returned a code, but token exchange failed. Check that the client ID and secret belong to the same Google OAuth client.';
		if (lastError) return lastError;
		if (diagnostics.last_auth_started_at && diagnostics.last_token_exchange_status === 'not_started') {
			return 'Google authorization opened, but Google has not redirected back to BitBuddy yet. Check URL-cleaning extensions such as ClearURLs, VPN/IP protection, test-user access, Gmail API enablement, and the OAuth Data Access scope.';
		}
		if (diagnostics.last_token_exchange_status) return `Token exchange: ${diagnostics.last_token_exchange_status}`;
		return status.message;
	}

	onMount(() => {
		void loadUserContext();
		void refreshCalendarPermissions();
		void refreshEmailPermissions();
	});

	$effect(() => {
		const shouldLoad = addProviderOpen || Boolean(editingProviderKey);
		if (!shouldLoad) {
			providerModels = [];
			providerModelLoadKey = '';
			return;
		}
		const key = `${draftProvider.type}|${draftProvider.url}|${draftProvider.has_api_key ? 'saved-key' : 'no-key'}`;
		if (key === providerModelLoadKey) return;
		providerModelLoadKey = key;
		void loadDraftProviderModels(true);
	});

	async function refreshCalendarPermissions() {
		try {
			const data = await getCalendarPermissions();
			calendarScopes = data.scopes;
			calendarPermissions = data.permissions;
			calendarPermError = '';
		} catch (caught) {
			calendarPermError = caught instanceof Error ? caught.message : 'Could not load calendar permissions.';
		}
	}

	async function setScope(scope: CalendarScope, state: CalendarPermissionState) {
		try {
			calendarPermissions = await setCalendarPermission(scope, state);
			calendarPermError = '';
		} catch (caught) {
			calendarPermError = caught instanceof Error ? caught.message : 'Could not update permission.';
		}
	}

	async function refreshEmailPermissions() {
		try {
			const data = await getEmailPermissions();
			emailScopes = data.scopes;
			emailPermissions = data.permissions;
			emailPermError = '';
		} catch (caught) {
			emailPermError = caught instanceof Error ? caught.message : 'Could not load email permissions.';
		}
	}

	async function setEmailScope(scope: string, state: string) {
		try {
			emailPermissions = await setEmailPermission(scope, state);
			emailPermError = '';
		} catch (caught) {
			emailPermError = caught instanceof Error ? caught.message : 'Could not update email permission.';
		}
	}

	async function refreshGmailStatus() {
		try {
			gmailStatus = await getGmailStatus();
			emailError = '';
		} catch (caught) {
			emailError = caught instanceof Error ? caught.message : 'Could not load Gmail status.';
		}
	}

	async function connectGmail(force = false) {
		gmailWorking = true;
		try {
			gmailStatus = await startGmailLogin(force);
			emailStatus = gmailStatus.message;
			gmailManualInput = '';
			emailError = '';
			if (gmailStatus.auth_url) window.open(gmailStatus.auth_url, '_blank', 'noopener,noreferrer');
		} catch (caught) {
			emailError = caught instanceof Error ? caught.message : 'Could not start Gmail authorization.';
			emailStatus = '';
		} finally {
			gmailWorking = false;
		}
	}

	async function finishGmailLogin() {
		gmailWorking = true;
		try {
			gmailStatus = await completeGmailLogin(gmailManualInput);
			email.gmail_connected = gmailStatus.connected;
			emailStatus = gmailStatus.message;
			gmailManualInput = '';
			emailError = '';
		} catch (caught) {
			emailError = caught instanceof Error ? caught.message : 'Could not complete Gmail authorization.';
			emailStatus = '';
		} finally {
			gmailWorking = false;
		}
	}

	async function connectGmailCleanBrowser() {
		gmailWorking = true;
		try {
			gmailStatus = await openGmailCleanBrowser(Boolean(email.gmail_connected || gmailStatus?.connected));
			emailStatus = gmailStatus.message;
			gmailManualInput = '';
			emailError = '';
		} catch (caught) {
			emailError = caught instanceof Error ? caught.message : 'Could not open clean browser OAuth profile.';
			emailStatus = '';
		} finally {
			gmailWorking = false;
		}
	}

	async function disconnectGmail() {
		gmailWorking = true;
		try {
			gmailStatus = await logoutGmail();
			emailStatus = gmailStatus.message;
			emailError = '';
		} catch (caught) {
			emailError = caught instanceof Error ? caught.message : 'Could not disconnect Gmail.';
			emailStatus = '';
		} finally {
			gmailWorking = false;
		}
	}

	async function removeGmailClientSecret() {
		gmailWorking = true;
		try {
			gmailStatus = await clearGmailClientSecret();
			email.has_gmail_client_secret = false;
			gmailClientSecret = '';
			emailStatus = gmailStatus.message;
			emailError = '';
		} catch (caught) {
			emailError = caught instanceof Error ? caught.message : 'Could not clear Gmail client secret.';
			emailStatus = '';
		} finally {
			gmailWorking = false;
		}
	}

	async function loadUserContext() {
		contextLoading = true;
		try {
			const config = await getConfig();
			const providers = configuredProviders(config.providers, config.provider);
			userContext = config.user_context ?? userContext;
			personalityDisplayName = config.personality?.display_name ?? '';
			personalityId = config.personality?.id ?? '';
			bitbuddyLikes = [...(config.personality?.bitbuddy_likes ?? [])];
			bitbuddyDislikes = [...(config.personality?.bitbuddy_dislikes ?? [])];
			chatConfig = config.chat ?? chatConfig;
			modelRuntime = {
				provider: config.provider,
				providers,
				active_provider: config.active_provider ?? config.provider.key ?? config.provider.type,
				project_scan_interval_seconds: config.runtime?.project_scan_interval_seconds ?? modelRuntime.project_scan_interval_seconds
			};
			beginAddProvider(firstAddableProviderType(providers), { open: false });
			pendingAddedProviderKey = '';
			if (providers.some((provider) => provider.type === 'codex')) void refreshCodexStatus();
			if (config.autonomy) {
				autonomy = config.autonomy;
			}
			if (config.dreaming) {
				dreaming = config.dreaming;
				goodnightTriggers = config.dreaming.goodnight_triggers.join(', ');
				goodmorningTriggers = config.dreaming.goodmorning_triggers.join(', ');
			}
			if (config.calendar) {
				calendar = config.calendar;
			}
			if (config.email) {
				email = config.email;
				if (config.email.provider === 'gmail') void refreshGmailStatus();
			}
			if (config.mcp) {
				mcp = config.mcp;
			}
			await refreshMcpStatus();
			contextError = '';
			modelError = '';
			chatConfigError = '';
			personalityError = '';
			mcpError = '';
			autonomyError = '';
			dreamingError = '';
			emailError = '';
		} catch (caught) {
			contextError = caught instanceof Error ? caught.message : 'Could not load local context.';
			chatConfigError = caught instanceof Error ? caught.message : 'Could not load chat settings.';
			personalityError = caught instanceof Error ? caught.message : 'Could not load personality settings.';
			modelError = caught instanceof Error ? caught.message : 'Could not load model and runtime settings.';
			autonomyError = caught instanceof Error ? caught.message : 'Could not load autonomy settings.';
			dreamingError = caught instanceof Error ? caught.message : 'Could not load dreaming settings.';
			emailError = caught instanceof Error ? caught.message : 'Could not load email settings.';
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

	function providerKey(provider: ProviderEntry | undefined): string {
		return provider?.key || provider?.type || 'none';
	}

	function providerLabel(type: string): string {
		return providerTypes.find((provider) => provider.value === type)?.label ?? type;
	}

	function isCloudProvider(type: string): boolean {
		return type === 'openai' || type === 'anthropic';
	}

	function isCodexProvider(type: string): boolean {
		return type === 'codex';
	}

	function providerUrlDefault(type: string): string {
		if (type === 'ollama') return 'http://127.0.0.1:11434';
		if (type === 'llama.cpp') return 'http://127.0.0.1:8080';
		if (type === 'openai') return 'https://api.openai.com';
		if (type === 'codex') return 'codex://chatgpt';
		if (type === 'anthropic') return 'https://api.anthropic.com';
		return '';
	}

	function providerModelDefault(type: string): string {
		if (type === 'openai') return 'gpt-4.1';
		if (type === 'codex') return 'gpt-5.5';
		if (type === 'anthropic') return 'claude-sonnet-4-6';
		return '';
	}

	function providerKeyUrl(type: string): string {
		if (type === 'openai') return 'https://platform.openai.com/api-keys';
		if (type === 'anthropic') return 'https://console.anthropic.com/settings/keys';
		return '';
	}

	function providerModelOptions(): SelectOption[] {
		const values: string[] = [];
		const current = draftProvider.model.trim();
		if (current) values.push(current);
		for (const model of providerModels) {
			if (model && !values.includes(model)) values.push(model);
		}
		return values.map((value) => ({ value, label: value }));
	}

	function setDraftProviderModel(model: string) {
		draftProvider.model = model;
	}

	function cleanQuirks(values: string[]): string[] {
		const result: string[] = [];
		const seen = new Set<string>();
		for (const value of values) {
			const clean = value.trim().replace(/\s+/g, ' ').slice(0, 80);
			const key = clean.toLowerCase();
			if (clean && !seen.has(key)) {
				result.push(clean);
				seen.add(key);
			}
		}
		return result;
	}

	function addQuirk(kind: 'like' | 'dislike') {
		if (kind === 'like') {
			bitbuddyLikes = [...bitbuddyLikes, ''];
		} else {
			bitbuddyDislikes = [...bitbuddyDislikes, ''];
		}
		quirkAddOpen = false;
	}

	function removeQuirk(kind: 'like' | 'dislike', index: number) {
		if (kind === 'like') {
			bitbuddyLikes = bitbuddyLikes.filter((_, itemIndex) => itemIndex !== index);
		} else {
			bitbuddyDislikes = bitbuddyDislikes.filter((_, itemIndex) => itemIndex !== index);
		}
	}

	function configuredProviders(providers: ProviderEntry[] | undefined, legacy: ProviderEntry): ProviderEntry[] {
		const list = providers?.length ? providers : legacy.type !== 'none' ? [legacy] : [];
		return list.filter((provider) => provider.type !== 'none').map((provider) => ({ ...provider, api_key: '' }));
	}

	function firstAddableProviderType(providers: ProviderEntry[]): string {
		return providerTypes.find((entry) => !providers.some((provider) => provider.type === entry.value))?.value ?? 'ollama';
	}

	function cleanProvider(provider: ProviderEntry): ProviderEntry {
		const clean: ProviderEntry = {
			key: provider.key || provider.type,
			type: provider.type,
			url: provider.url.trim(),
			model: provider.model.trim(),
			has_api_key: Boolean(provider.has_api_key)
		};
		if (provider.api_key?.trim()) clean.api_key = provider.api_key.trim();
		return clean;
	}

	function beginAddProvider(type = 'ollama', options: { open?: boolean } = {}) {
		draftProvider = { type, url: providerUrlDefault(type), model: providerModelDefault(type), has_api_key: false };
		draftProviderKey = '';
		editingProviderKey = '';
		addProviderOpen = Boolean(options.open);
	}

	function setDraftProviderType(type: string) {
		if (editingProviderKey) return;
		beginAddProvider(type, { open: true });
	}

	function openAddProvider() {
		if (pendingAddedProviderKey) {
			modelError = 'Save model settings or remove the unsaved provider before adding another provider.';
			return;
		}
		beginAddProvider(draftProvider.type || firstAddableProviderType(modelRuntime.providers ?? []), { open: true });
		modelError = '';
	}

	function cancelAddProvider() {
		beginAddProvider(firstAddableProviderType(modelRuntime.providers ?? []), { open: false });
		modelError = '';
		modelStatus = 'Provider add cancelled.';
	}

	function validateProviderDraft(provider: ProviderEntry): boolean {
		if (!isCodexProvider(provider.type) && !provider.url) {
			modelError = `${providerLabel(provider.type)} provider URL is required.`;
			return false;
		}
		if (isCloudProvider(provider.type) && !provider.has_api_key && !provider.api_key) {
			modelError = `${providerLabel(provider.type)} API key is required.`;
			return false;
		}
		return true;
	}

	function addProvider() {
		if (!addProviderOpen) {
			openAddProvider();
			return;
		}
		if (pendingAddedProviderKey) {
			modelError = 'Save model settings or remove the unsaved provider before adding another provider.';
			return;
		}
		const provider = cleanProvider({ ...draftProvider, api_key: draftProviderKey });
		if (!validateProviderDraft(provider)) return;
		const existing = modelRuntime.providers ?? [];
		if (existing.some((entry) => providerKey(entry) === providerKey(provider))) {
			modelError = `${providerLabel(provider.type)} is already configured. Use Edit provider on its card.`;
			return;
		}
		modelRuntime.providers = [...existing, provider];
		pendingAddedProviderKey = providerKey(provider);
		modelRuntime.active_provider = modelRuntime.active_provider && modelRuntime.active_provider !== 'none' ? modelRuntime.active_provider : providerKey(provider);
		modelError = '';
		modelStatus = `${providerLabel(provider.type)} provider added. Save model settings to apply.`;
		beginAddProvider(firstAddableProviderType([...existing, provider]), { open: false });
	}

	function editProvider(provider: ProviderEntry) {
		const key = providerKey(provider);
		if (pendingAddedProviderKey && pendingAddedProviderKey !== key) {
			modelError = 'Save model settings or remove the unsaved provider before editing another provider.';
			return;
		}
		editingProviderKey = key;
		addProviderOpen = false;
		draftProvider = { ...provider, api_key: '' };
		draftProviderKey = '';
		modelError = '';
		modelStatus = `Editing ${providerLabel(provider.type)}. Save or cancel from its card.`;
		if (provider.type === 'codex') void refreshCodexStatus();
	}

	function saveProviderEdit() {
		if (!editingProviderKey) return;
		const provider = cleanProvider({ ...draftProvider, api_key: draftProviderKey, key: editingProviderKey });
		if (!validateProviderDraft(provider)) return;
		const providers = modelRuntime.providers ?? [];
		modelRuntime.providers = providers.map((entry) => (providerKey(entry) === editingProviderKey ? provider : entry));
		if (modelRuntime.active_provider === editingProviderKey) modelRuntime.provider = provider;
		modelError = '';
		modelStatus = `${providerLabel(provider.type)} provider updated. Save model settings to apply.`;
		beginAddProvider(firstAddableProviderType(modelRuntime.providers ?? []), { open: false });
	}

	function cancelProviderEdit() {
		const previousType = draftProvider.type || 'ollama';
		beginAddProvider(previousType, { open: false });
		modelError = '';
		modelStatus = 'Provider edit cancelled.';
	}

	function selectActiveProvider(provider: ProviderEntry) {
		if (pendingAddedProviderKey && pendingAddedProviderKey !== providerKey(provider)) {
			modelError = 'Save model settings or remove the unsaved provider before switching active providers.';
			return;
		}
		modelRuntime.active_provider = providerKey(provider);
		modelRuntime.provider = provider;
		providerModels = [];
		providerContext = null;
	}

	function removeProvider(provider: ProviderEntry) {
		providerPendingRemoval = provider;
	}

	function confirmRemoveProvider() {
		if (!providerPendingRemoval) return;
		const provider = providerPendingRemoval;
		const key = providerKey(provider);
		const providers = (modelRuntime.providers ?? []).filter((entry) => providerKey(entry) !== key);
		modelRuntime.providers = providers;
		if (editingProviderKey === key || pendingAddedProviderKey === key) beginAddProvider(firstAddableProviderType(providers), { open: false });
		if (pendingAddedProviderKey === key) pendingAddedProviderKey = '';
		if (modelRuntime.active_provider === key) {
			modelRuntime.active_provider = providerKey(providers[0]);
			modelRuntime.provider = providers[0] ?? { type: 'none', url: '', model: '' };
		}
		providerModels = [];
		providerContext = null;
		providerPendingRemoval = null;
		modelStatus = `${providerLabel(provider.type)} provider removed. Save model settings to apply.`;
	}

	function cancelRemoveProvider() {
		providerPendingRemoval = null;
	}

	async function refreshCodexStatus() {
		codexWorking = true;
		try {
			const status = await getCodexStatus();
			codexLoggedIn = status.ok;
			codexStatus = status.message;
			if (status.ok) {
				codexAuthUrl = '';
				codexCallbackMode = '';
				codexManualInput = '';
				codexDeviceCode = '';
				codexLoginDetail = '';
			}
			modelError = '';
		} catch (caught) {
			codexLoggedIn = false;
			codexStatus = '';
			modelError = caught instanceof Error ? caught.message : 'Could not check Codex login status.';
		} finally {
			codexWorking = false;
		}
	}

	async function connectCodex() {
		codexWorking = true;
		try {
			const result = await startCodexLogin({ force: codexLoggedIn });
			codexLoggedIn = Boolean(result.connected);
			codexStatus = result.message;
			codexAuthUrl = result.auth_url ?? '';
			codexCallbackMode = result.callback_mode ?? '';
			codexDeviceCode = result.device_code ?? '';
			codexLoginDetail = result.log_excerpt ?? '';
			codexLoginLogPath = result.log_path ?? '';
			if (codexAuthUrl) window.open(codexAuthUrl, '_blank', 'noreferrer');
			modelError = '';
		} catch (caught) {
			modelError = caught instanceof Error ? caught.message : 'Could not start Codex login.';
		} finally {
			codexWorking = false;
		}
	}

	async function finishCodexLogin() {
		codexWorking = true;
		try {
			const result = await completeCodexLogin(codexManualInput);
			codexLoggedIn = result.ok;
			codexStatus = result.message;
			codexAuthUrl = '';
			codexManualInput = '';
			codexCallbackMode = '';
			modelError = '';
		} catch (caught) {
			modelError = caught instanceof Error ? caught.message : 'Could not complete Codex authorization.';
		} finally {
			codexWorking = false;
		}
	}

	async function disconnectCodex() {
		codexWorking = true;
		try {
			const result = await logoutCodex();
			codexLoggedIn = false;
			codexStatus = result.message;
			codexAuthUrl = '';
			codexCallbackMode = '';
			codexManualInput = '';
			codexDeviceCode = '';
			codexLoginDetail = '';
			codexLoginLogPath = '';
			modelError = '';
		} catch (caught) {
			modelError = caught instanceof Error ? caught.message : 'Could not logout Codex.';
		} finally {
			codexWorking = false;
		}
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

	async function saveCalendarConfig() {
		const next: CalendarConfig = {
			...calendar,
			reminder_upcoming_minutes: Math.max(1, Number(calendar.reminder_upcoming_minutes) || 1),
			reminder_starting_soon_minutes: Math.max(1, Number(calendar.reminder_starting_soon_minutes) || 1),
			urgent_interrupts_enabled: Boolean(calendar.urgent_interrupts_enabled),
			urgent_interrupt_persistent: Boolean(calendar.urgent_interrupt_persistent),
			scheduler_tick_seconds: Math.max(15, Number(calendar.scheduler_tick_seconds) || 60)
		};
		calendarSaving = true;
		try {
			const config = await updateCalendarConfig(next);
			calendar = config.calendar ?? next;
			calendarStatus = calendar.enabled
				? 'Calendar settings saved. Reminders use these values on the next scheduler tick.'
				: 'Calendar settings saved. Calendar is currently off.';
			calendarError = '';
		} catch (caught) {
			calendarError = caught instanceof Error ? caught.message : 'Could not save calendar settings.';
			calendarStatus = '';
		} finally {
			calendarSaving = false;
		}
	}

	async function saveEmailSettings() {
		const next: EmailConfig = {
			...email,
			provider: email.provider === 'gmail' ? 'gmail' : 'imap',
			email_address: email.email_address.trim(),
			account_label: email.account_label.trim(),
			imap_host: email.imap_host.trim(),
			imap_port: Math.max(1, Number(email.imap_port) || 993),
			username: email.username.trim(),
			gmail_oauth_mode: email.gmail_oauth_mode === 'web_secret' ? 'web_secret' : 'desktop_pkce',
			gmail_client_id: email.gmail_client_id.trim(),
			gmail_redirect_uri: email.gmail_redirect_uri.trim() || 'http://127.0.0.1:8787/email/gmail/callback',
			default_mailbox: email.default_mailbox.trim() || 'INBOX',
			max_preview_messages: Math.max(1, Math.min(200, Number(email.max_preview_messages) || 50))
		};
		emailSaving = true;
		try {
			const config = await updateEmailConfig({ ...next, password: emailPassword || undefined, gmail_client_secret: gmailClientSecret || undefined });
			email = config.email ?? next;
			emailPassword = '';
			gmailClientSecret = '';
			emailStatus = email.enabled ? 'Email settings saved. Inbox display will use this account later.' : 'Email settings saved. Email is currently off.';
			emailError = '';
			await refreshEmailPermissions();
			if (email.provider === 'gmail') await refreshGmailStatus();
		} catch (caught) {
			emailError = caught instanceof Error ? caught.message : 'Could not save email settings.';
			emailStatus = '';
		} finally {
			emailSaving = false;
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

	async function savePersonalityQuirks() {
		const likes = cleanQuirks(bitbuddyLikes);
		const dislikes = cleanQuirks(bitbuddyDislikes);
		personalitySaving = true;
		try {
			const config = await updatePersonalityConfig({ bitbuddy_likes: likes, bitbuddy_dislikes: dislikes });
			personalityDisplayName = config.personality?.display_name ?? personalityDisplayName;
			personalityId = config.personality?.id ?? personalityId;
			bitbuddyLikes = [...(config.personality?.bitbuddy_likes ?? likes)];
			bitbuddyDislikes = [...(config.personality?.bitbuddy_dislikes ?? dislikes)];
			personalityStatus = likes.length || dislikes.length
				? 'Personality quirks saved. BitBuddy will use them lightly in chat and autonomy.'
				: 'Personality quirks cleared.';
			personalityError = '';
		} catch (caught) {
			personalityError = caught instanceof Error ? caught.message : 'Could not save personality quirks.';
			personalityStatus = '';
		} finally {
			personalitySaving = false;
		}
	}

	async function saveChatConfig() {
		const next: ChatConfig = {
			...chatConfig,
			max_tool_rounds: Math.max(1, Number(chatConfig.max_tool_rounds) || 99)
		};

		chatConfigSaving = true;
		try {
			const config = await updateChatConfig(next);
			chatConfig = config.chat ?? next;
			chatConfigStatus = 'Chat settings saved. New chat turns will use this tool-call budget.';
			chatConfigError = '';
		} catch (caught) {
			chatConfigError = caught instanceof Error ? caught.message : 'Could not save chat settings.';
			chatConfigStatus = '';
		} finally {
			chatConfigSaving = false;
		}
	}

	async function saveModelRuntime() {
		if (addProviderOpen) {
			modelError = 'Save the provider card, or cancel the add form before saving model settings.';
			modelStatus = '';
			return;
		}
		const providers = (modelRuntime.providers ?? []).filter((provider) => provider.type !== 'none');
		const active = modelRuntime.active_provider && providers.some((provider) => providerKey(provider) === modelRuntime.active_provider)
			? modelRuntime.active_provider
			: providerKey(providers[0]);
		const activeProvider = providers.find((provider) => providerKey(provider) === active) ?? { type: 'none', url: '', model: '' };
		const next: ModelRuntimeConfig = {
			provider: cleanProvider(activeProvider),
			providers: providers.map(cleanProvider),
			active_provider: active,
			project_scan_interval_seconds: Math.max(0, Number(modelRuntime.project_scan_interval_seconds) || 0)
		};

		for (const provider of next.providers ?? []) {
			if (provider.type !== 'none' && !provider.url) {
				modelError = `${providerLabel(provider.type)} provider URL is required.`;
				modelStatus = '';
				return;
			}
			if (isCloudProvider(provider.type) && !provider.has_api_key && !provider.api_key) {
				modelError = `${providerLabel(provider.type)} API key is required.`;
				modelStatus = '';
				return;
			}
		}

		modelSaving = true;
		try {
			const config = await updateModelRuntimeConfig(next);
			const savedProviders = configuredProviders(config.providers, config.provider);
			modelRuntime = {
				provider: config.provider,
				providers: savedProviders,
				active_provider: config.active_provider ?? config.provider.key ?? config.provider.type,
				project_scan_interval_seconds: config.runtime?.project_scan_interval_seconds ?? next.project_scan_interval_seconds
			};
			providerModels = [];
			providerContext = null;
			pendingAddedProviderKey = '';
			addProviderOpen = false;
			editingProviderKey = '';
			beginAddProvider(firstAddableProviderType(savedProviders), { open: false });
			void refreshContextUsage('', { providerOnly: true });
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

	async function loadDraftProviderModels(silent = false) {
		modelLoadingModels = true;
		try {
			providerModels = await getProviderModels({ ...draftProvider, api_key: draftProviderKey });
			if (providerModels.length && (!draftProvider.model || (draftProvider.type === 'codex' && !providerModels.includes(draftProvider.model)))) {
				draftProvider.model = providerModels[0];
			}
			if (!silent) modelStatus = providerModels.length ? `Loaded ${providerModels.length} model(s) from provider.` : 'Provider did not report any models.';
			modelError = '';
		} catch (caught) {
			providerModels = [];
			if (!silent) {
				modelError = caught instanceof Error ? caught.message : 'Could not list provider models.';
				modelStatus = '';
			}
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
	<section class="settings-panel" aria-label="Settings">
		<header class="settings-header">
			<div class="title-mark" aria-hidden="true"><GearSixIcon size={30} weight="duotone" /></div>
			<div class="title-copy">
				<p class="eyebrow">Configuration</p>
				<h1>Settings</h1>
				<p>Appearance, model runtime, autonomy, and desktop control.</p>
			</div>
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

			<div class="settings-list runtime-settings-list">
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
					class:open={personalityQuirksOpen}
					onclick={() => (personalityQuirksOpen = !personalityQuirksOpen)}
					aria-expanded={personalityQuirksOpen}
				>
					<span>
						Personality quirks
						<small>Optional likes and dislikes that make BitBuddy feel less generic</small>
					</span>
					<div class="row-meta">
						{#if personalityDisplayName}<span class="badge">{personalityDisplayName}</span>{/if}
						<span class="badge">{cleanQuirks(bitbuddyLikes).length + cleanQuirks(bitbuddyDislikes).length} quirks</span>
						<span class="row-caret"><CaretRightIcon size={18} /></span>
					</div>
				</button>

				{#if personalityQuirksOpen}
					<div class="collapsible-panel">
						<p class="section-intro">Give BitBuddy things they are drawn to and things they tend to avoid. These are light flavor seeds, not hard rules, and you can add as many as you want.</p>

						{#if personalityError}
							<div class="inline-error">{personalityError}</div>
						{/if}

						<div class="context-panel quirk-panel">
							<div class="mock-item quirk-heading">
								<span>
									Current personality
									<small>{personalityDisplayName || personalityId || 'Selected personality'} · used lightly in chat and autonomy</small>
								</span>
							</div>
							{#if bitbuddyLikes.length === 0 && bitbuddyDislikes.length === 0}
								<div class="mock-item empty-quirks">
									<span>No custom quirks yet<small>Add a like or dislike to make BitBuddy feel more specific.</small></span>
								</div>
							{/if}
							{#each bitbuddyLikes as _like, index}
								<div class="mock-item field-row quirk-row">
									<span>BitBuddy likes<small>Curiosity or flavor seed</small></span>
									<input bind:value={bitbuddyLikes[index]} placeholder={index === 0 ? 'retro computers' : 'weird UI details'} disabled={contextLoading || personalitySaving} />
									<button class="ghost danger" onclick={() => removeQuirk('like', index)} disabled={contextLoading || personalitySaving}>Remove</button>
								</div>
							{/each}
							{#each bitbuddyDislikes as _dislike, index}
								<div class="mock-item field-row quirk-row">
									<span>BitBuddy dislikes<small>Light aversion or quality preference</small></span>
									<input bind:value={bitbuddyDislikes[index]} placeholder={index === 0 ? 'corporate AI tone' : 'soulless dashboards'} disabled={contextLoading || personalitySaving} />
									<button class="ghost danger" onclick={() => removeQuirk('dislike', index)} disabled={contextLoading || personalitySaving}>Remove</button>
								</div>
							{/each}
						</div>

						<div class="context-actions">
							<div class="quirk-add">
								<button class="secondary-action add-provider-button" onclick={() => (quirkAddOpen = !quirkAddOpen)} disabled={contextLoading || personalitySaving}>+ Add quirk</button>
								{#if quirkAddOpen}
									<div class="quirk-add-menu">
										<button onclick={() => addQuirk('like')}>Like</button>
										<button onclick={() => addQuirk('dislike')}>Dislike</button>
									</div>
								{/if}
							</div>
							<button class="primary-action" onclick={savePersonalityQuirks} disabled={contextLoading || personalitySaving}>
								{personalitySaving ? 'Saving...' : 'Save personality quirks'}
							</button>
						</div>

						{#if personalityStatus}
							<p class="save-status">{personalityStatus}</p>
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
						<small>Typing speed, response display, and tool-call budget</small>
					</span>
					<div class="row-meta">
						<span class="badge">{chatBehavior.replyAnimation}</span>
						<span class="badge">{chatConfig.max_tool_rounds} tools</span>
						<span class="row-caret"><CaretRightIcon size={18} /></span>
					</div>
				</button>

				{#if chatBehaviorOpen}
					<div class="collapsible-panel">
						<p class="section-intro">Choose how assistant replies appear while they stream into chat, and cap how many tool calls a single chat turn may run.</p>

						{#if chatConfigError}
							<div class="inline-error">{chatConfigError}</div>
						{/if}

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

						<div class="context-panel compact-context-panel">
							<label class="mock-item field-row">
								<span>
									Tool call budget
									<small>Maximum tool calls BitBuddy can run in one chat turn; lower is faster, higher allows deeper multi-step work</small>
								</span>
								<input type="number" min="1" bind:value={chatConfig.max_tool_rounds} disabled={contextLoading || chatConfigSaving} />
							</label>
						</div>

						<div class="context-actions">
							<button class="primary-action" onclick={saveChatConfig} disabled={contextLoading || chatConfigSaving}>
								{chatConfigSaving ? 'Saving...' : 'Save chat settings'}
							</button>
						</div>

						{#if chatConfigStatus}
							<p class="save-status">{chatConfigStatus}</p>
						{/if}
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
						<p class="section-intro">Configure local providers, cloud API providers, and ChatGPT-authorized Codex. Only configured providers appear in the active list.</p>

						{#if modelError}
							<div class="inline-error">{modelError}</div>
						{/if}

						<div class="context-panel provider-runtime-panel">
							<div class="provider-list">
								{#each modelRuntime.providers ?? [] as provider (providerKey(provider))}
									<div class="provider-card" class:active={modelRuntime.active_provider === providerKey(provider)} class:editing={editingProviderKey === providerKey(provider)} class:unsaved={pendingAddedProviderKey === providerKey(provider)}>
										<div class="mock-item provider-row">
											<span>
												<strong>{providerLabel(provider.type)}</strong>
												<small>{provider.model || 'No model set'}{provider.type !== 'codex' ? ` · ${provider.url}` : ' · ChatGPT authorization'}</small>
												{#if isCloudProvider(provider.type)}<small>{provider.has_api_key ? 'API key saved' : 'API key missing'}</small>{/if}
												{#if provider.type === 'codex'}<small>{codexLoggedIn ? 'Codex authorized for BitBuddy' : 'Codex authorization needed'}</small>{/if}
											</span>
											<div class="provider-actions">
												{#if modelRuntime.active_provider === providerKey(provider)}<span class="badge">Active</span>{/if}
												{#if pendingAddedProviderKey === providerKey(provider)}<span class="badge warning-badge">Unsaved</span>{/if}
												{#if editingProviderKey === providerKey(provider)}
													<button class="primary-action" onclick={saveProviderEdit} disabled={contextLoading}>Save provider</button>
													<button class="secondary-action" onclick={cancelProviderEdit} disabled={contextLoading}>Cancel</button>
												{:else}
													<button class="secondary-action" onclick={() => selectActiveProvider(provider)} disabled={contextLoading || Boolean(pendingAddedProviderKey && pendingAddedProviderKey !== providerKey(provider)) || modelRuntime.active_provider === providerKey(provider)}>Make active</button>
													<button class="secondary-action" onclick={() => editProvider(provider)} disabled={contextLoading || Boolean(pendingAddedProviderKey && pendingAddedProviderKey !== providerKey(provider))}>Edit</button>
												{/if}
												<button class="ghost danger" onclick={() => removeProvider(provider)} disabled={contextLoading}>Remove</button>
											</div>
										</div>
										{#if editingProviderKey === providerKey(provider)}
											<div class="provider-edit-panel">
												{#if !isCodexProvider(draftProvider.type)}
													<label class="mock-item field-row">
														<span>Provider URL<small>Endpoint for this provider</small></span>
														<input bind:value={draftProvider.url} placeholder="http://127.0.0.1:11434" disabled={contextLoading} />
													</label>
												{/if}
												<label class="mock-item field-row">
													<span>Model<small>{modelLoadingModels ? 'Loading models from provider...' : providerModels.length ? 'Models discovered from provider' : 'Provider did not report models yet'}</small></span>
													<div class="select-field"><SelectMenu value={draftProvider.model} options={providerModelOptions()} placeholder="Select model" ariaLabel="Provider model" onChange={setDraftProviderModel} disabled={contextLoading || modelLoadingModels || providerModelOptions().length === 0} /></div>
												</label>
												{#if isCloudProvider(draftProvider.type)}
													<label class="mock-item field-row">
														<span>API key<small>{draftProvider.has_api_key ? 'Leave blank to keep the saved key' : 'Stored outside config.yaml'} · <a href={providerKeyUrl(draftProvider.type)} target="_blank" rel="noreferrer">Get API key</a></small></span>
														<input type="password" bind:value={draftProviderKey} placeholder="sk-..." disabled={contextLoading} />
													</label>
												{/if}
												{#if isCodexProvider(draftProvider.type)}
													<div class="mock-item field-row codex-login-row">
														<span>
															Codex authorization
															<small>{codexStatus || 'Authorize BitBuddy with your ChatGPT/Codex account.'}</small>
															{#if codexAuthUrl}<small><a href={codexAuthUrl} target="_blank" rel="noreferrer">Open ChatGPT authorization</a></small>{/if}
															{#if codexCallbackMode === 'manual'}<small>After approving, paste the final callback URL or code below.</small>{/if}
														</span>
														<div class="provider-actions">
															<button class="secondary-action" onclick={connectCodex} disabled={contextLoading || codexWorking}>{codexWorking ? 'Working...' : codexLoggedIn ? 'Reconnect Codex' : 'Connect Codex'}</button>
															<button class="secondary-action" onclick={refreshCodexStatus} disabled={contextLoading || codexWorking}>Check status</button>
															<button class="ghost danger" onclick={disconnectCodex} disabled={contextLoading || codexWorking || !codexLoggedIn}>Disconnect</button>
														</div>
													</div>
													{#if codexCallbackMode === 'manual'}
														<label class="mock-item field-row">
															<span>Finish authorization<small>Paste the final browser URL, query string, or authorization code</small></span>
															<input bind:value={codexManualInput} placeholder="http://localhost:1455/auth/callback?code=...&state=..." disabled={contextLoading || codexWorking} />
														</label>
														<div class="mock-item provider-manual-actions"><button class="secondary-action" onclick={finishCodexLogin} disabled={contextLoading || codexWorking || !codexManualInput.trim()}>Finish Codex authorization</button></div>
													{/if}
												{/if}
											</div>
										{/if}
									</div>
								{:else}
									<div class="empty-state">No model providers configured. Add one below.</div>
								{/each}
							</div>
							{#if addProviderOpen && !editingProviderKey}
								<label class="mock-item field-row">
									<span>
										New provider
										<small>Choose a type, fill details, then press + below to create a card</small>
									</span>
									<div class="select-field"><SelectMenu value={draftProvider.type} options={providerOptions} ariaLabel="Provider type" onChange={setDraftProviderType} disabled={contextLoading} /></div>
								</label>
								{#if !isCodexProvider(draftProvider.type)}
									<label class="mock-item field-row">
										<span>
											Provider URL
											<small>Default endpoint is filled for each provider type</small>
										</span>
										<input bind:value={draftProvider.url} placeholder="http://127.0.0.1:11434" disabled={contextLoading} />
									</label>
								{/if}
								<label class="mock-item field-row">
									<span>
										Model
										<small>{modelLoadingModels ? 'Loading models from provider...' : providerModels.length ? 'Models discovered from provider' : 'Provider did not report models yet'}</small>
									</span>
									<div class="select-field"><SelectMenu value={draftProvider.model} options={providerModelOptions()} placeholder="Select model" ariaLabel="Provider model" onChange={setDraftProviderModel} disabled={contextLoading || modelLoadingModels || providerModelOptions().length === 0} /></div>
								</label>
								{#if isCloudProvider(draftProvider.type)}
									<label class="mock-item field-row">
										<span>
											API key
											<small>{draftProvider.has_api_key ? 'Leave blank to keep the saved key' : 'Stored outside config.yaml'} · <a href={providerKeyUrl(draftProvider.type)} target="_blank" rel="noreferrer">Get API key</a></small>
										</span>
										<input type="password" bind:value={draftProviderKey} placeholder="sk-..." disabled={contextLoading} />
									</label>
								{/if}
								{#if isCodexProvider(draftProvider.type)}
									<div class="mock-item field-row codex-login-row">
										<span>
											Codex authorization
											<small>{codexStatus || 'Authorize BitBuddy with your ChatGPT/Codex account.'}</small>
											{#if codexAuthUrl}<small><a href={codexAuthUrl} target="_blank" rel="noreferrer">Open ChatGPT authorization</a></small>{/if}
											{#if codexCallbackMode === 'manual'}<small>After approving, paste the final callback URL or code below.</small>{/if}
										</span>
										<div class="provider-actions">
											<button class="secondary-action" onclick={connectCodex} disabled={contextLoading || codexWorking}>{codexWorking ? 'Working...' : codexLoggedIn ? 'Reconnect Codex' : 'Connect Codex'}</button>
											<button class="secondary-action" onclick={refreshCodexStatus} disabled={contextLoading || codexWorking}>Check status</button>
											<button class="ghost danger" onclick={disconnectCodex} disabled={contextLoading || codexWorking || !codexLoggedIn}>Disconnect</button>
										</div>
									</div>
									{#if codexCallbackMode === 'manual'}
										<label class="mock-item field-row">
											<span>Finish authorization<small>Paste the final browser URL, query string, or authorization code</small></span>
											<input bind:value={codexManualInput} placeholder="http://localhost:1455/auth/callback?code=...&state=..." disabled={contextLoading || codexWorking} />
										</label>
										<div class="mock-item provider-manual-actions"><button class="secondary-action" onclick={finishCodexLogin} disabled={contextLoading || codexWorking || !codexManualInput.trim()}>Finish Codex authorization</button></div>
									{/if}
								{/if}
							{/if}
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

						<div class="context-actions model-actions">
							<button class={addProviderOpen ? 'primary-action' : 'secondary-action add-provider-button'} onclick={addProvider} disabled={contextLoading || Boolean(editingProviderKey) || Boolean(pendingAddedProviderKey)} title={pendingAddedProviderKey ? 'Save model settings or remove the unsaved provider first' : editingProviderKey ? 'Finish or cancel editing before adding another provider' : addProviderOpen ? 'Save provider card' : 'Show new provider form'}>
								{addProviderOpen ? 'Save' : '+ Add provider'}
							</button>
							{#if addProviderOpen}
								<button class="cancel-add-action" onclick={cancelAddProvider} disabled={contextLoading}>Cancel</button>
							{/if}
							<span class="action-spacer"></span>
							<button class="secondary-action" onclick={checkProvider} disabled={contextLoading || modelChecking || modelRuntime.provider.type === 'none'}>
								{modelChecking ? 'Checking...' : 'Check connection'}
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
							<div class="mock-item toggle-row">
								<span>
									Enable MCP discovery
									<small>External MCP tools appear in chat only when this is on</small>
								</span>
								<Checkbox bind:checked={mcp.enabled} ariaLabel="Enable MCP discovery" />
							</div>
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
							<div class="mock-item toggle-row">
								<span>
									Enable autonomy
									<small>Master switch for idle autonomous behavior</small>
								</span>
								<Checkbox bind:checked={autonomy.enabled} ariaLabel="Enable autonomy" />
							</div>
							<div class="mock-item toggle-row">
								<span>
									Run after memory consolidation
									<small>Schedule autonomy after private idle memory review finishes</small>
								</span>
								<Checkbox bind:checked={autonomy.run_after_idle_consolidation} ariaLabel="Run after memory consolidation" />
							</div>
							<label class="mock-item field-row">
								<span>
									Idle delay
									<small>Seconds before an idle autonomy cycle starts</small>
								</span>
								<input type="number" min="0" bind:value={autonomy.idle_delay_seconds} />
							</label>
							<div class="mock-item toggle-row">
								<span>
									Repeat idle cycles
									<small>Allow another cycle while you remain away</small>
								</span>
								<Checkbox bind:checked={autonomy.repeat_idle_cycles} ariaLabel="Repeat idle cycles" />
							</div>
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
							<div class="mock-item toggle-row">
								<span>
									Web search
									<small>Allow safe web curiosity through the local search backend</small>
								</span>
								<Checkbox bind:checked={autonomy.web_search.enabled} ariaLabel="Web search" />
							</div>
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
							<div class="mock-item toggle-row">
								<span>
									Enable dreaming
									<small>Allow NightEligible, MiniDream cleanup, and Sleep lifecycle states</small>
								</span>
								<Checkbox bind:checked={dreaming.enabled} ariaLabel="Enable dreaming" />
							</div>
							<div class="mock-item toggle-row">
								<span>
									Quiet mode after bedtime
									<small>Reduce low-priority autonomy while the user may be winding down</small>
								</span>
								<Checkbox bind:checked={dreaming.quiet_mode_after_bedtime} ariaLabel="Quiet mode after bedtime" />
							</div>
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
							<div class="mock-item toggle-row">
								<span>
									SelfNote injection
									<small>Experimental: selectively inject a few relevant SelfNotes into prompts</small>
								</span>
								<Checkbox bind:checked={dreaming.self_note_injection_enabled} ariaLabel="SelfNote injection" />
							</div>
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

		<section class="settings-section">
			<div class="section-header">
				<h2>Calendar</h2>
			</div>

			<div class="settings-list">
				<button
					class="mock-item settings-row"
					class:open={calendarOpen}
					onclick={() => (calendarOpen = !calendarOpen)}
					aria-expanded={calendarOpen}
				>
					<span>
						Calendar awareness
						<small>Local schedule, reminders, and conflict warnings</small>
					</span>
					<div class="row-meta">
						<span class="badge">{calendar.enabled ? 'Enabled' : 'Off'}</span>
						<span class="badge">{Math.round(Number(calendar.reminder_starting_soon_minutes) || 0)}m soon</span>
						<span class="row-caret"><CaretRightIcon size={18} /></span>
					</div>
				</button>

				{#if calendarOpen}
					<div class="collapsible-panel">
						<p class="section-intro">BitBuddy keeps a local-first calendar and can remind you about upcoming events. Use Calendar access below to control what it may do on its own.</p>

						{#if calendarError}
							<div class="inline-error">{calendarError}</div>
						{/if}

						<div class="context-panel">
							<div class="mock-item toggle-row">
								<span>
									Enable calendar
									<small>Master switch for calendar reading and reminders</small>
								</span>
								<Checkbox bind:checked={calendar.enabled} ariaLabel="Enable calendar" />
							</div>
							<label class="mock-item field-row">
								<span>
									Upcoming reminder lead
									<small>Minutes before an event to send the first heads-up</small>
								</span>
								<input type="number" min="1" bind:value={calendar.reminder_upcoming_minutes} disabled={!calendar.enabled} />
							</label>
							<label class="mock-item field-row">
								<span>
									Starting-soon lead
									<small>Minutes before an event for the "starting soon" reminder</small>
								</span>
								<input type="number" min="1" bind:value={calendar.reminder_starting_soon_minutes} disabled={!calendar.enabled} />
							</label>
							<div class="mock-item toggle-row">
								<span>
									Urgent calendar interrupts
									<small>Starting-soon reminders appear as urgent UI alerts without waiting for autonomy</small>
								</span>
								<Checkbox bind:checked={calendar.urgent_interrupts_enabled} disabled={!calendar.enabled} ariaLabel="Urgent calendar interrupts" />
							</div>
							<div class="mock-item toggle-row">
								<span>
									Persistent urgent reminders
									<small>Urgent calendar reminders stay visible until dismissed or opened</small>
								</span>
								<Checkbox bind:checked={calendar.urgent_interrupt_persistent} disabled={!calendar.enabled || !calendar.urgent_interrupts_enabled} ariaLabel="Persistent urgent reminders" />
							</div>
							<div class="mock-item toggle-row">
								<span>
									Conflict warnings
									<small>Warn when two events overlap</small>
								</span>
								<Checkbox bind:checked={calendar.conflict_warnings_enabled} disabled={!calendar.enabled} ariaLabel="Conflict warnings" />
							</div>
							<div class="mock-item toggle-row">
								<span>
									Chat nudges
									<small>Post calendar reminders directly into chat as well as the notification overlay. Off means notifications only.</small>
								</span>
								<Checkbox bind:checked={calendar.chat_nudges_enabled} disabled={!calendar.enabled} ariaLabel="Chat nudges" />
							</div>
							<label class="mock-item field-row">
								<span>
									Scheduler tick
									<small>How often BitBuddy checks for due reminders, in seconds (minimum 15)</small>
								</span>
								<input type="number" min="15" bind:value={calendar.scheduler_tick_seconds} disabled={!calendar.enabled} />
							</label>
							<div class="mock-item toggle-row">
								<span>
									Show holidays
									<small>Overlay public holidays for your country (read-only) onto the calendar</small>
								</span>
								<Checkbox bind:checked={calendar.holidays_enabled} disabled={!calendar.enabled} ariaLabel="Show holidays" />
							</div>
							<label class="mock-item field-row">
								<span>
									Holidays country
									<small>ISO country code (e.g. US, GB, DE). Leave blank to use your locale ({userContext.locale || 'en-US'})</small>
								</span>
								<input
									placeholder={(userContext.locale.split(/[-_]/)[1] || 'US').toUpperCase()}
									maxlength="2"
									bind:value={calendar.holidays_country}
									disabled={!calendar.enabled || !calendar.holidays_enabled}
									oninput={(e) => (calendar.holidays_country = e.currentTarget.value.toUpperCase())}
								/>
							</label>
						</div>

						<div class="context-actions">
							<button class="primary-action" onclick={saveCalendarConfig} disabled={calendarSaving || contextLoading}>
								{calendarSaving ? 'Saving...' : 'Save calendar settings'}
							</button>
						</div>

						{#if calendarStatus}
							<p class="save-status">{calendarStatus}</p>
						{/if}

						<div class="calendar-access">
							<div class="access-heading">Calendar access</div>
							<p class="section-intro">Control what BitBuddy may do with your calendar on its own. You can always manage events yourself on the Calendar page.</p>
							{#if calendarPermError}
								<div class="inline-error">{calendarPermError}</div>
							{/if}
							{#if calendarPermissions}
								<div class="scope-list">
									{#each calendarScopes as scope}
										<div class="scope-row">
											<span class="scope-label">{SCOPE_LABELS[scope]}</span>
											<div class="scope-states">
												{#each SCOPE_STATES as state}
													<button
														type="button"
														class="scope-state {state}"
														class:active={calendarPermissions[scope] === state}
														onclick={() => setScope(scope, state)}
													>
														{state === 'ask' ? 'Ask' : state === 'granted' ? 'Allow' : 'Deny'}
													</button>
												{/each}
											</div>
										</div>
									{/each}
								</div>
							{/if}
						</div>
					</div>
				{/if}
			</div>
		</section>

		<section class="settings-section">
			<div class="section-header">
				<h2>Email</h2>
			</div>

			<div class="settings-list">
				<button class="mock-item settings-row" class:open={emailOpen} onclick={() => (emailOpen = !emailOpen)} aria-expanded={emailOpen}>
					<span>
						Email awareness
						<small>Generic IMAP account, read/search awareness, and safe permission gates</small>
					</span>
					<div class="row-meta">
						<span class="badge">{email.enabled ? 'Enabled' : 'Off'}</span>
						<span class="badge">{email.email_address || 'IMAP'}</span>
						<span class="row-caret"><CaretRightIcon size={18} /></span>
					</div>
				</button>

				{#if emailOpen}
					<div class="collapsible-panel">
						<p class="section-intro">BitBuddy can become email-aware through local IMAP or self-hosted Gmail OAuth. Credentials and tokens stay on this machine. Gmail can read/search mail and, with explicit local permission, perform approved mailbox actions. Sending and other mutating actions should remain behind explicit permission gates.</p>
						{#if emailError}<div class="inline-error">{emailError}</div>{/if}

						<div class="context-panel">
							<div class="mock-item toggle-row"><span>Enable email<small>Master switch for email awareness and inbox access</small></span><Checkbox bind:checked={email.enabled} ariaLabel="Enable email" /></div>
							<div class="mock-item field-row"><span>Provider<small>Use generic IMAP or Google's Gmail API</small></span><div class="select-field"><SelectMenu value={email.provider} options={emailProviderOptions} ariaLabel="Email provider" disabled={!email.enabled} onChange={(value) => (email.provider = value as EmailConfig['provider'])} /></div></div>
							<label class="mock-item field-row"><span>Email address<small>The account BitBuddy should know about</small></span><input bind:value={email.email_address} placeholder="you@example.com" disabled={!email.enabled} /></label>
							<label class="mock-item field-row"><span>Account label<small>A local display name, such as Personal or Work</small></span><input bind:value={email.account_label} placeholder="Personal" disabled={!email.enabled} /></label>
							{#if email.provider === 'imap'}
								<label class="mock-item field-row"><span>IMAP host<small>Your provider's incoming mail server</small></span><input bind:value={email.imap_host} placeholder="imap.example.com" disabled={!email.enabled} /></label>
								<label class="mock-item field-row"><span>IMAP port<small>Usually 993 for SSL</small></span><input type="number" min="1" bind:value={email.imap_port} disabled={!email.enabled} /></label>
								<label class="mock-item field-row"><span>Security<small>Connection security for IMAP</small></span><select bind:value={email.imap_security} disabled={!email.enabled}><option value="ssl">SSL</option><option value="starttls">STARTTLS</option><option value="none">None</option></select></label>
								<label class="mock-item field-row"><span>Username<small>Usually the full email address</small></span><input bind:value={email.username} placeholder="you@example.com" disabled={!email.enabled} /></label>
								<label class="mock-item field-row"><span>Password / app password<small>{email.has_password ? 'Saved locally. Enter a new value to replace it.' : 'Stored as a local credential reference, not in config.'}</small></span><input type="password" bind:value={emailPassword} placeholder={email.has_password ? 'Saved' : 'App password'} disabled={!email.enabled} /></label>
							{:else}
								<div class="setup-card">
									<div>
										<p class="eyebrow">Self-hosted Gmail setup</p>
										<h3>Use your own Google Desktop OAuth client</h3>
										<p>BitBuddy ships no Google OAuth credentials. Create your own Desktop OAuth client, then store its client ID and client secret locally in BitBuddy secrets.</p>
									</div>
									<ol class="setup-steps">
										<li><span>Use a Google OAuth client configured as <strong>Desktop app</strong>.</span></li>
										<li><span>Enable the Gmail API and add Gmail scope <code>https://www.googleapis.com/auth/gmail.modify</code>.</span></li>
										<li><span>If the OAuth app is still in testing mode, add your Google account as a test user.</span></li>
										<li><span>Paste the Desktop app client ID and client secret below, save settings, then connect Gmail.</span></li>
									</ol>
								</div>
								<label class="mock-item field-row"><span>Google OAuth client ID<small>{email.gmail_oauth_mode === 'web_secret' ? 'Legacy Web Application OAuth client' : 'Recommended Desktop app OAuth client'}</small></span><input bind:value={email.gmail_client_id} placeholder="...apps.googleusercontent.com" disabled={!email.enabled} /></label>
								<label class="mock-item field-row"><span>Google OAuth client secret<small>{email.has_gmail_client_secret ? 'Saved locally. Enter a new value to replace it, or clear it below.' : email.gmail_oauth_mode === 'web_secret' ? 'Required for Web Application OAuth. Stored locally outside config.' : 'Use the client_secret from your Google Desktop OAuth credentials JSON. Stored locally outside config.'}</small></span><input type="password" bind:value={gmailClientSecret} placeholder={email.has_gmail_client_secret ? 'Saved' : 'Client secret'} disabled={!email.enabled} /></label>
								{#if email.has_gmail_client_secret}
									<div class="mock-item status-row"><span>Saved client secret<small>Stored locally in BitBuddy secrets, not in config. Clear it if you changed Google OAuth clients.</small></span><div class="provider-actions"><button class="secondary-action" onclick={removeGmailClientSecret} disabled={!email.enabled || gmailWorking}>Clear secret</button></div></div>
								{/if}
								<div class="mock-item status-row"><span>Gmail connection<small>{gmailStatus?.message ?? (email.gmail_connected ? 'Connected. Reconnect if you added Trash access after first setup.' : 'Not connected')}</small></span><div class="provider-actions"><button class="secondary-action" onclick={() => connectGmail(Boolean(email.gmail_connected || gmailStatus?.connected))} disabled={!email.enabled || gmailWorking || emailSaving}>{gmailWorking ? 'Working...' : email.gmail_connected || gmailStatus?.connected ? 'Reconnect Gmail' : 'Connect Gmail'}</button><button class="secondary-action" onclick={refreshGmailStatus} disabled={!email.enabled || gmailWorking}>Check status</button><button class="ghost danger" onclick={disconnectGmail} disabled={!email.enabled || gmailWorking || !(email.gmail_connected || gmailStatus?.connected)}>Disconnect</button></div></div>

								<button class="mock-item settings-row mini-row" class:open={emailAdvancedOpen} onclick={() => (emailAdvancedOpen = !emailAdvancedOpen)} aria-expanded={emailAdvancedOpen}>
									<span>Advanced OAuth<small>Redirect URI and inbox tuning</small></span>
									<span class="row-caret"><CaretRightIcon size={18} /></span>
								</button>
								{#if emailAdvancedOpen}
									<div class="mock-item field-row"><span>OAuth mode<small>Desktop app uses PKCE and can send your saved local client secret when Google requires it. Web app is a self-hosted legacy fallback.</small></span><div class="select-field"><SelectMenu value={email.gmail_oauth_mode || 'desktop_pkce'} options={[{ value: 'desktop_pkce', label: 'Desktop app (recommended)', description: 'PKCE plus optional local secret' }, { value: 'web_secret', label: 'Web app (legacy)', description: 'Requires client secret and redirect URI' }]} ariaLabel="Gmail OAuth mode" disabled={!email.enabled} onChange={(value) => (email.gmail_oauth_mode = value as EmailConfig['gmail_oauth_mode'])} /></div></div>
									<label class="mock-item field-row"><span>Redirect URI<small>{email.gmail_oauth_mode === 'web_secret' ? 'Add this exact URI to your Google Web Application OAuth client.' : 'Local 127.0.0.1 loopback callback used by BitBuddy during Google authorization.'}</small></span><input bind:value={email.gmail_redirect_uri} placeholder="http://127.0.0.1:8787/email/gmail/callback" disabled={!email.enabled} /></label>
									<label class="mock-item field-row"><span>Default mailbox<small>The inbox folder to open first</small></span><input bind:value={email.default_mailbox} placeholder="INBOX" disabled={!email.enabled} /></label>
									<label class="mock-item field-row"><span>Preview message limit<small>Maximum messages to preview in lightweight inbox views</small></span><input type="number" min="1" max="200" bind:value={email.max_preview_messages} disabled={!email.enabled} /></label>
								{/if}

								<button class="mock-item settings-row mini-row" class:open={emailTroubleshootingOpen} onclick={() => (emailTroubleshootingOpen = !emailTroubleshootingOpen)} aria-expanded={emailTroubleshootingOpen}>
									<span>Troubleshooting<small>Fallbacks for broken browser profiles or OAuth callback issues</small></span>
									<span class="row-caret"><CaretRightIcon size={18} /></span>
								</button>
								{#if emailTroubleshootingOpen}
									<div class="mock-item status-row"><span>OAuth status<small>{gmailTroubleshootingHint(gmailStatus)}</small></span><div class="provider-actions"><button class="secondary-action" onclick={refreshGmailStatus} disabled={!email.enabled || gmailWorking}>Refresh</button></div></div>
									<div class="mock-item status-row"><span>Browser extensions can break OAuth<small>URL cleaners such as ClearURLs, redirect cleaners, tracking-param strippers, and container extensions can remove Google OAuth parameters before BitBuddy receives a callback. Disable them or whitelist accounts.google.com, oauth2.googleapis.com, google.com, 127.0.0.1, and localhost.</small></span></div>
									<div class="mock-item status-row"><span>Google says "Something went wrong"<small>This usually happens before BitBuddy receives a callback. Check URL-cleaning extensions first, then VPN/IP protection, Google OAuth test-user access, Gmail API enablement, and the Gmail modify scope in Data Access.</small></span></div>
									<div class="mock-item status-row"><span>Clean browser OAuth<small>Opens Google auth in a disposable Chromium profile when available, otherwise a hardened Firefox profile. If this works, your normal browser profile or extension setup is the problem.</small></span><div class="provider-actions"><button class="secondary-action" onclick={connectGmailCleanBrowser} disabled={!email.enabled || gmailWorking || emailSaving}>Open Clean Browser</button></div></div>
									<label class="mock-item field-row"><span>Finish in another browser<small>Paste the final callback URL if the browser reaches BitBuddy but cannot complete automatically.</small></span><input bind:value={gmailManualInput} placeholder="http://127.0.0.1:8787/email/gmail/callback?code=...&state=..." disabled={!email.enabled || gmailWorking} /></label>
									<div class="mock-item provider-manual-actions"><button class="secondary-action" onclick={finishGmailLogin} disabled={!email.enabled || gmailWorking || !gmailManualInput.trim()}>Finish Gmail authorization</button></div>
								{/if}
							{/if}
							{#if email.provider !== 'gmail'}
								<label class="mock-item field-row"><span>Default mailbox<small>The inbox folder to open first</small></span><input bind:value={email.default_mailbox} placeholder="INBOX" disabled={!email.enabled} /></label>
								<label class="mock-item field-row"><span>Preview message limit<small>Maximum messages to preview in lightweight inbox views</small></span><input type="number" min="1" max="200" bind:value={email.max_preview_messages} disabled={!email.enabled} /></label>
							{/if}
						</div>

						<div class="context-actions"><button class="primary-action" onclick={saveEmailSettings} disabled={emailSaving || contextLoading}>{emailSaving ? 'Saving...' : 'Save email settings'}</button></div>
						{#if emailStatus}<p class="save-status">{emailStatus}</p>{/if}

						<div class="calendar-access email-access">
							<div class="access-heading">Email access</div>
							<p class="section-intro">Control what BitBuddy may do with email. Trash access only moves messages to Trash; it does not permanently delete mail.</p>
							{#if emailPermError}<div class="inline-error">{emailPermError}</div>{/if}
							{#if emailPermissions}
								<div class="scope-list">
									{#each emailScopes as scope}
										<div class="scope-row">
											<span class="scope-label">{EMAIL_SCOPE_LABELS[scope] ?? scope}</span>
											<div class="scope-states">
												{#each SCOPE_STATES as state}
													<button type="button" class="scope-state {state}" class:active={emailPermissions[scope] === state} onclick={() => setEmailScope(scope, state)}>{state === 'ask' ? 'Ask' : state === 'granted' ? 'Allow' : 'Deny'}</button>
												{/each}
											</div>
										</div>
									{/each}
								</div>
							{/if}
						</div>
					</div>
				{/if}
			</div>
		</section>
		</div>
	</section>
</div>

<Overlay open={Boolean(providerPendingRemoval)} label="Remove provider" onClose={cancelRemoveProvider}>
	<div class="confirm-dialog">
		<p class="eyebrow">Remove Provider</p>
		<h2>Remove {providerPendingRemoval ? providerLabel(providerPendingRemoval.type) : 'provider'}?</h2>
		<p>This removes the provider card from Settings. Save model settings afterward to apply the change.</p>
		<div class="confirm-actions">
			<button class="secondary-action" onclick={cancelRemoveProvider}>Cancel</button>
			<button class="danger-action" onclick={confirmRemoveProvider}>Remove</button>
		</div>
	</div>
</Overlay>

<style>
	.settings-page {
		--page-accent: var(--accent);
		--page-soft: color-mix(in srgb, var(--accent-soft) 72%, transparent);
		--page-border: color-mix(in srgb, var(--accent) 20%, var(--border));
		--page-glow: color-mix(in srgb, var(--accent) 10%, transparent);
		--card-glass-sheen: none;
		--card-inner-line: transparent;
		--card-shadow: none;
		--card-top-edge: transparent;
		--card-top-light: transparent;
		--shadow-panel: none;

		box-sizing: border-box;
		width: 100%;
		max-width: 100%;
		min-width: 0;
		height: 100%;
		min-height: 0;
		padding: 0 1rem;
		margin: 0 auto;
		display: flex;
		animation: fade-in 0.35s cubic-bezier(0.16, 1, 0.3, 1);
	}

	@keyframes fade-in {
		from { opacity: 0; transform: translateY(12px); }
		to { opacity: 1; transform: translateY(0); }
	}

	.settings-panel {
		width: 100%;
		height: 100%;
		max-height: calc(100vh - 3rem);
		min-height: 0;
		display: flex;
		flex-direction: column;
		border: 1px solid var(--page-border);
		border-radius: 1.45rem;
		background:
			linear-gradient(135deg, var(--glass-overlay), transparent 22rem),
			radial-gradient(circle at top right, var(--page-glow), transparent 30rem),
			var(--panel);
		box-shadow: var(--shadow-chat);
		overflow: hidden;
	}

	.settings-header {
		flex: 0 0 auto;
		padding: 1.35rem 1.5rem;
		display: flex;
		align-items: center;
		gap: 1rem;
		border-bottom: 1px solid var(--border);
		background:
			linear-gradient(135deg, var(--page-soft), transparent 70%),
			var(--header-bg);
	}

	.title-mark {
		width: 3.5rem;
		height: 3.5rem;
		display: grid;
		place-items: center;
		border-radius: 1.1rem;
		background: var(--surface-glass);
		border: 1px solid var(--page-border);
		color: var(--page-accent);
		box-shadow: 0 0 20px var(--page-soft);
		flex: 0 0 auto;
	}

	.title-copy {
		min-width: 0;
	}

	.eyebrow {
		color: var(--page-accent);
		font-size: 0.72rem;
		font-weight: 800;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	h1 {
		font-size: 1.65rem;
		font-weight: 900;
		letter-spacing: -0.03em;
		line-height: 1.1;
	}

	.title-copy p:last-child {
		margin: 0.15rem 0 0;
		color: var(--text-soft);
	}

	.settings-content {
		flex: 1 1 auto;
		min-height: 0;
		display: grid;
		gap: 1.75rem;
		min-width: 0;
		padding: 1.5rem;
		overflow-y: auto;
		scrollbar-color: var(--scrollbar-thumb) transparent;
	}

	.settings-section,
	.settings-list,
	.context-panel,
	.collapsible-panel {
		min-width: 0;
	}

	.settings-section + .settings-section {
		position: relative;
		padding-top: 0.15rem;
	}

	.settings-section + .settings-section::before {
		content: '';
		position: absolute;
		left: 0;
		top: -0.9rem;
		width: 100%;
		height: 2px;
		background: linear-gradient(
			90deg,
			transparent,
			color-mix(in srgb, var(--border-strong) 68%, transparent) 12%,
			color-mix(in srgb, var(--accent) 18%, var(--border-strong)) 50%,
			color-mix(in srgb, var(--border-strong) 68%, transparent) 88%,
			transparent
		);
		opacity: 0.9;
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
	}

	.theme-card.active {
		border-color: var(--accent);
		background: var(--accent-soft);
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
		overflow: visible;
		border: 1px solid var(--card-border);
		border-radius: 1.15rem;
		background:
			var(--card-glass-sheen),
			var(--card-bg);
		box-shadow: inset 0 1px 0 var(--card-inner-line), var(--card-shadow);
	}

	.runtime-settings-list,
	.provider-runtime-panel,
	.collapsible-panel,
	.context-panel {
		overflow: visible;
	}

	.settings-row {
		width: 100%;
		border-top: none;
		border-right: none;
		border-left: none;
		border-bottom-color: color-mix(in srgb, var(--card-border) 84%, var(--accent) 8%);
		background: transparent;
		font: inherit;
		text-align: left;
		transition: background 180ms ease;
	}

	.settings-page .settings-list > .settings-row {
		background: transparent;
		box-shadow: none;
	}

	.settings-list > .settings-row:first-child,
	.settings-list > .collapsible-panel:first-child {
		border-top-left-radius: calc(1.15rem - 1px);
		border-top-right-radius: calc(1.15rem - 1px);
	}

	.settings-list > .settings-row:last-child,
	.settings-list > .collapsible-panel:last-child {
		border-bottom-left-radius: calc(1.15rem - 1px);
		border-bottom-right-radius: calc(1.15rem - 1px);
	}

	.settings-list > .settings-row:not(:last-child),
	.settings-list > .collapsible-panel:not(:last-child) {
		border-bottom: 1px solid color-mix(in srgb, var(--card-border) 82%, var(--accent) 8%);
		box-shadow: inset 0 -1px 0 color-mix(in srgb, var(--card-top-light) 45%, transparent);
	}

	.settings-row:hover {
		background: transparent;
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
		border-bottom: 1px solid var(--card-border);
		background:
			var(--card-glass-sheen),
			color-mix(in srgb, var(--card-bg) 86%, var(--surface-inset));
	}

	.context-panel {
		overflow: visible;
		border: 1px solid var(--card-border);
		border-radius: 1.05rem;
		background:
			var(--card-glass-sheen),
			var(--card-bg);
		box-shadow: inset 0 1px 0 var(--card-inner-line);
	}

	.context-panel > .mock-item:not(:last-child) {
		border-bottom-color: color-mix(in srgb, var(--border) 82%, var(--text-soft) 12%);
	}

	:global(:root.light) .settings-page .context-panel > .mock-item:not(:last-child) {
		border-bottom-color: var(--border);
	}

	.setup-card {
		display: grid;
		gap: 0.9rem;
		padding: 1rem 1.25rem;
		border-bottom: 1px solid var(--border);
		color: var(--text-muted);
	}

	.setup-card h3 {
		margin: 0.15rem 0 0.25rem;
		color: var(--text);
		font-size: 1rem;
	}

	.setup-card p {
		margin: 0;
		color: var(--text-soft);
		line-height: 1.45;
	}

	.setup-steps {
		counter-reset: setup-step;
		display: grid;
		gap: 0.6rem;
		margin: 0;
		padding: 0;
		list-style: none;
		color: var(--text-soft);
		font-size: 0.88rem;
		line-height: 1.45;
	}

	.setup-steps li {
		counter-increment: setup-step;
		display: grid;
		grid-template-columns: 2rem minmax(0, 1fr);
		align-items: start;
		gap: 0.75rem;
		padding: 0.75rem;
		border: 1px solid color-mix(in srgb, var(--card-border) 84%, var(--accent) 12%);
		border-radius: 0.85rem;
		background:
			linear-gradient(135deg, color-mix(in srgb, var(--accent) 8%, transparent), transparent 58%),
			var(--surface-glass);
	}

	.setup-steps li::before {
		content: counter(setup-step);
		display: grid;
		width: 2rem;
		height: 2rem;
		place-items: center;
		border-radius: 999px;
		background: var(--accent);
		color: #fff;
		font-weight: 900;
		box-shadow: 0 0.45rem 1.2rem color-mix(in srgb, var(--accent) 24%, transparent);
	}

	.setup-steps li span {
		min-width: 0;
	}

	.setup-steps code {
		border: 1px solid var(--border);
		border-radius: 0.38rem;
		background: var(--surface-inset);
		color: var(--text);
		font-size: 0.78rem;
		padding: 0.08rem 0.28rem;
	}

	.mini-row {
		padding: 0.95rem 1.25rem;
	}

	.compact-context-panel {
		margin-top: 1rem;
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
		border: 1px solid var(--card-border);
		border-radius: 0.95rem;
		background:
			var(--card-glass-sheen),
			var(--card-bg);
		color: var(--text);
		font: inherit;
		text-align: left;
		transition: all 180ms ease;
	}

	.animation-card:hover {
		border-color: var(--border-strong);
		background: var(--card-hover);
	}

	.animation-card.active {
		border-color: var(--accent);
		background: var(--accent-soft);
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
		border: 1px solid var(--card-border);
		border-radius: 0.78rem;
		background: var(--surface-inset);
		color: var(--text);
		font: inherit;
		padding: 0.75rem 0.9rem;
	}

	.quirk-panel {
		overflow: visible;
	}

	.empty-quirks span {
		display: flex;
		flex-direction: column;
		font-weight: 800;
	}

	.quirk-row {
		grid-template-columns: minmax(10rem, 13rem) minmax(12rem, 1fr) auto;
	}

	.quirk-row input {
		width: 100%;
	}

	.quirk-add {
		position: relative;
		z-index: 60;
	}

	.quirk-add-menu {
		position: absolute;
		left: 0;
		bottom: calc(100% + 0.45rem);
		z-index: 5002;
		min-width: 9rem;
		padding: 0.35rem;
		display: grid;
		gap: 0.25rem;
		border: 1px solid color-mix(in srgb, var(--accent) 30%, var(--card-border));
		border-radius: 0.85rem;
		background: var(--panel-raised);
		box-shadow: 0 16px 34px rgba(0, 0, 0, 0.34);
	}

	.quirk-add-menu button {
		border: none;
		border-radius: 0.65rem;
		background: transparent;
		color: var(--text);
		font: inherit;
		font-weight: 800;
		text-align: left;
		padding: 0.55rem 0.7rem;
	}

	.quirk-add-menu button:hover {
		background: var(--card-hover);
	}

	.provider-list {
		display: grid;
		gap: 0.75rem;
	}

	.provider-card {
		overflow: hidden;
		border: 1px solid var(--card-border);
		border-radius: 1rem;
		background:
			var(--card-glass-sheen),
			var(--card-bg);
	}

	.provider-card.active {
		border-color: color-mix(in srgb, var(--accent) 46%, var(--card-border));
		box-shadow: inset 0 1px 0 var(--card-top-light), 0 0 0 1px color-mix(in srgb, var(--accent) 14%, transparent);
	}

	.provider-card.editing {
		position: relative;
		z-index: 120;
		overflow: visible;
		border-color: color-mix(in srgb, var(--accent) 58%, var(--card-border));
		background: color-mix(in srgb, var(--card-bg) 92%, var(--accent-soft));
	}

	.provider-card.unsaved {
		border-color: color-mix(in srgb, var(--warning) 58%, var(--card-border));
		box-shadow: 0 0 0 1px color-mix(in srgb, var(--warning) 16%, transparent);
	}

	.warning-badge {
		border-color: color-mix(in srgb, var(--warning) 45%, var(--border));
		background: color-mix(in srgb, var(--warning) 18%, transparent);
		color: var(--warning);
	}

	.provider-row {
		align-items: flex-start;
		gap: 1rem;
		border-bottom: 0;
		border-radius: 1rem;
		background: transparent;
	}

	.provider-card.editing .provider-row {
		border-bottom: 1px solid var(--card-border);
		border-radius: 1rem 1rem 0 0;
	}

	.provider-row > span {
		display: flex;
		min-width: min(18rem, 100%);
		flex: 1 1 18rem;
		flex-direction: column;
		gap: 0.25rem;
	}

	.provider-row strong {
		color: var(--text);
		font-size: 0.98rem;
	}

	.provider-row small {
		color: var(--text-soft);
		font-size: 0.78rem;
		font-weight: 500;
		overflow-wrap: anywhere;
	}

	.provider-edit-panel {
		overflow: visible;
		border-radius: 0 0 1rem 1rem;
		background: color-mix(in srgb, var(--surface-inset) 48%, transparent);
	}

	.provider-edit-panel .mock-item {
		border-radius: 0;
		background: transparent;
	}

	.provider-manual-actions {
		justify-content: flex-end;
		background: transparent;
	}

	.select-field {
		width: min(20rem, 52vw);
		min-width: 0;
		max-width: 100%;
	}

	.codex-login-row {
		align-items: flex-start;
	}

	.codex-login-row span {
		gap: 0.25rem;
	}

	.codex-log-row {
		align-items: stretch;
	}

	.provider-actions {
		display: flex;
		flex: 0 1 auto;
		flex-wrap: wrap;
		justify-content: flex-end;
		gap: 0.5rem;
		align-items: center;
	}

	.provider-actions .primary-action,
	.provider-actions .secondary-action,
	.provider-actions .ghost {
		padding: 0.55rem 0.75rem;
		font-size: 0.78rem;
	}

	.provider-actions .danger {
		border-color: color-mix(in srgb, var(--danger) 52%, var(--border));
		background: color-mix(in srgb, var(--danger) 14%, transparent);
		color: var(--danger);
	}

	.provider-actions .danger:hover:not(:disabled) {
		background: color-mix(in srgb, var(--danger) 22%, transparent);
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--danger) 10%, transparent);
	}

	.model-actions {
		align-items: center;
		justify-content: flex-end;
	}

	.add-provider-button {
		border-color: color-mix(in srgb, var(--accent) 38%, var(--border));
		color: var(--accent-strong);
	}

	.cancel-add-action {
		border: 1px solid color-mix(in srgb, var(--warning) 42%, var(--border));
		border-radius: 0.82rem;
		background: color-mix(in srgb, var(--warning) 9%, transparent);
		color: color-mix(in srgb, var(--warning) 82%, var(--text));
		font-weight: 800;
		padding: 0.75rem 1rem;
		transition: all 180ms ease;
	}

	.cancel-add-action:hover:not(:disabled) {
		background: color-mix(in srgb, var(--warning) 16%, transparent);
		transform: translateY(-1px);
	}

	.action-spacer {
		flex: 1 1 auto;
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

	.toggle-row :global(.checkbox) {
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
		border: 1px solid var(--card-border);
		border-radius: 0.95rem;
		background:
			var(--card-glass-sheen),
			var(--card-bg);
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
		border-radius: 0.82rem;
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
		background: var(--card-bg);
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
		border: 1px solid color-mix(in srgb, var(--danger) 35%, transparent);
		background: color-mix(in srgb, var(--danger) 10%, transparent);
		color: var(--danger);
	}

	.save-status {
		margin-top: 1rem;
		margin-bottom: 0;
		border: 1px solid color-mix(in srgb, var(--success) 35%, transparent);
		background: color-mix(in srgb, var(--success) 10%, transparent);
		color: var(--text-soft);
	}

	.confirm-dialog {
		padding: 1.35rem;
	}

	.confirm-dialog h2 {
		margin: 0.25rem 0 0.5rem;
		font-size: 1.2rem;
	}

	.confirm-dialog p:not(.eyebrow) {
		margin: 0;
		color: var(--text-soft);
		line-height: 1.5;
	}

	.confirm-actions {
		display: flex;
		justify-content: flex-end;
		gap: 0.65rem;
		margin-top: 1.2rem;
	}

	.danger-action {
		border: 1px solid color-mix(in srgb, var(--danger) 55%, var(--border));
		border-radius: 0.82rem;
		background: color-mix(in srgb, var(--danger) 88%, #000);
		color: white;
		font-weight: 850;
		padding: 0.75rem 1rem;
		transition: all 180ms ease;
	}

	.danger-action:hover {
		transform: translateY(-1px);
		box-shadow: 0 12px 28px color-mix(in srgb, var(--danger) 22%, transparent);
	}

	.mock-item:last-child {
		border-bottom: none;
	}

	.calendar-access {
		margin-top: 1.1rem;
		padding-top: 1.1rem;
		border-top: 1px solid var(--border);
	}

	.access-heading {
		font-weight: 800;
		font-size: 0.85rem;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--text-muted);
	}

	.calendar-access .section-intro {
		margin: 0.45rem 0 0.85rem;
		max-width: 42rem;
	}

	.scope-list {
		display: grid;
		gap: 0.55rem;
	}

	.scope-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		padding: 0.6rem 0.85rem;
		border: 1px solid var(--card-border);
		border-radius: 0.85rem;
		background: var(--event-bg);
	}

	.scope-label {
		font-weight: 750;
		font-size: 0.9rem;
	}

	.scope-states {
		display: inline-flex;
		gap: 0.3rem;
		padding: 0.25rem;
		border: 1px solid var(--border);
		border-radius: 0.7rem;
		background: var(--surface-inset);
	}

	.scope-state {
		padding: 0.4rem 0.7rem;
		border-radius: 0.5rem;
		background: transparent;
		color: var(--text-muted);
		font-weight: 750;
		font-size: 0.78rem;
		cursor: pointer;
	}

	.scope-state.active.granted { background: var(--success); color: var(--on-accent); }
	.scope-state.active.ask { background: var(--warning); color: var(--on-accent); }
	.scope-state.active.denied { background: var(--danger); color: var(--on-accent); }

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
