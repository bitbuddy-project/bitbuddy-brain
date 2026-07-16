<script lang="ts">
	import CaretRightIcon from 'phosphor-svelte/lib/CaretRightIcon';
	import FileCodeIcon from 'phosphor-svelte/lib/FileCodeIcon';
	import { slide } from 'svelte/transition';
	import type { ToolDiff, ToolDiffFile } from '$lib/api/bitbuddy';

	const SMALL_DIFF_LINES = 40;

	let { diff, toolName = 'file change', status = 'completed' } = $props<{
		diff: ToolDiff;
		toolName?: string;
		status?: string;
	}>();

	let expanded = $state(false);
	let rawExpanded = $state(false);
	let userToggled = $state(false);
	let lastFingerprint = $state('');

	let files: ToolDiffFile[] = $derived(diff.files ?? []);
	let totalAdded = $derived(files.reduce((total: number, file: ToolDiffFile) => total + Number(file.added || 0), 0));
	let totalRemoved = $derived(files.reduce((total: number, file: ToolDiffFile) => total + Number(file.removed || 0), 0));
	let totalLines = $derived(files.reduce((total: number, file: ToolDiffFile) => total + diffLines(file).length, 0));
	let fileLabel = $derived(`${files.length} file${files.length === 1 ? '' : 's'}`);
	let isSmallDiff = $derived(totalLines > 0 && totalLines <= SMALL_DIFF_LINES);
	let displayStatus = $derived(status === 'success' ? 'completed' : status);

	$effect(() => {
		const fingerprint = files.map((file: ToolDiffFile) => `${file.path}:${file.added}:${file.removed}:${file.unified.length}`).join('|');
		if (fingerprint === lastFingerprint) return;

		lastFingerprint = fingerprint;
		userToggled = false;
		expanded = isSmallDiff;
	});

	function toggleExpanded() {
		userToggled = true;
		expanded = !expanded;
	}

	function diffLines(file: ToolDiffFile) {
		return (file.unified || '').split('\n').filter((line) => line.length > 0);
	}

	function cleanLines(file: ToolDiffFile) {
		const lines = diffLines(file)
			.map((line) => {
				if (line.startsWith('@@')) return { kind: 'hunk', text: hunkLabel(line) };
				if (line.startsWith('+++') || line.startsWith('---')) return null;
				if (line === '+') return { kind: 'added blank', text: '+ blank line' };
				if (line === '-') return { kind: 'removed blank', text: '- blank line' };
				if (line.startsWith('+')) return { kind: 'added', text: line };
				if (line.startsWith('-')) return { kind: 'removed', text: line };
				return null;
			})
			.filter((line): line is { kind: string; text: string } => line !== null);

		return lines.length ? lines : [{ kind: 'context', text: 'No line-level changes.' }];
	}

	function lineKind(line: string) {
		if (line.startsWith('@@')) return 'hunk';
		if (line.startsWith('+++') || line.startsWith('---')) return 'file';
		if (line.startsWith('+')) return 'added';
		if (line.startsWith('-')) return 'removed';
		return 'context';
	}

	function statusLabel(file: ToolDiffFile) {
		return file.status || 'modified';
	}

	function titleStatus(file: ToolDiffFile) {
		const status = statusLabel(file);
		return status.charAt(0).toUpperCase() + status.slice(1);
	}

	function displayPath(path: string) {
		const clean = path.replace(/^([ab])\/+/, '').replace(/^\/home\/[^/]+/, '~');
		return clean || path;
	}

	function hunkLabel(line: string) {
		const match = line.match(/\+(\d+)/) ?? line.match(/-(\d+)/);
		return match ? `Around line ${match[1]}` : 'Nearby changes';
	}
</script>

<div class="diff-card" class:expanded class:small={isSmallDiff}>
	<div class="diff-icon"><FileCodeIcon size={16} weight="duotone" /></div>
	<div class="diff-body">
		<div class="diff-header">
			<div class="diff-title">
				<strong>{toolName}</strong>
				<span class="status">{displayStatus}</span>
			</div>
			<button class="toggle-btn" type="button" onclick={toggleExpanded} aria-expanded={expanded}>
				<span class="caret" class:open={expanded}><CaretRightIcon size={13} weight="bold" /></span>
				<span>{expanded ? 'Hide diff' : 'Show diff'}</span>
			</button>
		</div>

		<div class="diff-summary">
			<span>{fileLabel}</span>
			<span class="added">+{totalAdded}</span>
			<span class="removed">-{totalRemoved}</span>
			{#if isSmallDiff && !userToggled}
				<span class="auto-note">auto-expanded</span>
			{/if}
		</div>

		{#if expanded}
			<div class="diff-files" transition:slide={{ duration: 180 }}>
				{#each files as file (file.path)}
					<section class="diff-file">
						<div class="file-header">
							<div class="file-title">
								<span class="file-status">{titleStatus(file)}</span>
								<span class="file-path">{displayPath(file.path)}</span>
							</div>
							<button class="raw-toggle" type="button" onclick={() => (rawExpanded = !rawExpanded)} aria-expanded={rawExpanded}>
								{rawExpanded ? 'Readable view' : 'Raw diff'}
							</button>
						</div>
						{#if rawExpanded}
							<pre aria-label={`Raw diff for ${file.path}`}>{#each diffLines(file) as line}<code class={lineKind(line)}>{line}</code>{/each}</pre>
						{:else}
							<pre class="clean-diff" aria-label={`Changed lines for ${file.path}`}>{#each cleanLines(file) as line}<code class={line.kind}>{line.text}</code>{/each}</pre>
						{/if}
						{#if file.truncated}
							<div class="truncated-note">Diff was truncated.</div>
						{/if}
					</section>
				{/each}
			</div>
		{/if}
	</div>
</div>

<style>
	.diff-card {
		max-width: min(58rem, 94%);
		margin-left: 3rem;
		display: grid;
		grid-template-columns: 1.85rem minmax(0, 1fr);
		gap: 0.7rem;
		align-items: start;
		padding: 0.75rem 0.85rem;
		border: 1px solid color-mix(in srgb, var(--success) 38%, transparent);
		border-radius: 1rem;
		background:
			linear-gradient(180deg, rgba(255, 255, 255, 0.026), rgba(255, 255, 255, 0.008)),
			color-mix(in srgb, var(--success) 8%, var(--event-bg));
		color: var(--text-muted);
	}

	.diff-icon {
		width: 1.85rem;
		height: 1.85rem;
		display: grid;
		place-items: center;
		border: 1px solid rgba(110, 231, 183, 0.5);
		border-radius: 0.7rem;
		color: #6ee7b7;
		background: var(--surface-card);
	}

	.diff-body {
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 0.45rem;
	}

	.diff-header,
	.diff-title,
	.diff-summary,
	.file-header,
	.toggle-btn {
		display: flex;
		align-items: center;
	}

	.diff-header {
		justify-content: space-between;
		gap: 0.75rem;
	}

	.diff-title,
	.diff-summary {
		gap: 0.55rem;
		min-width: 0;
	}

	strong {
		color: var(--text);
		font-size: 0.78rem;
		font-weight: 850;
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}

	.status,
	.auto-note,
	.file-status {
		padding: 0.12rem 0.45rem;
		border: 1px solid var(--chip-border, var(--border));
		border-radius: 999px;
		color: var(--text-soft);
		font-size: 0.68rem;
		font-weight: 800;
		letter-spacing: 0.05em;
		text-transform: uppercase;
	}

	.diff-summary {
		font-size: 0.82rem;
		color: var(--text-soft);
	}

	.added {
		color: #6ee7b7;
		font-weight: 850;
	}

	.removed {
		color: #ff8b9a;
		font-weight: 850;
	}

	.toggle-btn {
		gap: 0.32rem;
		border: 1px solid color-mix(in srgb, var(--success) 28%, transparent);
		border-radius: 999px;
		padding: 0.24rem 0.58rem;
		background: var(--chip-bg, rgba(255, 255, 255, 0.045));
		color: var(--text-muted);
		font: inherit;
		font-size: 0.72rem;
		font-weight: 800;
		cursor: pointer;
	}

	.toggle-btn:hover {
		border-color: rgba(110, 231, 183, 0.45);
		color: var(--text);
	}

	.caret {
		display: grid;
		place-items: center;
		transition: transform 0.16s ease;
	}

	.caret.open {
		transform: rotate(90deg);
	}

	.diff-files {
		display: flex;
		flex-direction: column;
		gap: 0.7rem;
		padding-top: 0.2rem;
	}

	.diff-file {
		overflow: hidden;
		border: 1px solid color-mix(in srgb, var(--border) 82%, transparent);
		border-radius: 0.85rem;
		background: color-mix(in srgb, var(--bg) 82%, black);
	}

	.file-header {
		justify-content: space-between;
		gap: 0.75rem;
		padding: 0.48rem 0.65rem 0.48rem 0.8rem;
		border-bottom: 1px solid color-mix(in srgb, var(--border) 82%, transparent);
		background: var(--panel-header, rgba(255, 255, 255, 0.045));
	}

	.file-title {
		min-width: 0;
		display: flex;
		align-items: center;
		gap: 0.55rem;
	}

	.file-path {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: #d8eeff;
		font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', monospace;
		font-size: 0.75rem;
		font-weight: 800;
	}

	.raw-toggle {
		flex: 0 0 auto;
		border: 1px solid rgba(255, 255, 255, 0.14);
		border-radius: 999px;
		padding: 0.2rem 0.52rem;
		background: rgba(255, 255, 255, 0.045);
		color: #a9bad2;
		font: inherit;
		font-size: 0.68rem;
		font-weight: 850;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		cursor: pointer;
	}

	.raw-toggle:hover {
		border-color: rgba(110, 231, 183, 0.35);
		color: #eef5ff;
	}

	pre {
		margin: 0;
		padding: 0.7rem 0;
		overflow: auto;
	}

	code {
		display: block;
		min-width: max-content;
		padding: 0 0.85rem;
		font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', monospace;
		font-size: 0.8rem;
		line-height: 1.55;
		white-space: pre;
	}

	code.added {
		background: rgba(46, 160, 67, 0.2);
		color: #b7f5c6;
	}

	code.removed {
		background: rgba(248, 81, 73, 0.18);
		color: #ffbdc5;
	}

	code.hunk {
		background: rgba(121, 184, 255, 0.14);
		color: #9ed0ff;
		font-weight: 800;
	}

	code.file {
		color: #d7c5ff;
		font-weight: 800;
	}

	code.context {
		color: #d8dee9;
	}

	.clean-diff code.hunk {
		margin: 0.3rem 0 0.18rem;
		background: transparent;
		color: #8fb7dd;
		font-family: var(--font-sans, inherit);
		font-size: 0.72rem;
		font-weight: 850;
		letter-spacing: 0.06em;
		text-transform: uppercase;
	}

	.clean-diff code.blank {
		font-style: italic;
		opacity: 0.84;
	}

	.truncated-note {
		padding: 0.45rem 0.75rem;
		border-top: 1px solid rgba(255, 255, 255, 0.1);
		color: var(--text-soft);
		font-size: 0.78rem;
	}

	@media (max-width: 760px) {
		.diff-card {
			max-width: 100%;
			margin-left: 0;
			grid-template-columns: 1.65rem minmax(0, 1fr);
		}

		.diff-header {
			align-items: flex-start;
			flex-direction: column;
		}
	}
</style>
