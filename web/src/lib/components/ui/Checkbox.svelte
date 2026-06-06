<script lang="ts">
	let {
		checked = $bindable(false),
		disabled = false,
		label = '',
		ariaLabel,
		onChange
	}: {
		checked?: boolean;
		disabled?: boolean;
		label?: string;
		ariaLabel?: string;
		onChange?: (checked: boolean) => void;
	} = $props();

	function toggle() {
		if (disabled) return;
		checked = !checked;
		onChange?.(checked);
	}
</script>

<button
	class="checkbox"
	class:checked
	type="button"
	role="checkbox"
	aria-checked={checked}
	aria-label={ariaLabel ?? label}
	{disabled}
	onclick={toggle}
>
	<span class="box" aria-hidden="true">
		<svg viewBox="0 0 16 16" aria-hidden="true">
			<path d="M3.4 8.2 6.4 11 12.6 4.8" />
		</svg>
	</span>
	{#if label}
		<span class="label">{label}</span>
	{/if}
</button>

<style>
	.checkbox {
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
		width: fit-content;
		min-height: 1.5rem;
		padding: 0;
		border: 0;
		background: transparent;
		color: var(--text-muted);
		cursor: pointer;
		font: inherit;
		text-align: left;
	}

	.box {
		display: grid;
		place-items: center;
		width: 1.15rem;
		height: 1.15rem;
		border: 1px solid var(--border-strong);
		border-radius: 0.4rem;
		background: var(--surface-inset);
		transition: background 140ms ease, border-color 140ms ease, box-shadow 140ms ease;
	}

	svg {
		width: 0.8rem;
		height: 0.8rem;
		fill: none;
		stroke: var(--on-accent);
		stroke-linecap: round;
		stroke-linejoin: round;
		stroke-width: 2.4;
		opacity: 0;
		transform: scale(0.78);
		transition: opacity 120ms ease, transform 120ms ease;
	}

	.checkbox.checked .box {
		border-color: color-mix(in srgb, var(--accent) 70%, var(--border));
		background: var(--accent);
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 16%, transparent);
	}

	.checkbox.checked svg {
		opacity: 1;
		transform: scale(1);
	}

	.label {
		font-size: 0.88rem;
		font-weight: 650;
		color: var(--text);
	}

	.checkbox:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 3px;
		border-radius: 0.4rem;
	}

	.checkbox:disabled {
		cursor: not-allowed;
		opacity: 0.5;
	}
</style>
