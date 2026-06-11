<script lang="ts">
	import WrenchIcon from 'phosphor-svelte/lib/WrenchIcon';
	import CheckCircleIcon from 'phosphor-svelte/lib/CheckCircleIcon';
	import WarningCircleIcon from 'phosphor-svelte/lib/WarningCircleIcon';
	import CircleNotchIcon from 'phosphor-svelte/lib/CircleNotchIcon';
	import CaretRightIcon from 'phosphor-svelte/lib/CaretRightIcon';
	import BitBuddyFace from './BitBuddyFace.svelte';
	import MarkdownMessage from './MarkdownMessage.svelte';
	import type { ChatMessage } from '$lib/api/bitbuddy';
	import { slide } from 'svelte/transition';

	let { messages, showFace = false } = $props<{
		messages: ChatMessage[];
		showFace?: boolean;
	}>();

	type ActionStatus = 'running' | 'completed' | 'error';
	type ActionRow = {
		key: string;
		name: string;
		status: ActionStatus;
		target: string;
		summary: string;
		diffCount: number;
		count: number;
		messages: ChatMessage[];
	};

	let collapsed = $state(false);
	let actionRows = $derived(buildActionRows(messages));
	let hasRunning = $derived(actionRows.some((row: ActionRow) => row.status === 'running'));
	let hasError = $derived(actionRows.some((row: ActionRow) => row.status === 'error'));
	let statusLabel = $derived(hasError ? 'Needs attention' : hasRunning ? 'Working' : 'Done');
	let groupedTools = $derived(groupByTool(messages));

	function effectiveStatus(message: ChatMessage): ActionStatus {
		if (message.status === 'error' || message.metadata?.error) return 'error';
		if (message.status === 'success' || message.status === 'completed') return 'completed';
		if (message.metadata?.result_summary || message.metadata?.diff?.files?.length) return 'completed';
		const content = (message.content || '').trim();
		if (content && !content.toLowerCase().startsWith('running ')) return 'completed';
		return 'running';
	}

	function actionKey(message: ChatMessage) {
		return `${toolName(message)}:${stableJson(message.metadata?.arguments_summary ?? {})}`;
	}

	function toolName(message: ChatMessage) {
		const name = String(message.metadata?.tool || 'tool');
		return name === 'run_subagent' ? 'subagent' : name;
	}

	function summary(message: ChatMessage) {
		return message.metadata?.result_summary || message.metadata?.error || message.content || `Running ${toolName(message)}...`;
	}

	function target(message: ChatMessage) {
		const args = message.metadata?.arguments_summary ?? {};
		const path = typeof args.file_path === 'string' ? args.file_path : typeof args.path === 'string' ? args.path : '';
		const project = typeof args.project_id === 'string' ? args.project_id : '';
		const layer = typeof args.layer === 'string' ? args.layer : '';
		if (path) return path;
		if (project && layer) return `${project}/${layer}`;
		if (project) return project;
		if (layer) return layer;
		return '';
	}

	function rowKey(message: ChatMessage, index: number) {
		return message.id ?? `${index}:${toolName(message)}:${summary(message)}`;
	}

	function buildActionRows(items: ChatMessage[]): ActionRow[] {
		const rows: ActionRow[] = [];
		for (const message of items) {
			const status = effectiveStatus(message);
			const key = actionKey(message);
			const matchIndex = status === 'running'
				? -1
				: findLatestRunningRow(rows, key);

			if (matchIndex >= 0) {
				const current = rows[matchIndex];
				rows[matchIndex] = mergeRow(current, message, status);
				continue;
			}

			rows.push({
				key: `${key}:${rows.length}`,
				name: toolName(message),
				status,
				target: target(message),
				summary: summary(message),
				diffCount: message.metadata?.diff?.files?.length ?? 0,
				count: 1,
				messages: [message]
			});
		}
		return rows;
	}

	function findLatestRunningRow(rows: ActionRow[], key: string) {
		for (let index = rows.length - 1; index >= 0; index -= 1) {
			const row = rows[index];
			if (row.status === 'running' && row.key.startsWith(`${key}:`)) return index;
		}
		return -1;
	}

	function mergeRow(row: ActionRow, message: ChatMessage, status: ActionStatus): ActionRow {
		return {
			...row,
			status,
			target: target(message) || row.target,
			summary: summary(message) || row.summary,
			diffCount: message.metadata?.diff?.files?.length ?? row.diffCount,
			count: row.count + 1,
			messages: [...row.messages, message]
		};
	}

	function stableJson(value: unknown) {
		try {
			return JSON.stringify(sortJsonValue(value));
		} catch {
			return '';
		}
	}

	function sortJsonValue(value: unknown): unknown {
		if (Array.isArray(value)) return value.map(sortJsonValue);
		if (value && typeof value === 'object') {
			return Object.fromEntries(
				Object.entries(value as Record<string, unknown>)
					.sort(([left], [right]) => left.localeCompare(right))
					.map(([key, nested]) => [key, sortJsonValue(nested)])
			);
		}
		return value;
	}

	function groupByTool(items: ChatMessage[]) {
		return items.reduce((groups, message) => {
			const name = toolName(message);
			const existing = groups.find((group) => group.name === name);
			if (existing) {
				existing.messages.push(message);
				return groups;
			}
			groups.push({ name, messages: [message] });
			return groups;
		}, [] as { name: string; messages: ChatMessage[] }[]);
	}

	function toggleCollapsed() {
		collapsed = !collapsed;
	}
</script>

{#if messages.length}
	<div class="actions-row">
		{#if showFace}
			<BitBuddyFace isThinking={hasRunning} />
		{:else}
			<div class="face-spacer" aria-hidden="true"></div>
		{/if}

		<section class:error={hasError} class:running={hasRunning} class="actions-card" aria-label="BitBuddy actions">
			<header class="actions-header">
				<div class="actions-title">
					<span class="actions-icon" aria-hidden="true">
						{#if hasError}
							<WarningCircleIcon size={16} weight="duotone" />
						{:else if hasRunning}
							<CircleNotchIcon size={16} weight="bold" />
						{:else}
							<CheckCircleIcon size={16} weight="duotone" />
						{/if}
					</span>
					<div>
						<strong>Actions</strong>
						<small>{messages.length} step{messages.length === 1 ? '' : 's'} across {groupedTools.length} tool{groupedTools.length === 1 ? '' : 's'}</small>
					</div>
				</div>
				<div class="actions-meta">
					<span class="status">{statusLabel}</span>
					<button class="toggle-btn" type="button" onclick={toggleCollapsed} aria-expanded={!collapsed}>
						<span class="caret" class:open={!collapsed}><CaretRightIcon size={14} weight="bold" /></span>
						<span>{collapsed ? 'Show' : 'Hide'}</span>
					</button>
				</div>
			</header>

			{#if !collapsed}
				<div class="actions-list" transition:slide={{ duration: 180 }}>
					{#each actionRows as row (row.key)}
						<article class:error={row.status === 'error'} class:running={row.status === 'running'} class="action-row">
							<div class="row-icon"><WrenchIcon size={14} weight="bold" /></div>
							<div class="row-body">
								<div class="row-heading">
									<strong>{row.name}{row.count > 2 ? ` x${row.count - 1}` : ''}</strong>
									<span>{row.status}</span>
								</div>
								{#if row.target}<div class="target">{row.target}</div>{/if}
								<div class="summary"><MarkdownMessage content={row.summary} compact /></div>
								{#if row.diffCount}<div class="diff-chip">{row.diffCount} file diff{row.diffCount === 1 ? '' : 's'}</div>{/if}
							</div>
						</article>
					{/each}
				</div>
			{/if}
		</section>
	</div>
{/if}

<style>
	.actions-row {
		width: 100%;
		max-width: min(76rem, 98%);
		display: grid;
		grid-template-columns: 2.8rem minmax(0, 1fr);
		align-items: start;
		gap: 0.85rem;
	}

	.face-spacer {
		width: 2.8rem;
		height: 2.8rem;
	}

	.actions-card {
		min-width: 0;
		border: 1px solid color-mix(in srgb, var(--mode-border, var(--border)) 72%, transparent);
		border-radius: 1.15rem;
		background:
			linear-gradient(180deg, rgba(255, 255, 255, 0.032), rgba(255, 255, 255, 0.01)),
			var(--event-bg, rgba(121, 184, 255, 0.055));
		color: var(--text-muted);
		overflow: hidden;
	}

	.actions-card.running {
		border-style: dashed;
	}

	.actions-card.error {
		border-color: color-mix(in srgb, var(--danger) 42%, transparent);
		background: color-mix(in srgb, var(--danger) 8%, var(--event-bg));
	}

	.actions-header {
		padding: 0.78rem 0.9rem;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.85rem;
		border-top: 1px solid rgba(255, 255, 255, 0.14);
	}

	.actions-title,
	.actions-meta,
	.row-heading {
		display: flex;
		align-items: center;
		gap: 0.65rem;
		min-width: 0;
	}

	.actions-icon,
	.row-icon {
		width: 1.85rem;
		height: 1.85rem;
		display: grid;
		place-items: center;
		border: 1px solid color-mix(in srgb, var(--mode-color) 46%, transparent);
		border-radius: 0.72rem;
		background: var(--surface-card);
		color: var(--mode-color);
		flex: 0 0 auto;
	}

	.actions-card.running .actions-icon :global(svg) {
		animation: spin 900ms linear infinite;
	}

	.actions-title strong,
	.row-heading strong {
		display: block;
		color: var(--text);
		font-size: 0.78rem;
		font-weight: 850;
		letter-spacing: 0.05em;
		text-transform: uppercase;
	}

	.actions-title small {
		display: block;
		color: var(--text-soft);
		font-size: 0.76rem;
	}

	.status,
	.toggle-btn,
	.row-heading span,
	.diff-chip {
		border: 1px solid var(--chip-border, var(--border));
		border-radius: 999px;
		background: var(--chip-bg, var(--bg-soft));
		color: var(--text-soft);
		font-size: 0.68rem;
		font-weight: 800;
		letter-spacing: 0.05em;
		text-transform: uppercase;
	}

	.status,
	.row-heading span,
	.diff-chip {
		padding: 0.14rem 0.45rem;
	}

	.toggle-btn {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.2rem 0.58rem;
	}

	.caret {
		display: inline-flex;
		transition: transform 0.2s ease;
	}

	.caret.open {
		transform: rotate(90deg);
	}

	.actions-list {
		display: grid;
		gap: 0.45rem;
		padding: 0 0.75rem 0.75rem;
	}

	.action-row {
		display: grid;
		grid-template-columns: 1.85rem minmax(0, 1fr);
		gap: 0.65rem;
		padding: 0.62rem;
		border: 1px solid color-mix(in srgb, var(--border) 70%, transparent);
		border-radius: 0.9rem;
		background: color-mix(in srgb, var(--surface-card) 78%, transparent);
	}

	.action-row.running .row-icon :global(svg) {
		animation: pulse 900ms ease-in-out infinite alternate;
	}

	.action-row.error {
		border-color: color-mix(in srgb, var(--danger) 38%, transparent);
	}

	.row-body {
		min-width: 0;
		display: grid;
		gap: 0.25rem;
	}

	.row-heading {
		justify-content: space-between;
	}

	.target {
		color: var(--accent-strong);
		font-family: var(--font-ui);
		font-size: 0.76rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.summary {
		color: var(--text-muted);
		font-size: 0.84rem;
	}

	.diff-chip {
		width: max-content;
		margin-top: 0.1rem;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	@keyframes pulse {
		from { opacity: 0.58; transform: scale(0.96); }
		to { opacity: 1; transform: scale(1); }
	}

	@media (max-width: 760px) {
		.actions-row {
			max-width: 100%;
		}

		.actions-header,
		.actions-meta {
			align-items: flex-start;
		}

		.actions-header {
			flex-direction: column;
		}
	}
</style>
