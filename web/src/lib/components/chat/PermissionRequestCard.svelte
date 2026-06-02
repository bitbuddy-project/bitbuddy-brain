<script lang="ts">
	import type { ChatMessage } from '$lib/api/bitbuddy';
	import { respondToPermission } from '$lib/stores/chat.svelte';
	import ShieldCheck from 'phosphor-svelte/lib/ShieldCheck';
	import ShieldWarning from 'phosphor-svelte/lib/ShieldWarning';
	import Terminal from 'phosphor-svelte/lib/Terminal';
	import CaretDown from 'phosphor-svelte/lib/CaretDown';
	import CaretRight from 'phosphor-svelte/lib/CaretRight';
	import MessageBubble from './MessageBubble.svelte';

	let { message, buddyName = 'BitBuddy' } = $props<{
		message: ChatMessage;
		buddyName?: string;
	}>();

	let expanded = $state(false);
	let localDecision = $state<'approved' | 'denied' | null>(null);
	let submitting = $state(false);

	const isPending = $derived(message.status === 'running');
	const isApproved = $derived(message.status === 'success' || localDecision === 'approved');
	const isDenied = $derived(message.status === 'error' || localDecision === 'denied');
	const shouldShowOverlay = $derived(isPending && localDecision === null);
	const shouldShowSummaryBubble = $derived(
		!shouldShowOverlay && (isApproved || isDenied || localDecision !== null)
	);

	const tool = $derived(message.metadata?.tool || 'unknown tool');
	const argumentsSummary = $derived(message.metadata?.arguments_summary || {});
	const hasArguments = $derived(Object.keys(argumentsSummary).length > 0);
	const detailsId = $derived(`permission-details-${message.id ?? tool}`);
	const argumentsJson = $derived.by(() => prettyJson(argumentsSummary));

	const effectiveDecision = $derived.by(() => {
		if (isApproved) return 'approved';
		if (isDenied) return 'denied';
		return localDecision ?? '';
	});

	const summaryContent = $derived.by(() => buildSummaryContent(effectiveDecision, tool, argumentsSummary));

	function buildSummaryContent(
		decision: 'approved' | 'denied' | '',
		toolName: string,
		args: Record<string, unknown>
	) {
		const decisionLabel = decision === 'denied' ? 'denied' : 'approved';
		const target = summarizePermissionTarget(toolName, args);

		if (target) {
			return `Permission ${decisionLabel}: ${target}`;
		}

		return `Permission ${decisionLabel} for \`${toolName}\`.`;
	}

	function summarizePermissionTarget(toolName: string, args: Record<string, unknown>) {
		const command = stringArg(args, 'command');
		if (toolName === 'run_shell_command' && command) {
			return `\`${toolName}\` — \`${command}\``;
		}

		const path = stringArg(args, 'path') || stringArg(args, 'file_path');
		const projectId = stringArg(args, 'project_id');
		if (toolName === 'read_file' && path && projectId) {
			return `\`${toolName}\` — \`${path}\` from \`${projectId}\``;
		}
		if (toolName === 'read_file' && path) {
			return `\`${toolName}\` — \`${path}\``;
		}

		if (path) {
			return `\`${toolName}\` — \`${path}\``;
		}

		if (projectId) {
			return `\`${toolName}\` — \`${projectId}\``;
		}

		if (Object.keys(args).length > 0) {
			return `\`${toolName}\` — ${inlineJson(args)}`;
		}

		return `\`${toolName}\``;
	}

	function stringArg(args: Record<string, unknown>, key: string) {
		const value = args[key];
		return typeof value === 'string' ? value.trim() : '';
	}

	function inlineJson(value: unknown) {
		try {
			return `\`${JSON.stringify(value)}\``;
		} catch {
			return '`arguments unavailable`';
		}
	}

	function prettyJson(value: unknown) {
		try {
			return JSON.stringify(value, null, 2);
		} catch {
			return 'Arguments unavailable.';
		}
	}

	function toggleExpanded() {
		expanded = !expanded;
	}

	async function handleApprove() {
		if (submitting) return;

		submitting = true;
		localDecision = 'approved';

		try {
			await respondToPermission(true);
		} catch (error) {
			console.error('Failed to approve permission request:', error);
			localDecision = null;
		} finally {
			submitting = false;
		}
	}

	async function handleDeny() {
		if (submitting) return;

		submitting = true;
		localDecision = 'denied';

		try {
			await respondToPermission(false);
		} catch (error) {
			console.error('Failed to deny permission request:', error);
			localDecision = null;
		} finally {
			submitting = false;
		}
	}
</script>

{#snippet permissionCard()}
	<div
		class="permission-card"
		class:pending={isPending && localDecision === null}
		class:approved={isApproved}
		class:denied={isDenied}
	>
		<div class="header">
			<div class="icon">
				{#if isApproved}
					<ShieldCheck size={18} weight="fill" />
				{:else if isDenied}
					<ShieldWarning size={18} weight="fill" />
				{:else}
					<ShieldWarning size={18} weight="fill" />
				{/if}
			</div>

			<div class="title">
				{#if isApproved}
					Permission Granted
				{:else if isDenied}
					Permission Denied
				{:else}
					Permission Required
				{/if}
			</div>
		</div>

		<div class="body">
			<p class="reason">{message.content}</p>

			<div class="tool-info">
				<div class="tool-name">
					<Terminal size={14} weight="bold" />
					<span>{tool}</span>
				</div>

				{#if hasArguments}
					<button class="details-toggle" type="button" onclick={toggleExpanded} aria-expanded={expanded} aria-controls={detailsId}>
						{#if expanded}
							<CaretDown size={14} weight="bold" />
						{:else}
							<CaretRight size={14} weight="bold" />
						{/if}
						Details
					</button>
				{/if}
			</div>

			{#if expanded && hasArguments}
				<div class="details" id={detailsId}>
					<pre>{argumentsJson}</pre>
				</div>
			{/if}
		</div>

		{#if isPending && localDecision === null}
			<div class="actions">
				<button class="deny-btn" type="button" onclick={handleDeny} disabled={submitting}>
					Deny
				</button>

				<button class="approve-btn" type="button" onclick={handleApprove} disabled={submitting}>
					Approve
				</button>
			</div>
		{/if}
	</div>
{/snippet}

{#if shouldShowOverlay}
	<div class="permission-overlay" role="presentation">
		<div class="permission-dialog" role="dialog" aria-modal="true" aria-label="Permission request">
			{@render permissionCard()}
		</div>
	</div>
{:else if shouldShowSummaryBubble}
	<MessageBubble role="assistant" content={summaryContent} {buddyName} />
{/if}

<style>
	.permission-overlay {
		position: fixed;
		inset: 0;
		z-index: 10000;
		display: grid;
		place-items: center;
		padding: 1rem;
		background: color-mix(in srgb, var(--bg) 28%, transparent);
		backdrop-filter: blur(8px);
		-webkit-backdrop-filter: blur(8px);
		animation: overlayFadeIn 0.18s ease-out;
	}

	.permission-dialog {
		width: min(34rem, 100%);
		max-height: calc(100vh - 2rem);
		overflow: hidden;
		border-radius: var(--radius-md);
		box-shadow: var(--shadow-soft);
	}

	.permission-card {
		--permission-status: var(--warning);

		display: flex;
		flex-direction: column;
		max-height: calc(100vh - 2rem);
		border: 1px solid var(--permission-status);
		border-radius: var(--radius-md);
		background: var(--card-bg, var(--panel-raised));
		color: var(--text);
		overflow: hidden;
		margin: 0.5rem 0;
		box-shadow: var(--shadow-panel);
		animation: cardFadeIn 0.22s ease-out;
	}

	.permission-dialog .permission-card {
		margin: 0;
	}

	.permission-card.pending {
		--permission-status: var(--warning);
	}

	.permission-card.approved {
		--permission-status: var(--success);
	}

	.permission-card.denied {
		--permission-status: var(--danger);
	}

	.header,
	.actions {
		background: var(--panel-header, var(--panel-raised));
	}

	.header {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		flex: 0 0 auto;
		padding: 0.85rem 1rem;
		border-bottom: 1px solid var(--border-strong);
	}

	.icon {
		display: grid;
		place-items: center;
		width: 1.75rem;
		height: 1.75rem;
		border: 1px solid var(--permission-status);
		border-radius: 999px;
		background: var(--panel);
		color: var(--permission-status);
		flex: 0 0 auto;
	}

	.title {
		font-weight: 800;
		font-size: 0.86rem;
		letter-spacing: 0.035em;
		text-transform: uppercase;
		color: var(--text);
	}

	.body {
		min-height: 0;
		overflow-y: auto;
		padding: 1rem;
		background: var(--card-bg, var(--panel-raised));
	}

	.reason {
		margin: 0 0 1rem 0;
		font-size: 0.94rem;
		line-height: 1.55;
		color: var(--text);
	}

	.tool-info {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
	}

	.tool-name {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		min-width: 0;
		font-family: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace);
		font-size: 0.85rem;
		color: var(--text-muted);
		background: var(--chip-bg, var(--panel));
		border: 1px solid var(--chip-border, var(--border));
		padding: 0.38rem 0.6rem;
		border-radius: var(--radius-sm);
	}

	.tool-name span {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.details-toggle {
		display: flex;
		align-items: center;
		gap: 0.25rem;
		background: transparent;
		border: 1px solid transparent;
		color: var(--text-muted);
		font-size: 0.85rem;
		font-weight: 600;
		cursor: pointer;
		padding: 0.35rem 0.45rem;
		border-radius: var(--radius-sm);
	}

	.details-toggle:hover {
		background: var(--chip-bg, var(--panel));
		border-color: var(--border);
		color: var(--text);
	}

	.details {
		margin-top: 0.85rem;
		max-height: min(22rem, 42vh);
		overflow: auto;
		background: var(--panel);
		border: 1px solid var(--border);
		border-radius: var(--radius-sm);
		padding: 0.75rem;
	}

	.details pre {
		margin: 0;
		font-size: 0.8rem;
		line-height: 1.45;
		overflow: visible;
		color: var(--text-muted);
	}

	.actions {
		display: flex;
		flex: 0 0 auto;
		padding: 0.85rem 1rem;
		gap: 0.75rem;
		justify-content: flex-end;
		border-top: 1px solid var(--border-strong);
	}

	button {
		padding: 0.45rem 1rem;
		border-radius: var(--radius-sm);
		font-size: 0.875rem;
		font-weight: 700;
		cursor: pointer;
		transition:
			background 0.14s ease,
			color 0.14s ease,
			border-color 0.14s ease,
			transform 0.14s ease,
			opacity 0.14s ease;
	}

	button:hover:not(:disabled) {
		transform: translateY(-1px);
	}

	button:disabled {
		cursor: wait;
		opacity: 0.72;
	}

	.approve-btn {
		background: var(--success);
		color: var(--bg);
		border: 1px solid var(--success);
	}

	.approve-btn:hover:not(:disabled) {
		filter: brightness(0.94);
	}

	.deny-btn {
		background: transparent;
		color: var(--danger);
		border: 1px solid var(--danger);
	}

	.deny-btn:hover:not(:disabled) {
		background: color-mix(in srgb, var(--danger) 10%, transparent);
	}

	@keyframes overlayFadeIn {
		from {
			opacity: 0;
		}

		to {
			opacity: 1;
		}
	}

	@keyframes cardFadeIn {
		from {
			opacity: 0;
			transform: translateY(10px) scale(0.985);
		}

		to {
			opacity: 1;
			transform: translateY(0) scale(1);
		}
	}

	@media (max-width: 760px) {
		.permission-overlay {
			align-items: end;
			padding: 0.75rem;
		}

		.permission-dialog,
		.permission-card {
			width: 100%;
			max-height: calc(100vh - 1.5rem);
		}

		.tool-info {
			align-items: flex-start;
			flex-direction: column;
		}

		.actions {
			flex-direction: column-reverse;
		}

		.actions button {
			width: 100%;
		}
	}
</style>
