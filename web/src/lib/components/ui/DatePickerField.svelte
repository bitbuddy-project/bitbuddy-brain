<script lang="ts">
	import CalendarBlankIcon from 'phosphor-svelte/lib/CalendarBlankIcon';
	import CaretLeftIcon from 'phosphor-svelte/lib/CaretLeftIcon';
	import CaretRightIcon from 'phosphor-svelte/lib/CaretRightIcon';
	import Overlay from './Overlay.svelte';
	import { isToday, monthGrid, monthNav, sameDay, toISODate } from '$lib/utils/calendar-grid';

	let {
		label = 'Date',
		value = $bindable(''),
		disabled = false,
		onValueChange
	}: {
		label?: string;
		value?: string;
		disabled?: boolean;
		onValueChange?: (value: string) => void;
	} = $props();

	const DAYS_OF_WEEK = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

	let open = $state(false);
	let gridElement: HTMLDivElement | null = $state(null);
	let displayedMonth = $state(parseDisplay(value).month);
	let displayedYear = $state(parseDisplay(value).year);

	const days = $derived(monthGrid(displayedMonth, displayedYear));
	const monthLabel = $derived(
		new Date(displayedYear, displayedMonth).toLocaleString(undefined, { month: 'long', year: 'numeric' })
	);
	const displayValue = $derived(formatDisplay(value));

	function parseDisplay(raw: string): { month: number; year: number } {
		const [year, month] = (raw || '').split('-').map(Number);
		if (!year || !month) {
			const now = new Date();
			return { month: now.getMonth(), year: now.getFullYear() };
		}
		return { month: month - 1, year };
	}

	function parseDate(raw: string): Date | null {
		const [year, month, day] = (raw || '').split('-').map(Number);
		if (!year || !month || !day) return null;
		return new Date(year, month - 1, day);
	}

	function formatDisplay(raw: string): string {
		const date = parseDate(raw);
		return date ? date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : 'Select date';
	}

	function openPicker() {
		if (disabled) return;
		const parsed = parseDisplay(value);
		displayedMonth = parsed.month;
		displayedYear = parsed.year;
		open = true;
		setTimeout(() => {
			const selected = gridElement?.querySelector<HTMLButtonElement>('.day.selected');
			const first = gridElement?.querySelector<HTMLButtonElement>('.day');
			(selected ?? first)?.focus();
		}, 0);
	}

	function changeMonth(direction: 'prev' | 'next') {
		const next = monthNav(direction, displayedMonth, displayedYear);
		displayedMonth = next.month;
		displayedYear = next.year;
	}

	function choose(date: Date) {
		const next = toISODate(date);
		value = next;
		displayedMonth = date.getMonth();
		displayedYear = date.getFullYear();
		onValueChange?.(next);
		open = false;
	}

	function onDayKeydown(event: KeyboardEvent, index: number) {
		let next = index;
		if (event.key === 'ArrowRight') next = (index + 1) % days.length;
		else if (event.key === 'ArrowLeft') next = (index - 1 + days.length) % days.length;
		else if (event.key === 'ArrowDown') next = (index + 7) % days.length;
		else if (event.key === 'ArrowUp') next = (index - 7 + days.length) % days.length;
		else return;
		event.preventDefault();
		setTimeout(() => {
			gridElement?.querySelectorAll<HTMLButtonElement>('.day')?.[next]?.focus();
		}, 0);
	}

	function inCurrentMonth(date: Date): boolean {
		return date.getMonth() === displayedMonth && date.getFullYear() === displayedYear;
	}
</script>

<div class="datepicker" data-open={open}>
	<button class="dp-trigger" type="button" aria-expanded={open} {disabled} onclick={openPicker}>
		<CalendarBlankIcon size={16} weight="bold" />
		<span>{displayValue}</span>
	</button>
</div>

<Overlay {open} label={`${label} calendar`} onClose={() => (open = false)}>
	<div class="dp-menu">
		<div class="dp-topline">
			<button class="dp-nav" type="button" onclick={() => changeMonth('prev')} aria-label="Previous month">
				<CaretLeftIcon size={16} weight="bold" />
			</button>
			<div class="dp-title">
				<span>{label}</span>
				<strong>{monthLabel}</strong>
			</div>
			<button class="dp-nav" type="button" onclick={() => changeMonth('next')} aria-label="Next month">
				<CaretRightIcon size={16} weight="bold" />
			</button>
		</div>

		<div class="dp-weekrow" aria-hidden="true">
			{#each DAYS_OF_WEEK as day}<span>{day}</span>{/each}
		</div>

		<div class="dp-grid" bind:this={gridElement}>
			{#each days as day, index (toISODate(day))}
				<button
					class="day"
					class:muted={!inCurrentMonth(day)}
					class:today={isToday(day)}
					class:selected={toISODate(day) === value}
					type="button"
					onclick={() => choose(day)}
					onkeydown={(event) => onDayKeydown(event, index)}
					aria-label={day.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })}
				>
					<span>{day.getDate()}</span>
				</button>
			{/each}
		</div>
	</div>
</Overlay>

<style>
	.dp-trigger {
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
		width: 100%;
		min-height: 2.6rem;
		padding: 0.6rem 0.8rem;
		border: 1px solid var(--border);
		border-radius: 0.8rem;
		background: var(--surface-inset);
		color: var(--text);
		cursor: pointer;
		font: inherit;
		text-align: left;
		transition: border-color 140ms ease, box-shadow 140ms ease;
	}

	.dp-trigger:hover:not(:disabled),
	.datepicker[data-open='true'] .dp-trigger {
		border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 12%, transparent);
	}

	.dp-trigger:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.dp-trigger :global(svg) {
		flex: 0 0 auto;
		color: var(--accent);
	}

	.dp-menu {
		display: grid;
		min-width: min(88vw, 22rem);
	}

	.dp-topline {
		display: grid;
		grid-template-columns: auto minmax(0, 1fr) auto;
		align-items: center;
		gap: 0.5rem;
		padding: 0.85rem 1rem;
		border-bottom: 1px solid var(--card-border);
	}

	.dp-title {
		display: grid;
		gap: 0.1rem;
		text-align: center;
	}

	.dp-title span {
		font-size: 0.62rem;
		font-weight: 800;
		letter-spacing: 0.1em;
		text-transform: uppercase;
		color: var(--accent);
	}

	.dp-title strong {
		font-size: 1.15rem;
		letter-spacing: -0.02em;
	}

	.dp-nav {
		display: grid;
		place-items: center;
		width: 2.2rem;
		height: 2.2rem;
		border: 1px solid var(--border);
		border-radius: 0.65rem;
		background: var(--surface-glass);
		color: var(--text-muted);
		cursor: pointer;
	}

	.dp-nav:hover {
		border-color: color-mix(in srgb, var(--accent) 40%, var(--border));
		color: var(--text);
	}

	.dp-weekrow,
	.dp-grid {
		display: grid;
		grid-template-columns: repeat(7, minmax(0, 1fr));
	}

	.dp-weekrow {
		padding: 0.6rem 1rem 0.2rem;
		gap: 0;
	}

	.dp-weekrow span {
		text-align: center;
		font-size: 0.62rem;
		font-weight: 800;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		color: var(--text-soft);
	}

	.dp-grid {
		padding: 0.5rem 1rem 1rem;
		gap: 0.2rem;
	}

	.day {
		position: relative;
		display: grid;
		place-items: center;
		min-height: 2.4rem;
		border: 1px solid transparent;
		border-radius: 0.6rem;
		background: var(--surface-inset);
		color: var(--text);
		cursor: pointer;
		font: inherit;
		font-weight: 700;
		font-size: 0.88rem;
		transition: background 120ms ease, box-shadow 120ms ease, color 120ms ease;
	}

	.day:hover,
	.day:focus-visible {
		outline: none;
		background: color-mix(in srgb, var(--accent) 12%, var(--surface-inset));
		box-shadow: inset 0 0 0 1px var(--accent);
	}

	.day.muted {
		background: transparent;
		color: var(--text-soft);
		opacity: 0.55;
	}

	.day.today {
		box-shadow: inset 0 0 0 1px var(--accent);
		color: var(--accent-strong);
	}

	.day.selected {
		background: var(--accent);
		color: var(--on-accent);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 30%, transparent);
	}
</style>
