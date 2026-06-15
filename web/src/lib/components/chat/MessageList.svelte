<script lang="ts">
	import { onMount, tick } from 'svelte';
	import type { ChatMessage } from '$lib/api/bitbuddy';
	import { chatSession, saveChatScrollTop } from '$lib/stores/chat.svelte';
	import MessageBubble from './MessageBubble.svelte';
	import ThinkingStream from './ThinkingStream.svelte';
	import ToolEventGroup from './ToolEventGroup.svelte';
	import PermissionRequestCard from './PermissionRequestCard.svelte';

	let { messages, thinking, activeThinkEnabled, error, isStreaming, buddyName, onUserMessageDelete, onUserMessageEdit } = $props<{
		messages: ChatMessage[];
		thinking: string;
		activeThinkEnabled: boolean;
		error: string;
		isStreaming: boolean;
		buddyName: string;
		onUserMessageDelete?: (message: ChatMessage) => void | Promise<void>;
		onUserMessageEdit?: (message: ChatMessage, content: string) => void | Promise<void>;
	}>();

	function isAssistantMessage(message: ChatMessage | undefined) {
		return Boolean(message && (message.kind ?? 'message') === 'message' && message.role === 'assistant');
	}

	function latestAssistantMessageIndex() {
		for (let index = messages.length - 1; index >= 0; index -= 1) {
			if (messages[index]?.role === 'user') return -1;
			if (isAssistantMessage(messages[index])) return index;
		}
		return -1;
	}

	function isLatestAssistantMessage(message: ChatMessage, index: number) {
		return index === latestAssistantMessageIndex() && isAssistantMessage(message);
	}

	function hasAssistantMessage() {
		return latestAssistantMessageIndex() >= 0;
	}

	function thinkingFor(message: ChatMessage, index: number) {
		return isLatestAssistantMessage(message, index) ? thinking || message.thinking || '' : message.thinking || '';
	}

	let messageArea: HTMLDivElement;
	let isNearBottom = true;
	let lastMessageCount = $state(0);
	let lastFinalStartKey = $state('');
	let wasStreaming = $state(false);
	let activeEditingMessageKey = $state('');
	let animatingIds = $state<Set<string | number>>(new Set());
	let resizeObserver: ResizeObserver | null = null;

	function shouldAnimate(message: ChatMessage, index: number): boolean {
		return animatingIds.has(message.id ?? index);
	}

	onMount(() => {
		void tick().then(() => {
			if (messageArea) {
				if (chatSession.isStreaming) {
					messageArea.scrollTop = messageArea.scrollHeight;
				} else {
					messageArea.scrollTop = chatSession.chatScrollTop;
				}
			}
		});

		return () => {
			if (messageArea) saveChatScrollTop(messageArea.scrollTop);
		};
	});

	$effect(() => {
		if (!messageArea) return;

		resizeObserver?.disconnect();
		resizeObserver = new ResizeObserver(() => {
			if (isNearBottom) {
				messageArea.scrollTop = messageArea.scrollHeight;
			}
		});
		resizeObserver.observe(messageArea);

		return () => {
			resizeObserver?.disconnect();
			resizeObserver = null;
		};
	});

	$effect(() => {
		if (activeEditingMessageKey) {
			const stillEditable = !isStreaming && messages.some((message: ChatMessage, index: number) => editMessageKey(message, index) === activeEditingMessageKey && canEditUserMessage(message));
			if (!stillEditable) activeEditingMessageKey = '';
		}

		const messageCount = messages.length;
		if (messageCount !== lastMessageCount) {
			lastMessageCount = messageCount;
			if (isNearBottom) nudgeToBottom('auto');

			// New message just arrived
			if (messageCount > 0) {
				const newMsg = messages[messageCount - 1];
				const id = newMsg.id ?? messageCount - 1;
				// Only animate user messages immediately; assistant animates when streaming ends
				if (newMsg.role === 'user') {
					animatingIds = new Set([...animatingIds, id]);
					window.setTimeout(() => {
						animatingIds = new Set([...animatingIds].filter((x) => x !== id));
					}, 600);
				}
			}
		}

		// Streaming just finished — animate the final assistant message
		if (wasStreaming && !isStreaming && messages.length > 0) {
			const trailing = messages[messages.length - 1];
			if (trailing?.role === 'assistant' && (trailing.kind ?? 'message') === 'message') {
				const id = trailing.id ?? messages.length - 1;
				animatingIds = new Set([...animatingIds, id]);
				window.setTimeout(() => {
					animatingIds = new Set([...animatingIds].filter((x) => x !== id));
				}, 600);
			}
		}
		wasStreaming = isStreaming;

		const trailing = messages[messages.length - 1];
		const trailingKey = trailing?.id ? String(trailing.id) : String(messages.length - 1);
		const finalAnswerStarted = Boolean(
			isStreaming &&
			trailing &&
			(trailing.kind ?? 'message') === 'message' &&
			trailing.role === 'assistant' &&
			trailing.content?.trim()
		);

		if (finalAnswerStarted && trailingKey !== lastFinalStartKey) {
			lastFinalStartKey = trailingKey;
			nudgeToBottom('smooth');
		}
	});

	function nudgeToBottom(behavior: ScrollBehavior) {
		if (!messageArea) return;
		void tick().then(() => {
			messageArea.scrollTo({ top: messageArea.scrollHeight, behavior });
			window.setTimeout(() => {
				messageArea?.scrollTo({ top: messageArea.scrollHeight, behavior: 'auto' });
			}, 180);
		});
	}

	function handleScroll() {
		if (!messageArea) return;
		const threshold = 100;
		isNearBottom = messageArea.scrollHeight - messageArea.scrollTop - messageArea.clientHeight < threshold;
		saveChatScrollTop(messageArea.scrollTop);
	}

	function thinkingStorageKey(message: ChatMessage, index: number) {
		if (isLatestAssistantMessage(message, index) && isStreaming) return activeThinkingStorageKey();
		const chatKey = chatSession.currentChatId || chatSession.streamingChatId || 'unknown-chat';
		return message.id ? `chat:${chatKey}:message:${message.id}` : `chat:${chatKey}:transient:${index}`;
	}

	function activeThinkingStorageKey() {
		const chatKey = chatSession.currentChatId || chatSession.streamingChatId || 'pending-chat';
		for (let index = messages.length - 1; index >= 0; index -= 1) {
			const message = messages[index];
			if (message.role !== 'user') continue;
			const userKey = message.id ? `user:${message.id}` : `user:${index}:${fingerprint(message.content)}`;
			return `chat:${chatKey}:active-thinking:${userKey}`;
		}
		return `chat:${chatKey}:active-thinking:new`;
	}

	function fingerprint(value: string) {
		let hash = 0;
		for (let index = 0; index < value.length; index += 1) {
			hash = (hash * 31 + value.charCodeAt(index)) | 0;
		}
		return `${value.length}:${Math.abs(hash)}`;
	}

	function autonomyIntroKey(message: ChatMessage, index: number) {
		const chatKey = chatSession.currentChatId || chatSession.streamingChatId || 'unknown-chat';
		return `chat:${chatKey}:autonomy:${message.id ?? index}`;
	}

	function typingStorageKey(message: ChatMessage, index: number) {
		const chatKey = chatSession.currentChatId || chatSession.streamingChatId || 'unknown-chat';
		if (message.id) return `chat:${chatKey}:typed:${message.id}`;
		if (isLatestAssistantMessage(message, index)) return activeTypingStorageKey();
		return `chat:${chatKey}:typed:transient:${index}:${message.role}`;
	}

	function activeTypingStorageKey() {
		const chatKey = chatSession.currentChatId || chatSession.streamingChatId || 'pending-chat';
		for (let index = messages.length - 1; index >= 0; index -= 1) {
			const message = messages[index];
			if (message.role !== 'user') continue;
			const userKey = message.id ? `user:${message.id}` : `user:${index}:${fingerprint(message.content)}`;
			return `chat:${chatKey}:typed:active:${userKey}`;
		}
		return `chat:${chatKey}:typed:active:new`;
	}

	function messageRenderKey(message: ChatMessage, index: number) {
		const chatKey = chatSession.currentChatId || chatSession.streamingChatId || 'unknown-chat';
		const messageKey = message.id ?? `${index}:${message.role}:${message.kind ?? 'message'}`;
		return `${chatKey}:${messageKey}`;
	}

	function editMessageKey(message: ChatMessage, index: number) {
		if (!message.id) return '';
		return String(message.id ?? `${index}:${message.role}`);
	}

	function editDisabledFor(message: ChatMessage, index: number) {
		const key = editMessageKey(message, index);
		return Boolean(activeEditingMessageKey && key && activeEditingMessageKey !== key);
	}

	function setMessageEditing(message: ChatMessage, index: number, editing: boolean) {
		const key = editMessageKey(message, index);
		if (!key) return;
		if (editing) {
			activeEditingMessageKey = key;
			return;
		}
		if (activeEditingMessageKey === key) activeEditingMessageKey = '';
	}

	function canEditUserMessage(message: ChatMessage) {
		return message.role === 'user' && (message.kind ?? 'message') === 'message' && Boolean(message.id) && !isStreaming;
	}

	function shouldRenderMessageBubble(message: ChatMessage, index: number) {
		if (message.role === 'user') return true;
		if (message.role !== 'assistant') return false;
		if (message.content) return true;
		if (!isLatestAssistantMessage(message, index)) return false;
		return !thinkingFor(message, index) && !error && !isStreaming;
	}

	function shouldRenderThinking(message: ChatMessage, index: number) {
		if (message.role !== 'assistant') return false;
		if (thinkingFor(message, index)) return true;
		if (!isLatestAssistantMessage(message, index)) return false;
		return Boolean(error || (isStreaming && activeThinkEnabled));
	}

	type RenderItem =
		| { type: 'message'; message: ChatMessage; index: number; key: string }
		| { type: 'tool-group'; messages: ChatMessage[]; startIndex: number; key: string; showFace: boolean };

	let renderItems = $derived.by(() => {
		const items: RenderItem[] = [];
		let index = 0;
		while (index < messages.length) {
			const message = messages[index];
			if (isAbsorbableThinkingBeforeTool(index)) {
				index += 1;
				continue;
			}
			if ((message.kind ?? 'message') === 'tool') {
				const group: ChatMessage[] = [];
				const startIndex = index;
				let lastVisibleToolIndex = -1;
				while (index < messages.length) {
					const current = messages[index];
					if ((current.kind ?? 'message') === 'tool') {
						if (!isHiddenToolMessage(current)) {
							group.push(current);
							lastVisibleToolIndex = index;
						}
						index += 1;
						continue;
					}
					if (isAbsorbableThinkingAt(index, lastVisibleToolIndex) && nextVisibleToolIndex(index + 1, lastVisibleToolIndex) >= 0) {
						index += 1;
						continue;
					}
					break;
				}
				if (group.length) {
					items.push({
						type: 'tool-group',
						messages: group,
						startIndex,
						key: `tools:${startIndex}:${group.map((tool) => tool.id ?? tool.metadata?.tool ?? tool.content).join('|')}`,
						showFace: shouldShowFaceForToolGroup(startIndex)
					});
				}
				continue;
			}

			items.push({ type: 'message', message, index, key: messageRenderKey(message, index) });
			index += 1;
		}
		return items;
	});

	function isHiddenToolMessage(message: ChatMessage) {
		const metadata = (message.metadata ?? {}) as Record<string, unknown>;
		return metadata.tool === 'memory_consolidation' || metadata.memory_consolidation === true;
	}

	function isAbsorbableThinkingBeforeTool(index: number) {
		return isAbsorbableThinkingAt(index) && nextVisibleToolIndex(index + 1) >= 0;
	}

	function isAbsorbableThinkingMessage(message: ChatMessage | undefined) {
		if (!message || message.role !== 'assistant' || (message.kind ?? 'message') !== 'message') return false;
		if (message.content?.trim()) return false;
		const text = normalizeThinkingText(message.thinking || '');
		return !text || text === 'running the selected tool.' || text === 'running the tool.' || text === 'using the selected tool.';
	}

	function isAbsorbableThinkingAt(index: number, previousVisibleToolIndex = -1) {
		const message = messages[index];
		if (isAbsorbableThinkingMessage(message)) return true;
		if (!isProjectMemoryProgressThinking(message)) return false;
		const previousTool = previousVisibleToolIndex >= 0 ? messages[previousVisibleToolIndex] : undefined;
		const nextToolIndex = nextVisibleToolIndex(index + 1, previousVisibleToolIndex, false);
		const nextTool = nextToolIndex >= 0 ? messages[nextToolIndex] : undefined;
		return isProjectMemoryTool(previousTool) || isProjectMemoryTool(nextTool);
	}

	function isProjectMemoryProgressThinking(message: ChatMessage | undefined) {
		if (!message || message.role !== 'assistant' || (message.kind ?? 'message') !== 'message') return false;
		if (message.content?.trim()) return false;
		return normalizeThinkingText(message.thinking || '').startsWith('loading deeper project memory for ');
	}

	function isProjectMemoryTool(message: ChatMessage | undefined) {
		return (message?.kind ?? 'message') === 'tool' && String(message?.metadata?.tool || '').toLowerCase() === 'get_project_memory';
	}

	function normalizeThinkingText(value: string) {
		return value.replace(/<system-reminder\b[^>]*>[\s\S]*?(?:<\/system-reminder>|$)/gi, '').trim().replace(/\s+/g, ' ').toLowerCase();
	}

	function nextVisibleToolIndex(startIndex: number, previousVisibleToolIndex = -1, allowProjectMemoryProgress = true) {
		for (let index = startIndex; index < messages.length; index += 1) {
			const message = messages[index];
			if ((message.kind ?? 'message') === 'tool') return isHiddenToolMessage(message) ? -1 : index;
			if (isAbsorbableThinkingMessage(message)) continue;
			if (allowProjectMemoryProgress && isProjectMemoryProgressThinking(message) && isProjectMemoryTool(previousVisibleToolIndex >= 0 ? messages[previousVisibleToolIndex] : undefined)) continue;
			return -1;
		}
		return -1;
	}

	function toolGroupFollows(index: number) {
		for (let next = index + 1; next < messages.length; next += 1) {
			const message = messages[next];
			if ((message.kind ?? 'message') === 'tool') return !isHiddenToolMessage(message) || toolGroupHasVisibleMessage(next);
			if (isAbsorbableThinkingAt(next)) continue;
			if ((message.kind ?? 'message') !== 'permission') return false;
		}
		return false;
	}

	function toolGroupHasVisibleMessage(startIndex: number) {
		for (let index = startIndex; index < messages.length && (messages[index].kind ?? 'message') === 'tool'; index += 1) {
			if (!isHiddenToolMessage(messages[index])) return true;
		}
		return false;
	}

	function shouldShowFaceForToolGroup(startIndex: number) {
		for (let index = startIndex - 1; index >= 0; index -= 1) {
			const message = messages[index];
			if ((message.kind ?? 'message') === 'tool') continue;
			return message.role === 'assistant' && isLatestAssistantMessage(message, index);
		}
		return false;
	}
</script>

<div class="message-area" bind:this={messageArea} onscroll={handleScroll}>
	{#if messages.length === 0}
		{#if chatSession.initialized && !chatSession.serverAvailable}
			<MessageBubble
				role="assistant"
				{buddyName}
				content={`Start the backend with \`bitbuddy serve\`, then open the web UI with \`bitbuddy dashboard\`.`}
			/>
		{:else if chatSession.initialized}
			<div class="empty-chat">No messages yet.</div>
		{/if}
	{/if}

	{#each renderItems as item (item.key)}
		{#if item.type === 'tool-group'}
			<div class="message-turn" data-turn-mode={item.messages[0]?.mode || 'Chat'}>
				<ToolEventGroup messages={item.messages} showFace={item.showFace} />
			</div>
		{:else}
			{@const message = item.message}
			{@const index = item.index}
			<div class="message-turn" class:animate-in={shouldAnimate(message, index)} data-turn-mode={message.mode || 'Chat'}>
			{#if (message.kind ?? 'message') === 'permission'}
				<PermissionRequestCard {message} {buddyName} />
			{:else if message.role !== 'system'}
				{#if shouldRenderThinking(message, index)}
					<ThinkingStream
						content={thinkingFor(message, index)}
						{error}
						isStreaming={isLatestAssistantMessage(message, index) && isStreaming}
						autoCollapse={Boolean(message.content?.trim())}
						storageKey={thinkingStorageKey(message, index)}
						showFace={isLatestAssistantMessage(message, index) && !toolGroupFollows(index)}
					/>
				{/if}

				{#if shouldRenderMessageBubble(message, index)}
					<MessageBubble
						role={message.role === 'user' ? 'user' : 'assistant'}
						content={message.content}
						attachments={message.attachments ?? []}
						mode={message.mode || 'Chat'}
						{buddyName}
						isTyping={isLatestAssistantMessage(message, index) && isStreaming && Boolean(message.content)}
						showFace={message.role === 'assistant' && isLatestAssistantMessage(message, index)}
						autonomyIntroKey={message.metadata?.autonomy_intention_delivery ? autonomyIntroKey(message, index) : ''}
						typingStorageKey={message.role === 'assistant' ? typingStorageKey(message, index) : ''}
						createdAt={message.created_at ?? ''}
						canManage={canEditUserMessage(message)}
						editDisabled={editDisabledFor(message, index)}
						onDelete={message.role === 'user' ? () => onUserMessageDelete?.(message) : undefined}
						onEdit={message.role === 'user' ? (content) => onUserMessageEdit?.(message, content) : undefined}
						onEditingChange={(editing) => setMessageEditing(message, index, editing)}
					/>
				{/if}
			{/if}
		</div>
		{/if}
	{/each}

	{#if !hasAssistantMessage() && (thinking || error || (isStreaming && activeThinkEnabled))}
		<ThinkingStream content={thinking} {error} {isStreaming} storageKey={activeThinkingStorageKey()} />
	{/if}
</div>

<style>
	.message-area {
		--chat-canvas: var(--bg-soft);
		min-height: 0;
		min-width: 0;
		background: var(--chat-canvas-bg, var(--bg-soft));
		padding: clamp(1rem, 2.4vw, 2rem);
		display: flex;
		flex-direction: column;
		gap: 1.1rem;
		overflow: auto;
		scrollbar-color: var(--scrollbar-thumb) transparent;
	}

	.message-turn {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
	}

	.animate-in {
		animation: message-in 550ms cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
	}

	@keyframes message-in {
		0% {
			opacity: 0;
			transform: translateY(30px) scale(0.92);
		}
		100% {
			opacity: 1;
			transform: translateY(0) scale(1);
		}
	}

	.empty-chat {
		margin: auto;
		padding: 0.7rem 1rem;
		border: 1px solid var(--border);
		border-radius: var(--radius-control);
		background: var(--surface-card);
		color: var(--text-soft);
		font-size: 0.9rem;
	}

	/* Turn-aware mode color overrides — higher specificity than .chat-panel[data-mode] */
	.message-area .message-turn[data-turn-mode='Chat'] {
		--mode-color: #79b8ff;
		--mode-soft: rgba(121, 184, 255, 0.15);
		--mode-border: rgba(121, 184, 255, 0.28);
		--mode-glow: rgba(121, 184, 255, 0.16);
	}

	.message-area .message-turn[data-turn-mode='Plan'] {
		--mode-color: #6ee7b7;
		--mode-soft: rgba(110, 231, 183, 0.14);
		--mode-border: rgba(110, 231, 183, 0.28);
		--mode-glow: rgba(110, 231, 183, 0.14);
	}

	.message-area .message-turn[data-turn-mode='Debug'] {
		--mode-color: #f59e0b;
		--mode-soft: rgba(245, 158, 11, 0.14);
		--mode-border: rgba(245, 158, 11, 0.3);
		--mode-glow: rgba(245, 158, 11, 0.14);
	}

	:global(:root.light) .message-area .message-turn[data-turn-mode='Chat'] {
		--mode-color: #2563eb;
		--mode-soft: rgba(37, 99, 235, 0.13);
		--mode-border: rgba(37, 99, 235, 0.26);
		--mode-glow: rgba(37, 99, 235, 0.18);
	}

	:global(:root.light) .message-area .message-turn[data-turn-mode='Plan'] {
		--mode-color: #047857;
		--mode-soft: rgba(16, 185, 129, 0.18);
		--mode-border: rgba(4, 120, 87, 0.32);
		--mode-glow: rgba(4, 120, 87, 0.18);
	}

	:global(:root.light) .message-area .message-turn[data-turn-mode='Debug'] {
		--mode-color: #b45309;
		--mode-soft: rgba(245, 158, 11, 0.18);
		--mode-border: rgba(180, 83, 9, 0.32);
		--mode-glow: rgba(180, 83, 9, 0.16);
	}
</style>
