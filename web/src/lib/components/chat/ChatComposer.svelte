<script lang="ts">
	import { tick } from 'svelte';
	import ArrowUpIcon from 'phosphor-svelte/lib/ArrowUpIcon';
	import FileIcon from 'phosphor-svelte/lib/FileIcon';
	import MicrophoneIcon from 'phosphor-svelte/lib/MicrophoneIcon';
	import PlusIcon from 'phosphor-svelte/lib/PlusIcon';
	import LightbulbIcon from 'phosphor-svelte/lib/LightbulbIcon';
	import XIcon from 'phosphor-svelte/lib/XIcon';
	import type { ChatAttachment, ProviderContext } from '$lib/api/bitbuddy';
	import { chatSession, type PendingChatAttachment } from '$lib/stores/chat.svelte';
	import SelectMenu from '$lib/components/ui/SelectMenu.svelte';
	import { REASONING_EFFORT_OPTIONS } from '$lib/providerModels';

	let { mode, buddyName, contextUsage, thinkEnabled, thinkingLevel, reasoningEffortVisible, disabled, isStreaming, onDraftChange, onSend, onStop, onThinkToggle, onThinkingLevelChange } = $props<{
		mode: string;
		buddyName: string;
		contextUsage: ProviderContext | null;
		thinkEnabled: boolean;
		thinkingLevel: string;
		reasoningEffortVisible: boolean;
		disabled: boolean;
		isStreaming: boolean;
		onDraftChange: (draft: string) => void;
		onSend: (message: string, attachments?: ChatAttachment[]) => void;
		onStop: () => void;
		onThinkToggle: () => void;
		onThinkingLevelChange: (level: string) => void;
	}>();


	let draft = $derived.by(() => chatSession.draft);
	let attachments = $derived.by(() => chatSession.attachments);
	let messageHistory = $derived.by(() => chatSession.messages.filter((message) => message.role === 'user' && message.content.trim()).map((message) => message.content));
	let charCount = $derived(draft.length);
	let wordCount = $derived(draft.trim() ? draft.trim().split(/\s+/).length : 0);
	let contextText = $derived(formatContextWindow(contextUsage));
	let hasOutgoingDraft = $derived(Boolean(draft.trim()) || attachments.length > 0);

	let textarea: HTMLTextAreaElement;
	let fileInput: HTMLInputElement;
	let composerBar: HTMLDivElement;
	let measureBox: HTMLDivElement;
	let isMultiLine = $state(false);
	let uploadError = $state('');
	let historyIndex = $state(-1);
	let draftBeforeHistory = $state('');
	let historyChatId = $state('');

	let resizeObserver: ResizeObserver | null = null;
	let pendingFrame = 0;
	let lastMeasuredInlineWidth = 0;

	const MAX_TEXTAREA_HEIGHT = 192;
	const MAX_ATTACHMENTS = 8;
	const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
	const MAX_TEXT_BYTES = 10 * 1024 * 1024;
	const MAX_FILE_BYTES = 10 * 1024 * 1024;

	// These match the CSS widths below. Measurement is based on the single-line
	// layout so the component cannot flicker between one-line and multi-line.
	const INLINE_PLUS_REM = 4.35;
	const INLINE_THINK_REM = 5.45;
	// Combined thinking-level pill (cloud providers) replaces the Think button slot.
	const INLINE_LEVEL_REM = 6.6;
	const INLINE_ACTIONS_REM = 7.35;
	const INPUT_WRAP_HORIZONTAL_PADDING_REM = 2.9;
	const MIN_MEASURE_WIDTH = 120;

	function queueLayout() {
		if (pendingFrame) return;

		pendingFrame = requestAnimationFrame(() => {
			pendingFrame = 0;
			updateLayout();
		});
	}

	function updateLayout() {
		if (!textarea || !composerBar || !measureBox) return;

		const inlineWidth = getSingleLineTextareaWidth();
		const textareaStyle = getComputedStyle(textarea);
		const lineHeight = getLineHeight(textareaStyle);
		const paddingBlock = parseFloat(textareaStyle.paddingTop) + parseFloat(textareaStyle.paddingBottom);
		const singleLineHeight = Math.ceil(lineHeight + paddingBlock);

		measureBox.style.width = `${inlineWidth}px`;
		measureBox.textContent = `${chatSession.draft || ' '}\u200b`;

		const measuredHeight = Math.ceil(measureBox.scrollHeight);
		const nextIsMultiLine = chatSession.draft.includes('\n') || measuredHeight > singleLineHeight + 1;

		if (isMultiLine !== nextIsMultiLine) {
			isMultiLine = nextIsMultiLine;
		}

		void tick().then(resizeTextarea);
	}

	function resizeTextarea() {
		if (!textarea) return;

		const textareaStyle = getComputedStyle(textarea);
		const lineHeight = getLineHeight(textareaStyle);
		const paddingBlock = parseFloat(textareaStyle.paddingTop) + parseFloat(textareaStyle.paddingBottom);
		const singleLineHeight = Math.ceil(lineHeight + paddingBlock);

		textarea.style.height = 'auto';
		const nextHeight = Math.max(singleLineHeight, Math.min(textarea.scrollHeight, MAX_TEXTAREA_HEIGHT));
		textarea.style.height = `${nextHeight}px`;
	}

	function getSingleLineTextareaWidth() {
		const barStyle = getComputedStyle(composerBar);
		const barPadding = parseFloat(barStyle.paddingLeft) + parseFloat(barStyle.paddingRight);
		const contentWidth = composerBar.clientWidth - barPadding;
		// Cloud providers show the combined level pill in place of the Think button.
		const thinkSlotWidth = reasoningEffortVisible ? INLINE_LEVEL_REM : INLINE_THINK_REM;
		const inlineControlsWidth = remToPx(INLINE_PLUS_REM + thinkSlotWidth + INLINE_ACTIONS_REM + INPUT_WRAP_HORIZONTAL_PADDING_REM);
		return Math.max(MIN_MEASURE_WIDTH, Math.floor(contentWidth - inlineControlsWidth));
	}

	function getLineHeight(style: CSSStyleDeclaration) {
		const parsed = parseFloat(style.lineHeight);
		if (Number.isFinite(parsed)) return parsed;

		const fontSize = parseFloat(style.fontSize);
		return Number.isFinite(fontSize) ? fontSize * 1.5 : 22;
	}

	function remToPx(rem: number) {
		const rootFontSize = parseFloat(getComputedStyle(document.documentElement).fontSize);
		return rem * (Number.isFinite(rootFontSize) ? rootFontSize : 16);
	}

	$effect(() => {
		chatSession.draft;
		queueLayout();
	});

	$effect(() => {
		if (historyChatId === chatSession.currentChatId) return;
		resetMessageHistory();
		historyChatId = chatSession.currentChatId;
	});

	$effect(() => {
		if (!composerBar) return;

		resizeObserver?.disconnect();
		lastMeasuredInlineWidth = getSingleLineTextareaWidth();

		resizeObserver = new ResizeObserver(() => {
			const nextWidth = getSingleLineTextareaWidth();
			if (Math.abs(nextWidth - lastMeasuredInlineWidth) < 1) return;
			lastMeasuredInlineWidth = nextWidth;
			queueLayout();
		});

		resizeObserver.observe(composerBar);

		return () => {
			resizeObserver?.disconnect();
			resizeObserver = null;
			if (pendingFrame) {
				cancelAnimationFrame(pendingFrame);
				pendingFrame = 0;
			}
		};
	});

	function submit() {
		const message = draft.trim();
		if ((!message && attachments.length === 0) || disabled) return;
		const outgoing = attachments.map(({ previewUrl, ...attachment }) => attachment);
		resetMessageHistory();
		chatSession.draft = '';
		clearAttachments(true);
		onDraftChange('');
		onSend(message, outgoing);
		queueLayout();
	}

	function handleDraftInput() {
		resetMessageHistory();
		onDraftChange(chatSession.draft);
		queueLayout();
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Enter' && !event.shiftKey) {
			event.preventDefault();
			submit();
			return;
		}

		if (event.key === 'ArrowUp') {
			if (!canNavigateHistory('up', event)) return;
			event.preventDefault();
			navigateMessageHistory('up');
			return;
		}

		if (event.key === 'ArrowDown') {
			if (!canNavigateHistory('down', event)) return;
			event.preventDefault();
			navigateMessageHistory('down');
		}
	}

	function canNavigateHistory(direction: 'up' | 'down', event: KeyboardEvent) {
		if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.isComposing) return false;
		if (messageHistory.length === 0) return false;
		if (!textarea) return false;
		if (direction === 'down' && historyIndex < 0) return false;

		const selectionStart = textarea.selectionStart ?? 0;
		const selectionEnd = textarea.selectionEnd ?? 0;
		if (selectionStart !== selectionEnd) return false;

		return direction === 'up' ? cursorIsOnFirstLine(selectionStart) : cursorIsOnLastLine(selectionStart);
	}

	function navigateMessageHistory(direction: 'up' | 'down') {
		if (direction === 'up') {
			if (historyIndex === -1) {
				draftBeforeHistory = chatSession.draft;
				historyIndex = messageHistory.length - 1;
			} else {
				historyIndex = Math.max(0, historyIndex - 1);
			}
		} else if (historyIndex >= 0) {
			historyIndex += 1;
			if (historyIndex >= messageHistory.length) {
				applyDraftFromHistory(draftBeforeHistory);
				resetMessageHistory();
				return;
			}
		}

		applyDraftFromHistory(messageHistory[historyIndex] ?? '');
	}

	function applyDraftFromHistory(value: string) {
		chatSession.draft = value;
		onDraftChange(value);
		queueLayout();
		void tick().then(() => {
			const end = chatSession.draft.length;
			textarea?.setSelectionRange(end, end);
		});
	}

	function resetMessageHistory() {
		historyIndex = -1;
		draftBeforeHistory = '';
	}

	function cursorIsOnFirstLine(position: number) {
		return !chatSession.draft.slice(0, position).includes('\n');
	}

	function cursorIsOnLastLine(position: number) {
		return !chatSession.draft.slice(position).includes('\n');
	}

	function openFilePicker() {
		fileInput?.click();
	}

	async function handleFileSelection(event: Event) {
		const input = event.currentTarget as HTMLInputElement;
		const files = Array.from(input.files ?? []);
		input.value = '';
		if (!files.length) return;

		uploadError = '';
		for (const file of files) {
			if (chatSession.attachments.length >= MAX_ATTACHMENTS) {
				uploadError = `Up to ${MAX_ATTACHMENTS} files can be attached.`;
				break;
			}

			try {
				const attachment = await attachmentFromFile(file);
				chatSession.attachments = [...chatSession.attachments, attachment];
			} catch (error) {
				uploadError = error instanceof Error ? error.message : `Could not attach ${file.name}.`;
			}
		}
		queueLayout();
	}

	async function attachmentFromFile(file: File): Promise<PendingChatAttachment> {
		const type = file.type || guessMimeType(file.name);
		const base = {
			id: crypto.randomUUID(),
			name: file.name,
			mime_type: type || 'application/octet-stream',
			size: file.size
		};

		if (type.startsWith('image/')) {
			if (file.size > MAX_IMAGE_BYTES) throw new Error(`${file.name} is larger than 10 MB.`);
			const normalized = await normalizeImageForProvider(file);
			return {
				...base,
				name: normalized.name,
				mime_type: normalized.mimeType,
				kind: 'image',
				data: normalized.data,
				previewUrl: URL.createObjectURL(file)
			};
		}

		if (isTextLike(file, type)) {
			if (file.size > MAX_TEXT_BYTES) throw new Error(`${file.name} is larger than 10 MB.`);
			return {
				...base,
				kind: 'text',
				text: await file.text()
			};
		}

		if (file.size > MAX_FILE_BYTES) throw new Error(`${file.name} is larger than 10 MB.`);
		return { ...base, kind: 'file' };
	}

	function fileToBase64(file: File): Promise<string> {
		return new Promise((resolve, reject) => {
			const reader = new FileReader();
			reader.onload = () => resolve(String(reader.result ?? '').split(',')[1] ?? '');
			reader.onerror = () => reject(new Error(`Could not read ${file.name}.`));
			reader.readAsDataURL(file);
		});
	}

	async function normalizeImageForProvider(file: File): Promise<{ name: string; mimeType: string; data: string }> {
		try {
			return await normalizeImageWithBitmap(file);
		} catch {
			return await normalizeImageWithElement(file);
		}
	}

	async function normalizeImageWithBitmap(file: File): Promise<{ name: string; mimeType: string; data: string }> {
		const bitmap = await createImageBitmap(file);
		try {
			return await canvasImageToPng(bitmap, file.name);
		} finally {
			bitmap.close();
		}
	}

	function normalizeImageWithElement(file: File): Promise<{ name: string; mimeType: string; data: string }> {
		return new Promise((resolve, reject) => {
			const url = URL.createObjectURL(file);
			const image = new Image();
			image.onload = () => {
				void canvasImageToPng(image, file.name)
					.then(resolve)
					.catch(reject)
					.finally(() => URL.revokeObjectURL(url));
			};
			image.onerror = () => {
				URL.revokeObjectURL(url);
				reject(new Error(`${file.name} could not be converted to PNG for the vision model.`));
			};
			image.src = url;
		});
	}

	async function canvasImageToPng(source: ImageBitmap | HTMLImageElement, originalName: string): Promise<{ name: string; mimeType: string; data: string }> {
		const width = source instanceof HTMLImageElement ? source.naturalWidth : source.width;
		const height = source instanceof HTMLImageElement ? source.naturalHeight : source.height;
		const canvas = document.createElement('canvas');
		canvas.width = width;
		canvas.height = height;
		const context = canvas.getContext('2d');
		if (!context) throw new Error('Canvas is not available.');
		context.drawImage(source, 0, 0);
		const name = imageNameWithExtension(originalName, 'png');
		const blob = await canvasToBlob(canvas, 'image/png');
		return {
			name,
			mimeType: 'image/png',
			data: await fileToBase64(blobToFile(blob, name))
		};
	}

	function canvasToBlob(canvas: HTMLCanvasElement, type: string): Promise<Blob> {
		return new Promise((resolve, reject) => {
			canvas.toBlob((blob) => {
				if (blob) resolve(blob);
				else reject(new Error('Could not encode image.'));
			}, type);
		});
	}

	function blobToFile(blob: Blob, name: string) {
		return new File([blob], name, { type: blob.type || 'image/png' });
	}

	function imageNameWithExtension(name: string, extension: string) {
		return name.replace(/\.[^.]*$/, '') + `.${extension}`;
	}

	function removeAttachment(id: string) {
		const removed = chatSession.attachments.find((attachment) => attachment.id === id);
		if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl);
		chatSession.attachments = chatSession.attachments.filter((attachment) => attachment.id !== id);
		queueLayout();
	}

	function clearAttachments(revoke = true) {
		if (revoke) {
			for (const attachment of chatSession.attachments) {
				if (attachment.previewUrl) URL.revokeObjectURL(attachment.previewUrl);
			}
		}
		chatSession.attachments = [];
		uploadError = '';
	}

	function isTextLike(file: File, type: string) {
		const name = file.name.toLowerCase();
		return type.startsWith('text/') || /\.(txt|md|markdown|json|jsonl|csv|log|yaml|yml|toml|xml|html|htm|xhtml|css|js|mjs|cjs|ts|tsx|jsx|svelte|rs|py|go)$/i.test(name);
	}

	function guessMimeType(name: string) {
		if (/\.(md|markdown)$/i.test(name)) return 'text/markdown';
		if (/\.(html|htm)$/i.test(name)) return 'text/html';
		if (/\.xhtml$/i.test(name)) return 'application/xhtml+xml';
		if (/\.json$/i.test(name)) return 'application/json';
		if (/\.jsonl$/i.test(name)) return 'application/jsonl';
		if (/\.(yaml|yml)$/i.test(name)) return 'application/yaml';
		if (/\.css$/i.test(name)) return 'text/css';
		if (/\.(js|mjs|cjs)$/i.test(name)) return 'text/javascript';
		if (/\.(ts|tsx)$/i.test(name)) return 'text/typescript';
		return '';
	}

	function formatBytes(bytes: number) {
		if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
		if (bytes >= 1024) return `${Math.ceil(bytes / 1024)} KB`;
		return `${bytes} B`;
	}

	function formatContextWindow(context: ProviderContext | null): string {
		if (!context) return 'Context: unknown';
		const model = context.model || context.provider || 'model';
		const used = typeof context.used_tokens === 'number' ? formatTokens(context.used_tokens) : 'unknown';
		const total = typeof context.context_window_tokens === 'number' ? formatTokens(context.context_window_tokens) : 'unknown';
		return `Context: ${used} / ${total} · ${model}`;
	}

	function formatTokens(tokens: number): string {
		if (tokens >= 1000) {
			const rounded = tokens % 1000 === 0 ? String(tokens / 1000) : (tokens / 1000).toFixed(1);
			return `${rounded}k`;
		}
		return String(tokens);
	}
</script>

{#snippet PlusButton()}
	<button class="composer-icon plus-button" type="button" aria-label="Attach files or images" onclick={openFilePicker}>
		<PlusIcon size={20} />
	</button>
{/snippet}

{#snippet ThinkButton()}
	<button class="think-button" class:active={thinkEnabled} type="button" aria-label={thinkEnabled ? 'Turn thinking off' : 'Turn thinking on'} aria-pressed={thinkEnabled} onclick={onThinkToggle}>
		<LightbulbIcon size={21} />
		<span>Think</span>
	</button>
{/snippet}

{#snippet LevelIcon()}
	<LightbulbIcon size={18} />
{/snippet}

{#snippet ThinkingLevel()}
	<div class="level-select" class:off={thinkingLevel === 'off'}>
		<SelectMenu
			value={thinkingLevel}
			options={REASONING_EFFORT_OPTIONS}
			ariaLabel="Thinking level"
			compact
			leading={LevelIcon}
			onChange={onThinkingLevelChange}
		/>
	</div>
{/snippet}

<!-- Cloud providers expose reasoning levels, so the Think on/off toggle and the level
     are merged into one control; local providers keep the plain Think toggle. -->
{#snippet ThinkControl()}
	{#if reasoningEffortVisible}
		{@render ThinkingLevel()}
	{:else}
		{@render ThinkButton()}
	{/if}
{/snippet}

{#snippet RightButtons()}
	<div class="right-actions-group">
		<button class="composer-icon mic-button" type="button" aria-label="Start voice input">
			<MicrophoneIcon size={20} />
		</button>
		{#if isStreaming && !hasOutgoingDraft}
			<button class="send-button stop-button" type="button" aria-label="Stop response" onclick={onStop}>
				<span class="stop-square" aria-hidden="true"></span>
			</button>
		{:else}
			<button class="send-button" disabled={disabled || !hasOutgoingDraft} type="submit" aria-label={isStreaming ? 'Queue steering message' : 'Send message'}>
				<ArrowUpIcon size={18} weight="bold" />
			</button>
		{/if}
	</div>
{/snippet}

<form class="composer" onsubmit={(event) => { event.preventDefault(); submit(); }}>
	<input
		bind:this={fileInput}
		class="file-input"
		type="file"
		multiple
		accept="image/*,text/html,.txt,.md,.markdown,.json,.jsonl,.csv,.log,.yaml,.yml,.toml,.xml,.html,.htm,.xhtml,.css,.js,.mjs,.cjs,.ts,.tsx,.jsx,.svelte,.rs,.py,.go"
		onchange={handleFileSelection}
	/>

	{#if attachments.length > 0}
		<div class="attachment-strip" aria-label="Attached files">
			{#each attachments as attachment (attachment.id)}
				<div class:image-card={attachment.kind === 'image'} class="attachment-card">
					{#if attachment.kind === 'image' && attachment.previewUrl}
						<img src={attachment.previewUrl} alt={attachment.name} />
					{:else}
						<div class="file-glyph" aria-hidden="true"><FileIcon size={24} /></div>
					{/if}
					<div class="attachment-meta">
						<span class="attachment-name">{attachment.name}</span>
						<span class="attachment-size">{formatBytes(attachment.size)}</span>
					</div>
					<button class="remove-attachment" type="button" aria-label={`Remove ${attachment.name}`} onclick={() => removeAttachment(attachment.id)}>
						<XIcon size={14} weight="bold" />
					</button>
				</div>
			{/each}
		</div>
	{/if}

	{#if uploadError}
		<div class="upload-error">{uploadError}</div>
	{/if}

	<div bind:this={composerBar} class="composer-bar" class:multi-line={isMultiLine}>
		<div class="top-row">
			<div class="inline-plus-wrap" aria-hidden={isMultiLine}>
				{@render PlusButton()}
			</div>

			<div class="composer-input-wrap">
				<textarea
					bind:this={textarea}
					bind:value={chatSession.draft}
					aria-label={`Message ${buddyName}`}
					placeholder={`${mode} with ${buddyName}...`}
					rows="1"
					oninput={handleDraftInput}
					onkeydown={handleKeydown}
				></textarea>

				<div class="inline-think-wrap" class:level={reasoningEffortVisible} aria-hidden={isMultiLine}>
					{@render ThinkControl()}
				</div>
			</div>

			<div class="inline-actions-wrap" aria-hidden={isMultiLine}>
				{@render RightButtons()}
			</div>
		</div>

		<div class="bottom-row" aria-hidden={!isMultiLine}>
			<div class="bottom-controls">
				<div class="controls-left">
					{@render PlusButton()}
				</div>
				<div class="controls-right">
					{@render ThinkControl()}
					{@render RightButtons()}
				</div>
			</div>
		</div>

		<div bind:this={measureBox} class="textarea-measure" aria-hidden="true"></div>
	</div>

	<div class="composer-footer">
		<div class="stats">
			<span>{wordCount} words</span>
			<span>{charCount} chars</span>
		</div>
		<div class="context-info">
			{contextText}
		</div>
	</div>
</form>

<style>
	.composer {
		padding: 0.85rem 1.6rem 1.05rem;
		border-top: 0;
		background: transparent;
		min-width: 0;
	}

	.file-input {
		position: absolute;
		width: 1px;
		height: 1px;
		opacity: 0;
		pointer-events: none;
	}

	.attachment-strip {
		display: flex;
		gap: 0.65rem;
		min-width: 0;
		max-width: 60rem;
		margin: 0 auto 0.6rem;
		padding: 0.05rem 0.05rem 0.25rem;
		overflow-x: auto;
		overflow-y: hidden;
		scrollbar-width: thin;
	}

	.attachment-card {
		position: relative;
		width: 10rem;
		min-width: 10rem;
		height: 8.45rem;
		display: flex;
		flex-direction: column;
		justify-content: space-between;
		gap: 0.55rem;
		padding: 0.7rem 0.75rem 0.65rem;
		border: 1px solid var(--border);
		border-radius: 1rem;
		background: var(--surface-card);
		background-clip: padding-box;
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
		overflow: hidden;
		box-sizing: border-box;
	}

	:global(:root.light) .attachment-card {
		border-color: rgba(15, 23, 42, 0.1);
		background:
			linear-gradient(180deg, color-mix(in srgb, var(--panel-raised) 94%, transparent), color-mix(in srgb, var(--panel) 86%, transparent)),
			var(--panel);
		box-shadow: inset 0 1px 0 rgba(148, 184, 218, 0.32);
	}

	.attachment-card.image-card {
		width: 8.65rem;
		min-width: 8.65rem;
		height: 8.45rem;
		padding: 0.35rem 0.35rem 0.65rem;
	}

	.attachment-card img {
		width: 100%;
		height: 6.25rem;
		object-fit: cover;
		border-radius: 0.8rem;
	}

	.file-glyph {
		width: 3.25rem;
		height: 3.25rem;
		display: grid;
		place-items: center;
		border-radius: 0.75rem;
		background: var(--mode-soft);
		color: var(--mode-color);
		margin-top: 0.25rem;
	}

	:global(:root.light) .file-glyph {
		background: rgba(37, 99, 235, 0.1);
		box-shadow: inset 0 0 0 1px rgba(37, 99, 235, 0.08);
	}

	.attachment-meta {
		width: 100%;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 0.16rem;
	}

	.attachment-name,
	.attachment-size {
		display: block;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		max-width: 100%;
	}

	.attachment-name {
		color: var(--text);
		font-size: 0.82rem;
		font-weight: 700;
	}

	.attachment-size {
		color: var(--text-soft);
		font-size: 0.72rem;
	}

	.remove-attachment {
		position: absolute;
		top: 0.25rem;
		right: 0.25rem;
		width: 1.35rem;
		height: 1.35rem;
		display: grid;
		place-items: center;
		border-radius: 999px;
		background: rgba(0, 0, 0, 0.58);
		color: #fff;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.25);
	}

	.remove-attachment:hover {
		background: var(--danger, #ef4444);
	}

	.upload-error {
		max-width: 60rem;
		margin: 0 auto;
		padding: 0 0.6rem 0.45rem;
		color: var(--danger, #ef4444);
		font-size: 0.76rem;
	}

	.composer-bar {
		--composer-edge-bg: color-mix(in srgb, var(--mode-color) 9%, #07101d);
		--composer-mid-bg: color-mix(in srgb, var(--mode-color) 9%, #081322);
		--composer-left-width: 4.35rem;
		--composer-right-width: 7.35rem;
		--composer-stroke: color-mix(in srgb, var(--mode-color) 34%, rgba(148, 163, 184, 0.48));

		width: 100%;
		max-width: 72rem;
		margin: 0 auto;
		padding: 0;
		position: relative;
		display: flex;
		flex-direction: column;

		border: 1px solid transparent;
		border-radius: 1.42rem;

		background:
			linear-gradient(180deg, rgba(12, 26, 46, 0.98), rgba(6, 15, 28, 0.98)),
			var(--composer-edge-bg);

		box-shadow:
			0 0 18px color-mix(in srgb, var(--mode-color) 7%, transparent),
			0 18px 42px rgba(0, 0, 0, 0.32),
			inset 0 1px 0 rgba(255, 255, 255, 0.07);

		overflow: hidden;

		transition:
			border-color 160ms ease,
			box-shadow 160ms ease,
			border-radius 180ms cubic-bezier(0.22, 1, 0.36, 1),
			padding 180ms cubic-bezier(0.22, 1, 0.36, 1);
	}

	.composer-bar::after {
		content: '';
		position: absolute;
		inset: 0;
		z-index: 2;
		box-sizing: border-box;
		border: 2px solid var(--composer-stroke);
		border-radius: inherit;
		pointer-events: none;
	}

	.composer-bar:focus-within {
		--composer-stroke: color-mix(in srgb, var(--mode-color) 62%, rgba(226, 232, 240, 0.5));
		box-shadow:
			0 0 22px color-mix(in srgb, var(--mode-color) 13%, transparent),
			0 18px 42px rgba(0, 0, 0, 0.36),
			inset 0 1px 0 rgba(255, 255, 255, 0.08);
	}

	:global(:root.light) .composer-bar {
		--composer-mid-bg: #d3e1ef;
		--composer-edge-bg: #cbdbea;
		--composer-stroke: color-mix(in srgb, var(--mode-color) 28%, #8ca1b8 72%);

		border-color: transparent;
		background:
			linear-gradient(180deg, #d8e6f4 0%, #d3e1ef 42%, #cbdbea 100%);

		box-shadow:
			0 16px 34px rgba(50, 80, 118, 0.12),
			inset 0 1px 0 rgba(255, 255, 255, 0.92);
	}

	.composer-bar.multi-line {
		--composer-left-width: 0rem;
		--composer-right-width: 0rem;

		padding: 0;
		border-radius: 1.42rem;
	}

	.top-row {
		display: grid;
		grid-template-columns: var(--composer-left-width) minmax(0, 1fr) var(--composer-right-width);
		align-items: stretch;
		width: 100%;
		min-width: 0;
		min-height: 4.05rem;
		transition: grid-template-columns 180ms cubic-bezier(0.22, 1, 0.36, 1);
	}

	.inline-plus-wrap {
		box-sizing: border-box;
		display: flex;
		align-items: center;
		justify-content: flex-start;
		min-width: 0;
		/* Mirror .inline-actions-wrap so the plus icon sits the same distance from
		   the left edge as the send button does from the right edge. */
		padding: 0.35rem 0.25rem 0.35rem 0.9rem;

		background: var(--composer-edge-bg);

		border-radius: 0;
		opacity: 1;
		overflow: hidden;
		transform: translateX(0) scale(1);

		transition:
			opacity 120ms ease,
			transform 180ms cubic-bezier(0.22, 1, 0.36, 1);
	}

	.composer-input-wrap {
		box-sizing: border-box;
		min-width: 0;
		position: relative;
		display: flex;
		align-items: center;
		gap: 0.68rem;

		padding: 0.35rem 0.8rem 0.35rem 1.2rem;

		background: var(--composer-mid-bg);

		border-left: 0;
		border-right: 0;

		box-shadow:
			inset 0 1px 0 rgba(255, 255, 255, 0.055),
			inset 0 -1px 0 rgba(0, 0, 0, 0.08);
	}

	:global(:root.light) .composer-input-wrap {
		background: var(--composer-mid-bg);
		box-shadow:
			inset 0 1px 0 rgba(255, 255, 255, 0.95),
			inset 0 -1px 0 rgba(31, 72, 125, 0.08);
	}

	.inline-think-wrap {
		width: 5.45rem;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		min-width: 0;
		opacity: 1;
		overflow: hidden;
		transform: translateX(0) scale(1);

		transition:
			width 180ms cubic-bezier(0.22, 1, 0.36, 1),
			opacity 120ms ease,
			transform 180ms cubic-bezier(0.22, 1, 0.36, 1);
	}

	/* Cloud providers swap the Think button for the combined level pill, which needs
	   a touch more room than the plain toggle. */
	.inline-think-wrap.level {
		width: 6.6rem;
		overflow: visible;
	}

	/* Compact level pill (Off/Low/Medium/High) inside the dark composer bar. */
	.level-select {
		width: 100%;
		min-width: 0;
		font-size: 0.82rem;
	}

	.level-select.off {
		opacity: 0.72;
	}

	.controls-right .level-select {
		width: 7rem;
	}

	.inline-actions-wrap {
		box-sizing: border-box;
		display: flex;
		align-items: center;
		justify-content: flex-end;
		min-width: 0;
		padding: 0.35rem 0.9rem 0.35rem 0.25rem;

		background: var(--composer-edge-bg);

		border-radius: 0 1.12rem 1.12rem 0;

		opacity: 1;
		overflow: hidden;
		transform: translateX(0) scale(1);

		transition:
			opacity 120ms ease,
			transform 180ms cubic-bezier(0.22, 1, 0.36, 1);
	}

	.multi-line .inline-plus-wrap {
		opacity: 0;
		transform: translateX(-0.45rem) scale(0.82);
		pointer-events: none;
	}

	.multi-line .inline-think-wrap {
		width: 0;
		opacity: 0;
		transform: translateX(0.35rem) scale(0.82);
		pointer-events: none;
	}

	.multi-line .inline-actions-wrap {
		opacity: 0;
		transform: translateX(0.55rem) scale(0.82);
		pointer-events: none;
	}

	textarea,
	.textarea-measure {
		box-sizing: border-box;
		width: 100%;
		padding: 0.5rem 0.15rem;
		border: 0;
		font: inherit;
		font-size: 0.96rem;
		line-height: 1.5;
		letter-spacing: inherit;
		white-space: pre-wrap;
		overflow-wrap: break-word;
		word-break: break-word;
		tab-size: 4;
	}

	textarea {
		height: auto;
		max-height: 12rem;
		background: transparent;
		color: var(--text);
		resize: none;
		display: block;
		overflow-y: auto;
		outline: none;
		transition: height 120ms cubic-bezier(0.22, 1, 0.36, 1);
	}

	textarea:focus-visible {
		box-shadow: none;
	}

	textarea::placeholder {
		color: color-mix(in srgb, var(--text-soft) 78%, transparent);
	}

	:global(:root.light) textarea {
		color: #0d1b2e;
	}

	:global(:root.light) textarea::placeholder {
		color: rgba(75, 96, 122, 0.72);
	}

	.textarea-measure {
		position: absolute;
		top: 0;
		left: 0;
		height: auto;
		min-height: 0;
		visibility: hidden;
		pointer-events: none;
		z-index: -1;
		overflow: hidden;
	}

	.bottom-row {
		max-height: 0;
		padding-top: 0;
		opacity: 0;
		overflow: hidden;
		transform: translateY(-0.35rem);
		pointer-events: none;
		transition:
			max-height 180ms cubic-bezier(0.22, 1, 0.36, 1),
			padding-top 180ms cubic-bezier(0.22, 1, 0.36, 1),
			opacity 130ms ease,
			transform 180ms cubic-bezier(0.22, 1, 0.36, 1);
	}

	.multi-line .bottom-row {
		max-height: 5rem;
		padding-top: 0;
		opacity: 1;
		transform: translateY(0);
		pointer-events: auto;
	}

	.bottom-controls {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
		min-height: 3.45rem;
		padding: 0.45rem 0.9rem 0.85rem;
		border-top: 1px solid rgba(255, 255, 255, 0.055);
		border-radius: 0;
		background: var(--composer-edge-bg);
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.045);
	}

	:global(:root.light) .bottom-controls {
		border-top-color: rgba(31, 72, 125, 0.06);
		box-shadow: none;
	}

	.bottom-controls .controls-left,
	.bottom-controls .controls-right {
		opacity: 0;
		transform: translateY(-0.2rem);
		transition:
			opacity 140ms ease 35ms,
			transform 180ms cubic-bezier(0.22, 1, 0.36, 1) 35ms;
	}

	.multi-line .bottom-controls .controls-left,
	.multi-line .bottom-controls .controls-right {
		opacity: 1;
		transform: translateY(0);
	}

	.controls-left,
	.controls-right,
	.right-actions-group {
		display: flex;
		align-items: center;
		gap: 0.54rem;
	}

	.controls-right {
		gap: 0.62rem;
		flex: 0 0 auto;
		min-width: 0;
	}

	.bottom-controls .think-button {
		width: 2.55rem;
		padding: 0;
	}

	.bottom-controls .think-button span {
		display: none;
	}

	.right-actions-group {
		gap: 0.54rem;
		flex: 0 0 auto;
	}

	.composer-icon,
	.send-button,
	.think-button {
		height: 2.55rem;
		display: flex;
		align-items: center;
		justify-content: center;
		flex-shrink: 0;
		border: 1px solid transparent;
		transition:
			background 120ms ease,
			color 120ms ease,
			border-color 120ms ease,
			filter 120ms ease,
			transform 120ms ease,
			box-shadow 120ms ease;
	}

	.composer-icon {
		width: 2.55rem;
		border-radius: 0.82rem;
		background: rgba(255, 255, 255, 0.055);
		color: color-mix(in srgb, var(--text-soft) 82%, white 8%);
		box-shadow:
			inset 0 1px 0 rgba(255, 255, 255, 0.055),
			0 8px 18px rgba(0, 0, 0, 0.14);
	}

	.plus-button {
		background: rgba(255, 255, 255, 0.035);
		border-color: transparent;
		color: rgba(255, 255, 255, 0.9);
		box-shadow: none;
	}

	.plus-button :global(svg) {
		display: block;
	}

	.mic-button {
		background: rgba(255, 255, 255, 0.035);
		color: rgba(255, 255, 255, 0.9);
		box-shadow: none;
	}

	:global(:root.light) .composer-icon {
		background: rgba(255, 255, 255, 0.56);
		color: #43546a;
		box-shadow:
			inset 0 1px 0 rgba(255, 255, 255, 0.84),
			0 8px 18px rgba(50, 80, 118, 0.1);
	}

	:global(:root.light) .plus-button {
		background: rgba(15, 23, 42, 0.1);
		color: #24364d;
		box-shadow: none;
	}

	:global(:root.light) .mic-button {
		background: rgba(15, 23, 42, 0.1);
		color: #24364d;
		box-shadow: none;
	}

	.composer-icon:hover {
		background: color-mix(in srgb, var(--mode-color) 18%, rgba(255, 255, 255, 0.105));
		color: var(--mode-color);
		transform: translateY(-1px);
	}

	:global(:root.light) .composer-icon:hover {
		background: color-mix(in srgb, var(--mode-color) 13%, rgba(255, 255, 255, 0.88));
		color: var(--mode-color);
	}

	.think-button {
		width: 100%;
		white-space: nowrap;
		padding: 0 0.95rem;
		gap: 0.42rem;
		height: 2.42rem;
		border-radius: 0.62rem;

		background: rgba(255, 255, 255, 0.035);
		border-color: transparent;
		color: rgba(255, 255, 255, 0.86);

		font-size: 0.88rem;
		font-weight: 650;

		box-shadow: none;
	}

	.think-button :global(svg) {
		width: 1.2rem;
		height: 1.2rem;
		min-width: 1.2rem;
		flex-shrink: 0;
	}

	.think-button span {
		transform: translateY(0.06rem);
	}

	.think-button:hover {
		background: rgba(251, 188, 4, 0.18);
		border-color: transparent;
		color: #ffd666;
	}

	.think-button.active {
		background: rgba(202, 124, 0, 0.32);
		border-color: transparent;
		color: #ffb72e;
		box-shadow: none;
	}

	:global(:root.light) .think-button {
		background: rgba(15, 23, 42, 0.1);
		border-color: transparent;
		color: #24364d;
		box-shadow: none;
	}

	:global(:root.light) .think-button:hover,
	:global(:root.light) .think-button.active {
		background: rgba(202, 124, 0, 0.22);
		border-color: transparent;
		color: #6d3f00;
	}

	.send-button {
		width: 2.55rem;
		height: 2.55rem;
		border-radius: 0.82rem;
		background: color-mix(in srgb, var(--mode-color) 18%, transparent);
		color: color-mix(in srgb, var(--mode-color) 86%, white 10%);
		border-color: transparent;
		box-shadow: none;
	}

	.send-button:hover:not(:disabled) {
		background: color-mix(in srgb, var(--mode-color) 26%, transparent);
		color: color-mix(in srgb, var(--mode-color) 92%, white 16%);
		filter: none;
	}

	.send-button:disabled {
		background: rgba(255, 255, 255, 0.035);
		color: rgba(255, 255, 255, 0.42);
		opacity: 1;
		filter: none;
		cursor: not-allowed;
		box-shadow: none;
	}

	:global(:root.light) .send-button:disabled {
		background: rgba(15, 23, 42, 0.12);
		color: rgba(15, 23, 42, 0.42);
	}

	.stop-button {
		background: var(--danger, #ef4444);
		color: #fff;
		box-shadow: none;
	}

	.stop-square {
		width: 0.72rem;
		height: 0.72rem;
		border-radius: 0.18rem;
		background: currentColor;
	}

	.composer-footer {
		display: flex;
		justify-content: space-between;
		max-width: 72rem;
		margin: 0 auto;
		padding: 0.42rem 0.75rem 0;
		background: transparent;
		color: var(--text-soft);
		font-size: 0.68rem;
		letter-spacing: 0.01em;
	}

	.stats {
		display: flex;
		gap: 1rem;
	}

	.stats span,
	.context-info {
		background: transparent;
		box-shadow: none;
	}

	.context-info {
		opacity: 0.68;
	}

	@media (max-width: 760px) {
		.composer {
			padding-inline: 0.8rem;
		}

		.composer-bar {
			--composer-right-width: 6.2rem;
		}

		.think-button span {
			display: none;
		}

		.inline-think-wrap {
			width: 2.42rem;
		}

		.think-button {
			width: 2.42rem;
			padding: 0;
		}

		.composer-footer {
			font-size: 0.62rem;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.composer-bar,
		.top-row,
		.inline-plus-wrap,
		.inline-think-wrap,
		.inline-actions-wrap,
		textarea,
		.bottom-row,
		.bottom-controls .controls-left,
		.bottom-controls .controls-right,
		.composer-icon,
		.send-button,
		.think-button {
			transition: none;
		}
	}
</style>
