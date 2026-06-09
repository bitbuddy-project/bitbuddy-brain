<script lang="ts">
	import { onMount } from 'svelte';
	import Skeleton from '$lib/components/Skeleton.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import CalendarBlankIcon from 'phosphor-svelte/lib/CalendarBlankIcon';
	import CaretLeftIcon from 'phosphor-svelte/lib/CaretLeftIcon';
	import CaretRightIcon from 'phosphor-svelte/lib/CaretRightIcon';
	import ClockIcon from 'phosphor-svelte/lib/ClockIcon';
	import MapPinIcon from 'phosphor-svelte/lib/MapPinIcon';
	import PlusIcon from 'phosphor-svelte/lib/PlusIcon';
	import TrashIcon from 'phosphor-svelte/lib/TrashIcon';
	import WarningCircleIcon from 'phosphor-svelte/lib/WarningCircleIcon';
	import Overlay from '$lib/components/ui/Overlay.svelte';
	import Checkbox from '$lib/components/ui/Checkbox.svelte';
	import DatePickerField from '$lib/components/ui/DatePickerField.svelte';
	import {
		eventsForDay,
		isToday,
		monthGrid,
		monthNav,
		toISODate,
		weekDays
	} from '$lib/utils/calendar-grid';
	import {
		createCalendarEvent,
		deleteCalendarEvent,
		getCalendarEvents,
		getCalendarPermissions,
		getConfig,
		updateCalendarConfig,
		updateCalendarEvent,
		type CalendarEvent,
		type CalendarPermissionState,
		type CalendarScope
	} from '$lib/api/bitbuddy';

	type ViewMode = 'month' | 'week' | 'agenda';
	const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
	const VIEWS: ViewMode[] = ['month', 'week', 'agenda'];

	let view = $state<ViewMode>('month');
	let cursor = $state(new Date());
	let enabled = $state(false);
	let timezone = $state('UTC');
	let events = $state<CalendarEvent[]>([]);
	let permissions = $state<Record<CalendarScope, CalendarPermissionState> | null>(null);
	let loading = $state(true);
	let error = $state('');

	type EditorState = {
		open: boolean;
		mode: 'create' | 'edit';
		id: string;
		title: string;
		allDay: boolean;
		startDate: string;
		startTime: string;
		endDate: string;
		endTime: string;
		location: string;
		description: string;
		conflicts: CalendarEvent[];
		confirmDelete: boolean;
		saving: boolean;
		formError: string;
	};
	let editor = $state<EditorState>(blankEditor());

	const monthCells = $derived(monthGrid(cursor.getMonth(), cursor.getFullYear()));
	const weekCells = $derived(weekDays(cursor));
	const periodLabel = $derived(buildPeriodLabel());
	const agendaItems = $derived(
		[...events].sort((a, b) => a.start_at.localeCompare(b.start_at))
	);

	onMount(() => {
		void refresh();
	});

	function blankEditor(): EditorState {
		return {
			open: false,
			mode: 'create',
			id: '',
			title: '',
			allDay: false,
			startDate: '',
			startTime: '09:00',
			endDate: '',
			endTime: '10:00',
			location: '',
			description: '',
			conflicts: [],
			confirmDelete: false,
			saving: false,
			formError: ''
		};
	}

	function windowBounds(): { start: string; end: string } {
		if (view === 'month') {
			return { start: `${toISODate(monthCells[0])}T00:00`, end: `${toISODate(monthCells[41])}T23:59` };
		}
		if (view === 'week') {
			return { start: `${toISODate(weekCells[0])}T00:00`, end: `${toISODate(weekCells[6])}T23:59` };
		}
		const start = new Date();
		const end = new Date();
		end.setDate(end.getDate() + 30);
		return { start: `${toISODate(start)}T00:00`, end: `${toISODate(end)}T23:59` };
	}

	function buildPeriodLabel(): string {
		if (view === 'month') {
			return cursor.toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
		}
		if (view === 'week') {
			const a = weekCells[0];
			const b = weekCells[6];
			const fmt = (d: Date) => d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
			return `${fmt(a)} – ${fmt(b)}, ${b.getFullYear()}`;
		}
		return 'Next 30 days';
	}

	async function refresh() {
		try {
			loading = events.length === 0;
			const bounds = windowBounds();
			const [config, response] = await Promise.all([getConfig(), getCalendarEvents(bounds)]);
			enabled = Boolean(config.calendar?.enabled);
			timezone = response.timezone || 'UTC';
			events = response.events;
			try {
				permissions = (await getCalendarPermissions()).permissions;
			} catch {
				permissions = null;
			}
			error = '';
		} catch (e: any) {
			error = e.message ?? 'Could not load calendar.';
		} finally {
			loading = false;
		}
	}

	async function setView(next: ViewMode) {
		view = next;
		await refresh();
	}

	async function navigate(direction: 'prev' | 'next') {
		if (view === 'month') {
			const next = monthNav(direction, cursor.getMonth(), cursor.getFullYear());
			cursor = new Date(next.year, next.month, 1);
		} else if (view === 'week') {
			const next = new Date(cursor);
			next.setDate(cursor.getDate() + (direction === 'next' ? 7 : -7));
			cursor = next;
		}
		await refresh();
	}

	async function goToday() {
		cursor = new Date();
		await refresh();
	}

	async function enableCalendar() {
		try {
			await updateCalendarConfig({ enabled: true });
			await refresh();
		} catch (e: any) {
			error = e.message ?? 'Could not enable calendar.';
		}
	}

	function dayEvents(day: Date): CalendarEvent[] {
		return eventsForDay(events, day, timezone);
	}

	function localParts(iso: string): { date: string; time: string } {
		try {
			const dt = new Date(iso);
			const date = new Intl.DateTimeFormat('en-CA', {
				timeZone: timezone,
				year: 'numeric',
				month: '2-digit',
				day: '2-digit'
			}).format(dt);
			const time = new Intl.DateTimeFormat('en-GB', {
				timeZone: timezone,
				hour: '2-digit',
				minute: '2-digit',
				hour12: false
			}).format(dt);
			return { date, time };
		} catch {
			return { date: iso.slice(0, 10), time: '09:00' };
		}
	}

	function eventTime(event: CalendarEvent): string {
		if (event.all_day) return 'All day';
		const fmt = (iso: string) =>
			new Intl.DateTimeFormat(undefined, { timeZone: timezone, hour: 'numeric', minute: '2-digit' }).format(new Date(iso));
		return `${fmt(event.start_at)} – ${fmt(event.end_at)}`;
	}

	function dayLabel(iso: string): string {
		return new Intl.DateTimeFormat(undefined, { timeZone: timezone, weekday: 'short', month: 'short', day: 'numeric' }).format(new Date(iso));
	}

	function openCreate(day?: Date) {
		const base = day ?? new Date();
		const dateStr = toISODate(base);
		editor = {
			...blankEditor(),
			open: true,
			mode: 'create',
			startDate: dateStr,
			endDate: dateStr
		};
	}

	function openEdit(event: CalendarEvent) {
		if (event.source === 'holiday') return;
		const start = localParts(event.start_at);
		const end = localParts(event.end_at);
		editor = {
			open: true,
			mode: 'edit',
			id: event.id,
			title: event.title,
			allDay: event.all_day,
			startDate: start.date,
			startTime: start.time,
			endDate: end.date,
			endTime: end.time,
			location: event.location,
			description: event.description,
			conflicts: [],
			confirmDelete: false,
			saving: false,
			formError: ''
		};
	}

	function closeEditor() {
		editor = { ...editor, open: false };
	}

	async function saveEditor() {
		if (!editor.title.trim()) {
			editor.formError = 'A title is required.';
			return;
		}
		const start = editor.allDay ? `${editor.startDate}T00:00` : `${editor.startDate}T${editor.startTime}`;
		const end = editor.allDay ? `${editor.startDate}T23:59` : `${editor.endDate}T${editor.endTime}`;
		const payload = {
			title: editor.title.trim(),
			start,
			end,
			location: editor.location.trim(),
			description: editor.description.trim(),
			all_day: editor.allDay
		};
		editor.saving = true;
		editor.formError = '';
		try {
			const result =
				editor.mode === 'create'
					? await createCalendarEvent(payload)
					: await updateCalendarEvent(editor.id, payload);
			if (result.conflicts?.length) {
				editor.conflicts = result.conflicts;
				editor.saving = false;
				await refresh();
				return;
			}
			editor.open = false;
			await refresh();
		} catch (e: any) {
			editor.formError = e.message ?? 'Could not save event.';
		} finally {
			editor.saving = false;
		}
	}

	async function removeEvent() {
		try {
			await deleteCalendarEvent(editor.id);
			editor.open = false;
			await refresh();
		} catch (e: any) {
			editor.formError = e.message ?? 'Could not delete event.';
		}
	}

	let grantedRead = $derived(permissions ? permissions.read === 'granted' : true);
</script>

<svelte:head>
	<title>BitBuddy Calendar</title>
</svelte:head>

<div class="calendar-page">
	<PageHeader icon={CalendarBlankIcon} eyebrow="Schedule" title="Calendar" subtitle="Your local-first schedule — plan events and stay ahead of reminders.">
		{#snippet action()}
			<div class="header-controls">
				<div class="period-nav">
					<button class="nav-btn" type="button" onclick={goToday}>Today</button>
					<div class="period-stepper">
						<button class="nav-icon" class:invisible={view === 'agenda'} type="button" aria-label="Previous" tabindex={view === 'agenda' ? -1 : 0} onclick={() => navigate('prev')}><CaretLeftIcon size={16} weight="bold" /></button>
						<span class="period-label">{periodLabel}</span>
						<button class="nav-icon" class:invisible={view === 'agenda'} type="button" aria-label="Next" tabindex={view === 'agenda' ? -1 : 0} onclick={() => navigate('next')}><CaretRightIcon size={16} weight="bold" /></button>
					</div>
				</div>

				<div class="view-toggle" role="tablist" aria-label="View">
					{#each VIEWS as mode}
						<button type="button" role="tab" class:active={view === mode} aria-selected={view === mode} onclick={() => setView(mode)}>
							{mode[0].toUpperCase() + mode.slice(1)}
						</button>
					{/each}
				</div>

				<button class="add-btn" type="button" onclick={() => openCreate()}>
					<PlusIcon size={16} weight="bold" /> <span class="add-btn-label">Event</span>
				</button>
			</div>
		{/snippet}
	</PageHeader>
	<section class="calendar-panel" aria-label="Calendar">
		<div class="calendar-content">
			{#if error}
				<div class="error-banner">{error}</div>
			{/if}

			{#if !enabled}
				<div class="notice-card">
					<WarningCircleIcon size={22} weight="duotone" />
					<div>
						<strong>Calendar is off</strong>
						<p>Enable it so BitBuddy can read your schedule and send time-based reminders.</p>
					</div>
					<button type="button" onclick={enableCalendar}>Enable calendar</button>
				</div>
			{/if}

			{#if permissions && !grantedRead}
				<div class="notice-card subtle">
					<div>
						<strong>BitBuddy can't read your calendar yet</strong>
						<p>You can still manage events here. Grant the <em>read</em> scope on the Permissions page to let BitBuddy use it.</p>
					</div>
					<a class="link-button" href="/permissions">Open Permissions</a>
				</div>
			{/if}

			{#if loading}
				<div class="loading-state"><Skeleton variant="row" count={5} /></div>
			{:else if view === 'month'}
				<div class="month-grid">
					{#each WEEKDAYS as wd}<div class="weekday-head">{wd}</div>{/each}
					{#each monthCells as day (toISODate(day))}
						{@const inMonth = day.getMonth() === cursor.getMonth()}
						{@const list = dayEvents(day)}
						<div
							class="month-cell"
							class:muted={!inMonth}
							class:today={isToday(day)}
							role="button"
							tabindex="0"
							aria-label={`${day.toLocaleDateString(undefined, { month: 'long', day: 'numeric' })}, add event`}
							onclick={() => openCreate(day)}
							onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openCreate(day); } }}
						>
							<span class="cell-date">{day.getDate()}</span>
							<span class="cell-events">
								{#each list.slice(0, 3) as event (event.id)}
									<button
										class="chip"
										class:holiday={event.source === 'holiday'}
										type="button"
										title={event.title}
										onclick={(e) => { e.stopPropagation(); openEdit(event); }}
									>
										{#if !event.all_day}<span class="chip-dot"></span>{/if}
										<span class="chip-text">{event.title}</span>
									</button>
								{/each}
								{#if list.length > 3}<span class="chip-more">+{list.length - 3} more</span>{/if}
							</span>
						</div>
					{/each}
				</div>
			{:else if view === 'week'}
				<div class="week-grid">
					{#each weekCells as day (toISODate(day))}
						{@const list = dayEvents(day)}
						<div class="week-col" class:today={isToday(day)}>
							<button class="week-col-head" type="button" onclick={() => openCreate(day)}>
								<small>{day.toLocaleDateString(undefined, { weekday: 'short' })}</small>
								<strong>{day.getDate()}</strong>
							</button>
							<div class="week-col-body">
								{#each list as event (event.id)}
									<button class="chip block" class:holiday={event.source === 'holiday'} type="button" onclick={() => openEdit(event)}>
										<span class="chip-text">{event.title}</span>
										{#if !event.all_day}<small>{eventTime(event)}</small>{/if}
									</button>
								{:else}
									<span class="week-empty">—</span>
								{/each}
							</div>
						</div>
					{/each}
				</div>
			{:else}
				<div class="agenda">
					{#each agendaItems as event (event.id)}
						<button class="agenda-row" class:holiday={event.source === 'holiday'} type="button" onclick={() => openEdit(event)}>
							<div class="agenda-day">{dayLabel(event.start_at)}</div>
							<div class="agenda-main">
								<h3>{event.title}{#if event.source === 'holiday'}<span class="holiday-tag">Holiday</span>{/if}</h3>
								<div class="agenda-meta">
									<span><ClockIcon size={14} weight="bold" /> {eventTime(event)}</span>
									{#if event.location}<span><MapPinIcon size={14} weight="bold" /> {event.location}</span>{/if}
								</div>
								{#if event.description}<p class="agenda-desc">{event.description}</p>{/if}
							</div>
						</button>
					{:else}
						<div class="empty-state"><CalendarBlankIcon size={24} /> Nothing scheduled in the next 30 days.</div>
					{/each}
				</div>
			{/if}
		</div>
	</section>
</div>

<Overlay open={editor.open} label="Event editor" wide onClose={closeEditor}>
	<form class="event-form" onsubmit={(e) => { e.preventDefault(); void saveEditor(); }}>
		<div class="form-head">
			<h2>{editor.mode === 'create' ? 'New event' : 'Edit event'}</h2>
		</div>

		{#if editor.formError}<div class="form-error">{editor.formError}</div>{/if}
		{#if editor.conflicts.length}
			<div class="form-warn">
				<WarningCircleIcon size={16} weight="fill" /> Saved, but this overlaps with {editor.conflicts.map((c) => `'${c.title}'`).join(', ')}.
			</div>
		{/if}

		<label class="field">
			<span>Title</span>
			<input bind:value={editor.title} placeholder="What's happening?" />
		</label>

		<Checkbox bind:checked={editor.allDay} label="All day" />

		<div class="field-row">
			<label class="field"><span>Start date</span><DatePickerField label="Start date" bind:value={editor.startDate} /></label>
			{#if !editor.allDay}
				<label class="field narrow"><span>Start time</span><input type="time" bind:value={editor.startTime} /></label>
			{/if}
		</div>

		{#if !editor.allDay}
			<div class="field-row">
				<label class="field"><span>End date</span><DatePickerField label="End date" bind:value={editor.endDate} /></label>
				<label class="field narrow"><span>End time</span><input type="time" bind:value={editor.endTime} /></label>
			</div>
		{/if}

		<label class="field">
			<span>Location <small>optional</small></span>
			<input bind:value={editor.location} placeholder="Where?" />
		</label>

		<label class="field">
			<span>Description <small>optional — helps BitBuddy understand the event</small></span>
			<textarea bind:value={editor.description} rows="3" placeholder="Notes, agenda, context…"></textarea>
		</label>

		<div class="form-actions">
			{#if editor.mode === 'edit'}
				{#if editor.confirmDelete}
					<button type="button" class="danger-confirm" onclick={removeEvent}><TrashIcon size={15} weight="bold" /> Confirm delete</button>
					<button type="button" class="ghost" onclick={() => (editor.confirmDelete = false)}>Keep</button>
				{:else}
					<button type="button" class="ghost danger" onclick={() => (editor.confirmDelete = true)}><TrashIcon size={15} weight="bold" /> Delete</button>
				{/if}
			{/if}
			<span class="spacer"></span>
			<button type="button" class="ghost" onclick={closeEditor} disabled={editor.saving}>Cancel</button>
			<button type="submit" disabled={editor.saving || !editor.title.trim()}>{editor.saving ? 'Saving…' : 'Save'}</button>
		</div>
	</form>
</Overlay>

<style>
	.calendar-page {
		--page-accent: var(--accent);
		--page-soft: color-mix(in srgb, var(--accent-soft) 72%, transparent);
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

	.calendar-panel {
		width: 100%;
		flex: 1 1 auto;
		min-height: 0;
		display: flex;
		flex-direction: column;
	}

	.header-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 0.6rem; }

	.period-nav { display: inline-flex; align-items: center; gap: 0.5rem; }
	.period-stepper { display: inline-flex; align-items: center; gap: 0.4rem; }
	.period-label { min-width: 6.5rem; text-align: center; font-weight: 800; font-size: 0.92rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.nav-icon.invisible { visibility: hidden; }

	.nav-btn {
		padding: 0.45rem 0.7rem;
		border: 1px solid var(--border);
		border-radius: 0.7rem;
		background: var(--surface-glass);
		color: var(--text-muted);
		font-weight: 750;
		font-size: 0.82rem;
		cursor: pointer;
	}

	.nav-icon {
		display: grid;
		place-items: center;
		width: 2rem;
		height: 2rem;
		border: 1px solid var(--border);
		border-radius: 0.65rem;
		background: var(--surface-glass);
		color: var(--text-muted);
		cursor: pointer;
	}

	.nav-btn:hover, .nav-icon:hover { color: var(--text); border-color: color-mix(in srgb, var(--accent) 40%, var(--border)); }

	.view-toggle { display: inline-flex; gap: 0.25rem; padding: 0.25rem; border: 1px solid var(--border); border-radius: 0.8rem; background: var(--surface-inset); }
	.view-toggle button { padding: 0.42rem 0.7rem; border-radius: 0.6rem; background: transparent; color: var(--text-muted); font-weight: 750; font-size: 0.8rem; cursor: pointer; }
	.view-toggle button.active { background: var(--accent); color: var(--on-accent); }

	.add-btn {
		display: inline-flex; align-items: center; gap: 0.4rem;
		padding: 0.5rem 0.85rem;
		border: 0; border-radius: 0.75rem;
		background: #2563eb;
		color: #fff; font-weight: 800; cursor: pointer;
	}

	.calendar-content {
		flex: 1 1 auto;
		min-height: 0;
		display: flex;
		flex-direction: column;
		gap: 0.9rem;
		padding: 1rem;
		overflow-y: auto;
		scrollbar-color: var(--scrollbar-thumb) transparent;
	}

	.error-banner {
		padding: 0.8rem 1rem;
		border: 1px solid color-mix(in srgb, var(--danger) 38%, var(--border));
		border-radius: 0.85rem;
		background: color-mix(in srgb, var(--danger) 12%, transparent);
		color: var(--danger);
		font-size: 0.85rem;
	}

	.notice-card {
		display: flex; align-items: center; gap: 0.85rem;
		padding: 0.9rem 1.1rem;
		border: 1px solid color-mix(in srgb, var(--warning) 32%, var(--border));
		border-radius: 0.95rem;
		background: color-mix(in srgb, var(--warning) 9%, transparent);
	}
	.notice-card.subtle { border-color: var(--card-border); background: var(--event-bg); }
	.notice-card strong { display: block; }
	.notice-card p { color: var(--text-soft); font-size: 0.83rem; margin-top: 0.15rem; }
	.notice-card > div { flex: 1; min-width: 0; }
	.notice-card button {
		padding: 0.5rem 0.8rem; border: 0; border-radius: 0.7rem;
		background: var(--accent); color: var(--on-accent); font-weight: 800; cursor: pointer;
	}
	.link-button {
		padding: 0.5rem 0.8rem; border: 1px solid var(--border); border-radius: 0.7rem;
		background: var(--surface-glass); color: var(--accent-strong); font-weight: 800; font-size: 0.82rem; text-decoration: none; white-space: nowrap;
	}

	/* Month grid */
	.month-grid {
		display: grid;
		grid-template-columns: repeat(7, minmax(0, 1fr));
		gap: 1px;
		background: var(--card-border);
		border: 1px solid var(--card-border);
		border-radius: 0.9rem;
		overflow: hidden;
		flex: 1 1 auto;
		min-height: 28rem;
		grid-auto-rows: minmax(0, 1fr);
		grid-template-rows: auto repeat(6, minmax(4.5rem, 1fr));
	}

	.weekday-head {
		background: var(--panel-header);
		padding: 0.5rem;
		text-align: center;
		font-size: 0.66rem;
		font-weight: 800;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--text-soft);
	}

	.month-cell {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		align-items: stretch;
		padding: 0.35rem;
		border: 0;
		background: var(--panel);
		color: var(--text);
		cursor: pointer;
		text-align: left;
		min-width: 0;
		overflow: hidden;
	}
	.month-cell:hover { background: color-mix(in srgb, var(--accent) 6%, var(--panel)); }
	.month-cell.muted { background: color-mix(in srgb, var(--panel-shell) 70%, transparent); color: var(--text-soft); }
	.month-cell.today .cell-date {
		background: var(--accent); color: var(--on-accent);
		border-radius: 999px;
	}
	.cell-date { align-self: flex-end; min-width: 1.5rem; height: 1.5rem; display: grid; place-items: center; font-size: 0.8rem; font-weight: 750; }
	.cell-events { display: grid; gap: 0.18rem; min-width: 0; }

	.chip {
		display: inline-flex; align-items: center; gap: 0.3rem;
		padding: 0.16rem 0.36rem;
		border: 0; border-radius: 0.4rem;
		background: color-mix(in srgb, var(--accent) 16%, transparent);
		color: var(--text);
		font: inherit; font-size: 0.72rem; font-weight: 650;
		cursor: pointer; min-width: 0; width: 100%;
	}
	.chip .chip-text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.chip-dot { width: 0.4rem; height: 0.4rem; border-radius: 999px; background: var(--accent); flex: 0 0 auto; }
	.chip.holiday { background: color-mix(in srgb, var(--success) 16%, transparent); color: color-mix(in srgb, var(--success) 86%, var(--text)); }
	.chip-more { font-size: 0.68rem; color: var(--text-soft); padding-left: 0.2rem; }

	/* Week grid */
	.week-grid {
		display: grid;
		grid-template-columns: repeat(7, minmax(0, 1fr));
		gap: 1px;
		background: var(--card-border);
		border: 1px solid var(--card-border);
		border-radius: 0.9rem;
		overflow: hidden;
		flex: 1 1 auto;
		min-height: 24rem;
	}
	.week-col { display: flex; flex-direction: column; background: var(--panel); min-width: 0; }
	.week-col.today { background: color-mix(in srgb, var(--accent) 6%, var(--panel)); }
	.week-col-head {
		display: grid; gap: 0.05rem; place-items: center;
		padding: 0.5rem; border: 0; border-bottom: 1px solid var(--card-border);
		background: var(--panel-header); color: var(--text); cursor: pointer;
	}
	.week-col-head small { font-size: 0.62rem; font-weight: 800; text-transform: uppercase; color: var(--text-soft); }
	.week-col-head strong { font-size: 1.05rem; }
	.week-col.today .week-col-head strong { color: var(--accent-strong); }
	.week-col-body { display: grid; gap: 0.25rem; padding: 0.35rem; align-content: start; min-height: 0; overflow-y: auto; }
	.chip.block { width: 100%; flex-direction: column; align-items: flex-start; gap: 0.1rem; padding: 0.3rem 0.4rem; }
	.chip.block small { font-size: 0.66rem; color: var(--text-soft); font-weight: 600; }
	.week-empty { color: var(--text-soft); text-align: center; font-size: 0.8rem; opacity: 0.5; padding: 0.4rem; }

	/* Agenda */
	.agenda { display: grid; gap: 0.6rem; }
	.agenda-row {
		display: grid; grid-template-columns: 7rem 1fr; gap: 0.85rem; align-items: start;
		padding: 0.8rem 1rem; border: 1px solid var(--card-border); border-radius: 0.95rem;
		background: var(--event-bg); cursor: pointer; text-align: left; color: var(--text);
	}
	.agenda-row.holiday { background: color-mix(in srgb, var(--success) 8%, var(--event-bg)); cursor: default; }
	.agenda-day { font-size: 0.78rem; font-weight: 800; color: var(--text-soft); padding-right: 0.85rem; border-right: 1px solid var(--card-border); }
	.agenda-main { min-width: 0; }
	.agenda-main h3 { font-size: 1rem; display: flex; align-items: center; gap: 0.5rem; }
	.holiday-tag { font-size: 0.62rem; font-weight: 800; text-transform: uppercase; letter-spacing: 0.05em; color: var(--success); padding: 0.1rem 0.4rem; border: 1px solid color-mix(in srgb, var(--success) 40%, var(--border)); border-radius: 999px; }
	.agenda-meta { display: flex; flex-wrap: wrap; gap: 0.75rem; margin-top: 0.3rem; color: var(--text-soft); font-size: 0.8rem; }
	.agenda-meta span { display: inline-flex; align-items: center; gap: 0.3rem; }
	.agenda-desc { margin-top: 0.4rem; color: var(--text-muted); font-size: 0.84rem; }

	.empty-state {
		display: flex; align-items: center; gap: 0.65rem;
		padding: 1.4rem; color: var(--text-muted);
		border: 1px dashed var(--border-strong); border-radius: 1rem;
	}
	.loading-state { display: flex; align-items: center; gap: 0.65rem; padding: 1rem; color: var(--text-muted); }

	/* Editor */
	.event-form { display: grid; gap: 0.8rem; padding: 1.1rem; }
	.form-head h2 { font-size: 1.15rem; }
	.field { display: grid; gap: 0.3rem; }
	.field > span { font-size: 0.78rem; font-weight: 750; color: var(--text-soft); }
	.field > span small { font-weight: 550; color: var(--text-soft); opacity: 0.8; text-transform: none; }
	.event-form .field-row {
		display: grid;
		grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
		gap: 0.6rem;
		width: 100%;
		max-width: 100%;
		border: 0;
		background: transparent;
		box-shadow: none;
	}
	@media (max-width: 760px) {
		/* Toolbar drops below the title; let its groups spread and the Today/Event
		   buttons stay reachable. */
		.header-controls { width: 100%; justify-content: space-between; }
		.period-nav { flex: 1 1 auto; }
		.period-label { flex: 1 1 auto; min-width: 0; }
	}

	@media (max-width: 520px) {
		.event-form .field-row {
			width: 100%;
			grid-template-columns: 1fr;
		}

		.add-btn-label { display: none; }
		.add-btn { padding: 0.5rem; }
	}
	.field.narrow { min-width: 0; }
	.event-form input, .event-form textarea {
		width: 100%; padding: 0.6rem 0.75rem;
		border: 1px solid var(--border); border-radius: 0.75rem;
		background: var(--surface-inset); color: var(--text); font: inherit;
	}
	.event-form textarea { resize: none; min-height: 4rem; }
	.form-error { color: var(--danger); font-size: 0.84rem; }
	.form-warn { display: flex; align-items: center; gap: 0.4rem; color: var(--warning); font-size: 0.82rem; }
	.form-actions { display: flex; align-items: center; gap: 0.5rem; margin-top: 0.3rem; }
	.form-actions .spacer { flex: 1; }
	.event-form button {
		padding: 0.55rem 0.85rem; border-radius: 0.7rem; border: 0;
		background: #2563eb; color: #fff;
		font-weight: 800; cursor: pointer;
	}
	.event-form button:disabled { opacity: 0.5; cursor: not-allowed; }
	.event-form button.ghost { background: var(--surface-glass); color: var(--text-muted); border: 1px solid var(--border); }
	.event-form button.ghost.danger { color: var(--danger); }
	.event-form button.danger-confirm { background: var(--danger); }

	@container (max-width: 40rem) {
		.agenda-row { grid-template-columns: 1fr; }
		.agenda-day { border-right: 0; padding-right: 0; }
	}
</style>
