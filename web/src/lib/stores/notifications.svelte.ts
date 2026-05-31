import type { NotificationItem } from '$lib/api/bitbuddy';
import { getNotifications, markNotificationRead } from '$lib/api/bitbuddy';

const NOTIFICATION_POLL_MS = 8000;
const LAST_SEEN_KEY = 'bitbuddy:notifications:last-seen-id';
const MAX_TOASTS = 4;
const MAX_ITEMS = 50;

let notificationPollTimer: number | undefined;
let lastSeenId = 0;

export const notificationCenter = $state({
	initialized: false,
	items: [] as NotificationItem[],
	toasts: [] as NotificationItem[],
	unreadCount: 0,
	error: ''
});

export function initializeNotifications() {
	if (typeof window === 'undefined') return;
	if (!notificationCenter.initialized) {
		notificationCenter.initialized = true;
		lastSeenId = readLastSeenId();
		void pollNotifications({ showToasts: true });
	}
	startNotificationPolling();
}

export function startNotificationPolling() {
	if (typeof window === 'undefined' || notificationPollTimer) return;
	notificationPollTimer = window.setInterval(() => {
		void pollNotifications({ showToasts: true });
	}, NOTIFICATION_POLL_MS);
}

export function stopNotificationPolling() {
	if (!notificationPollTimer) return;
	window.clearInterval(notificationPollTimer);
	notificationPollTimer = undefined;
}

export async function pollNotifications({ showToasts = true }: { showToasts?: boolean } = {}) {
	try {
		const response = await getNotifications({ afterId: lastSeenId, limit: lastSeenId > 0 ? MAX_ITEMS : 20 });
		const incoming = response.notifications.filter((notification) => notification.id > lastSeenId);
		if (response.notifications.length > 0) {
			lastSeenId = Math.max(lastSeenId, ...response.notifications.map((notification) => notification.id));
			writeLastSeenId(lastSeenId);
		}

		if (response.notifications.length > 0) {
			notificationCenter.items = mergeNotifications(notificationCenter.items, response.notifications);
		}
		notificationCenter.unreadCount = response.unread_count;
		notificationCenter.error = '';

		if (showToasts && incoming.length > 0) {
			notificationCenter.toasts = mergeNotifications(notificationCenter.toasts, incoming).slice(0, MAX_TOASTS);
		}
	} catch (caught) {
		notificationCenter.error = caught instanceof Error ? caught.message : 'Could not load notifications.';
	}
}

export async function closeToast(notificationId: number) {
	notificationCenter.toasts = notificationCenter.toasts.filter((notification) => notification.id !== notificationId);
	try {
		notificationCenter.unreadCount = await markNotificationRead(notificationId);
		notificationCenter.items = notificationCenter.items.map((notification) =>
			notification.id === notificationId ? { ...notification, read_at: notification.read_at || new Date().toISOString() } : notification
		);
	} catch {
		// Closing a toast should not surface transient API failures.
	}
}

function mergeNotifications(current: NotificationItem[], incoming: NotificationItem[]) {
	const byId = new Map<number, NotificationItem>();
	for (const notification of current) byId.set(notification.id, notification);
	for (const notification of incoming) byId.set(notification.id, notification);
	return [...byId.values()].sort((a, b) => b.id - a.id).slice(0, MAX_ITEMS);
}

function readLastSeenId() {
	const stored = window.localStorage.getItem(LAST_SEEN_KEY);
	const value = Number(stored ?? 0);
	return Number.isFinite(value) && value > 0 ? value : 0;
}

function writeLastSeenId(value: number) {
	window.localStorage.setItem(LAST_SEEN_KEY, String(value));
}
