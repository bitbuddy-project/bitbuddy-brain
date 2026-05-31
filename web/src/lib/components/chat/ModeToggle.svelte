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
		padding: 0.08rem 0.16rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: var(--toggle-bg);
	}

	.mode-toggle button {
		min-width: 4.35rem;
		padding: 0.42rem 1rem;
		border: 1px solid transparent;
		border-radius: 999px;
		color: var(--text-soft);
		font-size: 0.85rem;
		font-weight: 600;
		text-align: center;
		transition: background-color 120ms ease, border-color 120ms ease, color 120ms ease;
	}

	.mode-toggle button:hover:not(.active) {
		color: var(--text-muted);
		background: var(--toggle-hover-bg);
	}

	.mode-toggle button.active {
		border-color: var(--mode-border);
		background: var(--mode-soft);
		color: var(--mode-color);
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
