<script lang="ts">
	import { onMount } from 'svelte';
	import BookOpenIcon from 'phosphor-svelte/lib/BookOpenIcon';
	import ArchiveIcon from 'phosphor-svelte/lib/ArchiveIcon';
	import MarkdownMessage from '$lib/components/chat/MarkdownMessage.svelte';
	import { archiveSkillByName, getSkill, getSkills, type Skill } from '$lib/api/bitbuddy';

	let skills = $state<Skill[]>([]);
	let selectedName = $state<string | null>(null);
	let selectedSkill = $state<Skill | null>(null);
	let loadingList = $state(true);
	let loadingDetail = $state(false);
	let showArchived = $state(false);
	let archivingName = $state<string | null>(null);
	let error = $state('');

	let activeSkills = $derived(skills.filter((s) => !s.archived));
	let archivedSkills = $derived(skills.filter((s) => s.archived));
	let displaySkills = $derived(showArchived ? skills : activeSkills);

	onMount(() => {
		void loadSkills();
	});

	async function loadSkills() {
		loadingList = true;
		try {
			skills = await getSkills(true);
			error = '';
			if (skills.length > 0 && !selectedName) {
				await selectSkill(skills.find((s) => !s.archived)?.name ?? skills[0].name);
			}
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Could not load skills.';
		} finally {
			loadingList = false;
		}
	}

	async function selectSkill(name: string) {
		if (selectedName === name && selectedSkill) return;
		selectedName = name;
		loadingDetail = true;
		try {
			selectedSkill = await getSkill(name);
		} catch {
			selectedSkill = null;
		} finally {
			loadingDetail = false;
		}
	}

	async function doArchive(name: string) {
		if (archivingName !== name) {
			archivingName = name;
			return;
		}
		try {
			await archiveSkillByName(name);
			skills = skills.map((s) => s.name === name ? { ...s, archived: true } : s);
			if (selectedName === name) {
				const next = activeSkills.find((s) => s.name !== name);
				if (next) await selectSkill(next.name);
				else { selectedName = null; selectedSkill = null; }
			}
		} catch {
			// ignore
		} finally {
			archivingName = null;
		}
	}
</script>

<svelte:head>
	<title>BitBuddy — Skills</title>
</svelte:head>

<div class="skills-page">
	<header class="page-header">
		<div class="header-icon"><BookOpenIcon size={28} weight="duotone" /></div>
		<div class="header-copy">
			<h1>Skills</h1>
			<p>{activeSkills.length} active · {archivedSkills.length} archived</p>
		</div>
		{#if archivedSkills.length > 0}
			<button class="toggle-archived" type="button" onclick={() => { showArchived = !showArchived; }}>
				{showArchived ? 'Hide archived' : 'Show archived'}
			</button>
		{/if}
	</header>

	{#if error}
		<div class="error-banner">{error}</div>
	{:else if loadingList}
		<div class="loading-state">Loading skills…</div>
	{:else if displaySkills.length === 0}
		<div class="empty-state">No skills yet. Ask BitBuddy to create one.</div>
	{:else}
		<div class="skills-layout">
			<aside class="skill-list" aria-label="Skill catalog">
				{#each displaySkills as skill (skill.name)}
					<button
						class="skill-item"
						class:active={selectedName === skill.name}
						class:archived={skill.archived}
						type="button"
						onclick={() => selectSkill(skill.name)}
					>
						<span class="skill-name">{skill.name}</span>
						{#if skill.archived}
							<span class="archived-badge">archived</span>
						{:else}
							<span class="usage-hint">{skill.usage ?? 0} use{skill.usage === 1 ? '' : 's'}</span>
						{/if}
						<span class="skill-desc">{skill.description}</span>
					</button>
				{/each}
			</aside>

			<div class="skill-detail">
				{#if loadingDetail}
					<div class="detail-loading">Loading…</div>
				{:else if selectedSkill}
					<div class="detail-header">
						<div class="detail-title-row">
							<h2>{selectedSkill.name}</h2>
							<span class="version-badge">v{selectedSkill.version}</span>
						</div>
						<p class="detail-desc">{selectedSkill.description}</p>
						{#if !selectedSkill.archived}
							<button
								class="archive-btn"
								class:confirm={archivingName === selectedSkill.name}
								type="button"
								onclick={() => selectedSkill && doArchive(selectedSkill.name)}
								onblur={() => { if (archivingName === selectedSkill?.name) archivingName = null; }}
							>
								<ArchiveIcon size={14} />
								{archivingName === selectedSkill.name ? 'Confirm archive?' : 'Archive'}
							</button>
						{/if}
					</div>
					<div class="detail-body">
						{#if selectedSkill.body}
							<MarkdownMessage content={selectedSkill.body} />
						{:else}
							<p class="no-body">No body content.</p>
						{/if}
					</div>
				{:else}
					<div class="no-selection">Select a skill to view its content.</div>
				{/if}
			</div>
		</div>
	{/if}
</div>

<style>
	.skills-page {
		width: 100%;
		max-width: 72rem;
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
		padding: 0.5rem 0 2rem;
		height: calc(100vh - 3rem);
	}

	.page-header {
		display: flex;
		align-items: center;
		gap: 1rem;
		flex-shrink: 0;
	}

	.header-icon {
		width: 3rem;
		height: 3rem;
		display: grid;
		place-items: center;
		border-radius: 1rem;
		background: color-mix(in srgb, var(--success) 14%, transparent);
		color: var(--success);
		flex-shrink: 0;
	}

	.header-copy {
		flex: 1;
	}

	.header-copy h1 {
		font-size: 1.5rem;
		font-weight: 800;
		color: var(--text);
		margin: 0;
	}

	.header-copy p {
		margin: 0.15rem 0 0;
		font-size: 0.85rem;
		color: var(--text-soft);
	}

	.toggle-archived {
		padding: 0.4rem 0.85rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: transparent;
		color: var(--text-muted);
		font-size: 0.8rem;
		font-weight: 600;
		cursor: pointer;
		flex-shrink: 0;
	}

	.toggle-archived:hover {
		border-color: var(--border-strong);
		color: var(--text);
	}

	.skills-layout {
		display: grid;
		grid-template-columns: 17rem 1fr;
		gap: 1rem;
		min-height: 0;
		flex: 1;
	}

	.skill-list {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
		overflow-y: auto;
		padding-right: 0.25rem;
	}

	.skill-item {
		display: flex;
		flex-direction: column;
		gap: 0.2rem;
		padding: 0.75rem 1rem;
		border: 1px solid var(--border);
		border-radius: 0.85rem;
		background: var(--panel);
		text-align: left;
		cursor: pointer;
		transition: all 120ms ease;
	}

	.skill-item:hover {
		border-color: var(--border-strong);
		background: var(--panel-raised);
	}

	.skill-item.active {
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 8%, transparent);
	}

	.skill-item.archived {
		opacity: 0.55;
	}

	.skill-name {
		font-size: 0.9rem;
		font-weight: 700;
		color: var(--text);
	}

	.skill-desc {
		font-size: 0.78rem;
		color: var(--text-soft);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.usage-hint {
		font-size: 0.72rem;
		color: var(--text-muted);
		font-weight: 600;
	}

	.archived-badge {
		font-size: 0.7rem;
		font-weight: 700;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.skill-detail {
		display: flex;
		flex-direction: column;
		border: 1px solid var(--border-strong);
		border-radius: 1.25rem;
		background: var(--panel);
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
	}

	.version-badge {
		font-size: 0.72rem;
		font-weight: 700;
		padding: 0.15rem 0.45rem;
		border-radius: 999px;
		background: color-mix(in srgb, var(--accent) 14%, transparent);
		color: var(--accent);
	}

	.detail-desc {
		margin: 0;
		font-size: 0.85rem;
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
		.skills-layout {
			grid-template-columns: 1fr;
			grid-template-rows: 14rem 1fr;
		}

		.skill-list {
			flex-direction: row;
			overflow-x: auto;
			overflow-y: hidden;
			padding-bottom: 0.25rem;
		}

		.skill-item {
			flex-shrink: 0;
			width: 12rem;
		}
	}
</style>
