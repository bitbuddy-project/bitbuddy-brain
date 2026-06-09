<script lang="ts">
	import { onDestroy } from 'svelte';
	import { renderPlainText } from '$lib/markdown';
	import { maskHtml, revealMaskedChips } from '$lib/mask';
	import type { ChatAttachment } from '$lib/api/bitbuddy';
	import { chatBehavior, replyAnimationConfig } from '$lib/stores/chat-behavior.svelte';
	import FileIcon from 'phosphor-svelte/lib/FileIcon';
	import PencilSimpleIcon from 'phosphor-svelte/lib/PencilSimpleIcon';
	import TrashIcon from 'phosphor-svelte/lib/TrashIcon';
	import ChecksIcon from 'phosphor-svelte/lib/ChecksIcon';
	import ConfirmDialog from '$lib/components/ui/ConfirmDialog.svelte';
	import MarkdownMessage from './MarkdownMessage.svelte';
	import BitBuddyFace from './BitBuddyFace.svelte';

	let { role, content, attachments = [], mode = 'Chat', buddyName, isTyping = false, showFace = false, autonomyIntroKey = '', typingStorageKey = '', createdAt = '', canManage = false, editDisabled = false, onDelete, onEdit, onEditingChange } = $props<{
		role: 'user' | 'assistant';
		content: string;
		attachments?: ChatAttachment[];
		mode?: string;
		buddyName: string;
		isTyping?: boolean;
		showFace?: boolean;
		autonomyIntroKey?: string;
		typingStorageKey?: string;
		createdAt?: string;
		canManage?: boolean;
		editDisabled?: boolean;
		onDelete?: () => void | Promise<void>;
		onEdit?: (content: string) => void | Promise<void>;
		onEditingChange?: (editing: boolean) => void;
	}>();

	let visibleContent = $state('');
	let hasVisibleContent = $state(false);
	let isEditing = $state(false);
	let editContent = $state('');
	let actionBusy = $state(false);
	let deleteConfirmOpen = $state(false);
	let typeTimer: ReturnType<typeof setTimeout> | undefined;
	let introTimer: ReturnType<typeof setTimeout> | undefined;
	let lastTyping = $state(false);
	let showingAutonomyIntro = $state(false);
	let activeAutonomyIntroKey = $state('');
	let shouldType = $derived(role === 'assistant' && isTyping && chatBehavior.replyAnimation !== 'Off');
	let typingConfig = $derived(replyAnimationConfig(chatBehavior.replyAnimation));
	let safeContent = $derived(role === 'assistant' ? stripSystemReminders(content) : content);
	let shouldDelayAutonomyIntro = $derived(
		role === 'assistant' &&
		Boolean(autonomyIntroKey) &&
		Boolean(safeContent) &&
		chatBehavior.replyAnimation !== 'Off' &&
		!typingWasCompleted(typingStorageKey) &&
		messageIsRecent(createdAt) &&
		!autonomyIntroWasShown(autonomyIntroKey)
	);

	function clearTypeTimer() {
		if (!typeTimer) return;
		clearTimeout(typeTimer);
		typeTimer = undefined;
	}

	function clearIntroTimer() {
		if (!introTimer) return;
		clearTimeout(introTimer);
		introTimer = undefined;
	}

	function queueTypeStep() {
		if (typeTimer) return;
		typeTimer = setTimeout(() => {
			typeTimer = undefined;
			if (role !== 'assistant' || (!shouldType && !lastTyping)) {
				visibleContent = safeContent;
				lastTyping = false;
				return;
			}
			if (!safeContent.startsWith(visibleContent) || visibleContent.length > safeContent.length) {
				visibleContent = safeContent;
				lastTyping = false;
				return;
			}
			const remaining = safeContent.length - visibleContent.length;
			if (remaining <= 0) {
				if (!shouldType) {
					lastTyping = false;
					markTypingCompleted(typingStorageKey);
				}
				return;
			}
			const batch = remaining > 80 ? typingConfig.largeBatch : remaining > 32 ? typingConfig.mediumBatch : typingConfig.smallBatch;
			visibleContent += safeContent.slice(visibleContent.length, visibleContent.length + batch);
			if (visibleContent.length < safeContent.length || shouldType) queueTypeStep();
			else {
				lastTyping = false;
				markTypingCompleted(typingStorageKey);
			}
		}, typingConfig.delayMs);
	}

	$effect(() => {
		if (!isEditing) editContent = content;
	});

	$effect(() => {
		if (shouldDelayAutonomyIntro && activeAutonomyIntroKey !== autonomyIntroKey) {
			clearTypeTimer();
			clearIntroTimer();
			activeAutonomyIntroKey = autonomyIntroKey;
			showingAutonomyIntro = true;
			visibleContent = '';
			hasVisibleContent = true;
			lastTyping = false;
			introTimer = setTimeout(() => {
				introTimer = undefined;
				markAutonomyIntroShown(autonomyIntroKey);
				showingAutonomyIntro = false;
				lastTyping = true;
				queueTypeStep();
			}, randomIntroDelayMs());
			return;
		}

		if (showingAutonomyIntro) {
			visibleContent = '';
			hasVisibleContent = true;
			return;
		}

		if (role === 'assistant' && chatBehavior.replyAnimation === 'Off') {
			clearTypeTimer();
			clearIntroTimer();
			visibleContent = safeContent;
			hasVisibleContent = true;
			lastTyping = false;
			showingAutonomyIntro = false;
			markTypingCompleted(typingStorageKey);
			return;
		}

		if (role === 'assistant' && typingWasCompleted(typingStorageKey)) {
			clearTypeTimer();
			clearIntroTimer();
			visibleContent = safeContent;
			hasVisibleContent = true;
			lastTyping = false;
			showingAutonomyIntro = false;
			return;
		}

		if (role === 'assistant' && !shouldType && lastTyping && safeContent.startsWith(visibleContent) && visibleContent.length < safeContent.length) {
			queueTypeStep();
			return;
		}

		if (role !== 'assistant' || !shouldType || safeContent.length === 0) {
			clearTypeTimer();
			if (!lastTyping) visibleContent = safeContent;
			hasVisibleContent = true;
			return;
		}

		if (!lastTyping) {
			clearTypeTimer();
			visibleContent = '';
			hasVisibleContent = true;
			lastTyping = true;
			queueTypeStep();
			return;
		}

		if (!hasVisibleContent) {
			visibleContent = '';
			hasVisibleContent = true;
			queueTypeStep();
			return;
		}

		if (!safeContent.startsWith(visibleContent) || visibleContent.length > safeContent.length) {
			visibleContent = safeContent;
			hasVisibleContent = true;
			return;
		}

		if (visibleContent.length < safeContent.length) queueTypeStep();
	});

	onDestroy(() => {
		clearTypeTimer();
		clearIntroTimer();
		if (isEditing) onEditingChange?.(false);
	});

	let displayedContent = $derived.by(() => {
		let text = hasVisibleContent ? visibleContent : safeContent;
		if (role === 'assistant' && (shouldType || lastTyping) && safeContent.length > 0) text += ' %%BITBUDDY_CARET%%';
		return text;
	});
	let renderedPlainText = $derived(maskHtml(renderPlainText(displayedContent)));
	let timeLabel = $derived(formatTime(createdAt));
	let showMeta = $derived(
		!isEditing && !showingAutonomyIntro && !(role === 'assistant' && showFace && !safeContent)
	);

	function imageSrc(attachment: ChatAttachment) {
		return attachment.data ? `data:${attachment.mime_type};base64,${attachment.data}` : '';
	}

	function formatBytes(bytes: number) {
		if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
		if (bytes >= 1024) return `${Math.ceil(bytes / 1024)} KB`;
		return `${bytes} B`;
	}

	function attachmentKindLabel(attachment: ChatAttachment) {
		if (attachment.kind === 'image') return 'Image';
		if (attachment.kind === 'text') return 'Text file';
		return 'File';
	}

	function randomIntroDelayMs() {
		return 10_000 + Math.floor(Math.random() * 20_001);
	}

	function formatTime(value: string) {
		if (!value) return '';
		const normalized = value.includes('T') ? value : value.replace(' ', 'T') + 'Z';
		const parsed = Date.parse(normalized);
		if (!Number.isFinite(parsed)) return '';
		return new Date(parsed).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
	}

	function stripSystemReminders(value: string) {
		return value.replace(/<system-reminder\b[^>]*>[\s\S]*?(?:<\/system-reminder>|$)/gi, '').trim();
	}

	function messageIsRecent(value: string) {
		if (!value) return true;
		const normalized = value.includes('T') ? value : value.replace(' ', 'T') + 'Z';
		const created = Date.parse(normalized);
		if (!Number.isFinite(created)) return true;
		return Date.now() - created < 60_000;
	}

	function autonomyIntroWasShown(key: string) {
		if (!key || typeof window === 'undefined') return true;
		return window.localStorage.getItem(`bitbuddy:autonomy-intro:${key}`) === 'shown';
	}

	function markAutonomyIntroShown(key: string) {
		if (!key || typeof window === 'undefined') return;
		window.localStorage.setItem(`bitbuddy:autonomy-intro:${key}`, 'shown');
	}

	function typingWasCompleted(key: string) {
		if (!key || typeof window === 'undefined') return false;
		return window.localStorage.getItem(`bitbuddy:${key}`) === 'shown';
	}

	function markTypingCompleted(key: string) {
		if (!key || typeof window === 'undefined') return;
		window.localStorage.setItem(`bitbuddy:${key}`, 'shown');
	}

	async function submitEdit() {
		if (!onEdit || actionBusy) return;
		if (!editContent.trim() && attachments.length === 0) return;
		actionBusy = true;
		try {
			await onEdit(editContent);
			isEditing = false;
			onEditingChange?.(false);
		} finally {
			actionBusy = false;
		}
	}

	function beginEdit() {
		if (actionBusy || editDisabled) return;
		isEditing = true;
		onEditingChange?.(true);
	}

	function cancelEdit() {
		isEditing = false;
		editContent = content;
		onEditingChange?.(false);
	}

	async function deleteTurn() {
		if (!onDelete || actionBusy) return;
		actionBusy = true;
		try {
			await onDelete();
			deleteConfirmOpen = false;
		} finally {
			actionBusy = false;
		}
	}
</script>

<div class:assistant={role === 'assistant'} class:user={role === 'user'} class="message-row">
	{#if role === 'assistant'}
		{#if showFace}
			<BitBuddyFace {isTyping} />
		{:else}
			<div class="avatar avatar-dim">{buddyName.slice(0, 1).toUpperCase()}</div>
		{/if}
	{:else}
		<div class="avatar">Y</div>
	{/if}
	<div class="message-container">
		<span class="sender">{role === 'user' ? 'You' : buddyName}</span>
		<div
			class="message"
			class:editing={isEditing}
			class:typing-active={role === 'assistant' && (isTyping || lastTyping || showingAutonomyIntro)}
			class:dot-only={role === 'assistant' && showingAutonomyIntro}
		>
			{#if attachments.length > 0}
				<div class="message-attachments" aria-label="Message attachments">
					{#each attachments as attachment (attachment.id)}
						<div class:image-attachment={attachment.kind === 'image'} class="message-attachment">
							{#if attachment.kind === 'image' && imageSrc(attachment)}
								<div class="image-frame">
									<img src={imageSrc(attachment)} alt={attachment.name} />
								</div>
								<div class="image-caption">
									<span>{attachment.name}</span>
									<small>{formatBytes(attachment.size)}</small>
								</div>
							{:else}
								<div class="message-file-glyph" aria-hidden="true"><FileIcon size={22} /></div>
								<div class="message-file-meta">
									<span>{attachment.name}</span>
									<small>{attachmentKindLabel(attachment)} · {formatBytes(attachment.size)}</small>
								</div>
							{/if}
						</div>
					{/each}
				</div>
			{/if}
			<div class="content">
				{#if isEditing}
					<textarea bind:value={editContent} rows="4" aria-label="Edit your message"></textarea>
				{:else if role === 'assistant' && showingAutonomyIntro}
					<span class="typing-dots" aria-label={`${buddyName} is about to ask something`}><i></i><i></i><i></i></span>
				{:else if role === 'assistant' && showFace && !content}
					<span class="typing-dots" aria-label={`${buddyName} is preparing a response`}><i></i><i></i><i></i></span>
				{:else if role === 'assistant'}
					<MarkdownMessage content={displayedContent} />
				{:else}
					<span class="plain-text" use:revealMaskedChips>{@html renderedPlainText}</span>
				{/if}
			</div>
			{#if showMeta}
				<div class="meta">
					<span class="mode-tag" title={`${mode} mode`}><i class="mode-dot"></i>{mode}</span>
					{#if timeLabel}<span class="time">{timeLabel}</span>{/if}
					{#if role === 'user'}
						<ChecksIcon class="receipt" size={14} weight="bold" />
					{/if}
				</div>
			{/if}
		</div>
		{#if role === 'user' && canManage}
			{#if isEditing}
				<div class="message-actions editing-actions">
					<span>Editing will remove later messages and rerun from here.</span>
					<button type="button" onclick={cancelEdit} disabled={actionBusy}>Cancel</button>
					<button class="save-rerun-action" type="button" onclick={submitEdit} disabled={actionBusy || (!editContent.trim() && attachments.length === 0)}>
						{actionBusy ? 'Saving...' : 'Save & rerun'}
					</button>
				</div>
			{:else}
				<div class="message-actions">
					<button type="button" onclick={beginEdit} disabled={actionBusy || editDisabled} aria-label="Edit message" title={editDisabled ? 'Finish or cancel the current edit first.' : 'Edit message'}>
						<PencilSimpleIcon size={15} />
						<span>Edit</span>
					</button>
					<button class="danger-action" type="button" onclick={() => (deleteConfirmOpen = true)} disabled={actionBusy || editDisabled} aria-label="Delete message turn" title={editDisabled ? 'Finish or cancel the current edit first.' : 'Delete message turn'}>
						<TrashIcon size={15} />
						<span>Delete</span>
					</button>
				</div>
			{/if}
		{/if}
	</div>
</div>

<ConfirmDialog
	open={deleteConfirmOpen}
	title="Delete this turn?"
	description="This removes your message and BitBuddy's following reply. Later turns stay in the chat."
	confirmLabel="Delete turn"
	destructive
	busy={actionBusy}
	onCancel={() => (deleteConfirmOpen = false)}
	onConfirm={deleteTurn}
/>

<style>
	.message-row {
		max-width: min(76rem, 98%);
		display: grid;
		grid-template-columns: 2.8rem minmax(0, 1fr);
		align-items: start;
		gap: 0.85rem;
		margin-bottom: 0.5rem;
	}

	.message-row.user {
		align-self: flex-end;
		grid-template-columns: minmax(0, 1fr) 2.8rem;
		max-width: min(31rem, 82%);
	}

	.message-row.user .avatar {
		grid-column: 2;
		grid-row: 1;
	}

	.avatar {
		width: 2.2rem;
		height: 2.2rem;
		display: grid;
		place-items: center;
		border: 1px solid color-mix(in srgb, var(--accent) 42%, var(--border));
		border-radius: 999px;
		background:
			radial-gradient(circle at 30% 20%, rgba(255, 255, 255, 0.18), transparent 46%),
			color-mix(in srgb, var(--accent) 22%, var(--panel-raised));
		color: var(--accent-strong);
		font-size: 0.85rem;
		font-weight: 900;
	}

	.avatar-dim {
		opacity: 0.45;
		transform: scale(0.85);
	}

	.message-container {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
	}

	.message-row.user .message-container {
		align-items: flex-end;
	}

	.sender {
		display: block;
		padding: 0 0.25rem;
		color: var(--text-soft);
		font-size: 0.74rem;
		font-weight: 750;
		letter-spacing: 0.02em;
		opacity: 0.85;
	}

	.message {
		--bubble-bg: var(--panel-raised);
		--bubble-border: var(--border-strong);
		position: relative;
		padding: 0.85rem 1rem;
		border: 1px solid var(--bubble-border);
		border-radius: var(--radius-bubble);
		background: var(--bubble-bg);
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.045), var(--shadow-chat);
		backdrop-filter: blur(14px) saturate(1.12);
	}

	/* Tails removed; the asymmetric top-corner notch still hints at the sender side. */
	.message-row.assistant .message {
		--bubble-bg: color-mix(in srgb, #0d1a2c 78%, transparent);
		--bubble-border: rgba(73, 111, 158, 0.38);
		border-top-left-radius: 0.2rem;
		background:
			linear-gradient(145deg, rgba(255, 255, 255, 0.045), transparent 60%),
			var(--bubble-bg);
	}

	.message-row.user .message {
		--bubble-bg: #183b6e;
		--bubble-border: rgba(91, 145, 226, 0.68);
		border-top-right-radius: 0.2rem;
		background:
			linear-gradient(145deg, rgba(255, 255, 255, 0.11), rgba(255, 255, 255, 0.02)),
			var(--bubble-bg);
		box-shadow:
			inset 0 1px 0 rgba(255, 255, 255, 0.08),
			0 10px 26px rgba(24, 59, 110, 0.22);
	}

	:global(:root.light) .message-row.assistant .message {
		--bubble-bg: rgba(241, 247, 253, 0.74);
		--bubble-border: rgba(73, 104, 145, 0.24);
		box-shadow:
			inset 0 1px 0 rgba(255, 255, 255, 0.74),
			0 10px 24px rgba(50, 80, 118, 0.08);
	}

	:global(:root.light) .message-row.user .message {
		--bubble-bg: #2e6fd0;
		--bubble-border: rgba(37, 99, 235, 0.46);
	}

	:global(:root.light) .message-row.user .meta {
		color: rgba(255, 255, 255, 0.7);
	}

	:global(:root.light) .message-row.user .mode-tag {
		color: #7fb3ff;
		opacity: 1;
	}

	:global(:root.light) .message-row.user .meta :global(.receipt) {
		color: #75e0a7;
	}

	:global(:root.light) .message-row.user .mode-dot {
		background: #7fb3ff;
		box-shadow: 0 0 6px rgba(127, 179, 255, 0.5);
	}

	.meta {
		display: flex;
		align-items: center;
		gap: 0.3rem;
		margin-top: 0.4rem;
		color: var(--text-soft);
		font-size: 0.68rem;
		font-weight: 600;
		letter-spacing: 0.02em;
	}

	.message-row.user .meta {
		justify-content: flex-end;
		color: color-mix(in srgb, var(--mode-color, var(--accent)) 60%, var(--text-soft));
	}

	.mode-tag {
		display: inline-flex;
		align-items: center;
		gap: 0.28rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-size: 0.62rem;
		font-weight: 800;
		color: var(--mode-color, var(--accent));
		opacity: 0.85;
	}

	.mode-dot {
		width: 0.4rem;
		height: 0.4rem;
		border-radius: 999px;
		background: var(--mode-color, var(--accent));
		box-shadow: 0 0 6px color-mix(in srgb, var(--mode-color, var(--accent)) 55%, transparent);
	}

	.meta :global(.receipt) {
		color: var(--mode-color, var(--accent));
	}

	.message-row.user .meta :global(.receipt) {
		color: #75e0a7;
	}

	.content {
		color: var(--text);
		font-size: 0.95rem;
		line-height: 1.65;
	}

	.message-row.user .content {
		color: #f5f9ff;
	}

	.typing-dots {
		display: inline-flex;
		align-items: center;
		gap: 0.24rem;
		min-width: 2.1rem;
		padding: 0.34rem 0.1rem;
		color: var(--mode-color, #3b82f6);
	}

	.typing-dots i {
		width: 0.42rem;
		height: 0.42rem;
		border-radius: 999px;
		background: currentColor;
		box-shadow: 0 0 12px var(--mode-glow, rgba(59, 130, 246, 0.38));
		animation: dot-rise 1.15s infinite ease-in-out;
	}

	.typing-dots i:nth-child(2) {
		animation-delay: 0.16s;
	}

	.typing-dots i:nth-child(3) {
		animation-delay: 0.32s;
	}

	@keyframes dot-rise {
		0%, 80%, 100% {
			opacity: 0.35;
			transform: translateY(0) scale(0.86);
		}
		40% {
			opacity: 1;
			transform: translateY(-0.15rem) scale(1.05);
		}
	}

	.message-attachments {
		display: flex;
		align-items: stretch;
		gap: 0.7rem;
		max-width: min(42rem, 76vw);
		margin: 0 0 0.9rem;
		padding: 0 0 0.15rem;
		overflow-x: auto;
		overflow-y: hidden;
		scrollbar-width: thin;
	}

	.message-attachment {
		min-width: 14.5rem;
		height: 4.25rem;
		display: grid;
		grid-template-columns: 2.7rem minmax(0, 1fr);
		align-items: center;
		gap: 0.72rem;
		padding: 0.58rem 0.72rem;
		border: 1px solid color-mix(in srgb, var(--mode-border, var(--border)) 72%, transparent);
		border-radius: 1.05rem;
		background:
			linear-gradient(180deg, rgba(255, 255, 255, 0.09), rgba(255, 255, 255, 0.025)),
			color-mix(in srgb, var(--panel-raised) 72%, transparent);
		background-clip: padding-box;
		box-shadow:
			inset 0 1px 0 rgba(255, 255, 255, 0.08),
			0 6px 16px rgba(0, 0, 0, 0.1);
		overflow: hidden;
		box-sizing: border-box;
	}

	:global(:root.light) .message-attachment {
		border-color: rgba(15, 23, 42, 0.1);
		background:
			linear-gradient(180deg, color-mix(in srgb, var(--panel-raised) 94%, transparent), color-mix(in srgb, var(--panel) 86%, transparent)),
			var(--panel);
		box-shadow: inset 0 1px 0 rgba(148, 184, 218, 0.32);
	}

	.message-attachment.image-attachment {
		min-width: 14rem;
		width: 14rem;
		height: auto;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		padding: 0.42rem 0.42rem 0.65rem;
	}

	.image-frame {
		width: 100%;
		aspect-ratio: 16 / 10;
		padding: 0;
		border-radius: 0.9rem;
		background: rgba(0, 0, 0, 0.18);
		overflow: hidden;
	}

	.image-frame img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		display: block;
	}

	.image-caption {
		min-width: 0;
		padding: 0 0.35rem;
		display: flex;
		flex-direction: column;
		gap: 0.12rem;
	}

	.image-caption span,
	.image-caption small {
		display: block;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 100%;
	}

	.image-caption span {
		font-size: 0.78rem;
		font-weight: 750;
	}

	.image-caption small {
		color: var(--text-soft);
		font-size: 0.7rem;
	}

	.message-file-glyph {
		width: 2.6rem;
		height: 2.6rem;
		display: grid;
		place-items: center;
		border-radius: 0.82rem;
		background: var(--mode-soft);
		color: var(--mode-color);
	}

	:global(:root.light) .message-file-glyph {
		background: rgba(37, 99, 235, 0.1);
		box-shadow: inset 0 0 0 1px rgba(37, 99, 235, 0.08);
	}

	.message-file-meta {
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 0.12rem;
	}

	.message-file-meta span,
	.message-file-meta small {
		display: block;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 100%;
	}

	.message-file-meta span {
		font-size: 0.84rem;
		font-weight: 750;
	}

	.message-file-meta small {
		color: var(--text-soft);
		font-size: 0.72rem;
	}

	.content :global(.typing-caret) {
		display: inline-block;
		width: 0.5ch;
		margin-left: 0.06rem;
		color: var(--mode-color, #3b82f6);
		font-weight: 900;
		line-height: 1;
		vertical-align: baseline;
		box-shadow:
			0 0 0 3px var(--mode-soft, rgba(59, 130, 246, 0.17)),
			0 0 18px var(--mode-glow, rgba(59, 130, 246, 0.46));
		animation: -global-caret-blink 0.95s steps(2, start) infinite;
	}

	.message.typing-active {
		border-color: color-mix(in srgb, var(--mode-color, #3b82f6) 38%, var(--border-strong));
	}

	.message.dot-only {
		width: fit-content;
		padding: 0.55rem 0.7rem;
		border-radius: 999px;
	}

	.message.dot-only .content {
		line-height: 1;
	}

	.message.dot-only .typing-dots {
		min-width: 1.75rem;
		padding: 0.08rem 0;
	}

	.message.editing {
		width: min(40rem, 76vw);
		padding: 0.75rem;
	}

	.content textarea {
		width: 100%;
		min-height: 7rem;
		resize: none;
		border: 1px solid var(--mode-border, var(--border));
		border-radius: 0.9rem;
		background: var(--surface-inset);
		color: var(--text);
		font: inherit;
		line-height: 1.55;
		padding: 0.85rem;
	}

	.message-row.user .content textarea {
		color: #fff;
		caret-color: #fff;
	}

	:global(:root.light) .message-row.user .content textarea {
		border-color: rgba(255, 255, 255, 0.34);
		background: color-mix(in srgb, var(--bubble-bg) 68%, #0f3c78);
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.12);
	}

	.content textarea:focus {
		outline: none;
		border-color: var(--mode-color);
		box-shadow: 0 0 0 3px var(--mode-soft);
	}

	.message-actions {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 0.45rem;
		padding-right: 0.15rem;
		opacity: 0.72;
		transition: opacity 140ms ease;
	}

	.message-container:hover .message-actions,
	.message-actions:focus-within {
		opacity: 1;
	}

	.message-actions button {
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		padding: 0.36rem 0.55rem;
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		background: var(--panel);
		color: var(--text-soft);
		font-size: 0.72rem;
		font-weight: 800;
		transition: 140ms ease;
	}

	.message-actions button:hover:not(:disabled) {
		border-color: var(--mode-border, var(--border-strong));
		color: var(--text);
		transform: translateY(-1px);
	}

	.message-actions .danger-action:hover:not(:disabled) {
		border-color: rgba(248, 113, 113, 0.42);
		color: var(--danger);
	}

	.message-actions .save-rerun-action {
		border-color: var(--mode-color);
		background: var(--mode-color);
		color: #fff;
	}

	.message-actions .save-rerun-action:hover:not(:disabled) {
		color: #fff;
	}

	.message-actions button:disabled {
		cursor: not-allowed;
		opacity: 0.55;
	}

	.editing-actions {
		max-width: min(40rem, 76vw);
		flex-wrap: wrap;
	}

	.editing-actions span {
		margin-right: auto;
		color: var(--text-soft);
		font-size: 0.72rem;
		font-weight: 700;
	}

	@keyframes -global-caret-blink {
		50% {
			opacity: 0.34;
		}
	}

	@media (max-width: 760px) {
		.message-row,
		.message-row.user {
			max-width: 100%;
		}

		.message.editing,
		.editing-actions {
			width: 100%;
			max-width: 100%;
		}

		.message-actions {
			opacity: 1;
		}
	}
</style>
