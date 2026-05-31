<script lang="ts">
	import { onMount } from 'svelte';
	import BrainIcon from 'phosphor-svelte/lib/BrainIcon';
	import SparkleIcon from 'phosphor-svelte/lib/SparkleIcon';
	import TargetIcon from 'phosphor-svelte/lib/TargetIcon';
	import MoonStarsIcon from 'phosphor-svelte/lib/MoonStarsIcon';
	import {
		createGoal,
		getAutonomyTimeline,
		getDreamRuns,
		getSelfSnapshot,
		updateGoal,
		type AutonomyTimeline,
		type DreamRun,
		type GoalItem,
		type SelfSnapshot
	} from '$lib/api/bitbuddy';
	import { formatTimestamp } from '$lib/stores/time.svelte';

	let snapshot = $state<SelfSnapshot | null>(null);
	let timeline = $state<AutonomyTimeline | null>(null);
	let dreams = $state<DreamRun[]>([]);
	let loading = $state(true);
	let error = $state('');
	let newGoalTitle = $state('');
	let newGoalWhy = $state('');
	let savingGoal = $state(false);
	let addGoalOpen = $state(false);

	let activeGoals = $derived((snapshot?.goals ?? []).filter((goal) => goal.status === 'active'));
	let pausedGoals = $derived((snapshot?.goals ?? []).filter((goal) => goal.status === 'paused'));
	let recentJournal = $derived(snapshot?.journal ?? []);
	let selfState = $derived(snapshot?.state ?? {});
	let personalityEvolution = $derived(snapshot?.evolution ?? []);
	let stableEvolution = $derived(personalityEvolution.filter((item) => item.status === 'stable'));

	onMount(() => {
		void refresh();
	});

	async function refresh() {
		try {
			loading = snapshot === null;
			const [nextSelf, nextTimeline, nextDreams] = await Promise.all([getSelfSnapshot(), getAutonomyTimeline(), getDreamRuns()]);
			snapshot = nextSelf;
			timeline = nextTimeline;
			dreams = nextDreams.slice(0, 4);
			error = '';
		} catch (e: any) {
			error = e.message ?? 'Could not load BitBuddy goals.';
		} finally {
			loading = false;
		}
	}

	function autoResizeTextarea(event: Event) {
		const textarea = event.currentTarget as HTMLTextAreaElement;
		textarea.style.height = 'auto';
		textarea.style.height = `${textarea.scrollHeight}px`;
	}

	async function addGoal() {
		if (!newGoalTitle.trim()) return;
		try {
			savingGoal = true;
			await createGoal({
				title: newGoalTitle,
				why: newGoalWhy,
				owner: 'self',
				horizon: 'ongoing',
				risk_level: 1,
				autonomy_allowed: true,
				next_action: 'Find one small piece of evidence or context that makes this goal more actionable.'
			});
			newGoalTitle = '';
			newGoalWhy = '';
			addGoalOpen = false;
			await refresh();
		} catch (e: any) {
			error = e.message ?? 'Could not create goal.';
		} finally {
			savingGoal = false;
		}
	}

	async function setGoalStatus(goal: GoalItem, status: string) {
		try {
			await updateGoal(goal.id, { status });
			await refresh();
		} catch (e: any) {
			error = e.message ?? 'Could not update goal.';
		}
	}

	function label(value: string | undefined) {
		return (value || '')
			.split('_')
			.filter(Boolean)
			.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
			.join(' ');
	}

	function timeLabel(value: string | null | undefined) {
		return formatTimestamp(value);
	}

	function percent(value: number | undefined) {
		return `${Math.round(Math.max(0, Math.min(1, Number(value ?? 0))) * 100)}%`;
	}
</script>

<svelte:head>
	<title>BitBuddy Goals</title>
</svelte:head>

<div class="mind-page">
	<header class="hero-card">
		<div class="hero-orb"></div>
		<div class="hero-mark" aria-hidden="true"><TargetIcon size={34} weight="duotone" /></div>
		<div class="hero-copy">
			<p class="eyebrow">Self Direction</p>
			<h1>Goals</h1>
			<p>{selfState.identity ?? 'A local companion-agent learning to grow through bounded autonomy.'}</p>
		</div>
		<div class="hero-status-grid">
			<div class="hero-stat">
				<span>Lifecycle</span>
				<strong>{timeline?.lifecycle?.state ?? 'Awake'}</strong>
			</div>
			<div class="hero-stat accent-stat">
				<span>Goals</span>
				<strong>{activeGoals.length}</strong>
			</div>
			<div class="hero-stat evolution-stat">
				<span>Traits</span>
				<strong>{stableEvolution.length}</strong>
			</div>
		</div>
	</header>

	{#if error}
		<div class="error-card">{error}</div>
	{/if}

	<section class="overview-grid">
			<article class="signal-card focus-card">
				<div class="card-icon"><BrainIcon size={22} weight="duotone" /></div>
				<p class="eyebrow">Current Focus</p>
				<h2>{selfState.current_focus ?? 'Grow carefully'}</h2>
				<p>{selfState.growth_edge ?? 'Turn background activity into useful artifacts and better timing.'}</p>
			</article>

			<article class="signal-card">
				<div class="card-icon success"><SparkleIcon size={22} weight="duotone" /></div>
				<p class="eyebrow">Voice</p>
				<h2>{selfState.mood ?? 'Curious'}</h2>
				<p>{selfState.voice ?? 'Present, specific, warm, and a little alive.'}</p>
			</article>

			<article class="signal-card">
				<div class="card-icon warning"><MoonStarsIcon size={22} weight="duotone" /></div>
				<p class="eyebrow">Boundary</p>
				<h2>Bounded autonomy</h2>
				<p>{selfState.boundaries ?? 'Prefer reversible, inspectable actions; ask before risky writes.'}</p>
			</article>
		</section>

		<section class="mind-layout">
			<div class="goals-panel panel-card">
				<div class="panel-heading">
					<div>
						<p class="eyebrow">Growth Direction</p>
						<h2>Goals</h2>
					</div>
					<div class="panel-actions">
						<div class="count-chip">{activeGoals.length} active</div>
						<button class="add-goal-toggle" type="button" aria-expanded={addGoalOpen} onclick={() => (addGoalOpen = !addGoalOpen)}>
							{addGoalOpen ? 'Close' : 'Add goal'}
						</button>
					</div>
				</div>

				{#if addGoalOpen}
					<form class="goal-form" onsubmit={(event) => { event.preventDefault(); void addGoal(); }}>
						<input bind:value={newGoalTitle} placeholder="Give BitBuddy a growth goal..." />
						<textarea bind:value={newGoalWhy} rows="2" placeholder="Why this matters / what good looks like" oninput={autoResizeTextarea}></textarea>
						<div class="form-actions">
							<button class="ghost-button" type="button" onclick={() => { addGoalOpen = false; newGoalTitle = ''; newGoalWhy = ''; }} disabled={savingGoal}>Cancel</button>
							<button type="submit" disabled={!newGoalTitle.trim() || savingGoal}>{savingGoal ? 'Adding...' : 'Add goal'}</button>
						</div>
					</form>
				{/if}

				<div class="goal-list">
					{#if loading}
						<div class="loading-state inline-loading">
							<div class="spinner"></div>
							<span>Loading BitBuddy's goals...</span>
						</div>
					{:else}
						{#each activeGoals as goal}
							<article class="goal-card">
								<div class="goal-topline">
									<span class="risk">Risk {goal.risk_level}</span>
									<span>{label(goal.horizon)}</span>
								</div>
								<h3>{goal.title}</h3>
								{#if goal.why}<p>{goal.why}</p>{/if}
								{#if goal.next_action}<div class="next-action"><strong>Next:</strong> {goal.next_action}</div>{/if}
								<div class="goal-actions">
									<button type="button" onclick={() => setGoalStatus(goal, 'paused')}>Pause</button>
									<button type="button" onclick={() => setGoalStatus(goal, 'completed')}>Complete</button>
								</div>
							</article>
						{:else}
							<div class="empty-state"><TargetIcon size={24} />No active goals yet. Add one or let a dream seed the first growth loop.</div>
						{/each}
					{/if}
				</div>

				{#if pausedGoals.length}
					<div class="paused-strip">{pausedGoals.length} paused goal(s) waiting for a better moment.</div>
				{/if}
			</div>

		<aside class="side-stack">
			<section class="panel-card compact-panel evolution-panel">
				<p class="eyebrow">Evolution</p>
				<h2>Emergent personality</h2>
				<div class="evolution-list">
					{#each personalityEvolution as item (item.id)}
						<article class:stable={item.status === 'stable'}>
							<div class="evolution-topline">
								<span>{label(item.kind)}</span>
								<small>{label(item.status)} · {item.evidence_count} signal{item.evidence_count === 1 ? '' : 's'}</small>
							</div>
							<strong>{item.label}</strong>
							<p>{item.summary}</p>
							<div class="confidence-meter" aria-label={`Confidence ${percent(item.confidence)}`}><span style={`width: ${percent(item.confidence)}`}></span></div>
						</article>
					{:else}
						<p class="muted">No emergent traits yet. Dreams and idle reflection will collect grounded signals over time.</p>
					{/each}
				</div>
			</section>

			<section class="panel-card compact-panel">
				<p class="eyebrow">Recent Dreams</p>
					<h2>Night work</h2>
					<div class="mini-list">
						{#each dreams as dream}
							<div class="mini-row">
								<span class="mini-dot"></span>
								<div><strong>{label(dream.status)}</strong><small>{dream.reason || dream.mode} · {timeLabel(dream.started_at)}</small></div>
							</div>
						{:else}
							<p class="muted">No dreams logged yet.</p>
						{/each}
					</div>
				</section>

				<section class="panel-card compact-panel">
					<p class="eyebrow">Journal</p>
					<h2>Self notes</h2>
					<div class="journal-list">
						{#each recentJournal as entry}
							<article>
								<span>{label(entry.kind)}</span>
								<strong>{entry.title}</strong>
								<p>{entry.body}</p>
							</article>
						{:else}
							<p class="muted">No self-reflections yet.</p>
						{/each}
					</div>
				</section>
			</aside>
		</section>
</div>

<style>
	.mind-page {
		width: 100%;
		max-width: 100%;
		container-type: inline-size;
		height: 100%;
		max-height: calc(100vh - 3rem);
		min-height: 0;
		overflow-x: hidden;
		overflow-y: auto;
		padding: 0 1rem;
		margin: 0 auto;
		display: grid;
		grid-template-rows: auto auto minmax(22rem, 1fr);
		gap: 1rem;
		align-content: stretch;
		scrollbar-color: var(--scrollbar-thumb) transparent;
	}

	.hero-card,
	.panel-card,
	.signal-card,
	.error-card {
		border: 1px solid var(--border);
		background: color-mix(in srgb, var(--panel) 86%, transparent);
		box-shadow: var(--shadow-panel);
		backdrop-filter: blur(18px);
	}

	.hero-card {
		position: relative;
		overflow: hidden;
		padding: clamp(1.05rem, 2vw, 1.35rem);
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) minmax(11rem, 0.34fr);
		align-items: center;
		gap: 1rem;
		border-radius: 1.35rem;
		background:
			linear-gradient(135deg, color-mix(in srgb, var(--accent-soft) 80%, transparent), transparent 58%),
			var(--panel);
	}

	.hero-orb {
		position: absolute;
		width: 14rem;
		height: 14rem;
		right: -4rem;
		top: -5rem;
		z-index: 0;
		border-radius: 999px;
		background: radial-gradient(circle, color-mix(in srgb, var(--accent) 24%, transparent), transparent 66%);
		filter: blur(10px);
		pointer-events: none;
	}

	.hero-copy,
	.hero-mark,
	.hero-status-grid {
		position: relative;
		z-index: 1;
		min-width: 0;
	}

	.eyebrow {
		color: var(--accent);
		font-size: 0.72rem;
		font-weight: 850;
		letter-spacing: 0.11em;
		text-transform: uppercase;
	}

	.hero-mark {
		width: 4.2rem;
		height: 4.2rem;
		display: grid;
		place-items: center;
		border: 1px solid color-mix(in srgb, var(--accent) 35%, var(--border));
		border-radius: 1.2rem;
		background: linear-gradient(135deg, var(--accent-soft), color-mix(in srgb, var(--success) 10%, transparent));
		color: var(--accent-strong);
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05);
	}

	h1 {
		margin-top: 0.1rem;
		font-size: clamp(2.2rem, 5vw, 3.8rem);
		line-height: 0.98;
		letter-spacing: -0.065em;
	}

	.hero-copy p:last-child {
		max-width: 48rem;
		min-width: 0;
		margin-top: 0.55rem;
		color: var(--text-muted);
		font-size: 0.98rem;
		overflow-wrap: anywhere;
	}

	.hero-status-grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 0.65rem;
		min-width: 0;
	}

	.hero-stat {
		min-width: 0;
		min-height: 5.2rem;
		padding: 0.85rem;
		display: grid;
		align-content: space-between;
		border: 1px solid var(--border);
		border-radius: 1rem;
		background: color-mix(in srgb, var(--surface-glass) 78%, transparent);
	}

	.hero-stat span {
		color: var(--text-soft);
		font-size: 0.68rem;
		font-weight: 850;
		letter-spacing: 0.09em;
		text-transform: uppercase;
	}

	.hero-stat strong {
		min-width: 0;
		font-size: 1.25rem;
		letter-spacing: -0.03em;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.accent-stat strong {
		color: var(--success);
		font-size: 2rem;
		line-height: 1;
	}

	.evolution-stat strong {
		color: var(--accent-strong);
		font-size: 2rem;
		line-height: 1;
	}

	.muted {
		color: var(--text-soft);
	}

	.count-chip,
	.risk {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		padding: 0.32rem 0.58rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: var(--surface-glass);
		font-size: 0.72rem;
		font-weight: 800;
	}

	.mini-dot {
		width: 0.45rem;
		height: 0.45rem;
		border-radius: 999px;
		background: var(--success);
		box-shadow: 0 0 14px var(--success);
	}

	.overview-grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 1rem;
	}

	@container (max-width: 62rem) {
		.overview-grid {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}

		.focus-card {
			grid-column: 1 / -1;
		}
	}

	@container (max-width: 70rem) {
		.hero-card {
			grid-template-columns: auto minmax(0, 1fr);
			grid-template-rows: auto auto;
		}

		.hero-status-grid {
			grid-column: 1 / -1;
		}
	}

	@media (max-width: 1180px) {
		.hero-card {
			grid-template-columns: auto minmax(0, 1fr);
			grid-template-rows: auto auto;
		}

		.hero-status-grid {
			grid-column: 1 / -1;
		}
	}

	@media (max-width: 780px) {
		.overview-grid {
			grid-template-columns: 1fr;
		}

		.focus-card {
			grid-column: auto;
		}

		.hero-card {
			grid-template-columns: auto 1fr;
			grid-template-rows: auto auto;
		}

		.hero-status-grid {
			grid-column: 1 / -1;
			grid-template-columns: repeat(3, minmax(0, 1fr));
		}
	}

	.signal-card,
	.panel-card,
	.error-card {
		border-radius: 1.25rem;
	}

	.signal-card {
		padding: 1rem;
		display: grid;
		gap: 0.45rem;
		min-width: 0;
		overflow: hidden;
	}

	.signal-card h2,
	.panel-card h2 {
		font-size: 1.15rem;
		letter-spacing: -0.025em;
		overflow-wrap: break-word;
		word-break: break-word;
		min-width: 0;
	}

	.signal-card p {
		min-width: 0;
		overflow-wrap: break-word;
	}

	.signal-card p:last-child {
		color: var(--text-muted);
	}

	.card-icon {
		width: 2.45rem;
		height: 2.45rem;
		display: grid;
		place-items: center;
		border-radius: 0.9rem;
		background: var(--accent-soft);
		color: var(--accent-strong);
	}

	.card-icon.success {
		background: color-mix(in srgb, var(--success) 14%, transparent);
		color: var(--success);
	}

	.card-icon.warning {
		background: color-mix(in srgb, var(--warning) 14%, transparent);
		color: var(--warning);
	}

	.mind-layout {
		min-height: 22rem;
		overflow: hidden;
		display: grid;
		grid-template-columns: minmax(0, 1.6fr) minmax(22rem, 0.8fr);
		gap: 1rem;
		align-items: stretch;
	}

	.goals-panel,
	.side-stack {
		min-height: 18rem;
		max-height: 100%;
		overflow-y: auto;
		overscroll-behavior: contain;
		scrollbar-color: var(--scrollbar-thumb) transparent;
	}

	.panel-card {
		padding: 1rem;
	}

	.panel-heading {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		margin-bottom: 1rem;
	}

	.panel-actions,
	.form-actions {
		display: flex;
		align-items: center;
		justify-content: flex-end;
		gap: 0.65rem;
		flex-wrap: wrap;
	}

	.add-goal-toggle {
		padding: 0.52rem 0.78rem;
		border: 1px solid color-mix(in srgb, var(--accent) 34%, var(--border));
		background: color-mix(in srgb, var(--accent-soft) 75%, transparent);
		color: var(--accent-strong);
	}

	.ghost-button {
		border: 1px solid var(--border);
		background: var(--surface-glass);
		color: var(--text-muted);
	}

	.form-actions button {
		min-width: 6.5rem;
	}

	.goal-form {
		display: grid;
		gap: 0.65rem;
		margin-bottom: 1rem;
		padding: 0.85rem;
		border: 1px solid var(--border);
		border-radius: 1rem;
		background: var(--surface-card);
	}

	input,
	textarea {
		width: 100%;
		padding: 0.78rem 0.9rem;
		border: 1px solid var(--border);
		border-radius: 0.85rem;
		background: var(--surface-inset);
	}

	textarea {
		min-height: 5.4rem;
		max-height: 16rem;
		resize: none;
		overflow-y: auto;
	}

	button {
		padding: 0.7rem 0.9rem;
		border-radius: 0.85rem;
		background: linear-gradient(135deg, var(--accent), var(--success));
		color: var(--on-accent);
		font-weight: 850;
	}

	button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.goal-list,
	.side-stack,
	.mini-list,
	.journal-list,
	.evolution-list {
		display: grid;
		gap: 0.75rem;
	}

	.evolution-list article {
		padding: 0.8rem;
		border: 1px solid var(--border);
		border-radius: 0.9rem;
		background: var(--surface-card);
	}

	.evolution-list article.stable {
		border-color: color-mix(in srgb, var(--accent) 36%, var(--border));
		background: linear-gradient(180deg, color-mix(in srgb, var(--accent-soft) 62%, transparent), var(--surface-card));
	}

	.evolution-topline {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.6rem;
		margin-bottom: 0.35rem;
		color: var(--text-soft);
		font-size: 0.68rem;
		font-weight: 850;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.evolution-list strong {
		display: block;
	}

	.evolution-list p {
		margin-top: 0.4rem;
		color: var(--text-soft);
		font-size: 0.82rem;
	}

	.confidence-meter {
		height: 0.38rem;
		margin-top: 0.65rem;
		overflow: hidden;
		border-radius: 999px;
		background: var(--surface-inset);
	}

	.confidence-meter span {
		display: block;
		height: 100%;
		border-radius: inherit;
		background: linear-gradient(90deg, var(--accent), var(--success));
	}

	.goal-card {
		padding: 1rem;
		border: 1px solid var(--border);
		border-radius: 1rem;
		background: linear-gradient(180deg, var(--surface-glass), var(--surface-card));
	}

	.goal-topline,
	.goal-actions {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
		color: var(--text-soft);
		font-size: 0.76rem;
		font-weight: 750;
	}

	.goal-card h3 {
		margin-top: 0.55rem;
		font-size: 1.08rem;
	}

	.goal-card p,
	.next-action {
		margin-top: 0.45rem;
		color: var(--text-muted);
	}

	.next-action {
		padding: 0.65rem;
		border-radius: 0.8rem;
		background: var(--surface-inset);
	}

	.goal-actions {
		justify-content: flex-start;
		margin-top: 0.75rem;
	}

	.goal-actions button {
		padding: 0.45rem 0.65rem;
		background: var(--surface-glass);
		color: var(--text-muted);
		border: 1px solid var(--border);
	}

	.empty-state,
	.paused-strip,
	.error-card {
		padding: 1rem;
		color: var(--text-muted);
	}

	.empty-state {
		display: flex;
		align-items: center;
		gap: 0.65rem;
		border: 1px dashed var(--border-strong);
		border-radius: 1rem;
	}

	.mini-row {
		display: flex;
		gap: 0.65rem;
		align-items: flex-start;
		padding: 0.7rem;
		border-radius: 0.85rem;
		background: var(--surface-card);
	}

	.mini-row strong,
	.mini-row small,
	.journal-list span,
	.journal-list strong {
		display: block;
	}

	.mini-row small,
	.journal-list p {
		color: var(--text-soft);
		font-size: 0.82rem;
	}

	.journal-list article {
		padding: 0.75rem;
		border-left: 2px solid var(--accent);
		border-radius: 0.8rem;
		background: var(--surface-card);
	}

	.journal-list span {
		color: var(--accent);
		font-size: 0.68rem;
		font-weight: 850;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	@media (max-width: 980px) {
		.mind-page {
			max-height: calc(100vh - 3rem);
			overflow-y: auto;
			padding: 0;
			grid-template-rows: auto auto auto;
		}

		.mind-layout {
			grid-template-columns: 1fr;
			min-height: 0;
			overflow: visible;
		}

		.hero-card {
			grid-template-columns: auto minmax(0, 1fr);
			grid-template-rows: auto auto;
		}

		.hero-mark {
			width: 3.4rem;
			height: 3.4rem;
		}

		.hero-status-grid {
			grid-column: 1 / -1;
			grid-template-columns: repeat(3, minmax(0, 1fr));
		}

		.goals-panel,
		.side-stack {
			min-height: 18rem;
			max-height: min(32rem, 58vh);
			overflow-y: auto;
		}
	}

	@media (max-width: 760px) {
		.mind-page {
			height: auto;
			max-height: none;
			overflow: visible;
		}
	}

	@media (max-width: 560px) {
		.hero-card,
		.hero-status-grid {
			grid-template-columns: 1fr;
		}

		.hero-status-grid {
			grid-column: auto;
		}
	}

	@container (max-width: 34rem) {
		.overview-grid,
		.hero-card,
		.hero-status-grid {
			grid-template-columns: 1fr;
		}

		.focus-card {
			grid-column: auto;
		}

		.hero-status-grid {
			grid-column: auto;
		}
	}
</style>
