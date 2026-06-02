<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import ClockCounterClockwiseIcon from 'phosphor-svelte/lib/ClockCounterClockwiseIcon';
	import TrashIcon from 'phosphor-svelte/lib/TrashIcon';
	import MagnifyingGlassIcon from 'phosphor-svelte/lib/MagnifyingGlassIcon';
	import { deleteChat, getChats, type ChatSummary } from '$lib/api/bitbuddy';
	import { loadPersistedChat } from '$lib/stores/chat.svelte';
	import { formatTimestamp } from '$lib/stores/time.svelte';

	let allChats = $state<ChatSummary[]>([]);
	let loading = $state(true);
	let error = $state('');
	let search = $state('');
	let modeFilter = $state<'all' | string>('all');
	let deletingId = $state<string | null>(null);

	const modes = ['all', 'chat', 'plan', 'debug'];

	let filtered = $derived(
		allChats.filter((c) => {
			const matchesMode = modeFilter === 'all' || c.mode === modeFilter;
			const matchesSearch = !search.trim() || c.title.toLowerCase().includes(search.trim().toLowerCase());
			return matchesMode && matchesSearch;
		})
	);

	onMount(() => {
		void load();
	});

	async function load() {
		loading = true;
		try {
			allChats = await getChats({ limit: 500 });
			error = '';
		} catch (e: unknown) {
			error = e instanceof Error ? e.message : 'Could not load chat history.';
		} finally {
			loading = false;
		}
	}

	async function openChat(chatId: string) {
		await loadPersistedChat(chatId);
		await goto('/');
	}

	async function doDelete(chatId: string, event: MouseEvent) {
		event.stopPropagation();
		if (deletingId === chatId) {
			try {
				await deleteChat(chatId);
				allChats = allChats.filter((c) => c.id !== chatId);
			} catch {
				// ignore
			} finally {
				deletingId = null;
			}
		} else {
			deletingId = chatId;
		}
	}

	function modeClass(mode: string) {
		if (mode === 'plan') return 'mode-plan';
		if (mode === 'debug') return 'mode-debug';
		return 'mode-chat';
	}
</script>

<svelte:head>
	<title>BitBuddy — History</title>
</svelte:head>

<div class="history-page">
	<section class="history-panel" aria-label="Chat history">
		<header class="history-header">
			<div class="title-mark" aria-hidden="true"><ClockCounterClockwiseIcon size={30} weight="duotone" /></div>
			<div class="title-copy">
				<p class="eyebrow">Conversation Log</p>
				<h1>History</h1>
				<p>{allChats.length} conversation{allChats.length === 1 ? '' : 's'} saved locally.</p>
			</div>
		</header>

		<div class="history-content">
			<div class="toolbar">
				<div class="search-wrap">
					<MagnifyingGlassIcon size={16} />
					<input
						class="search-input"
						type="search"
						placeholder="Search by title..."
						bind:value={search}
						aria-label="Search chats"
					/>
				</div>
				<div class="mode-chips" role="group" aria-label="Filter by mode">
					{#each modes as mode}
						<button
							class="chip"
							class:active={modeFilter === mode}
							type="button"
							onclick={() => { modeFilter = mode; }}
						>
							{mode === 'all' ? 'All' : mode}
						</button>
					{/each}
				</div>
			</div>

			{#if error}
				<div class="error-banner">{error}</div>
			{:else if loading}
				<div class="loading-state">Loading history...</div>
			{:else if filtered.length === 0}
				<div class="empty-state">
					{search || modeFilter !== 'all' ? 'No chats match your filters.' : 'No saved chats yet.'}
				</div>
			{:else}
				<ul class="chat-list" aria-label="Chat history">
					{#each filtered as chat (chat.id)}
						<li class="chat-card" role="presentation">
							<button class="chat-body" type="button" onclick={() => openChat(chat.id)}>
								<span class="chat-title">{chat.title}</span>
								<span class="chat-meta">
									<span class="mode-badge {modeClass(chat.mode)}">{chat.mode}</span>
									<span class="chat-time">{formatTimestamp(chat.updated_at)}</span>
								</span>
							</button>
							<button
								class="delete-btn"
								class:confirm={deletingId === chat.id}
								type="button"
								aria-label={deletingId === chat.id ? 'Confirm delete' : `Delete ${chat.title}`}
								onclick={(e) => doDelete(chat.id, e)}
								onblur={() => { if (deletingId === chat.id) deletingId = null; }}
							>
								<TrashIcon size={15} />
								{#if deletingId === chat.id}<span class="confirm-label">Delete?</span>{/if}
							</button>
						</li>
					{/each}
				</ul>
			{/if}
		</div>
	</section>
</div>

<style>
	.history-page {
		--page-accent: #a78bfa;
		--page-soft: rgba(167, 139, 250, 0.12);
		--page-border: rgba(167, 139, 250, 0.25);
		--page-glow: rgba(167, 139, 250, 0.14);

		width: 100%;
		max-width: 100%;
		padding: 0 1rem;
		height: 100%;
		margin: 0 auto;
		display: flex;
		min-height: 0;
		animation: fade-in 0.35s cubic-bezier(0.16, 1, 0.3, 1);
	}

	@keyframes fade-in {
		from { opacity: 0; transform: translateY(12px); }
		to { opacity: 1; transform: translateY(0); }
	}

	.history-panel {
		width: 100%;
		height: 100%;
		max-height: calc(100vh - 3rem);
		min-height: 0;
		display: flex;
		flex-direction: column;
		border: 1px solid var(--page-border);
		border-radius: 1.45rem;
		background:
			linear-gradient(135deg, var(--glass-overlay), transparent 22rem),
			radial-gradient(circle at top right, var(--page-glow), transparent 30rem),
			radial-gradient(circle at bottom left, rgba(110, 231, 183, 0.055), transparent 34rem),
			var(--panel);
		box-shadow: var(--shadow-chat);
		overflow: hidden;
	}

	.history-header {
		flex: 0 0 auto;
		padding: 1.35rem 1.5rem;
		display: flex;
		align-items: center;
		gap: 1rem;
		border-bottom: 1px solid var(--border);
		background:
			linear-gradient(135deg, var(--page-soft), transparent 70%),
			var(--header-bg);
	}

	.title-mark {
		width: 3.5rem;
		height: 3.5rem;
		display: grid;
		place-items: center;
		border-radius: 1.1rem;
		background: var(--surface-glass);
		border: 1px solid var(--page-border);
		color: var(--page-accent);
		box-shadow: 0 0 20px var(--page-soft);
		flex: 0 0 auto;
	}

	.title-copy {
		min-width: 0;
	}

	.eyebrow {
		color: var(--page-accent);
		font-size: 0.72rem;
		font-weight: 800;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	h1 {
		font-size: 1.65rem;
		font-weight: 900;
		letter-spacing: -0.03em;
		line-height: 1.1;
	}

	.title-copy p:last-child {
		margin: 0.15rem 0 0;
		color: var(--text-soft);
	}

	.history-content {
		min-height: 0;
		flex: 1 1 auto;
		display: flex;
		flex-direction: column;
		gap: 1rem;
		padding: 1.25rem;
		overflow-y: auto;
		scrollbar-color: var(--scrollbar-thumb) transparent;
	}

	.toolbar {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		flex-wrap: wrap;
	}

	.search-wrap {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex: 1;
		min-width: 12rem;
		padding: 0.5rem 0.85rem;
		border: 1px solid var(--border-strong);
		border-radius: 0.75rem;
		background: var(--surface-inset);
		color: var(--text-muted);
	}

	.search-wrap:focus-within {
		border-color: var(--page-accent);
		color: var(--text);
	}

	.search-input {
		flex: 1;
		border: none;
		background: transparent;
		color: var(--text);
		font-size: 0.9rem;
		outline: none;
	}

	.search-input::placeholder {
		color: var(--text-muted);
	}

	.mode-chips {
		display: flex;
		gap: 0.35rem;
	}

	.chip {
		padding: 0.4rem 0.8rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: transparent;
		color: var(--text-muted);
		font-size: 0.8rem;
		font-weight: 600;
		text-transform: capitalize;
		cursor: pointer;
		transition: all 120ms ease;
	}

	.chip:hover {
		border-color: var(--border-strong);
		color: var(--text);
	}

	.chip.active {
		border-color: var(--page-accent);
		background: var(--page-soft);
		color: var(--page-accent);
	}

	.chat-list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}

	.chat-card {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.25rem;
		border-radius: 0.85rem;
		border: 1px solid var(--border);
		background: var(--surface-card);
		box-shadow: var(--shadow-panel);
		transition: border-color 120ms ease, background 120ms ease;
	}

	.chat-card:hover {
		border-color: var(--border-strong);
		background: var(--panel-raised);
	}

	.chat-body {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: 0.3rem;
		padding: 0.65rem 1rem;
		text-align: left;
		background: transparent;
		border: none;
		cursor: pointer;
		color: inherit;
	}

	.chat-title {
		font-size: 0.95rem;
		font-weight: 600;
		color: var(--text);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 100%;
	}

	.chat-meta {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.mode-badge {
		font-size: 0.7rem;
		font-weight: 700;
		padding: 0.15rem 0.45rem;
		border-radius: 999px;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.mode-chat { background: color-mix(in srgb, var(--accent) 15%, transparent); color: var(--accent); }
	.mode-plan { background: color-mix(in srgb, var(--success) 15%, transparent); color: var(--success); }
	.mode-debug { background: color-mix(in srgb, var(--warning) 15%, transparent); color: var(--warning); }

	.chat-time {
		font-size: 0.8rem;
		color: var(--text-soft);
	}

	.delete-btn {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		flex-shrink: 0;
		padding: 0.5rem 0.65rem;
		margin-right: 0.25rem;
		border-radius: 0.65rem;
		border: none;
		background: transparent;
		color: var(--text-soft);
		font-size: 0.8rem;
		cursor: pointer;
		transition: all 120ms ease;
	}

	.delete-btn:hover {
		background: color-mix(in srgb, var(--danger) 12%, transparent);
		color: var(--danger);
	}

	.delete-btn.confirm {
		background: color-mix(in srgb, var(--danger) 18%, transparent);
		color: var(--danger);
	}

	.confirm-label {
		font-weight: 700;
	}

	.loading-state,
	.empty-state {
		flex: 1 1 auto;
		min-height: 18rem;
		padding: 3rem;
		display: flex;
		align-items: center;
		justify-content: center;
		text-align: center;
		color: var(--text-soft);
		font-size: 0.95rem;
	}

	.error-banner {
		padding: 0.85rem 1.25rem;
		border-radius: 0.75rem;
		background: color-mix(in srgb, var(--danger) 12%, transparent);
		border: 1px solid color-mix(in srgb, var(--danger) 30%, transparent);
		color: var(--danger);
		font-size: 0.9rem;
	}

	@media (max-width: 900px) {
		.history-page,
		.history-panel {
			height: auto;
			max-height: none;
		}
	}

	@media (max-width: 640px) {
		.history-page {
			padding: 0;
		}

		.history-header {
			align-items: flex-start;
		}

		.title-mark {
			width: 3rem;
			height: 3rem;
		}

		.mode-chips {
			width: 100%;
			overflow-x: auto;
			padding-bottom: 0.2rem;
		}
	}
</style>
