<script lang="ts">
	import ModeToggle from './ModeToggle.svelte';
	import RecentChats from './RecentChats.svelte';
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
		position: relative;
		z-index: 10;
		padding: 1.15rem 1.55rem;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1rem;
		border: 1px solid color-mix(in srgb, var(--bg-soft) 68%, var(--border));
		border-radius: 1.35rem;
		background:
			radial-gradient(circle at 18% 0%, rgba(50, 78, 115, 0.1), transparent 23rem),
			linear-gradient(135deg, rgba(255, 255, 255, 0.026), transparent 62%),
			color-mix(in srgb, var(--panel-shell, var(--panel)) 86%, #01050d);
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.13), var(--shadow-chat);
		min-width: 0;
		overflow: visible;
	}

	.chat-header::before {
		content: '';
		position: absolute;
		inset: 0;
		border-top: 1px solid rgba(255, 255, 255, 0.24);
		border-radius: inherit;
		pointer-events: none;
	}

	:global(:root.light) .chat-header {
		border-color: rgba(73, 104, 145, 0.18);
		background:
			radial-gradient(circle at 18% 0%, rgba(37, 99, 235, 0.08), transparent 23rem),
			linear-gradient(135deg, rgba(255, 255, 255, 0.34), transparent 62%),
			color-mix(in srgb, #d6e4f2 82%, var(--panel) 18%);
		box-shadow:
			0 16px 34px rgba(50, 80, 118, 0.1),
			inset 0 1px 0 rgba(255, 255, 255, 0.74);
	}

	:global(:root.light) .chat-header::before {
		border-top-color: rgba(255, 255, 255, 0.78);
	}

	.header-main {
		min-width: 0;
		flex: 1;
	}

	.eyebrow {
		color: color-mix(in srgb, var(--mode-color, var(--accent)) 48%, var(--text-soft));
		font-size: 0.72rem;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		margin-bottom: 0.2rem;
	}

	h1 {
		font-size: clamp(1.25rem, 1.7vw, 1.72rem);
		font-weight: 800;
		letter-spacing: -0.035em;
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
