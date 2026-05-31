import { browser } from '$app/environment';

export type ThemeVariant = 'Auto' | 'Dark' | 'Light';

class ThemeStore {
	variant = $state<ThemeVariant>('Auto');

	constructor() {
		if (browser) {
			const stored = localStorage.getItem('bitbuddy-theme') as ThemeVariant;
			if (stored) {
				this.variant = stored;
			}
			this.apply();

			window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
				if (this.variant === 'Auto') {
					this.apply();
				}
			});
		}
	}

	setVariant(v: ThemeVariant) {
		this.variant = v;
		if (browser) {
			localStorage.setItem('bitbuddy-theme', v);
			this.apply();
		}
	}

	private apply() {
		if (!browser) return;

		const isDark =
			this.variant === 'Dark' ||
			(this.variant === 'Auto' && window.matchMedia('(prefers-color-scheme: dark)').matches);

		document.documentElement.classList.toggle('light', !isDark);
		document.documentElement.style.colorScheme = isDark ? 'dark' : 'light';
	}
}

export const theme = new ThemeStore();
