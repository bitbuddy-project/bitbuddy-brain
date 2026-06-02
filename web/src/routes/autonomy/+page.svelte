<script lang="ts">
	import { onMount } from 'svelte';
	import {
		dismissIntention,
		getActivity,
		getAutonomyTimeline,
		getIntentions,
		getSubagentRuns,
		type ActivityItem,
		type AutonomyStatus,
		type AutonomyTimeline,
		type AutonomyTimelineCycle,
		type AutonomyTimelineStep,
		type IntentionItem,
		type SubagentRun
	} from '$lib/api/bitbuddy';
	import ActivityList from '$lib/components/activity/ActivityList.svelte';
	import { formatTime } from '$lib/stores/time.svelte';
	import SparkleIcon from 'phosphor-svelte/lib/SparkleIcon';

	let activity = $state<ActivityItem[]>([]);
	let autonomyStatus = $state<AutonomyStatus | null>(null);
	let timeline = $state<AutonomyTimeline | null>(null);
	let intentions = $state<IntentionItem[]>([]);
	let subagentRuns = $state<SubagentRun[]>([]);
	let expandedRunIds = $state<Set<string>>(new Set());
	let error = $state('');
	let loading = $state(true);
	let activeTab = $state<'timeline' | 'activity' | 'questions' | 'subagents'>('timeline');
	let cycleSteps = $derived((timeline?.steps ?? []).filter((step) => step.id !== 'delivery'));
	let deliveryStep = $derived((timeline?.steps ?? []).find((step) => step.id === 'delivery') ?? null);

	onMount(() => {
		void refreshActivity();
		const timer = window.setInterval(refreshActivity, 5000);
		return () => window.clearInterval(timer);
	});

	async function refreshActivity() {
		try {
			const [nextActivity, nextIntentions, nextTimeline, nextRuns] = await Promise.all([getActivity(), getIntentions(), getAutonomyTimeline(), getSubagentRuns()]);
			activity = nextActivity;
			intentions = nextIntentions;
			timeline = nextTimeline;
			autonomyStatus = nextTimeline.status;
			subagentRuns = nextRuns;
			error = '';
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}

	function toggleRunExpanded(runId: string) {
		const next = new Set(expandedRunIds);
		if (next.has(runId)) {
			next.delete(runId);
		} else {
			next.add(runId);
		}
		expandedRunIds = next;
	}

	function runStatusClass(status: string): string {
		if (status === 'completed') return 'completed';
		if (status === 'failed') return 'failed';
		if (status === 'running') return 'running';
		return '';
	}

	async function dismiss(id: number) {
		try {
			await dismissIntention(id);
			intentions = intentions.filter((item) => item.id !== id);
		} catch (e: any) {
			error = e.message;
		}
	}

	function projectLabel(intention: IntentionItem): string {
		const projectId = intention.metadata?.project_id;
		return typeof projectId === 'string' && projectId.trim() ? projectId : '';
	}

	function activeAutonomyJob() {
		return autonomyStatus?.jobs.find((job) => job.phase !== 'scheduled') ?? autonomyStatus?.jobs[0] ?? null;
	}

	function autonomyHeadline(): string {
		const job = activeAutonomyJob();
		if (job) return phaseLabel(job.phase);
		if (!autonomyStatus) return 'Loading Status';
		return stateLabel(autonomyStatus.state);
	}

	function autonomySubline(): string {
		const job = activeAutonomyJob();
		if (job?.activity) return `${activityLabel(job.activity)} · ${job.phase_message}`;
		return autonomyStatus?.message ?? '';
	}

	function stateLabel(state: string): string {
		if (state === 'blocked_by_lifecycle') return 'Lifecycle Paused';
		return phaseLabel(state || 'idle');
	}

	function phaseLabel(value: string): string {
		return value
			.split('_')
			.filter(Boolean)
			.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
			.join(' ');
	}

	function activityLabel(value: string): string {
		return phaseLabel(value);
	}

	function timestampLabel(value: string): string {
		return formatTime(value);
	}

	function cycleTitle(cycle: AutonomyTimelineCycle): string {
		return cycle.activity ? activityLabel(cycle.activity) : cycle.id.slice(0, 8);
	}

	function metadataText(step: AutonomyTimelineStep): string {
		const parts = [];
		const jobId = step.metadata?.job_id;
		const activity = step.metadata?.activity;
		const state = step.metadata?.state;
		const delay = step.metadata?.delay_seconds;
		if (typeof activity === 'string' && activity) parts.push(activityLabel(activity));
		if (typeof state === 'string' && state) parts.push(state);
		if (typeof delay === 'number' && delay > 0) parts.push(`${Math.round(delay)}s delay`);
		if (typeof jobId === 'string' && jobId) parts.push(`job ${jobId.slice(0, 8)}`);
		return parts.join(' · ');
	}

	function stepLabel(step: AutonomyTimelineStep): string {
		if (step.id === 'scheduled') return 'Idle wait';
		if (step.id === 'delivery') return 'Queued message delivery';
		return step.label;
	}

	function stepDescription(step: AutonomyTimelineStep): string {
		if (step.id === 'scheduled') return 'BitBuddy waits for a quiet window before starting background autonomy.';
		if (step.id === 'delivery') return 'Queued questions or comments are surfaced separately when cooldown and lifecycle gates allow.';
		return step.description;
	}
</script>

<div class="autonomy-page">
	<div class="autonomy-card">
		<header class="autonomy-header">
			<div class="title-mark" aria-hidden="true">
				<SparkleIcon size={30} weight="duotone" />
			</div>
			<div class="title-copy">
				<p class="eyebrow">System Activity</p>
				<h1>Autonomy</h1>
				<p>Agent logs and project monitoring activity.</p>
			</div>
			<div
				class="monitor-status"
				class:running={autonomyStatus?.state === 'running'}
				class:scheduled={autonomyStatus?.state === 'scheduled'}
				class:paused={autonomyStatus?.state === 'disabled' || autonomyStatus?.state === 'blocked_by_lifecycle'}
				title={autonomySubline()}
			>
				<span class="status-dot"></span>
				<div class="monitor-copy">
					<span>{autonomyHeadline()}</span>
					{#if autonomySubline()}<small>{autonomySubline()}</small>{/if}
				</div>
			</div>
		</header>

		<div class="autonomy-tabs" aria-label="Autonomy sections">
			<button class="tab-button" class:active={activeTab === 'timeline'} type="button" onclick={() => (activeTab = 'timeline')}>
				Timeline
			</button>
			<button class="tab-button" class:active={activeTab === 'activity'} type="button" onclick={() => (activeTab = 'activity')}>
				Activity Logs
			</button>
			<button class="tab-button" class:active={activeTab === 'questions'} type="button" onclick={() => (activeTab = 'questions')}>
				Questions
				{#if intentions.length}<span class="tab-count">{intentions.length}</span>{/if}
			</button>
			<button class="tab-button" class:active={activeTab === 'subagents'} type="button" onclick={() => (activeTab = 'subagents')}>
				Subagent Runs
				{#if subagentRuns.length}<span class="tab-count">{subagentRuns.length}</span>{/if}
			</button>
		</div>

		<div class="card-content">
			{#if loading}
				<div class="loading-state">
					<div class="spinner"></div>
					<span>Loading activity...</span>
				</div>
			{:else if activeTab === 'timeline'}
				<section class="timeline-panel" aria-label="Autonomy cycle timeline">
					<div class="timeline-heading">
						<div>
							<p class="eyebrow">Cycle Track</p>
							<h2>Autonomy Timeline</h2>
							<p>Follow the current idle cycle from activity through memory, lifecycle gates, background work, outputs, and repeat scheduling.</p>
						</div>
						{#if timeline?.lifecycle}
							<div class="lifecycle-chip" class:quiet={timeline.lifecycle.quiet_mode}>
								<span>{timeline.lifecycle.state}</span>
								<small>{timeline.lifecycle.quiet_mode ? 'Quiet mode' : 'Normal mode'}</small>
							</div>
						{/if}
					</div>

					{#if error}
						<div class="timeline-error">{error}</div>
					{/if}

					<div class="timeline-layout">
						<div class="cycle-track" aria-label="Background autonomy cycle">
							{#each cycleSteps as step}
								<article class={`timeline-step ${step.status}`}>
									<div class="step-rail" aria-hidden="true">
										<span></span>
									</div>
									<div class="step-card">
										<div class="step-topline">
											<span class="step-status">{phaseLabel(step.status)}</span>
											{#if step.timestamp}<time>{timestampLabel(step.timestamp)}</time>{/if}
										</div>
										<h3>{stepLabel(step)}</h3>
										<p>{step.message || stepDescription(step)}</p>
										{#if step.message}<small>{stepDescription(step)}</small>{/if}
										{#if metadataText(step)}<div class="step-meta">{metadataText(step)}</div>{/if}
									</div>
								</article>
							{/each}
						</div>

						<aside class="delivery-panel" aria-label="Queued message delivery">
							<div class="delivery-heading">
								<p class="eyebrow">Separate Lane</p>
								<h3>Queued Message Delivery</h3>
								<p>Questions and comments generated by autonomy wait in their own queue. They can surface later, independent of the current background cycle.</p>
							</div>
							{#if deliveryStep}
								<div class={`delivery-card ${deliveryStep.status}`}>
									<div class="delivery-status-row">
										<span class="delivery-status">{phaseLabel(deliveryStep.status)}</span>
										{#if deliveryStep.timestamp}<time>{timestampLabel(deliveryStep.timestamp)}</time>{/if}
									</div>
									<h4>{stepLabel(deliveryStep)}</h4>
									<p>{deliveryStep.message || stepDescription(deliveryStep)}</p>
									{#if deliveryStep.message}<small>{stepDescription(deliveryStep)}</small>{/if}
									{#if metadataText(deliveryStep)}<div class="step-meta">{metadataText(deliveryStep)}</div>{/if}
								</div>
							{:else}
								<div class="delivery-card pending">
									<span class="delivery-status">Pending</span>
									<h4>No delivery activity yet</h4>
									<p>Queued questions or comments will appear here when BitBuddy schedules or delivers one.</p>
								</div>
							{/if}
						</aside>
					</div>

					<div class="recent-cycles">
						<div class="recent-heading">
							<h3>Recent Cycles</h3>
							<span>{timeline?.recent_cycles.length ?? 0} tracked</span>
						</div>
						{#if !timeline?.recent_cycles.length}
							<p class="empty-intentions">No autonomy cycle history yet. New phase transitions will appear here as BitBuddy runs.</p>
						{:else}
							<div class="cycle-list">
								{#each timeline.recent_cycles as cycle}
									<article class={`cycle-card ${cycle.status}`}>
										<div>
											<span>{phaseLabel(cycle.status)}</span>
											<h4>{cycleTitle(cycle)}</h4>
											<small>{cycle.events.length} event(s) · updated {timestampLabel(cycle.updated_at)}</small>
										</div>
										<code>{cycle.id.slice(0, 8)}</code>
									</article>
								{/each}
							</div>
						{/if}
					</div>
				</section>
			{:else if activeTab === 'questions'}
				<section class="intentions-panel" aria-label="Generated questions and comments">
					<div class="intentions-heading">
						<div>
							<p class="eyebrow">Generated for Later</p>
							<h2>Questions & Comments</h2>
						</div>
						<span>{intentions.length} pending</span>
					</div>
					{#if intentions.length === 0}
						<p class="empty-intentions">No generated questions or comments yet. Idle autonomy will add them here when it has something worth bringing up later.</p>
					{:else}
						<div class="intention-list">
							{#each intentions as intention}
								<article class="intention-card">
									<div>
										<span class="kind-pill">{intention.kind}</span>
										{#if projectLabel(intention)}<span class="project-pill">{projectLabel(intention)}</span>{/if}
										<p>{intention.content}</p>
										{#if intention.reason}<small>{intention.reason}</small>{/if}
									</div>
									<button type="button" onclick={() => dismiss(intention.id)}>Dismiss</button>
								</article>
							{/each}
						</div>
					{/if}
				</section>
			{:else if activeTab === 'subagents'}
				<section class="subagents-panel" aria-label="Subagent run history">
					<div class="subagents-heading">
						<div>
							<p class="eyebrow">Delegated Work</p>
							<h2>Subagent Runs</h2>
							<p>Bounded worker runs delegated by BitBuddy via the <code>run_subagent</code> tool, with per-step tool use.</p>
						</div>
						<span>{subagentRuns.length} run{subagentRuns.length !== 1 ? 's' : ''}</span>
					</div>
					{#if subagentRuns.length === 0}
						<p class="empty-intentions">No subagent runs yet. BitBuddy will record delegated research and implementation tasks here when it uses the <code>run_subagent</code> tool.</p>
					{:else}
						<div class="subagent-list">
							{#each subagentRuns as run}
								<article class={`subagent-card ${runStatusClass(run.status)}`}>
									<button class="subagent-header" type="button" onclick={() => toggleRunExpanded(run.id)}>
										<div class="subagent-meta">
											<span class="kind-pill">{run.agent_type}</span>
											<span class={`run-status run-status-${runStatusClass(run.status)}`}>{run.status}</span>
										</div>
										<p class="subagent-task">{run.task}</p>
										<small>{run.steps.length} step{run.steps.length !== 1 ? 's' : ''} · {run.created_at ? timestampLabel(run.created_at) : ''}</small>
										<span class="expand-caret" class:expanded={expandedRunIds.has(run.id)}>▾</span>
									</button>
									{#if expandedRunIds.has(run.id)}
										<div class="subagent-body">
											{#if run.steps.length}
												<div class="step-list">
													{#each run.steps as step}
														<div class="subagent-step">
															<code class="step-tool">{step.tool}</code>
															<span class={`step-status-dot step-${step.status}`}></span>
															<span class="step-summary">{step.summary || '—'}</span>
														</div>
													{/each}
												</div>
											{/if}
											{#if run.report}
												<div class="subagent-report">
													<p class="eyebrow">Report</p>
													<p>{run.report}</p>
												</div>
											{/if}
											{#if run.error}
												<div class="subagent-error">{run.error}</div>
											{/if}
										</div>
									{/if}
								</article>
							{/each}
						</div>
					{/if}
				</section>
			{:else}
				<ActivityList {activity} {error} />
			{/if}
		</div>
	</div>
</div>

<style>
	.autonomy-page {
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

	.autonomy-card {
		--page-accent: #fb7185;
		--page-soft: rgba(251, 113, 133, 0.12);
		--page-border: rgba(251, 113, 133, 0.25);
		--page-glow: rgba(251, 113, 133, 0.14);

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

	.autonomy-header {
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
		flex: 1 1 auto;
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
		color: var(--text-soft);
	}

	.monitor-status {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		max-width: min(24rem, 38vw);
		font-size: 0.85rem;
		font-weight: 700;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.monitor-status { flex: 0 0 auto; }

	.monitor-copy {
		min-width: 0;
		display: grid;
		gap: 0.15rem;
	}

	.monitor-copy > span,
	.monitor-copy > small {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.monitor-copy > small {
		color: var(--text-soft);
		font-size: 0.68rem;
		font-weight: 700;
		letter-spacing: 0.02em;
		text-transform: none;
	}

	.autonomy-tabs {
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
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.75rem 1rem;
		border: none;
		border-bottom: 2px solid transparent;
		background: none;
		color: var(--text-muted);
		font-size: 0.85rem;
		font-weight: 700;
		letter-spacing: 0.02em;
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

	.tab-count {
		display: inline-grid;
		min-width: 1.15rem;
		height: 1.15rem;
		place-items: center;
		border-radius: 999px;
		background: var(--page-soft);
		color: var(--page-accent);
		font-size: 0.66rem;
		font-weight: 900;
	}

	.status-dot {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 999px;
		background: var(--success);
		box-shadow: 0 0 8px var(--success);
		flex: 0 0 auto;
	}

	.monitor-status.running .status-dot {
		background: var(--page-accent);
		box-shadow: 0 0 10px var(--page-accent);
	}

	.monitor-status.scheduled .status-dot {
		background: var(--warning);
		box-shadow: 0 0 10px var(--warning);
	}

	.monitor-status.paused .status-dot {
		background: var(--text-soft);
		box-shadow: none;
	}

	.card-content {
		min-height: 0;
		flex: 1 1 auto;
		padding: 1.25rem;
		overflow-y: auto;
		overscroll-behavior: contain;
		scrollbar-color: var(--scrollbar-thumb) transparent;
	}

	.timeline-panel {
		display: grid;
		gap: 1rem;
	}

	.timeline-heading,
	.recent-cycles {
		padding: 1rem;
		border: 1px solid var(--border);
		border-radius: 1.2rem;
		background: var(--surface-card);
		box-shadow: var(--shadow-panel);
	}

	.timeline-heading {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 1rem;
	}

	.timeline-heading h2 {
		font-size: 1.2rem;
		font-weight: 900;
	}

	.timeline-heading p:last-child {
		max-width: 48rem;
		color: var(--text-soft);
		font-size: 0.9rem;
		line-height: 1.5;
	}

	.lifecycle-chip {
		display: grid;
		gap: 0.2rem;
		min-width: 8.5rem;
		padding: 0.65rem 0.8rem;
		border: 1px solid var(--border);
		border-radius: 1rem;
		background: var(--surface-inset);
		text-align: right;
	}

	.lifecycle-chip span {
		color: var(--text);
		font-weight: 900;
	}

	.lifecycle-chip small {
		color: var(--text-soft);
		font-size: 0.72rem;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	.lifecycle-chip.quiet {
		border-color: rgba(251, 191, 36, 0.35);
		background: rgba(251, 191, 36, 0.08);
	}

	.timeline-error {
		padding: 0.8rem 1rem;
		border: 1px solid rgba(248, 113, 113, 0.35);
		border-radius: 1rem;
		background: rgba(248, 113, 113, 0.1);
		color: var(--danger);
	}

	.timeline-layout {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(18rem, 24rem);
		align-items: start;
		gap: 1rem;
	}

	.cycle-track {
		position: relative;
		display: grid;
		gap: 0.5rem;
		padding: 0.25rem 0;
	}

	.timeline-step {
		display: grid;
		grid-template-columns: 2rem minmax(0, 1fr);
		gap: 0.8rem;
	}

	.step-rail {
		position: relative;
		display: flex;
		justify-content: center;
		padding-top: 1.35rem;
	}

	.step-rail::before {
		content: '';
		position: absolute;
		top: 0;
		bottom: -0.75rem;
		width: 2px;
		border-radius: 999px;
		background: var(--border);
	}

	.timeline-step:last-child .step-rail::before {
		bottom: 50%;
	}

	.step-rail span {
		position: relative;
		z-index: 1;
		width: 0.78rem;
		height: 0.78rem;
		border: 2px solid var(--border-strong);
		border-radius: 999px;
		background: var(--panel);
		box-shadow: 0 0 0 0.28rem var(--panel);
	}

	.step-card {
		padding: 0.9rem 1rem;
		border: 1px solid var(--border);
		border-radius: 1rem;
		background: var(--surface-card);
		transition: border-color 140ms ease, background 140ms ease, transform 140ms ease;
	}

	.timeline-step.active .step-card {
		border-color: var(--page-border);
		background: linear-gradient(135deg, var(--page-soft), var(--surface-card));
		transform: translateY(-1px);
	}

	.timeline-step.completed .step-card {
		border-color: var(--border-strong);
		background: var(--surface-card);
	}

	.timeline-step.active .step-rail span {
		border-color: var(--page-accent);
		background: var(--page-accent);
		box-shadow: 0 0 0 0.28rem var(--panel), 0 0 16px var(--page-accent);
	}

	.timeline-step.completed .step-rail span {
		border-color: var(--border-strong);
		background: var(--panel-raised);
	}

	.timeline-step.completed .step-status {
		color: var(--text-soft);
	}

	.timeline-step.skipped .step-rail span,
	.timeline-step.blocked .step-rail span {
		border-color: var(--warning);
		background: var(--warning);
	}

	.timeline-step.failed .step-rail span {
		border-color: var(--danger);
		background: var(--danger);
	}

	.step-topline {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
		margin-bottom: 0.35rem;
	}

	.step-status {
		color: var(--page-accent);
		font-size: 0.68rem;
		font-weight: 900;
		text-transform: uppercase;
		letter-spacing: 0.08em;
	}

	.step-topline time {
		color: var(--text-soft);
		font-size: 0.72rem;
		font-weight: 700;
	}

	.step-card h3 {
		font-size: 1rem;
		font-weight: 900;
	}

	.step-card p {
		margin-top: 0.25rem;
		color: var(--text-soft);
		font-size: 0.9rem;
		line-height: 1.5;
	}

	.step-card small {
		display: block;
		margin-top: 0.45rem;
		color: var(--text-soft);
		font-size: 0.78rem;
		line-height: 1.45;
	}

	.step-meta {
		display: inline-flex;
		max-width: 100%;
		margin-top: 0.7rem;
		padding: 0.28rem 0.55rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		color: var(--text-soft);
		font-size: 0.72rem;
		font-weight: 800;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.delivery-panel {
		position: sticky;
		top: 0.25rem;
		display: grid;
		gap: 0.75rem;
		padding: 1rem;
		border: 1px solid var(--border);
		border-radius: 1.2rem;
		background:
			linear-gradient(135deg, rgba(110, 231, 183, 0.06), transparent 60%),
			var(--surface-card);
		box-shadow: var(--shadow-panel);
	}

	.delivery-heading {
		display: grid;
		gap: 0.25rem;
	}

	.delivery-heading h3 {
		font-size: 1.05rem;
		font-weight: 900;
	}

	.delivery-heading p:last-child {
		color: var(--text-soft);
		font-size: 0.86rem;
		line-height: 1.45;
	}

	.delivery-card {
		display: grid;
		gap: 0.35rem;
		padding: 0.85rem;
		border: 1px solid var(--border);
		border-radius: 1rem;
		background: var(--surface-inset);
	}

	.delivery-card.active {
		border-color: rgba(245, 158, 11, 0.35);
		background: rgba(245, 158, 11, 0.08);
	}

	.delivery-card.completed {
		border-color: rgba(110, 231, 183, 0.28);
		background: rgba(110, 231, 183, 0.07);
	}

	.delivery-card.failed {
		border-color: rgba(255, 107, 122, 0.32);
		background: rgba(255, 107, 122, 0.06);
	}

	.delivery-status-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
	}

	.delivery-status {
		width: fit-content;
		padding: 0.18rem 0.5rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		color: var(--text-soft);
		font-size: 0.66rem;
		font-weight: 900;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.delivery-card.active .delivery-status {
		border-color: rgba(245, 158, 11, 0.42);
		color: var(--warning);
	}

	.delivery-card.completed .delivery-status {
		border-color: rgba(110, 231, 183, 0.34);
		color: var(--success);
	}

	.delivery-card.failed .delivery-status {
		border-color: rgba(255, 107, 122, 0.38);
		color: var(--danger);
	}

	.delivery-card time {
		color: var(--text-soft);
		font-size: 0.72rem;
		font-weight: 700;
	}

	.delivery-card h4 {
		font-size: 0.95rem;
		font-weight: 900;
	}

	.delivery-card p,
	.delivery-card small {
		color: var(--text-soft);
		font-size: 0.86rem;
		line-height: 1.45;
	}

	.delivery-card small {
		display: block;
		margin-top: 0.15rem;
	}

	.recent-heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		margin-bottom: 0.9rem;
	}

	.recent-heading h3 {
		font-size: 1rem;
		font-weight: 900;
	}

	.recent-heading span {
		color: var(--text-soft);
		font-size: 0.72rem;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	.cycle-list {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(18rem, 100%), 1fr));
		gap: 0.75rem;
	}

	.cycle-card {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 1rem;
		padding: 0.8rem;
		border: 1px solid var(--border);
		border-radius: 1rem;
		background: var(--surface-inset);
	}

	.cycle-card span {
		color: var(--page-accent);
		font-size: 0.66rem;
		font-weight: 900;
		text-transform: uppercase;
		letter-spacing: 0.08em;
	}

	.cycle-card h4 {
		margin-top: 0.15rem;
		font-size: 0.95rem;
		font-weight: 900;
	}

	.cycle-card small {
		display: block;
		margin-top: 0.25rem;
		color: var(--text-soft);
		font-size: 0.78rem;
	}

	.cycle-card code {
		padding: 0.25rem 0.45rem;
		border: 1px solid var(--border);
		border-radius: 0.55rem;
		color: var(--text-soft);
		font-size: 0.72rem;
	}

	.intentions-panel {
		margin: 0;
		padding: 1rem;
		border: 1px solid var(--border);
		border-radius: 1.2rem;
		background: var(--surface-card);
		box-shadow: var(--shadow-panel);
	}

	.intentions-heading {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 1rem;
		margin-bottom: 1rem;
	}

	.intentions-heading > div {
		min-width: 0;
	}

	.intentions-heading h2 {
		font-size: 1.1rem;
		font-weight: 900;
		overflow-wrap: break-word;
	}

	.intentions-heading > span,
	.kind-pill,
	.project-pill {
		padding: 0.24rem 0.55rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		color: var(--text-soft);
		font-size: 0.72rem;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.empty-intentions {
		color: var(--text-soft);
		font-size: 0.9rem;
	}

	.intention-list {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(30rem, 100%), 1fr));
		gap: 0.8rem;
	}

	.intention-card {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 1rem;
		max-height: 18rem;
		overflow-y: auto;
		padding: 0.9rem;
		border: 1px solid var(--border);
		border-radius: 1rem;
		background: var(--surface-inset);
	}

	.intention-card > div {
		min-width: 0;
		flex: 1 1 auto;
		overflow-wrap: break-word;
	}

	.kind-pill {
		display: inline-flex;
		margin-right: 0.4rem;
		margin-bottom: 0.55rem;
		color: var(--page-accent);
		max-width: 100%;
		overflow-wrap: break-word;
	}

	.project-pill {
		display: inline-flex;
		margin-bottom: 0.55rem;
		max-width: 100%;
		overflow-wrap: break-word;
	}

	.intention-card p {
		line-height: 1.5;
		overflow-wrap: break-word;
	}

	.intention-card small {
		display: block;
		margin-top: 0.45rem;
		color: var(--text-soft);
		overflow-wrap: break-word;
	}

	.intention-card button {
		flex: 0 0 auto;
		padding: 0.5rem 0.7rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		color: var(--text-soft);
		font-size: 0.75rem;
		font-weight: 800;
	}

	.intention-card button:hover {
		border-color: var(--border-strong);
		background: var(--panel-raised);
		color: var(--text);
	}

	.loading-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 1rem;
		padding: 4rem;
		color: var(--text-soft);
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

	.subagents-panel {
		padding: 1rem;
		border: 1px solid var(--border);
		border-radius: 1.2rem;
		background: var(--surface-card);
		box-shadow: var(--shadow-panel);
	}

	.subagents-heading {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 1rem;
		margin-bottom: 1rem;
	}

	.subagents-heading h2 {
		font-size: 1.1rem;
		font-weight: 900;
	}

	.subagents-heading p:last-child {
		color: var(--text-soft);
		font-size: 0.9rem;
		line-height: 1.45;
	}

	.subagents-heading > span {
		padding: 0.24rem 0.55rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		color: var(--text-soft);
		font-size: 0.72rem;
		font-weight: 800;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		white-space: nowrap;
	}

	.subagent-list {
		display: grid;
		gap: 0.75rem;
	}

	.subagent-card {
		border: 1px solid var(--border);
		border-radius: 1rem;
		background: var(--surface-inset);
		overflow: hidden;
	}

	.subagent-card.completed { border-color: rgba(110, 231, 183, 0.22); }
	.subagent-card.failed { border-color: rgba(255, 107, 122, 0.28); }
	.subagent-card.running { border-color: var(--page-border); }

	.subagent-header {
		width: 100%;
		display: grid;
		gap: 0.3rem;
		padding: 0.85rem;
		text-align: left;
		border: none;
		background: none;
		cursor: pointer;
		position: relative;
	}

	.subagent-header:hover { background: var(--surface-hover, rgba(255,255,255,0.03)); }

	.subagent-meta {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.run-status {
		padding: 0.16rem 0.45rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		font-size: 0.66rem;
		font-weight: 900;
		text-transform: uppercase;
		letter-spacing: 0.07em;
		color: var(--text-soft);
	}

	.run-status-completed { border-color: rgba(110,231,183,0.34); color: var(--success); }
	.run-status-failed { border-color: rgba(255,107,122,0.38); color: var(--danger); }
	.run-status-running { border-color: var(--page-border); color: var(--page-accent); }

	.subagent-task {
		font-size: 0.92rem;
		font-weight: 700;
		line-height: 1.4;
		overflow-wrap: break-word;
	}

	.subagent-header small {
		color: var(--text-soft);
		font-size: 0.78rem;
	}

	.expand-caret {
		position: absolute;
		top: 0.85rem;
		right: 0.9rem;
		color: var(--text-soft);
		font-size: 1rem;
		transition: transform 0.2s ease;
	}

	.expand-caret.expanded { transform: rotate(180deg); }

	.subagent-body {
		padding: 0 0.85rem 0.85rem;
		display: grid;
		gap: 0.75rem;
	}

	.step-list {
		display: grid;
		gap: 0.35rem;
	}

	.subagent-step {
		display: flex;
		align-items: baseline;
		gap: 0.55rem;
		font-size: 0.85rem;
	}

	.step-tool {
		flex: 0 0 auto;
		padding: 0.1rem 0.4rem;
		border: 1px solid var(--border);
		border-radius: 0.45rem;
		color: var(--text-soft);
		font-size: 0.75rem;
	}

	.step-status-dot {
		width: 0.45rem;
		height: 0.45rem;
		border-radius: 999px;
		flex: 0 0 auto;
		background: var(--border-strong);
	}

	.step-completed { background: var(--success); }
	.step-error { background: var(--danger); }

	.step-summary {
		color: var(--text-soft);
		line-height: 1.4;
		overflow-wrap: break-word;
		min-width: 0;
	}

	.subagent-report {
		padding: 0.75rem;
		border: 1px solid var(--border);
		border-radius: 0.85rem;
		background: var(--surface-card);
	}

	.subagent-report p:last-child {
		margin-top: 0.35rem;
		font-size: 0.9rem;
		line-height: 1.5;
		color: var(--text-soft);
		overflow-wrap: break-word;
	}

	.subagent-error {
		padding: 0.6rem 0.8rem;
		border: 1px solid rgba(255, 107, 122, 0.32);
		border-radius: 0.8rem;
		background: rgba(255, 107, 122, 0.07);
		color: var(--danger);
		font-size: 0.85rem;
	}

	@media (max-width: 760px) {
		.autonomy-page,
		.autonomy-card {
			height: auto;
			max-height: none;
		}

		.autonomy-header {
			align-items: flex-start;
			flex-wrap: wrap;
		}

		.title-mark {
			width: 3rem;
			height: 3rem;
		}

		.monitor-status {
			width: 100%;
			max-width: 100%;
		}

		.timeline-heading {
			flex-direction: column;
		}

		.lifecycle-chip {
			width: 100%;
			text-align: left;
		}

		.timeline-layout {
			grid-template-columns: 1fr;
		}

		.delivery-panel {
			position: static;
			order: -1;
		}

		.timeline-step {
			grid-template-columns: 1.4rem minmax(0, 1fr);
			gap: 0.55rem;
		}

		.step-topline {
			align-items: flex-start;
			flex-direction: column;
			gap: 0.2rem;
		}
	}
</style>
