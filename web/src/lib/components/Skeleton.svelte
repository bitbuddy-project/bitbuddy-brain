<script lang="ts">
	type Variant = 'card' | 'row' | 'line' | 'avatar';

	let {
		variant = 'line',
		count = 1,
		width = '',
		height = '',
		gap = '0.6rem'
	} = $props<{
		variant?: Variant;
		count?: number;
		width?: string;
		height?: string;
		gap?: string;
	}>();

	const items = $derived(Array.from({ length: Math.max(1, count) }));
</script>

<div class="skeleton-stack" style:gap aria-hidden="true">
	{#each items as _item}
		<div
			class="skeleton skeleton-{variant}"
			style:width={width || undefined}
			style:height={height || undefined}
		></div>
	{/each}
</div>

<style>
	.skeleton-stack {
		display: flex;
		flex-direction: column;
		width: 100%;
	}

	.skeleton {
		position: relative;
		overflow: hidden;
		background: color-mix(in srgb, var(--surface-card) 85%, var(--surface-inset));
		border: 1px solid color-mix(in srgb, var(--border) 70%, transparent);
		border-radius: var(--radius-md, 10px);
		animation: bitbuddy-skeleton-pulse 1.4s ease-in-out infinite;
	}

	.skeleton-line {
		height: 0.85rem;
		border-radius: var(--radius-sm, 6px);
		border: none;
	}

	.skeleton-line:nth-child(3n) {
		width: 72%;
	}
	.skeleton-line:nth-child(3n + 2) {
		width: 88%;
	}

	.skeleton-row {
		height: 3.2rem;
		border-radius: var(--radius-md, 10px);
	}

	.skeleton-card {
		height: 8rem;
		border-radius: var(--radius-lg, 18px);
	}

	.skeleton-avatar {
		width: 2.4rem;
		height: 2.4rem;
		border-radius: 50%;
		flex: none;
	}

	@media (prefers-reduced-motion: reduce) {
		.skeleton {
			animation: none;
		}
	}
</style>
