<script lang="ts">
	import { onDestroy } from 'svelte';
	import { renderPlainText } from '$lib/markdown';
	import type { ChatAttachment } from '$lib/api/bitbuddy';
	import { chatBehavior, replyAnimationConfig } from '$lib/stores/chat-behavior.svelte';
	import FileIcon from 'phosphor-svelte/lib/FileIcon';
	import PencilSimpleIcon from 'phosphor-svelte/lib/PencilSimpleIcon';
	import TrashIcon from 'phosphor-svelte/lib/TrashIcon';
	import ConfirmDialog from '$lib/components/ui/ConfirmDialog.svelte';
	import MarkdownMessage from './MarkdownMessage.svelte';
	import BitBuddyFace from './BitBuddyFace.svelte';

	let { role, content, attachments = [], buddyName, isTyping = false, showFace = false, autonomyIntroKey = '', typingStorageKey = '', createdAt = '', canManage = false, onDelete, onEdit } = $props<{
		role: 'user' | 'assistant';
		content: string;
		attachments?: ChatAttachment[];
		buddyName: string;
		isTyping?: boolean;
		showFace?: boolean;
		autonomyIntroKey?: string;
		typingStorageKey?: string;
		createdAt?: string;
		canManage?: boolean;
		onDelete?: () => void | Promise<void>;
		onEdit?: (content: string) => void | Promise<void>;
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
	let shouldDelayAutonomyIntro = $derived(
		role === 'assistant' &&
		Boolean(autonomyIntroKey) &&
		Boolean(content) &&
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
				visibleContent = content;
				lastTyping = false;
				return;
			}
			if (!content.startsWith(visibleContent) || visibleContent.length > content.length) {
				visibleContent = content;
				lastTyping = false;
				return;
			}
			const remaining = content.length - visibleContent.length;
			if (remaining <= 0) {
				if (!shouldType) {
					lastTyping = false;
					markTypingCompleted(typingStorageKey);
				}
				return;
			}
			const batch = remaining > 80 ? typingConfig.largeBatch : remaining > 32 ? typingConfig.mediumBatch : typingConfig.smallBatch;
			visibleContent += content.slice(visibleContent.length, visibleContent.length + batch);
			if (visibleContent.length < content.length || shouldType) queueTypeStep();
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
			visibleContent = content;
			hasVisibleContent = true;
			lastTyping = false;
			showingAutonomyIntro = false;
			markTypingCompleted(typingStorageKey);
			return;
		}

		if (role === 'assistant' && typingWasCompleted(typingStorageKey)) {
			clearTypeTimer();
			clearIntroTimer();
			visibleContent = content;
			hasVisibleContent = true;
			lastTyping = false;
			showingAutonomyIntro = false;
			return;
		}

		if (role === 'assistant' && !shouldType && lastTyping && content.startsWith(visibleContent) && visibleContent.length < content.length) {
			queueTypeStep();
			return;
		}

		if (role !== 'assistant' || !shouldType || content.length === 0) {
			clearTypeTimer();
			if (!lastTyping) visibleContent = content;
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

		if (!content.startsWith(visibleContent) || visibleContent.length > content.length) {
			visibleContent = content;
			hasVisibleContent = true;
			return;
		}

		if (visibleContent.length < content.length) queueTypeStep();
	});

	onDestroy(() => {
		clearTypeTimer();
		clearIntroTimer();
	});

	let displayedContent = $derived.by(() => {
		let text = hasVisibleContent ? visibleContent : content;
		if (role === 'assistant' && (shouldType || lastTyping) && content.length > 0) text += ' %%BITBUDDY_CARET%%';
		return text;
	});
	let renderedPlainText = $derived(renderPlainText(displayedContent));

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
		} finally {
			actionBusy = false;
		}
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
					{@html renderedPlainText}
				{/if}
			</div>
		</div>
		{#if role === 'user' && canManage}
			{#if isEditing}
				<div class="message-actions editing-actions">
					<span>Editing will remove later messages and rerun from here.</span>
					<button type="button" onclick={() => { isEditing = false; editContent = content; }} disabled={actionBusy}>Cancel</button>
					<button class="primary-action" type="button" onclick={submitEdit} disabled={actionBusy || (!editContent.trim() && attachments.length === 0)}>
						{actionBusy ? 'Saving...' : 'Save & rerun'}
					</button>
				</div>
			{:else}
				<div class="message-actions">
					<button type="button" onclick={() => (isEditing = true)} disabled={actionBusy} aria-label="Edit message">
						<PencilSimpleIcon size={15} />
						<span>Edit</span>
					</button>
					<button class="danger-action" type="button" onclick={() => (deleteConfirmOpen = true)} disabled={actionBusy} aria-label="Delete message turn">
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
		border: 1px solid var(--mode-border, var(--border));
		border-radius: 0.85rem;
		background:
			radial-gradient(circle at 30% 20%, rgba(255, 255, 255, 0.22), transparent 44%),
			var(--mode-soft);
		color: var(--mode-color);
		font-size: 0.85rem;
		font-weight: 900;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
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
		color: var(--mode-color);
		font-size: 0.78rem;
		font-weight: 800;
		letter-spacing: 0.02em;
		opacity: 0.9;
	}

	.message {
		padding: 1.3rem 1.1rem;
		border: 1px solid var(--border-strong);
		border-radius: 1.15rem;
		background:
			linear-gradient(180deg, var(--glass-overlay, rgba(255, 255, 255, 0.04)), rgba(255, 255, 255, 0.01)),
			var(--panel-raised);
		box-shadow: var(--shadow-soft);
	}

	.message-row.user .message {
		border-color: var(--mode-border, var(--border));
		background:
			linear-gradient(180deg, var(--glass-overlay, rgba(255, 255, 255, 0.06)), rgba(255, 255, 255, 0.01)),
			var(--mode-soft);
	}

	.content {
		color: var(--text);
		font-size: 0.96rem;
		line-height: 1.65;
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
		border-radius: 999px;
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

	.message-actions .primary-action {
		border-color: var(--mode-color);
		background: var(--mode-color);
		color: var(--on-accent);
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
