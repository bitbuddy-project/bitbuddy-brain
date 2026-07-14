<script module lang="ts">
	export type SelectOption = {
		value: string;
		label: string;
		description?: string;
		disabled?: boolean;
	};
</script>

<script lang="ts">
	import { onMount, tick } from 'svelte';
	import type { Snippet } from 'svelte';
	import CaretDownIcon from 'phosphor-svelte/lib/CaretDownIcon';
	import CheckIcon from 'phosphor-svelte/lib/CheckIcon';

	let {
		value = '',
		options = [],
		placeholder = 'Select',
		disabled = false,
		compact = false,
		ariaLabel = 'Select option',
		onChange = () => {},
		leading = undefined
	} = $props<{
		value?: string;
		options?: SelectOption[];
		placeholder?: string;
		disabled?: boolean;
		compact?: boolean;
		ariaLabel?: string;
		onChange?: (value: string) => void;
		leading?: Snippet;
	}>();

	let open = $state(false);
	let rootEl: HTMLDivElement | undefined;
	let triggerEl: HTMLButtonElement | undefined;
	let listEl = $state<HTMLDivElement | undefined>(undefined);
	let listPositioned = $state(false);
	let repositionFrame = 0;

	// Move the dropdown list to <body> so it escapes ancestors that establish a
	// containing block for fixed positioning (any `transform`, `filter`, or
	// `backdrop-filter` — the composer wraps and the sidebar both have these) and
	// the `overflow: hidden` that clips it. Without this, `position: fixed` is
	// trapped inside the transformed ancestor and the menu appears empty/clipped.
	function portal(node: HTMLElement) {
		document.body.appendChild(node);
		return {
			destroy() {
				node.remove();
			}
		};
	}
	// Inline style for the dropdown list. The list is positioned with `position: fixed`
	// from the trigger's rect so it escapes any `overflow: hidden` ancestor (the chat
	// composer bar and the sidebar both clip), and flips upward when there isn't room
	// below — e.g. the composer sits at the bottom of the screen.
	let listStyle = $state('');
	let selected = $derived(options.find((option: SelectOption) => option.value === value));

	const MAX_LIST_HEIGHT = 13 * 16; // matches .select-list max-height (13rem)

	function positionList() {
		if (!triggerEl) return;
		const rect = triggerEl.getBoundingClientRect();
		const spaceBelow = window.innerHeight - rect.bottom;
		const spaceAbove = rect.top;
		const flipUp = spaceBelow < MAX_LIST_HEIGHT + 8 && spaceAbove > spaceBelow;
		const maxHeight = Math.max(120, Math.min(MAX_LIST_HEIGHT, (flipUp ? spaceAbove : spaceBelow) - 12));
		const vertical = flipUp
			? `bottom: ${Math.round(window.innerHeight - rect.top + 6)}px;`
			: `top: ${Math.round(rect.bottom + 6)}px;`;
		listStyle = `position: fixed; left: ${Math.round(rect.left)}px; width: ${Math.round(rect.width)}px; ${vertical} max-height: ${Math.round(maxHeight)}px;`;
	}

	async function toggle() {
		if (disabled) return;
		if (open) {
			open = false;
			return;
		}
		listPositioned = false;
		open = true;
		await tick();
		positionList();
		listPositioned = true;
		requestAnimationFrame(positionList);
	}

	function choose(option: SelectOption) {
		if (disabled || option.disabled) return;
		onChange(option.value);
		open = false;
	}

	function handleWindowPointerDown(event: PointerEvent) {
		if (!open) return;
		const target = event.target as Node;
		// The list is portaled to <body>, so it is no longer a DOM descendant of
		// rootEl — check it separately or an option click counts as "outside".
		if (rootEl?.contains(target) || listEl?.contains(target)) return;
		open = false;
	}

	function handleWindowKeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') open = false;
	}

	function handleReposition() {
		if (!open || repositionFrame) return;
		repositionFrame = requestAnimationFrame(() => {
			repositionFrame = 0;
			positionList();
		});
	}

	onMount(() => {
		window.addEventListener('scroll', handleReposition, true);
		return () => {
			window.removeEventListener('scroll', handleReposition, true);
			if (repositionFrame) cancelAnimationFrame(repositionFrame);
		};
	});
</script>

<svelte:window
	onpointerdown={handleWindowPointerDown}
	onkeydown={handleWindowKeydown}
	onresize={handleReposition}
/>

<div class="select-menu" class:open class:disabled bind:this={rootEl}>
	<button
		bind:this={triggerEl}
		class="select-trigger"
		type="button"
		onclick={toggle}
		aria-haspopup="listbox"
		aria-expanded={open}
		aria-label={ariaLabel}
		disabled={disabled}
	>
		{#if leading}
			<span class="trigger-leading">{@render leading()}</span>
		{/if}
		<span class="trigger-copy">
			<strong>{selected?.label ?? placeholder}</strong>
			{#if selected?.description && !compact}
				<small>{selected.description}</small>
			{/if}
		</span>
		<span class="trigger-caret"><CaretDownIcon size={15} weight="bold" /></span>
	</button>

	{#if open}
		<div
			class="select-list"
			class:positioned={listPositioned}
			role="listbox"
			aria-label={ariaLabel}
			tabindex="-1"
			style={listStyle}
			bind:this={listEl}
			use:portal
			onpointerdown={(event) => event.stopPropagation()}
		>
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

	.trigger-leading {
		flex: 0 0 auto;
		display: inline-flex;
		align-items: center;
		color: var(--text-soft);
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
		/* Positioned via inline `position: fixed` style (see positionList) so the menu
		   escapes `overflow: hidden` ancestors and can flip above the trigger. */
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

	.select-list:not(.positioned) {
		visibility: hidden;
		animation: none;
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
