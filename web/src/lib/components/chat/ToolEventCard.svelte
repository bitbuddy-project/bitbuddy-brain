<script lang="ts">
	import WrenchIcon from 'phosphor-svelte/lib/WrenchIcon';
	import BrainIcon from 'phosphor-svelte/lib/BrainIcon';
	import BlueprintIcon from 'phosphor-svelte/lib/BlueprintIcon';
	import CaretRightIcon from 'phosphor-svelte/lib/CaretRightIcon';
	import type { ChatMessage } from '$lib/api/bitbuddy';
	import DiffEventCard from './DiffEventCard.svelte';
	import MarkdownMessage from './MarkdownMessage.svelte';
	import { slide } from 'svelte/transition';

	let { message } = $props<{ message: ChatMessage }>();

	let metadata = $derived(message.metadata ?? {});
	let toolName = $derived(metadata.tool || 'tool');
	let status = $derived(message.status || 'running');
	let projectId = $derived(
		typeof metadata.arguments_summary?.project_id === 'string' ? metadata.arguments_summary.project_id : ''
	);
	let memoryLayer = $derived(
		typeof metadata.arguments_summary?.layer === 'string' ? metadata.arguments_summary.layer : ''
	);
	let filePath = $derived(
		typeof metadata.arguments_summary?.file_path === 'string'
			? metadata.arguments_summary.file_path
			: typeof metadata.arguments_summary?.path === 'string'
				? metadata.arguments_summary.path
				: ''
	);
	let subagentRunId = $derived(
		typeof metadata.arguments_summary?.run_id === 'string' ? metadata.arguments_summary.run_id : ''
	);
	let summary = $derived(metadata.result_summary || metadata.error || message.content || 'Tool event');
	let displayStatus = $derived(status === 'success' ? 'completed' : status);
	let diff = $derived(metadata.diff);
	let hasDiff = $derived(Boolean(diff?.files?.length));

	let isMemoryTool = $derived(['record_episode', 'update_episode', 'forget_episode', 'record_project_memory', 'record_memory', 'write_memory', 'update_memory', 'archive_memory', 'move_memory', 'merge_memory'].includes(String(toolName)));
	let isFailedMemory = $derived(isMemoryTool && status === 'error');
	let memoryTitle = $derived(
		toolName === 'record_episode' && summary.startsWith('Saved episodic memory:')
			? summary.replace('Saved episodic memory: ', '')
			: (toolName === 'record_memory' || toolName === 'write_memory') && summary.startsWith('Saved ')
				? summary.replace('Saved ', '')
			: toolName === 'update_memory' && summary.startsWith('Updated ')
				? summary.replace('Updated ', '')
			: toolName === 'archive_memory' && summary.startsWith('Archived ')
				? summary.replace('Archived ', '')
			: toolName === 'move_memory' && summary.startsWith('Moved memory to ')
				? summary.replace('Moved memory to ', '')
			: toolName === 'merge_memory' && summary.startsWith('Merged memory into ')
				? summary.replace('Merged memory into ', '')
			: toolName === 'update_episode' && summary.startsWith('Updated episodic memory:')
				? summary.replace('Updated episodic memory: ', '')
				: toolName === 'forget_episode' && summary.startsWith('Forgot episodic memory:')
					? summary.replace('Forgot episodic memory: ', '')
			: toolName === 'record_project_memory' && summary.startsWith('Recorded ')
				? summary.replace('Recorded ', '').replace(' in project memory', '')
				: summary
	);

	// Hide failed memory attempts completely - they clutter the chat
	let showMemoryCard = $derived(isMemoryTool && !isFailedMemory);

	// Hide internal tools like memory consolidation - they are not user-facing
	let isHiddenTool = $derived(toolName === 'memory_consolidation' || metadata.memory_consolidation === true);
	let displayToolName = $derived(toolName === 'run_subagent' ? 'subagent' : toolName);

	let collapsed = $state(true);
	function toggleCollapsed() {
		collapsed = !collapsed;
	}
</script>

{#if !isHiddenTool}
{#if showMemoryCard}
	<div class="memory-row">
		<div class="memory-spacer" aria-hidden="true"></div>
		<div class="memory-card" class:project={toolName === 'record_project_memory' || memoryLayer === 'project'}>
			<div class="memory-header">
				<span class="memory-label">
					{#if toolName === 'record_episode' || toolName === 'update_episode' || toolName === 'forget_episode' || toolName === 'record_memory' || toolName === 'write_memory' || toolName === 'update_memory' || toolName === 'archive_memory' || toolName === 'move_memory' || toolName === 'merge_memory'}
						<BrainIcon size={14} weight="duotone" />
						<strong>{toolName === 'forget_episode' || toolName === 'archive_memory' ? 'Memory archived' : toolName === 'update_episode' || toolName === 'update_memory' ? 'Memory updated' : toolName === 'move_memory' ? 'Memory moved' : toolName === 'merge_memory' ? 'Memory merged' : memoryLayer ? `${memoryLayer} memory` : 'Memory'}</strong>
					{:else}
						<BlueprintIcon size={14} weight="duotone" />
						<strong>Project memory</strong>
					{/if}
					<span class="memory-title">{memoryTitle}</span>
				</span>
				<button class="toggle-btn" type="button" onclick={toggleCollapsed}>
					<div class="caret" class:collapsed>
						<CaretRightIcon size={13} weight="bold" />
					</div>
					<span>{collapsed ? 'Show' : 'Hide'}</span>
				</button>
			</div>
			{#if !collapsed}
				<div transition:slide={{ duration: 200 }} class="memory-body">
					<div class="memory-summary"><MarkdownMessage content={summary} compact /></div>
					{#if projectId}
						<div class="memory-meta">project: {projectId}</div>
					{/if}
					{#if memoryLayer}
						<div class="memory-meta">layer: {memoryLayer}</div>
					{/if}
				</div>
				{/if}
		</div>
	</div>
{:else if !isMemoryTool}
	{#if hasDiff && diff}
		<DiffEventCard {diff} toolName={displayToolName} status={displayStatus} />
	{:else}
	<div class:error={status === 'error'} class:success={status === 'success' || status === 'completed'} class="tool-card">
		<div class="tool-icon"><WrenchIcon size={15} weight="bold" /></div>
		<div class="tool-body">
			<div class="tool-header">
				<strong>{displayToolName}</strong>
				<span class="status">{displayStatus}</span>
			</div>
			{#if toolName === 'run_subagent'}
				<div class="argument">private delegated run{subagentRunId ? `: ${subagentRunId.slice(0, 8)}` : ''}</div>
			{/if}
			{#if projectId}
				<div class="argument">project: <code>{projectId}</code></div>
			{/if}
			{#if filePath}
				<div class="argument">file: <code>{filePath}</code></div>
			{/if}
			<div class="summary"><MarkdownMessage content={summary} compact /></div>
			{#if metadata.truncated}
				<div class="note">Tool result was truncated before being sent to the model.</div>
			{/if}
		</div>
	</div>
	{/if}
{/if}
{/if}

<style>
	.tool-card {
		max-width: min(42rem, 88%);
		margin-left: 3rem;
		display: grid;
		grid-template-columns: 1.85rem minmax(0, 1fr);
		gap: 0.7rem;
		align-items: start;
		padding: 0.75rem 0.85rem;
		border: 1px solid color-mix(in srgb, var(--mode-border, var(--event-border)) 88%, transparent);
		border-radius: 1rem;
		background:
			linear-gradient(180deg, rgba(255, 255, 255, 0.028), rgba(255, 255, 255, 0.008)),
			var(--event-bg, rgba(121, 184, 255, 0.055));
		color: var(--text-muted);
	}

	.tool-card.success {
		border-color: color-mix(in srgb, var(--success) 38%, transparent);
		background:
			linear-gradient(180deg, rgba(255, 255, 255, 0.026), rgba(255, 255, 255, 0.008)),
			color-mix(in srgb, var(--success) 8%, var(--event-bg));
	}

	.tool-card.error {
		border-color: rgba(255, 107, 122, 0.32);
		background: color-mix(in srgb, var(--danger) 8%, var(--event-bg));
	}

	.tool-icon {
		width: 1.85rem;
		height: 1.85rem;
		display: grid;
		place-items: center;
		border: 1px solid currentColor;
		border-radius: 0.7rem;
		color: var(--mode-color);
		background: var(--surface-card);
	}

	.tool-body {
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
	}

	.tool-header {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		justify-content: space-between;
	}

	strong {
		color: var(--text);
		font-size: 0.78rem;
		font-weight: 850;
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}

	.status {
		padding: 0.12rem 0.45rem;
		border-radius: 999px;
		border: 1px solid var(--chip-border, var(--border));
		color: var(--text-soft);
		font-size: 0.68rem;
		font-weight: 800;
		letter-spacing: 0.05em;
		text-transform: uppercase;
	}

	.argument,
	.summary,
	.note {
		font-size: 0.86rem;
		line-height: 1.45;
	}

	.summary {
		color: var(--text-muted);
	}

	.argument,
	.note {
		color: var(--text-soft);
	}

	code {
		padding: 0.08rem 0.3rem;
		border-radius: 0.35rem;
		background: var(--surface-code);
		color: var(--accent-strong);
	}

	.memory-row {
		max-width: min(64rem, 98%);
		display: grid;
		grid-template-columns: 2.8rem minmax(0, 1fr);
		align-items: start;
		gap: 0.85rem;
	}

	.memory-spacer {
		width: 2.8rem;
		height: 2.8rem;
	}

	.memory-card {
		max-width: min(48rem, 100%);
		padding: 0.7rem 0.9rem;
		border: 1px dashed rgba(129, 140, 248, 0.3);
		border-radius: 1.1rem;
		background:
			linear-gradient(180deg, rgba(129, 140, 248, 0.04), rgba(129, 140, 248, 0.02)),
			var(--surface-inset);
		color: var(--text-muted);
		font-size: 0.85rem;
		transition: all 0.2s ease;
	}

	.memory-card.project {
		border-color: rgba(110, 231, 183, 0.25);
		background:
			linear-gradient(180deg, rgba(110, 231, 183, 0.03), rgba(110, 231, 183, 0.015)),
			rgba(0, 0, 0, 0.08);
	}

	.memory-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
	}

	.memory-label {
		display: inline-flex;
		align-items: center;
		gap: 0.45rem;
		color: #818cf8;
	}

	.memory-label :global(svg) {
		color: #818cf8;
	}

	.memory-card.project .memory-label {
		color: #6ee7b7;
	}

	.memory-card.project .memory-label :global(svg) {
		color: #6ee7b7;
	}

	.memory-label strong {
		color: currentColor;
		font-size: 0.72rem;
		font-weight: 800;
		letter-spacing: 0.06em;
		text-transform: uppercase;
	}

	.memory-title {
		color: var(--text-soft);
		font-size: 0.82rem;
		font-weight: 600;
		margin-left: 0.3rem;
	}

	.memory-body {
		margin-top: 0.6rem;
	}

	.memory-summary {
		font-size: 0.82rem;
		line-height: 1.5;
		color: var(--text-muted);
	}

	.memory-meta {
		margin-top: 0.4rem;
		font-size: 0.75rem;
		color: var(--text-soft);
		font-family: monospace;
	}

	.toggle-btn {
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		padding: 0.18rem 0.5rem;
		border-radius: 999px;
		background: rgba(129, 140, 248, 0.08);
		border: 1px solid rgba(129, 140, 248, 0.15);
		color: #818cf8;
		font-size: 0.7rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		transition: all 0.2s ease;
		cursor: pointer;
	}

	.toggle-btn:hover {
		background: rgba(129, 140, 248, 0.14);
		border-color: rgba(129, 140, 248, 0.25);
	}

	.memory-card.project .toggle-btn {
		background: rgba(110, 231, 183, 0.08);
		border-color: rgba(110, 231, 183, 0.15);
		color: #6ee7b7;
	}

	.memory-card.project .toggle-btn:hover {
		background: rgba(110, 231, 183, 0.14);
		border-color: rgba(110, 231, 183, 0.25);
	}

	.caret {
		display: flex;
		transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1);
		transform: rotate(90deg);
	}

	.caret.collapsed {
		transform: rotate(0deg);
	}

	@media (max-width: 760px) {
		.tool-card {
			max-width: 100%;
			margin-left: 0;
		}

		.memory-row {
			max-width: 100%;
		}
	}
</style>
