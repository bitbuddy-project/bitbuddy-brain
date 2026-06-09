<script lang="ts">
	import { onMount } from 'svelte';
	import ArrowClockwiseIcon from 'phosphor-svelte/lib/ArrowClockwiseIcon';
	import EnvelopeSimpleIcon from 'phosphor-svelte/lib/EnvelopeSimpleIcon';
	import TrashIcon from 'phosphor-svelte/lib/TrashIcon';
	import {
		createSenderTrashRule,
		emptyEmailTrash,
		getEmailMailboxes,
		getEmailMessages,
		getEmailOverview,
		readEmailMessage,
		searchEmailMessages,
		trashEmailMessage,
		type EmailConfig,
		type EmailMailbox,
		type EmailMessage
	} from '$lib/api/bitbuddy';

	type EmailOverview = EmailConfig & { permissions?: Record<string, string>; account_id?: string };

	let loading = $state(true);
	let mailboxLoading = $state(false);
	let messageLoading = $state(false);
	let error = $state('');
	let query = $state('');
	let selectedMailbox = $state('INBOX');
	let overview = $state<EmailOverview | null>(null);
	let mailboxes = $state<EmailMailbox[]>([]);
	let messages = $state<EmailMessage[]>([]);
	let selectedMessage = $state<EmailMessage | null>(null);
	let messageAction = $state(false);
	let loadingMore = $state(false);
	let emptyTrashConfirm = $state(false);
	let ruleConfirm = $state(false);
	let actionStatus = $state('');
	let nextPageToken = $state('');
	let resultSizeEstimate = $state<number | null>(null);
	let messageRequestId = 0;
	const pageSize = 50;

	const mailboxDisplayNames: Record<string, string> = {
		INBOX: 'Inbox',
		SENT: 'Sent',
		DRAFT: 'Drafts',
		SPAM: 'Spam',
		TRASH: 'Trash',
		STARRED: 'Starred',
		IMPORTANT: 'Important',
		UNREAD: 'Unread'
	};
	const mailboxOrder = ['INBOX', 'STARRED', 'IMPORTANT', 'UNREAD', 'SENT', 'DRAFT', 'SPAM', 'TRASH'];
	const hiddenGmailLabels = new Set(['CHAT', 'YELLOW_STAR', 'CATEGORY_FORUMS', 'CATEGORY_UPDATES', 'CATEGORY_PERSONAL', 'CATEGORY_PROMOTIONS', 'CATEGORY_SOCIAL']);
	const systemMailboxIds = new Set(mailboxOrder);

	let primaryMailboxes = $derived(
		mailboxes
			.filter((mailbox) => systemMailboxIds.has(mailbox.name) && !hiddenGmailLabels.has(mailbox.name))
			.sort((left, right) => mailboxOrder.indexOf(left.name) - mailboxOrder.indexOf(right.name))
	);
	let labelMailboxes = $derived(
		mailboxes
			.filter((mailbox) => !systemMailboxIds.has(mailbox.name) && !hiddenGmailLabels.has(mailbox.name))
			.sort((left, right) => mailboxLabel(left).localeCompare(mailboxLabel(right)))
	);

	onMount(() => {
		void load();
	});

	async function load() {
		loading = true;
		try {
			overview = await getEmailOverview();
			selectedMailbox = overview.default_mailbox || 'INBOX';
			if (overview.enabled && (overview.provider !== 'gmail' || overview.gmail_connected)) {
				await loadMailboxData();
			}
			error = '';
		} catch (caught) {
			error = caught instanceof Error ? caught.message : 'Could not load email status.';
		} finally {
			loading = false;
		}
	}

	async function loadMailboxData() {
		mailboxLoading = true;
		try {
			mailboxes = await getEmailMailboxes();
			if (!selectedMailbox) selectedMailbox = overview?.default_mailbox || mailboxes[0]?.name || 'INBOX';
			await loadMessages();
		} finally {
			mailboxLoading = false;
		}
	}

	async function loadMessages(options: { clear?: boolean; append?: boolean } = {}) {
		const requestId = ++messageRequestId;
		const mailbox = selectedMailbox;
		const searchQuery = query.trim();
		const pageToken = options.append ? nextPageToken : '';
		messageLoading = !options.append;
		loadingMore = Boolean(options.append);
		if (options.clear) {
			messages = [];
			selectedMessage = null;
			nextPageToken = '';
			resultSizeEstimate = null;
		}
		try {
			const page = searchQuery
				? await searchEmailMessages(searchQuery, mailbox, pageSize, pageToken)
				: await getEmailMessages(mailbox, pageSize, pageToken);
			if (requestId !== messageRequestId) return;
			messages = options.append ? [...messages, ...page.messages] : page.messages;
			nextPageToken = page.next_page_token || '';
			resultSizeEstimate = page.result_size_estimate ?? selectedMailboxCount();
			if (!options.append) selectedMessage = null;
			error = '';
		} catch (caught) {
			if (requestId !== messageRequestId) return;
			error = caught instanceof Error ? caught.message : 'Could not load inbox messages.';
		} finally {
			if (requestId === messageRequestId) {
				messageLoading = false;
				loadingMore = false;
			}
		}
	}

	async function loadMoreMessages() {
		if (!nextPageToken || messageLoading || loadingMore) return;
		await loadMessages({ append: true });
	}

	async function chooseMailbox(mailbox: string) {
		if (mailbox === selectedMailbox && !query.trim()) return;
		selectedMailbox = mailbox;
		query = '';
		emptyTrashConfirm = false;
		await loadMessages({ clear: true });
	}

	async function openMessage(message: EmailMessage) {
		messageLoading = true;
		ruleConfirm = false;
		actionStatus = '';
		try {
			selectedMessage = await readEmailMessage(message.id, message.mailbox || selectedMailbox);
			error = '';
		} catch (caught) {
			error = caught instanceof Error ? caught.message : 'Could not read email message.';
		} finally {
			messageLoading = false;
		}
	}

	async function trashSelectedMessage() {
		if (!selectedMessage || messageAction) return;
		messageAction = true;
		try {
			await trashEmailMessage(selectedMessage.id, selectedMessage.mailbox || selectedMailbox);
			messages = messages.filter((message) => message.id !== selectedMessage?.id);
			actionStatus = 'Moved to Trash.';
			selectedMessage = null;
			error = '';
		} catch (caught) {
			error = caught instanceof Error ? caught.message : 'Could not move email to Trash.';
		} finally {
			messageAction = false;
		}
	}

	async function emptyTrash() {
		if (selectedMailbox !== 'TRASH' || messageAction) return;
		if (!emptyTrashConfirm) {
			emptyTrashConfirm = true;
			actionStatus = 'Click again to permanently delete every message in Trash.';
			return;
		}
		messageAction = true;
		try {
			const result = await emptyEmailTrash();
			actionStatus = `Emptied Trash. Permanently deleted ${result.deleted} message${result.deleted === 1 ? '' : 's'}.`;
			messages = [];
			selectedMessage = null;
			nextPageToken = '';
			resultSizeEstimate = 0;
			emptyTrashConfirm = false;
			mailboxes = mailboxes.map((mailbox) => mailbox.name === 'TRASH' ? { ...mailbox, messages_total: 0, messages_unread: 0, threads_total: 0, threads_unread: 0 } : mailbox);
			void getEmailMailboxes().then((next) => (mailboxes = next)).catch(() => undefined);
			error = '';
		} catch (caught) {
			error = caught instanceof Error ? caught.message : 'Could not empty Trash.';
		} finally {
			messageAction = false;
		}
	}

	async function autoTrashSender(applyExisting: boolean) {
		if (!selectedMessage || messageAction) return;
		messageAction = true;
		try {
			const result = await createSenderTrashRule(selectedMessage.from_addr, { mailbox: selectedMailbox, applyExisting });
			actionStatus = applyExisting
				? `Auto-trash enabled. Moved ${result.applied} existing matching email${result.applied === 1 ? '' : 's'}.`
				: 'Auto-trash enabled for future emails from this sender.';
			ruleConfirm = false;
			selectedMessage = null;
			await loadMessages({ clear: true });
			error = '';
		} catch (caught) {
			error = caught instanceof Error ? caught.message : 'Could not create auto-trash rule.';
		} finally {
			messageAction = false;
		}
	}

	function mailboxLabel(mailbox: EmailMailbox) {
		const label = mailboxDisplayNames[mailbox.name] || mailbox.flags[0] || mailbox.name;
		return label.replace(/^\[Gmail\]\//, '');
	}

	function selectedMailboxLabel() {
		const mailbox = mailboxes.find((item) => item.name === selectedMailbox);
		return mailbox ? mailboxLabel(mailbox) : mailboxDisplayNames[selectedMailbox] || selectedMailbox || 'mail';
	}

	function selectedMailboxCount() {
		const mailbox = mailboxes.find((item) => item.name === selectedMailbox);
		return mailbox?.messages_total ?? null;
	}

	function mailboxBadgeValue(mailbox: EmailMailbox) {
		const unread = mailbox.messages_unread ?? 0;
		if (unread > 0) return unread;
		return mailbox.messages_total ?? null;
	}

	function mailboxBadgeLabel(mailbox: EmailMailbox) {
		const value = mailboxBadgeValue(mailbox);
		return value === null ? '' : compactCount(value);
	}

	function mailboxBadgeKind(mailbox: EmailMailbox) {
		return (mailbox.messages_unread ?? 0) > 0 ? 'unread' : 'total';
	}

	function compactCount(value: number) {
		if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(value >= 10_000_000 ? 0 : 1)}m`;
		if (value >= 1_000) return `${(value / 1_000).toFixed(value >= 10_000 ? 0 : 1)}k`;
		return String(value);
	}

	function messageCountLabel() {
		const total = resultSizeEstimate ?? selectedMailboxCount();
		if (total === null || total === undefined) return `Showing ${messages.length}`;
		return `Showing ${messages.length} of ${compactCount(total)}`;
	}

	function showEmptyTrashButton() {
		return selectedMailbox === 'TRASH' && (messages.length > 0 || (selectedMailboxCount() ?? 0) > 0);
	}

	function formatDate(value: string) {
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return value;
		return date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
	}
</script>

<svelte:head>
	<title>BitBuddy Email</title>
</svelte:head>

<div class="email-page">
	<section class="email-panel" aria-label="Email inbox">
		<header class="email-header">
			<div class="title-mark" aria-hidden="true"><EnvelopeSimpleIcon size={30} weight="duotone" /></div>
			<div class="title-copy">
				<p class="eyebrow">Inbox</p>
				<h1>Email</h1>
				<p>Read-only mail awareness will live here. Account setup is in Settings.</p>
			</div>
			<a class="settings-link" href="/settings">Email settings</a>
		</header>

		<div class="email-content">
			{#if error}
				<div class="notice danger">{error}</div>
			{:else if loading}
				<div class="empty-card">Loading email status...</div>
			{:else if !overview?.enabled}
				<section class="empty-card primary-empty">
					<div class="empty-icon"><EnvelopeSimpleIcon size={28} weight="duotone" /></div>
					<div>
						<p class="eyebrow">Not Connected</p>
						<h2>Email is not configured yet</h2>
						<p>Connect IMAP or Gmail in Settings when you want BitBuddy to read/search mail safely.</p>
					</div>
					<a href="/settings">Open Settings</a>
				</section>
			{:else if overview.provider === 'gmail' && !overview.gmail_connected}
				<section class="empty-card primary-empty">
					<div class="empty-icon"><EnvelopeSimpleIcon size={28} weight="duotone" /></div>
					<div>
						<p class="eyebrow">Gmail Ready</p>
						<h2>Gmail is configured but not connected</h2>
						<p>Connect Gmail in Settings to authorize read-only inbox access.</p>
					</div>
					<a href="/settings">Open Settings</a>
				</section>
			{:else}
				<section class="inbox-shell">
					<aside class="inbox-rail">
						<div class="rail-heading">
							<p class="eyebrow">Account</p>
							<strong>{overview.account_label || overview.email_address || 'Email account'}</strong>
							<small>{overview.provider.toUpperCase()} · read-only</small>
						</div>
						<div class="mailbox-list" aria-label="Mailboxes">
							{#if mailboxLoading && mailboxes.length === 0}
								<div class="mailbox-pill muted">Loading...</div>
							{:else}
								<div class="mailbox-section">
									<p>Mailboxes</p>
									{#each primaryMailboxes as mailbox (mailbox.name)}
										<button class="mailbox-pill folder" class:active={selectedMailbox === mailbox.name} type="button" onclick={() => chooseMailbox(mailbox.name)}>
											<span class="mailbox-glyph" aria-hidden="true"></span>
											<span class="mailbox-name">{mailboxLabel(mailbox)}</span>
											{#if mailboxBadgeValue(mailbox) !== null}
												<span class="mailbox-badge" class:unread={mailboxBadgeKind(mailbox) === 'unread'}>{mailboxBadgeLabel(mailbox)}</span>
											{/if}
										</button>
									{/each}
								</div>
								{#if labelMailboxes.length > 0}
									<div class="mailbox-section">
										<p>Labels</p>
										{#each labelMailboxes as mailbox (mailbox.name)}
											<button class="mailbox-pill label" class:active={selectedMailbox === mailbox.name} type="button" onclick={() => chooseMailbox(mailbox.name)}>
												<span class="mailbox-glyph" aria-hidden="true"></span>
												<span class="mailbox-name">{mailboxLabel(mailbox)}</span>
												{#if mailboxBadgeValue(mailbox) !== null}
													<span class="mailbox-badge" class:unread={mailboxBadgeKind(mailbox) === 'unread'}>{mailboxBadgeLabel(mailbox)}</span>
												{/if}
											</button>
										{/each}
									</div>
								{/if}
							{/if}
						</div>
					</aside>
					<section class="message-list-panel" aria-label="Messages">
						<form class="search-row" onsubmit={(event) => { event.preventDefault(); void loadMessages(); }}>
							<input bind:value={query} placeholder={`Search ${selectedMailboxLabel()}...`} />
							{#if showEmptyTrashButton()}
								<button class="empty-trash-action" class:confirm={emptyTrashConfirm} type="button" onclick={emptyTrash} disabled={messageAction || messageLoading || loadingMore}>
									{emptyTrashConfirm ? 'Confirm empty' : 'Empty Trash'}
								</button>
							{/if}
							<button type="submit" class:icon-only={!query.trim()} aria-label={query.trim() ? 'Search email' : 'Refresh inbox'} disabled={messageLoading}>
								{#if query.trim()}
									Search
								{:else}
									<ArrowClockwiseIcon size={18} weight="bold" />
								{/if}
							</button>
						</form>
						{#if !messageLoading || messages.length > 0}
							<div class="message-list-meta">
								<span>{messageCountLabel()}</span>
								{#if nextPageToken}<span>More available</span>{/if}
							</div>
						{/if}

						<div class="message-list">
							{#if messageLoading && messages.length === 0}
								<div class="empty-list">Loading messages...</div>
							{:else if messages.length === 0}
								<div class="empty-list">No messages found in {selectedMailboxLabel()}.</div>
							{:else}
								{#each messages as message (message.mailbox + ':' + message.id)}
									<button class="message-row" class:active={selectedMessage?.id === message.id} type="button" onclick={() => openMessage(message)}>
										<span class="message-topline"><strong>{message.subject || '(no subject)'}</strong><time>{formatDate(message.date)}</time></span>
										<span class="sender">{message.from_addr || 'Unknown sender'}</span>
										<span class="snippet">{message.snippet}</span>
									</button>
								{/each}
								{#if nextPageToken}
									<div class="load-more-wrap">
										<button class="load-more" type="button" onclick={loadMoreMessages} disabled={loadingMore || messageLoading}>
											{loadingMore ? 'Loading more...' : 'Load more'}
										</button>
									</div>
								{/if}
							{/if}
						</div>
					</section>

					<aside class="guard-card">
						{#if selectedMessage}
							<div class="preview-body">
								<div class="preview-heading">
									<p class="eyebrow">Message preview</p>
									<h2>{selectedMessage.subject || '(no subject)'}</h2>
									<p>{selectedMessage.from_addr}</p>
									<time>{formatDate(selectedMessage.date)}</time>
								</div>
								<div class="preview-actions">
									<button class="trash-action" type="button" onclick={trashSelectedMessage} disabled={messageAction}>
										<TrashIcon size={15} weight="bold" /> Move to Trash
									</button>
									<button class="secondary-preview-action" type="button" onclick={() => (ruleConfirm = !ruleConfirm)} disabled={messageAction}>Auto-trash sender</button>
								</div>
								{#if ruleConfirm}
									<div class="rule-confirm">
										<p>Automatically move future emails from this sender to Trash?</p>
										<div>
											<button type="button" onclick={() => autoTrashSender(false)} disabled={messageAction}>Future only</button>
											<button type="button" onclick={() => autoTrashSender(true)} disabled={messageAction}>Also existing</button>
										</div>
									</div>
								{/if}
								<pre>{selectedMessage.body || selectedMessage.snippet || 'No readable body found.'}</pre>
							</div>
						{:else}
							<EnvelopeSimpleIcon size={22} weight="duotone" />
							<div>
								<strong>Select a message</strong>
								<p>{actionStatus || 'Choose an email from the list to preview it here.'}</p>
							</div>
						{/if}
					</aside>
				</section>
			{/if}
		</div>
	</section>
</div>

<style>
	.email-page {
		--page-accent: var(--accent);
		--page-soft: color-mix(in srgb, var(--accent-soft) 72%, transparent);
		--page-border: color-mix(in srgb, var(--accent) 20%, var(--border));
		--page-glow: color-mix(in srgb, var(--accent) 10%, transparent);

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

	.email-panel {
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
			radial-gradient(circle at bottom left, color-mix(in srgb, var(--success) 5.5%, transparent), transparent 34rem),
			var(--panel);
		box-shadow: var(--shadow-chat);
		overflow: hidden;
	}

	.email-header {
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
		flex: 1;
	}

	.eyebrow {
		color: var(--page-accent);
		font-size: 0.72rem;
		font-weight: 800;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	h1,
	h2 {
		margin: 0;
		letter-spacing: -0.03em;
	}

	h1 {
		font-size: 1.65rem;
		font-weight: 900;
		line-height: 1.1;
	}

	h2 {
		font-size: 1.15rem;
		font-weight: 850;
	}

	.title-copy p:last-child {
		margin: 0.15rem 0 0;
	}

	p {
		margin: 0;
		color: var(--text-soft);
		line-height: 1.5;
	}

	.settings-link,
	.empty-card a {
		border-radius: 999px;
		padding: 0.68rem 0.9rem;
		background: var(--accent);
		color: var(--on-accent);
		font-weight: 850;
		white-space: nowrap;
		flex-shrink: 0;
	}

	.empty-icon {
		display: grid;
		place-items: center;
		width: 3.6rem;
		height: 3.6rem;
		border-radius: 1.1rem;
		border: 1px solid color-mix(in srgb, var(--accent) 24%, var(--border));
		background: var(--surface-glass);
		color: var(--accent);
	}

	.email-content {
		min-height: 0;
		flex: 1 1 auto;
		display: flex;
		flex-direction: column;
		gap: 1rem;
		padding: 1.25rem;
		overflow-y: auto;
		scrollbar-color: var(--scrollbar-thumb) transparent;
	}

	.empty-card {
		min-height: 20rem;
		display: grid;
		place-items: center;
		text-align: center;
		color: var(--text-soft);
	}

	.primary-empty {
		place-items: stretch;
		align-content: center;
		justify-items: center;
		gap: 1rem;
	}

	.notice.danger {
		padding: 0.9rem 1rem;
		border: 1px solid color-mix(in srgb, var(--danger) 35%, transparent);
		border-radius: 1rem;
		background: color-mix(in srgb, var(--danger) 10%, transparent);
		color: var(--danger);
	}

	.inbox-shell {
		height: 100%;
		min-height: 24rem;
		display: grid;
		grid-template-columns: 14rem minmax(20rem, 0.85fr) minmax(18rem, 1fr);
		gap: 1rem;
	}

	.inbox-rail,
	.message-list-panel,
	.guard-card {
		min-height: 0;
		border: 1px solid var(--border);
		border-radius: 1.05rem;
		background: var(--surface-card);
		overflow: hidden;
	}

	.inbox-rail,
	.guard-card {
		padding: 1rem;
	}

	.inbox-rail {
		display: flex;
		min-height: 0;
		flex-direction: column;
	}

	.rail-heading {
		margin-bottom: 1rem;
	}

	.rail-heading strong {
		display: block;
		margin-top: 0.25rem;
		color: var(--text);
	}

	.rail-heading small,
	.sender,
	.snippet,
	.message-topline time,
	.preview-heading time {
		color: var(--text-soft);
		font-size: 0.78rem;
	}

	.mailbox-list {
		min-height: 0;
		display: grid;
		gap: 1rem;
		overflow: auto;
		padding-right: 0.15rem;
	}

	.mailbox-section {
		display: grid;
		gap: 0.38rem;
	}

	.mailbox-section > p {
		padding: 0 0.35rem;
		color: var(--text-soft);
		font-size: 0.68rem;
		font-weight: 850;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.mailbox-pill {
		width: 100%;
		display: flex;
		align-items: center;
		gap: 0.58rem;
		padding: 0.65rem 0.75rem;
		border: 1px solid transparent;
		border-radius: 0.8rem;
		background: transparent;
		color: var(--text-soft);
		font-weight: 800;
		text-align: left;
	}

	.mailbox-name {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.mailbox-badge {
		flex: 0 0 auto;
		min-width: 1.55rem;
		max-width: 4.5rem;
		padding: 0.16rem 0.42rem;
		border: 1px solid color-mix(in srgb, var(--border) 76%, transparent);
		border-radius: 999px;
		background: color-mix(in srgb, var(--surface-inset) 78%, transparent);
		color: var(--text-soft);
		font-size: 0.68rem;
		font-weight: 900;
		line-height: 1;
		text-align: center;
	}

	.mailbox-badge.unread {
		border-color: color-mix(in srgb, var(--accent) 48%, var(--border));
		background: color-mix(in srgb, var(--accent) 82%, #ffffff 0%);
		color: var(--on-accent);
		box-shadow: 0 0 1rem color-mix(in srgb, var(--accent) 20%, transparent);
	}

	.mailbox-glyph {
		position: relative;
		width: 0.95rem;
		height: 0.75rem;
		flex: 0 0 auto;
		border-radius: 0.16rem;
		background: color-mix(in srgb, var(--accent) 18%, var(--surface-glass));
		border: 1px solid color-mix(in srgb, var(--accent) 28%, var(--border));
	}

	.mailbox-pill.folder .mailbox-glyph::before {
		content: '';
		position: absolute;
		left: 0.08rem;
		top: -0.28rem;
		width: 0.48rem;
		height: 0.28rem;
		border-radius: 0.15rem 0.15rem 0 0;
		background: color-mix(in srgb, var(--accent) 22%, var(--surface-glass));
		border: 1px solid color-mix(in srgb, var(--accent) 28%, var(--border));
		border-bottom: 0;
	}

	.mailbox-pill.label .mailbox-glyph {
		width: 0.78rem;
		height: 0.78rem;
		border-radius: 999px;
		background: color-mix(in srgb, var(--success) 18%, var(--surface-glass));
		border-color: color-mix(in srgb, var(--success) 30%, var(--border));
	}

	.mailbox-pill:hover,
	.mailbox-pill.active {
		border-color: color-mix(in srgb, var(--accent) 24%, var(--border));
		background: var(--surface-glass);
		color: var(--text);
	}

	.mailbox-pill.muted {
		color: var(--text-soft);
		pointer-events: none;
	}

	.message-list-panel {
		display: flex;
		flex-direction: column;
	}

	.search-row {
		display: flex;
		gap: 0.55rem;
		padding: 0.85rem;
		border-bottom: 1px solid var(--border);
		background: color-mix(in srgb, var(--surface-inset) 42%, transparent);
	}

	.search-row input {
		min-width: 0;
		flex: 1;
		border: 1px solid var(--border);
		border-radius: 0.75rem;
		background: var(--surface-inset);
		color: var(--text);
		font: inherit;
		padding: 0.65rem 0.75rem;
	}

	.search-row button {
		display: inline-grid;
		place-items: center;
		border-radius: 0.75rem;
		background: var(--accent);
		color: var(--on-accent);
		font-weight: 850;
		padding: 0.65rem 0.8rem;
	}

	.search-row .empty-trash-action {
		border: 1px solid color-mix(in srgb, var(--danger) 42%, var(--border));
		background: color-mix(in srgb, var(--danger) 18%, var(--surface-inset));
		color: color-mix(in srgb, var(--danger) 76%, var(--text));
		white-space: nowrap;
	}

	.search-row .empty-trash-action.confirm {
		background: var(--danger);
		color: #fff;
	}

	.search-row button.icon-only {
		aspect-ratio: 1;
		padding: 0.65rem;
	}

	.message-list-meta {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
		padding: 0.48rem 0.85rem;
		border-bottom: 1px solid color-mix(in srgb, var(--border) 66%, transparent);
		background: color-mix(in srgb, var(--surface-inset) 24%, transparent);
		color: var(--text-soft);
		font-size: 0.72rem;
		font-weight: 750;
	}

	.message-list {
		min-height: 0;
		overflow: auto;
	}

	.message-row {
		width: 100%;
		display: grid;
		gap: 0.28rem;
		padding: 0.85rem;
		border-bottom: 1px solid color-mix(in srgb, var(--border) 72%, transparent);
		background: transparent;
		color: var(--text);
		text-align: left;
	}

	.message-row:hover,
	.message-row.active {
		background: color-mix(in srgb, var(--accent-soft) 38%, transparent);
	}

	.load-more-wrap {
		padding: 0.9rem;
		display: grid;
		place-items: center;
	}

	.load-more {
		border: 1px solid color-mix(in srgb, var(--accent) 28%, var(--border));
		border-radius: 999px;
		background: color-mix(in srgb, var(--accent-soft) 34%, transparent);
		color: var(--text);
		font-weight: 850;
		padding: 0.58rem 0.95rem;
	}

	.load-more:disabled {
		opacity: 0.6;
		cursor: wait;
	}

	.message-topline {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		gap: 0.75rem;
	}

	.message-topline strong,
	.sender,
	.snippet {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.message-topline strong {
		font-size: 0.92rem;
	}

	.message-topline time {
		flex: 0 0 auto;
		white-space: nowrap;
	}

	.empty-list {
		min-height: 12rem;
		display: grid;
		place-items: center;
		padding: 1.25rem;
		color: var(--text-soft);
		text-align: center;
	}

	.guard-card {
		display: flex;
		min-height: 0;
		align-items: flex-start;
		gap: 0.75rem;
		color: var(--accent);
		overflow: auto;
	}

	.guard-card strong {
		color: var(--text);
	}

	.preview-body {
		width: 100%;
		min-width: 0;
	}

	.preview-heading {
		display: grid;
		gap: 0.35rem;
		color: var(--text);
	}

	.preview-heading h2 {
		line-height: 1.18;
	}

	.preview-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
		margin-top: 1rem;
	}

	.preview-actions button,
	.rule-confirm button {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		border-radius: 0.72rem;
		font-weight: 850;
		padding: 0.55rem 0.72rem;
	}

	.trash-action {
		background: var(--danger);
		color: #fff;
	}

	.secondary-preview-action,
	.rule-confirm button {
		border: 1px solid var(--border);
		background: var(--surface-glass);
		color: var(--text);
	}

	.preview-actions button:disabled,
	.rule-confirm button:disabled {
		opacity: 0.55;
		cursor: not-allowed;
	}

	.rule-confirm {
		display: grid;
		gap: 0.65rem;
		margin-top: 0.8rem;
		padding: 0.85rem;
		border: 1px solid color-mix(in srgb, var(--warning) 34%, var(--border));
		border-radius: 0.9rem;
		background: color-mix(in srgb, var(--warning) 8%, transparent);
	}

	.rule-confirm div {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
	}

	.guard-card pre {
		margin: 1rem 0 0;
		white-space: pre-wrap;
		color: var(--text);
		font: inherit;
		line-height: 1.55;
	}

	@media (max-width: 980px) {
		.email-page,
		.email-panel {
			height: auto;
			max-height: none;
		}

		.email-header {
			align-items: flex-start;
			flex-wrap: wrap;
		}

		.inbox-shell {
			grid-template-columns: 1fr;
			height: auto;
		}
	}
</style>
