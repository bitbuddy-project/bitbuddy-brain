<script lang="ts">
	import { onMount } from 'svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import Skeleton from '$lib/components/Skeleton.svelte';
	import ListChecksIcon from 'phosphor-svelte/lib/ListChecksIcon';
	import PlusIcon from 'phosphor-svelte/lib/PlusIcon';
	import CheckCircleIcon from 'phosphor-svelte/lib/CheckCircleIcon';
	import ArrowCounterClockwiseIcon from 'phosphor-svelte/lib/ArrowCounterClockwiseIcon';
	import TrashIcon from 'phosphor-svelte/lib/TrashIcon';
	import BellIcon from 'phosphor-svelte/lib/BellIcon';
	import {
		completeTask,
		createTask,
		deleteTask,
		getTasks,
		updateTask,
		type Task,
		type TaskStatus
	} from '$lib/api/bitbuddy';

	type Filter = 'open' | 'done' | 'all';
	const FILTERS: Filter[] = ['open', 'done', 'all'];

	let filter = $state<Filter>('open');
	let tasks = $state<Task[]>([]);
	let loading = $state(true);
	let error = $state('');

	// Quick-add form
	let newTitle = $state('');
	let newDate = $state('');
	let newTime = $state('');
	let newPriority = $state(3);
	let saving = $state(false);
	let formError = $state('');

	onMount(() => {
		void refresh();
	});

	async function refresh() {
		loading = true;
		error = '';
		try {
			tasks = await getTasks({ status: filter });
		} catch (err) {
			error = err instanceof Error ? err.message : 'Could not load tasks.';
		} finally {
			loading = false;
		}
	}

	function setFilter(next: Filter) {
		if (filter === next) return;
		filter = next;
		void refresh();
	}

	function toIso(date: string, time: string): string | null {
		if (!date) return null;
		const local = new Date(`${date}T${time || '09:00'}`);
		if (Number.isNaN(local.getTime())) return null;
		return local.toISOString();
	}

	async function addTask(event: SubmitEvent) {
		event.preventDefault();
		formError = '';
		const title = newTitle.trim();
		if (!title) {
			formError = 'Give the task a title.';
			return;
		}
		if (newTime && !newDate) {
			formError = 'Pick a date for the reminder time.';
			return;
		}
		saving = true;
		try {
			await createTask({
				title,
				remind_at: toIso(newDate, newTime),
				priority: newPriority
			});
			newTitle = '';
			newDate = '';
			newTime = '';
			newPriority = 3;
			if (filter === 'done') filter = 'open';
			await refresh();
		} catch (err) {
			formError = err instanceof Error ? err.message : 'Could not add task.';
		} finally {
			saving = false;
		}
	}

	async function toggleDone(task: Task) {
		try {
			if (task.status === 'done') {
				await updateTask(task.id, { status: 'open' as TaskStatus });
			} else {
				await completeTask(task.id);
			}
			await refresh();
		} catch (err) {
			error = err instanceof Error ? err.message : 'Could not update task.';
		}
	}

	async function removeTask(task: Task) {
		try {
			await deleteTask(task.id);
			tasks = tasks.filter((item) => item.id !== task.id);
		} catch (err) {
			error = err instanceof Error ? err.message : 'Could not delete task.';
		}
	}

	function whenLabel(task: Task): string {
		const stamp = task.remind_at ?? task.due_at;
		if (!stamp) return '';
		const date = new Date(stamp);
		if (Number.isNaN(date.getTime())) return stamp;
		return date.toLocaleString(undefined, {
			weekday: 'short',
			month: 'short',
			day: 'numeric',
			hour: 'numeric',
			minute: '2-digit'
		});
	}

	function isOverdue(task: Task): boolean {
		if (task.status !== 'open' || !task.remind_at) return false;
		return new Date(task.remind_at).getTime() < Date.now();
	}
</script>

<div class="tasks-page">
	<PageHeader
		icon={ListChecksIcon}
		eyebrow="Everyday"
		title="Tasks & reminders"
		subtitle="Things you asked me to remember. I'll nudge you when a reminder comes due."
	/>

	<section class="panel">
		<form class="quick-add" onsubmit={addTask}>
			<input
				class="title-input"
				type="text"
				placeholder="Add a task — e.g. Call the dentist"
				bind:value={newTitle}
				maxlength={300}
			/>
			<div class="when-fields">
				<input type="date" bind:value={newDate} aria-label="Reminder date" />
				<input type="time" bind:value={newTime} aria-label="Reminder time" />
				<select bind:value={newPriority} aria-label="Priority">
					<option value={1}>Low</option>
					<option value={3}>Normal</option>
					<option value={4}>High</option>
					<option value={5}>Urgent</option>
				</select>
				<button type="submit" class="add-btn" disabled={saving}>
					<PlusIcon size={16} weight="bold" />
					<span>{saving ? 'Adding…' : 'Add'}</span>
				</button>
			</div>
		</form>
		{#if formError}<p class="form-error">{formError}</p>{/if}

		<div class="filters">
			{#each FILTERS as option}
				<button class="filter" class:active={filter === option} onclick={() => setFilter(option)}>
					{option === 'all' ? 'All' : option === 'open' ? 'Open' : 'Done'}
				</button>
			{/each}
		</div>

		{#if loading}
			<div class="list">
				{#each Array(3) as _}<Skeleton height="3.4rem" />{/each}
			</div>
		{:else if error}
			<p class="empty error">{error}</p>
		{:else if tasks.length === 0}
			<p class="empty">{filter === 'done' ? 'Nothing completed yet.' : 'No tasks — add one above.'}</p>
		{:else}
			<ul class="list">
				{#each tasks as task (task.id)}
					<li class="task" class:done={task.status === 'done'} class:overdue={isOverdue(task)}>
						<button
							class="check"
							aria-label={task.status === 'done' ? 'Reopen task' : 'Mark done'}
							title={task.status === 'done' ? 'Reopen' : 'Mark done'}
							onclick={() => toggleDone(task)}
						>
							{#if task.status === 'done'}
								<ArrowCounterClockwiseIcon size={18} />
							{:else}
								<CheckCircleIcon size={20} weight="regular" />
							{/if}
						</button>
						<div class="task-body">
							<span class="task-title">{task.title}</span>
							<div class="task-meta">
								{#if task.priority >= 4}<span class="pill priority">P{task.priority}</span>{/if}
								{#if whenLabel(task)}
									<span class="pill when"><BellIcon size={12} weight="fill" />{whenLabel(task)}</span>
								{/if}
								{#if task.notes}<span class="notes">{task.notes}</span>{/if}
							</div>
						</div>
						<button class="delete" aria-label="Delete task" title="Delete" onclick={() => removeTask(task)}>
							<TrashIcon size={16} />
						</button>
					</li>
				{/each}
			</ul>
		{/if}
	</section>
</div>

<style>
	.tasks-page {
		display: flex;
		flex-direction: column;
		gap: 0.85rem;
		min-height: 0;
		--page-accent: var(--accent);
	}

	.panel {
		margin: 0 0.7rem;
		padding: 1.1rem 1.25rem 1.35rem;
		border-radius: 1.35rem;
		background: color-mix(in srgb, var(--panel) 88%, #01050d);
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08), var(--shadow-chat);
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.quick-add {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
	}

	.title-input,
	.when-fields input,
	.when-fields select {
		padding: 0.6rem 0.75rem;
		border: 1px solid color-mix(in srgb, var(--bg-soft) 55%, var(--border));
		border-radius: 0.7rem;
		background: var(--surface-glass);
		color: var(--text);
		font-size: 0.9rem;
	}

	.title-input {
		width: 100%;
	}

	.title-input:focus,
	.when-fields input:focus,
	.when-fields select:focus {
		outline: none;
		border-color: color-mix(in srgb, var(--accent) 55%, var(--border));
	}

	.when-fields {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
		align-items: center;
	}

	.add-btn {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.6rem 1rem;
		margin-left: auto;
		border: 0;
		border-radius: 0.7rem;
		background: var(--accent);
		color: var(--on-accent);
		font-weight: 700;
		cursor: pointer;
	}

	.add-btn:disabled {
		opacity: 0.6;
		cursor: default;
	}

	.form-error {
		margin: 0;
		color: var(--danger);
		font-size: 0.82rem;
	}

	.filters {
		display: flex;
		gap: 0.4rem;
	}

	.filter {
		padding: 0.4rem 0.85rem;
		border: 1px solid transparent;
		border-radius: 999px;
		background: color-mix(in srgb, var(--surface-card) 60%, transparent);
		color: var(--text-muted);
		font-size: 0.82rem;
		font-weight: 650;
		cursor: pointer;
	}

	.filter.active {
		border-color: color-mix(in srgb, var(--accent) 30%, var(--border));
		background: color-mix(in srgb, var(--accent-soft) 70%, transparent);
		color: var(--accent-strong);
	}

	.list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.task {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.7rem 0.85rem;
		border: 1px solid color-mix(in srgb, var(--bg-soft) 50%, var(--border));
		border-radius: 0.85rem;
		background: color-mix(in srgb, var(--surface-glass) 55%, transparent);
	}

	.task.overdue {
		border-color: color-mix(in srgb, var(--danger) 45%, var(--border));
	}

	.task.done .task-title {
		text-decoration: line-through;
		color: var(--text-soft);
	}

	.check,
	.delete {
		display: grid;
		place-items: center;
		width: 2rem;
		height: 2rem;
		flex: 0 0 auto;
		border: 0;
		border-radius: 0.6rem;
		background: transparent;
		color: var(--text-muted);
		cursor: pointer;
	}

	.check:hover {
		color: var(--success);
		background: color-mix(in srgb, var(--success) 12%, transparent);
	}

	.delete:hover {
		color: var(--danger);
		background: color-mix(in srgb, var(--danger) 12%, transparent);
	}

	.task-body {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.task-title {
		font-weight: 600;
		font-size: 0.95rem;
	}

	.task-meta {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.4rem;
	}

	.pill {
		display: inline-flex;
		align-items: center;
		gap: 0.25rem;
		padding: 0.15rem 0.5rem;
		border-radius: 999px;
		font-size: 0.72rem;
		font-weight: 650;
	}

	.pill.when {
		background: color-mix(in srgb, var(--accent-soft) 70%, transparent);
		color: var(--accent-strong);
	}

	.task.overdue .pill.when {
		background: color-mix(in srgb, var(--danger) 16%, transparent);
		color: var(--danger);
	}

	.pill.priority {
		background: color-mix(in srgb, var(--warning) 18%, transparent);
		color: var(--warning);
	}

	.notes {
		color: var(--text-soft);
		font-size: 0.8rem;
	}

	.empty {
		margin: 1.5rem 0;
		text-align: center;
		color: var(--text-soft);
	}

	.empty.error {
		color: var(--danger);
	}
</style>
