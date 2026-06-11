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
		variant = 'page',
		action
	} = $props<{
		icon?: Component<{ size?: number; weight?: IconWeight }>;
		iconWeight?: IconWeight;
		iconSize?: number;
		eyebrow: string;
		title: string;
		subtitle?: string;
		variant?: 'page' | 'chat';
		action?: Snippet;
	}>();

	const Icon = $derived(icon);
</script>

<header class="page-header" class:chat={variant === 'chat'}>
	{#if Icon}
		<div class="title-mark"><Icon size={iconSize} weight={iconWeight} /></div>
	{/if}
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
	/* Compact standalone, fully-rounded card - sits above the content panel with a gap.
	   Uses the same radial-shine + gradient treatment as the chat header. */
	.page-header {
		flex: 0 0 auto;
		box-sizing: border-box;
		position: relative;
		z-index: 10;
		/* Match the 0.7rem horizontal inset the content cards get from app.css so the
		   header lines up edge-to-edge with the card below it. */
		margin: 0 0.7rem;
		display: flex;
		align-items: center;
		gap: 0.9rem;
		padding: 1.15rem 1.55rem;
		border-radius: 1.35rem;
		border: 0;
		background:
			radial-gradient(circle at 18% 0%, rgba(50, 78, 115, 0.1), transparent 23rem),
			linear-gradient(135deg, rgba(255, 255, 255, 0.026), transparent 62%),
			color-mix(in srgb, var(--panel-shell, var(--panel)) 86%, #01050d);
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.13), var(--shadow-chat);
		min-width: 0;
		overflow: visible;
	}

	.page-header::before {
		content: '';
		position: absolute;
		inset: 0;
		border-top: 1px solid rgba(255, 255, 255, 0.24);
		border-radius: inherit;
		pointer-events: none;
	}

	:global(:root.light) .page-header {
		background:
			radial-gradient(circle at 18% 0%, rgba(37, 99, 235, 0.08), transparent 23rem),
			linear-gradient(135deg, rgba(255, 255, 255, 0.34), transparent 62%),
			color-mix(in srgb, #d6e4f2 82%, var(--panel) 18%);
		box-shadow:
			0 16px 34px rgba(50, 80, 118, 0.1),
			inset 0 1px 0 rgba(255, 255, 255, 0.74);
	}

	:global(:root.light) .page-header::before {
		border-top-color: rgba(255, 255, 255, 0.78);
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

	.page-header.chat {
		margin: 0;
		gap: 1rem;
		justify-content: space-between;
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

	.page-header.chat .eyebrow {
		color: color-mix(in srgb, var(--mode-color, var(--accent)) 48%, var(--text-soft));
		font-size: 0.72rem;
		font-weight: 700;
		margin-bottom: 0.2rem;
	}

	h1 {
		margin: 0;
		font-size: 1.3rem;
		font-weight: 900;
		line-height: 1.15;
		letter-spacing: -0.03em;
	}

	.page-header.chat h1 {
		font-size: clamp(1.25rem, 1.7vw, 1.72rem);
		font-weight: 800;
		letter-spacing: -0.035em;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 100%;
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

	.page-header.chat .header-action {
		gap: 0.75rem;
	}

	/* Tablet / large phone: compact a touch further and let the action wrap. */
	@media (max-width: 760px) {
		.page-header {
			flex-wrap: wrap;
			gap: 0.7rem;
			padding: 0.75rem 0.9rem;
		}

		.page-header.chat {
			flex-direction: column;
			align-items: stretch;
			padding: 1rem;
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

		.page-header.chat .header-action {
			justify-content: space-between;
		}
	}

	@media (max-width: 480px) {
		h1 {
			font-size: 1.12rem;
		}
	}
</style>
