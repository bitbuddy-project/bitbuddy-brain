<script lang="ts">
	import {
		cancelPendingSteer,
		chatSession,
		deleteUserMessageTurn,
		editUserMessageAndRerun,
		loadPersistedChat,
		removeRecentChat,
		scheduleContextUsage,
		sendMessage,
		setMode,
		startNewChat,
		steerPendingMessage,
		stopActiveResponse,
		toggleThink,
		toggleRecent
	} from '$lib/stores/chat.svelte';
	import ChatComposer from './ChatComposer.svelte';
	import ChatHeader from './ChatHeader.svelte';
	import MessageList from './MessageList.svelte';
	import SteeringCard from './SteeringCard.svelte';
</script>

<section class="chat-wrap" aria-label="BitBuddy chat">
	<div class="chat-panel" data-mode={chatSession.mode}>
		<ChatHeader
			mode={chatSession.mode}
			title={chatSession.title}
			chats={chatSession.recentChats}
			recentOpen={chatSession.recentOpen}
			notifications={chatSession.backgroundNotifications}
			onModeChange={setMode}
			onRecentToggle={toggleRecent}
			onRecentSelect={loadPersistedChat}
			onRecentDelete={removeRecentChat}
			onNewChat={startNewChat}
		/>
		<MessageList
			messages={chatSession.messages}
			thinking={chatSession.thinking}
			thinkEnabled={chatSession.thinkEnabled}
			error={chatSession.error}
			isStreaming={chatSession.isStreaming}
			buddyName={chatSession.buddyName}
			onUserMessageDelete={deleteUserMessageTurn}
			onUserMessageEdit={editUserMessageAndRerun}
		/>
		{#if chatSession.pendingSteer}
			<SteeringCard pending={chatSession.pendingSteer} onSteer={steerPendingMessage} onCancel={cancelPendingSteer} />
		{/if}
		<ChatComposer
			mode={chatSession.mode}
			buddyName={chatSession.buddyName}
			contextUsage={chatSession.contextUsage}
			thinkEnabled={chatSession.thinkEnabled}
			disabled={false}
			isStreaming={chatSession.isStreaming}
			hasPendingSteer={Boolean(chatSession.pendingSteer)}
			onDraftChange={scheduleContextUsage}
			onSend={sendMessage}
			onStop={stopActiveResponse}
			onSteer={steerPendingMessage}
			onThinkToggle={toggleThink}
		/>
	</div>
</section>

<style>
	.chat-wrap {
		width: 100%;
		max-width: 100%;
		padding: 0 1rem;
		height: 100%;
		display: flex;
		flex-direction: column;
		justify-content: center;
		margin: 0 auto;
		overflow: hidden;
	}

	.chat-panel {
		width: 100%;
		height: 100%;
		max-height: calc(100vh - 3rem);
		display: grid;
		grid-template-rows: auto 1fr auto auto;
		border: 1px solid var(--mode-border, var(--border));
		border-radius: 1.45rem;
		background:
			linear-gradient(135deg, var(--glass-overlay, rgba(255, 255, 255, 0.04)), transparent 24rem),
			radial-gradient(circle at top right, color-mix(in srgb, var(--mode-glow) 72%, transparent), transparent 30rem),
			var(--panel-shell, var(--panel));
		box-shadow: var(--shadow-chat);
		overflow: hidden;
		min-width: 0;
	}

	.chat-panel[data-mode='Chat'] {
		--mode-color: #79b8ff;
		--mode-soft: rgba(121, 184, 255, 0.15);
		--mode-border: rgba(121, 184, 255, 0.28);
		--mode-glow: rgba(121, 184, 255, 0.16);
	}

	.chat-panel[data-mode='Plan'] {
		--mode-color: #6ee7b7;
		--mode-soft: rgba(110, 231, 183, 0.14);
		--mode-border: rgba(110, 231, 183, 0.28);
		--mode-glow: rgba(110, 231, 183, 0.14);
	}

	.chat-panel[data-mode='Debug'] {
		--mode-color: #f59e0b;
		--mode-soft: rgba(245, 158, 11, 0.14);
		--mode-border: rgba(245, 158, 11, 0.3);
		--mode-glow: rgba(245, 158, 11, 0.14);
	}

	:global(:root.light) .chat-panel[data-mode='Chat'] {
		--mode-color: #2563eb;
		--mode-soft: rgba(37, 99, 235, 0.13);
		--mode-border: rgba(37, 99, 235, 0.26);
		--mode-glow: rgba(37, 99, 235, 0.18);
	}

	:global(:root.light) .chat-panel[data-mode='Plan'] {
		--mode-color: #047857;
		--mode-soft: rgba(16, 185, 129, 0.18);
		--mode-border: rgba(4, 120, 87, 0.32);
		--mode-glow: rgba(4, 120, 87, 0.18);
	}

	:global(:root.light) .chat-panel[data-mode='Debug'] {
		--mode-color: #b45309;
		--mode-soft: rgba(245, 158, 11, 0.18);
		--mode-border: rgba(180, 83, 9, 0.32);
		--mode-glow: rgba(180, 83, 9, 0.16);
	}

	@media (max-width: 760px) {
		.chat-wrap,
		.chat-panel {
			height: calc(100vh - 2rem);
		}
	}
</style>
