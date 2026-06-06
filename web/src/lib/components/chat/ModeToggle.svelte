<script lang="ts">
	let { mode, onModeChange } = $props<{
		mode: string;
		onModeChange: (mode: string) => void;
	}>();

	const modes = ['Chat', 'Plan', 'Debug'];
</script>

<div class="mode-toggle" aria-label="Chat mode">
	{#each modes as item}
		<button class:active={mode === item} type="button" onclick={() => onModeChange(item)}>{item}</button>
	{/each}
</div>

<style>
	.mode-toggle {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		padding: 0.23rem;
		gap: 0.15rem;
		border: 1px solid color-mix(in srgb, var(--bg-soft) 58%, var(--border));
		border-radius: 0.68rem;
		background: color-mix(in srgb, var(--toggle-bg) 86%, transparent);
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
	}

	.mode-toggle button {
		min-width: 4.35rem;
		padding: 0.48rem 1.05rem;
		border: 1px solid transparent;
		border-radius: 0.48rem;
		color: var(--text-soft);
		font-size: 0.85rem;
		font-weight: 720;
		text-align: center;
		transition: background-color 120ms ease, border-color 120ms ease, color 120ms ease;
	}

	.mode-toggle button:hover:not(.active) {
		color: var(--text-muted);
		background: var(--toggle-hover-bg);
	}

	.mode-toggle button.active {
		border-color: transparent;
		background: color-mix(in srgb, var(--mode-color) 38%, #10213a);
		color: var(--mode-color);
		box-shadow: none;
	}

	:global(:root.light) .mode-toggle button.active {
		background: var(--mode-soft);
	}

	@media (max-width: 760px) {
		.mode-toggle {
			width: 100%;
		}

		.mode-toggle button {
			min-width: 0;
			padding: 0.45rem 0.6rem;
		}
	}
</style>
