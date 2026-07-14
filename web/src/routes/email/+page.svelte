<script lang="ts">
	import { onMount } from 'svelte';
	import ArrowClockwiseIcon from 'phosphor-svelte/lib/ArrowClockwiseIcon';
	import EnvelopeSimpleIcon from 'phosphor-svelte/lib/EnvelopeSimpleIcon';
	import TrashIcon from 'phosphor-svelte/lib/TrashIcon';
	import TrayIcon from 'phosphor-svelte/lib/TrayIcon';
	import StarIcon from 'phosphor-svelte/lib/StarIcon';
	import PushPinIcon from 'phosphor-svelte/lib/PushPinIcon';
	import PaperPlaneTiltIcon from 'phosphor-svelte/lib/PaperPlaneTiltIcon';
	import NoteIcon from 'phosphor-svelte/lib/NoteIcon';
	import WarningIcon from 'phosphor-svelte/lib/WarningIcon';
	import FolderIcon from 'phosphor-svelte/lib/FolderIcon';
	import TagIcon from 'phosphor-svelte/lib/TagIcon';
	import UserCircleIcon from 'phosphor-svelte/lib/UserCircleIcon';
	import MagnifyingGlassIcon from 'phosphor-svelte/lib/MagnifyingGlassIcon';
	import XIcon from 'phosphor-svelte/lib/XIcon';
	import {
		createSenderTrashRule,
		deleteEmailMessage,
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
	import { escapeHtml } from '$lib/markdown';
	import { maskHtml, revealMaskedChips } from '$lib/mask';
	import Skeleton from '$lib/components/Skeleton.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
	import { emailCache, pageKey, cacheIsFresh, invalidateMailbox } from '$lib/stores/email.svelte';

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
	let mobilePane = $state<'messages' | 'preview'>('messages');
	let mailboxOverlayOpen = $state(false);
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

	const mailboxIcons: Record<string, typeof TrayIcon> = {
		INBOX: TrayIcon,
		STARRED: StarIcon,
		IMPORTANT: PushPinIcon,
		UNREAD: EnvelopeSimpleIcon,
		SENT: PaperPlaneTiltIcon,
		DRAFT: NoteIcon,
		SPAM: WarningIcon,
		TRASH: TrashIcon
	};

	function mailboxIcon(name: string): typeof TrayIcon {
		return mailboxIcons[name] ?? FolderIcon;
	}

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
		// Paint instantly from cache, then revalidate in the background.
		const hydrated = hydrateFromCache();
		loading = !hydrated;
		try {
			overview = await getEmailOverview();
			emailCache.overview = overview;
			if (!selectedMailbox) selectedMailbox = overview.default_mailbox || 'INBOX';
			if (overview.enabled && (overview.provider !== 'gmail' || overview.gmail_connected)) {
				await loadMailboxData();
			}
			emailCache.fetchedAt = Date.now();
			error = '';
		} catch (caught) {
			if (!hydrated) error = caught instanceof Error ? caught.message : 'Could not load email status.';
		} finally {
			loading = false;
		}
	}

	function hydrateFromCache(): boolean {
		if (!emailCache.overview) return false;
		overview = emailCache.overview;
		mailboxes = emailCache.mailboxes;
		selectedMailbox = emailCache.selectedMailbox || overview.default_mailbox || 'INBOX';
		const cachedPage = emailCache.pages[pageKey(selectedMailbox, '')];
		if (cachedPage) {
			messages = cachedPage.messages;
			nextPageToken = cachedPage.nextPageToken;
			resultSizeEstimate = cachedPage.resultSizeEstimate;
		}
		return true;
	}

	async function loadMailboxData() {
		mailboxLoading = mailboxes.length === 0;
		try {
			mailboxes = await getEmailMailboxes();
			emailCache.mailboxes = mailboxes;
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
		const cached = !options.append ? emailCache.pages[pageKey(mailbox, searchQuery)] : undefined;
		// Show cached results immediately if we have them; otherwise show a skeleton.
		messageLoading = !options.append && !cached;
		loadingMore = Boolean(options.append);
		if (!options.append) {
			emailCache.selectedMailbox = mailbox;
			if (cached) {
				messages = cached.messages;
				nextPageToken = cached.nextPageToken;
				resultSizeEstimate = cached.resultSizeEstimate;
			} else if (options.clear) {
				messages = [];
				selectedMessage = null;
				nextPageToken = '';
				resultSizeEstimate = null;
			}
		}
		try {
			const page = searchQuery
				? await searchEmailMessages(searchQuery, mailbox, pageSize, pageToken)
				: await getEmailMessages(mailbox, pageSize, pageToken);
			if (requestId !== messageRequestId) return;
			messages = options.append ? [...messages, ...page.messages] : page.messages;
			nextPageToken = page.next_page_token || '';
			resultSizeEstimate = page.result_size_estimate ?? selectedMailboxCount();
			if (!options.append && !cached) selectedMessage = null;
			emailCache.pages[pageKey(mailbox, searchQuery)] = {
				messages,
				nextPageToken,
				resultSizeEstimate
			};
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
		mobilePane = 'messages';
		mailboxOverlayOpen = false;
		if (mailbox === selectedMailbox && !query.trim()) return;
		selectedMailbox = mailbox;
		query = '';
		emptyTrashConfirm = false;
		await loadMessages({ clear: true });
	}

	async function openMessage(message: EmailMessage) {
		mobilePane = 'preview';
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
			if (selectedMailbox === 'TRASH') {
				await deleteEmailMessage(selectedMessage.id, selectedMessage.mailbox || selectedMailbox);
				actionStatus = `Permanently deleted "${selectedMessage.subject || selectedMessage.id}" from Trash.`;
			} else {
				await trashEmailMessage(selectedMessage.id, selectedMessage.mailbox || selectedMailbox);
				actionStatus = `Moved "${selectedMessage.subject || selectedMessage.id}" to Trash. This is not permanent deletion.`;
			}
			messages = messages.filter((message) => message.id !== selectedMessage?.id);
			selectedMessage = null;
			invalidateMailbox(selectedMailbox);
			invalidateMailbox('TRASH');
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
			invalidateMailbox('TRASH');
			mailboxes = mailboxes.map((mailbox) => mailbox.name === 'TRASH' ? { ...mailbox, messages_total: 0, messages_unread: 0, threads_total: 0, threads_unread: 0 } : mailbox);
			emailCache.mailboxes = mailboxes;
			void getEmailMailboxes().then((next) => { mailboxes = next; emailCache.mailboxes = next; }).catch(() => undefined);
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
				? `Auto-trash enabled. Moved ${result.applied} existing matching email${result.applied === 1 ? '' : 's'} to Trash, not permanently deleted.`
				: 'Auto-trash enabled for future emails from this sender. Matching mail will move to Trash, not permanent deletion.';
			ruleConfirm = false;
			selectedMessage = null;
			invalidateMailbox(selectedMailbox);
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
		return selectedMailbox === 'TRASH' && (overview?.provider !== 'gmail' || overview.gmail_full_mail_access) && (messages.length > 0 || (selectedMailboxCount() ?? 0) > 0);
	}

	function gmailTrashDeleteUnavailable() {
		return selectedMailbox === 'TRASH' && overview?.provider === 'gmail' && !overview.gmail_full_mail_access;
	}

	function formatDate(value: string) {
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return value;
		return date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
	}

	function emailPreviewDocument(bodyHtml: string) {
		const document = new DOMParser().parseFromString(bodyHtml, 'text/html');
		for (const element of document.querySelectorAll('script, iframe, object, embed, base, meta')) element.remove();
		for (const element of document.querySelectorAll('*')) {
			for (const attribute of [...element.attributes]) {
				if (attribute.name.toLowerCase().startsWith('on') || attribute.name.toLowerCase() === 'srcdoc') element.removeAttribute(attribute.name);
			}
		}
		const style = document.createElement('style');
		style.textContent = 'html { background: #fff; } body { margin: 0; } img { max-width: 100%; height: auto; } table { max-width: 100%; }';
		document.head.append(style);
		return `<!doctype html>${document.documentElement.outerHTML}`;
	}
</script>

<svelte:head>
	<title>BitBuddy Email</title>
</svelte:head>

<div class="email-page">
	<PageHeader icon={EnvelopeSimpleIcon} eyebrow="Inbox" title="Email" subtitle="Browse mail locally and manage safe mailbox actions. Account setup is in Settings.">
		{#snippet action()}
			<a class="settings-link" href="/settings">Email settings</a>
		{/snippet}
	</PageHeader>
	<section class="email-panel" aria-label="Email inbox">
		<div class="email-content">
			{#if error}
				<div class="notice danger">{error}</div>
			{:else if loading}
				<div class="empty-card"><Skeleton variant="card" count={2} /></div>
			{:else if !overview?.enabled}
				<section class="empty-card primary-empty">
					<div class="empty-icon"><EnvelopeSimpleIcon size={28} weight="duotone" /></div>
					<div>
						<p class="eyebrow">Not Connected</p>
						<h2>Email is not configured yet</h2>
						<p>Connect IMAP or Gmail in Settings when you want local mail browsing and assistant-aware read/search tools.</p>
					</div>
					<a href="/settings">Open Settings</a>
				</section>
			{:else if overview.provider === 'gmail' && !overview.gmail_connected}
				<section class="empty-card primary-empty">
					<div class="empty-icon"><EnvelopeSimpleIcon size={28} weight="duotone" /></div>
					<div>
						<p class="eyebrow">Gmail Ready</p>
						<h2>Gmail is configured but not connected</h2>
						<p>Connect Gmail in Settings to authorize inbox access for the dashboard and assistant-aware tools.</p>
					</div>
					<a href="/settings">Open Settings</a>
				</section>
			{:else}
				<section class="inbox-shell" data-pane={mobilePane} class:overlay-open={mailboxOverlayOpen}>
					<div class="mobile-pane-switch">
						<button type="button" class="mailbox-toggle" class:active={mailboxOverlayOpen} aria-expanded={mailboxOverlayOpen} onclick={() => (mailboxOverlayOpen = !mailboxOverlayOpen)}>Mailboxes</button>
						<div class="pane-tabs" role="tablist" aria-label="Email view">
							<button type="button" role="tab" aria-selected={mobilePane === 'messages'} class:active={mobilePane === 'messages'} onclick={() => (mobilePane = 'messages')}>Messages</button>
							<button type="button" role="tab" aria-selected={mobilePane === 'preview'} class:active={mobilePane === 'preview'} onclick={() => (mobilePane = 'preview')}>Preview</button>
						</div>
					</div>
					<button type="button" class="mailbox-backdrop" aria-label="Close mailboxes" onclick={() => (mailboxOverlayOpen = false)}></button>
					<aside class="inbox-rail">
						<button type="button" class="drawer-close" aria-label="Close mailboxes" onclick={() => (mailboxOverlayOpen = false)}>
							<XIcon size={18} weight="bold" />
						</button>
						<div class="rail-heading">
							<p class="eyebrow"><EnvelopeSimpleIcon size={13} weight="bold" /> Account</p>
							<strong>{overview.account_label || overview.email_address || 'Email account'}</strong>
							<small>{overview.provider.toUpperCase()} · local dashboard access</small>
						</div>
						<div class="mailbox-list" aria-label="Mailboxes">
							{#if mailboxLoading && mailboxes.length === 0}
								<Skeleton variant="row" count={5} gap="0.4rem" />
							{:else}
								<div class="mailbox-section">
									<p><TrayIcon size={13} weight="bold" /> Mailboxes</p>
									{#each primaryMailboxes as mailbox (mailbox.name)}
										{@const MailboxGlyph = mailboxIcon(mailbox.name)}
										<button class="mailbox-pill folder" class:active={selectedMailbox === mailbox.name} type="button" onclick={() => chooseMailbox(mailbox.name)}>
											<MailboxGlyph class="mailbox-icon" size={17} weight={selectedMailbox === mailbox.name ? 'fill' : 'regular'} />
											<span class="mailbox-name">{mailboxLabel(mailbox)}</span>
											{#if mailboxBadgeValue(mailbox) !== null}
												<span class="mailbox-badge" class:unread={mailboxBadgeKind(mailbox) === 'unread'}>{mailboxBadgeLabel(mailbox)}</span>
											{/if}
										</button>
									{/each}
								</div>
								{#if labelMailboxes.length > 0}
									<div class="mailbox-section">
										<p><TagIcon size={13} weight="bold" /> Labels</p>
										{#each labelMailboxes as mailbox (mailbox.name)}
											<button class="mailbox-pill label" class:active={selectedMailbox === mailbox.name} type="button" onclick={() => chooseMailbox(mailbox.name)}>
												<TagIcon class="mailbox-icon" size={16} weight={selectedMailbox === mailbox.name ? 'fill' : 'regular'} />
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
									<MagnifyingGlassIcon size={16} weight="bold" /> Search
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
								<div class="empty-list"><Skeleton variant="row" count={6} /></div>
							{:else if messages.length === 0}
								<div class="empty-list">No messages found in {selectedMailboxLabel()}.</div>
							{:else}
								{#each messages as message (message.mailbox + ':' + message.id)}
									<button class="message-row" class:active={selectedMessage?.id === message.id} type="button" onclick={() => openMessage(message)}>
										<span class="message-topline"><strong>{message.subject || '(no subject)'}</strong><time>{formatDate(message.date)}</time></span>
										<span class="sender"><UserCircleIcon size={14} weight="bold" /> {message.from_addr || 'Unknown sender'}</span>
										<span class="snippet" use:revealMaskedChips>{@html maskHtml(escapeHtml(message.snippet ?? ''))}</span>
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
									{#if gmailTrashDeleteUnavailable()}
										<div class="trash-scope-note">Gmail requires the full mail scope to permanently delete Trash. Enable Full Gmail access in Settings, add <code>https://mail.google.com/</code> in Google Cloud Data Access, then reconnect Gmail.</div>
									{:else}
										<button class="trash-action" type="button" onclick={trashSelectedMessage} disabled={messageAction}>
											<TrashIcon size={15} weight="bold" /> {selectedMailbox === 'TRASH' ? 'Delete permanently from Trash' : 'Move selected email to Trash'}
										</button>
										{#if selectedMailbox !== 'TRASH'}<button class="secondary-preview-action" type="button" onclick={() => (ruleConfirm = !ruleConfirm)} disabled={messageAction}>Auto-trash sender</button>{/if}
									{/if}
								</div>
								{#if ruleConfirm}
									<div class="rule-confirm">
										<p>Automatically move future emails from this sender to Trash?</p>
										<div>
											<button type="button" onclick={() => autoTrashSender(false)} disabled={messageAction}>Future only</button>
											<button type="button" onclick={() => autoTrashSender(true)} disabled={messageAction}>Also move existing to Trash</button>
										</div>
									</div>
								{/if}
								{#if selectedMessage.body_html}
									<iframe
										class="email-html-preview"
										title={`Email content: ${selectedMessage.subject || 'message'}`}
										sandbox=""
										referrerpolicy="no-referrer"
										srcdoc={emailPreviewDocument(selectedMessage.body_html)}
									></iframe>
								{:else}
									<pre use:revealMaskedChips>{@html maskHtml(escapeHtml(selectedMessage.body || selectedMessage.snippet || 'No readable body found.'))}</pre>
								{/if}
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
		flex-direction: column;
		gap: 0.7rem;
		min-height: 0;
		animation: fade-in 0.35s cubic-bezier(0.16, 1, 0.3, 1);
	}

	@keyframes fade-in {
		from { opacity: 0; transform: translateY(12px); }
		to { opacity: 1; transform: translateY(0); }
	}

	.email-panel {
		width: 100%;
		flex: 1 1 auto;
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

	.eyebrow {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		color: var(--page-accent);
		font-size: 0.72rem;
		font-weight: 800;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	h2 {
		margin: 0;
		letter-spacing: -0.03em;
		font-size: 1.15rem;
		font-weight: 850;
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
		position: relative;
		height: 100%;
		min-height: 24rem;
		display: grid;
		grid-template-columns: 14rem minmax(20rem, 0.85fr) minmax(18rem, 1fr);
		gap: 1rem;
	}

	.mobile-pane-switch {
		display: none;
		grid-column: 1 / -1;
		gap: 0.5rem;
		align-items: center;
	}

	.pane-tabs {
		display: flex;
		flex: 1;
		gap: 0.4rem;
		padding: 0.25rem;
		border: 1px solid var(--border);
		border-radius: var(--radius-control, 0.8rem);
		background: var(--surface-inset);
	}

	.pane-tabs button,
	.mailbox-toggle {
		border: none;
		border-radius: var(--radius-sm, 6px);
		background: transparent;
		color: var(--text-muted);
		font-weight: 700;
		font-size: 0.85rem;
		cursor: pointer;
	}

	.pane-tabs button {
		flex: 1;
		padding: 0.5rem 0.4rem;
	}

	.pane-tabs button.active {
		background: var(--accent-soft);
		color: var(--text);
	}

	.mailbox-toggle {
		padding: 0.6rem 0.8rem;
		border: 1px solid var(--border);
		border-radius: var(--radius-control, 0.8rem);
		background: var(--surface-card);
		white-space: nowrap;
	}

	.mailbox-toggle.active {
		background: var(--accent-soft);
		color: var(--text);
		border-color: color-mix(in srgb, var(--accent) 35%, transparent);
	}

	.mailbox-backdrop {
		display: none;
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
		flex: 0 0 auto;
		margin-bottom: 1rem;
	}

	.drawer-close {
		display: none;
		position: absolute;
		top: 0.6rem;
		right: 0.6rem;
		z-index: 1;
		width: 2rem;
		height: 2rem;
		align-items: center;
		justify-content: center;
		border: 1px solid var(--border);
		border-radius: 999px;
		background: var(--surface-card);
		color: var(--text-muted);
		cursor: pointer;
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
		display: flex;
		align-items: center;
		gap: 0.35rem;
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

	.mailbox-pill :global(.mailbox-icon) {
		flex: 0 0 auto;
		color: var(--text-muted);
	}

	.mailbox-pill.active :global(.mailbox-icon) {
		color: var(--page-accent, var(--accent));
	}

	.mailbox-pill.label :global(.mailbox-icon) {
		color: color-mix(in srgb, var(--success) 70%, var(--text-muted));
	}

	.mailbox-pill:hover,
	.mailbox-pill.active {
		border-color: color-mix(in srgb, var(--accent) 24%, var(--border));
		background: var(--surface-glass);
		color: var(--text);
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
		flex: 1 1 auto;
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

	.sender :global(svg) {
		vertical-align: -0.15em;
		margin-right: 0.1rem;
		color: var(--text-muted);
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
		min-height: 100%;
		display: flex;
		flex-direction: column;
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

	.trash-scope-note {
		padding: 0.62rem 0.72rem;
		border: 1px solid color-mix(in srgb, var(--warning, #f59e0b) 30%, var(--border));
		border-radius: 0.72rem;
		background: color-mix(in srgb, var(--warning, #f59e0b) 10%, transparent);
		color: var(--text-soft);
		font-size: 0.78rem;
		line-height: 1.35;
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

	.email-html-preview {
		width: 100%;
		min-height: 28rem;
		flex: 1 1 auto;
		margin-top: 1rem;
		border: 1px solid var(--border);
		border-radius: 0.8rem;
		background: #fff;
	}

	@media (max-width: 980px) {
		/* Keep the whole mail view a fixed height; the active pane scrolls inside. */
		.email-page {
			height: calc(100dvh - 5rem);
		}

		.email-panel {
			flex: 1 1 auto;
			min-height: 0;
		}

		.inbox-shell {
			grid-template-columns: 1fr;
			grid-template-rows: auto minmax(0, 1fr);
			height: 100%;
			min-height: 0;
		}

		/* Messages/Preview tabs swap the two main panes; mailboxes is a drawer. */
		.mobile-pane-switch {
			display: flex;
		}

		.inbox-rail {
			display: none;
		}

		.inbox-shell[data-pane='messages'] .guard-card,
		.inbox-shell[data-pane='preview'] .message-list-panel {
			display: none;
		}

		/* Mailboxes drawer overlays only the email card, full card height. */
		.inbox-shell.overlay-open .mailbox-backdrop {
			display: block;
			position: absolute;
			inset: 0;
			z-index: 15;
			border: 0;
			border-radius: 1.05rem;
			background: rgba(3, 7, 18, 0.5);
			backdrop-filter: blur(2px);
			cursor: pointer;
		}

		.inbox-shell.overlay-open .inbox-rail {
			display: flex;
			flex-direction: column;
			position: absolute;
			top: 0;
			bottom: 0;
			left: 0;
			width: min(19rem, 84%);
			z-index: 20;
			background: var(--panel-raised);
			border: 1px solid var(--border-strong, var(--border));
			border-radius: 1.05rem;
			box-shadow: 0 18px 48px rgba(0, 0, 0, 0.5);
			animation: mailbox-drawer-in 0.22s cubic-bezier(0.22, 1, 0.36, 1);
		}

		.inbox-shell.overlay-open .inbox-rail .mailbox-list {
			flex: 1 1 auto;
			min-height: 0;
			overflow-y: auto;
		}

		.drawer-close {
			display: inline-flex;
		}

		@keyframes mailbox-drawer-in {
			from { transform: translateX(-100%); opacity: 0.4; }
			to { transform: translateX(0); opacity: 1; }
		}
	}

	@media (max-width: 768px) {
		.guard-card {
			flex-direction: column;
			align-items: stretch;
		}

		.message-list-meta {
			flex-wrap: wrap;
		}

		.search-row {
			flex-wrap: wrap;
		}

		.empty-card {
			min-height: 12rem;
		}

		.mailbox-badge {
			max-width: 3.5rem;
			overflow: hidden;
			text-overflow: ellipsis;
		}
	}
</style>
