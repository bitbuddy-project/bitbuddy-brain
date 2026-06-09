<script lang="ts">
	import type { Component, Snippet } from 'svelte';

	type IconWeight = 'thin' | 'light' | 'regular' | 'bold' | 'fill' | 'duotone';

	let {
		icon,
		iconWeight = 'duotone',
		iconSize = 24,
		eyebrow,
		title,
		subtitle = '',
		action
	} = $props<{
		icon: Component<{ size?: number; weight?: IconWeight }>;
		iconWeight?: IconWeight;
		iconSize?: number;
		eyebrow: string;
		title: string;
		subtitle?: string;
		action?: Snippet;
	}>();

	const Icon = $derived(icon);
</script>

<header class="page-header">
	<div class="title-mark"><Icon size={iconSize} weight={iconWeight} /></div>
	<div class="title-copy">
		<p class="eyebrow">{eyebrow}</p>
		<h1>{title}</h1>
		{#if subtitle}<p class="subtitle">{subtitle}</p>{/if}
	</div>
	{#if action}
		<div class="header-action">{@render action()}</div>
	{/if}
</header>

<style>
	/* Compact standalone, fully-rounded card — sits above the content panel with a gap. */
	.page-header {
		flex: 0 0 auto;
		box-sizing: border-box;
		/* Match the 0.7rem horizontal inset the content cards get from app.css so the
		   header lines up edge-to-edge with the card below it. */
		margin: 0 0.7rem;
		display: flex;
		align-items: center;
		gap: 0.9rem;
		padding: 1.15rem 1.55rem;
		border-radius: 1.35rem;
		background:
			linear-gradient(135deg, var(--page-soft), transparent 70%),
			var(--panel);
		box-shadow: var(--shadow-chat);
	}

	.title-mark {
		width: 2.75rem;
		height: 2.75rem;
		display: grid;
		place-items: center;
		border-radius: 0.9rem;
		background: var(--surface-glass);
		color: var(--page-accent, var(--accent));
		box-shadow: 0 0 18px var(--page-soft);
		flex: 0 0 auto;
	}

	.title-copy {
		min-width: 0;
		flex: 1;
	}

	.eyebrow {
		display: flex;
		align-items: center;
		gap: 0.3rem;
		color: var(--page-accent, var(--accent));
		font-size: 0.66rem;
		font-weight: 800;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		margin: 0;
	}

	h1 {
		margin: 0;
		font-size: 1.3rem;
		font-weight: 900;
		line-height: 1.15;
		letter-spacing: -0.03em;
	}

	.subtitle {
		margin: 0.1rem 0 0;
		color: var(--text-soft);
		font-size: 0.82rem;
		line-height: 1.45;
	}

	.header-action {
		flex: 0 0 auto;
		display: flex;
		align-items: center;
		gap: 0.6rem;
	}

	/* Tablet / large phone: compact a touch further and let the action wrap. */
	@media (max-width: 760px) {
		.page-header {
			flex-wrap: wrap;
			gap: 0.7rem;
			padding: 0.75rem 0.9rem;
		}

		.title-mark {
			width: 2.5rem;
			height: 2.5rem;
			border-radius: 0.8rem;
		}

		h1 {
			font-size: 1.2rem;
		}

		/* Action drops below the title block and aligns left. */
		.header-action {
			flex: 1 1 100%;
			flex-wrap: wrap;
		}
	}

	@media (max-width: 480px) {
		h1 {
			font-size: 1.12rem;
		}
	}
</style>
