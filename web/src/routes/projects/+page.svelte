<script lang="ts">
	import { onMount } from 'svelte';
	import Skeleton from '$lib/components/Skeleton.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import BlueprintIcon from 'phosphor-svelte/lib/BlueprintIcon';
	import FolderOpenIcon from 'phosphor-svelte/lib/FolderOpenIcon';
	import PlusIcon from 'phosphor-svelte/lib/PlusIcon';
	import TrashIcon from 'phosphor-svelte/lib/TrashIcon';
	import XIcon from 'phosphor-svelte/lib/XIcon';
	import ConfirmDialog from '$lib/components/ui/ConfirmDialog.svelte';
	import { addProject, deleteProject, getProjects, type ProjectSummary } from '$lib/api/bitbuddy';

	let projects = $state<ProjectSummary[]>([]);
	let loading = $state(true);
	let error = $state('');
	let addOpen = $state(false);
	let adding = $state(false);
	let deleting = $state(false);
	let pendingDeleteProject = $state<ProjectSummary | null>(null);
	let projectName = $state('');
	let projectPaths = $state('');

	onMount(() => {
		void loadProjects();
	});

	async function loadProjects() {
		loading = true;
		try {
			projects = await getProjects();
			error = '';
		} catch (caught) {
			error = caught instanceof Error ? caught.message : 'Could not load projects.';
		} finally {
			loading = false;
		}
	}

	function primaryPath(project: ProjectSummary): string {
		return project.paths?.[0] ?? 'No path recorded';
	}

	async function submitProject() {
		const paths = projectPaths
			.split('\n')
			.map((path) => path.trim())
			.filter(Boolean);
		if (!projectName.trim() || paths.length === 0) {
			error = 'Project name and at least one path are required.';
			return;
		}

		adding = true;
		try {
			await addProject({ name: projectName.trim(), paths });
			projectName = '';
			projectPaths = '';
			addOpen = false;
			await loadProjects();
		} catch (caught) {
			error = caught instanceof Error ? caught.message : 'Could not add project.';
		} finally {
			adding = false;
		}
	}

	function requestRemoveProject(project: ProjectSummary) {
		pendingDeleteProject = project;
	}

	async function removeProject() {
		if (!pendingDeleteProject) return;
		deleting = true;
		try {
			await deleteProject(pendingDeleteProject.id);
			pendingDeleteProject = null;
			await loadProjects();
			error = '';
		} catch (caught) {
			error = caught instanceof Error ? caught.message : 'Could not delete project.';
		} finally {
			deleting = false;
		}
	}
</script>

<div class="projects-page">
	<PageHeader icon={BlueprintIcon} eyebrow="Workspace Map" title="Projects" subtitle="Registered read-only project paths BitBuddy can use for memory and context.">
		{#snippet action()}
				<button
					class="add-project-button"
					class:active={addOpen}
					type="button"
					aria-label={addOpen ? 'Close add project form' : 'Add project'}
					aria-expanded={addOpen}
					onclick={() => (addOpen = !addOpen)}
				>
					<span class="icon-wrap plus-icon" class:hidden={addOpen}>
						<PlusIcon size={22} weight="bold" />
					</span>
					<span class="icon-wrap x-icon" class:hidden={!addOpen}>
						<XIcon size={22} weight="bold" />
					</span>
				</button>
			{/snippet}
	</PageHeader>
	<section class="projects-panel" aria-label="Registered projects">

		<div class="projects-content">
			{#if addOpen}
				<form class="add-project-form" onsubmit={(event) => { event.preventDefault(); void submitProject(); }}>
					<div class="form-grid">
						<label>
							<span>Project name</span>
							<input bind:value={projectName} placeholder="Anchorbox" autocomplete="off" />
						</label>
						<label>
							<span>Project path</span>
							<input bind:value={projectPaths} placeholder="/home/dustin/dev/active/anchorbox" autocomplete="off" />
						</label>
					</div>
					<div class="form-actions">
						<button class="cancel-button" type="button" onclick={() => (addOpen = false)} disabled={adding}>Cancel</button>
						<button class="submit-button" type="submit" disabled={adding}>{adding ? 'Adding...' : 'Add project'}</button>
					</div>
				</form>
			{/if}

			{#if error && projects.length > 0}
				<div class="inline-error">{error}</div>
			{/if}

			{#if loading}
				<Skeleton variant="card" count={3} />
			{:else if error && projects.length === 0}
				<div class="center-state error-state">
					<h2>Could not load projects</h2>
					<p>{error}</p>
				</div>
			{:else if projects.length === 0}
				<div class="center-state empty-state">
					<div class="empty-icon">
						<FolderOpenIcon size={42} weight="duotone" />
					</div>
					<h2>No projects registered</h2>
					<p>Add one with <code>bitbuddy projects add my-project /path/to/project</code>.</p>
				</div>
			{:else}
				<div class="projects-grid">
					{#each projects as project}
						<article class="project-card">
							<div class="project-icon" aria-hidden="true">
								<BlueprintIcon size={24} weight="duotone" />
							</div>
							<div class="project-copy">
								<h2>{project.name}</h2>
								<p>{primaryPath(project)}</p>
								<div class="project-meta">
									<span>{project.id}</span>
									<span>{project.access ?? 'read-only'}</span>
								</div>
							</div>
							<button
								class="delete-project-button"
								type="button"
								aria-label="Delete project"
								onclick={() => requestRemoveProject(project)}
							>
								<TrashIcon size={18} weight="bold" />
							</button>
						</article>
					{/each}
				</div>
			{/if}
		</div>
	</section>
</div>

<ConfirmDialog
	open={Boolean(pendingDeleteProject)}
	title="Delete project memory?"
	description={`This removes ${pendingDeleteProject?.name ?? 'this project'} and its BitBuddy memory data. This cannot be undone.`}
	confirmLabel="Delete project"
	destructive
	busy={deleting}
	onCancel={() => (pendingDeleteProject = null)}
	onConfirm={removeProject}
/>

<style>
	.projects-page {
		--page-accent: var(--accent);
		--page-soft: color-mix(in srgb, var(--accent-soft) 72%, transparent);
		--page-border: color-mix(in srgb, var(--accent) 20%, var(--border));
		--page-glow: color-mix(in srgb, var(--accent) 10%, transparent);

		width: 100%;
		max-width: 100%;
		padding: 0 1rem;
		height: 100%;
		margin: 0 auto;
		display: flex;
		flex-direction: column;
		gap: 0.7rem;
		min-height: 0;
		animation: fade-in 0.35s cubic-bezier(0.16, 1, 0.3, 1);
	}

	@keyframes fade-in {
		from { opacity: 0; transform: translateY(12px); }
		to { opacity: 1; transform: translateY(0); }
	}

	.projects-panel {
		--page-accent: var(--accent);
		--page-soft: color-mix(in srgb, var(--accent-soft) 72%, transparent);
		--page-border: color-mix(in srgb, var(--accent) 20%, var(--border));
		--page-glow: color-mix(in srgb, var(--accent) 10%, transparent);

		width: 100%;
		flex: 1 1 auto;
		min-height: 0;
		display: flex;
		flex-direction: column;
		border: 1px solid var(--page-border);
		border-radius: 1.45rem;
		background:
			linear-gradient(135deg, var(--glass-overlay), transparent 22rem),
			radial-gradient(circle at top right, var(--page-glow), transparent 30rem),
			radial-gradient(circle at bottom left, color-mix(in srgb, var(--success) 5.5%, transparent), transparent 34rem),
			var(--panel);
		box-shadow: var(--shadow-chat);
		overflow: hidden;
	}


	.add-project-button {
		width: 2.75rem;
		height: 2.75rem;
		display: grid;
		place-items: center;
		flex: 0 0 auto;
		position: relative;
		border: 1px solid var(--border-strong);
		border-radius: 999px;
		background: var(--accent-soft);
		color: var(--page-accent);
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease, transform 120ms ease;
		overflow: hidden;
	}

	.add-project-button:hover {
		border-color: var(--accent);
		background: var(--accent);
		color: var(--on-accent);
		transform: translateY(-1px);
	}

	.icon-wrap {
		display: grid;
		place-items: center;
		transition: transform 200ms cubic-bezier(0.34, 1.56, 0.64, 1), opacity 150ms ease;
	}

	.plus-icon {
		transform: rotate(0deg) scale(1);
	}

	.plus-icon.hidden {
		transform: rotate(-90deg) scale(0.5);
		opacity: 0;
	}

	.x-icon {
		position: absolute;
		inset: 0;
		transform: rotate(90deg) scale(0.5);
		opacity: 0;
	}

	.x-icon.hidden {
		transform: rotate(0deg) scale(1);
		opacity: 0;
	}

	.x-icon:not(.hidden) {
		transform: rotate(0deg) scale(1);
		opacity: 1;
	}

	.center-state p,
	.project-copy p {
		color: var(--text-soft);
	}

	.projects-content {
		flex: 1 1 auto;
		min-height: 0;
		overflow-y: auto;
		padding: 1.25rem;
		scrollbar-color: var(--scrollbar-thumb) transparent;
	}

	.projects-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr));
		gap: 1rem;
	}

	.add-project-form {
		margin-bottom: 1rem;
		padding: 1rem;
		display: grid;
		gap: 1rem;
		border: 1px solid var(--border);
		border-radius: 1.2rem;
		background: var(--surface-card);
		box-shadow: var(--shadow-panel);
	}

	.form-grid {
		display: grid;
		grid-template-columns: minmax(12rem, 0.7fr) minmax(16rem, 1fr);
		gap: 0.85rem;
	}

	label {
		display: grid;
		gap: 0.35rem;
	}

	label span {
		color: var(--page-accent);
		font-size: 0.72rem;
		font-weight: 800;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	input,
	input {
		width: 100%;
		height: 2.9rem;
		padding: 0.75rem 0.85rem;
		border: 1px solid var(--border);
		border-radius: 0.9rem;
		background: var(--surface-inset);
		color: var(--text);
	}

	input:focus {
		border-color: var(--accent);
		box-shadow: 0 0 0 3px var(--accent-soft);
	}

	.form-actions {
		display: flex;
		justify-content: flex-end;
		gap: 0.6rem;
	}

	.cancel-button,
	.submit-button {
		padding: 0.65rem 0.95rem;
		border-radius: 999px;
		font-size: 0.85rem;
		font-weight: 800;
	}

	.cancel-button {
		border: 1px solid var(--border);
		color: var(--text-muted);
	}

	.submit-button {
		background: var(--accent);
		color: var(--on-accent);
	}

	.cancel-button:disabled,
	.submit-button:disabled {
		opacity: 0.55;
		cursor: not-allowed;
	}

	.project-card {
		padding: 1.2rem;
		display: flex;
		gap: 0.9rem;
		align-items: flex-start;
		border: 1px solid var(--border);
		border-radius: 1.2rem;
		background: var(--surface-card);
		box-shadow: var(--shadow-panel);
	}

	.delete-project-button {
		width: 2rem;
		height: 2rem;
		display: grid;
		place-items: center;
		flex: 0 0 auto;
		margin-left: auto;
		border: 1px solid var(--border);
		border-radius: 0.6rem;
		background: transparent;
		color: var(--text-muted);
		cursor: pointer;
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
	}

	.delete-project-button:hover {
		border-color: var(--danger);
		background: color-mix(in srgb, var(--danger) 10%, transparent);
		color: var(--danger);
	}

	.empty-icon,
	.project-icon {
		display: grid;
		place-items: center;
		background: var(--page-soft);
		color: var(--page-accent);
	}

	.project-icon {
		width: 2.6rem;
		height: 2.6rem;
		flex: 0 0 auto;
		border-radius: 0.9rem;
	}

	.project-copy {
		min-width: 0;
	}

	.project-copy h2 {
		font-size: 1.1rem;
		font-weight: 900;
		letter-spacing: -0.02em;
	}

	.project-copy p {
		margin-top: 0.25rem;
		font-size: 0.85rem;
		overflow-wrap: anywhere;
	}

	.project-meta {
		margin-top: 0.75rem;
		display: flex;
		flex-wrap: wrap;
		gap: 0.45rem;
	}

	.project-meta span {
		padding: 0.24rem 0.5rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		color: var(--text-muted);
		font-size: 0.72rem;
	}

	.center-state {
		min-height: 22rem;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 1rem;
		text-align: center;
	}

	.center-state h2 {
		color: var(--text);
		font-size: 1.35rem;
		font-weight: 900;
		letter-spacing: -0.02em;
	}

	.empty-icon {
		width: 5rem;
		height: 5rem;
		border-radius: 1.5rem;
	}

	.error-state {
		color: var(--danger);
	}

	.inline-error {
		margin-bottom: 1rem;
		padding: 0.85rem 1rem;
		border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent);
		border-radius: 1rem;
		background: color-mix(in srgb, var(--danger) 8%, transparent);
		color: var(--danger);
	}


	@media (max-width: 900px) {
		.projects-page,
		.projects-panel {
			height: auto;
			max-height: none;
		}
	}

	@media (max-width: 640px) {
		.form-grid {
			grid-template-columns: 1fr;
		}

		.form-actions {
			justify-content: stretch;
		}

		.cancel-button,
		.submit-button {
			flex: 1;
		}
	}
</style>
