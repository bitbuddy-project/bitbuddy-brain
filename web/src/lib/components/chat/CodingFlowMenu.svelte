<script lang="ts">
	import FlowArrowIcon from 'phosphor-svelte/lib/FlowArrowIcon';
	import CaretDownIcon from 'phosphor-svelte/lib/CaretDownIcon';
	import PlusIcon from 'phosphor-svelte/lib/PlusIcon';
	import SlidersHorizontalIcon from 'phosphor-svelte/lib/SlidersHorizontalIcon';
	import type { CodingWorkflow } from '$lib/api/bitbuddy';

	let { workflows, selectedId, open, disabled = false, onToggle, onSelect, onNew, onEdit } = $props<{
		workflows: CodingWorkflow[];
		selectedId: string;
		open: boolean;
		disabled?: boolean;
		onToggle: () => void;
		onSelect: (workflow: CodingWorkflow) => void;
		onNew: () => void;
		onEdit: () => void;
	}>();

	let selected = $derived(workflows.find((workflow: CodingWorkflow) => workflow.id === selectedId));
	let container: HTMLDivElement;

	function handleOutsideClick(event: MouseEvent) {
		if (open && container && !container.contains(event.target as Node)) onToggle();
	}

	function pick(workflow: CodingWorkflow) {
		onSelect(workflow);
		onToggle();
	}

	function stageSummary(workflow: CodingWorkflow) {
		return workflow.stages.map((stage) => stage.name).join(' → ');
	}
</script>

<svelte:window onclick={handleOutsideClick} />

<div class="flow-wrap" bind:this={container}>
	<button class="flow-button" class:open type="button" onclick={onToggle} aria-expanded={open}>
		<FlowArrowIcon size={17} weight="bold" />
		<span class="flow-name">{selected ? selected.name : 'Choose flow'}</span>
		<CaretDownIcon size={13} weight="bold" />
	</button>

	{#if open}
		<div class="flow-menu">
			<div class="menu-header">
				<span class="menu-title">Coding flows</span>
				<button class="new-flow-btn" type="button" onclick={() => { onNew(); onToggle(); }} disabled={disabled}>
					<PlusIcon size={14} weight="bold" /><span>New</span>
				</button>
			</div>
			<div class="flow-list">
				{#if workflows.length === 0}
					<p class="flow-empty">No flows yet.</p>
				{:else}
					{#each workflows as workflow (workflow.id)}
						<button class="flow-select" class:active={selectedId === workflow.id} type="button" onclick={() => pick(workflow)}>
							<strong>{workflow.name}</strong>
							<span>{stageSummary(workflow)}</span>
						</button>
					{/each}
				{/if}
			</div>
			<div class="menu-footer">
				<button class="edit-flow" type="button" onclick={() => { onEdit(); onToggle(); }} disabled={disabled || !selected}>
					<SlidersHorizontalIcon size={15} /> Edit this flow
				</button>
			</div>
		</div>
	{/if}
</div>

<style>
	.flow-wrap {
		position: relative;
		z-index: 21;
		--flow-button-bg: rgba(255, 255, 255, 0.03);
		--flow-button-hover-bg: rgba(255, 255, 255, 0.06);
		--flow-menu-bg: var(--panel);
		--flow-header-bg: rgba(255, 255, 255, 0.02);
		--flow-row-hover-bg: rgba(255, 255, 255, 0.05);
		--flow-shadow: var(--shadow-soft);
	}

	:global(:root.light) .flow-wrap {
		--flow-button-bg: rgba(15, 23, 42, 0.08);
		--flow-button-hover-bg: rgba(37, 99, 235, 0.08);
		--flow-menu-bg: color-mix(in srgb, var(--panel) 96%, var(--accent-soft));
		--flow-header-bg: linear-gradient(180deg, rgba(37, 99, 235, 0.055), rgba(15, 23, 42, 0.018));
		--flow-row-hover-bg: rgba(37, 99, 235, 0.07);
		--flow-shadow: 0 20px 48px rgba(15, 23, 42, 0.16), 0 2px 8px rgba(15, 23, 42, 0.06);
	}

	:global(:root.light) .flow-button {
		color: #24364d;
	}

	.flow-button {
		height: 2.75rem;
		max-width: 15rem;
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0 0.85rem;
		border: 1px solid transparent;
		border-radius: 0.82rem;
		background: var(--flow-button-bg);
		color: rgba(255, 255, 255, 0.86);
		font-size: 0.85rem;
		font-weight: 700;
	}

	.flow-button:hover,
	.flow-button.open {
		color: var(--mode-color, var(--accent));
		background: var(--flow-button-hover-bg);
	}

	.flow-name {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.flow-menu {
		position: absolute;
		top: calc(100% + 0.6rem);
		left: 0;
		width: 22rem;
		max-height: 28rem;
		display: flex;
		flex-direction: column;
		border: 1px solid var(--border-strong);
		border-radius: 1.15rem;
		background:
			linear-gradient(135deg, rgba(255, 255, 255, 0.065), transparent 68%),
			var(--flow-menu-bg);
		box-shadow: var(--flow-shadow), inset 0 1px 0 rgba(255, 255, 255, 0.055);
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
		display: flex;
		align-items: center;
		justify-content: space-between;
		border-bottom: 1px solid var(--border);
		background: var(--flow-header-bg);
	}

	.menu-title {
		font-size: 0.85rem;
		font-weight: 800;
		color: var(--text-soft);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.new-flow-btn {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.35rem 0.75rem;
		border-radius: 0.6rem;
		background: var(--accent);
		color: var(--new-chat-text, #06101d);
		font-size: 0.8rem;
		font-weight: 700;
	}

	:global(:root.light) .new-flow-btn {
		color: #ffffff;
	}

	.flow-list {
		padding: 0.5rem;
		overflow-y: auto;
		display: grid;
		gap: 0.2rem;
	}

	.flow-select {
		display: grid;
		gap: 0.2rem;
		padding: 0.7rem 0.85rem;
		border: 1px solid transparent;
		border-radius: 0.75rem;
		background: transparent;
		color: var(--text);
		text-align: left;
		cursor: pointer;
	}

	.flow-select:hover {
		background: var(--flow-row-hover-bg);
	}

	.flow-select.active {
		border-color: color-mix(in srgb, var(--mode-color, var(--accent)) 45%, var(--border));
		background: color-mix(in srgb, var(--mode-color, var(--accent)) 10%, transparent);
	}

	.flow-select strong {
		font-size: 0.9rem;
		font-weight: 700;
	}

	.flow-select span {
		color: var(--text-soft);
		font-size: 0.74rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.flow-empty {
		padding: 2rem;
		text-align: center;
		color: var(--text-soft);
		font-size: 0.9rem;
	}

	.menu-footer {
		padding: 0.6rem 0.85rem;
		border-top: 1px solid var(--border);
	}

	.edit-flow {
		width: 100%;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: 0.45rem;
		padding: 0.6rem;
		border: 1px solid var(--border);
		border-radius: 0.7rem;
		color: var(--text-soft);
		font-weight: 700;
		font-size: 0.82rem;
	}

	.edit-flow:hover:not(:disabled) {
		color: var(--mode-color, var(--accent));
		border-color: var(--mode-color, var(--accent));
	}

	.edit-flow:disabled {
		opacity: 0.5;
	}

	@media (max-width: 760px) {
		.flow-button {
			max-width: 11rem;
		}

		.flow-menu {
			position: fixed;
			top: 4.25rem;
			left: 1rem;
			right: 1rem;
			width: auto;
		}
	}
</style>
