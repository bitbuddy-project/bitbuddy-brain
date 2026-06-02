<script lang="ts">
	import BrainIcon from 'phosphor-svelte/lib/BrainIcon';
	import CaretRightIcon from 'phosphor-svelte/lib/CaretRightIcon';
	import { slide } from 'svelte/transition';
	import BitBuddyFace from './BitBuddyFace.svelte';

	let { content, error, isStreaming, autoCollapse = false, storageKey = '', showFace = false } = $props<{
		content: string;
		error: string;
		isStreaming: boolean;
		autoCollapse?: boolean;
		storageKey?: string;
		showFace?: boolean;
	}>();

	let collapsed = $state(true);
	let initialized = $state(false);
	let lastAutoCollapse = $state(false);
	let lastStorageKey = $state('');

	$effect.pre(() => {
		if (initialized) return;
		collapsed = initialCollapsed(storageKey);
		lastAutoCollapse = autoCollapse;
		lastStorageKey = storageKey;
		initialized = true;
	});

	$effect(() => {
		if (!initialized) return;
		if (storageKey !== lastStorageKey) {
			collapsed = initialCollapsed(storageKey);
			lastStorageKey = storageKey;
			lastAutoCollapse = autoCollapse;
			return;
		}
		if (autoCollapse && !lastAutoCollapse && storedCollapseState(storageKey) === null) {
			collapsed = true;
		}
		lastAutoCollapse = autoCollapse;
	});

	function toggleCollapsed() {
		collapsed = !collapsed;
		saveCollapseState(storageKey, collapsed);
	}

	function initialCollapsed(key: string) {
		const stored = storedCollapseState(key);
		if (stored !== null) return stored;
		return true;
	}

	function storedCollapseState(key: string): boolean | null {
		if (!key || typeof window === 'undefined') return null;
		const stored = window.localStorage.getItem(`bitbuddy:thinking-collapsed:${key}`);
		if (stored === 'true') return true;
		if (stored === 'false') return false;
		return null;
	}

	function saveCollapseState(key: string, value: boolean) {
		if (!key || typeof window === 'undefined') return;
		window.localStorage.setItem(`bitbuddy:thinking-collapsed:${key}`, String(value));
	}
</script>

{#if content || error || isStreaming}
	<div class="thinking-row">
		{#if showFace && !autoCollapse}
			<BitBuddyFace isThinking={isStreaming && !error} />
		{:else}
			<div class="thinking-face-spacer" aria-hidden="true"></div>
		{/if}
		<div class:error={Boolean(error)} class="thinking-box">
			<div class="thinking-header">
				<div class="thinking-left">
					<span class="thinking-label">
						<BrainIcon size={15} />
						<strong>{error ? 'Connection' : 'Thinking'}</strong>
					</span>
				</div>
				<button class="toggle-btn" type="button" onclick={toggleCollapsed}>
					<div class="caret" class:collapsed>
						<CaretRightIcon size={14} weight="bold" />
					</div>
					<span>{collapsed ? 'Show' : 'Hide'}</span>
				</button>
			</div>
			{#if !collapsed}
				<div transition:slide={{ duration: 250 }}>
					<p>{error || content || 'Waiting for model reasoning...'}</p>
				</div>
			{/if}
		</div>
	</div>
{/if}

<style>
	.thinking-row {
		width: 100%;
		max-width: min(76rem, 98%);
		display: grid;
		grid-template-columns: 2.8rem minmax(0, 1fr);
		align-items: start;
		gap: 0.85rem;
	}

	.thinking-face-spacer {
		width: 2.8rem;
		height: 2.8rem;
	}

	.thinking-box {
		width: 100%;
		min-width: 0;
		box-sizing: border-box;
		padding: 0.85rem 1rem;
		border: 1px dashed color-mix(in srgb, var(--mode-border, var(--border)) 86%, transparent);
		border-radius: 1.1rem;
		background:
			var(--thinking-overlay, rgba(255, 255, 255, 0.018)),
			var(--event-bg, var(--thinking-bg, rgba(0, 0, 0, 0.1)));
		color: var(--text-muted);
		transition: all 0.3s ease;
	}

	.thinking-box.error {
		border-color: var(--danger);
		background: rgba(255, 107, 122, 0.03);
	}

	.thinking-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
	}

	.thinking-left {
		display: inline-flex;
		align-items: center;
		gap: 0.65rem;
		min-width: 0;
	}

	.thinking-label {
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
		color: var(--mode-color);
	}

	strong {
		display: block;
		color: currentColor;
		font-size: 0.72rem;
		font-weight: 800;
		letter-spacing: 0.06em;
		text-transform: uppercase;
	}

	.toggle-btn {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.2rem 0.6rem;
		border-radius: 999px;
		background: var(--chip-bg, var(--bg-soft));
		border: 1px solid var(--chip-border, var(--border));
		color: var(--text-soft);
		font-size: 0.72rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		transition: all 0.2s ease;
	}

	.toggle-btn:hover {
		color: var(--text-muted);
		border-color: var(--border-strong);
		background: var(--card-hover, var(--panel-raised));
	}

	.caret {
		display: flex;
		transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
		transform: rotate(90deg);
	}

	.caret.collapsed {
		transform: rotate(0deg);
	}

	p {
		margin-top: 0.75rem;
		font-size: 0.92rem;
		line-height: 1.6;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		color: var(--text-muted);
	}

	@media (max-width: 760px) {
		.thinking-row {
			max-width: 100%;
		}
	}
</style>
