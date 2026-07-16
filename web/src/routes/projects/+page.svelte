<script lang="ts">
	import { onMount } from 'svelte';
	import Skeleton from '$lib/components/Skeleton.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import BlueprintIcon from 'phosphor-svelte/lib/BlueprintIcon';
	import FolderOpenIcon from 'phosphor-svelte/lib/FolderOpenIcon';
	import PlusIcon from 'phosphor-svelte/lib/PlusIcon';
	import TrashIcon from 'phosphor-svelte/lib/TrashIcon';
	import XIcon from 'phosphor-svelte/lib/XIcon';
	import CaretLeftIcon from 'phosphor-svelte/lib/CaretLeftIcon';
	import PencilSimpleIcon from 'phosphor-svelte/lib/PencilSimpleIcon';
	import ArchiveIcon from 'phosphor-svelte/lib/ArchiveIcon';
	import FileTextIcon from 'phosphor-svelte/lib/FileTextIcon';
	import ConfirmDialog from '$lib/components/ui/ConfirmDialog.svelte';
	import Overlay from '$lib/components/ui/Overlay.svelte';
	import SelectMenu, { type SelectOption } from '$lib/components/ui/SelectMenu.svelte';
	import {
		addProject,
		archiveProjectSpec,
		createProjectSpec,
		deleteProject,
		getProjectSpec,
		getProjectSpecs,
		getProjects,
		updateProjectPaths,
		updateProjectSpec,
		type ProjectSpec,
		type ProjectSummary
	} from '$lib/api/bitbuddy';

	let projects = $state<ProjectSummary[]>([]);
	let loading = $state(true);
	let error = $state('');
	let addOpen = $state(false);
	let adding = $state(false);
	let deleting = $state(false);
	let pendingDeleteProject = $state<ProjectSummary | null>(null);
	let projectName = $state('');
	let projectPaths = $state('');

	let editPathsProject = $state<ProjectSummary | null>(null);
	let editPathsValue = $state('');
	let savingPaths = $state(false);
	let editPathsError = $state('');

	let selectedProject = $state<ProjectSummary | null>(null);
	let specs = $state<ProjectSpec[]>([]);
	let specsLoading = $state(false);
	let specsError = $state('');
	let showArchivedSpecs = $state(false);

	let specEditorOpen = $state(false);
	let editingSpec = $state<ProjectSpec | null>(null);
	let specTitle = $state('');
	let specBody = $state('');
	let specStatus = $state('draft');
	let specTags = $state('');
	let specSaving = $state(false);
	let specError = $state('');
	let pendingArchiveSpec = $state<ProjectSpec | null>(null);
	let archiving = $state(false);

	const specStatusOptions: SelectOption[] = [
		{ value: 'draft', label: 'Draft', description: 'Not injected into context' },
		{ value: 'active', label: 'Active', description: 'Injected into project context' },
		{ value: 'archived', label: 'Archived', description: 'Hidden from context and lists' }
	];

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
			if (selectedProject?.id === pendingDeleteProject.id) selectedProject = null;
			pendingDeleteProject = null;
			await loadProjects();
			error = '';
		} catch (caught) {
			error = caught instanceof Error ? caught.message : 'Could not delete project.';
		} finally {
			deleting = false;
		}
	}

	function openEditPaths(project: ProjectSummary) {
		editPathsProject = project;
		editPathsValue = (project.paths ?? []).join('\n');
		editPathsError = '';
	}

	async function submitEditPaths() {
		if (!editPathsProject) return;
		const paths = editPathsValue
			.split('\n')
			.map((path) => path.trim())
			.filter(Boolean);
		if (paths.length === 0) {
			editPathsError = 'At least one directory is required.';
			return;
		}
		savingPaths = true;
		try {
			const updated = await updateProjectPaths(editPathsProject.id, paths);
			if (selectedProject?.id === updated.id) selectedProject = updated;
			editPathsProject = null;
			await loadProjects();
			error = '';
		} catch (caught) {
			editPathsError = caught instanceof Error ? caught.message : 'Could not update directories.';
		} finally {
			savingPaths = false;
		}
	}

	async function openProject(project: ProjectSummary) {
		selectedProject = project;
		specs = [];
		specsError = '';
		await loadSpecs();
	}

	async function closeProject() {
		selectedProject = null;
		specs = [];
		specsError = '';
	}

	async function loadSpecs() {
		if (!selectedProject) return;
		specsLoading = true;
		specsError = '';
		try {
			specs = await getProjectSpecs(selectedProject.id, { includeArchived: showArchivedSpecs });
		} catch (caught) {
			specsError = caught instanceof Error ? caught.message : 'Could not load specs.';
		} finally {
			specsLoading = false;
		}
	}

	async function toggleArchivedSpecs() {
		showArchivedSpecs = !showArchivedSpecs;
		await loadSpecs();
	}

	function openNewSpecEditor() {
		editingSpec = null;
		specTitle = '';
		specBody = '';
		specStatus = 'draft';
		specTags = '';
		specError = '';
		specEditorOpen = true;
	}

	async function openEditSpecEditor(spec: ProjectSpec) {
		editingSpec = spec;
		specTitle = spec.title;
		specBody = spec.body ?? '';
		specStatus = spec.status;
		specTags = (spec.tags ?? []).join(', ');
		specError = '';
		let working = spec;
		try {
			working = await getProjectSpec(selectedProject!.id, spec.id);
			specBody = working.body ?? specBody;
		} catch {
			// fall back to list-level data
		}
		specEditorOpen = true;
	}

	function closeSpecEditor() {
		specEditorOpen = false;
		editingSpec = null;
		specError = '';
	}

	async function saveSpec() {
		if (!selectedProject) return;
		if (!specTitle.trim()) {
			specError = 'Title is required.';
			return;
		}
		const tags = specTags
			.split(',')
			.map((tag) => tag.trim())
			.filter(Boolean);
		specSaving = true;
		specError = '';
		try {
			if (editingSpec) {
				await updateProjectSpec(selectedProject.id, editingSpec.id, {
					title: specTitle.trim(),
					body: specBody,
					status: specStatus,
					tags
				});
			} else {
				await createProjectSpec(selectedProject.id, {
					title: specTitle.trim(),
					body: specBody,
					status: specStatus,
					tags
				});
			}
			specEditorOpen = false;
			editingSpec = null;
			await loadSpecs();
		} catch (caught) {
			specError = caught instanceof Error ? caught.message : 'Could not save spec.';
		} finally {
			specSaving = false;
		}
	}

	function requestArchiveSpec(spec: ProjectSpec) {
		pendingArchiveSpec = spec;
	}

	async function archiveSpec() {
		if (!selectedProject || !pendingArchiveSpec) return;
		archiving = true;
		try {
			await archiveProjectSpec(selectedProject.id, pendingArchiveSpec.id);
			pendingArchiveSpec = null;
			await loadSpecs();
		} catch (caught) {
			specsError = caught instanceof Error ? caught.message : 'Could not archive spec.';
		} finally {
			archiving = false;
		}
	}

	function statusBadgeClass(status: string): string {
		if (status === 'active') return 'status-badge active';
		if (status === 'archived') return 'status-badge archived';
		return 'status-badge draft';
	}
</script>

<div class="projects-page">
	<PageHeader icon={BlueprintIcon} eyebrow="Workspace Map" title="Projects" subtitle="Registered read-only project paths BitBuddy can use for memory and context.">
		{#snippet action()}
			{#if !selectedProject}
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
			{/if}
		{/snippet}
	</PageHeader>
	<section class="projects-panel" aria-label="Registered projects">

		<div class="projects-content">
			{#if selectedProject}
				<button class="back-button" type="button" onclick={closeProject}>
					<CaretLeftIcon size={18} weight="bold" />
					<span>All projects</span>
				</button>
				<header class="detail-header">
					<div class="project-icon project-icon-lg" aria-hidden="true">
						<BlueprintIcon size={28} weight="duotone" />
					</div>
					<div class="detail-copy">
						<h2>{selectedProject.name}</h2>
						<p>{primaryPath(selectedProject)}</p>
						<div class="project-meta">
							<span>{selectedProject.id}</span>
							<span>{selectedProject.access ?? 'read-only'}</span>
						</div>
					</div>
				</header>

				<div class="specs-section">
					<div class="specs-header">
						<div class="specs-title">
							<FileTextIcon size={20} weight="duotone" />
							<h3>Specs</h3>
							{#if specs.length}
								<span class="specs-count">{specs.length}</span>
							{/if}
						</div>
						<div class="specs-actions">
							<button class="toggle-mini" type="button" onclick={toggleArchivedSpecs}>
								{showArchivedSpecs ? 'Hide archived' : 'Show archived'}
							</button>
							<button class="new-spec-button" type="button" onclick={openNewSpecEditor}>
								<PlusIcon size={16} weight="bold" />
								<span>New spec</span>
							</button>
						</div>
					</div>

					{#if specsError}
						<div class="inline-error">{specsError}</div>
					{/if}

					{#if specsLoading}
						<Skeleton variant="card" count={2} />
					{:else if specs.length === 0}
						<div class="specs-empty">
							<p>No specs {showArchivedSpecs ? 'found' : 'yet'}. Specs capture how this project is supposed to look and behave.</p>
						</div>
					{:else}
						<div class="specs-list">
							{#each specs as spec (spec.id)}
								<article class="spec-card">
									<div class="spec-card-head">
										<h4>{spec.title}</h4>
										<span class={statusBadgeClass(spec.status)}>{spec.status}</span>
									</div>
									{#if spec.tags?.length}
										<div class="spec-tags">
											{#each spec.tags as tag}
												<span class="spec-tag">{tag}</span>
											{/each}
										</div>
									{/if}
									{#if spec.body}
										<p class="spec-body-preview">{spec.body.slice(0, 240)}{spec.body.length > 240 ? '…' : ''}</p>
									{/if}
									<div class="spec-card-actions">
										<button class="spec-action edit" type="button" onclick={() => openEditSpecEditor(spec)}>
											<PencilSimpleIcon size={15} weight="bold" />
											<span>Edit</span>
										</button>
										{#if spec.status !== 'archived'}
											<button class="spec-action archive" type="button" onclick={() => requestArchiveSpec(spec)}>
												<ArchiveIcon size={15} weight="bold" />
												<span>Archive</span>
											</button>
										{/if}
									</div>
								</article>
							{/each}
						</div>
					{/if}
				</div>
			{:else if addOpen}
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

			{#if !selectedProject}
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
						{#each projects as project (project.id)}
							<div class="project-card clickable" role="button" tabindex="0"
								onclick={() => openProject(project)}
								onkeydown={(event) => {
									if (event.key === 'Enter' || event.key === ' ') {
										event.preventDefault();
										openProject(project);
									}
								}}
							>
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
								<div class="project-card-actions">
									<button
										class="edit-project-button"
										type="button"
										aria-label="Change project directories"
										title="Change directories"
										onclick={(event) => { event.stopPropagation(); openEditPaths(project); }}
									>
										<PencilSimpleIcon size={18} weight="bold" />
									</button>
									<button
										class="delete-project-button"
										type="button"
										aria-label="Delete project"
										onclick={(event) => { event.stopPropagation(); requestRemoveProject(project); }}
									>
										<TrashIcon size={18} weight="bold" />
									</button>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			{/if}
		</div>
	</section>
</div>

<Overlay open={specEditorOpen} label="Project spec editor" wide onClose={closeSpecEditor}>
	{#if specEditorOpen}
		<form class="spec-editor" onsubmit={(event) => { event.preventDefault(); void saveSpec(); }}>
			<div class="spec-editor-head">
				<h3>{editingSpec ? 'Edit spec' : 'New spec'}</h3>
			</div>
			{#if specError}
				<div class="inline-error">{specError}</div>
			{/if}
			<label class="field">
				<span>Title</span>
				<input bind:value={specTitle} placeholder="Auth Redesign" autocomplete="off" />
			</label>
			<label class="field">
				<span>Status</span>
				<div class="select-field">
					<SelectMenu
						value={specStatus}
						options={specStatusOptions}
						ariaLabel="Spec status"
						onChange={(value) => (specStatus = value)}
					/>
				</div>
			</label>
			<label class="field">
				<span>Tags (comma separated)</span>
				<input bind:value={specTags} placeholder="backend, security" autocomplete="off" />
			</label>
			<label class="field grow">
				<span>Body (Markdown)</span>
				<textarea bind:value={specBody} placeholder="# Purpose&#10;&#10;Describe what this project or feature should become.&#10;&#10;# Requirements&#10;- ...&#10;&#10;# Acceptance Criteria&#10;- ..."></textarea>
			</label>
			<div class="form-actions">
				<button class="cancel-button" type="button" onclick={closeSpecEditor} disabled={specSaving}>Cancel</button>
				<button class="submit-button" type="submit" disabled={specSaving}>{specSaving ? 'Saving...' : 'Save spec'}</button>
			</div>
		</form>
	{/if}
</Overlay>

<Overlay open={Boolean(editPathsProject)} label="Change project directories" onClose={() => (editPathsProject = null)}>
	{#if editPathsProject}
		<form class="paths-editor" onsubmit={(event) => { event.preventDefault(); void submitEditPaths(); }}>
			<div class="paths-editor-head">
				<h3>Change directories</h3>
				<p>Re-point <strong>{editPathsProject.name}</strong> at a new location. Its memory and history are kept.</p>
			</div>
			{#if editPathsError}
				<div class="inline-error">{editPathsError}</div>
			{/if}
			<label class="field">
				<span>Directories <small>(one path per line)</small></span>
				<textarea bind:value={editPathsValue} rows="4" placeholder="/home/dustin/dev/active/anchorbox" autocomplete="off"></textarea>
			</label>
			<div class="form-actions">
				<button class="cancel-button" type="button" onclick={() => (editPathsProject = null)} disabled={savingPaths}>Cancel</button>
				<button class="submit-button" type="submit" disabled={savingPaths}>{savingPaths ? 'Saving...' : 'Save directories'}</button>
			</div>
		</form>
	{/if}
</Overlay>

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

<ConfirmDialog
	open={Boolean(pendingArchiveSpec)}
	title="Archive spec?"
	description={`Archiving marks "${pendingArchiveSpec?.title ?? 'this spec'}" as archived. It will no longer be injected into project context. You can still find it under "Show archived".`}
	confirmLabel="Archive spec"
	busy={archiving}
	onCancel={() => (pendingArchiveSpec = null)}
	onConfirm={archiveSpec}
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

	.project-card.clickable {
		cursor: pointer;
		transition: border-color 140ms ease, transform 140ms ease, box-shadow 140ms ease;
	}

	.project-card.clickable:hover {
		border-color: var(--page-accent);
		transform: translateY(-2px);
		box-shadow: var(--shadow-panel), 0 0 0 3px var(--accent-soft);
	}

	.project-card.clickable:focus-visible {
		outline: none;
		border-color: var(--page-accent);
		box-shadow: 0 0 0 3px var(--accent-soft);
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

	.project-card-actions {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		margin-left: auto;
		flex: 0 0 auto;
	}

	.edit-project-button {
		width: 2rem;
		height: 2rem;
		display: grid;
		place-items: center;
		flex: 0 0 auto;
		border: 1px solid var(--border);
		border-radius: 0.6rem;
		background: transparent;
		color: var(--text-muted);
		cursor: pointer;
		transition: background 120ms ease, border-color 120ms ease, color 120ms ease;
	}

	.edit-project-button:hover {
		border-color: var(--accent);
		background: color-mix(in srgb, var(--accent) 10%, transparent);
		color: var(--accent);
	}

	.paths-editor {
		display: flex;
		flex-direction: column;
		gap: 0.85rem;
		padding: 1.25rem;
	}

	.paths-editor-head h3 {
		font-size: 1.1rem;
		font-weight: 900;
		letter-spacing: -0.01em;
	}

	.paths-editor-head p {
		margin-top: 0.25rem;
		color: var(--text-soft);
		font-size: 0.85rem;
	}

	.paths-editor .field {
		display: grid;
		gap: 0.35rem;
	}

	.paths-editor .field small {
		color: var(--text-muted);
		font-weight: 500;
	}

	.paths-editor textarea {
		width: 100%;
		padding: 0.85rem;
		border: 1px solid var(--border);
		border-radius: 0.9rem;
		background: var(--surface-inset);
		color: var(--text);
		font-family: var(--font-mono, inherit);
		font-size: 0.88rem;
		resize: vertical;
	}

	.paths-editor textarea:focus {
		border-color: var(--accent);
		box-shadow: 0 0 0 3px var(--accent-soft);
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

	.project-icon-lg {
		width: 3rem;
		height: 3rem;
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

	.back-button {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		margin-bottom: 1rem;
		padding: 0.5rem 0.85rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: transparent;
		color: var(--text-muted);
		font-weight: 700;
		font-size: 0.85rem;
		cursor: pointer;
		transition: color 120ms ease, border-color 120ms ease;
	}

	.back-button:hover {
		color: var(--page-accent);
		border-color: var(--page-accent);
	}

	.detail-header {
		display: flex;
		gap: 1rem;
		align-items: flex-start;
		margin-bottom: 1.5rem;
		padding: 1.2rem;
		border: 1px solid var(--border);
		border-radius: 1.2rem;
		background: var(--surface-card);
		box-shadow: var(--shadow-panel);
	}

	.detail-copy h2 {
		font-size: 1.4rem;
		font-weight: 900;
		letter-spacing: -0.02em;
	}

	.detail-copy p {
		margin-top: 0.3rem;
		color: var(--text-soft);
		font-size: 0.9rem;
		overflow-wrap: anywhere;
	}

	.specs-section {
		display: flex;
		flex-direction: column;
		gap: 0.85rem;
	}

	.specs-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
		flex-wrap: wrap;
	}

	.specs-title {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		color: var(--page-accent);
	}

	.specs-title h3 {
		font-size: 1.05rem;
		font-weight: 900;
		letter-spacing: -0.01em;
	}

	.specs-count {
		padding: 0.15rem 0.5rem;
		border-radius: 999px;
		background: var(--accent-soft);
		color: var(--page-accent);
		font-size: 0.72rem;
		font-weight: 800;
	}

	.specs-actions {
		display: flex;
		gap: 0.5rem;
		align-items: center;
	}

	.toggle-mini {
		padding: 0.4rem 0.7rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: transparent;
		color: var(--text-muted);
		font-size: 0.78rem;
		font-weight: 700;
		cursor: pointer;
		transition: color 120ms ease, border-color 120ms ease;
	}

	.toggle-mini:hover {
		color: var(--page-accent);
		border-color: var(--page-accent);
	}

	.new-spec-button {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.45rem 0.85rem;
		border: 1px solid var(--page-accent);
		border-radius: 999px;
		background: var(--accent-soft);
		color: var(--page-accent);
		font-size: 0.8rem;
		font-weight: 800;
		cursor: pointer;
		transition: background 120ms ease, color 120ms ease;
	}

	.new-spec-button:hover {
		background: var(--accent);
		color: var(--on-accent);
	}

	.specs-empty {
		padding: 1.5rem;
		border: 1px dashed var(--border);
		border-radius: 1rem;
		text-align: center;
		color: var(--text-soft);
	}

	.specs-list {
		display: grid;
		gap: 0.75rem;
	}

	.spec-card {
		padding: 1rem;
		border: 1px solid var(--border);
		border-radius: 1rem;
		background: var(--surface-card);
		box-shadow: var(--shadow-panel);
	}

	.spec-card-head {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 0.6rem;
	}

	.spec-card-head h4 {
		font-size: 1rem;
		font-weight: 800;
		letter-spacing: -0.01em;
		overflow-wrap: anywhere;
	}

	.status-badge {
		flex: 0 0 auto;
		padding: 0.2rem 0.55rem;
		border-radius: 999px;
		font-size: 0.68rem;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	.status-badge.draft {
		background: color-mix(in srgb, var(--text-muted) 16%, transparent);
		color: var(--text-muted);
	}

	.status-badge.active {
		background: color-mix(in srgb, var(--success) 18%, transparent);
		color: var(--success);
	}

	.status-badge.archived {
		background: color-mix(in srgb, var(--warning) 16%, transparent);
		color: var(--warning);
	}

	.spec-tags {
		margin-top: 0.5rem;
		display: flex;
		flex-wrap: wrap;
		gap: 0.35rem;
	}

	.spec-tag {
		padding: 0.15rem 0.5rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		color: var(--text-muted);
		font-size: 0.7rem;
	}

	.spec-body-preview {
		margin-top: 0.55rem;
		color: var(--text-soft);
		font-size: 0.85rem;
		overflow-wrap: anywhere;
	}

	.spec-card-actions {
		margin-top: 0.75rem;
		display: flex;
		gap: 0.5rem;
	}

	.spec-action {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.35rem 0.7rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: transparent;
		color: var(--text-muted);
		font-size: 0.78rem;
		font-weight: 700;
		cursor: pointer;
		transition: color 120ms ease, border-color 120ms ease;
	}

	.spec-action.edit:hover {
		color: var(--page-accent);
		border-color: var(--page-accent);
	}

	.spec-action.archive:hover {
		color: var(--warning);
		border-color: var(--warning);
	}

	.spec-editor {
		display: flex;
		flex-direction: column;
		gap: 0.85rem;
		padding: 1.25rem;
	}

	.spec-editor-head {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.spec-editor-head h3 {
		font-size: 1.1rem;
		font-weight: 900;
		letter-spacing: -0.01em;
	}

	.spec-editor .field {
		display: grid;
		gap: 0.35rem;
	}

	.spec-editor .field.grow {
		flex: 1 1 auto;
	}

	.select-field {
		width: 100%;
	}

	.spec-editor textarea {
		width: 100%;
		min-height: 16rem;
		padding: 0.85rem;
		border: 1px solid var(--border);
		border-radius: 0.9rem;
		background: var(--surface-inset);
		color: var(--text);
		font-family: var(--font-mono, inherit);
		font-size: 0.88rem;
		resize: none;
	}

	.spec-editor textarea:focus {
		border-color: var(--accent);
		box-shadow: 0 0 0 3px var(--accent-soft);
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
