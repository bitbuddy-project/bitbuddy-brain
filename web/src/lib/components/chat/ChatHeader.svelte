<script lang="ts">
	import ModeToggle from './ModeToggle.svelte';
	import RecentChats from './RecentChats.svelte';
	import GearSixIcon from 'phosphor-svelte/lib/GearSixIcon';
	import type { ChatSummary } from '$lib/api/bitbuddy';

	let {
		mode,
		title,
		chats,
		recentOpen,
		notifications = {},
		onModeChange,
		onRecentToggle,
		onRecentSelect,
		onRecentDelete,
		onNewChat
	} = $props<{
		mode: string;
		title: string;
		chats: ChatSummary[];
		recentOpen: boolean;
		notifications?: Record<string, number>;
		onModeChange: (mode: string) => void;
		onRecentToggle: () => void;
		onRecentSelect: (chatId: string) => void;
		onRecentDelete: (chatId: string) => void;
		onNewChat: () => void;
	}>();
</script>

<header class="chat-header">
	<div class="header-main">
		<p class="eyebrow">Current chat · {mode} mode</p>
		<h1>{title}</h1>
	</div>

	<div class="header-actions">
		<RecentChats {chats} open={recentOpen} {notifications} onToggle={onRecentToggle} onSelect={onRecentSelect} onDelete={onRecentDelete} {onNewChat} />
		<ModeToggle {mode} {onModeChange} />
	</div>
</header>

<style>
	.chat-header {
		padding: 1.25rem 1.5rem;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		border-bottom: 1px solid var(--border);
		background: var(--header-bg);
		min-width: 0;
	}

	.header-main {
		min-width: 0;
		flex: 1;
	}

	.eyebrow {
		color: var(--text-soft);
		font-size: 0.72rem;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		margin-bottom: 0.2rem;
	}

	h1 {
		font-size: 1.35rem;
		font-weight: 800;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 100%;
	}

	.header-actions {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}

	@media (max-width: 760px) {
		.chat-header {
			padding: 1rem;
			flex-direction: column;
			align-items: stretch;
		}

		.header-actions {
			justify-content: space-between;
		}
	}
</style>
