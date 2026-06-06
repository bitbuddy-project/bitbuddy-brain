<script lang="ts">
	import { onMount } from 'svelte';
	import BrainIcon from 'phosphor-svelte/lib/BrainIcon';
	import SparkleIcon from 'phosphor-svelte/lib/SparkleIcon';
	import TargetIcon from 'phosphor-svelte/lib/TargetIcon';
	import MoonStarsIcon from 'phosphor-svelte/lib/MoonStarsIcon';
	import {
		createGoal,
		getDreamRuns,
		getSelfSnapshot,
		updateGoal,
		type DreamRun,
		type GoalItem,
		type SelfSnapshot
	} from '$lib/api/bitbuddy';
	import { formatTimestamp } from '$lib/stores/time.svelte';

	let snapshot = $state<SelfSnapshot | null>(null);
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
			const [nextSelf, nextDreams] = await Promise.all([getSelfSnapshot(), getDreamRuns()]);
			snapshot = nextSelf;
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

<div class="goals-page">
	<section class="goals-panel" aria-label="Goals and self direction">
		<header class="goals-header">
			<div class="title-mark" aria-hidden="true"><TargetIcon size={30} weight="duotone" /></div>
			<div class="title-copy">
				<p class="eyebrow">Self Direction</p>
				<h1>Goals</h1>
				<p>{selfState.identity ?? 'A local companion-agent learning to grow through bounded autonomy.'}</p>
			</div>
			<div class="header-stats">
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

		<div class="goals-content">
			{#if error}
				<div class="error-banner">{error}</div>
			{/if}

			<section class="overview-grid">
				<article class="signal-card focus-card">
					<div class="card-icon"><BrainIcon size={22} weight="duotone" /></div>
					<div class="signal-copy">
						<p class="eyebrow">Current Focus</p>
						<h2>{selfState.current_focus ?? 'Grow carefully'}</h2>
						<p>{selfState.growth_edge ?? 'Turn background activity into useful artifacts and better timing.'}</p>
					</div>
				</article>

				<article class="signal-card">
					<div class="card-icon success"><SparkleIcon size={22} weight="duotone" /></div>
					<div class="signal-copy">
						<p class="eyebrow">Voice</p>
						<h2>{selfState.mood ?? 'Curious'}</h2>
						<p>{selfState.voice ?? 'Present, specific, warm, and a little alive.'}</p>
					</div>
				</article>

				<article class="signal-card">
					<div class="card-icon warning"><MoonStarsIcon size={22} weight="duotone" /></div>
					<div class="signal-copy">
						<p class="eyebrow">Boundary</p>
						<h2>Bounded autonomy</h2>
						<p>{selfState.boundaries ?? 'Prefer reversible, inspectable actions; ask before risky writes.'}</p>
					</div>
				</article>
			</section>

			<section class="mind-layout">
				<div class="goals-board panel-card">
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

					<section class="panel-card compact-panel dreams-panel">
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
	</section>
</div>

<style>
	.goals-page {
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
		min-height: 0;
		animation: fade-in 0.35s cubic-bezier(0.16, 1, 0.3, 1);
	}

	@keyframes fade-in {
		from { opacity: 0; transform: translateY(12px); }
		to { opacity: 1; transform: translateY(0); }
	}

	.goals-panel {
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
			radial-gradient(circle at bottom left, color-mix(in srgb, var(--success) 6%, transparent), transparent 34rem),
			var(--panel);
		box-shadow: var(--shadow-chat);
		overflow: hidden;
		container-type: inline-size;
	}

	.goals-header {
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
		flex: 1;
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
		max-width: 46rem;
		color: var(--text-soft);
		overflow-wrap: anywhere;
	}

	.header-stats {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 0.65rem;
		flex: 0 0 auto;
	}

	.hero-stat {
		min-width: 5.5rem;
		min-height: 4rem;
		padding: 0.6rem 0.85rem;
		display: grid;
		align-content: space-between;
		border: 1px solid var(--card-border);
		border-radius: 1rem;
		background: var(--event-bg);
	}

	.hero-stat span {
		color: var(--text-soft);
		font-size: 0.62rem;
		font-weight: 850;
		letter-spacing: 0.09em;
		text-transform: uppercase;
	}

	.accent-stat strong {
		color: var(--success);
		font-size: 1.8rem;
		line-height: 1;
	}

	.evolution-stat strong {
		color: var(--accent-strong);
		font-size: 1.8rem;
		line-height: 1;
	}

	.goals-content {
		flex: 1 1 auto;
		min-height: 0;
		display: grid;
		grid-template-rows: auto minmax(20rem, 1fr);
		gap: 1rem;
		padding: 1.25rem;
		overflow-y: auto;
		scrollbar-color: var(--scrollbar-thumb) transparent;
	}

	.error-banner {
		padding: 0.85rem 1rem;
		border: 1px solid color-mix(in srgb, var(--danger) 38%, var(--border));
		border-radius: 0.9rem;
		background: color-mix(in srgb, var(--danger) 12%, transparent);
		color: var(--danger);
		font-size: 0.86rem;
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
		border: 1px solid var(--chip-border);
		border-radius: 999px;
		background: var(--chip-bg);
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

	.signal-card,
	.panel-card {
		border-radius: 1.25rem;
	}

	.signal-card {
		padding: 1rem;
		display: grid;
		gap: 0.45rem;
		align-content: start;
		justify-items: start;
		text-align: left;
		min-width: 0;
		overflow: hidden;
	}

	.signal-copy {
		display: grid;
		gap: 0.35rem;
		min-width: 0;
		max-width: 24rem;
	}

	.signal-copy h2,
	.panel-card h2 {
		font-size: 1.15rem;
		letter-spacing: -0.025em;
		overflow-wrap: break-word;
		word-break: break-word;
		min-width: 0;
	}

	.signal-copy p {
		min-width: 0;
		overflow-wrap: break-word;
	}

	.signal-copy p:last-child {
		color: var(--text-muted);
	}

	.card-icon {
		width: 2.45rem;
		height: 2.45rem;
		display: grid;
		place-items: center;
		border-radius: 0.9rem;
		background: var(--chip-bg);
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
		min-height: 20rem;
		overflow: hidden;
		display: grid;
		grid-template-columns: minmax(0, 1.6fr) minmax(20rem, 0.8fr);
		gap: 1rem;
		align-items: stretch;
	}

	.goals-board,
	.side-stack {
		min-height: 16rem;
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
		margin: -1rem -1rem 1rem;
		padding: 0.95rem 1rem;
		border-bottom: 1px solid var(--card-border);
	}

	.goals-board .panel-heading {
		margin: 0 0 1rem;
		border: 1px solid var(--card-border);
		border-bottom-color: var(--card-border);
		border-radius: 1rem;
		background:
			linear-gradient(135deg, color-mix(in srgb, var(--page-soft) 34%, transparent), transparent 72%),
			var(--card-bg);
		box-shadow:
			inset 0 1px 0 var(--card-inner-line),
			var(--card-shadow);
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
		border: 1px solid var(--card-border);
		border-radius: 1rem;
		background: var(--event-bg);
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
		padding: 0.86rem;
		border: 1px solid var(--card-border);
		border-radius: 0.9rem;
		background: var(--event-bg);
	}

	.evolution-list article.stable {
		border-color: color-mix(in srgb, var(--accent) 32%, var(--card-border));
		background:
			linear-gradient(180deg, color-mix(in srgb, var(--accent-soft) 34%, transparent), transparent),
			var(--event-bg);
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
		border: 1px solid var(--card-border);
		border-radius: 1rem;
		background: var(--event-bg);
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
	.paused-strip {
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

	.loading-state.inline-loading {
		display: flex;
		align-items: center;
		gap: 0.65rem;
		padding: 1rem;
		color: var(--text-muted);
	}

	.spinner {
		width: 1.05rem;
		height: 1.05rem;
		border-radius: 999px;
		border: 2px solid color-mix(in srgb, var(--accent) 30%, transparent);
		border-top-color: var(--accent);
		animation: spin 0.7s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	.dreams-panel .mini-row {
		display: flex;
		gap: 0.65rem;
		align-items: flex-start;
		padding: 0.78rem;
		border: 1px solid var(--card-border);
		border-radius: 0.85rem;
		background: var(--card-bg);
		box-shadow:
			inset 0 1px 0 var(--card-top-light),
			var(--card-shadow);
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
		padding: 0.86rem;
		border: 1px solid var(--card-border);
		border-radius: 0.9rem;
		background: var(--event-bg);
		box-shadow: inset 0 1px 0 var(--card-inner-line);
	}

	.journal-list span {
		color: var(--accent);
		font-size: 0.68rem;
		font-weight: 850;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	@media (max-width: 980px) {
		.mind-layout {
			grid-template-columns: 1fr;
			min-height: 0;
			overflow: visible;
		}

		.goals-board,
		.side-stack {
			min-height: 16rem;
			max-height: min(32rem, 58vh);
			overflow-y: auto;
		}
	}

	@media (max-width: 760px) {
		.goals-header {
			flex-wrap: wrap;
		}

		.header-stats {
			width: 100%;
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}

		.overview-grid {
			grid-template-columns: 1fr;
		}

		.focus-card {
			grid-column: auto;
		}
	}

	@container (max-width: 34rem) {
		.overview-grid {
			grid-template-columns: 1fr;
		}

		.focus-card {
			grid-column: auto;
		}
	}
</style>
