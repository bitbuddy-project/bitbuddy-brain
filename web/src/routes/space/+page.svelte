<script lang="ts">
	import { onMount } from 'svelte';
	import HouseLineIcon from 'phosphor-svelte/lib/HouseLineIcon';
	import ArchiveIcon from 'phosphor-svelte/lib/ArchiveIcon';
	import TargetIcon from 'phosphor-svelte/lib/TargetIcon';
	import MarkdownMessage from '$lib/components/chat/MarkdownMessage.svelte';
	import {
		archiveWorkspaceDocument,
		getGoals,
		getWorkspaceDocument,
		getWorkspaceDocuments,
		type GoalItem,
		type WorkspaceDocument
	} from '$lib/api/bitbuddy';

	const KIND_ORDER = ['notes', 'drafts', 'research', 'journal'];
	const KIND_LABELS: Record<string, string> = {
		notes: 'Notes',
		drafts: 'Drafts',
		research: 'Research',
		journal: 'Journal'
	};

	let documents = $state<WorkspaceDocument[]>([]);
	let goals = $state<GoalItem[]>([]);
	let selectedId = $state<string | null>(null);
	let selectedDoc = $state<WorkspaceDocument | null>(null);
	let loadingList = $state(true);
	let loadingDetail = $state(false);
	let archivingId = $state<string | null>(null);
	let error = $state('');

	let selfGoals = $derived(goals.filter((g) => g.owner === 'self' && g.status === 'active'));
	let groups = $derived(
		KIND_ORDER.map((kind) => ({
			kind,
			label: KIND_LABELS[kind] ?? kind,
			docs: documents.filter((d) => d.kind === kind)
		})).filter((group) => group.docs.length > 0)
	);

	onMount(() => {
		void load();
	});

	async function load() {
		loadingList = true;
		try {
			const [docs, goalList] = await Promise.all([getWorkspaceDocuments(), getGoals(false)]);
			documents = docs;
			goals = goalList;
			error = '';
			if (documents.length > 0 && !selectedId) {
				await selectDoc(documents[0].id);
			}
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Could not load the workspace.';
		} finally {
			loadingList = false;
		}
	}

	async function selectDoc(id: string) {
		if (selectedId === id && selectedDoc) return;
		selectedId = id;
		loadingDetail = true;
		try {
			selectedDoc = await getWorkspaceDocument(id);
		} catch {
			selectedDoc = null;
		} finally {
			loadingDetail = false;
		}
	}

	function goalTitleFor(goalId: string): string {
		const goal = goals.find((g) => String(g.id) === goalId);
		return goal ? goal.title : '';
	}

	async function doArchive(id: string) {
		if (archivingId !== id) {
			archivingId = id;
			return;
		}
		try {
			await archiveWorkspaceDocument(id);
			documents = documents.filter((d) => d.id !== id);
			if (selectedId === id) {
				if (documents.length > 0) await selectDoc(documents[0].id);
				else {
					selectedId = null;
					selectedDoc = null;
				}
			}
		} catch {
			// ignore
		} finally {
			archivingId = null;
		}
	}

	function formatWhen(value: string): string {
		if (!value) return '';
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return value;
		return date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
	}
</script>

<svelte:head>
	<title>BitBuddy — AI Space</title>
</svelte:head>

<div class="space-page">
	<section class="space-panel" aria-label="AI workspace">
		<header class="space-header">
			<div class="title-mark" aria-hidden="true"><HouseLineIcon size={30} weight="duotone" /></div>
			<div class="title-copy">
				<p class="eyebrow">Workspace</p>
				<h1>AI Space</h1>
				<p>{documents.length} document{documents.length === 1 ? '' : 's'} · {selfGoals.length} active goal{selfGoals.length === 1 ? '' : 's'}</p>
			</div>
		</header>

		<div class="space-content">
			{#if selfGoals.length > 0}
				<section class="goals-strip" aria-label="Current AI goals">
					{#each selfGoals as goal (goal.id)}
						<article class="goal-card">
							<div class="goal-card-head">
								<TargetIcon size={15} weight="duotone" />
								<span class="goal-title">{goal.title}</span>
							</div>
							{#if goal.next_action}
								<p class="goal-next">{goal.next_action}</p>
							{/if}
						</article>
					{/each}
				</section>
			{/if}

			{#if error}
				<div class="error-banner">{error}</div>
			{:else if loadingList}
				<div class="loading-state">Loading workspace...</div>
			{:else if documents.length === 0}
				<div class="empty-state">This workspace is empty for now. BitBuddy will leave notes, drafts, and research here while working on goals.</div>
			{:else}
				<div class="space-layout">
			<aside class="doc-list" aria-label="Workspace documents">
				{#each groups as group (group.kind)}
					<div class="doc-group">
						<h3 class="group-label">{group.label}</h3>
						{#each group.docs as doc (doc.id)}
							<button
								class="doc-item"
								class:active={selectedId === doc.id}
								type="button"
								onclick={() => selectDoc(doc.id)}
							>
								<span class="doc-title">{doc.title}</span>
								{#if doc.summary}
									<span class="doc-summary">{doc.summary}</span>
								{/if}
								<span class="doc-meta">
									{formatWhen(doc.updated_at)}
									{#if doc.goal_id && goalTitleFor(doc.goal_id)}
										· from goal: {goalTitleFor(doc.goal_id)}
									{/if}
								</span>
							</button>
						{/each}
					</div>
				{/each}
			</aside>

			<div class="doc-detail">
				{#if loadingDetail}
					<div class="detail-loading">Loading…</div>
				{:else if selectedDoc}
					<div class="detail-header">
						<div class="detail-title-row">
							<h2>{selectedDoc.title}</h2>
							<span class="kind-badge">{KIND_LABELS[selectedDoc.kind] ?? selectedDoc.kind}</span>
						</div>
						<p class="detail-meta">
							Updated {formatWhen(selectedDoc.updated_at)}
							{#if selectedDoc.goal_id && goalTitleFor(selectedDoc.goal_id)}
								· from goal: <strong>{goalTitleFor(selectedDoc.goal_id)}</strong>
							{/if}
							{#if selectedDoc.source}
								· {selectedDoc.source}
							{/if}
						</p>
						<button
							class="archive-btn"
							class:confirm={archivingId === selectedDoc.id}
							type="button"
							onclick={() => selectedDoc && doArchive(selectedDoc.id)}
							onblur={() => { if (archivingId === selectedDoc?.id) archivingId = null; }}
						>
							<ArchiveIcon size={14} />
							{archivingId === selectedDoc.id ? 'Confirm archive?' : 'Archive'}
						</button>
					</div>
					<div class="detail-body">
						{#if selectedDoc.body}
							<MarkdownMessage content={selectedDoc.body} />
						{:else}
							<p class="no-body">This document is empty.</p>
						{/if}
					</div>
				{:else}
					<div class="no-selection">Select a document to read it.</div>
				{/if}
			</div>
				</div>
			{/if}
		</div>
	</section>
</div>

<style>
	.space-page {
		--page-accent: #79b8ff;
		--page-soft: rgba(121, 184, 255, 0.12);
		--page-border: rgba(121, 184, 255, 0.25);
		--page-glow: rgba(121, 184, 255, 0.14);

		width: 100%;
		max-width: 100%;
		padding: 0 1rem;
		height: 100%;
		margin: 0 auto;
		display: flex;
		min-height: 0;
		animation: fade-in 0.35s cubic-bezier(0.16, 1, 0.3, 1);
	}

	@keyframes fade-in {
		from { opacity: 0; transform: translateY(12px); }
		to { opacity: 1; transform: translateY(0); }
	}

	.space-panel {
		width: 100%;
		height: 100%;
		max-height: calc(100vh - 3rem);
		min-height: 0;
		display: flex;
		flex-direction: column;
		border: 1px solid var(--page-border);
		border-radius: 1.45rem;
		background:
			linear-gradient(135deg, var(--glass-overlay), transparent 22rem),
			radial-gradient(circle at top right, var(--page-glow), transparent 30rem),
			radial-gradient(circle at bottom left, rgba(110, 231, 183, 0.055), transparent 34rem),
			var(--panel);
		box-shadow: var(--shadow-chat);
		overflow: hidden;
	}

	.space-header {
		flex: 0 0 auto;
		padding: 1.35rem 1.5rem;
		display: flex;
		align-items: center;
		gap: 1rem;
		border-bottom: 1px solid var(--border);
		background:
			linear-gradient(135deg, var(--page-soft), transparent 70%),
			var(--header-bg);
	}

	.title-mark {
		width: 3.5rem;
		height: 3.5rem;
		display: grid;
		place-items: center;
		border-radius: 1.1rem;
		background: var(--surface-glass);
		border: 1px solid var(--page-border);
		color: var(--page-accent);
		box-shadow: 0 0 20px var(--page-soft);
		flex: 0 0 auto;
	}

	.title-copy {
		min-width: 0;
	}

	.eyebrow {
		color: var(--page-accent);
		font-size: 0.72rem;
		font-weight: 800;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	h1 {
		font-size: 1.65rem;
		font-weight: 900;
		letter-spacing: -0.03em;
		line-height: 1.1;
	}

	.title-copy p:last-child {
		margin: 0.15rem 0 0;
		color: var(--text-soft);
	}

	.space-content {
		flex: 1 1 auto;
		min-height: 0;
		padding: 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 1rem;
		overflow: hidden;
		scrollbar-color: var(--scrollbar-thumb) transparent;
	}

	.goals-strip {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(15rem, 1fr));
		gap: 0.6rem;
		flex-shrink: 0;
	}

	.goal-card {
		border: 1px solid var(--border);
		border-radius: 1rem;
		background: var(--surface-card);
		box-shadow: var(--shadow-panel);
		padding: 0.7rem 0.85rem;
		min-width: 0;
	}

	.goal-card-head {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		color: var(--page-accent);
	}

	.goal-title {
		font-size: 0.85rem;
		font-weight: 700;
		color: var(--text);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		min-width: 0;
	}

	.goal-next {
		margin: 0.35rem 0 0;
		font-size: 0.78rem;
		color: var(--text-soft);
		overflow-wrap: break-word;
	}

	.space-layout {
		display: grid;
		grid-template-columns: 18rem 1fr;
		gap: 1rem;
		min-height: 0;
		flex: 1;
	}

	.doc-list {
		display: flex;
		flex-direction: column;
		gap: 0.8rem;
		overflow-y: auto;
		padding-right: 0.25rem;
		scrollbar-color: var(--scrollbar-thumb) transparent;
	}

	.doc-group {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}

	.group-label {
		margin: 0 0 0.1rem;
		font-size: 0.72rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--text-muted);
	}

	.doc-item {
		display: flex;
		flex-direction: column;
		gap: 0.2rem;
		padding: 0.7rem 0.9rem;
		border: 1px solid var(--border);
		border-radius: 0.85rem;
		background: var(--surface-card);
		text-align: left;
		cursor: pointer;
		transition: all 120ms ease;
	}

	.doc-item:hover {
		border-color: var(--border-strong);
		background: var(--panel-raised);
	}

	.doc-item.active {
		border-color: var(--page-accent);
		background: var(--page-soft);
	}

	.doc-title {
		font-size: 0.88rem;
		font-weight: 700;
		color: var(--text);
	}

	.doc-summary {
		font-size: 0.76rem;
		color: var(--text-soft);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.doc-meta {
		font-size: 0.7rem;
		color: var(--text-muted);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.doc-detail {
		display: flex;
		flex-direction: column;
		border: 1px solid var(--border-strong);
		border-radius: 1.25rem;
		background: var(--surface-card);
		box-shadow: var(--shadow-panel);
		overflow: hidden;
		min-height: 0;
	}

	.detail-header {
		padding: 1.25rem 1.5rem;
		border-bottom: 1px solid var(--border);
		flex-shrink: 0;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}

	.detail-title-row {
		display: flex;
		align-items: center;
		gap: 0.6rem;
	}

	.detail-title-row h2 {
		margin: 0;
		font-size: 1.1rem;
		font-weight: 800;
		color: var(--text);
		min-width: 0;
		overflow-wrap: break-word;
	}

	.kind-badge {
		font-size: 0.72rem;
		font-weight: 700;
		padding: 0.15rem 0.45rem;
		border-radius: 999px;
		background: var(--page-soft);
		color: var(--page-accent);
		flex-shrink: 0;
	}

	.detail-meta {
		margin: 0;
		font-size: 0.8rem;
		color: var(--text-soft);
	}

	.archive-btn {
		align-self: flex-start;
		display: flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.35rem 0.75rem;
		border: 1px solid var(--border);
		border-radius: 0.6rem;
		background: transparent;
		color: var(--text-muted);
		font-size: 0.8rem;
		font-weight: 600;
		cursor: pointer;
		transition: all 120ms ease;
	}

	.archive-btn:hover,
	.archive-btn.confirm {
		border-color: var(--warning);
		color: var(--warning);
		background: color-mix(in srgb, var(--warning) 10%, transparent);
	}

	.detail-body {
		padding: 1.5rem;
		overflow-y: auto;
		flex: 1;
		min-height: 0;
	}

	.detail-loading,
	.no-selection,
	.no-body {
		padding: 3rem;
		text-align: center;
		color: var(--text-soft);
		font-size: 0.9rem;
	}

	.loading-state,
	.empty-state {
		flex: 1;
		display: flex;
		align-items: center;
		justify-content: center;
		text-align: center;
		color: var(--text-soft);
		font-size: 0.95rem;
		padding: 2rem;
		min-height: 18rem;
	}

	.error-banner {
		padding: 0.85rem 1.25rem;
		border-radius: 0.75rem;
		background: color-mix(in srgb, var(--danger) 12%, transparent);
		border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent);
		color: var(--danger);
		font-size: 0.9rem;
	}

	@media (max-width: 900px) {
		.space-page,
		.space-panel {
			height: auto;
			max-height: none;
		}

		.space-content {
			overflow: visible;
		}

		.space-layout {
			grid-template-columns: 1fr;
			grid-template-rows: 14rem 1fr;
		}

		.doc-list {
			flex-direction: row;
			overflow-x: auto;
			overflow-y: hidden;
			padding-bottom: 0.25rem;
		}

		.doc-group {
			flex-shrink: 0;
			width: 13rem;
		}
	}

	@media (max-width: 640px) {
		.space-page {
			padding: 0;
		}

		.space-header {
			align-items: flex-start;
		}

		.title-mark {
			width: 3rem;
			height: 3rem;
		}
	}
</style>
