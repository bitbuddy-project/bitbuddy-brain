<script module lang="ts">
	export type SelectOption = {
		value: string;
		label: string;
		description?: string;
		disabled?: boolean;
	};
</script>

<script lang="ts">
	import CaretDownIcon from 'phosphor-svelte/lib/CaretDownIcon';
	import CheckIcon from 'phosphor-svelte/lib/CheckIcon';

	let {
		value = '',
		options = [],
		placeholder = 'Select',
		disabled = false,
		ariaLabel = 'Select option',
		onChange = () => {}
	} = $props<{
		value?: string;
		options?: SelectOption[];
		placeholder?: string;
		disabled?: boolean;
		ariaLabel?: string;
		onChange?: (value: string) => void;
	}>();

	let open = $state(false);
	let rootEl: HTMLDivElement | undefined;
	let selected = $derived(options.find((option: SelectOption) => option.value === value));

	function toggle() {
		if (disabled) return;
		open = !open;
	}

	function choose(option: SelectOption) {
		if (disabled || option.disabled) return;
		onChange(option.value);
		open = false;
	}

	function handleWindowPointerDown(event: PointerEvent) {
		if (!open) return;
		if (rootEl && !rootEl.contains(event.target as Node)) open = false;
	}

	function handleWindowKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') open = false;
	}
</script>

<svelte:window onpointerdown={handleWindowPointerDown} onkeydown={handleWindowKeydown} />

<div class="select-menu" class:open class:disabled bind:this={rootEl}>
	<button
		class="select-trigger"
		type="button"
		onclick={toggle}
		aria-haspopup="listbox"
		aria-expanded={open}
		aria-label={ariaLabel}
		disabled={disabled}
	>
		<span class="trigger-copy">
			<strong>{selected?.label ?? placeholder}</strong>
			{#if selected?.description}
				<small>{selected.description}</small>
			{/if}
		</span>
		<span class="trigger-caret"><CaretDownIcon size={15} weight="bold" /></span>
	</button>

	{#if open}
		<div class="select-list" role="listbox" aria-label={ariaLabel}>
			{#each options as option}
				<button
					class="select-option"
					class:selected={option.value === value}
					type="button"
					role="option"
					aria-selected={option.value === value}
					disabled={option.disabled}
					onclick={() => choose(option)}
				>
					<span>
						<strong>{option.label}</strong>
						{#if option.description}<small>{option.description}</small>{/if}
					</span>
					{#if option.value === value}
						<CheckIcon size={15} weight="bold" />
					{/if}
				</button>
			{/each}
		</div>
	{/if}
</div>

<style>
	.select-menu {
		position: relative;
		z-index: 20;
		min-width: 0;
	}

	.select-menu.open {
		z-index: 5000;
	}

	.select-trigger {
		width: 100%;
		min-height: 2.65rem;
		padding: 0.54rem 0.58rem 0.54rem 0.72rem;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.7rem;
		border: 1px solid color-mix(in srgb, var(--accent) 26%, var(--border));
		border-radius: 0.72rem;
		background:
			linear-gradient(180deg, rgba(255, 255, 255, 0.045), transparent),
			color-mix(in srgb, var(--bg-soft) 86%, #000);
		color: var(--text);
		text-align: left;
	}

	.select-menu.open .select-trigger,
	.select-trigger:hover:not(:disabled) {
		border-color: color-mix(in srgb, var(--accent) 54%, var(--border));
		background:
			linear-gradient(180deg, rgba(255, 255, 255, 0.06), transparent),
			color-mix(in srgb, var(--bg-soft) 92%, #000);
	}

	.trigger-copy,
	.select-option span {
		min-width: 0;
		display: grid;
		gap: 0.04rem;
	}

	.trigger-copy strong,
	.select-option strong {
		overflow: hidden;
		color: var(--text);
		font-size: 0.84rem;
		font-weight: 720;
		line-height: 1.2;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.trigger-copy small,
	.select-option small {
		overflow: hidden;
		color: var(--text-soft);
		font-size: 0.68rem;
		font-weight: 650;
		line-height: 1.2;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.trigger-caret {
		flex: 0 0 auto;
		color: var(--text-soft);
		transition: transform 140ms ease, color 140ms ease;
	}

	.select-menu.open .trigger-caret {
		color: var(--accent-strong);
		transform: rotate(180deg);
	}

	.select-list {
		position: absolute;
		inset: calc(100% + 0.35rem) 0 auto 0;
		z-index: 5001;
		max-height: 13rem;
		padding: 0.32rem;
		display: grid;
		gap: 0.16rem;
		border: 1px solid color-mix(in srgb, var(--accent) 34%, var(--border-strong));
		border-radius: 0.82rem;
		background:
			linear-gradient(135deg, rgba(255, 255, 255, 0.07), transparent 72%),
			color-mix(in srgb, var(--panel-raised) 94%, #020713);
		box-shadow: 0 18px 38px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.055);
		overflow-y: auto;
		animation: menu-in 120ms ease;
	}

	.select-option {
		width: 100%;
		min-height: 2.45rem;
		padding: 0.48rem 0.52rem;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.6rem;
		border: 1px solid transparent;
		border-radius: 0.62rem;
		color: var(--text-muted);
		text-align: left;
	}

	.select-option:hover:not(:disabled),
	.select-option.selected {
		border-color: color-mix(in srgb, var(--accent) 28%, transparent);
		background: color-mix(in srgb, var(--accent-soft) 56%, transparent);
		color: var(--accent-strong);
	}

	.select-option.selected strong,
	.select-option.selected :global(svg) {
		color: var(--accent-strong);
	}

	.select-option:disabled {
		cursor: not-allowed;
		opacity: 0.5;
	}

	.select-trigger:disabled {
		cursor: not-allowed;
		opacity: 0.58;
	}

	@keyframes menu-in {
		from {
			opacity: 0;
			transform: translateY(-0.25rem) scale(0.98);
		}
		to {
			opacity: 1;
			transform: translateY(0) scale(1);
		}
	}
</style>
