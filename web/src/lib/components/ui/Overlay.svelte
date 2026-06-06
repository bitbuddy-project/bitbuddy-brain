<script lang="ts">
	import type { Snippet } from 'svelte';
	import { portal } from '$lib/actions/portal';

	let {
		open = false,
		label = 'Dialog',
		wide = false,
		onClose,
		children
	}: {
		open?: boolean;
		label?: string;
		wide?: boolean;
		onClose?: () => void;
		children: Snippet;
	} = $props();

	let scrimElement: HTMLDivElement | null = $state(null);

	function close() {
		onClose?.();
	}

	function onScrimClick(event: MouseEvent) {
		if (event.target === scrimElement) close();
	}

	function onKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') {
			event.preventDefault();
			close();
		}
	}

	$effect(() => {
		if (typeof document === 'undefined') return;
		document.body.classList.toggle('overlay-open', open);
		return () => document.body.classList.remove('overlay-open');
	});
</script>

{#if open}
	<div
		class="overlay-scrim"
		bind:this={scrimElement}
		use:portal
		role="presentation"
		onclick={onScrimClick}
		onkeydown={onKeydown}
	>
		<div class="overlay-card" class:wide role="dialog" aria-modal="true" aria-label={label} tabindex="-1">
			{@render children()}
		</div>
	</div>
{/if}

<style>
	.overlay-scrim {
		position: fixed;
		inset: 0;
		z-index: 1200;
		display: grid;
		place-items: center;
		padding: clamp(1rem, 4vw, 2rem);
		background: color-mix(in srgb, var(--bg) 58%, rgba(2, 6, 16, 0.62));
		backdrop-filter: blur(9px) saturate(1.05);
		animation: overlay-fade 160ms ease;
	}

	.overlay-card {
		position: relative;
		width: min(94vw, 30rem);
		max-height: min(90vh, 46rem);
		overflow: auto;
		border: 1px solid var(--card-border);
		border-radius: 1.1rem;
		background: var(--panel-raised);
		box-shadow: 0 28px 70px rgba(0, 0, 0, 0.42), inset 0 1px 0 var(--card-inner-line);
		scrollbar-color: var(--scrollbar-thumb) transparent;
		animation: overlay-rise 180ms cubic-bezier(0.16, 1, 0.3, 1);
	}

	.overlay-card.wide {
		width: min(94vw, 40rem);
	}

	@keyframes overlay-fade {
		from { opacity: 0; }
		to { opacity: 1; }
	}

	@keyframes overlay-rise {
		from { opacity: 0; transform: translateY(10px) scale(0.98); }
		to { opacity: 1; transform: translateY(0) scale(1); }
	}
</style>
