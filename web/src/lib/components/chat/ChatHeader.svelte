<script lang="ts">
	import PageHeader from '$lib/components/PageHeader.svelte';
	import ModeToggle from './ModeToggle.svelte';
	import CodingButton from './CodingButton.svelte';
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

<PageHeader variant="chat" eyebrow={`Current chat · ${mode} mode`} title={title}>
	{#snippet action()}
		<RecentChats {chats} open={recentOpen} {notifications} onToggle={onRecentToggle} onSelect={onRecentSelect} onDelete={onRecentDelete} {onNewChat} />
		<ModeToggle {mode} {onModeChange} />
		<CodingButton />
	{/snippet}
</PageHeader>
