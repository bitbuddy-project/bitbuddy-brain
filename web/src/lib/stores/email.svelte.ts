/*
 * Client-side email cache (stale-while-revalidate). Holds the overview, mailbox
 * list, and the most-recent page per mailbox/search so re-opening the email page
 * paints instantly from cache while fresh data is fetched in the background.
 */
import type { EmailConfig, EmailMailbox, EmailMessage } from '$lib/api/bitbuddy';

export type EmailOverview = EmailConfig & {
	permissions?: Record<string, string>;
	account_id?: string;
};

export interface MailboxPage {
	messages: EmailMessage[];
	nextPageToken: string;
	resultSizeEstimate: number | null;
}

interface EmailCacheState {
	overview: EmailOverview | null;
	mailboxes: EmailMailbox[];
	selectedMailbox: string;
	pages: Record<string, MailboxPage>;
	fetchedAt: number;
}

export const emailCache = $state<EmailCacheState>({
	overview: null,
	mailboxes: [],
	selectedMailbox: '',
	pages: {},
	fetchedAt: 0
});

/** Key a cached page by mailbox, namespacing search queries so they don't collide. */
export function pageKey(mailbox: string, query: string): string {
	const trimmed = query.trim();
	return trimmed ? `q:${mailbox}:${trimmed}` : mailbox;
}

/** True when the cache was refreshed within the freshness window. */
export function cacheIsFresh(maxAgeMs = 60_000): boolean {
	return emailCache.fetchedAt > 0 && Date.now() - emailCache.fetchedAt < maxAgeMs;
}

/** Drop cached pages for a mailbox (after trash/delete/empty mutations). */
export function invalidateMailbox(mailbox: string): void {
	for (const key of Object.keys(emailCache.pages)) {
		if (key === mailbox || key.startsWith(`q:${mailbox}:`)) {
			delete emailCache.pages[key];
		}
	}
}
