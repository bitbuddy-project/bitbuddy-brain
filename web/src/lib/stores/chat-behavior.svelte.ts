import { browser } from '$app/environment';

export type ReplyAnimation = 'Off' | 'Balanced' | 'Slow';

export type ReplyAnimationConfig = {
	delayMs: number;
	largeBatch: number;
	mediumBatch: number;
	smallBatch: number;
};

const STORAGE_KEY = 'bitbuddy-reply-animation';

class ChatBehaviorStore {
	replyAnimation = $state<ReplyAnimation>('Balanced');

	constructor() {
		if (!browser) return;

		const stored = localStorage.getItem(STORAGE_KEY);
		if (isReplyAnimation(stored)) {
			this.replyAnimation = stored;
		}
	}

	setReplyAnimation(value: ReplyAnimation) {
		this.replyAnimation = value;
		if (browser) localStorage.setItem(STORAGE_KEY, value);
	}
}

export function replyAnimationConfig(value: ReplyAnimation): ReplyAnimationConfig {
	if (value === 'Slow') {
		return { delayMs: 58, largeBatch: 4, mediumBatch: 3, smallBatch: 1 };
	}

	return { delayMs: 42, largeBatch: 6, mediumBatch: 4, smallBatch: 2 };
}

function isReplyAnimation(value: string | null): value is ReplyAnimation {
	return value === 'Off' || value === 'Balanced' || value === 'Slow';
}

export const chatBehavior = new ChatBehaviorStore();
