<script lang="ts">
	import { onMount } from 'svelte';
	import BrainIcon from 'phosphor-svelte/lib/BrainIcon';
	import {
		archiveMemory,
		getMemories,
		getMemoryLayers,
		getProjectMemory,
		getProjects,
		moveMemory,
		updateMemory,
		type ArchitectureSummary,
		type CurrentTaskMemory,
		type DecisionPreference,
		type FileIndexEntry,
		type MemoryLayer,
		type MemoryLayerInfo,
		type MemoryRecord,
		type ProjectCardMemory,
		type ProjectMemory,
		type ProjectSummary,
		type ReadBeforeEditingRule,
		type SymbolContract
	} from '$lib/api/bitbuddy';
	import { formatDate, formatTimestamp } from '$lib/stores/time.svelte';

	const MEMORY_TABS: MemoryLayer[] = ['project', 'episodic', 'semantic', 'procedural', 'self', 'relationship'];
	let activeTab = $state<MemoryLayer>('project');
	let layerInfos = $state<MemoryLayerInfo[]>([]);

	// Project memory state
	let projects = $state<ProjectSummary[]>([]);
	let selectedProjectId = $state('');
	let memory = $state<ProjectMemory | null>(null);
	let loadingProjects = $state(true);
	let loadingMemory = $state(false);
	let projectError = $state('');

	// Canonical layered memory state
	let memoriesByLayer = $state<Record<MemoryLayer, MemoryRecord[]>>({
		episodic: [],
		semantic: [],
		project: [],
		procedural: [],
		self: [],
		relationship: []
	});
	let loadingLayerMemories = $state(true);
	let layerError = $state('');

	// Inline edit state
	let editingMemoryId = $state<string | null>(null);
	let editTitle = $state('');
	let editSummary = $state('');
	let movingMemoryId = $state<string | null>(null);
	let memoryActionError = $state('');

	onMount(() => {
		void loadProjects();
		void loadLayerCatalog();
		void loadLayerMemories();
	});

	async function loadProjects() {
		loadingProjects = true;
		try {
			projects = await getProjects();
			projectError = '';
			if (projects[0]) {
				await selectProject(projects[0].id);
			}
		} catch (caught) {
			projectError = caught instanceof Error ? caught.message : 'Could not load project memories.';
		} finally {
			loadingProjects = false;
		}
	}

	async function loadLayerCatalog() {
		try {
			layerInfos = await getMemoryLayers();
		} catch {
			layerInfos = [];
		}
	}

	async function loadLayerMemories() {
		loadingLayerMemories = true;
		try {
			const entries = await Promise.all(MEMORY_TABS.map(async (layer) => [layer, await getMemories({ layer, limit: 30 })] as const));
			memoriesByLayer = Object.fromEntries(entries) as Record<MemoryLayer, MemoryRecord[]>;
			layerError = '';
		} catch (caught) {
			layerError = caught instanceof Error ? caught.message : 'Could not load memories.';
		} finally {
			loadingLayerMemories = false;
		}
	}

	function activeLayerInfo(): MemoryLayerInfo | undefined {
		return layerInfos.find((info) => info.layer === activeTab);
	}

	function activeLayerMemories(): MemoryRecord[] {
		return memoriesByLayer[activeTab] ?? [];
	}

	function layerTitle(layer: MemoryLayer): string {
		return `${layer.charAt(0).toUpperCase()}${layer.slice(1)} Memory`;
	}

	function layerHeading(layer: MemoryLayer): string {
		return layer.charAt(0).toUpperCase() + layer.slice(1);
	}

	async function selectProject(projectId: string) {
		selectedProjectId = projectId;
		memory = null;
		loadingMemory = true;
		try {
			const response = await getProjectMemory(projectId);
			memory = response.memory ?? null;
			projectError = '';
		} catch (caught) {
			projectError = caught instanceof Error ? caught.message : 'Could not load project memory.';
		} finally {
			loadingMemory = false;
		}
	}

	function selectedProject(): ProjectSummary | undefined {
		return projects.find((project) => project.id === selectedProjectId);
	}

	function projectCard(): ProjectCardMemory {
		return memory?.project_card ?? {};
	}

	function architecture(): ArchitectureSummary {
		return memory?.architecture_summary ?? {};
	}

	function fileIndex(): FileIndexEntry[] {
		return memory?.file_index ?? [];
	}

	function symbolContracts(): SymbolContract[] {
		return memory?.symbol_contracts ?? [];
	}

	function decisions(): DecisionPreference[] {
		return memory?.decisions_preferences ?? [];
	}

	function tasks(): CurrentTaskMemory[] {
		return memory?.current_task_memory ?? [];
	}

	function readRules(): ReadBeforeEditingRule[] {
		return memory?.read_before_editing_rules ?? [];
	}

	function facts(): string[] {
		return splitFacts(projectCard().verified_facts);
	}

	function inferences(): string[] {
		return splitFacts(projectCard().inferred_facts);
	}

	function totalIndexedFiles(): string {
		const indexedFact = facts().find((fact) => fact.startsWith('indexed_file_count='));
		return indexedFact?.split('=', 2)[1] ?? '';
	}

	function hasProjectOverview(): boolean {
		const card = projectCard();
		return Boolean(card.repo_path || card.stack || card.purpose || card.current_status || card.needs_read || facts().length || inferences().length);
	}

	function hasArchitecture(): boolean {
		const arch = architecture();
		return Boolean(arch.backend_layout || arch.frontend_layout || arch.important_packages || arch.major_responsibilities);
	}

	function hasAnyMemory(): boolean {
		return Boolean(
			hasProjectOverview() ||
				hasArchitecture() ||
				fileIndex().length ||
				symbolContracts().length ||
				decisions().length ||
				tasks().length ||
				readRules().length ||
				memory?.project_notes?.length ||
				memory?.retrieval_policy
		);
	}

	function projectNotes() {
		return memory?.project_notes ?? [];
	}

	function splitFacts(value?: string): string[] {
		return (value ?? '')
			.split(';')
			.map((item) => item.trim())
			.filter(Boolean);
	}

	function startEdit(record: MemoryRecord) {
		editingMemoryId = record.id;
		editTitle = record.title;
		editSummary = record.summary;
		movingMemoryId = null;
		memoryActionError = '';
	}

	function cancelEdit() {
		editingMemoryId = null;
		memoryActionError = '';
	}

	async function saveEdit(record: MemoryRecord) {
		try {
			const updated = await updateMemory(record.id, { title: editTitle.trim(), summary: editSummary.trim() });
			replaceMemoryInLayer(record.layer, updated);
			editingMemoryId = null;
			memoryActionError = '';
		} catch (e: unknown) {
			memoryActionError = e instanceof Error ? e.message : 'Failed to update memory.';
		}
	}

	async function doArchive(record: MemoryRecord) {
		try {
			await archiveMemory(record.id);
			removeMemoryFromLayer(record.layer, record.id);
			memoryActionError = '';
		} catch (e: unknown) {
			memoryActionError = e instanceof Error ? e.message : 'Failed to archive memory.';
		}
	}

	async function doMove(record: MemoryRecord, targetLayer: MemoryLayer) {
		if (!targetLayer || targetLayer === record.layer) { movingMemoryId = null; return; }
		try {
			const updated = await moveMemory(record.id, targetLayer);
			removeMemoryFromLayer(record.layer, record.id);
			memoriesByLayer[targetLayer] = [updated, ...memoriesByLayer[targetLayer]];
			movingMemoryId = null;
			memoryActionError = '';
		} catch (e: unknown) {
			memoryActionError = e instanceof Error ? e.message : 'Failed to move memory.';
		}
	}

	function replaceMemoryInLayer(layer: MemoryLayer, updated: MemoryRecord) {
		memoriesByLayer[layer] = memoriesByLayer[layer].map((m) => (m.id === updated.id ? updated : m));
	}

	function removeMemoryFromLayer(layer: MemoryLayer, id: string) {
		memoriesByLayer[layer] = memoriesByLayer[layer].filter((m) => m.id !== id);
	}

	function otherLayers(current: MemoryLayer): MemoryLayer[] {
		return MEMORY_TABS.filter((l) => l !== current);
	}

	function compactPath(project: ProjectSummary): string {
		return project.paths?.[0] ?? 'No path recorded';
	}

	function compactHash(value?: string): string {
		return value ? value.slice(0, 12) : '';
	}

	function shortList(values?: string[], limit = 4): string {
		const clean = (values ?? []).filter(Boolean);
		if (!clean.length) return '';
		const visible = clean.slice(0, limit).join(', ');
		return clean.length > limit ? `${visible}, +${clean.length - limit} more` : visible;
	}
</script>

<div class="memory-page">
	<section class="memory-panel" aria-label="Project memories">
		<header class="memory-header">
			<div class="title-mark" aria-hidden="true">
				<BrainIcon size={30} weight="duotone" />
			</div>
			<div class="title-copy">
				{#if activeTab === 'project'}
					<p class="eyebrow">Project Memory</p>
					<h1>Projects</h1>
					<p>Structured project context built by the librarian, with canonical project-layer links where useful.</p>
				{:else}
					<p class="eyebrow">{layerTitle(activeTab)}</p>
					<h1>{layerHeading(activeTab)}</h1>
					<p>{activeLayerInfo()?.description ?? 'Canonical durable memory layer.'}</p>
				{/if}
			</div>
		</header>

		<div class="memory-tabs">
			{#each MEMORY_TABS as tab}
				<button class="tab-button" class:active={activeTab === tab} onclick={() => activeTab = tab}>
					{layerHeading(tab)}
				</button>
			{/each}
		</div>

		<div class="memory-content">
			{#if activeTab === 'project'}
				{#if loadingProjects}
					<div class="center-state">
						<div class="spinner"></div>
						<p>Loading project memories...</p>
					</div>
				{:else if projectError && projects.length === 0}
					<div class="center-state error-state">
						<h2>Could not load memories</h2>
						<p>{projectError}</p>
					</div>
				{:else if projects.length === 0}
					<div class="center-state empty-state">
						<div class="empty-icon">
							<BrainIcon size={42} weight="duotone" />
						</div>
						<h2>No project memories yet</h2>
						<p>Add or index a project to let BitBuddy build project memory.</p>
					</div>
				{:else}
				<div class="project-strip" aria-label="Registered projects">
					{#each projects as project}
						<button
							class="project-pill"
							class:active={project.id === selectedProjectId}
							onclick={() => selectProject(project.id)}
						>
							<span>{project.name}</span>
							<small>{project.id}</small>
						</button>
					{/each}
				</div>

				{#if projectError}
					<div class="inline-error">{projectError}</div>
				{/if}

				{#if loadingMemory}
					<div class="center-state compact">
						<div class="spinner"></div>
						<p>Loading selected project memory...</p>
					</div>
				{:else if memory && selectedProject()}
					<div class="memory-grid">
						<section class="overview-card wide-card">
							<div>
								<p class="section-kicker">Selected project</p>
								<h2>{selectedProject()?.name}</h2>
								<p class="path-line">{compactPath(selectedProject()!)}</p>
							</div>
							<div class="metric-row">
								<div class="metric">
									<span>Important files shown</span>
									<strong>{fileIndex().length}</strong>
								</div>
								{#if totalIndexedFiles()}
									<div class="metric">
										<span>Total indexed files</span>
										<strong>{totalIndexedFiles()}</strong>
									</div>
								{/if}
								<div class="metric">
									<span>Symbol contracts shown</span>
									<strong>{symbolContracts().length}</strong>
								</div>
							</div>
						</section>

						{#if !hasAnyMemory()}
							<section class="memory-section wide-card gentle-empty">
								<h2>No saved memory details yet</h2>
								<p>This project is registered, but the memory endpoint did not return project details yet.</p>
							</section>
						{/if}

						{#if hasProjectOverview()}
							<section class="memory-section wide-card">
								<div class="section-header">
									<p class="section-kicker">Project overview</p>
									{#if projectCard().updated_at}<span>{formatTimestamp(projectCard().updated_at)}</span>{/if}
								</div>
								<div class="detail-list">
									{#if projectCard().current_status}<p><strong>Status</strong>{projectCard().current_status}</p>{/if}
									{#if projectCard().stack}<p><strong>Stack</strong>{projectCard().stack}</p>{/if}
									{#if projectCard().purpose}<p><strong>Purpose</strong>{projectCard().purpose}</p>{/if}
									{#if projectCard().needs_read}<p><strong>Use safely</strong>{projectCard().needs_read}</p>{/if}
								</div>
								{#if facts().length}
									<div class="pill-list" aria-label="Verified facts">
										{#each facts() as fact}<span>{fact}</span>{/each}
									</div>
								{/if}
								{#if inferences().length}
									<div class="inference-box">
										<strong>Inferences</strong>
										<ul>{#each inferences() as item}<li>{item}</li>{/each}</ul>
									</div>
								{/if}
							</section>
						{/if}

						{#if hasArchitecture()}
							<section class="memory-section wide-card">
								<p class="section-kicker">Architecture summary</p>
								<div class="detail-list two-column">
									{#if architecture().backend_layout}<p><strong>Backend</strong>{architecture().backend_layout}</p>{/if}
									{#if architecture().frontend_layout}<p><strong>Frontend</strong>{architecture().frontend_layout}</p>{/if}
									{#if architecture().important_packages}<p><strong>Packages/config</strong>{architecture().important_packages}</p>{/if}
									{#if architecture().major_responsibilities}<p><strong>Responsibilities</strong>{architecture().major_responsibilities}</p>{/if}
								</div>
							</section>
						{/if}

						{#if readRules().length}
							<section class="memory-section">
								<p class="section-kicker">Read-before-editing rules</p>
								<div class="stack-list">
									{#each readRules().slice(0, 8) as rule}
										<article>
											<h3>{rule.area}</h3>
											{#if rule.reason}<p>{rule.reason}</p>{/if}
											{#if rule.files_to_read?.length}<small>{shortList(rule.files_to_read, 5)}</small>{/if}
										</article>
									{/each}
								</div>
							</section>
						{/if}

						{#if decisions().length || tasks().length}
							<section class="memory-section priority-memory">
								<p class="section-kicker">Decisions & task memory</p>
								<div class="stack-list">
									{#each decisions().slice(0, 6) as decision}
										<article>
											<h3>{decision.decision}</h3>
											{#if decision.constraint}<p>{decision.constraint}</p>{/if}
											{#if decision.source}<small>source: {decision.source}</small>{/if}
										</article>
									{/each}
									{#each tasks().slice(0, 4) as task}
										<article>
											<h3>{task.task}</h3>
											{#if task.notes}<p>{task.notes}</p>{/if}
											{#if task.status}<small>status: {task.status}</small>{/if}
										</article>
									{/each}
								</div>
							</section>
						{/if}

						{#if projectNotes().length}
							<section class="memory-section priority-memory">
								<div class="section-header">
									<p class="section-kicker">Canonical project notes</p>
									<span>{projectNotes().length} linked</span>
								</div>
								<div class="stack-list">
									{#each projectNotes().slice(0, 8) as note}
										<article>
											<h3>{note.category}</h3>
											{#if note.content}<p>{note.content}</p>{/if}
											<small>{note.layer ?? 'project'} / {note.kind ?? note.category}{note.memory_id ? ` · ${note.memory_id.slice(0, 8)}` : ''}</small>
											{#if note.tags?.length}<div class="episode-tags compact-tags">{#each note.tags as tag}<span class="tag">{tag}</span>{/each}</div>{/if}
										</article>
									{/each}
								</div>
							</section>
						{/if}

						{#if fileIndex().length}
							<section class="memory-section wide-card">
								<div class="section-header">
									<p class="section-kicker">Important files</p>
									<span>{fileIndex().length} shown</span>
								</div>
								<div class="file-grid">
									{#each fileIndex().slice(0, 18) as file}
										<article class="file-card" class:stale={file.stale}>
											<h3>{file.path}</h3>
											{#if file.role}<p>{file.role}</p>{/if}
											{#if file.key_responsibilities?.length}<small>{shortList(file.key_responsibilities, 3)}</small>{/if}
											<div class="file-meta">
												{#if file.stale}<span class="warn">stale</span>{/if}
												{#if file.content_hash}<span>hash {compactHash(file.content_hash)}</span>{/if}
											</div>
										</article>
									{/each}
								</div>
							</section>
						{/if}

						{#if symbolContracts().length}
							<section class="memory-section wide-card">
								<div class="section-header">
									<p class="section-kicker">Symbol contracts</p>
									<span>{symbolContracts().length} shown</span>
								</div>
								<div class="symbol-list">
									{#each symbolContracts().slice(0, 24) as symbol}
										<article>
											<h3>{symbol.name}</h3>
											<small>{symbol.kind} · {symbol.file_path}</small>
											{#if symbol.contract}<p>{symbol.contract}</p>{/if}
										</article>
									{/each}
								</div>
							</section>
						{/if}

						{#if memory?.retrieval_policy}
							<section class="memory-section wide-card policy-card">
								<p class="section-kicker">Retrieval policy</p>
								<p>{memory.retrieval_policy}</p>
							</section>
						{/if}
					</div>
					{/if}
				{/if}
			{:else}
				<section class="layer-guide">
					<p class="section-kicker">Routing rule</p>
					<p>{activeLayerInfo()?.routing_rule ?? 'Use this layer for the matching durable memory category.'}</p>
					{#if activeTab === 'relationship'}
						<p class="preference-note">Preferences live here as tags, kinds, or subtypes. Preference is not its own top-level layer.</p>
					{/if}
				</section>

				{#if loadingLayerMemories}
					<div class="center-state">
						<div class="spinner"></div>
						<p>Loading {activeTab} memories...</p>
					</div>
				{:else if layerError}
					<div class="center-state error-state">
						<h2>Could not load memories</h2>
						<p>{layerError}</p>
					</div>
				{:else if activeLayerMemories().length === 0}
					<div class="center-state empty-state">
						<div class="empty-icon">
							<BrainIcon size={42} weight="duotone" />
						</div>
						<h2>No {activeTab} memories yet</h2>
						<p>Canonical {activeTab} memories will appear here once created.</p>
					</div>
				{:else}
					{#if memoryActionError}
						<div class="memory-action-error">{memoryActionError}</div>
					{/if}
					<div class="episode-list">
						{#each activeLayerMemories() as memoryRecord}
							<article class="episode-card">
								{#if editingMemoryId === memoryRecord.id}
									<div class="memory-edit-form">
										<input class="edit-input" type="text" bind:value={editTitle} placeholder="Title" />
										<textarea class="edit-textarea" bind:value={editSummary} placeholder="Summary" rows={4}></textarea>
										<div class="edit-actions">
											<button class="edit-save" type="button" onclick={() => saveEdit(memoryRecord)}>Save</button>
											<button class="edit-cancel" type="button" onclick={cancelEdit}>Cancel</button>
										</div>
									</div>
								{:else}
									<div class="episode-header">
										<div class="episode-title-row">
											<h3>{memoryRecord.title}</h3>
											{#if memoryRecord.importance >= 4}
												<span class="importance-badge high">{memoryRecord.importance}</span>
											{:else}
												<span class="importance-badge">{memoryRecord.importance}</span>
											{/if}
										</div>
										<div class="episode-meta">
											<span class="episode-type">{memoryRecord.kind}</span>
											<span>{formatDate(memoryRecord.created_at)}</span>
											{#if memoryRecord.source}<span>{memoryRecord.source}</span>{/if}
											{#if memoryRecord.project_id}
												<span class="project-badge">{memoryRecord.project_id.slice(0, 8)}</span>
											{/if}
										</div>
									</div>
									<p class="episode-summary">{memoryRecord.summary}</p>
									<div class="memory-id">id: {memoryRecord.id}</div>
									{#if memoryRecord.tags.length}
										<div class="episode-tags">
											{#each memoryRecord.tags as tag}
												<span class="tag">{tag}</span>
											{/each}
										</div>
									{/if}
									<div class="memory-actions">
										<button class="mem-action-btn" type="button" onclick={() => startEdit(memoryRecord)}>Edit</button>
										<button class="mem-action-btn" type="button" onclick={() => movingMemoryId = movingMemoryId === memoryRecord.id ? null : memoryRecord.id}>Move</button>
										<button class="mem-action-btn mem-action-danger" type="button" onclick={() => doArchive(memoryRecord)}>Archive</button>
									</div>
									{#if movingMemoryId === memoryRecord.id}
										<div class="move-layer-row">
											<span>Move to:</span>
											{#each otherLayers(memoryRecord.layer) as layer}
												<button class="layer-chip" type="button" onclick={() => doMove(memoryRecord, layer)}>{layer}</button>
											{/each}
										</div>
									{/if}
								{/if}
							</article>
						{/each}
					</div>
				{/if}
			{/if}
		</div>
	</section>
</div>

<style>
	.memory-page {
		width: 100%;
		max-width: 90rem;
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

	.memory-panel {
		--page-accent: #818cf8;
		--page-soft: rgba(129, 140, 248, 0.12);
		--page-border: rgba(129, 140, 248, 0.25);
		--page-glow: rgba(129, 140, 248, 0.14);

		width: 100%;
		height: 100%;
		max-height: calc(100vh - 3rem);
		display: flex;
		min-height: 0;
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

	.memory-header {
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

	.eyebrow,
	.section-kicker {
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

	.title-copy p:last-child,
	.path-line,
	.center-state p,
	.memory-section p,
	.stack-list p,
	.file-card p,
	.symbol-list p {
		color: var(--text-soft);
	}

	.memory-tabs {
		flex: 0 0 auto;
		display: flex;
		justify-content: center;
		gap: 0.25rem;
		padding: 0 1.5rem;
		border-bottom: 1px solid var(--border);
		background: var(--header-bg);
		overflow-x: auto;
		scrollbar-color: var(--scrollbar-thumb) transparent;
	}

	.tab-button {
		flex: 0 0 auto;
		padding: 0.75rem 1rem;
		border: none;
		border-bottom: 2px solid transparent;
		background: none;
		color: var(--text-muted);
		font-size: 0.85rem;
		font-weight: 700;
		letter-spacing: 0.02em;
		white-space: nowrap;
		cursor: pointer;
		transition: color 120ms ease, border-color 120ms ease;
	}

	.tab-button:hover {
		color: var(--text);
	}

	.tab-button.active {
		color: var(--page-accent);
		border-bottom-color: var(--page-accent);
	}

	.memory-content {
		flex: 1 1 auto;
		min-height: 0;
		overflow-y: auto;
		overscroll-behavior: contain;
		padding: 1.25rem;
		scrollbar-color: var(--scrollbar-thumb) transparent;
	}

	.episode-list {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(30rem, 100%), 1fr));
		gap: 0.85rem;
	}

	.layer-guide {
		margin-bottom: 1rem;
		padding: 1rem;
		border: 1px solid var(--page-border);
		border-radius: 1.1rem;
		background: var(--page-soft);
		display: grid;
		gap: 0.35rem;
	}

	.layer-guide p:not(.section-kicker) {
		color: var(--text-soft);
		line-height: 1.5;
		overflow-wrap: break-word;
	}

	.preference-note {
		padding-top: 0.35rem;
		color: var(--success) !important;
		font-weight: 700;
	}

	.episode-card {
		padding: 1rem;
		max-height: 24rem;
		overflow-y: auto;
		border: 1px solid var(--border);
		border-radius: 1rem;
		background: var(--surface-card);
		box-shadow: var(--shadow-panel);
	}

	.episode-header {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
		margin-bottom: 0.6rem;
	}

	.episode-title-row {
		display: flex;
		align-items: center;
		gap: 0.6rem;
	}

	.episode-title-row h3 {
		font-size: 1rem;
		font-weight: 800;
		letter-spacing: -0.01em;
		margin: 0;
		min-width: 0;
		overflow-wrap: break-word;
	}

	.episode-meta {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		font-size: 0.75rem;
		color: var(--text-muted);
	}

	.episode-type {
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-weight: 700;
	}

	.importance-badge {
		padding: 0.15rem 0.45rem;
		border-radius: 0.35rem;
		background: var(--page-soft);
		color: var(--page-accent);
		font-size: 0.72rem;
		font-weight: 800;
	}

	.importance-badge.high {
		background: rgba(245, 158, 11, 0.15);
		color: var(--warning);
	}

	.project-badge {
		padding: 0.1rem 0.4rem;
		border-radius: 0.3rem;
		background: rgba(110, 231, 183, 0.1);
		color: var(--success);
		font-size: 0.7rem;
		font-family: monospace;
	}

	.episode-summary {
		color: var(--text-soft);
		font-size: 0.9rem;
		line-height: 1.55;
		margin: 0;
		overflow-wrap: break-word;
	}

	.memory-id {
		margin-top: 0.55rem;
		color: var(--text-muted);
		font-size: 0.72rem;
		font-family: monospace;
		overflow-wrap: break-word;
	}

	.episode-tags {
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
		margin-top: 0.6rem;
	}

	.compact-tags {
		margin-top: 0.45rem;
	}

	.episode-tags .tag {
		padding: 0.2rem 0.5rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: var(--surface-card);
		color: var(--text-muted);
		font-size: 0.75rem;
		word-break: break-word;
	}

	.memory-actions {
		display: flex;
		gap: 0.4rem;
		margin-top: 0.65rem;
	}

	.mem-action-btn {
		padding: 0.22rem 0.6rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: none;
		color: var(--text-soft);
		font-size: 0.72rem;
		font-weight: 800;
		letter-spacing: 0.03em;
		cursor: pointer;
		transition: color 120ms ease, border-color 120ms ease, background 120ms ease;
	}

	.mem-action-btn:hover {
		color: var(--text);
		border-color: var(--border-strong);
		background: var(--panel-raised);
	}

	.mem-action-danger:hover {
		color: var(--danger);
		border-color: rgba(255, 107, 122, 0.38);
	}

	.move-layer-row {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		flex-wrap: wrap;
		margin-top: 0.5rem;
		font-size: 0.78rem;
		color: var(--text-soft);
	}

	.layer-chip {
		padding: 0.2rem 0.55rem;
		border: 1px solid var(--page-border);
		border-radius: 999px;
		background: var(--page-soft);
		color: var(--page-accent);
		font-size: 0.72rem;
		font-weight: 800;
		cursor: pointer;
		transition: background 120ms ease;
	}

	.layer-chip:hover { background: rgba(129, 140, 248, 0.2); }

	.memory-edit-form {
		display: grid;
		gap: 0.6rem;
	}

	.edit-input,
	.edit-textarea {
		width: 100%;
		padding: 0.5rem 0.7rem;
		border: 1px solid var(--border);
		border-radius: 0.7rem;
		background: var(--surface-inset);
		color: var(--text);
		font-size: 0.9rem;
		font-family: inherit;
		resize: vertical;
	}

	.edit-input:focus,
	.edit-textarea:focus {
		outline: none;
		border-color: var(--page-accent);
	}

	.edit-actions {
		display: flex;
		gap: 0.5rem;
	}

	.edit-save {
		padding: 0.35rem 0.9rem;
		border: 1px solid var(--page-border);
		border-radius: 999px;
		background: var(--page-soft);
		color: var(--page-accent);
		font-size: 0.78rem;
		font-weight: 800;
		cursor: pointer;
	}

	.edit-save:hover { background: rgba(129, 140, 248, 0.22); }

	.edit-cancel {
		padding: 0.35rem 0.9rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: none;
		color: var(--text-soft);
		font-size: 0.78rem;
		font-weight: 800;
		cursor: pointer;
	}

	.edit-cancel:hover { color: var(--text); border-color: var(--border-strong); }

	.memory-action-error {
		padding: 0.6rem 0.85rem;
		margin-bottom: 0.75rem;
		border: 1px solid rgba(255, 107, 122, 0.32);
		border-radius: 0.85rem;
		background: rgba(255, 107, 122, 0.07);
		color: var(--danger);
		font-size: 0.85rem;
	}

	.project-strip {
		display: flex;
		gap: 0.7rem;
		overflow-x: auto;
		padding-bottom: 0.9rem;
		margin-bottom: 1rem;
		scrollbar-color: var(--scrollbar-thumb) transparent;
	}

	.project-pill {
		min-width: 13rem;
		max-width: 18rem;
		padding: 0.85rem 1rem;
		display: grid;
		gap: 0.15rem;
		border: 1px solid var(--border);
		border-radius: 1rem;
		background: var(--surface-card);
		text-align: left;
	}

	.project-pill:hover,
	.project-pill.active {
		border-color: var(--page-accent);
		background: var(--page-soft);
	}

	.project-pill span {
		font-weight: 800;
		overflow-wrap: break-word;
	}

	.project-pill small,
	.section-header span,
	.stack-list small,
	.file-card small,
	.symbol-list small,
	.file-meta span {
		color: var(--text-muted);
		font-size: 0.75rem;
		overflow-wrap: break-word;
	}

	.memory-grid {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.wide-card {
		width: 100%;
	}

	.overview-card,
	.memory-section {
		border: 1px solid var(--border);
		border-radius: 1.2rem;
		background: var(--surface-card);
		box-shadow: var(--shadow-panel);
	}

	.overview-card {
		padding: 1.2rem;
		display: grid;
		grid-template-columns: minmax(0, 1fr) auto;
		gap: 1.25rem;
		align-items: end;
	}

	.overview-card > div {
		min-width: 0;
		overflow-wrap: break-word;
	}

	.overview-card h2,
	.center-state h2,
	.gentle-empty h2 {
		font-size: 1.35rem;
		font-weight: 900;
		letter-spacing: -0.02em;
	}

	.metric-row {
		display: flex;
		gap: 0.7rem;
		flex-wrap: wrap;
		justify-content: flex-end;
	}

	.metric {
		min-width: 8.5rem;
		padding: 0.8rem;
		border: 1px solid var(--border);
		border-radius: 0.9rem;
		background: var(--surface-inset);
		overflow-wrap: break-word;
	}

	.metric span {
		display: block;
		color: var(--text-soft);
		font-size: 0.72rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	.metric strong {
		font-size: 1.5rem;
	}

	.memory-section {
		padding: 1rem;
		display: grid;
		gap: 0.85rem;
		max-height: 30rem;
		overflow-y: auto;
	}

	.section-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
	}

	.detail-list {
		display: grid;
		gap: 0.65rem;
	}

	.detail-list.two-column {
		grid-template-columns: repeat(auto-fit, minmax(min(20rem, 100%), 1fr));
	}

	.detail-list p {
		display: grid;
		gap: 0.18rem;
		overflow-wrap: break-word;
	}

	.detail-list strong {
		color: var(--text);
		font-size: 0.82rem;
	}

	.pill-list {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
	}

	.pill-list span {
		padding: 0.35rem 0.55rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: var(--surface-card);
		color: var(--text-muted);
		font-size: 0.78rem;
		overflow-wrap: break-word;
	}

	.inference-box {
		padding: 0.85rem;
		border: 1px solid rgba(245, 158, 11, 0.22);
		border-radius: 1rem;
		background: rgba(245, 158, 11, 0.08);
	}

	.inference-box strong {
		color: var(--warning);
		font-size: 0.82rem;
	}

	.inference-box ul {
		margin-top: 0.45rem;
		display: grid;
		gap: 0.25rem;
		color: var(--text-muted);
		font-size: 0.9rem;
	}

	.inference-box li {
		overflow-wrap: break-word;
	}

	.stack-list,
	.symbol-list {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(20rem, 100%), 1fr));
		align-items: stretch;
		gap: 0.7rem;
	}

	.priority-memory {
		border-color: rgba(110, 231, 183, 0.2);
		background: rgba(110, 231, 183, 0.035);
	}

	.stack-list article,
	.symbol-list article,
	.file-card {
		padding: 0.85rem;
		border: 1px solid var(--border);
		border-radius: 0.95rem;
		background: var(--surface-inset);
		overflow-wrap: break-word;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}

	.stack-list article > :last-child,
	.symbol-list article > :last-child,
	.file-card > :last-child {
		margin-top: auto;
	}

	.stack-list h3,
	.file-card h3,
	.symbol-list h3 {
		font-size: 0.95rem;
		font-weight: 800;
		word-break: break-word;
	}

	.file-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(20rem, 100%), 1fr));
		gap: 0.75rem;
	}

	.file-card.stale {
		border-color: rgba(245, 158, 11, 0.32);
	}

	.file-meta {
		display: flex;
		gap: 0.6rem;
		flex-wrap: wrap;
	}

	.file-meta .warn {
		color: var(--warning);
	}

	.policy-card {
		border-color: rgba(110, 231, 183, 0.18);
		background: rgba(110, 231, 183, 0.045);
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

	.center-state.compact {
		min-height: 14rem;
	}

	.empty-icon {
		width: 5rem;
		height: 5rem;
		display: grid;
		place-items: center;
		border-radius: 1.5rem;
		background: var(--page-soft);
		color: var(--page-accent);
	}

	.spinner {
		width: 2rem;
		height: 2rem;
		border: 2px solid var(--border);
		border-top-color: var(--page-accent);
		border-radius: 50%;
		animation: spin 1s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	.inline-error {
		margin-bottom: 1rem;
		padding: 0.85rem 1rem;
		border: 1px solid rgba(255, 107, 122, 0.3);
		border-radius: 1rem;
		background: rgba(255, 107, 122, 0.08);
		color: var(--danger);
	}

	.gentle-empty {
		text-align: center;
		padding: 2rem;
	}

	@media (max-width: 900px) {
		.memory-page,
		.memory-panel {
			height: auto;
			max-height: none;
		}

		.memory-grid,
		.detail-list.two-column,
		.overview-card {
			grid-template-columns: 1fr;
		}

		.metric-row {
			justify-content: stretch;
		}

		.metric {
			flex: 1 1 10rem;
		}
	}

	@media (max-width: 640px) {
		.memory-page {
			padding: 0;
		}

		.memory-header {
			align-items: flex-start;
		}

		.memory-tabs {
			justify-content: flex-start;
			padding: 0 0.75rem;
			scroll-padding-inline: 0.75rem;
		}

		.tab-button {
			padding: 0.75rem 0.85rem;
		}

		.title-mark {
			width: 3rem;
			height: 3rem;
		}

		.project-strip {
			flex-wrap: wrap;
			overflow-x: visible;
		}

		.project-pill {
			min-width: min(100%, 13rem);
			flex: 1 1 13rem;
		}
	}
</style>
