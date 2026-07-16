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
	import ShieldCheckIcon from 'phosphor-svelte/lib/ShieldCheckIcon';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import ChatComposer from '$lib/components/chat/ChatComposer.svelte';
	import CodingFlowMenu from '$lib/components/chat/CodingFlowMenu.svelte';
	import CodingRunsMenu from '$lib/components/chat/CodingRunsMenu.svelte';
	import ToolEventCard from '$lib/components/chat/ToolEventCard.svelte';
	import MarkdownMessage from '$lib/components/chat/MarkdownMessage.svelte';
	import ThinkingStream from '$lib/components/chat/ThinkingStream.svelte';
	import BitBuddyFace from '$lib/components/chat/BitBuddyFace.svelte';
	import Overlay from '$lib/components/ui/Overlay.svelte';
	import SelectMenu from '$lib/components/ui/SelectMenu.svelte';
	import type { SelectOption } from '$lib/components/ui/SelectMenu.svelte';
	import type { PendingChatAttachment } from '$lib/stores/chat.svelte';
	import {
		deleteCodingWorkflow,
		getProjectValidationRecipes,
		getProviderModels,
		saveCodingWorkflow,
		type ChatMessage,
		type CodingRun,
		type CodingRunStep,
		type ChatAttachment,
		type CodingStage,
		type CodingStageKind,
		type CodingWorkflow,
		type ProviderEntry,
		type QuestionRequest,
		type ToolDiff,
		type ValidationRecipe
	} from '$lib/api/bitbuddy';
	import { buildProviderModelOptions, reasoningEffortOptionsForProvider } from '$lib/providerModels';
	import {
		beginCodingRun,
		codingSession,
		initializeCoding,
		removeCodingRun,
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
	let flowMenuOpen = $state(false);
	let runsMenuOpen = $state(false);
	let editorOpen = $state(false);
	let bypassThisRun = $state(false);

	let selectedStage = $derived(draft?.stages.find((stage) => stage.id === selectedStageId) ?? null);
	let selectedProvider = $derived(selectedStage ? providerFor(selectedStage.provider_key) : undefined);
	let activeBusy = $derived(Boolean(codingSession.activeRun && !['completed', 'needs_attention', 'cancelled', 'failed'].includes(codingSession.activeRun.status)));
	let workflowRuns = $derived(codingSession.recentRuns.filter((run) => run.metadata?.source === 'workflow'));
	let visibleSteps = $derived((codingSession.activeRun?.steps ?? []).filter((step) => ['stage', 'tool', 'thinking'].includes(step.kind)));
	// The stage step is only persisted once a stage finishes, so while a stage is running we render a
	// live block (streaming thoughts + working indicator) until its final step shows up in visibleSteps.
	let liveStageActive = $derived(
		activeBusy &&
		Boolean(codingSession.activeStageId) &&
		!visibleSteps.some((step) => step.kind === 'stage' && step.metadata?.stage_id === codingSession.activeStageId)
	);
	let projectOptions = $derived<SelectOption[]>(codingSession.projects.map((project) => ({ value: project.id, label: project.name })));
	let providerOptions = $derived<SelectOption[]>(codingSession.providers.map((provider) => ({ value: providerKey(provider), label: providerLabel(provider), description: provider.model })));
	let runAttachments = $derived((codingSession.activeRun?.metadata?.attachments ?? []) as ChatAttachment[]);
	let flowTrusted = $derived(Boolean(draft?.bypass_permissions));
	let effectiveBypass = $derived(flowTrusted || bypassThisRun);

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
		if (!draft) {
			selectWorkflow(codingSession.workflows.find((workflow) => workflow.is_default) ?? codingSession.workflows[0]);
			if (!draft) return;
		}
		draft = { ...cloneWorkflow(draft!), id: '', name: `${draft!.name} copy`, is_default: false, stages: draft!.stages.map((stage) => ({ ...stage, id: crypto.randomUUID() })) };
		selectedWorkflowId = '';
		selectedStageId = draft.stages[0]?.id ?? '';
		editorOpen = true;
	}

	async function removeFlow() {
		if (!draft?.id) return;
		try {
			await deleteCodingWorkflow(draft.id);
			codingSession.workflows = codingSession.workflows.filter((workflow) => workflow.id !== draft?.id);
			selectWorkflow(codingSession.workflows[0]);
			editorOpen = false;
		} catch (caught) { localError = caught instanceof Error ? caught.message : 'Could not delete flow.'; }
	}

	async function startRun(message: string, attachments: ChatAttachment[] = []) {
		if (!draft || starting) return;
		if (!draft.id) await saveFlow();
		if (!draft.id && selectedWorkflowId) draft.id = selectedWorkflowId;
		if (!projectId || !draft.id || (!message.trim() && attachments.length === 0)) { localError = 'Choose a project, save the flow, and describe the coding task.'; return; }
		starting = true; localError = '';
		try { await beginCodingRun(projectId, draft.id, message.trim() || 'Use the attached files as the coding task.', attachments, bypassThisRun); }
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

	// Adapt a coding tool step into the ChatMessage shape the chat ToolEventCard/DiffEventCard expect,
	// so the coding feed reuses the same cards, diff highlighting, and tool-input rendering as chat.
	function toolMessage(step: CodingRunStep): ChatMessage {
		const metadata = step.metadata ?? {};
		return {
			role: 'tool',
			kind: 'tool',
			content: step.summary,
			status: step.status === 'error' || step.status === 'failed' ? 'error' : step.status === 'running' ? 'running' : 'completed',
			metadata: {
				tool: step.tool,
				arguments_summary: metadata.arguments_summary as Record<string, unknown> | undefined,
				result_summary: step.summary,
				error: typeof metadata.error === 'string' ? metadata.error : undefined,
				diff: metadata.diff as ToolDiff | undefined
			}
		};
	}

	function stageName(step: CodingRunStep) {
		return String((step.metadata?.stage as CodingStage | undefined)?.name ?? step.phase);
	}

	function stepThinking(step: CodingRunStep) {
		return typeof step.metadata?.thinking === 'string' ? step.metadata.thinking : '';
	}

	function stageReport(step: CodingRunStep) {
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

	function selectRun(run: CodingRun) {
		codingSession.activeRun = run;
		runsMenuOpen = false;
	}

	async function deleteRun(runId: string) {
		try { await removeCodingRun(runId); }
		catch (caught) { localError = caught instanceof Error ? caught.message : 'Could not delete run.'; }
	}
</script>

<section class="coding-wrap" data-mode="Code" aria-label="BitBuddy Coding workspace">
	<PageHeader icon={CodeIcon} variant="chat" eyebrow="Coding workspace" title={activeBusy ? (codingSession.activeStageName || 'Workflow running') : (draft?.name || 'Coding')}>
		{#snippet action()}
			{#if activeBusy}<span class="run-status">{codingSession.activeRun?.status.replaceAll('_', ' ')}</span>{/if}
			<CodingFlowMenu
				workflows={codingSession.workflows}
				selectedId={selectedWorkflowId}
				open={flowMenuOpen}
				disabled={activeBusy}
				onToggle={() => (flowMenuOpen = !flowMenuOpen)}
				onSelect={selectWorkflow}
				onNew={duplicateFlow}
				onEdit={() => (editorOpen = true)}
			/>
			<div class="project-pill"><SelectMenu value={projectId} options={projectOptions} placeholder="Project" ariaLabel="Coding project" disabled={activeBusy} compact onChange={(value) => (projectId = value)} /></div>
			<CodingRunsMenu
				runs={workflowRuns}
				open={runsMenuOpen}
				activeRunId={codingSession.activeRun?.id ?? ''}
				onToggle={() => (runsMenuOpen = !runsMenuOpen)}
				onSelect={selectRun}
				onDelete={deleteRun}
			/>
			<button class="header-button" type="button" onclick={() => goto('/')}><ArrowLeftIcon size={17} weight="bold" /> Chat</button>
		{/snippet}
	</PageHeader>

	<div class="coding-body">
		{#if localError || codingSession.error}<p class="error-banner">{localError || codingSession.error}</p>{/if}

		<div class="conversation-scroll">
			{#if codingSession.activeRun}
				<div class="user-turn">
					<div class="user-bubble"><p>{codingSession.activeRun.user_request}</p>{#if runAttachments.length}<div class="run-attachments">{#each runAttachments as attachment}<span>{attachment.name}</span>{/each}</div>{/if}</div>
				</div>
			{/if}
			{#if visibleSteps.length || liveStageActive}
				<div class="timeline">
					{#each visibleSteps as step (step.id)}
						{#if step.kind === 'thinking'}
							<ThinkingStream content={stepThinking(step)} error="" isStreaming={false} autoCollapse storageKey={`coding-think-${step.id}`} />
						{:else if step.kind === 'stage'}
							<div class="stage-turn" class:error={step.status === 'error'}>
								<div class="stage-avatar"><BitBuddyFace size="2.4rem" /></div>
								<div class="stage-content">
									<div class="stage-heading"><strong>{stageName(step)}</strong><span class="stage-status" class:error={step.status === 'error'}>{step.status}</span></div>
									<div class="stage-report"><MarkdownMessage content={stageReport(step)} /></div>
								</div>
							</div>
						{:else}
							<ToolEventCard message={toolMessage(step)} />
						{/if}
					{/each}
					{#if liveStageActive}
						<div class="stage-turn live">
							<div class="stage-avatar"><BitBuddyFace size="2.4rem" isThinking={!codingSession.stageOutput} isTyping={Boolean(codingSession.stageOutput)} /></div>
							<div class="stage-content">
								<div class="stage-heading"><strong>{codingSession.activeStageName || 'Working'}</strong><span class="stage-status running">running</span></div>
								{#if codingSession.stageThinking}<ThinkingStream content={codingSession.stageThinking} error="" isStreaming={true} storageKey="coding-live" />{/if}
								{#if codingSession.stageOutput}<div class="stage-report"><MarkdownMessage content={codingSession.stageOutput} /></div>{:else}<div class="stage-working"><span></span>Working…</div>{/if}
							</div>
						</div>
					{/if}
				</div>
			{:else if activeBusy}
				<div class="working-state"><span></span>{codingSession.activeStageName || 'Starting coding flow…'}</div>
			{:else}
				<div class="empty-output">
					<strong>What should BitBuddy work on?</strong>
					<span>Pick a flow and project up top, then describe the task below. The stages and their work appear here as they run.</span>
				</div>
			{/if}
		</div>

		<div class="run-options">
			{#if flowTrusted}
				<span class="trust-pill on"><ShieldCheckIcon size={14} weight="fill" /> Trusted flow — permission prompts off</span>
			{:else}
				<label class="trust-toggle" class:on={bypassThisRun}>
					<input type="checkbox" bind:checked={bypassThisRun} disabled={activeBusy} />
					<ShieldCheckIcon size={14} weight={bypassThisRun ? 'fill' : 'regular'} />
					<span>Skip permission prompts for this run</span>
				</label>
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
	</div>
</section>

<Overlay open={editorOpen} wide label="Edit coding flow" onClose={() => (editorOpen = false)}>
	<div class="flow-editor">
		<div class="editor-top">
			<div class="flow-title">
				<span>Flow</span>
				{#if draft}<input bind:value={draft.name} aria-label="Flow name" disabled={activeBusy} />{:else}<strong>Choose a saved flow</strong>{/if}
			</div>
			<button class="save" type="button" onclick={saveFlow} disabled={saving || activeBusy || !draft}><FloppyDiskIcon size={15} /> {saving ? 'Saving…' : 'Save'}</button>
		</div>

		<div class="add-actions">
			<button type="button" onclick={() => addStage('plan')} disabled={activeBusy || !draft}><PlusIcon size={14} /> Plan</button>
			<button type="button" onclick={() => addStage('review')} disabled={activeBusy || !draft}><PlusIcon size={14} /> Review</button>
			<button type="button" onclick={() => addStage('test')} disabled={activeBusy || !draft}><PlusIcon size={14} /> Test</button>
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

		<div class="stage-editor">
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
		</div>

		{#if draft}
			<label class="check trust-check"><input type="checkbox" bind:checked={draft.bypass_permissions} disabled={activeBusy} /><span><strong>Trust this flow</strong><small>Skip all permission prompts whenever this flow runs.</small></span></label>
		{/if}

		{#if draft?.id && !draft.is_default}<button class="delete-flow" type="button" onclick={removeFlow} disabled={activeBusy}><TrashIcon size={15} /> Delete flow</button>{/if}
	</div>
</Overlay>

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
	/* Coding mirrors the Chat surface: a header with dropdowns, one big transcript,
	   and the shared composer at the bottom. Flow editing lives in an overlay. */
	.coding-wrap {
		width: 100%;
		max-width: 100%;
		height: 100%;
		max-height: calc(100vh - 3rem);
		display: grid;
		grid-template-rows: auto minmax(0, 1fr);
		gap: 0.72rem;
		overflow: hidden;
		--page-accent: #a78bfa;
		--page-soft: rgba(167, 139, 250, 0.16);
		--mode-color: #a78bfa;
		--mode-soft: rgba(167, 139, 250, 0.22);
		--mode-border: rgba(167, 139, 250, 0.28);
		--mode-glow: rgba(167, 139, 250, 0.15);
	}

	:global(:root.light) .coding-wrap {
		--page-accent: #7c3aed;
		--page-soft: rgba(124, 58, 237, 0.14);
		--mode-color: #7c3aed;
		--mode-soft: rgba(124, 58, 237, 0.16);
		--mode-border: rgba(124, 58, 237, 0.3);
		--mode-glow: rgba(124, 58, 237, 0.18);
	}

	.header-button {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		height: 2.75rem;
		border: 1px solid var(--border);
		border-radius: 0.82rem;
		padding: 0 0.85rem;
		color: var(--text-soft);
		font-weight: 720;
	}

	.header-button:hover {
		color: var(--mode-color);
		border-color: var(--mode-color);
	}

	.project-pill {
		min-width: 9rem;
		max-width: 12rem;
	}

	.run-status {
		padding: 0.42rem 0.65rem;
		border-radius: 999px;
		background: color-mix(in srgb, var(--warning) 14%, transparent);
		color: var(--warning);
		font-size: 0.74rem;
		font-weight: 800;
		text-transform: capitalize;
	}

	/* Message surface — same treatment as ChatPanel's .chat-body. */
	.coding-body {
		--chat-canvas-bg: var(--bg-soft);
		--chat-panel-bg:
			radial-gradient(circle at 24% 0%, rgba(88, 66, 128, 0.14), transparent 27rem),
			linear-gradient(135deg, var(--glass-overlay, rgba(255, 255, 255, 0.03)), transparent 24rem),
			var(--panel-shell, var(--panel));
		position: relative;
		min-height: 0;
		min-width: 0;
		display: grid;
		grid-template-rows: minmax(0, 1fr) auto auto;
		border: 1px solid color-mix(in srgb, var(--bg-soft) 74%, var(--border));
		border-radius: 1.45rem;
		background: var(--chat-panel-bg);
		overflow: hidden;
	}

	.coding-body::before {
		content: '';
		position: absolute;
		inset: 0;
		z-index: 1;
		border-top: 1px solid rgba(255, 255, 255, 0.24);
		border-radius: inherit;
		pointer-events: none;
	}

	:global(:root.light) .coding-body {
		--chat-canvas-bg: #d3e1ef;
		--chat-panel-bg:
			radial-gradient(circle at 24% 0%, rgba(124, 58, 237, 0.08), transparent 27rem),
			linear-gradient(135deg, rgba(255, 255, 255, 0.28), transparent 24rem),
			#d8e6f4;
		border-color: rgba(73, 104, 145, 0.22);
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.68);
	}

	.error-banner {
		margin: 0.7rem 0.7rem 0;
		padding: 0.7rem 0.85rem;
		border: 1px solid color-mix(in srgb, var(--danger) 45%, var(--border));
		border-radius: 0.75rem;
		background: color-mix(in srgb, var(--danger) 8%, var(--panel));
		color: var(--danger);
		position: relative;
		z-index: 2;
	}

	.conversation-scroll {
		min-height: 0;
		overflow: auto;
		padding: 1.25rem clamp(0.8rem, 3vw, 2.5rem);
		position: relative;
		z-index: 2;
	}

	.user-turn {
		display: flex;
		justify-content: flex-end;
		margin-bottom: 1rem;
	}

	.user-bubble {
		width: min(42rem, 82%);
		padding: 0.72rem 0.9rem;
		border-radius: 1rem 1rem 0.28rem 1rem;
		background: color-mix(in srgb, var(--mode-color) 18%, var(--bg-soft));
		color: var(--text);
	}

	.user-bubble p {
		margin: 0;
		white-space: pre-wrap;
	}

	.run-attachments {
		display: flex;
		flex-wrap: wrap;
		gap: 0.35rem;
		margin-top: 0.55rem;
	}

	.run-attachments span {
		max-width: 15rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		padding: 0.25rem 0.45rem;
		border: 1px solid var(--border);
		border-radius: 0.45rem;
		color: var(--text-soft);
		font-size: 0.68rem;
	}

	.timeline {
		max-width: 64rem;
		margin: 0 auto;
		display: grid;
		gap: 0.85rem;
	}

	/* Stage turns read like an assistant message: avatar gutter + name, collapsible thoughts, report. */
	.stage-turn {
		display: grid;
		grid-template-columns: 2.4rem minmax(0, 1fr);
		gap: 0.7rem;
		align-items: start;
	}

	.stage-avatar {
		width: 2.4rem;
		height: 2.4rem;
	}

	.stage-content {
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.stage-heading {
		display: flex;
		align-items: center;
		gap: 0.55rem;
	}

	.stage-heading strong {
		color: var(--text);
		font-size: 0.8rem;
		font-weight: 850;
		letter-spacing: 0.03em;
	}

	.stage-status {
		padding: 0.12rem 0.45rem;
		border-radius: 999px;
		border: 1px solid var(--chip-border, var(--border));
		color: var(--text-soft);
		font-size: 0.66rem;
		font-weight: 800;
		letter-spacing: 0.05em;
		text-transform: uppercase;
	}

	.stage-status.running {
		color: var(--mode-color);
		border-color: var(--mode-border);
		background: color-mix(in srgb, var(--mode-color) 10%, transparent);
	}

	.stage-status.error {
		color: var(--danger);
		border-color: color-mix(in srgb, var(--danger) 45%, transparent);
		background: color-mix(in srgb, var(--danger) 10%, transparent);
	}

	.stage-report {
		border: 1px solid var(--card-border, var(--border));
		border-radius: 1rem;
		background: var(--surface-card, var(--bg-soft));
		padding: 0.6rem 0.9rem;
		color: var(--text);
	}

	.stage-turn.error .stage-report {
		border-color: color-mix(in srgb, var(--danger) 35%, var(--border));
	}

	.stage-working {
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
		color: var(--text-soft);
		font-size: 0.82rem;
	}

	.stage-working span {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 50%;
		background: var(--mode-color);
		box-shadow: 0 0 0 0.3rem rgba(167, 139, 250, 0.12);
		animation: coding-pulse 1.3s ease-in-out infinite;
	}

	.modal pre {
		margin: 0.55rem 0 0;
		white-space: pre-wrap;
		overflow-wrap: anywhere;
		font: 0.78rem/1.5 ui-monospace, monospace;
		color: var(--text-soft);
		max-height: 24rem;
		overflow: auto;
	}

	.empty-output {
		min-height: 100%;
		display: grid;
		place-content: center;
		gap: 0.25rem;
		padding: 2rem 1rem;
		text-align: center;
		color: var(--text-soft);
		line-height: 1.5;
	}

	.empty-output strong {
		color: var(--text);
		font-size: 1rem;
	}

	.working-state {
		height: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.55rem;
		color: var(--text-soft);
	}

	.working-state span {
		width: 0.55rem;
		height: 0.55rem;
		border-radius: 50%;
		background: var(--mode-color);
		box-shadow: 0 0 0 0.35rem rgba(167, 139, 250, 0.12);
		animation: coding-pulse 1.3s ease-in-out infinite;
	}

	@keyframes coding-pulse {
		50% { opacity: 0.42; transform: scale(0.8); }
	}

	.run-options {
		position: relative;
		z-index: 2;
		display: flex;
		justify-content: flex-start;
		padding: 0 clamp(0.8rem, 3vw, 2.5rem);
		padding-left: calc(clamp(0.8rem, 3vw, 2.5rem) + 50px);
		margin-bottom: -0.35rem;
	}

	.trust-toggle,
	.trust-pill {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.3rem 0.6rem;
		border-radius: 999px;
		font-size: 0.72rem;
		font-weight: 700;
		color: var(--text-soft);
		border: 1px solid transparent;
		cursor: pointer;
	}

	.trust-toggle input {
		width: auto;
		margin: 0;
		accent-color: var(--mode-color);
	}

	.trust-toggle:hover {
		color: var(--text);
	}

	.trust-toggle.on {
		color: var(--mode-color);
		background: color-mix(in srgb, var(--mode-color) 12%, transparent);
		border-color: var(--mode-border);
	}

	.trust-pill.on {
		cursor: default;
		color: var(--success);
		background: color-mix(in srgb, var(--success) 12%, transparent);
		border-color: color-mix(in srgb, var(--success) 40%, transparent);
	}

	/* Flow editor overlay */
	.flow-editor {
		display: grid;
		gap: 0.85rem;
		padding: 1.15rem;
	}

	.editor-top {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.7rem;
	}

	.flow-title {
		min-width: 0;
		display: flex;
		align-items: center;
		gap: 0.55rem;
	}

	.flow-title span,
	.editor-header span {
		color: var(--text-soft);
		font-size: 0.68rem;
		font-weight: 800;
		letter-spacing: 0.07em;
		text-transform: uppercase;
	}

	.flow-title input {
		width: min(20rem, 60vw);
		border: 1px solid var(--border);
		border-radius: 0.62rem;
		background: var(--bg-soft);
		color: var(--text);
		padding: 0.5rem 0.6rem;
		font: inherit;
		font-weight: 700;
	}

	.editor-top .save {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.5rem 0.75rem;
		border: 1px solid var(--border);
		border-radius: 0.65rem;
		color: var(--mode-color);
		font-weight: 720;
	}

	.editor-top .save:hover:not(:disabled) {
		border-color: var(--mode-color);
	}

	.add-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.35rem;
	}

	.add-actions button {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.45rem 0.6rem;
		border: 1px solid var(--border);
		border-radius: 0.6rem;
		color: var(--text-soft);
		font-size: 0.74rem;
		font-weight: 700;
	}

	.add-actions button:hover:not(:disabled) {
		color: var(--mode-color);
		border-color: var(--mode-color);
	}

	.stage-strip {
		display: flex;
		gap: 0.45rem;
		overflow-x: auto;
		padding-bottom: 0.2rem;
	}

	.stage-link {
		position: relative;
		flex: 0 0 8.5rem;
	}

	.stage-link.current .stage-card {
		box-shadow: 0 0 0 2px var(--success);
	}

	.stage-card {
		width: 100%;
		min-height: 5.8rem;
		display: grid;
		align-content: start;
		gap: 0.2rem;
		padding: 0.58rem;
		border: 1px solid var(--border);
		border-radius: 0.72rem;
		text-align: left;
		color: var(--text);
		background: var(--bg-soft);
	}

	.stage-card.selected {
		border-color: var(--mode-color);
		background: color-mix(in srgb, var(--mode-color) 8%, transparent);
	}

	.stage-card small {
		color: var(--text-soft);
		font-size: 0.64rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.stage-card em {
		justify-self: start;
		padding: 0.12rem 0.3rem;
		border-radius: 999px;
		background: rgba(245, 158, 11, 0.12);
		color: var(--warning);
		font-size: 0.58rem;
		font-style: normal;
	}

	.stage-number {
		color: var(--mode-color);
		font-size: 0.66rem;
		font-weight: 850;
	}

	.stage-order {
		position: absolute;
		top: 0.25rem;
		right: 0.25rem;
		display: flex;
	}

	.stage-order button {
		display: grid;
		place-items: center;
		width: 1.3rem;
		height: 1.3rem;
		color: var(--text-soft);
	}

	.stage-editor {
		display: grid;
		align-content: start;
		gap: 0.7rem;
		padding-top: 0.4rem;
		border-top: 1px solid var(--border);
	}

	.editor-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 0.7rem;
	}

	.editor-header > div {
		display: grid;
		gap: 0.2rem;
	}

	.editor-header strong {
		font-size: 0.95rem;
	}

	.editor-header button {
		display: grid;
		place-items: center;
		width: 1.9rem;
		height: 1.9rem;
		border-radius: 0.5rem;
		color: var(--text-soft);
	}

	.editor-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.55rem;
	}

	.editor-grid .instructions {
		grid-column: 1 / -1;
	}

	label {
		display: grid;
		gap: 0.3rem;
		color: var(--text-soft);
		font-size: 0.7rem;
		font-weight: 700;
	}

	.stage-editor input,
	.stage-editor textarea {
		width: 100%;
		border: 1px solid var(--border);
		border-radius: 0.62rem;
		background: var(--bg-soft);
		color: var(--text);
		padding: 0.58rem 0.65rem;
		font: inherit;
		resize: vertical;
	}

	.stage-editor input:focus,
	.stage-editor textarea:focus {
		outline: none;
		border-color: var(--mode-color);
	}

	.check {
		display: flex;
		align-items: flex-start;
		gap: 0.5rem;
		font-size: 0.74rem;
	}

	.check input {
		width: auto;
		margin-top: 0.12rem;
	}

	.recipes {
		display: grid;
		gap: 0.55rem;
		padding-top: 0.3rem;
		border-top: 1px solid var(--border);
	}

	.recipes > span {
		font-size: 0.74rem;
		font-weight: 800;
	}

	.recipes .check span {
		display: grid;
		gap: 0.15rem;
		min-width: 0;
	}

	.recipes small {
		color: var(--text-soft);
		font-weight: 500;
		overflow-wrap: anywhere;
	}

	.trust-check {
		padding-top: 0.4rem;
		border-top: 1px solid var(--border);
	}

	.trust-check span {
		display: grid;
		gap: 0.15rem;
	}

	.trust-check small {
		color: var(--text-soft);
		font-weight: 500;
	}

	.empty-editor {
		padding: 2rem 1rem;
		color: var(--text-soft);
		text-align: center;
	}

	.delete-flow {
		justify-self: start;
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		color: var(--danger);
		font-size: 0.78rem;
		font-weight: 700;
	}

	/* Shared modal styling (gate / question / permission) */
	.modal {
		position: fixed;
		inset: 0;
		z-index: 10000;
		display: grid;
		place-items: center;
		padding: 1rem;
		background: rgba(2, 6, 15, 0.66);
		backdrop-filter: blur(8px);
	}

	.modal-card {
		width: min(42rem, 100%);
		max-height: calc(100vh - 2rem);
		overflow: auto;
		padding: 1.2rem;
		border: 1px solid var(--border);
		border-radius: 1rem;
		background: var(--panel-raised);
		box-shadow: var(--shadow-panel);
	}

	.modal-kicker {
		color: var(--mode-color);
		font-size: 0.7rem;
		font-weight: 850;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.modal h2 {
		margin: 0.3rem 0 0.7rem;
	}

	.modal textarea {
		width: 100%;
		border: 1px solid var(--border);
		border-radius: 0.62rem;
		background: var(--bg-soft);
		color: var(--text);
		padding: 0.65rem 0.7rem;
		font: inherit;
		resize: vertical;
	}

	.modal footer {
		display: flex;
		justify-content: flex-end;
		gap: 0.55rem;
		margin-top: 1rem;
	}

	.modal footer button {
		padding: 0.62rem 0.9rem;
		border: 1px solid var(--border);
		border-radius: 0.6rem;
	}

	.modal footer .primary {
		background: #7c3aed;
		color: white;
		border-color: transparent;
	}

	.question-modal fieldset {
		display: grid;
		gap: 0.45rem;
		margin: 0.9rem 0;
		padding: 0;
		border: 0;
	}

	.question-modal legend {
		display: grid;
		gap: 0.2rem;
		margin-bottom: 0.25rem;
	}

	.question-modal fieldset > button {
		display: grid;
		gap: 0.15rem;
		padding: 0.7rem;
		border: 1px solid var(--border);
		border-radius: 0.65rem;
		text-align: left;
	}

	.question-modal fieldset > button.selected {
		border-color: var(--mode-color);
		background: color-mix(in srgb, var(--mode-color) 9%, transparent);
	}

	.question-modal label {
		display: grid;
		gap: 0.3rem;
	}

	.question-modal label input {
		width: 100%;
		border: 1px solid var(--border);
		border-radius: 0.62rem;
		background: var(--bg-soft);
		color: var(--text);
		padding: 0.6rem 0.7rem;
		font: inherit;
	}

	.question-modal button small {
		color: var(--text-soft);
	}

	@media (max-width: 760px) {
		.coding-wrap {
			height: calc(100vh - 2rem);
			max-height: none;
		}

		.project-pill {
			min-width: 7rem;
		}

		.editor-grid {
			grid-template-columns: 1fr;
		}

		.editor-grid .instructions {
			grid-column: auto;
		}
	}
</style>
