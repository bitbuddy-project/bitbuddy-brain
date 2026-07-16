<script lang="ts">
	import ClockCounterClockwiseIcon from 'phosphor-svelte/lib/ClockCounterClockwiseIcon';
	import TrashIcon from 'phosphor-svelte/lib/TrashIcon';
	import type { CodingRun } from '$lib/api/bitbuddy';
	import { formatTimestamp } from '$lib/stores/time.svelte';

	let { runs, open, activeRunId = '', onToggle, onSelect, onDelete } = $props<{
		runs: CodingRun[];
		open: boolean;
		activeRunId?: string;
		onToggle: () => void;
		onSelect: (run: CodingRun) => void;
		onDelete: (runId: string) => void;
	}>();

	const BAD = ['failed', 'needs_attention'];

	let container: HTMLDivElement;

	function handleOutsideClick(event: MouseEvent) {
		if (open && container && !container.contains(event.target as Node)) onToggle();
	}
</script>

<svelte:window onclick={handleOutsideClick} />

<div class="runs-wrap" bind:this={container}>
	<button class="runs-button" class:open type="button" onclick={onToggle} aria-expanded={open}>
		<ClockCounterClockwiseIcon size={18} />
		<span>Recent runs</span>
	</button>

	{#if open}
		<div class="runs-menu">
			<div class="menu-header">
				<span class="menu-title">Recent runs</span>
			</div>
			<div class="run-list">
				{#if runs.length === 0}
					<p class="runs-empty">No coding runs yet.</p>
				{:else}
					{#each runs as run (run.id)}
						<div class="run-row" class:active={activeRunId === run.id}>
							<button class="run-select" type="button" onclick={() => onSelect(run)}>
								<div class="run-info">
									<strong>{run.user_request}</strong>
									<span class:bad={BAD.includes(run.status)}>{run.status.replaceAll('_', ' ')} · {formatTimestamp(run.updated_at)}</span>
								</div>
							</button>
							<button class="delete-run" type="button" aria-label={`Delete run ${run.user_request}`} onclick={() => onDelete(run.id)}>
								<TrashIcon size={16} />
							</button>
						</div>
					{/each}
				{/if}
			</div>
		</div>
	{/if}
</div>

<style>
	.runs-wrap {
		position: relative;
		z-index: 20;
		--runs-button-bg: rgba(255, 255, 255, 0.03);
		--runs-button-hover-bg: rgba(255, 255, 255, 0.06);
		--runs-menu-bg: var(--panel);
		--runs-header-bg: rgba(255, 255, 255, 0.02);
		--runs-row-hover-bg: rgba(255, 255, 255, 0.05);
		--runs-shadow: var(--shadow-soft);
	}

	:global(:root.light) .runs-wrap {
		--runs-button-bg: rgba(15, 23, 42, 0.08);
		--runs-button-hover-bg: rgba(37, 99, 235, 0.08);
		--runs-menu-bg: color-mix(in srgb, var(--panel) 96%, var(--accent-soft));
		--runs-header-bg: linear-gradient(180deg, rgba(37, 99, 235, 0.055), rgba(15, 23, 42, 0.018));
		--runs-row-hover-bg: rgba(37, 99, 235, 0.07);
		--runs-shadow: 0 20px 48px rgba(15, 23, 42, 0.16), 0 2px 8px rgba(15, 23, 42, 0.06);
	}

	:global(:root.light) .runs-button {
		color: #24364d;
	}

	.runs-button {
		height: 2.75rem;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 0.45rem;
		padding: 0 0.85rem;
		border: 1px solid transparent;
		border-radius: 0.82rem;
		background: var(--runs-button-bg);
		color: rgba(255, 255, 255, 0.86);
		font-size: 0.85rem;
		font-weight: 600;
	}

	.runs-button:hover,
	.runs-button.open {
		color: var(--mode-color, var(--accent));
		background: var(--runs-button-hover-bg);
	}

	.runs-menu {
		position: absolute;
		top: calc(100% + 0.6rem);
		right: 0;
		width: 24rem;
		max-height: 28rem;
		display: flex;
		flex-direction: column;
		border: 1px solid var(--border-strong);
		border-radius: 1.15rem;
		background:
			linear-gradient(135deg, rgba(255, 255, 255, 0.065), transparent 68%),
			var(--runs-menu-bg);
		box-shadow: var(--runs-shadow), inset 0 1px 0 rgba(255, 255, 255, 0.055);
		backdrop-filter: blur(24px);
		z-index: 1000;
		overflow: hidden;
		animation: scale-up 0.2s cubic-bezier(0.16, 1, 0.3, 1);
	}

	@keyframes scale-up {
		from { opacity: 0; transform: scale(0.95) translateY(-10px); }
		to { opacity: 1; transform: scale(1) translateY(0); }
	}

	.menu-header {
		padding: 1rem 1.25rem;
		border-bottom: 1px solid var(--border);
		background: var(--runs-header-bg);
	}

	.menu-title {
		font-size: 0.85rem;
		font-weight: 800;
		color: var(--text-soft);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.run-list {
		padding: 0.5rem;
		overflow-y: auto;
	}

	.run-row {
		width: 100%;
		padding: 0.25rem;
		border-radius: 0.85rem;
		display: flex;
		align-items: center;
		gap: 0.25rem;
		transition: 120ms ease;
	}

	.run-row:hover {
		background: var(--runs-row-hover-bg);
	}

	.run-row.active {
		background: color-mix(in srgb, var(--mode-color, var(--accent)) 12%, transparent);
	}

	.run-select {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.7rem 0.85rem 0.7rem 1rem;
		border: none;
		background: transparent;
		color: var(--text);
		text-align: left;
		cursor: pointer;
		flex: 1;
		min-width: 0;
	}

	.run-info {
		min-width: 0;
	}

	.run-select strong {
		display: block;
		color: var(--text);
		font-size: 0.9rem;
		font-weight: 600;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.run-select span {
		display: block;
		color: var(--text-soft);
		font-size: 0.76rem;
		margin-top: 0.1rem;
		text-transform: capitalize;
	}

	.run-select span.bad {
		color: var(--warning);
	}

	.delete-run {
		width: 2.1rem;
		height: 2.1rem;
		flex: 0 0 auto;
		display: grid;
		place-items: center;
		border-radius: 999px;
		color: var(--text-soft);
	}

	.delete-run:hover {
		background: rgba(255, 107, 122, 0.12);
		color: var(--danger);
	}

	.runs-empty {
		padding: 2rem;
		text-align: center;
		color: var(--text-soft);
		font-size: 0.9rem;
	}

	@media (max-width: 760px) {
		.runs-button > span {
			position: absolute;
			width: 1px;
			height: 1px;
			clip: rect(0 0 0 0);
			clip-path: inset(50%);
			overflow: hidden;
		}

		.runs-button {
			width: 2.35rem;
			padding: 0;
		}

		.runs-menu {
			position: fixed;
			top: 4.25rem;
			right: 1rem;
			left: 1rem;
			width: auto;
			max-height: min(28rem, calc(100dvh - 5.25rem));
			z-index: 60;
		}
	}
</style>
