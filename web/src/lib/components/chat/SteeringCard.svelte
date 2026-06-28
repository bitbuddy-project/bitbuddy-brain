<script lang="ts">
	import SteeringWheelIcon from 'phosphor-svelte/lib/SteeringWheelIcon';
	import ArrowElbowUpLeftIcon from 'phosphor-svelte/lib/ArrowElbowUpLeftIcon';
	import XIcon from 'phosphor-svelte/lib/XIcon';
	import type { PendingSteerMessage } from '$lib/stores/chat.svelte';

	let { pending, onSteer, onCancel } = $props<{
		pending: PendingSteerMessage;
		onSteer: () => void | Promise<void>;
		onCancel: () => void;
	}>();

	let preview = $derived.by(() => pending.content || attachmentPreview(pending.attachments.length));

	function attachmentPreview(count: number) {
		if (count === 1) return '1 attachment queued';
		return `${count} attachments queued`;
	}
</script>

<div class="steering-dock" aria-live="polite">
	<div class="steering-card">
		<div class="steering-copy">
			<span class="steering-label"><SteeringWheelIcon size={18} weight="bold" /> Steering queued</span>
			<span class="steering-text" title={preview}>{preview}</span>
		</div>
		<div class="steering-actions">
			<button class="steer-button" type="button" onclick={onSteer} aria-label="Steer now">
				<ArrowElbowUpLeftIcon size={16} weight="bold" />
				<span>Steer</span>
			</button>
			<button class="cancel-button" type="button" onclick={onCancel} aria-label="Cancel queued steering message">
				<XIcon size={15} weight="bold" />
			</button>
		</div>
	</div>
</div>

<style>
	.steering-dock {
		padding: 0.45rem 1.6rem 0.65rem;
		display: flex;
		justify-content: center;
		background: transparent;
		position: relative;
		z-index: 1;
	}

	.steering-card {
		width: 100%;
		max-width: 72rem;
		margin: 0 auto;
		padding: 0.58rem 0.62rem 0.58rem 0.78rem;
		display: flex;
		align-items: center;
		gap: 0.75rem;
		border: 1px solid color-mix(in srgb, var(--mode-color) 34%, rgba(148, 163, 184, 0.36));
		border-radius: 1.18rem;
		background:
			linear-gradient(135deg, color-mix(in srgb, var(--mode-color) 16%, transparent), transparent 64%),
			linear-gradient(180deg, rgba(255, 255, 255, 0.055), rgba(255, 255, 255, 0.025)),
			color-mix(in srgb, var(--surface-glass) 72%, #081322);
		box-shadow:
			0 14px 34px rgba(0, 0, 0, 0.18),
			inset 0 1px 0 rgba(255, 255, 255, 0.075);
		backdrop-filter: blur(18px) saturate(1.08);
	}

	:global(:root.light) .steering-card {
		border-color: color-mix(in srgb, var(--mode-color) 24%, rgba(73, 104, 145, 0.22));
		background:
			linear-gradient(135deg, color-mix(in srgb, var(--mode-color) 11%, transparent), transparent 64%),
			linear-gradient(180deg, rgba(255, 255, 255, 0.82), rgba(255, 255, 255, 0.52)),
			color-mix(in srgb, var(--panel) 82%, #d8e6f4);
		box-shadow:
			0 12px 28px rgba(50, 80, 118, 0.12),
			inset 0 1px 0 rgba(255, 255, 255, 0.88);
	}

	.steering-copy {
		min-width: 0;
		display: flex;
		align-items: center;
		gap: 0.65rem;
		flex: 1;
	}

	.steering-label {
		display: inline-flex;
		align-items: center;
		gap: 0.38rem;
		flex-shrink: 0;
		padding: 0.38rem 0.58rem;
		border: 1px solid color-mix(in srgb, var(--mode-color) 24%, transparent);
		border-radius: 999px;
		background: color-mix(in srgb, var(--mode-color) 11%, rgba(255, 255, 255, 0.04));
		color: color-mix(in srgb, var(--mode-color) 86%, white 8%);
		font-size: 0.72rem;
		font-weight: 800;
		letter-spacing: 0.03em;
		text-transform: uppercase;
	}

	.steering-text {
		flex: 1;
		min-width: 0;
		/* Hard single-line cap: clamps even if a break sneaks in, so the steer
		   bar can never grow taller than the composer/input bar below it. */
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 1;
		line-clamp: 1;
		overflow: hidden;
		text-overflow: ellipsis;
		word-break: break-word;
		color: color-mix(in srgb, var(--text) 92%, white 8%);
		font-size: 0.86rem;
		font-weight: 600;
	}

	.steering-actions {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		flex-shrink: 0;
	}

	.steer-button,
	.cancel-button {
		height: 2.25rem;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border: 1px solid transparent;
		border-radius: 0.78rem;
		transition: background 120ms ease, color 120ms ease, border-color 120ms ease, filter 120ms ease;
	}

	.steer-button {
		gap: 0.35rem;
		padding: 0 0.82rem;
		background: color-mix(in srgb, var(--mode-color) 22%, transparent);
		border-color: color-mix(in srgb, var(--mode-color) 26%, transparent);
		color: color-mix(in srgb, var(--mode-color) 90%, white 14%);
		font-size: 0.78rem;
		font-weight: 800;
	}

	.cancel-button {
		width: 2.25rem;
		background: rgba(255, 255, 255, 0.035);
		color: var(--text-soft);
	}

	.steer-button:hover {
		background: color-mix(in srgb, var(--mode-color) 30%, transparent);
		border-color: color-mix(in srgb, var(--mode-color) 38%, transparent);
		filter: brightness(1.05);
	}

	.cancel-button:hover {
		background: rgba(239, 68, 68, 0.12);
		border-color: rgba(239, 68, 68, 0.22);
		color: var(--danger, #ef4444);
	}

	@media (max-width: 760px) {
		.steering-dock {
			padding-inline: 0.85rem;
		}

		.steering-card {
			width: 100%;
			gap: 0.5rem;
			padding-left: 0.62rem;
		}

		.steering-label {
			display: none;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.steer-button,
		.cancel-button {
			transition: none;
		}
	}
</style>
