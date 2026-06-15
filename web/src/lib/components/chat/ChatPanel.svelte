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
		setReasoningEffort,
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
	import { PROVIDER_SUPPORTS_EFFORT } from '$lib/providerModels';

	let reasoningEffortVisible = $derived(PROVIDER_SUPPORTS_EFFORT.has(chatSession.contextUsage?.provider ?? ''));
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
		<div class="chat-body">
			<MessageList
				messages={chatSession.messages}
				thinking={chatSession.thinking}
				activeThinkEnabled={chatSession.activeThinkEnabled}
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
				reasoningEffort={chatSession.reasoningEffort}
				reasoningEffortVisible={reasoningEffortVisible}
				disabled={false}
				isStreaming={chatSession.isStreaming}
				onDraftChange={scheduleContextUsage}
				onSend={sendMessage}
				onStop={stopActiveResponse}
				onThinkToggle={toggleThink}
				onReasoningEffortChange={setReasoningEffort}
			/>
		</div>
	</div>
</section>

<style>
	.chat-wrap {
		width: 100%;
		max-width: 100%;
		padding: 0 0.85rem;
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
		grid-template-rows: auto minmax(0, 1fr);
		gap: 0.72rem;
		min-width: 0;
	}

	.chat-body {
		--chat-canvas-bg: var(--bg-soft);
		--chat-panel-bg:
			radial-gradient(circle at 24% 0%, rgba(57, 88, 128, 0.12), transparent 27rem),
			linear-gradient(135deg, var(--glass-overlay, rgba(255, 255, 255, 0.03)), transparent 24rem),
			var(--panel-shell, var(--panel));

		position: relative;
		min-height: 0;
		min-width: 0;
		display: grid;
		grid-template-rows: minmax(0, 1fr) auto auto;
		border: 1px solid color-mix(in srgb, var(--bg-soft) 74%, var(--border));
		border-radius: 1.45rem;
		background: var(--chat-panel-bg);
		box-shadow: none;
		overflow: hidden;
	}

	.chat-body::before {
		content: '';
		position: absolute;
		inset: 0;
		z-index: 1;
		border-top: 1px solid rgba(255, 255, 255, 0.24);
		border-radius: inherit;
		pointer-events: none;
	}

	:global(:root.light) .chat-body {
		--chat-canvas-bg: #d3e1ef;
		--chat-panel-bg:
			radial-gradient(circle at 24% 0%, rgba(37, 99, 235, 0.08), transparent 27rem),
			linear-gradient(135deg, rgba(255, 255, 255, 0.28), transparent 24rem),
			#d8e6f4;

		border-color: rgba(73, 104, 145, 0.22);
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.68);
	}

	:global(:root.light) .chat-body::before {
		border-top-color: rgba(255, 255, 255, 0.78);
	}

	.chat-panel[data-mode='Chat'] {
		--mode-color: #6aa4f6;
		--mode-soft: rgba(70, 126, 205, 0.24);
		--mode-border: rgba(88, 147, 230, 0.28);
		--mode-glow: rgba(88, 147, 230, 0.15);
	}

	.chat-panel[data-mode='Plan'] {
		--mode-color: #6ee7b7;
		--mode-soft: rgba(110, 231, 183, 0.18);
		--mode-border: rgba(110, 231, 183, 0.3);
		--mode-glow: rgba(110, 231, 183, 0.16);
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
