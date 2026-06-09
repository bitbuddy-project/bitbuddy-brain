import type { ChatAttachment, ChatMessage, ChatMode, ChatSummary, ProviderContext, StreamChunk } from '$lib/api/bitbuddy';
import { ApiError, cancelChat, deleteChat, deleteChatMessageTurn, getActiveChatNotifications, getChat, getChatContextUsage, getConfig, getProviderContext, getRecentChats, grantPermission, sendActiveChat, streamChat, trimChatFromMessage } from '$lib/api/bitbuddy';

let contextTimer: number | undefined;
let externalChatSyncTimer: number | undefined;
let activeChatHeartbeatTimer: number | undefined;
let notificationPollTimer: number | undefined;
let streamSequence = 0;
let activeStream: ActiveStream | null = null;
const chatSnapshots = new Map<string, ChatSnapshot>();
const EXTERNAL_CHAT_SYNC_MS = 3000;
const ACTIVE_CHAT_HEARTBEAT_MS = 5000;
const NOTIFICATION_POLL_MS = 8000;
const THINK_STORAGE_KEY = 'bitbuddy:think-enabled';

type ActiveStream = {
	token: number;
	chatId: string;
	initialChatId: string;
	controller: AbortController;
};

type ChatSnapshot = {
	title: string;
	mode: string;
	turnMode: string;
	messages: ChatMessage[];
	thinking: string;
};

export type PendingChatAttachment = ChatAttachment & { previewUrl?: string };

export type PendingSteerMessage = {
	content: string;
	attachments: ChatAttachment[];
	chatId: string;
};

export const chatSession = $state({
	initialized: false,
	serverAvailable: false,
	mode: 'Chat',
	turnMode: 'Chat',
	buddyName: 'BitBuddy',
	title: 'New chat',
	currentChatId: '',
	recentChats: [] as ChatSummary[],
	recentOpen: false,
	messages: [] as ChatMessage[],
	thinking: '',
	error: '',
	isStreaming: false,
	streamingChatId: '',
	chatScrollTop: 0,
	contextUsage: null as ProviderContext | null,
	draft: '',
	attachments: [] as PendingChatAttachment[],
	pendingSteer: null as PendingSteerMessage | null,
	backgroundNotifications: {} as Record<string, number>,
	thinkEnabled: true,
	// Thinking setting captured at the start of the active stream. Visibility of the
	// in-flight thinking stream is gated on this, so toggling thinkEnabled mid-response
	// does not tear down the thinking already being shown for the current run.
	activeThinkEnabled: false
});

function loadThinkPreference() {
	if (typeof window === 'undefined') return;
	try {
		const stored = window.localStorage.getItem(THINK_STORAGE_KEY);
		if (stored !== null) chatSession.thinkEnabled = stored === 'true';
	} catch { /* ignore */ }
}

function saveThinkPreference() {
	if (typeof window === 'undefined') return;
	try {
		window.localStorage.setItem(THINK_STORAGE_KEY, String(chatSession.thinkEnabled));
	} catch { /* ignore */ }
}

function saveStreamState() {
	if (!chatSession.currentChatId) return;
	try {
		window.localStorage.setItem(
			'bitbuddy:stream-state',
			JSON.stringify({
				chatId: chatSession.currentChatId,
				mode: chatSession.mode.toLowerCase(),
				turnMode: chatSession.turnMode.toLowerCase(),
				thinkEnabled: chatSession.thinkEnabled,
				messages: chatSession.messages
			})
		);
	} catch { /* ignore */ }
}

function restoreStreamState() {
	try {
		const raw = window.localStorage.getItem('bitbuddy:stream-state');
		if (!raw) return false;
		const state = JSON.parse(raw);
		if (!state.chatId || !Array.isArray(state.messages)) return false;
		chatSession.currentChatId = state.chatId;
		window.localStorage.setItem('bitbuddy:last-chat-id', state.chatId);
		chatSession.mode = modeLabel(state.mode);
		chatSession.turnMode = modeLabel(state.turnMode || state.mode);
		if (typeof state.thinkEnabled === 'boolean') {
			chatSession.thinkEnabled = state.thinkEnabled;
			saveThinkPreference();
		}
		chatSession.messages = state.messages;
		return true;
	} catch {
		return false;
	}
}

function clearStreamState() {
	try {
		window.localStorage.removeItem('bitbuddy:stream-state');
	} catch { /* ignore */ }
}

function rememberCurrentChat() {
	if (!chatSession.currentChatId) return;
	chatSnapshots.set(chatSession.currentChatId, {
		title: chatSession.title,
		mode: chatSession.mode,
		turnMode: chatSession.turnMode,
		messages: cloneMessages(chatSession.messages),
		thinking: chatSession.thinking
	});
}

function beginStream(chatId: string): ActiveStream {
	const stream = {
		token: ++streamSequence,
		chatId,
		initialChatId: chatId,
		controller: new AbortController(),
	};
	activeStream = stream;
	chatSession.isStreaming = true;
	chatSession.streamingChatId = chatId;
	// Capture the thinking setting for this run so later toggles of thinkEnabled
	// don't hide the thinking stream already rendering for the in-flight response.
	chatSession.activeThinkEnabled = chatSession.thinkEnabled;
	return stream;
}

function ownsStream(stream: ActiveStream): boolean {
	return activeStream?.token === stream.token;
}

function finishStream(stream: ActiveStream) {
	if (!ownsStream(stream)) return;
	activeStream = null;
	chatSession.isStreaming = false;
	chatSession.streamingChatId = '';
}

function syncPendingSteerChatId(stream: ActiveStream, chatId: string) {
	const pending = chatSession.pendingSteer;
	if (!pending || !chatId) return;
	if (!pending.chatId || pending.chatId === stream.initialChatId || pending.chatId === stream.chatId) {
		pending.chatId = chatId;
	}
}

function detachActiveStream() {
	rememberCurrentChat();
	if (activeStream) activeStream.controller.abort();
	activeStream = null;
	chatSession.isStreaming = false;
	chatSession.streamingChatId = '';
	clearPendingSteer();
}

function isAbortError(caught: unknown): boolean {
	return typeof DOMException !== 'undefined' && caught instanceof DOMException && caught.name === 'AbortError';
}

export async function initializeChat() {
	if (chatSession.initialized) {
		startExternalChatSync();
		return;
	}
	chatSession.initialized = true;
	loadThinkPreference();
	startExternalChatSync();

	try {
		const config = await getConfig();
		chatSession.buddyName = config.name || 'BitBuddy';
		chatSession.serverAvailable = true;
	} catch {
		chatSession.buddyName = 'BitBuddy';
		chatSession.serverAvailable = false;
	}

	try {
		chatSession.contextUsage = await getProviderContext();
	} catch {
		chatSession.contextUsage = null;
	}

	await refreshRecentChats();

	if (chatSession.messages.length === 0) {
		const restored = restoreStreamState();
		if (restored && chatSession.currentChatId) {
			await attemptReconnect();
			return;
		}
	}

	if (!chatSession.isStreaming && chatSession.messages.length === 0) {
		const lastChatId = window.localStorage.getItem('bitbuddy:last-chat-id');
		if (lastChatId) {
			await loadPersistedChat(lastChatId);
		} else if (chatSession.recentChats[0]) {
			await loadPersistedChat(chatSession.recentChats[0].id);
		}
	}
	startActiveChatHeartbeat();
	startNotificationPolling();
}

function startExternalChatSync() {
	if (typeof window === 'undefined' || externalChatSyncTimer) return;
	externalChatSyncTimer = window.setInterval(() => {
		void syncActiveChatFromServer();
	}, EXTERNAL_CHAT_SYNC_MS);
}

function startActiveChatHeartbeat() {
	if (typeof window === 'undefined' || activeChatHeartbeatTimer) return;
	activeChatHeartbeatTimer = window.setInterval(() => {
		void sendActiveChatHeartbeat();
	}, ACTIVE_CHAT_HEARTBEAT_MS);
}

function stopActiveChatHeartbeat() {
	if (activeChatHeartbeatTimer) {
		window.clearInterval(activeChatHeartbeatTimer);
		activeChatHeartbeatTimer = undefined;
	}
}

async function sendActiveChatHeartbeat() {
	if (!chatSession.currentChatId) return;
	try {
		await sendActiveChat(chatSession.currentChatId);
	} catch {
		// Background heartbeat should not surface errors.
	}
}

function startNotificationPolling() {
	if (typeof window === 'undefined' || notificationPollTimer) return;
	notificationPollTimer = window.setInterval(() => {
		void pollNotifications();
	}, NOTIFICATION_POLL_MS);
}

function stopNotificationPolling() {
	if (notificationPollTimer) {
		window.clearInterval(notificationPollTimer);
		notificationPollTimer = undefined;
	}
}

async function pollNotifications() {
	try {
		const notifications = await getActiveChatNotifications();
		chatSession.backgroundNotifications = notifications;
	} catch {
		// Background poll should not surface errors.
	}
}

async function syncActiveChatFromServer() {
	if (!chatSession.currentChatId || chatSession.isStreaming) return;

	const chatId = chatSession.currentChatId;
	try {
		const chat = await getChat(chatId);
		if (chatSession.currentChatId !== chatId || chatSession.isStreaming) return;

		const persistedMessages = chat.messages.map(normalizeTimelineItem);
		if (timelinesMatch(chatSession.messages, persistedMessages)) return;

		chatSession.title = chat.title;
		chatSession.mode = modeLabel(chat.mode);
		chatSession.turnMode = modeLabel(chat.mode);
		chatSession.messages = persistedMessages;
		chatSession.thinking = '';
		chatSession.error = '';
		void refreshRecentChats();
		void refreshContextUsage('');
	} catch {
		// Background sync should not surface transient API errors in the composer.
	}
}

async function attemptReconnect() {
	if (!chatSession.currentChatId) return;

	const stream = beginStream(chatSession.currentChatId);
	let completed = false;

	try {
		await streamChat({
			chatId: chatSession.currentChatId,
			mode: chatSession.mode.toLowerCase() as ChatMode,
			messages: chatSession.messages,
			thinkingEnabled: chatSession.thinkEnabled,
			resume: true,
			signal: stream.controller.signal,
				onChunk: (chunk) => {
					if (!ownsStream(stream)) return;
				if (chunk.kind === 'snapshot') {
					replaceAssistantSnapshot(chunk.content ?? '', chunk.thinking ?? '');
					saveStreamState();
				}
				if (chunk.kind === 'thinking') appendAssistantThinking(chunk.text ?? '');
				if (chunk.kind === 'response') appendAssistantText(chunk.text ?? '');
				if (chunk.kind === 'tool_call' || chunk.kind === 'tool_result' || chunk.kind === 'tool_error') handleToolChunk(chunk);
				if (chunk.kind === 'permission_request') handlePermissionChunk(chunk);
				if (chunk.kind === 'chat' && chunk.chat_id) {
					syncPendingSteerChatId(stream, chunk.chat_id);
					stream.chatId = chunk.chat_id;
					chatSession.streamingChatId = chunk.chat_id;
					chatSession.currentChatId = chunk.chat_id;
					window.localStorage.setItem('bitbuddy:last-chat-id', chunk.chat_id);
					if (chunk.title) chatSession.title = chunk.title;
					saveStreamState();
				}
				if (chunk.kind === 'error') chatSession.error = chunk.text ?? 'BitBuddy stream failed.';
				if (chunk.kind === 'cancelled') clearStreamState();
					if (chunk.done) {
						completed = true;
						chatSnapshots.delete(stream.chatId);
					}
				}
			});
		if (completed) {
			await loadPersistedChatState(stream.chatId);
			clearStreamState();
		}
		await refreshRecentChats();
	} catch (caught) {
		if (!isAbortError(caught) && ownsStream(stream)) chatSession.error = 'BitBuddy stream failed.';
		// Keep restored/persisted partial content visible.
	} finally {
		const owns = ownsStream(stream);
		finishStream(stream);
		if (owns) void refreshContextUsage('');
	}
}

async function loadPersistedChatState(chatId: string) {
	if (!chatId) return;
	const chat = await getChat(chatId);
	chatSession.currentChatId = chat.id;
	window.localStorage.setItem('bitbuddy:last-chat-id', chat.id);
	chatSession.title = chat.title;
	chatSession.mode = modeLabel(chat.mode);
	chatSession.messages = chat.messages.map(normalizeTimelineItem);
	chatSession.thinking = '';
	chatSession.error = '';
}

async function reconnectIfActive(chatId: string) {
	if (!chatId || chatSession.currentChatId !== chatId) return;
	await attemptReconnect();
}

export function setMode(nextMode: string) {
	chatSession.mode = nextMode;
	void refreshContextUsage('');
}

export function toggleThink() {
	chatSession.thinkEnabled = !chatSession.thinkEnabled;
	saveThinkPreference();
}

export async function sendMessage(content: string, attachments: ChatAttachment[] = []) {
	if (chatSession.isStreaming) {
		queuePendingSteer(content, attachments);
		return;
	}
	chatSession.turnMode = chatSession.mode;
	const userMessage: ChatMessage = { kind: 'message', role: 'user', content, attachments, mode: chatSession.turnMode };
	const outbound = [...chatSession.messages, userMessage].filter(
		(message) => message.role !== 'assistant' || message.content.trim() || message.thinking?.trim()
	);
	chatSession.messages = [...chatSession.messages, userMessage];
	if (chatSession.title === 'New chat') {
		chatSession.title = content.trim()
			? content.split(/\s+/).slice(0, 9).join(' ')
			: attachments.length ? `Uploaded ${attachments[0].name}` : 'New chat';
	}
	chatSession.thinking = '';
	chatSession.error = '';
	const stream = beginStream(chatSession.currentChatId);

	let completed = false;

	try {
		await streamChat({
			chatId: chatSession.currentChatId,
			mode: chatSession.mode.toLowerCase() as ChatMode,
			messages: outbound,
			thinkingEnabled: chatSession.thinkEnabled,
			signal: stream.controller.signal,
			onChunk: (chunk) => {
				if (!ownsStream(stream)) return;
				if (chunk.kind === 'chat' && chunk.chat_id) {
					syncPendingSteerChatId(stream, chunk.chat_id);
					stream.chatId = chunk.chat_id;
					chatSession.streamingChatId = chunk.chat_id;
					chatSession.currentChatId = chunk.chat_id;
					window.localStorage.setItem('bitbuddy:last-chat-id', chunk.chat_id);
					if (chunk.title) {
						chatSession.title = chunk.title;
					}
					// Immediately surface the new chat in the recent list
					if (!chatSession.recentChats.some((c) => c.id === chunk.chat_id)) {
						const now = new Date().toISOString();
						chatSession.recentChats = [
							{
								id: chunk.chat_id,
								title: chatSession.title,
								mode: chatSession.mode.toLowerCase() as ChatMode,
								created_at: now,
								updated_at: now
							},
							...chatSession.recentChats
						];
					}
					saveStreamState();
				}
				if (chunk.kind === 'snapshot') {
					replaceAssistantSnapshot(chunk.content ?? '', chunk.thinking ?? '');
					saveStreamState();
				}
				if (chunk.kind === 'thinking') appendAssistantThinking(chunk.text ?? '');
				if (chunk.kind === 'error') chatSession.error = chunk.text ?? 'BitBuddy stream failed.';
				if (chunk.kind === 'response') appendAssistantText(chunk.text ?? '');
				if (chunk.kind === 'tool_call' || chunk.kind === 'tool_result' || chunk.kind === 'tool_error') handleToolChunk(chunk);
				if (chunk.kind === 'permission_request') handlePermissionChunk(chunk);
				if (chunk.kind === 'cancelled') clearStreamState();
				if (chunk.done) {
					completed = true;
					clearStreamState();
				}
			}
		});
		await refreshRecentChats();
	} catch (caught) {
		if (!isAbortError(caught) && ownsStream(stream)) {
			chatSession.error = caught instanceof Error ? caught.message : 'BitBuddy could not connect.';
		}
	} finally {
		const owns = ownsStream(stream);
		finishStream(stream);
		if (completed) clearStreamState();
		if (completed) chatSnapshots.delete(stream.chatId);
		if (owns) {
			void refreshContextUsage('');
			void sendPendingSteerAfterTurn(stream.chatId);
		}
	}
}

function queuePendingSteer(content: string, attachments: ChatAttachment[] = []) {
	const clean = content.trim();
	if (!clean && attachments.length === 0) return;
	chatSession.pendingSteer = {
		content: clean,
		attachments,
		chatId: chatSession.streamingChatId || chatSession.currentChatId
	};
}

export function cancelPendingSteer() {
	clearPendingSteer();
}

export async function steerPendingMessage() {
	const pending = chatSession.pendingSteer;
	if (!pending) return;
	chatSession.pendingSteer = null;
	await stopActiveResponse();
	await sendMessage(pending.content, pending.attachments);
}

async function sendPendingSteerAfterTurn(chatId: string) {
	const pending = chatSession.pendingSteer;
	if (!pending || chatSession.isStreaming) return;
	const activeChatId = chatSession.currentChatId || chatId;
	if (pending.chatId && activeChatId && pending.chatId !== activeChatId && pending.chatId !== chatId) return;
	if (activeChatId) pending.chatId = activeChatId;
	chatSession.pendingSteer = null;
	await sendMessage(pending.content, pending.attachments);
}

function clearPendingSteer() {
	chatSession.pendingSteer = null;
}

export function scheduleContextUsage(draft: string) {
	if (typeof window === 'undefined') return;
	if (contextTimer) window.clearTimeout(contextTimer);
	contextTimer = window.setTimeout(() => {
		void refreshContextUsage(draft);
	}, 350);
}

export async function refreshContextUsage(draft = '', options: { providerOnly?: boolean } = {}) {
	try {
		if (options.providerOnly) {
			chatSession.contextUsage = await getProviderContext();
			return;
		}
		const draftMessage = draft.trim() ? [{ role: 'user' as const, content: draft.trim() }] : [];
		const messages = [...chatSession.messages, ...draftMessage].filter(
			(message) => message.role !== 'assistant' || message.content.trim() || message.thinking?.trim()
		);
		chatSession.contextUsage = await getChatContextUsage({
			mode: chatSession.mode.toLowerCase() as ChatMode,
			messages
		});
	} catch {
		try {
			chatSession.contextUsage = await getProviderContext();
		} catch {
			chatSession.contextUsage = null;
		}
	}
}

export async function refreshRecentChats() {
	try {
		chatSession.recentChats = await getRecentChats();
	} catch {
		chatSession.recentChats = [];
	}
}

export async function stopActiveResponse() {
	const stream = activeStream;
	if (!stream) return;
	const pending = chatSession.pendingSteer;

	const chatId = stream.chatId || chatSession.currentChatId;
	stream.controller.abort();
	finishStream(stream);
	clearStreamState();

	if (chatId) {
		try {
			await cancelChat(chatId);
		} catch (caught) {
			if (chatSession.currentChatId === chatId) {
				chatSession.error = caught instanceof Error ? caught.message : 'Could not stop BitBuddy.';
			}
		}
	}

	if (pending && chatSession.pendingSteer === pending) {
		chatSession.pendingSteer = null;
		await sendMessage(pending.content, pending.attachments);
	}
}

export async function deleteUserMessageTurn(message: ChatMessage) {
	if (chatSession.isStreaming || !chatSession.currentChatId || !message.id) return;
	try {
		const chat = await deleteChatMessageTurn(chatSession.currentChatId, message.id);
		chatSession.messages = chat.messages.map(normalizeTimelineItem);
		chatSession.title = chat.title;
		chatSession.mode = modeLabel(chat.mode);
		chatSession.thinking = '';
		chatSession.error = '';
		await refreshRecentChats();
		void refreshContextUsage('');
	} catch (caught) {
		chatSession.error = caught instanceof Error ? caught.message : 'Could not delete message turn.';
	}
}

export async function editUserMessageAndRerun(message: ChatMessage, content: string) {
	if (chatSession.isStreaming || !chatSession.currentChatId || !message.id) return;
	const clean = content.trim();
	if (!clean && !(message.attachments?.length)) return;
	try {
		const chat = await trimChatFromMessage(chatSession.currentChatId, message.id);
		chatSession.messages = chat.messages.map(normalizeTimelineItem);
		chatSession.title = chat.title;
		chatSession.mode = modeLabel(chat.mode);
		chatSession.thinking = '';
		chatSession.error = '';
		await sendMessage(clean, message.attachments ?? []);
	} catch (caught) {
		chatSession.error = caught instanceof Error ? caught.message : 'Could not edit message.';
	}
}

export async function loadPersistedChat(chatId: string) {
	detachActiveStream();
	clearStreamState();
	try {
		const chat = await getChat(chatId);
		const cached = chatSnapshots.get(chat.id);
		const persistedMessages = chat.messages.map(normalizeTimelineItem);
		const useCached = Boolean(cached && snapshotScore(cached.messages) > snapshotScore(persistedMessages));
		const messages = useCached && cached ? cloneMessages(cached.messages) : persistedMessages;
		chatSession.currentChatId = chat.id;
		window.localStorage.setItem('bitbuddy:last-chat-id', chat.id);
		chatSession.title = cached?.title || chat.title;
		chatSession.mode = cached?.mode || modeLabel(chat.mode);
		chatSession.turnMode = cached?.turnMode || modeLabel(chat.mode);
		chatSession.messages = messages;
		chatSession.thinking = useCached && cached ? cached.thinking : '';
		chatSession.error = '';
		chatSession.chatScrollTop = 0;
		chatSession.recentOpen = false;
		chatSession.backgroundNotifications = { ...chatSession.backgroundNotifications, [chat.id]: 0 };
		void refreshContextUsage('');
		void reconnectIfActive(chat.id);
	} catch (caught) {
		if (caught instanceof ApiError && caught.status === 404) {
			if (chatSession.currentChatId === chatId) chatSession.currentChatId = '';
			window.localStorage.removeItem('bitbuddy:last-chat-id');
			clearStreamState();
			chatSession.title = 'New chat';
			chatSession.messages = [];
			chatSession.thinking = '';
			chatSession.error = '';
			chatSession.chatScrollTop = 0;
			void refreshContextUsage('');
			return;
		}
		chatSession.error = caught instanceof Error ? caught.message : 'Could not load chat.';
	}
}

export async function removeRecentChat(chatId: string) {
	if (chatSession.isStreaming) return;
	clearStreamState();
	try {
		await deleteChat(chatId);
		chatSession.recentChats = chatSession.recentChats.filter((chat) => chat.id !== chatId);
		if (chatSession.currentChatId === chatId) {
			window.localStorage.removeItem('bitbuddy:last-chat-id');
			startNewChat();
		} else {
			await refreshRecentChats();
		}
	} catch (caught) {
		chatSession.error = caught instanceof Error ? caught.message : 'Could not delete chat.';
	}
}

export function startNewChat() {
	detachActiveStream();
	clearStreamState();
	clearPendingAttachments();
	clearPendingSteer();
	chatSession.currentChatId = '';
	chatSession.title = 'New chat';
	chatSession.messages = [];
	chatSession.thinking = '';
	chatSession.error = '';
	chatSession.chatScrollTop = 0;
	chatSession.recentOpen = false;
	chatSession.turnMode = 'Chat';
	window.localStorage.removeItem('bitbuddy:last-chat-id');
	void refreshContextUsage('');
	void refreshRecentChats();
}

export function clearPendingAttachments() {
	for (const attachment of chatSession.attachments) {
		if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
	}
	chatSession.attachments = [];
}

export function saveChatScrollTop(value: number) {
	chatSession.chatScrollTop = value;
}

export function toggleRecent() {
	chatSession.recentOpen = !chatSession.recentOpen;
}

function appendAssistantText(text: string) {
	if (chatSession.messages.length === 0 || chatSession.messages[chatSession.messages.length - 1].role !== 'assistant') {
		chatSession.messages = [...chatSession.messages, { kind: 'message', role: 'assistant', content: text, mode: chatSession.turnMode }];
		saveStreamState();
		return;
	}

	chatSession.messages = chatSession.messages.map((message, index) =>
		index === chatSession.messages.length - 1 ? { ...message, content: message.content + text } : message
	);
	saveStreamState();
}

function appendAssistantThinking(text: string) {
	chatSession.thinking += text;
	if (chatSession.messages.length === 0 || chatSession.messages[chatSession.messages.length - 1].role !== 'assistant') {
		chatSession.messages = [...chatSession.messages, { kind: 'message', role: 'assistant', content: '', thinking: text, mode: chatSession.turnMode }];
		saveStreamState();
		return;
	}

	chatSession.messages = chatSession.messages.map((message, index) =>
		index === chatSession.messages.length - 1 ? { ...message, thinking: (message.thinking ?? '') + text } : message
	);
	saveStreamState();
}

function replaceAssistantSnapshot(content: string, thinking: string) {
	if (chatSession.messages.length === 0 || chatSession.messages[chatSession.messages.length - 1].role !== 'assistant') {
		chatSession.messages = [...chatSession.messages, { kind: 'message', role: 'assistant', content, thinking, mode: chatSession.turnMode }];
		return;
	}

	chatSession.messages = chatSession.messages.map((message, index) =>
		index === chatSession.messages.length - 1 ? { ...message, content, thinking } : message
	);
	chatSession.thinking = thinking;
}

function handleToolChunk(chunk: { event?: ChatMessage; id?: number; tool?: string; status?: string; arguments_summary?: Record<string, unknown>; result_summary?: string; error?: string }) {
	const event = chunk.event
		? normalizeTimelineItem(chunk.event)
		: normalizeTimelineItem({
				id: chunk.id,
				kind: 'tool',
				role: 'tool',
				content: chunk.result_summary || chunk.error || `Running ${chunk.tool ?? 'tool'}...`,
				status: (chunk.status as ChatMessage['status']) ?? 'running',
				mode: chatSession.turnMode,
				metadata: {
					tool: chunk.tool,
					arguments_summary: chunk.arguments_summary,
					result_summary: chunk.result_summary,
					error: chunk.error,
					raw_result_visible: false
				}
			});

	upsertTimelineItem(event);
	saveStreamState();
}

function handlePermissionChunk(chunk: StreamChunk) {
	const event: ChatMessage = normalizeTimelineItem({
		kind: 'permission',
		role: 'system',
		content: chunk.reason || 'BitBuddy needs your permission to proceed.',
		status: 'running',
		mode: chatSession.turnMode,
		metadata: {
			tool: chunk.tool,
			arguments_summary: chunk.arguments as Record<string, unknown>,
		}
	});

	upsertTimelineItem(event);
	saveStreamState();
}

export async function respondToPermission(granted: boolean) {
	if (!chatSession.currentChatId) return;

	try {
		await grantPermission(chatSession.currentChatId, granted);

		// Update the last permission message to reflect the choice
		chatSession.messages = chatSession.messages.map(msg => {
			if (msg.kind === 'permission' && msg.status === 'running') {
				return { ...msg, status: granted ? 'success' : 'error' };
			}
			return msg;
		});
		saveStreamState();
	} catch (err) {
		chatSession.error = err instanceof Error ? err.message : 'Failed to send permission.';
	}
}

function upsertTimelineItem(event: ChatMessage) {
	if (!event.id) {
		if (event.kind === 'permission' && event.status === 'running') {
			let updated = false;
			chatSession.messages = chatSession.messages.map((message) => {
				if (!isSamePendingPermission(message, event)) return message;
				updated = true;
				return { ...message, ...event, metadata: { ...(message.metadata ?? {}), ...(event.metadata ?? {}) } };
			});
			if (updated) return;
		}

		chatSession.messages = [...chatSession.messages, event];
		return;
	}

	let updated = false;
	chatSession.messages = chatSession.messages.map((message) => {
		if (message.id !== event.id) return message;
		updated = true;
		return { ...message, ...event, metadata: { ...(message.metadata ?? {}), ...(event.metadata ?? {}) } };
	});

	if (!updated) chatSession.messages = [...chatSession.messages, event];
}

function isSamePendingPermission(message: ChatMessage, event: ChatMessage) {
	if (message.kind !== 'permission' || message.status !== 'running') return false;
	return message.metadata?.tool === event.metadata?.tool
		&& stableJson(message.metadata?.arguments_summary ?? {}) === stableJson(event.metadata?.arguments_summary ?? {});
}

function stableJson(value: unknown) {
	try {
		return JSON.stringify(sortJsonValue(value));
	} catch {
		return '';
	}
}

function sortJsonValue(value: unknown): unknown {
	if (Array.isArray(value)) return value.map(sortJsonValue);
	if (!value || typeof value !== 'object') return value;
	return Object.fromEntries(
		Object.entries(value as Record<string, unknown>)
			.sort(([left], [right]) => left.localeCompare(right))
			.map(([key, entry]) => [key, sortJsonValue(entry)])
	);
}

function normalizeTimelineItem(message: ChatMessage): ChatMessage {
	return {
		...message,
		kind: message.kind ?? 'message',
		role: message.role,
		content: message.content ?? '',
		thinking: message.thinking ?? '',
		status: message.status ?? '',
		metadata: message.metadata ?? {},
		attachments: message.attachments ?? message.metadata?.attachments ?? [],
		mode: modeLabel(message.mode || '')
	};
}

function snapshotScore(messages: ChatMessage[]): number {
	return messages.reduce((score, message) => {
		const contentLength = message.content?.length ?? 0;
		const thinkingLength = message.thinking?.length ?? 0;
		return score + 1 + contentLength + thinkingLength;
	}, 0);
}

function cloneMessages(messages: ChatMessage[]): ChatMessage[] {
	return messages.map((message) => ({
		...message,
		metadata: message.metadata ? { ...message.metadata } : undefined,
		attachments: message.attachments ? message.attachments.map((attachment) => ({ ...attachment })) : undefined
	}));
}

function timelinesMatch(current: ChatMessage[], next: ChatMessage[]): boolean {
	if (current.length !== next.length) return false;

	return current.every((message, index) => {
		const candidate = next[index];
		return Boolean(
			candidate &&
			(message.id ?? null) === (candidate.id ?? null) &&
			(message.sequence ?? null) === (candidate.sequence ?? null) &&
			(message.kind ?? 'message') === (candidate.kind ?? 'message') &&
			message.role === candidate.role &&
			(message.status ?? '') === (candidate.status ?? '') &&
			(message.content ?? '') === (candidate.content ?? '') &&
			(message.thinking ?? '') === (candidate.thinking ?? '')
		);
	});
}

function modeLabel(savedMode: string) {
	const lower = (savedMode || '').toLowerCase();
	if (lower === 'plan') return 'Plan';
	if (lower === 'debug') return 'Debug';
	return 'Chat';
}
