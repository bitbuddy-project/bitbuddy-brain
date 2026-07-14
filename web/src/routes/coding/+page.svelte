<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import ArrowLeftIcon from 'phosphor-svelte/lib/ArrowLeftIcon';
	import CodeIcon from 'phosphor-svelte/lib/CodeIcon';
	import PlusIcon from 'phosphor-svelte/lib/PlusIcon';
	import FloppyDiskIcon from 'phosphor-svelte/lib/FloppyDiskIcon';
	import TrashIcon from 'phosphor-svelte/lib/TrashIcon';
	import ArrowUpIcon from 'phosphor-svelte/lib/ArrowUpIcon';
	import ArrowDownIcon from 'phosphor-svelte/lib/ArrowDownIcon';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import ChatComposer from '$lib/components/chat/ChatComposer.svelte';
	import SelectMenu from '$lib/components/ui/SelectMenu.svelte';
	import type { SelectOption } from '$lib/components/ui/SelectMenu.svelte';
	import type { PendingChatAttachment } from '$lib/stores/chat.svelte';
	import {
		deleteCodingWorkflow,
		getProjectValidationRecipes,
		getProviderModels,
		saveCodingWorkflow,
		type CodingRunStep,
		type ChatAttachment,
		type CodingStage,
		type CodingStageKind,
		type CodingWorkflow,
		type ProviderEntry,
		type QuestionRequest,
		type ValidationRecipe
	} from '$lib/api/bitbuddy';
	import { buildProviderModelOptions, reasoningEffortOptionsForProvider } from '$lib/providerModels';
	import {
		beginCodingRun,
		codingSession,
		initializeCoding,
		replaceWorkflow,
		resolveCodingGate,
		resolveCodingPermission,
		resolveCodingQuestion,
		stopCodingRun
	} from '$lib/stores/coding.svelte';

	let selectedWorkflowId = $state('');
	let draft = $state<CodingWorkflow | null>(null);
	let selectedStageId = $state('');
	let projectId = $state('');
	let codingDraft = $state('');
	let codingAttachments = $state<PendingChatAttachment[]>([]);
	let recipes = $state<ValidationRecipe[]>([]);
	let liveModels = $state<Record<string, string[]>>({});
	let saving = $state(false);
	let starting = $state(false);
	let localError = $state('');
	let revisionFeedback = $state('');
	let questionAnswers = $state<Record<string, string>>({});
	let questionCustom = $state<Record<string, string>>({});

	let selectedStage = $derived(draft?.stages.find((stage) => stage.id === selectedStageId) ?? null);
	let selectedProvider = $derived(selectedStage ? providerFor(selectedStage.provider_key) : undefined);
	let activeBusy = $derived(Boolean(codingSession.activeRun && !['completed', 'needs_attention', 'cancelled', 'failed'].includes(codingSession.activeRun.status)));
	let workflowRuns = $derived(codingSession.recentRuns.filter((run) => run.metadata?.source === 'workflow'));
	let visibleSteps = $derived((codingSession.activeRun?.steps ?? []).filter((step) => ['stage', 'tool'].includes(step.kind)));
	let projectOptions = $derived<SelectOption[]>(codingSession.projects.map((project) => ({ value: project.id, label: project.name })));
	let providerOptions = $derived<SelectOption[]>(codingSession.providers.map((provider) => ({ value: providerKey(provider), label: providerLabel(provider), description: provider.model })));
	let runAttachments = $derived((codingSession.activeRun?.metadata?.attachments ?? []) as ChatAttachment[]);

	onMount(async () => {
		await initializeCoding();
		if (!projectId && codingSession.projects[0]) projectId = codingSession.projects[0].id;
		if (!selectedWorkflowId) selectWorkflow(codingSession.workflows.find((workflow) => workflow.is_default) ?? codingSession.workflows[0]);
	});

	$effect(() => {
		if (projectId) void loadRecipes(projectId);
	});

	function cloneWorkflow(workflow: CodingWorkflow): CodingWorkflow {
		return JSON.parse(JSON.stringify(workflow));
	}

	function selectWorkflow(workflow?: CodingWorkflow) {
		if (!workflow) return;
		selectedWorkflowId = workflow.id;
		draft = cloneWorkflow(workflow);
		selectedStageId = draft.stages[0]?.id ?? '';
		for (const stage of draft.stages) void loadStageModels(stage);
	}

	function providerKey(provider: ProviderEntry) {
		return provider.key || provider.type;
	}

	function providerFor(key: string) {
		return codingSession.providers.find((provider) => providerKey(provider) === key);
	}

	function providerLabel(provider?: ProviderEntry) {
		if (!provider) return 'Missing provider';
		const labels: Record<string, string> = { anthropic: 'Anthropic', openai: 'OpenAI API', codex: 'Codex', 'z.ai': 'Z.ai API', 'z.ai-coding': 'Z.ai Coding', ollama: 'Ollama', 'llama.cpp': 'llama.cpp' };
		return labels[provider.type] ?? provider.type;
	}

	async function loadStageModels(stage: CodingStage) {
		const provider = providerFor(stage.provider_key);
		if (!provider || liveModels[stage.provider_key]) return;
		try {
			liveModels[stage.provider_key] = await getProviderModels(provider);
		} catch {
			liveModels[stage.provider_key] = [];
		}
	}

	function modelOptions(stage: CodingStage) {
		const provider = providerFor(stage.provider_key);
		if (!provider) return [{ value: stage.model, label: stage.model }];
		return buildProviderModelOptions(provider.type, liveModels[stage.provider_key] ?? [], stage.model);
	}

	function changeProvider(stage: CodingStage, key: string) {
		const provider = providerFor(key);
		if (!provider) return;
		stage.provider_key = key;
		stage.model = provider.model;
		stage.reasoning_effort = provider.reasoning_effort || 'medium';
		void loadStageModels(stage);
	}

	function addStage(kind: Exclude<CodingStageKind, 'build'>) {
		if (!draft) return;
		const provider = codingSession.providers[0];
		const stage: CodingStage = {
			id: crypto.randomUUID(), kind, name: kind[0].toUpperCase() + kind.slice(1),
			provider_key: provider ? providerKey(provider) : '', model: provider?.model ?? '', reasoning_effort: provider?.reasoning_effort ?? 'medium',
			instructions: defaultInstructions(kind), approval_gate: false, validation_recipes: []
		};
		const buildIndex = draft.stages.findIndex((item) => item.kind === 'build');
		if (kind === 'plan') draft.stages.splice(buildIndex, 0, stage); else draft.stages.push(stage);
		selectedStageId = stage.id;
		void loadStageModels(stage);
	}

	function defaultInstructions(kind: CodingStageKind) {
		if (kind === 'plan') return 'Inspect the project and produce an implementation-ready plan.';
		if (kind === 'review') return 'Review independently for correctness, regressions, and missed requirements.';
		if (kind === 'test') return 'Run the selected project checks and assess whether the implementation is ready.';
		return 'Implement the approved plans and verify the changes.';
	}

	function removeStage(stage: CodingStage) {
		if (!draft || stage.kind === 'build') return;
		draft.stages = draft.stages.filter((item) => item.id !== stage.id);
		selectedStageId = draft.stages[0]?.id ?? '';
	}

	function moveStage(stage: CodingStage, direction: -1 | 1) {
		if (!draft || stage.kind === 'build') return;
		const index = draft.stages.findIndex((item) => item.id === stage.id);
		const target = index + direction;
		if (target < 0 || target >= draft.stages.length) return;
		if (draft.stages[target].kind === 'build') return;
		[draft.stages[index], draft.stages[target]] = [draft.stages[target], draft.stages[index]];
	}

	function canMove(stage: CodingStage, direction: -1 | 1) {
		if (!draft || stage.kind === 'build') return false;
		const index = draft.stages.findIndex((item) => item.id === stage.id);
		const target = index + direction;
		return target >= 0 && target < draft.stages.length && draft.stages[target].kind !== 'build';
	}

	async function saveFlow() {
		if (!draft || saving) return;
		saving = true; localError = '';
		try {
			const workflow = await saveCodingWorkflow(draft);
			replaceWorkflow(workflow);
			selectedWorkflowId = workflow.id;
			draft = cloneWorkflow(workflow);
		} catch (caught) { localError = caught instanceof Error ? caught.message : 'Could not save flow.'; }
		finally { saving = false; }
	}

	function duplicateFlow() {
		if (!draft) return;
		draft = { ...cloneWorkflow(draft), id: '', name: `${draft.name} copy`, is_default: false, stages: draft.stages.map((stage) => ({ ...stage, id: crypto.randomUUID() })) };
		selectedWorkflowId = '';
		selectedStageId = draft.stages[0]?.id ?? '';
	}

	async function removeFlow() {
		if (!draft?.id) return;
		try {
			await deleteCodingWorkflow(draft.id);
			codingSession.workflows = codingSession.workflows.filter((workflow) => workflow.id !== draft?.id);
			selectWorkflow(codingSession.workflows[0]);
		} catch (caught) { localError = caught instanceof Error ? caught.message : 'Could not delete flow.'; }
	}

	async function startRun(message: string, attachments: ChatAttachment[] = []) {
		if (!draft || starting) return;
		if (!draft.id) await saveFlow();
		if (!draft.id && selectedWorkflowId) draft.id = selectedWorkflowId;
		if (!projectId || !draft.id || (!message.trim() && attachments.length === 0)) { localError = 'Choose a project, save the flow, and describe the coding task.'; return; }
		starting = true; localError = '';
		try { await beginCodingRun(projectId, draft.id, message.trim() || 'Use the attached files as the coding task.', attachments); }
		catch (caught) { localError = caught instanceof Error ? caught.message : 'Could not start coding run.'; }
		finally { starting = false; }
	}

	async function loadRecipes(id: string) {
		try { recipes = (await getProjectValidationRecipes(id, { includeSuggestions: true })).filter((recipe) => recipe.source !== 'suggested'); }
		catch { recipes = []; }
	}

	function toggleRecipe(stage: CodingStage, name: string) {
		stage.validation_recipes = stage.validation_recipes.includes(name) ? stage.validation_recipes.filter((item) => item !== name) : [...stage.validation_recipes, name];
	}

	function stepOutput(step: CodingRunStep) {
		const diff = step.metadata?.diff as { files?: Array<{ path?: string; unified?: string }> } | undefined;
		if (diff?.files?.length) return diff.files.map((file) => `${file.path ?? 'file'}\n${file.unified ?? ''}`).join('\n\n');
		return typeof step.metadata?.output === 'string' ? step.metadata.output : step.summary;
	}

	function selectQuestionChoice(request: QuestionRequest, questionId: string, label: string) {
		questionAnswers[questionId] = label;
		questionCustom[questionId] = '';
	}

	async function submitQuestion(request: QuestionRequest) {
		if (request.questions.some((item) => !questionAnswers[item.id]?.trim())) { localError = 'Answer each question before continuing.'; return; }
		await resolveCodingQuestion(request.id, questionAnswers);
		questionAnswers = {}; questionCustom = {};
	}
</script>

<section class="coding-wrap" aria-label="BitBuddy Coding workspace">
	<PageHeader icon={CodeIcon} variant="chat" eyebrow="Coding workspace" title={activeBusy ? (codingSession.activeStageName || 'Workflow running') : 'Coding'}>
		{#snippet action()}
			{#if activeBusy}<span class="run-status">{codingSession.activeRun?.status.replaceAll('_', ' ')}</span>{/if}
			<button class="header-button" type="button" onclick={() => goto('/')}><ArrowLeftIcon size={17} weight="bold" /> Chat</button>
		{/snippet}
	</PageHeader>

	<div class="coding-grid">
		<aside class="flow-sidebar">
			<div class="section-heading"><span>Saved flows</span><button type="button" onclick={duplicateFlow} title="Duplicate selected flow"><PlusIcon size={15} /></button></div>
			<div class="flow-list">
				{#each codingSession.workflows as workflow}
					<button class:active={selectedWorkflowId === workflow.id} type="button" onclick={() => selectWorkflow(workflow)}>
						<strong>{workflow.name}</strong><small>{workflow.stages.map((stage) => stage.name).join(' → ')}</small>
					</button>
				{/each}
			</div>
			<div class="section-heading recent"><span>Recent runs</span></div>
			<div class="run-list">
				{#each workflowRuns.slice(0, 8) as run}
					<button type="button" onclick={() => (codingSession.activeRun = run)}><strong>{run.user_request}</strong><small class:bad={['failed', 'needs_attention'].includes(run.status)}>{run.status.replaceAll('_', ' ')}</small></button>
				{/each}
			</div>
		</aside>

		<main class="workspace">
			{#if localError || codingSession.error}<p class="error-banner">{localError || codingSession.error}</p>{/if}

			<div class="config-row">
				<section class="flow-canvas">
					<div class="canvas-header">
						<div class="flow-title"><span>Flow</span>{#if draft}<input bind:value={draft.name} aria-label="Flow name" disabled={activeBusy} />{:else}<strong>Choose a saved flow</strong>{/if}</div>
						<div class="canvas-actions">
							<button type="button" onclick={() => addStage('plan')} disabled={activeBusy}><PlusIcon size={14} /> Plan</button>
							<button type="button" onclick={() => addStage('review')} disabled={activeBusy}><PlusIcon size={14} /> Review</button>
							<button type="button" onclick={() => addStage('test')} disabled={activeBusy}><PlusIcon size={14} /> Test</button>
							<button class="save" type="button" onclick={saveFlow} disabled={saving || activeBusy}><FloppyDiskIcon size={15} /> {saving ? 'Saving…' : 'Save'}</button>
						</div>
					</div>

					<div class="stage-strip">
						{#each draft?.stages ?? [] as stage, index (stage.id)}
							<div class="stage-link" class:current={codingSession.activeStageId === stage.id}>
								<button class="stage-card" class:selected={selectedStageId === stage.id} type="button" onclick={() => (selectedStageId = stage.id)}>
									<span class="stage-number">{index + 1}</span><strong>{stage.name}</strong>
									<small>{providerLabel(providerFor(stage.provider_key))} · {stage.model}</small>
									{#if stage.approval_gate}<em>approval</em>{/if}
								</button>
								<div class="stage-order">
									<button type="button" onclick={() => moveStage(stage, -1)} disabled={!canMove(stage, -1) || activeBusy} aria-label="Move stage up"><ArrowUpIcon size={13} /></button>
									<button type="button" onclick={() => moveStage(stage, 1)} disabled={!canMove(stage, 1) || activeBusy} aria-label="Move stage down"><ArrowDownIcon size={13} /></button>
								</div>
							</div>
						{/each}
					</div>
				</section>

				<aside class="stage-editor">
					{#if selectedStage}
						<div class="editor-header"><div><span>Stage settings</span><strong>{selectedStage.name}</strong></div>{#if selectedStage.kind !== 'build'}<button type="button" onclick={() => removeStage(selectedStage)} disabled={activeBusy} title="Remove stage"><TrashIcon size={16} /></button>{/if}</div>
						<div class="editor-grid">
							<label><span>Name</span><input bind:value={selectedStage.name} disabled={activeBusy} /></label>
							<label><span>Provider</span><SelectMenu value={selectedStage.provider_key} options={providerOptions} ariaLabel="Stage provider" disabled={activeBusy} onChange={(value) => changeProvider(selectedStage, value)} /></label>
							<label><span>Model</span><SelectMenu value={selectedStage.model} options={modelOptions(selectedStage)} ariaLabel="Stage model" disabled={activeBusy} onChange={(value) => (selectedStage.model = value)} /></label>
							<label><span>Reasoning</span><SelectMenu value={selectedStage.reasoning_effort} options={reasoningEffortOptionsForProvider(selectedProvider?.type ?? '', selectedStage.model)} ariaLabel="Stage reasoning" disabled={activeBusy} onChange={(value) => (selectedStage.reasoning_effort = value)} /></label>
							<label class="instructions"><span>Instructions</span><textarea bind:value={selectedStage.instructions} rows="3" disabled={activeBusy}></textarea></label>
						</div>
						<label class="check"><input type="checkbox" bind:checked={selectedStage.approval_gate} disabled={activeBusy} /><span>Pause for approval after this stage</span></label>
						{#if selectedStage.kind === 'test'}
							<div class="recipes"><span>Validation recipes</span>{#if recipes.length}{#each recipes as recipe}<label class="check"><input type="checkbox" checked={selectedStage.validation_recipes.includes(recipe.name)} onchange={() => toggleRecipe(selectedStage, recipe.name)} disabled={activeBusy} /><span><strong>{recipe.name}</strong><small>{recipe.command}</small></span></label>{/each}{:else}<small>No validation recipes found for this project.</small>{/if}</div>
						{/if}
					{:else}<div class="empty-editor">Select a stage to configure it.</div>{/if}
					{#if draft?.id && !draft.is_default}<button class="delete-flow" type="button" onclick={removeFlow} disabled={activeBusy}><TrashIcon size={15} /> Delete flow</button>{/if}
				</aside>
			</div>

			<section class="coding-conversation">
				<div class="conversation-toolbar">
					<div class="project-picker"><span>Project</span><SelectMenu value={projectId} options={projectOptions} placeholder="Choose project" ariaLabel="Coding project" disabled={activeBusy} compact onChange={(value) => (projectId = value)} /></div>
					<div class="output-state"><span>Run</span><strong>{codingSession.activeRun ? codingSession.activeRun.status.replaceAll('_', ' ') : 'Ready'}</strong></div>
				</div>
				<div class="conversation-scroll">
					{#if codingSession.activeRun}
						<div class="user-turn">
							<div class="user-bubble"><p>{codingSession.activeRun.user_request}</p>{#if runAttachments.length}<div class="run-attachments">{#each runAttachments as attachment}<span>{attachment.name}</span>{/each}</div>{/if}</div>
						</div>
					{/if}
					{#if visibleSteps.length}
						<div class="timeline">
							{#each visibleSteps as step}
								<article class:tool={step.kind === 'tool'} class:error={step.status === 'error'}>
									<header><span>{step.kind === 'stage' ? String((step.metadata?.stage as CodingStage | undefined)?.name ?? step.phase) : step.tool}</span><small>{step.status}</small></header>
									<pre>{stepOutput(step)}</pre>
								</article>
							{/each}
						</div>
					{:else if activeBusy}
						<div class="working-state"><span></span>{codingSession.activeStageName || 'Starting coding flow…'}</div>
					{:else}
						<div class="empty-output"><strong>What should BitBuddy work on?</strong><span>Choose a project and flow, then send a task below. The stages and their work will appear here as they run.</span></div>
					{/if}
				</div>
				<ChatComposer
					mode="Code"
					buddyName="BitBuddy"
					contextUsage={null}
					thinkEnabled={false}
					thinkingLevel="off"
					reasoningEffortOptions={[]}
					reasoningEffortVisible={false}
					showThinkingControls={false}
					disabled={activeBusy || starting || !draft || !projectId}
					isStreaming={activeBusy}
					bind:draft={codingDraft}
					bind:attachments={codingAttachments}
					messageHistory={workflowRuns.map((run) => run.user_request)}
					historyKey="coding"
					placeholder="Describe what you want BitBuddy to build..."
					contextLabel={draft ? `Runs through ${draft.name}` : 'Choose a coding flow'}
					onDraftChange={() => {}}
					onSend={startRun}
					onStop={stopCodingRun}
					onThinkToggle={() => {}}
					onThinkingLevelChange={() => {}}
				/>
			</section>
		</main>
	</div>
</section>

{#if codingSession.pendingGate}
	<div class="modal"><div class="modal-card"><span class="modal-kicker">Stage approval</span><h2>{codingSession.pendingGate.stage_name} is ready</h2><pre>{codingSession.pendingGate.output}</pre><textarea bind:value={revisionFeedback} rows="3" placeholder="What should this stage revise?"></textarea><footer><button type="button" onclick={() => resolveCodingGate('stop')}>Stop</button><button type="button" onclick={() => resolveCodingGate('revise', revisionFeedback)} disabled={!revisionFeedback.trim()}>Revise</button><button class="primary" type="button" onclick={() => resolveCodingGate('approve')}>Continue</button></footer></div></div>
{/if}

{#if codingSession.pendingQuestion}
	{@const request = codingSession.pendingQuestion}
	<div class="modal"><div class="modal-card question-modal"><span class="modal-kicker">Input needed</span><h2>The active stage is paused</h2>{#each request.questions as item}<fieldset><legend><strong>{item.header}</strong>{item.question}</legend>{#each item.options as option}<button class:selected={questionAnswers[item.id] === option.label && !questionCustom[item.id]} type="button" onclick={() => selectQuestionChoice(request, item.id, option.label)}><strong>{option.label}</strong><small>{option.description}</small></button>{/each}<label><span>Other</span><input value={questionCustom[item.id] ?? ''} oninput={(event) => { const value = event.currentTarget.value; questionCustom[item.id] = value; if (value.trim()) questionAnswers[item.id] = value.trim(); else delete questionAnswers[item.id]; }} /></label></fieldset>{/each}<footer><button type="button" onclick={stopCodingRun}>Stop run</button><button class="primary" type="button" onclick={() => submitQuestion(request)}>Continue</button></footer></div></div>
{/if}

{#if codingSession.pendingPermission}
	<div class="modal"><div class="modal-card"><span class="modal-kicker">Permission required</span><h2>{codingSession.pendingPermission.tool}</h2><p>{codingSession.pendingPermission.reason}</p><pre>{JSON.stringify(codingSession.pendingPermission.arguments ?? {}, null, 2)}</pre><footer><button type="button" onclick={() => resolveCodingPermission(false)}>Deny and stop</button><button class="primary" type="button" onclick={() => resolveCodingPermission(true)}>Approve</button></footer></div></div>
{/if}

<style>
	.coding-wrap { width: 100%; max-width: 100%; height: 100%; display: grid; grid-template-rows: auto minmax(0, 1fr); gap: .72rem; --page-accent: #a78bfa; --page-soft: rgba(167,139,250,.16); }
	.header-button, .canvas-actions button { display: inline-flex; align-items: center; gap: .4rem; border: 1px solid var(--border); border-radius: .65rem; padding: .58rem .78rem; color: var(--text-soft); font-weight: 720; }
	.header-button:hover, .canvas-actions button:hover { color: var(--accent); border-color: var(--accent); }
	.run-status { padding: .42rem .65rem; border-radius: 999px; background: color-mix(in srgb, var(--warning) 14%, transparent); color: var(--warning); font-size: .74rem; font-weight: 800; text-transform: capitalize; }
	.coding-grid { min-height: 0; display: grid; grid-template-columns: 15.5rem minmax(32rem, 1fr) 21rem; gap: .72rem; }
	.flow-sidebar, .stage-editor, .flow-canvas { border: 1px solid color-mix(in srgb, var(--bg-soft) 70%, var(--border)); border-radius: 1.15rem; background: color-mix(in srgb, var(--panel) 92%, transparent); }
	.flow-sidebar, .stage-editor { min-height: 0; overflow: auto; padding: .9rem; }
	.section-heading, .editor-header, .canvas-header { display: flex; justify-content: space-between; align-items: center; gap: .7rem; }
	.section-heading { color: var(--text-soft); font-size: .72rem; font-weight: 820; letter-spacing: .08em; text-transform: uppercase; }
	.section-heading button, .editor-header button { display: grid; place-items: center; width: 1.9rem; height: 1.9rem; border-radius: .5rem; color: var(--text-soft); }
	.flow-list, .run-list { display: grid; gap: .42rem; margin-top: .65rem; }
	.flow-list button, .run-list button { display: grid; gap: .24rem; padding: .68rem .72rem; border: 1px solid transparent; border-radius: .72rem; text-align: left; color: var(--text); }
	.flow-list button:hover, .flow-list button.active { border-color: color-mix(in srgb, #a78bfa 45%, var(--border)); background: rgba(167,139,250,.09); }
	.flow-list small, .run-list small { color: var(--text-soft); font-size: .7rem; overflow: hidden; text-overflow: ellipsis; }
	.run-list strong { font-size: .78rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }.run-list small.bad { color: var(--warning); }
	.section-heading.recent { margin-top: 1.3rem; }
	.workspace { min-width: 0; min-height: 0; overflow: auto; display: grid; align-content: start; gap: .72rem; }
	label { display: grid; gap: .35rem; color: var(--text-soft); font-size: .74rem; font-weight: 700; } input, textarea { width: 100%; border: 1px solid var(--border); border-radius: .62rem; background: var(--bg-soft); color: var(--text); padding: .65rem .7rem; font: inherit; resize: vertical; } input:focus, textarea:focus { outline: none; border-color: var(--accent); }
	.error-banner { margin: 0; padding: .7rem .85rem; border: 1px solid color-mix(in srgb, var(--danger) 45%, var(--border)); border-radius: .75rem; background: color-mix(in srgb, var(--danger) 8%, var(--panel)); color: var(--danger); }
	.flow-canvas { padding: .9rem; }.canvas-header > div:first-child { display: flex; align-items: center; gap: .6rem; }.canvas-header span, .editor-header span { color: var(--text-soft); font-size: .7rem; font-weight: 800; letter-spacing: .07em; text-transform: uppercase; }.canvas-actions { display: flex; flex-wrap: wrap; gap: .35rem; }.canvas-actions button { padding: .45rem .55rem; font-size: .72rem; }.canvas-actions .save { color: #a78bfa; }
	.stage-strip { display: flex; gap: .55rem; overflow-x: auto; padding-top: .85rem; }.stage-link { position: relative; flex: 0 0 10rem; }.stage-link.current .stage-card { box-shadow: 0 0 0 2px var(--success); }.stage-card { width: 100%; min-height: 8.2rem; display: grid; align-content: start; gap: .25rem; padding: .72rem; border: 1px solid var(--border); border-radius: .8rem; text-align: left; color: var(--text); background: var(--bg-soft); }.stage-card.selected { border-color: #a78bfa; background: rgba(167,139,250,.08); }.stage-card small { color: var(--text-soft); font-size: .68rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.stage-card em { justify-self: start; margin-top: .2rem; padding: .16rem .35rem; border-radius: 999px; background: rgba(245,158,11,.12); color: var(--warning); font-size: .62rem; font-style: normal; }.stage-number { color: #a78bfa; font-size: .66rem; font-weight: 850; }.stage-order { position: absolute; top: .35rem; right: .35rem; display: flex; }.stage-order button { display: grid; place-items: center; width: 1.45rem; height: 1.45rem; color: var(--text-soft); }
	.timeline { display: grid; gap: .65rem; padding: .8rem; }.timeline article { border-left: 3px solid #a78bfa; border-radius: .55rem; background: var(--bg-soft); padding: .7rem .8rem; }.timeline article.tool { border-left-color: var(--accent); }.timeline article.error { border-left-color: var(--danger); }.timeline article header { display: flex; justify-content: space-between; text-transform: capitalize; }.timeline article small { color: var(--text-soft); }.timeline pre, .modal pre { margin: .55rem 0 0; white-space: pre-wrap; overflow-wrap: anywhere; font: .78rem/1.5 ui-monospace, monospace; color: var(--text-soft); max-height: 24rem; overflow: auto; }.empty-output, .empty-editor { padding: 2rem 1rem; color: var(--text-soft); text-align: center; line-height: 1.5; }
	.stage-editor { display: grid; align-content: start; gap: .8rem; }.editor-header > div { display: grid; gap: .2rem; }.editor-header strong { font-size: 1.05rem; }.check { display: flex; align-items: flex-start; gap: .5rem; }.check input { width: auto; margin-top: .12rem; }.recipes { display: grid; gap: .55rem; padding-top: .3rem; border-top: 1px solid var(--border); }.recipes > span { font-size: .74rem; font-weight: 800; }.recipes .check span { display: grid; gap: .15rem; min-width: 0; }.recipes small { color: var(--text-soft); font-weight: 500; overflow-wrap: anywhere; }.delete-flow { margin-top: 1rem; display: inline-flex; align-items: center; gap: .35rem; color: var(--danger); }
	.modal { position: fixed; inset: 0; z-index: 10000; display: grid; place-items: center; padding: 1rem; background: rgba(2,6,15,.66); backdrop-filter: blur(8px); }.modal-card { width: min(42rem, 100%); max-height: calc(100vh - 2rem); overflow: auto; padding: 1.2rem; border: 1px solid var(--border); border-radius: 1rem; background: var(--panel-raised); box-shadow: var(--shadow-panel); }.modal-kicker { color: #a78bfa; font-size: .7rem; font-weight: 850; letter-spacing: .08em; text-transform: uppercase; }.modal h2 { margin: .3rem 0 .7rem; }.modal footer { display: flex; justify-content: flex-end; gap: .55rem; margin-top: 1rem; }.modal footer button { padding: .62rem .9rem; border: 1px solid var(--border); border-radius: .6rem; }.modal footer .primary { background: #7c3aed; color: white; border-color: transparent; }.question-modal fieldset { display: grid; gap: .45rem; margin: .9rem 0; padding: 0; border: 0; }.question-modal legend { display: grid; gap: .2rem; margin-bottom: .25rem; }.question-modal fieldset > button { display: grid; gap: .15rem; padding: .7rem; border: 1px solid var(--border); border-radius: .65rem; text-align: left; }.question-modal fieldset > button.selected { border-color: #a78bfa; background: rgba(167,139,250,.09); }.question-modal button small { color: var(--text-soft); }
	@media (max-width: 1350px) { .coding-grid { grid-template-columns: 13rem minmax(28rem, 1fr) 19rem; } }
	@media (max-width: 1100px) { .coding-grid { grid-template-columns: 1fr; overflow: auto; }.flow-sidebar, .stage-editor { overflow: visible; }.flow-list, .run-list { grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); }.workspace { overflow: visible; }.coding-wrap { overflow: auto; }.stage-editor { order: 2; } }
	@media (max-width: 700px) { .canvas-header { align-items: flex-start; flex-direction: column; }.coding-grid { min-width: 0; } }

	/* Coding uses the same conversation proportions as Chat: compact setup above,
	   one wide scrolling transcript, and the shared composer at the bottom. */
	.coding-wrap { overflow: hidden; }
	.coding-grid { grid-template-columns: 13.5rem minmax(0, 1fr); overflow: hidden; }
	.workspace { display: flex; flex-direction: column; overflow: hidden; align-content: normal; }
	.config-row { min-width: 0; display: grid; grid-template-columns: minmax(0, 1fr) minmax(19rem, 28rem); gap: .72rem; }
	.flow-canvas, .stage-editor, .coding-conversation { border: 1px solid color-mix(in srgb, var(--bg-soft) 70%, var(--border)); border-radius: 1.05rem; background: color-mix(in srgb, var(--panel) 92%, transparent); }
	.flow-canvas, .stage-editor { min-width: 0; max-height: 25rem; overflow: auto; padding: .78rem; }
	.flow-title { min-width: 0; display: flex; align-items: baseline; gap: .55rem; }
	.flow-title strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.flow-title input { width: min(20rem, 32vw); padding: .42rem .55rem; }
	.canvas-header span, .editor-header span, .conversation-toolbar span { color: var(--text-soft); font-size: .68rem; font-weight: 800; letter-spacing: .07em; text-transform: uppercase; }
	.stage-strip { gap: .45rem; padding-top: .7rem; padding-bottom: .1rem; }
	.stage-link { flex-basis: 8.25rem; }
	.stage-card { min-height: 5.8rem; gap: .2rem; padding: .58rem; border-radius: .72rem; }
	.stage-card small { font-size: .64rem; }
	.stage-card em { margin-top: 0; padding: .12rem .3rem; font-size: .58rem; }
	.stage-order { top: .25rem; right: .25rem; }
	.stage-order button { width: 1.3rem; height: 1.3rem; }
	.stage-editor { display: grid; align-content: start; gap: .62rem; }
	.editor-header strong { font-size: .9rem; }
	.editor-grid { display: grid; grid-template-columns: 1fr 1fr; gap: .55rem; }
	.editor-grid .instructions { grid-column: 1 / -1; }
	.stage-editor label { gap: .3rem; font-size: .7rem; }
	.stage-editor input, .stage-editor textarea { padding: .58rem .65rem; }
	.delete-flow { margin-top: 0; font-size: .72rem; }
	.coding-conversation { flex: 1 1 0; min-width: 0; min-height: 0; overflow: hidden; display: grid; grid-template-rows: auto minmax(0, 1fr) auto; }
	.conversation-toolbar { min-height: 3.55rem; display: flex; justify-content: space-between; align-items: center; gap: 1rem; padding: .48rem .78rem; border-bottom: 1px solid var(--border); }
	.project-picker { width: min(20rem, 48%); display: grid; grid-template-columns: auto minmax(9rem, 1fr); align-items: center; gap: .55rem; }
	.output-state { display: grid; justify-items: end; gap: .1rem; }
	.output-state strong { font-size: .78rem; text-transform: capitalize; }
	.conversation-scroll { min-height: 0; overflow: auto; padding: 1rem clamp(.8rem, 3vw, 2.5rem); }
	.user-turn { display: flex; justify-content: flex-end; margin-bottom: 1rem; }
	.user-bubble { width: min(42rem, 82%); padding: .72rem .9rem; border-radius: 1rem 1rem .28rem 1rem; background: color-mix(in srgb, var(--accent) 18%, var(--bg-soft)); color: var(--text); }
	.user-bubble p { margin: 0; white-space: pre-wrap; }
	.run-attachments { display: flex; flex-wrap: wrap; gap: .35rem; margin-top: .55rem; }
	.run-attachments span { max-width: 15rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: .25rem .45rem; border: 1px solid var(--border); border-radius: .45rem; color: var(--text-soft); font-size: .68rem; }
	.timeline { max-width: 64rem; margin: 0 auto; padding: 0; }
	.timeline article { border-radius: .62rem; padding: .72rem .82rem; }
	.timeline article.tool { margin-left: 1.15rem; }
	.empty-output { min-height: 100%; display: grid; place-content: center; gap: .25rem; }
	.empty-output strong { color: var(--text); font-size: 1rem; }
	.working-state { height: 100%; display: flex; align-items: center; justify-content: center; gap: .55rem; color: var(--text-soft); }
	.working-state span { width: .55rem; height: .55rem; border-radius: 50%; background: #a78bfa; box-shadow: 0 0 0 .35rem rgba(167,139,250,.12); animation: coding-pulse 1.3s ease-in-out infinite; }
	@keyframes coding-pulse { 50% { opacity: .42; transform: scale(.8); } }
	@media (max-width: 1150px) { .coding-grid { grid-template-columns: 12.5rem minmax(0, 1fr); }.config-row { grid-template-columns: minmax(0, 1fr) minmax(18rem, 22rem); } }
	@media (max-width: 900px) { .coding-wrap { overflow: auto; height: auto; min-height: 100%; }.coding-grid { grid-template-columns: 1fr; overflow: visible; }.flow-sidebar { overflow: visible; }.flow-list, .run-list { grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); }.workspace { overflow: visible; }.config-row { grid-template-columns: 1fr; }.flow-canvas, .stage-editor { max-height: none; }.stage-editor { display: grid; }.coding-conversation { flex-basis: auto; min-height: 32rem; }.section-heading.recent { margin-top: .7rem; } }
	@media (max-width: 650px) { .flow-title { width: 100%; }.flow-title input { width: 100%; }.conversation-toolbar { align-items: stretch; flex-direction: column; }.project-picker { width: 100%; }.output-state { display: none; }.editor-grid { grid-template-columns: 1fr; }.editor-grid .instructions { grid-column: auto; }.user-bubble { width: 92%; } }
</style>
