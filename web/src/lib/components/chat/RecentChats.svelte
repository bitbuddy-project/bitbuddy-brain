<script lang="ts">
	import ClockCounterClockwiseIcon from 'phosphor-svelte/lib/ClockCounterClockwiseIcon';
	import TrashIcon from 'phosphor-svelte/lib/TrashIcon';
	import PlusIcon from 'phosphor-svelte/lib/PlusIcon';
	import type { ChatSummary } from '$lib/api/bitbuddy';
	import { formatTimestamp } from '$lib/stores/time.svelte';

	let { chats, open, onToggle, onSelect, onDelete, onNewChat, notifications = {} as Record<string, number> } = $props<{
		chats: ChatSummary[];
		open: boolean;
		onToggle: () => void;
		onSelect: (chatId: string) => void;
		onDelete: (chatId: string) => void;
		onNewChat: () => void;
		notifications?: Record<string, number>;
	}>();

	let totalNotifications = $derived((Object.values(notifications) as number[]).reduce((sum, n) => sum + n, 0));

	let container: HTMLDivElement;

	function handleOutsideClick(event: MouseEvent) {
		if (open && container && !container.contains(event.target as Node)) {
			onToggle();
		}
	}
</script>

<svelte:window onclick={handleOutsideClick} />

<div class="recent-wrap" bind:this={container}>
	<button class="recent-button" class:open type="button" onclick={onToggle} aria-expanded={open}>
		<ClockCounterClockwiseIcon size={18} />
		<span>Recent</span>
		{#if totalNotifications > 0 && !open}
			<span class="notification-badge">{totalNotifications > 9 ? '9+' : totalNotifications}</span>
		{/if}
	</button>

	{#if open}
		<div class="recent-menu">
			<div class="menu-header">
				<span class="menu-title">Recent Chats</span>
				<button class="new-chat-btn" type="button" onclick={onNewChat}>
					<PlusIcon size={14} weight="bold" />
					<span>New Chat</span>
				</button>
			</div>
			<div class="chat-list">
				{#if chats.length === 0}
					<p class="empty-state">No saved chats yet.</p>
				{:else}
					{#each chats as chat}
						<div class="chat-row">
						<button class="chat-select" type="button" onclick={() => onSelect(chat.id)}>
							<div class="chat-info">
								<strong>{chat.title}</strong>
								<span>{chat.mode} · {formatTimestamp(chat.updated_at)}</span>
							</div>
							{#if (Number(notifications[chat.id] ?? 0)) > 0}
								<span class="chat-notification-dot" title={`${notifications[chat.id]} unread`}></span>
							{/if}
						</button>
						<button class="delete-chat" type="button" aria-label={`Delete chat ${chat.title}`} onclick={() => onDelete(chat.id)}>
							<TrashIcon size={16} />
						</button>
						</div>
					{/each}
				{/if}
			</div>
			<div class="menu-footer">
				<a class="all-chats-link" href="/history" onclick={onToggle}>All chats →</a>
			</div>
		</div>
	{/if}
</div>

<style>
	.recent-wrap {
		position: relative;
		--recent-button-bg: rgba(255, 255, 255, 0.03);
		--recent-button-hover-bg: rgba(255, 255, 255, 0.06);
		--recent-menu-bg: var(--panel);
		--recent-header-bg: rgba(255, 255, 255, 0.02);
		--recent-row-hover-bg: rgba(255, 255, 255, 0.05);
		--recent-shadow: var(--shadow-soft);
	}

	:global(:root.light) .recent-wrap {
		--recent-button-bg: rgba(15, 23, 42, 0.035);
		--recent-button-hover-bg: rgba(37, 99, 235, 0.08);
		--recent-menu-bg: color-mix(in srgb, var(--panel) 96%, var(--accent-soft));
		--recent-header-bg: linear-gradient(180deg, rgba(37, 99, 235, 0.055), rgba(15, 23, 42, 0.018));
		--recent-row-hover-bg: rgba(37, 99, 235, 0.07);
		--recent-shadow: 0 20px 48px rgba(15, 23, 42, 0.16), 0 2px 8px rgba(15, 23, 42, 0.06);
		--new-chat-text: #ffffff;
	}

	.recent-button {
		display: inline-flex;
		align-items: center;
		gap: 0.45rem;
		padding: 0.5rem 0.9rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: var(--recent-button-bg);
		color: var(--text-muted);
		font-size: 0.85rem;
		font-weight: 600;
	}

	.recent-button:hover,
	.recent-button.open {
		color: var(--text);
		border-color: var(--border-strong);
		background: var(--recent-button-hover-bg);
	}

	.recent-menu {
		position: absolute;
		top: calc(100% + 0.6rem);
		right: 0;
		width: 22rem;
		max-height: 28rem;
		display: flex;
		flex-direction: column;
		border: 1px solid var(--border-strong);
		border-radius: 1.25rem;
		background: var(--recent-menu-bg);
		box-shadow: var(--recent-shadow);
		backdrop-filter: blur(24px);
		z-index: 50;
		overflow: hidden;
		animation: scale-up 0.2s cubic-bezier(0.16, 1, 0.3, 1);
	}

	@keyframes scale-up {
		from { opacity: 0; transform: scale(0.95) translateY(-10px); }
		to { opacity: 1; transform: scale(1) translateY(0); }
	}

	.menu-header {
		padding: 1rem 1.25rem;
		display: flex;
		align-items: center;
		justify-content: space-between;
		border-bottom: 1px solid var(--border);
		background: var(--recent-header-bg);
	}

	.menu-title {
		font-size: 0.85rem;
		font-weight: 800;
		color: var(--text-soft);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.notification-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 18px;
		height: 18px;
		padding: 0 4px;
		border-radius: 999px;
		background: var(--mode-color, #79b8ff);
		color: #fff;
		font-size: 0.65rem;
		font-weight: 700;
		line-height: 1;
	}

	.new-chat-btn {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		padding: 0.35rem 0.75rem;
		border-radius: 0.6rem;
		background: var(--accent);
		color: var(--new-chat-text, #06101d);
		font-size: 0.8rem;
		font-weight: 700;
	}

	.chat-list {
		padding: 0.5rem;
		overflow-y: auto;
	}

	.chat-row {
		width: 100%;
		padding: 0.25rem;
		border-radius: 0.85rem;
		display: flex;
		align-items: center;
		gap: 0.25rem;
		text-align: left;
		transition: 120ms ease;
	}

	.chat-row:hover {
		background: var(--recent-row-hover-bg);
	}

	.chat-select {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.75rem 1rem 0.75rem 1.25rem;
		border: none;
		background: transparent;
		color: var(--text);
		font-size: 0.9rem;
		text-align: left;
		cursor: pointer;
		flex: 1;
		min-width: 0;
	}

	.chat-notification-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--mode-color, #79b8ff);
		flex-shrink: 0;
	}

	.delete-chat {
		width: 2.1rem;
		height: 2.1rem;
		flex: 0 0 auto;
		display: grid;
		place-items: center;
		border-radius: 999px;
		color: var(--text-soft);
	}

	.delete-chat:hover {
		background: rgba(255, 107, 122, 0.12);
		color: var(--danger);
	}

	.chat-info {
		min-width: 0;
	}

	.chat-select strong {
		display: block;
		color: var(--text);
		font-size: 0.95rem;
		font-weight: 600;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.chat-select span {
		display: block;
		color: var(--text-soft);
		font-size: 0.78rem;
		margin-top: 0.1rem;
	}

	.empty-state {
		padding: 2rem;
		text-align: center;
		color: var(--text-soft);
		font-size: 0.9rem;
	}

	.menu-footer {
		padding: 0.6rem 1.25rem;
		border-top: 1px solid var(--border);
		display: flex;
		justify-content: flex-end;
	}

	.all-chats-link {
		font-size: 0.8rem;
		font-weight: 600;
		color: var(--text-muted);
		text-decoration: none;
		transition: color 120ms ease;
	}

	.all-chats-link:hover {
		color: var(--accent);
	}

	@media (max-width: 760px) {
		.recent-button {
			width: 2.35rem;
			height: 2.35rem;
			justify-content: center;
			padding: 0;
			gap: 0;
		}

		.recent-button > span:not(.notification-badge) {
			display: none;
		}

		.notification-badge {
			position: absolute;
			top: -0.35rem;
			right: -0.35rem;
		}

		.recent-menu {
			position: fixed;
			top: 4.25rem;
			right: 1rem;
			left: 1rem;
			width: auto;
			max-height: min(28rem, calc(100dvh - 5.25rem));
			z-index: 60;
		}
	}
</style>
