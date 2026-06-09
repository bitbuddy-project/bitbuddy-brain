<script lang="ts">
	import { onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import type { NotificationItem } from '$lib/api/bitbuddy';
	import { formatTime } from '$lib/stores/time.svelte';
	import { loadPersistedChat } from '$lib/stores/chat.svelte';
	import { closeToast, notificationCenter } from '$lib/stores/notifications.svelte';

	const TOAST_TIMEOUT_MS = 8000;
	const timers = new Map<number, number>();

	$effect(() => {
		const activeIds = new Set(notificationCenter.toasts.map((notification) => notification.id));

		for (const notification of notificationCenter.toasts) {
			if (isPersistent(notification)) continue;
			if (timers.has(notification.id)) continue;
			const timer = window.setTimeout(() => {
				void closeToast(notification.id);
				timers.delete(notification.id);
			}, TOAST_TIMEOUT_MS);
			timers.set(notification.id, timer);
		}

		for (const [id, timer] of timers.entries()) {
			if (activeIds.has(id)) continue;
			window.clearTimeout(timer);
			timers.delete(id);
		}
	});

	onDestroy(() => {
		for (const timer of timers.values()) window.clearTimeout(timer);
		timers.clear();
	});

	async function viewNotification(notification: NotificationItem) {
		await closeToast(notification.id);
		if (notification.chat_id) {
			await goto('/');
			await loadPersistedChat(notification.chat_id);
			return;
		}
		if (notification.action_url) {
			await goto(notification.action_url);
		}
	}

	function categoryLabel(category: string) {
		if (category === 'reminder') return 'Reminder';
		if (category === 'memory') return 'Memory';
		if (category === 'autonomy') return 'Autonomy';
		if (category === 'project') return 'Project';
		if (category === 'dream') return 'Dream';
		return 'BitBuddy';
	}

	function isPersistent(notification: NotificationItem) {
		return notification.metadata?.persistent === true;
	}
</script>

{#if notificationCenter.toasts.length > 0}
	<section class="notification-stack" aria-label="BitBuddy notifications" aria-live="polite">
		{#each notificationCenter.toasts as notification (notification.id)}
			<article class="toast" data-category={notification.category} data-severity={notification.severity} data-persistent={isPersistent(notification)}>
				<div class="toast-mark" aria-hidden="true"></div>
				<div class="toast-copy">
					<div class="toast-topline">
						<span>{categoryLabel(notification.category)}</span>
						<time>{formatTime(notification.created_at)}</time>
					</div>
					<h2>{notification.title}</h2>
					{#if notification.body}<p>{notification.body}</p>{/if}
					<div class="toast-actions">
						{#if notification.chat_id || notification.action_url}
							<button class="view-btn" type="button" onclick={() => viewNotification(notification)}>View</button>
						{/if}
						<button class="close-btn" type="button" onclick={() => closeToast(notification.id)}>Dismiss</button>
					</div>
				</div>
			</article>
		{/each}
	</section>
{/if}

<style>
	.notification-stack {
		position: fixed;
		right: 1.25rem;
		bottom: 1.25rem;
		z-index: 100;
		width: min(24rem, calc(100vw - 2rem));
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		pointer-events: none;
	}

	.toast {
		pointer-events: auto;
		display: grid;
		grid-template-columns: 0.35rem minmax(0, 1fr);
		gap: 0.85rem;
		padding: 0.95rem;
		border: 1px solid var(--border-strong);
		border-radius: 1.15rem;
		background:
			linear-gradient(135deg, rgba(255, 255, 255, 0.08), rgba(255, 255, 255, 0.025)),
			var(--panel);
		box-shadow: var(--shadow-panel);
		backdrop-filter: blur(22px);
		animation: toast-in 180ms cubic-bezier(0.16, 1, 0.3, 1);
	}

	:global(:root.light) .toast {
		background:
			linear-gradient(135deg, rgba(37, 99, 235, 0.08), rgba(225, 238, 250, 0.68)),
			var(--panel);
	}

	.toast-mark {
		width: 0.35rem;
		min-height: 100%;
		border-radius: 999px;
		background: var(--accent);
		box-shadow: 0 0 22px var(--accent-soft);
	}

	.toast[data-category='memory'] .toast-mark {
		background: #8b5cf6;
		box-shadow: 0 0 22px rgba(139, 92, 246, 0.28);
	}

	.toast[data-category='autonomy'] .toast-mark {
		background: var(--success);
		box-shadow: 0 0 22px rgba(110, 231, 183, 0.28);
	}

	.toast[data-severity='warning'] .toast-mark {
		background: var(--warning);
	}

	.toast[data-persistent='true'] {
		border-color: color-mix(in srgb, var(--warning) 42%, var(--border-strong));
	}

	.toast[data-severity='error'] .toast-mark {
		background: var(--danger);
	}

	.toast-copy {
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
	}

	.toast-topline {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
		color: var(--text-soft);
		font-size: 0.68rem;
		font-weight: 800;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	time {
		max-width: 9rem;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-weight: 700;
		letter-spacing: 0.02em;
		text-transform: none;
	}

	h2 {
		color: var(--text);
		font-size: 0.98rem;
		font-weight: 850;
		line-height: 1.25;
	}

	p {
		color: var(--text-muted);
		font-size: 0.86rem;
		line-height: 1.45;
	}

	.toast-actions {
		margin-top: 0.2rem;
		display: flex;
		justify-content: flex-end;
		gap: 0.5rem;
	}

	.toast-actions button {
		padding: 0.38rem 0.7rem;
		border-radius: 999px;
		font-size: 0.78rem;
		font-weight: 800;
	}

	.view-btn {
		background: var(--accent);
		color: var(--on-accent);
	}

	.close-btn {
		border: 1px solid var(--border);
		color: var(--text-muted);
	}

	.close-btn:hover {
		border-color: var(--border-strong);
		color: var(--text);
		background: var(--surface-glass);
	}

	@keyframes toast-in {
		from { opacity: 0; transform: translateY(0.75rem) scale(0.98); }
		to { opacity: 1; transform: translateY(0) scale(1); }
	}

	@media (max-width: 760px) {
		.notification-stack {
			right: 1rem;
			bottom: 1rem;
			width: calc(100vw - 2rem);
		}
	}
</style>
