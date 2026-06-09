export type ChatMode = 'chat' | 'plan' | 'debug';

export type ToolDiffFile = {
    path: string;
    status: 'created' | 'modified' | 'deleted' | string;
    added: number;
    removed: number;
    unified: string;
    truncated?: boolean;
};

export type ToolDiff = {
    files: ToolDiffFile[];
};

export type ToolEventMetadata = {
    tool?: string;
    arguments_summary?: Record<string, unknown>;
    result_summary?: string;
    error?: string;
    truncated?: boolean;
    raw_result_visible?: boolean;
    attachments?: ChatAttachment[];
    autonomy_intention_delivery?: boolean;
    intention_id?: number;
    intention_kind?: string;
    diff?: ToolDiff;
};

export type ChatAttachment = {
    id: string;
    name: string;
    mime_type: string;
    size: number;
    kind: 'image' | 'text' | 'file';
    data?: string;
    text?: string;
};

export type ChatMessage = {
	id?: number;
	kind?: 'message' | 'tool' | 'permission';
	role: 'user' | 'assistant' | 'system' | 'tool';
	content: string;
	thinking?: string;
	status?: 'running' | 'completed' | 'success' | 'error' | '';
	metadata?: ToolEventMetadata;
	attachments?: ChatAttachment[];
	sequence?: number;
	parent_message_id?: number | null;
	mode?: string;
	created_at?: string;
};

export type StreamChunk = {
	kind?: 'thinking' | 'response' | 'error' | 'chat' | 'snapshot' | 'tool_call' | 'tool_result' | 'tool_error' | 'cancelled' | 'permission_request' | 'heartbeat';
	text?: string;
	content?: string;
	thinking?: string;
	chat_id?: string;
	title?: string;
	event?: ChatMessage;
	id?: number;
	tool?: string;
	status?: string;
	arguments_summary?: Record<string, unknown>;
	arguments?: Record<string, unknown>;
	reason?: string;
	result_summary?: string;
	error?: string;
	done?: boolean;
};

export type ChatSummary = {
	id: string;
	title: string;
	mode: ChatMode;
	created_at: string;
	updated_at: string;
};

export type PersistedChat = ChatSummary & {
	messages: ChatMessage[];
};

export type BitBuddyConfig = {
	name: string;
	config_path?: string;
	personalities_dir?: string;
	legacy_personality_path?: string;
	provider: ProviderEntry;
	providers?: ProviderEntry[];
	active_provider?: string;
	runtime?: RuntimeConfig;
	user_context?: UserContextConfig;
	chat?: ChatConfig;
	autonomy?: AutonomyConfig;
	dreaming?: DreamingConfig;
	calendar?: CalendarConfig;
	email?: EmailConfig;
	mcp?: McpConfig;
	mcp_servers?: Record<string, McpServerConfig>;
	presentation?: {
		style: string;
		pronouns: string;
	};
	personality?: {
		source: string;
		id: string;
		path?: string | null;
		expressiveness: string;
		proactivity: string;
		quirk_frequency: string;
		bitbuddy_likes?: string[];
		bitbuddy_dislikes?: string[];
		display_name?: string;
		dislikes?: string[];
	};
};

export type McpConfig = {
	enabled: boolean;
};

export type McpServerConfig = {
	command: string;
	args: string[];
	timeout: number;
	connect_timeout: number;
	enabled: boolean;
};

export type McpStatus = {
	mcp: McpConfig;
	computer_use_linux: {
		configured: boolean;
		available: boolean;
		path: string;
		source: string;
		message: string;
	};
	mcp_servers: Record<string, McpServerConfig>;
	message?: string;
	doctor?: {
		ok: boolean;
		stdout: string;
		stderr: string;
		returncode: number;
	};
};

export type ChatConfig = {
	return_greeting_enabled: boolean;
	return_greeting_idle_minutes: number;
	return_greeting_phrases: string[];
	max_tool_rounds: number;
};

export type AutonomyConfig = {
	enabled: boolean;
	run_after_idle_consolidation: boolean;
	idle_delay_seconds: number;
	repeat_idle_cycles: boolean;
	idle_backoff_multiplier: number;
	idle_max_delay_seconds: number;
	max_actions_per_cycle: number;
	max_pending_questions: number;
	max_pending_comments: number;
	max_new_questions_per_cycle: number;
	max_autonomous_deliveries_per_day: number;
	web_search: {
		enabled: boolean;
		provider: string;
		url: string;
		startup_command?: string;
		max_results: number;
	};
};

export type DreamingConfig = {
	enabled: boolean;
	bedtime: string;
	wake_time: string;
	goodnight_triggers: string[];
	goodmorning_triggers: string[];
	idle_before_dream_minutes: number;
	minimum_dream_window_minutes: number;
	max_dream_tasks_per_night: number;
	allow_post_dream_autonomy_rounds: number;
	soft_delete_memories: boolean;
	quiet_mode_after_bedtime: boolean;
	goodnight_immediate_winddown: boolean;
	stale_intention_days: number;
	low_priority_stale_intention_days: number;
	self_note_injection_enabled: boolean;
};

export type UserContextConfig = {
	location_label: string;
	timezone: string;
	locale: string;
};

export type ModelRuntimeConfig = {
	provider: ProviderEntry;
	providers?: ProviderEntry[];
	active_provider?: string;
	project_scan_interval_seconds: number;
};

export type ProviderEntry = {
	key?: string;
	type: string;
	url: string;
	model: string;
	has_api_key?: boolean;
	api_key?: string;
};

export type RuntimeConfig = {
	project_scan_interval_seconds: number;
};

export type ProviderHealth = {
	ok: boolean;
	message: string;
	log_path?: string;
	connected?: boolean;
	auth_url?: string;
	callback_mode?: string;
	device_code?: string;
	log_excerpt?: string;
};

export type ProviderContext = {
	provider: string;
	model: string;
	used_tokens?: number | null;
	context_window_tokens: number | null;
	source?: string;
	usage_source?: string;
	window_source?: string;
};

export type ActivityItem = {
	id: number;
	kind: string;
	message: string;
	metadata: Record<string, unknown>;
	created_at: string;
};

export type NotificationItem = {
	id: number;
	category: string;
	severity: 'info' | 'success' | 'warning' | 'error' | string;
	title: string;
	body: string;
	source_kind: string;
	chat_id: string;
	action_url: string;
	metadata: Record<string, unknown>;
	created_at: string;
	read_at: string | null;
	dismissed_at: string | null;
};

export type NotificationResponse = {
	notifications: NotificationItem[];
	unread_count: number;
};

export type LifecycleState = {
	state: 'Awake' | 'NightEligible' | 'Dreaming' | 'Sleep';
	previous_state: string;
	transition_reason: string;
	night_reason: string;
	quiet_mode: boolean;
	last_user_activity_at: string;
	dream_allowed_after: string;
	current_dream_id: string;
	updated_at: string;
	metadata: Record<string, unknown>;
};

export type DreamRun = {
	id: string;
	mode: string;
	status: string;
	reason: string;
	previous_state: string;
	transition_reason: string;
	started_at: string;
	completed_at: string | null;
	interrupted_at: string | null;
	scheduled_token: Record<string, unknown>;
	metadata: Record<string, unknown>;
};

export type DreamTask = {
	id: number;
	dream_run_id: string;
	kind: string;
	status: string;
	started_at: string;
	completed_at: string | null;
	summary: string;
	changes: Record<string, unknown>;
	error: string;
};

export type IntentionItem = {
	id: number;
	kind: string;
	content: string;
	reason: string;
	source: string;
	source_cycle_id: string | null;
	status: string;
	created_at: string;
	used_at: string | null;
	metadata: Record<string, unknown>;
};

export type AutonomyJobStatus = {
	chat_id: string;
	job_id: string;
	phase: string;
	phase_message: string;
	activity: string;
	delay_seconds: number;
	repeat_index: number;
	created_at: string;
	started_at: string;
	updated_at: string;
};

export type AutonomyStatus = {
	state: 'idle' | 'scheduled' | 'running' | 'disabled' | 'blocked_by_lifecycle' | string;
	message: string;
	enabled: boolean;
	lifecycle_allows_autonomy: boolean;
	jobs: AutonomyJobStatus[];
};

export type AutonomyTimelineStep = {
	id: string;
	label: string;
	description: string;
	status: 'pending' | 'active' | 'completed' | 'skipped' | 'failed' | 'blocked' | string;
	message: string;
	timestamp: string;
	metadata: Record<string, unknown>;
};

export type AutonomyTimelineCycle = {
	id: string;
	chat_id: string;
	activity: string;
	status: string;
	started_at: string;
	updated_at: string;
	events: ActivityItem[];
};

export type AutonomyTimeline = {
	status: AutonomyStatus;
	lifecycle: LifecycleState;
	steps: AutonomyTimelineStep[];
	recent_cycles: AutonomyTimelineCycle[];
	recent_events: ActivityItem[];
};

export type SelfJournalEntry = {
	id: number;
	kind: string;
	title: string;
	body: string;
	created_at: string;
	metadata: Record<string, unknown>;
};

export type SelfStateEntry = {
	key: string;
	value: string;
	updated_at: string;
};

export type GoalItem = {
	id: number;
	title: string;
	why: string;
	owner: 'self' | 'user' | 'system' | string;
	horizon: 'session' | 'day' | 'week' | 'ongoing' | string;
	status: 'active' | 'paused' | 'completed' | 'dropped' | string;
	risk_level: number;
	autonomy_allowed: boolean;
	next_action: string;
	evidence: string;
	created_at: string;
	updated_at: string;
	metadata: Record<string, unknown>;
};

export type PersonalityEvolutionItem = {
	id: number;
	kind: string;
	label: string;
	summary: string;
	intensity: number;
	confidence: number;
	evidence_count: number;
	status: 'emerging' | 'stable' | 'cooling' | 'retired' | string;
	project_id: string;
	created_at: string;
	updated_at: string;
	last_seen_at: string;
	metadata: Record<string, unknown>;
};

export type SelfSnapshot = {
	state: Record<string, string>;
	state_entries: SelfStateEntry[];
	journal: SelfJournalEntry[];
	goals: GoalItem[];
	evolution: PersonalityEvolutionItem[];
};

export type MemoryLayer = 'episodic' | 'semantic' | 'project' | 'procedural' | 'self' | 'relationship';

export type MemoryLayerInfo = {
    layer: MemoryLayer;
    description: string;
    routing_rule: string;
};

export type MemoryRecord = {
    id: string;
    layer: MemoryLayer;
    kind: string;
    title: string;
    summary: string;
    importance: number;
    created_at: string;
    updated_at: string;
    archived_at: string | null;
    conversation_id: string | null;
    project_id: string | null;
    emotional_tone: string | null;
    source: string | null;
    tags: string[];
    metadata: Record<string, unknown>;
};

export type Episode = {
	id: string;
	created_at: string;
	updated_at: string;
	conversation_id: string | null;
	project_id: string | null;
	type: string;
	title: string;
	summary: string;
	importance: number;
	emotional_tone: string | null;
	source: string | null;
	tags: string[];
	metadata: Record<string, unknown>;
};

export type ProjectSummary = {
	id: string;
	name: string;
	paths: string[];
	database_path?: string;
	metadata_path?: string;
	access?: string;
};

export type ProjectCardMemory = {
	name?: string;
	repo_path?: string;
	stack?: string;
	purpose?: string;
	current_status?: string;
	verified_facts?: string;
	inferred_facts?: string;
	needs_read?: string;
	repo_structure_snapshot?: string;
	updated_at?: string;
};

export type ArchitectureSummary = {
	backend_layout?: string;
	frontend_layout?: string;
	important_packages?: string;
	major_responsibilities?: string;
	updated_at?: string;
};

export type FileIndexEntry = {
	path?: string;
	role?: string;
	key_responsibilities?: string[];
	when_to_read?: string;
	related_files?: string[];
	stale?: boolean;
	content_hash?: string;
	mtime_ns?: number;
	last_verified_at?: string;
};

export type SymbolContract = {
	file_path?: string;
	name?: string;
	kind?: string;
	contract?: string;
	related_files?: string[];
};

export type DecisionPreference = {
	decision?: string;
	constraint?: string;
	source?: string;
};

export type CurrentTaskMemory = {
	task?: string;
	status?: string;
	notes?: string;
	updated_at?: string;
};

export type ReadBeforeEditingRule = {
	area?: string;
	files_to_read?: string[];
	reason?: string;
};

export type ProjectNoteMemory = {
    category?: string;
    content?: string;
    source_chat_id?: string | null;
    created_at?: string;
    memory_id?: string | null;
    layer?: string;
    kind?: string;
    tags?: string[];
};

export type ProjectMemory = {
	project_card?: ProjectCardMemory;
	architecture_summary?: ArchitectureSummary;
	file_index?: FileIndexEntry[];
	symbol_contracts?: SymbolContract[];
	decisions_preferences?: DecisionPreference[];
	current_task_memory?: CurrentTaskMemory[];
	read_before_editing_rules?: ReadBeforeEditingRule[];
	project_notes?: ProjectNoteMemory[];
	retrieval_policy?: string;
};

export type ProjectMemoryResponse = {
	project: string;
	memory: ProjectMemory;
};

export const BITBUDDY_API = 'http://127.0.0.1:8787';

export class ApiError extends Error {
	constructor(
		message: string,
		readonly status: number
	) {
		super(message);
	}
}

export async function getActivity(): Promise<ActivityItem[]> {
	const response = await fetch(`${BITBUDDY_API}/activity`);
	if (!response.ok) throw new Error('Could not load BitBuddy activity. Is `bitbuddy serve` running?');
	const data = await response.json();
	return data.activity ?? [];
}

export async function getNotifications(options: { afterId?: number; limit?: number } = {}): Promise<NotificationResponse> {
	const params = new URLSearchParams();
	if (options.afterId) params.set('after_id', String(options.afterId));
	if (options.limit) params.set('limit', String(options.limit));
	const suffix = params.toString() ? `?${params.toString()}` : '';
	const response = await fetch(`${BITBUDDY_API}/notifications${suffix}`);
	if (!response.ok) throw new Error('Could not load BitBuddy notifications.');
	const data = await response.json();
	return {
		notifications: data.notifications ?? [],
		unread_count: Number(data.unread_count ?? 0)
	};
}

export async function markNotificationRead(id: number): Promise<number> {
	const response = await fetch(`${BITBUDDY_API}/notifications/${id}/read`, { method: 'POST' });
	if (!response.ok) throw new Error('Could not mark notification read.');
	const data = await response.json();
	return Number(data.unread_count ?? 0);
}

export async function dismissNotification(id: number): Promise<number> {
	const response = await fetch(`${BITBUDDY_API}/notifications/${id}/dismiss`, { method: 'POST' });
	if (!response.ok) throw new Error('Could not dismiss notification.');
	const data = await response.json();
	return Number(data.unread_count ?? 0);
}

export async function getAutonomyStatus(): Promise<AutonomyStatus> {
	const response = await fetch(`${BITBUDDY_API}/autonomy/status`);
	if (!response.ok) throw new Error('Could not load BitBuddy autonomy status.');
	const data = await response.json();
	return data.autonomy;
}

export async function getAutonomyTimeline(): Promise<AutonomyTimeline> {
	const response = await fetch(`${BITBUDDY_API}/autonomy/timeline`);
	if (!response.ok) throw new Error('Could not load BitBuddy autonomy timeline.');
	const data = await response.json();
	return data.timeline;
}

export async function getLifecycleStatus(): Promise<LifecycleState> {
	const response = await fetch(`${BITBUDDY_API}/lifecycle/status`);
	if (!response.ok) throw new Error('Could not load BitBuddy lifecycle status.');
	const data = await response.json();
	return data.lifecycle;
}

export async function getDreamRuns(): Promise<DreamRun[]> {
	const response = await fetch(`${BITBUDDY_API}/dreams`);
	if (!response.ok) throw new Error('Could not load BitBuddy dream logs.');
	const data = await response.json();
	return data.dreams ?? [];
}

export async function getDreamTasks(dreamId: string): Promise<DreamTask[]> {
	const response = await fetch(`${BITBUDDY_API}/dreams/${encodeURIComponent(dreamId)}`);
	if (!response.ok) throw new Error('Could not load BitBuddy dream tasks.');
	const data = await response.json();
	return data.tasks ?? [];
}

export async function getPermissionActivity(): Promise<ActivityItem[]> {
	const response = await fetch(`${BITBUDDY_API}/permissions/activity`);
	if (!response.ok) throw new Error('Could not load permission activity.');
	const data = await response.json();
	return data.activity ?? [];
}

export async function getIntentions(): Promise<IntentionItem[]> {
	const response = await fetch(`${BITBUDDY_API}/autonomy/intentions`);
	if (!response.ok) throw new Error('Could not load BitBuddy intentions.');
	const data = await response.json();
	return data.intentions ?? [];
}

export async function dismissIntention(id: number): Promise<boolean> {
	const response = await fetch(`${BITBUDDY_API}/autonomy/intentions/${id}/dismiss`, { method: 'POST' });
	if (!response.ok) throw new Error('Could not dismiss intention.');
	const data = await response.json();
	return Boolean(data.dismissed);
}

export async function getSelfSnapshot(): Promise<SelfSnapshot> {
	const response = await fetch(`${BITBUDDY_API}/self`);
	if (!response.ok) throw new Error('Could not load BitBuddy self model.');
	return response.json();
}

export async function updateSelfState(updates: Record<string, string>): Promise<SelfSnapshot> {
	const response = await fetch(`${BITBUDDY_API}/self`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(updates)
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not update self model.');
	return data;
}

export async function getGoals(includeDone = false): Promise<GoalItem[]> {
	const suffix = includeDone ? '?include_done=true' : '';
	const response = await fetch(`${BITBUDDY_API}/goals${suffix}`);
	if (!response.ok) throw new Error('Could not load BitBuddy goals.');
	const data = await response.json();
	return data.goals ?? [];
}

export async function createGoal(options: Partial<GoalItem> & { title: string }): Promise<GoalItem> {
	const response = await fetch(`${BITBUDDY_API}/goals`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(options)
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not create goal.');
	return data;
}

export async function updateGoal(id: number, updates: Partial<GoalItem>): Promise<GoalItem> {
	const response = await fetch(`${BITBUDDY_API}/goals/${id}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(updates)
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not update goal.');
	return data;
}

export async function getProjects(): Promise<ProjectSummary[]> {
	const response = await fetch(`${BITBUDDY_API}/projects`);
	if (!response.ok) throw new Error('Could not load project memories. Is `bitbuddy serve` running?');
	const data = await response.json();
	return data.projects ?? [];
}

export async function addProject(options: { name: string; paths: string[] }): Promise<ProjectSummary> {
	const response = await fetch(`${BITBUDDY_API}/projects`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(options)
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not add project.');
	return data.project;
}

export async function getProjectMemory(projectId: string): Promise<ProjectMemoryResponse> {
	const response = await fetch(`${BITBUDDY_API}/projects/${projectId}/memory`);
	if (!response.ok) throw new Error('Could not load project memory.');
	return response.json();
}

export async function deleteProject(projectId: string): Promise<void> {
	const response = await fetch(`${BITBUDDY_API}/projects/${projectId}`, { method: 'DELETE' });
	if (!response.ok) throw new Error('Could not delete project.');
}

export async function getRecentEpisodes(): Promise<Episode[]> {
	const response = await fetch(`${BITBUDDY_API}/memory/episodes`);
	if (!response.ok) throw new Error('Could not load episodic memories.');
	const data = await response.json();
	return data.episodes ?? [];
}

export async function searchEpisodes(query: string): Promise<Episode[]> {
	const response = await fetch(`${BITBUDDY_API}/memory/episodes/search?q=${encodeURIComponent(query)}`);
	if (!response.ok) throw new Error('Could not search episodic memories.');
	const data = await response.json();
	return data.episodes ?? [];
}

export async function getMemoryLayers(): Promise<MemoryLayerInfo[]> {
	const response = await fetch(`${BITBUDDY_API}/memory/layers`);
	if (!response.ok) throw new Error('Could not load memory layers.');
	const data = await response.json();
	return data.layers ?? [];
}

export async function getMemories(options: { layer?: MemoryLayer; query?: string; projectId?: string; includeArchived?: boolean; limit?: number } = {}): Promise<MemoryRecord[]> {
	const params = new URLSearchParams();
	if (options.layer) params.set('layer', options.layer);
	if (options.query) params.set('q', options.query);
	if (options.projectId) params.set('project_id', options.projectId);
	if (options.includeArchived) params.set('include_archived', 'true');
	if (options.limit) params.set('limit', String(options.limit));
	const suffix = params.toString() ? `?${params.toString()}` : '';
	const response = await fetch(`${BITBUDDY_API}/memory${suffix}`);
	if (!response.ok) throw new Error('Could not load memories.');
	const data = await response.json();
	return data.memories ?? [];
}

export async function getConfig(): Promise<BitBuddyConfig> {
	const response = await fetch(`${BITBUDDY_API}/config`);
	if (!response.ok) throw new Error('Could not load BitBuddy config.');
	return response.json();
}

export async function updateUserContext(userContext: UserContextConfig): Promise<BitBuddyConfig> {
	const response = await fetch(`${BITBUDDY_API}/config/user-context`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(userContext)
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not save local context.');
	return data;
}

export async function updatePersonalityConfig(personality: Partial<NonNullable<BitBuddyConfig['personality']>>): Promise<BitBuddyConfig> {
	const response = await fetch(`${BITBUDDY_API}/config/personality`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(personality)
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not save personality settings.');
	return data;
}

export async function updateDreamingConfig(dreaming: DreamingConfig): Promise<BitBuddyConfig> {
	const response = await fetch(`${BITBUDDY_API}/config/dreaming`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(dreaming)
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not save dreaming settings.');
	return data;
}

export async function updateChatConfig(chat: ChatConfig): Promise<BitBuddyConfig> {
	const response = await fetch(`${BITBUDDY_API}/config/chat`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(chat)
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not save chat settings.');
	return data;
}

export async function updateAutonomyConfig(autonomy: AutonomyConfig): Promise<BitBuddyConfig> {
	const response = await fetch(`${BITBUDDY_API}/config/autonomy`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(autonomy)
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not save autonomy settings.');
	return data;
}

export type CalendarConfig = {
	enabled: boolean;
	default_provider: string;
	reminder_upcoming_minutes: number;
	reminder_starting_soon_minutes: number;
	urgent_interrupts_enabled: boolean;
	urgent_interrupt_persistent: boolean;
	conflict_warnings_enabled: boolean;
	free_day_summary_enabled: boolean;
	chat_nudges_enabled: boolean;
	scheduler_tick_seconds: number;
	holidays_enabled: boolean;
	holidays_country: string;
};

export type CalendarEvent = {
	id: string;
	calendar_id: string;
	title: string;
	description: string;
	location: string;
	start_at: string;
	end_at: string;
	all_day: boolean;
	timezone: string;
	rrule: string | null;
	status: string;
	attendees: string[];
	source: string;
	metadata: Record<string, unknown>;
	created_at: string;
	updated_at: string;
};

export type EmailConfig = {
	enabled: boolean;
	provider: string;
	account_label: string;
	email_address: string;
	imap_host: string;
	imap_port: number;
	imap_security: 'ssl' | 'starttls' | 'none' | string;
	username: string;
	credentials_ref: string;
	gmail_oauth_mode: 'desktop_pkce' | 'web_secret' | string;
	gmail_client_id: string;
	gmail_credentials_ref: string;
	gmail_token_ref: string;
	gmail_redirect_uri: string;
	default_mailbox: string;
	max_preview_messages: number;
	has_password?: boolean;
	has_gmail_client_secret?: boolean;
	gmail_connected?: boolean;
};

export type GmailOAuthStatus = {
	ok: boolean;
	connected: boolean;
	message: string;
	auth_url?: string;
	redirect_uri?: string;
	oauth_mode?: string;
	diagnostics?: Record<string, string>;
};

export type EmailMailbox = {
	name: string;
	flags: string[];
	delimiter: string;
};

export type EmailMessage = {
	id: string;
	mailbox: string;
	subject: string;
	from_addr: string;
	to_addrs: string[];
	date: string;
	snippet: string;
	flags: string[];
	body?: string;
};

export type EmailRule = {
	id: number;
	account_id: string;
	kind: string;
	value: string;
	action: string;
	enabled: boolean;
	created_at: string;
	updated_at: string;
};

export type CalendarEventInput = {
	title: string;
	start: string;
	end: string;
	description?: string;
	location?: string;
	all_day?: boolean;
	attendees?: string[];
};

export type CalendarScope = 'read' | 'create' | 'modify' | 'delete';
export type CalendarPermissionState = 'granted' | 'denied' | 'ask';

export async function getCalendarEvents(
	options: { range?: string; start?: string; end?: string } = {}
): Promise<{ timezone: string; events: CalendarEvent[] }> {
	const params = new URLSearchParams();
	if (options.range) params.set('range', options.range);
	if (options.start) params.set('start', options.start);
	if (options.end) params.set('end', options.end);
	const suffix = params.toString() ? `?${params.toString()}` : '';
	const response = await fetch(`${BITBUDDY_API}/calendar/events${suffix}`);
	if (!response.ok) throw new Error('Could not load calendar events.');
	return response.json();
}

export async function createCalendarEvent(
	input: CalendarEventInput
): Promise<{ event: CalendarEvent; conflicts: CalendarEvent[] }> {
	const response = await fetch(`${BITBUDDY_API}/calendar/events`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(input)
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not create event.');
	return data;
}

export async function updateCalendarEvent(
	id: string,
	updates: Partial<CalendarEventInput> & { status?: string }
): Promise<{ event: CalendarEvent; conflicts: CalendarEvent[] }> {
	const response = await fetch(`${BITBUDDY_API}/calendar/events/${id}`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(updates)
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not update event.');
	return data;
}

export async function deleteCalendarEvent(id: string): Promise<boolean> {
	const response = await fetch(`${BITBUDDY_API}/calendar/events/${id}`, { method: 'DELETE' });
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not delete event.');
	return Boolean(data.deleted);
}

export async function getCalendarPermissions(): Promise<{
	scopes: CalendarScope[];
	permissions: Record<CalendarScope, CalendarPermissionState>;
}> {
	const response = await fetch(`${BITBUDDY_API}/calendar/permissions`);
	if (!response.ok) throw new Error('Could not load calendar permissions.');
	return response.json();
}

export async function setCalendarPermission(
	scope: CalendarScope,
	state: CalendarPermissionState
): Promise<Record<CalendarScope, CalendarPermissionState>> {
	const response = await fetch(`${BITBUDDY_API}/calendar/permissions`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ scope, state })
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not update calendar permission.');
	return data.permissions;
}

export async function updateCalendarConfig(calendar: Partial<CalendarConfig>): Promise<BitBuddyConfig> {
	const response = await fetch(`${BITBUDDY_API}/config/calendar`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(calendar)
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not save calendar settings.');
	return data;
}

export async function updateEmailConfig(email: Partial<EmailConfig> & { password?: string; gmail_client_secret?: string }): Promise<BitBuddyConfig> {
	const response = await fetch(`${BITBUDDY_API}/config/email`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(email)
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not save email settings.');
	return data;
}

export async function getGmailStatus(): Promise<GmailOAuthStatus> {
	const response = await fetch(`${BITBUDDY_API}/email/gmail/status`);
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not load Gmail status.');
	return data;
}

export async function startGmailLogin(force = false): Promise<GmailOAuthStatus> {
	const response = await fetch(`${BITBUDDY_API}/email/gmail/login`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ force })
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? data.message ?? 'Could not start Gmail authorization.');
	return data;
}

export async function openGmailCleanBrowser(force = false): Promise<GmailOAuthStatus> {
	const response = await fetch(`${BITBUDDY_API}/email/gmail/open-clean-browser`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ force })
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? data.message ?? 'Could not open clean browser OAuth profile.');
	return data;
}

export async function completeGmailLogin(input: string): Promise<GmailOAuthStatus> {
	const response = await fetch(`${BITBUDDY_API}/email/gmail/complete`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ input })
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.message ?? data.error ?? 'Could not complete Gmail authorization.');
	return data;
}

export async function logoutGmail(): Promise<GmailOAuthStatus> {
	const response = await fetch(`${BITBUDDY_API}/email/gmail/logout`, { method: 'POST' });
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? data.message ?? 'Could not disconnect Gmail.');
	return data;
}

export async function clearGmailClientSecret(): Promise<GmailOAuthStatus> {
	const response = await fetch(`${BITBUDDY_API}/email/gmail/client-secret`, { method: 'DELETE' });
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? data.message ?? 'Could not clear Gmail client secret.');
	return data;
}

export async function getEmailOverview(): Promise<EmailConfig & { permissions: Record<string, string>; account_id: string }> {
	const response = await fetch(`${BITBUDDY_API}/email/overview`);
	if (!response.ok) throw new Error('Could not load email overview.');
	return response.json();
}

export async function getEmailPermissions(): Promise<{ scopes: string[]; permissions: Record<string, string> }> {
	const response = await fetch(`${BITBUDDY_API}/email/permissions`);
	if (!response.ok) throw new Error('Could not load email permissions.');
	return response.json();
}

export async function setEmailPermission(scope: string, state: string): Promise<Record<string, string>> {
	const response = await fetch(`${BITBUDDY_API}/email/permissions`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ scope, state })
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not update email permission.');
	return data.permissions;
}

export async function getEmailMailboxes(): Promise<EmailMailbox[]> {
	const response = await fetch(`${BITBUDDY_API}/email/mailboxes`);
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not load email mailboxes.');
	return data.mailboxes ?? [];
}

export async function getEmailMessages(mailbox = '', limit = 25): Promise<EmailMessage[]> {
	const params = new URLSearchParams();
	if (mailbox) params.set('mailbox', mailbox);
	params.set('limit', String(limit));
	const response = await fetch(`${BITBUDDY_API}/email/messages?${params}`);
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not load email messages.');
	return data.messages ?? [];
}

export async function searchEmailMessages(query: string, mailbox = '', limit = 25): Promise<EmailMessage[]> {
	const params = new URLSearchParams({ q: query, limit: String(limit) });
	if (mailbox) params.set('mailbox', mailbox);
	const response = await fetch(`${BITBUDDY_API}/email/search?${params}`);
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not search email messages.');
	return data.messages ?? [];
}

export async function readEmailMessage(id: string, mailbox = ''): Promise<EmailMessage> {
	const params = new URLSearchParams({ id });
	if (mailbox) params.set('mailbox', mailbox);
	const response = await fetch(`${BITBUDDY_API}/email/message?${params}`);
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not read email message.');
	return data.message;
}

export async function trashEmailMessage(id: string, mailbox = ''): Promise<EmailMessage> {
	const response = await fetch(`${BITBUDDY_API}/email/message/trash`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ message_id: id, mailbox })
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not move email to Trash.');
	return data.message;
}

export async function getEmailRules(): Promise<EmailRule[]> {
	const response = await fetch(`${BITBUDDY_API}/email/rules`);
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not load email rules.');
	return data.rules ?? [];
}

export async function createSenderTrashRule(sender: string, options: { mailbox?: string; applyExisting?: boolean } = {}): Promise<{ rule: EmailRule; applied: number }> {
	const response = await fetch(`${BITBUDDY_API}/email/rules/sender-trash`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ sender, mailbox: options.mailbox ?? 'INBOX', apply_existing: options.applyExisting ?? false })
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not create email rule.');
	return data;
}

export async function deleteEmailRule(id: number): Promise<boolean> {
	const response = await fetch(`${BITBUDDY_API}/email/rules/${id}`, { method: 'DELETE' });
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not delete email rule.');
	return Boolean(data.deleted);
}

export async function updateModelRuntimeConfig(config: ModelRuntimeConfig): Promise<BitBuddyConfig> {
	const response = await fetch(`${BITBUDDY_API}/config/model-runtime`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(config)
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not save model and runtime settings.');
	return data;
}

export async function updateMcpConfig(config: McpConfig): Promise<BitBuddyConfig> {
	const response = await fetch(`${BITBUDDY_API}/config/mcp`, {
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(config)
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not save MCP settings.');
	return data;
}

export async function getMcpStatus(): Promise<McpStatus> {
	const response = await fetch(`${BITBUDDY_API}/mcp/status`);
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not load MCP status.');
	return data;
}

export async function installComputerUseLinux(): Promise<McpStatus> {
	const response = await fetch(`${BITBUDDY_API}/mcp/computer-use-linux/install`, { method: 'POST' });
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.message ?? data.error ?? 'Could not install Linux desktop control.');
	return data;
}

export async function configureComputerUseLinux(): Promise<McpStatus> {
	const response = await fetch(`${BITBUDDY_API}/mcp/computer-use-linux/configure`, { method: 'POST' });
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.message ?? data.error ?? 'Could not configure Linux desktop control.');
	return data;
}

export async function doctorComputerUseLinux(): Promise<McpStatus> {
	const response = await fetch(`${BITBUDDY_API}/mcp/computer-use-linux/doctor`, { method: 'POST' });
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.message ?? data.error ?? 'Linux desktop-control doctor failed.');
	return data;
}

export async function getProviderHealth(): Promise<ProviderHealth> {
	const response = await fetch(`${BITBUDDY_API}/provider/health`);
	const data = await response.json().catch(() => ({}));
	if (!response.ok && typeof data.message !== 'string') throw new Error(data.error ?? 'Could not check provider connection.');
	return {
		ok: Boolean(data.ok),
		message: String(data.message ?? 'Provider check failed.')
	};
}

export async function getProviderModels(provider?: Partial<ProviderEntry>): Promise<string[]> {
	const response = provider
		? await fetch(`${BITBUDDY_API}/provider/models`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(provider)
			})
		: await fetch(`${BITBUDDY_API}/provider/models`);
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not list provider models.');
	return data.models ?? [];
}

export async function getProviderContext(): Promise<ProviderContext> {
	const response = await fetch(`${BITBUDDY_API}/provider/context`);
	if (!response.ok) throw new Error('Could not load provider context window.');
	return response.json();
}

export async function getCodexStatus(): Promise<ProviderHealth> {
	const response = await fetch(`${BITBUDDY_API}/provider/codex/status`);
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not check Codex login status.');
	return {
		ok: Boolean(data.ok),
		message: String(data.message ?? 'Codex status unavailable.'),
		log_path: typeof data.log_path === 'string' ? data.log_path : undefined,
		connected: typeof data.connected === 'boolean' ? data.connected : undefined,
		auth_url: typeof data.auth_url === 'string' ? data.auth_url : undefined,
		callback_mode: typeof data.callback_mode === 'string' ? data.callback_mode : undefined,
		device_code: typeof data.device_code === 'string' ? data.device_code : undefined,
		log_excerpt: typeof data.log_excerpt === 'string' ? data.log_excerpt : undefined
	};
}

export async function startCodexLogin(options: { force?: boolean } = {}): Promise<ProviderHealth> {
	const response = await fetch(`${BITBUDDY_API}/provider/codex/login`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(options)
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? data.message ?? 'Could not start Codex login.');
	return {
		ok: Boolean(data.ok),
		message: String(data.message ?? 'Codex login started.'),
		log_path: typeof data.log_path === 'string' ? data.log_path : undefined,
		connected: typeof data.connected === 'boolean' ? data.connected : undefined,
		auth_url: typeof data.auth_url === 'string' ? data.auth_url : undefined,
		callback_mode: typeof data.callback_mode === 'string' ? data.callback_mode : undefined,
		device_code: typeof data.device_code === 'string' ? data.device_code : undefined,
		log_excerpt: typeof data.log_excerpt === 'string' ? data.log_excerpt : undefined
	};
}

export async function completeCodexLogin(input: string): Promise<ProviderHealth> {
	const response = await fetch(`${BITBUDDY_API}/provider/codex/complete`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ input })
	});
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? data.message ?? 'Could not complete Codex authorization.');
	return {
		ok: Boolean(data.ok),
		message: String(data.message ?? 'Codex authorization complete.'),
		connected: typeof data.connected === 'boolean' ? data.connected : undefined
	};
}

export async function logoutCodex(): Promise<ProviderHealth> {
	const response = await fetch(`${BITBUDDY_API}/provider/codex/logout`, { method: 'POST' });
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? data.message ?? 'Could not logout Codex.');
	return {
		ok: Boolean(data.ok),
		message: String(data.message ?? 'Codex logout complete.'),
		log_path: typeof data.log_path === 'string' ? data.log_path : undefined
	};
}

export async function getChatContextUsage(options: { mode: ChatMode; messages: ChatMessage[] }): Promise<ProviderContext> {
	const response = await fetch(`${BITBUDDY_API}/chat/context`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ mode: options.mode, messages: options.messages })
	});
	if (!response.ok) throw new Error('Could not load chat context usage.');
	return response.json();
}

export async function getRecentChats(): Promise<ChatSummary[]> {
	const response = await fetch(`${BITBUDDY_API}/chats`);
	if (!response.ok) throw new Error('Could not load recent chats. Is `bitbuddy serve` running?');
	const data = await response.json();
	return data.chats ?? [];
}

export async function getChats(options: { search?: string; limit?: number } = {}): Promise<ChatSummary[]> {
	const params = new URLSearchParams();
	if (options.search) params.set('search', options.search);
	if (options.limit) params.set('limit', String(options.limit));
	const query = params.toString() ? `?${params}` : '';
	const response = await fetch(`${BITBUDDY_API}/chats${query}`);
	if (!response.ok) throw new Error('Could not load chats.');
	const data = await response.json();
	return data.chats ?? [];
}

export async function getChat(chatId: string): Promise<PersistedChat> {
	const response = await fetch(`${BITBUDDY_API}/chats/${chatId}`);
	if (!response.ok) {
		throw new ApiError(response.status === 404 ? 'Chat no longer exists.' : 'Could not load chat.', response.status);
	}
	return response.json();
}

export async function deleteChat(chatId: string): Promise<void> {
	const response = await fetch(`${BITBUDDY_API}/chats/${chatId}`, { method: 'DELETE' });
	if (!response.ok) throw new Error('Could not delete chat.');
}

export async function deleteChatMessageTurn(chatId: string, messageId: number): Promise<PersistedChat> {
	const response = await fetch(`${BITBUDDY_API}/chats/${encodeURIComponent(chatId)}/messages/${messageId}/turn`, { method: 'DELETE' });
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not delete message turn.');
	return data.chat;
}

export async function trimChatFromMessage(chatId: string, messageId: number): Promise<PersistedChat> {
	const response = await fetch(`${BITBUDDY_API}/chats/${encodeURIComponent(chatId)}/messages/${messageId}/trim-from-message`, { method: 'POST' });
	const data = await response.json().catch(() => ({}));
	if (!response.ok) throw new Error(data.error ?? 'Could not edit message.');
	return data.chat;
}

export async function cancelChat(chatId: string): Promise<boolean> {
	const response = await fetch(`${BITBUDDY_API}/chat/cancel`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ chat_id: chatId })
	});
	if (!response.ok) throw new Error('Could not stop BitBuddy.');
	const data = await response.json();
	return Boolean(data.cancelled);
}

export async function grantPermission(chatId: string, granted: boolean): Promise<void> {
	const response = await fetch(`${BITBUDDY_API}/chat/permission`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ chat_id: chatId, granted })
	});
	if (!response.ok) throw new Error('Could not send permission response.');
}

export async function streamChat(options: {
	chatId: string;
	mode: ChatMode;
	messages: ChatMessage[];
	thinkingEnabled?: boolean;
	resume?: boolean;
	signal?: AbortSignal;
	onChunk: (chunk: StreamChunk) => void;
}): Promise<void> {
	const response = await fetch(`${BITBUDDY_API}/chat/stream`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		signal: options.signal,
		body: JSON.stringify({
			chat_id: options.chatId || undefined,
			mode: options.mode,
			messages: options.messages,
			thinking_enabled: options.thinkingEnabled ?? false,
			resume: options.resume ?? false
		})
	});

	if (!response.ok || !response.body) {
		throw new Error('Could not connect to BitBuddy. Start the backend with `bitbuddy serve`.');
	}

	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let buffer = '';

	while (true) {
		const { done, value } = await reader.read();
		if (done) break;
		buffer += decoder.decode(value, { stream: true });
		const events = buffer.split('\n\n');
		buffer = events.pop() ?? '';
		for (const event of events) {
			const line = event
				.split('\n')
				.find((part) => part.startsWith('data:'))
				?.replace(/^data:\s*/, '');
			if (!line) continue;
			options.onChunk(JSON.parse(line));
		}
	}
}

export async function sendActiveChat(chatId: string): Promise<void> {
	await fetch(`${BITBUDDY_API}/chat/active`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ chat_id: chatId })
	});
}

export async function getActiveChatNotifications(): Promise<Record<string, number>> {
	const response = await fetch(`${BITBUDDY_API}/chat/active/notifications`);
	if (!response.ok) return {};
	const data = await response.json();
	return data.notifications ?? {};
}

export type SubagentStep = {
	sequence: number;
	tool: string;
	status: string;
	summary: string;
};

export type SubagentRun = {
	id: string;
	agent_type: string;
	task: string;
	status: string;
	created_at: string;
	completed_at: string | null;
	report: string;
	error: string;
	metadata: Record<string, unknown>;
	steps: SubagentStep[];
};

export async function getSubagentRuns(limit = 20): Promise<SubagentRun[]> {
	const response = await fetch(`${BITBUDDY_API}/subagents/runs?limit=${limit}`);
	if (!response.ok) return [];
	const data = await response.json();
	return data.runs ?? [];
}

export type MemoryUpdatePatch = {
	title?: string;
	summary?: string;
	kind?: string;
	importance?: number;
	emotional_tone?: string;
	tags?: string[];
};

export async function archiveMemory(id: string, reason = 'Archived from memory browser.'): Promise<MemoryRecord> {
	const response = await fetch(`${BITBUDDY_API}/memory/${encodeURIComponent(id)}/archive`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ reason }),
	});
	if (!response.ok) throw new Error('Failed to archive memory.');
	return response.json();
}

export async function moveMemory(id: string, newLayer: MemoryLayer, reason = ''): Promise<MemoryRecord> {
	const response = await fetch(`${BITBUDDY_API}/memory/${encodeURIComponent(id)}/move`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ new_layer: newLayer, reason }),
	});
	if (!response.ok) throw new Error('Failed to move memory.');
	return response.json();
}

export async function updateMemory(id: string, patch: MemoryUpdatePatch): Promise<MemoryRecord> {
	const response = await fetch(`${BITBUDDY_API}/memory/${encodeURIComponent(id)}`, {
		method: 'PUT',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(patch),
	});
	if (!response.ok) throw new Error('Failed to update memory.');
	return response.json();
}

export type Skill = {
	name: string;
	description: string;
	version: string;
	path: string;
	metadata: Record<string, unknown>;
	usage: number;
	archived: boolean;
	frontmatter?: string;
	body?: string;
	content?: string;
};

export async function getSkills(includeArchived = false): Promise<Skill[]> {
	const params = includeArchived ? '?include_archived=true' : '';
	const response = await fetch(`${BITBUDDY_API}/skills${params}`);
	if (!response.ok) throw new Error('Could not load skills.');
	const data = await response.json();
	return data.skills ?? [];
}

export async function getSkill(name: string): Promise<Skill> {
	const response = await fetch(`${BITBUDDY_API}/skills/${encodeURIComponent(name)}`);
	if (!response.ok) throw new Error(`Could not load skill: ${name}`);
	return response.json();
}

export async function archiveSkillByName(name: string): Promise<void> {
	const response = await fetch(`${BITBUDDY_API}/skills/${encodeURIComponent(name)}/archive`, { method: 'POST' });
	if (!response.ok) throw new Error(`Could not archive skill: ${name}`);
}

export type WorkspaceDocument = {
	id: string;
	rel_path: string;
	title: string;
	kind: string;
	summary: string;
	source: string;
	goal_id: string;
	cycle_id: string;
	tags: string[];
	pinned: boolean;
	status: string;
	created_at: string;
	updated_at: string;
	body?: string;
};

export async function getWorkspaceDocuments(kind = '', status = 'active'): Promise<WorkspaceDocument[]> {
	const params = new URLSearchParams();
	if (kind) params.set('kind', kind);
	if (status) params.set('status', status);
	const query = params.toString() ? `?${params.toString()}` : '';
	const response = await fetch(`${BITBUDDY_API}/workspace${query}`);
	if (!response.ok) throw new Error('Could not load workspace documents.');
	const data = await response.json();
	return data.documents ?? [];
}

export async function getWorkspaceDocument(id: string): Promise<WorkspaceDocument> {
	const response = await fetch(`${BITBUDDY_API}/workspace/${encodeURIComponent(id)}`);
	if (!response.ok) throw new Error(`Could not load document: ${id}`);
	return response.json();
}

export async function archiveWorkspaceDocument(id: string): Promise<void> {
	const response = await fetch(`${BITBUDDY_API}/workspace/${encodeURIComponent(id)}/archive`, { method: 'POST' });
	if (!response.ok) throw new Error(`Could not archive document: ${id}`);
}

export async function pinWorkspaceDocument(id: string, pinned: boolean): Promise<void> {
	const response = await fetch(`${BITBUDDY_API}/workspace/${encodeURIComponent(id)}/pin`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify({ pinned })
	});
	if (!response.ok) throw new Error(`Could not update document: ${id}`);
}
