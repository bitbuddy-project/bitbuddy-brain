<script lang="ts">
	import TrashIcon from 'phosphor-svelte/lib/TrashIcon';
	import WarningCircleIcon from 'phosphor-svelte/lib/WarningCircleIcon';

	let {
		open = false,
		title,
		description,
		confirmLabel = 'Confirm',
		cancelLabel = 'Cancel',
		destructive = false,
		busy = false,
		onConfirm,
		onCancel
	} = $props<{
		open?: boolean;
		title: string;
		description: string;
		confirmLabel?: string;
		cancelLabel?: string;
		destructive?: boolean;
		busy?: boolean;
		onConfirm?: () => void | Promise<void>;
		onCancel?: () => void;
	}>();

	let dialog = $state<HTMLDivElement>();

	$effect(() => {
		if (!open || typeof window === 'undefined') return;

		const previousActive = document.activeElement instanceof HTMLElement ? document.activeElement : null;
		window.setTimeout(() => dialog?.focus(), 0);

		function handleKeydown(event: KeyboardEvent) {
			if (event.key === 'Escape' && !busy) onCancel?.();
		}

		window.addEventListener('keydown', handleKeydown);
		return () => {
			window.removeEventListener('keydown', handleKeydown);
			previousActive?.focus();
		};
	});

	async function confirm() {
		if (busy) return;
		await onConfirm?.();
	}

	function cancel() {
		if (busy) return;
		onCancel?.();
	}
</script>

{#if open}
	<div class="confirm-overlay" role="presentation">
		<button class="confirm-backdrop" type="button" aria-label="Cancel confirmation" onclick={cancel} disabled={busy}></button>
		<div
			bind:this={dialog}
			class="confirm-dialog"
			class:destructive
			role="dialog"
			aria-modal="true"
			aria-labelledby="confirm-title"
			aria-describedby="confirm-description"
			tabindex="-1"
		>
			<div class="dialog-body">
				<div class="dialog-mark" aria-hidden="true">
					{#if destructive}
						<TrashIcon size={22} weight="duotone" />
					{:else}
						<WarningCircleIcon size={22} weight="duotone" />
					{/if}
				</div>
				<div class="dialog-copy">
					<h2 id="confirm-title">{title}</h2>
					<p id="confirm-description">{description}</p>
				</div>
			</div>

			<div class="dialog-actions">
				<button class="cancel-button" type="button" onclick={cancel} disabled={busy}>{cancelLabel}</button>
				<button class="confirm-button" type="button" onclick={confirm} disabled={busy}>
					{busy ? 'Working...' : confirmLabel}
				</button>
			</div>
		</div>
	</div>
{/if}

<style>
	.confirm-overlay {
		position: fixed;
		inset: 0;
		z-index: 10000;
		display: grid;
		place-items: center;
		padding: 1rem;
		background: color-mix(in srgb, var(--bg) 24%, transparent);
		backdrop-filter: blur(6px);
		-webkit-backdrop-filter: blur(6px);
		animation: overlay-fade-in 0.16s ease-out;
	}

	.confirm-backdrop {
		position: absolute;
		inset: 0;
		width: 100%;
		height: 100%;
		padding: 0;
		border: 0;
		border-radius: 0;
		background: transparent;
		cursor: default;
	}

	.confirm-backdrop:disabled {
		cursor: wait;
	}

	.confirm-dialog {
		position: relative;
		z-index: 1;
		width: min(30rem, 100%);
		border: 1px solid var(--border-strong);
		border-radius: var(--radius-lg);
		background:
			linear-gradient(135deg, var(--glass-overlay), transparent 18rem),
			var(--panel-raised);
		box-shadow: var(--shadow-soft);
		color: var(--text);
		overflow: hidden;
		animation: dialog-rise 0.18s cubic-bezier(0.16, 1, 0.3, 1);
	}

	.confirm-dialog:focus {
		outline: none;
	}

	.dialog-body {
		display: grid;
		grid-template-columns: 2.7rem minmax(0, 1fr);
		gap: 0.9rem;
		padding: 1.2rem;
	}

	.dialog-mark {
		display: grid;
		place-items: center;
		width: 2.55rem;
		height: 2.55rem;
		border: 1px solid var(--accent);
		border-radius: 1rem;
		background: var(--accent-soft);
		color: var(--accent);
		box-shadow: 0 0 20px var(--accent-soft);
		overflow: visible;
	}

	.dialog-mark :global(svg) {
		overflow: visible;
	}

	.confirm-dialog.destructive .dialog-mark {
		border-color: var(--danger);
		background: color-mix(in srgb, var(--danger) 14%, transparent);
		color: var(--danger);
		box-shadow: 0 0 20px color-mix(in srgb, var(--danger) 18%, transparent);
	}

	h2 {
		font-size: 1.05rem;
		font-weight: 900;
		letter-spacing: -0.01em;
	}

	p {
		margin-top: 0.35rem;
		color: var(--text-soft);
		font-size: 0.92rem;
		line-height: 1.55;
	}

	.dialog-actions {
		display: flex;
		justify-content: flex-end;
		gap: 0.7rem;
		padding: 0.9rem 1.2rem 1.1rem;
		border-top: 1px solid var(--border);
		background: var(--surface-card);
	}

	.dialog-actions button {
		padding: 0.62rem 0.95rem;
		border: 1px solid var(--border);
		border-radius: 999px;
		font-size: 0.84rem;
		font-weight: 850;
		transition: transform 140ms ease, border-color 140ms ease, background 140ms ease, color 140ms ease, opacity 140ms ease;
	}

	.dialog-actions button:hover:not(:disabled) {
		transform: translateY(-1px);
	}

	.dialog-actions button:disabled {
		cursor: wait;
		opacity: 0.66;
	}

	.cancel-button {
		background: var(--panel);
		color: var(--text-soft);
	}

	.cancel-button:hover:not(:disabled) {
		border-color: var(--border-strong);
		color: var(--text);
	}

	.confirm-button {
		border-color: var(--accent);
		background: var(--accent);
		color: var(--on-accent);
	}

	.confirm-dialog.destructive .confirm-button {
		border-color: var(--danger);
		background: var(--danger);
		color: #fff;
	}

	@keyframes overlay-fade-in {
		from { opacity: 0; }
		to { opacity: 1; }
	}

	@keyframes dialog-rise {
		from { opacity: 0; transform: translateY(10px) scale(0.985); }
		to { opacity: 1; transform: translateY(0) scale(1); }
	}

	@media (max-width: 760px) {
		.confirm-overlay {
			align-items: end;
			padding: 0.75rem;
		}

		.confirm-dialog {
			width: 100%;
			border-radius: 1.25rem;
		}

		.dialog-actions {
			flex-direction: column-reverse;
		}

		.dialog-actions button {
			width: 100%;
		}
	}
</style>
