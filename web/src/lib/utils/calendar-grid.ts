/**
 * Calendar grid helpers. The month-grid / navigation mechanics are ported from
 * sparekey's `datePicker.ts`; week-grid and event-bucketing are added for the
 * BitBuddy calendar page.
 */

export type GridDay = {
	date: Date;
	inCurrentMonth: boolean;
	isToday: boolean;
};

function pad(value: number): string {
	return String(value).padStart(2, '0');
}

export function startOfDay(date: Date): Date {
	return new Date(date.getFullYear(), date.getMonth(), date.getDate());
}

/** Local YYYY-MM-DD for a Date (no timezone math — calendar/browser local). */
export function toISODate(date: Date): string {
	return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function isToday(date: Date): boolean {
	return startOfDay(date).getTime() === startOfDay(new Date()).getTime();
}

export function sameDay(a: Date, b: Date): boolean {
	return startOfDay(a).getTime() === startOfDay(b).getTime();
}

export function getDaysInMonth(month: number, year: number): number {
	return new Date(year, month + 1, 0).getDate();
}

/** 42-cell (6×7) month grid with leading/trailing days, Sunday-first. */
export function monthGrid(month: number, year: number): Date[] {
	const startDay = new Date(year, month, 1).getDay();
	const daysInMonth = getDaysInMonth(month, year);
	const days: Date[] = [];

	const prevMonth = month === 0 ? 11 : month - 1;
	const prevYear = month === 0 ? year - 1 : year;
	const prevMonthDays = getDaysInMonth(prevMonth, prevYear);
	for (let day = prevMonthDays - startDay + 1; day <= prevMonthDays; day += 1) {
		days.push(new Date(prevYear, prevMonth, day));
	}
	for (let day = 1; day <= daysInMonth; day += 1) {
		days.push(new Date(year, month, day));
	}
	const nextMonth = month === 11 ? 0 : month + 1;
	const nextYear = month === 11 ? year + 1 : year;
	for (let day = 1; days.length < 42; day += 1) {
		days.push(new Date(nextYear, nextMonth, day));
	}
	return days;
}

/** The seven days (Sun–Sat) of the week containing `date`. */
export function weekDays(date: Date): Date[] {
	const base = startOfDay(date);
	const start = new Date(base);
	start.setDate(base.getDate() - base.getDay());
	return Array.from({ length: 7 }, (_, i) => {
		const day = new Date(start);
		day.setDate(start.getDate() + i);
		return day;
	});
}

export function monthNav(direction: 'prev' | 'next', month: number, year: number): { month: number; year: number } {
	if (direction === 'prev') {
		return month === 0 ? { month: 11, year: year - 1 } : { month: month - 1, year };
	}
	return month === 11 ? { month: 0, year: year + 1 } : { month: month + 1, year };
}

/** Format a UTC ISO instant to YYYY-MM-DD in the given IANA timezone. */
export function localYMD(iso: string, timeZone: string): string {
	try {
		const parts = new Intl.DateTimeFormat('en-CA', {
			timeZone,
			year: 'numeric',
			month: '2-digit',
			day: '2-digit'
		}).formatToParts(new Date(iso));
		const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
		return `${get('year')}-${get('month')}-${get('day')}`;
	} catch {
		return iso.slice(0, 10);
	}
}

/** Events whose start lands on `day` (in `timeZone`), holidays sorted first. */
export function eventsForDay<T extends { start_at: string; all_day?: boolean; source?: string }>(
	events: T[],
	day: Date,
	timeZone: string
): T[] {
	const key = toISODate(day);
	return events
		.filter((event) => localYMD(event.start_at, timeZone) === key)
		.sort((a, b) => {
			const ah = a.source === 'holiday' ? 0 : 1;
			const bh = b.source === 'holiday' ? 0 : 1;
			if (ah !== bh) return ah - bh;
			if (a.all_day && !b.all_day) return -1;
			if (!a.all_day && b.all_day) return 1;
			return a.start_at.localeCompare(b.start_at);
		});
}
