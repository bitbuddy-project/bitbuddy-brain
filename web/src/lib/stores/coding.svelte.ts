import {
	answerCodingGate,
	answerCodingPermission,
	answerCodingQuestion,
	cancelCodingWorkflow,
	getCodingRun,
	getCodingRuns,
	getCodingWorkflows,
	getConfig,
	getProjects,
	startCodingWorkflow,
	streamCodingWorkflow,
	type CodingRun,
	type ChatAttachment,
	type CodingStreamEvent,
	type CodingWorkflow,
	type ProjectSummary,
	type ProviderEntry,
	type QuestionRequest
} from '$lib/api/bitbuddy';

const TERMINAL = new Set(['completed', 'needs_attention', 'cancelled', 'failed']);
let initializedPromise: Promise<void> | null = null;
let streamController: AbortController | null = null;

export const codingSession = $state({
	initialized: false,
	loading: false,
	error: '',
	projects: [] as ProjectSummary[],
	providers: [] as ProviderEntry[],
	workflows: [] as CodingWorkflow[],
	recentRuns: [] as CodingRun[],
	activeRun: null as CodingRun | null,
	activeStageId: '',
	activeStageName: '',
	stageOutput: '',
	events: [] as CodingStreamEvent[],
	pendingGate: null as CodingStreamEvent | null,
	pendingQuestion: null as QuestionRequest | null,
	pendingPermission: null as CodingStreamEvent | null
});

export function initializeCoding() {
	if (!initializedPromise) initializedPromise = loadCodingState();
	return initializedPromise;
}

async function loadCodingState() {
	codingSession.loading = true;
	try {
		const [config, projects, workflows, runs] = await Promise.all([getConfig(), getProjects(), getCodingWorkflows(), getCodingRuns({ limit: 30 })]);
		codingSession.providers = config.providers?.length ? config.providers : config.provider.type !== 'none' ? [config.provider] : [];
		codingSession.projects = projects;
		codingSession.workflows = workflows;
		codingSession.recentRuns = runs;
		const active = runs.find((run) => run.metadata?.source === 'workflow' && !TERMINAL.has(run.status));
		if (active) {
			codingSession.activeRun = active;
			connectToRun(active.id);
		}
		codingSession.initialized = true;
		codingSession.error = '';
	} catch (caught) {
		codingSession.error = caught instanceof Error ? caught.message : 'Could not load Coding.';
	} finally {
		codingSession.loading = false;
	}
}

export async function refreshCoding() {
	initializedPromise = null;
	await initializeCoding();
}

export function replaceWorkflow(workflow: CodingWorkflow) {
	const index = codingSession.workflows.findIndex((item) => item.id === workflow.id);
	if (index >= 0) codingSession.workflows[index] = workflow;
	else codingSession.workflows = [workflow, ...codingSession.workflows];
}

export async function beginCodingRun(projectId: string, workflowId: string, task: string, attachments: ChatAttachment[] = []) {
	codingSession.error = '';
	const run = await startCodingWorkflow({ project_id: projectId, workflow_id: workflowId, task, attachments });
	codingSession.activeRun = run;
	codingSession.recentRuns = [run, ...codingSession.recentRuns.filter((item) => item.id !== run.id)];
	codingSession.events = [];
	codingSession.stageOutput = '';
	connectToRun(run.id);
}

function connectToRun(runId: string) {
	streamController?.abort();
	streamController = new AbortController();
	void streamCodingWorkflow(runId, handleCodingEvent, streamController.signal).catch((caught) => {
		if (caught instanceof DOMException && caught.name === 'AbortError') return;
		codingSession.error = caught instanceof Error ? caught.message : 'Coding stream disconnected.';
	});
}

function handleCodingEvent(event: CodingStreamEvent) {
	if (event.kind !== 'heartbeat') codingSession.events = [...codingSession.events, event].slice(-200);
	if (event.run) codingSession.activeRun = event.run;
	if (event.kind === 'stage_started') {
		codingSession.activeStageId = event.stage?.id ?? '';
		codingSession.activeStageName = event.stage?.name ?? '';
		codingSession.stageOutput = '';
	}
	if (event.kind === 'stage_output' || event.kind === 'stage_completed') codingSession.stageOutput = event.text ?? event.output ?? '';
	if (event.kind === 'gate_request') codingSession.pendingGate = event;
	if (event.kind === 'gate_resolved') codingSession.pendingGate = null;
	if (event.kind === 'question_request') codingSession.pendingQuestion = event.request ?? null;
	if (event.kind === 'question_answered') codingSession.pendingQuestion = null;
	if (event.kind === 'permission_request') codingSession.pendingPermission = event;
	if (event.kind === 'error') codingSession.error = event.text ?? event.error ?? 'Coding workflow failed.';
	if (event.done && codingSession.activeRun) {
		codingSession.pendingGate = null;
		codingSession.pendingQuestion = null;
		codingSession.pendingPermission = null;
		void refreshRun(codingSession.activeRun.id);
	}
	if (['stage_completed', 'tool_result', 'validation_result'].includes(event.kind) && codingSession.activeRun) void refreshRun(codingSession.activeRun.id);
}

async function refreshRun(runId: string) {
	try {
		const run = await getCodingRun(runId);
		codingSession.activeRun = run;
		codingSession.recentRuns = [run, ...codingSession.recentRuns.filter((item) => item.id !== run.id)];
	} catch { /* live stream remains the source of truth */ }
}

export async function resolveCodingGate(action: 'approve' | 'revise' | 'stop', feedback = '') {
	if (!codingSession.activeRun) return;
	await answerCodingGate(codingSession.activeRun.id, action, feedback);
	if (action === 'stop') codingSession.pendingGate = null;
}

export async function resolveCodingQuestion(interactionId: string, answers: Record<string, string>) {
	if (!codingSession.activeRun) return;
	await answerCodingQuestion(codingSession.activeRun.id, interactionId, answers);
	codingSession.pendingQuestion = null;
}

export async function resolveCodingPermission(granted: boolean) {
	if (!codingSession.activeRun) return;
	await answerCodingPermission(codingSession.activeRun.id, granted);
	codingSession.pendingPermission = null;
}

export async function stopCodingRun() {
	if (!codingSession.activeRun) return;
	await cancelCodingWorkflow(codingSession.activeRun.id);
}

export function codingStatusLabel() {
	const run = codingSession.activeRun;
	if (!run) return '';
	if (run.status === 'waiting_for_approval') return 'waiting';
	if (run.status === 'waiting_for_question') return 'question';
	if (run.status === 'waiting_for_permission') return 'permission';
	if (run.status === 'running') return 'running';
	return '';
}
