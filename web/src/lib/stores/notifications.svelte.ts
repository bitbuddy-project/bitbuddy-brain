import type { NotificationItem } from '$lib/api/bitbuddy';
import { BITBUDDY_API, getNotifications, markNotificationRead } from '$lib/api/bitbuddy';

const NOTIFICATION_POLL_MS = 8000;
const LAST_SEEN_KEY = 'bitbuddy:notifications:last-seen-id';
const MAX_TOASTS = 4;
const MAX_ITEMS = 50;

let notificationPollTimer: number | undefined;
let notificationEvents: EventSource | null = null;
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
		startNotificationStream();
	}
	startNotificationPolling();
}

function startNotificationStream() {
	if (typeof window === 'undefined' || notificationEvents) return;
	try {
		notificationEvents = new EventSource(`${BITBUDDY_API}/notifications/stream`);
		notificationEvents.onmessage = (event) => {
			try {
				const chunk = JSON.parse(event.data);
				if (chunk.kind === 'notification' && chunk.notification) {
					handleIncomingNotifications([chunk.notification], { showToasts: true });
				}
			} catch {
				// Ignore malformed stream events; polling remains the fallback.
			}
		};
		notificationEvents.onerror = () => {
			notificationEvents?.close();
			notificationEvents = null;
		};
	} catch {
		notificationEvents = null;
	}
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
		handleIncomingNotifications(response.notifications, { showToasts });
		notificationCenter.unreadCount = response.unread_count;
		notificationCenter.error = '';
	} catch (caught) {
		notificationCenter.error = caught instanceof Error ? caught.message : 'Could not load notifications.';
	}
}

function handleIncomingNotifications(notifications: NotificationItem[], { showToasts = true }: { showToasts?: boolean } = {}) {
	if (notifications.length === 0) return;
	const incoming = notifications.filter((notification) => notification.id > lastSeenId);
	lastSeenId = Math.max(lastSeenId, ...notifications.map((notification) => notification.id));
	writeLastSeenId(lastSeenId);
	notificationCenter.items = mergeNotifications(notificationCenter.items, notifications);
	if (showToasts && incoming.length > 0) {
		notificationCenter.toasts = mergeToastNotifications(notificationCenter.toasts, incoming);
		notificationCenter.unreadCount += incoming.filter((notification) => !notification.read_at && !notification.dismissed_at).length;
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

function mergeToastNotifications(current: NotificationItem[], incoming: NotificationItem[]) {
	const merged = mergeNotifications(current, incoming);
	const persistent = merged.filter(isPersistentNotification);
	const regular = merged.filter((notification) => !isPersistentNotification(notification)).slice(0, MAX_TOASTS);
	return [...persistent, ...regular].slice(0, Math.max(MAX_TOASTS, persistent.length));
}

export function isPersistentNotification(notification: NotificationItem) {
	return notification.metadata?.persistent === true;
}

function readLastSeenId() {
	const stored = window.localStorage.getItem(LAST_SEEN_KEY);
	const value = Number(stored ?? 0);
	return Number.isFinite(value) && value > 0 ? value : 0;
}

function writeLastSeenId(value: number) {
	window.localStorage.setItem(LAST_SEEN_KEY, String(value));
}
