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
		padding: 0 1.25rem;
		display: flex;
		justify-content: center;
		background: transparent;
		position: relative;
		z-index: 1;
	}

	.steering-card {
		width: min(72%, 46rem);
		max-width: 60rem;
		margin: 0 auto -1px;
		padding: 0.48rem 0.45rem 0.48rem 0.75rem;
		display: flex;
		align-items: center;
		gap: 0.75rem;
		border: 1px solid color-mix(in srgb, var(--mode-color) 36%, var(--border));
		border-bottom-color: var(--border);
		border-radius: 0.95rem 0.95rem 0 0;
		background:
			linear-gradient(135deg, color-mix(in srgb, var(--mode-soft) 76%, transparent), transparent),
			var(--surface-card);
		box-shadow: 0 -0.45rem 1.4rem rgba(0, 0, 0, 0.12);
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
		gap: 0.3rem;
		flex-shrink: 0;
		color: var(--mode-color);
		font-size: 0.72rem;
		font-weight: 800;
		letter-spacing: 0.03em;
		text-transform: uppercase;
	}

	.steering-text {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		color: var(--text);
		font-size: 0.86rem;
	}

	.steering-actions {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		flex-shrink: 0;
	}

	.steer-button,
	.cancel-button {
		height: 2rem;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		border-radius: 999px;
		transition: background 120ms ease, color 120ms ease, filter 120ms ease, transform 120ms ease;
	}

	.steer-button {
		gap: 0.35rem;
		padding: 0 0.75rem;
		background: var(--mode-color);
		color: var(--on-accent);
		font-size: 0.78rem;
		font-weight: 800;
	}

	.cancel-button {
		width: 2rem;
		color: var(--text-soft);
	}

	.steer-button:hover {
		filter: brightness(1.05);
		transform: translateY(-1px);
	}

	.cancel-button:hover {
		background: rgba(239, 68, 68, 0.12);
		color: var(--danger, #ef4444);
	}

	@media (max-width: 760px) {
		.steering-dock {
			padding-inline: 0.85rem;
		}

		.steering-card {
			width: 100%;
			gap: 0.5rem;
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
