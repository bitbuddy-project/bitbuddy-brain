import { getConfig } from '$lib/api/bitbuddy';

export const timePreferences = $state({
	timezone: 'UTC',
	locale: 'en-US',
	loaded: false
});

const STORAGE_KEY = 'bitbuddy:time-preferences';

export function loadStoredTimePreferences() {
	if (typeof localStorage === 'undefined') return;
	try {
		const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
		if (typeof stored.timezone === 'string' && stored.timezone) timePreferences.timezone = stored.timezone;
		if (typeof stored.locale === 'string' && stored.locale) timePreferences.locale = stored.locale;
	} catch {
		// Ignore malformed local storage; config load will repair it.
	}
}

export function setTimePreferences(timezone: string, locale: string) {
	timePreferences.timezone = timezone || 'UTC';
	timePreferences.locale = locale || 'en-US';
	timePreferences.loaded = true;
	if (typeof localStorage !== 'undefined') {
		localStorage.setItem(STORAGE_KEY, JSON.stringify({ timezone: timePreferences.timezone, locale: timePreferences.locale }));
	}
}

export async function initializeTimePreferences() {
	loadStoredTimePreferences();
	try {
		const config = await getConfig();
		setTimePreferences(config.user_context?.timezone || 'UTC', config.user_context?.locale || 'en-US');
	} catch {
		timePreferences.loaded = true;
	}
}

export function parseTimestamp(value: string | null | undefined): Date | null {
	if (!value) return null;
	const clean = value.trim();
	if (!clean) return null;
	const isoLike = clean.includes('T') ? clean : clean.replace(' ', 'T');
	const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(isoLike);
	const date = new Date(hasZone ? isoLike : `${isoLike}Z`);
	return Number.isNaN(date.getTime()) ? null : date;
}

export function formatTimestamp(
	value: string | null | undefined,
	options: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }
): string {
	const date = parseTimestamp(value);
	if (!date) return value ?? '';
	try {
		return new Intl.DateTimeFormat(timePreferences.locale || undefined, {
			timeZone: timePreferences.timezone || 'UTC',
			...options
		}).format(date);
	} catch {
		return new Intl.DateTimeFormat(undefined, options).format(date);
	}
}

export function formatTime(value: string | null | undefined): string {
	return formatTimestamp(value, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function formatDate(value: string | null | undefined): string {
	return formatTimestamp(value, { year: 'numeric', month: 'short', day: 'numeric' });
}
