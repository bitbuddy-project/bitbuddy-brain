<script lang="ts">
	import { onMount, tick } from 'svelte';
	import { portal } from '$lib/actions/portal';
	import CaretDownIcon from 'phosphor-svelte/lib/CaretDownIcon';

	type SelectOption = { label: string; value: string; description?: string };

	let {
		value = $bindable(''),
		options,
		placeholder = 'Select…',
		disabled = false,
		ariaLabel,
		onChange
	}: {
		value?: string;
		options: SelectOption[];
		placeholder?: string;
		disabled?: boolean;
		ariaLabel?: string;
		onChange?: (value: string) => void;
	} = $props();

	let open = $state(false);
	let rootElement: HTMLDivElement | null = $state(null);
	let menuElement: HTMLDivElement | null = $state(null);
	let activeIndex = $state(0);
	let direction = $state<'up' | 'down'>('down');
	let menuStyle = $state('');

	const selectedOption = $derived(options.find((option) => option.value === value) ?? null);

	$effect(() => {
		const index = options.findIndex((option) => option.value === value);
		activeIndex = Math.max(0, index);
	});

	onMount(() => {
		function handlePointerDown(event: PointerEvent) {
			const target = event.target as Node;
			if (!rootElement?.contains(target) && !menuElement?.contains(target)) open = false;
		}
		function handleViewportChange() {
			if (open) positionMenu();
		}
		document.addEventListener('pointerdown', handlePointerDown);
		window.addEventListener('resize', handleViewportChange);
		window.addEventListener('scroll', handleViewportChange, true);
		return () => {
			document.removeEventListener('pointerdown', handlePointerDown);
			window.removeEventListener('resize', handleViewportChange);
			window.removeEventListener('scroll', handleViewportChange, true);
		};
	});

	function positionMenu() {
		if (!rootElement) return;
		const rect = rootElement.getBoundingClientRect();
		const estimated = Math.min(288, Math.max(48, options.length * 50));
		const menuHeight = menuElement?.offsetHeight || estimated;
		const gap = 6;
		const pad = 8;
		const spaceBelow = window.innerHeight - rect.bottom - pad;
		const spaceAbove = rect.top - pad;
		direction = spaceBelow < menuHeight && spaceAbove > spaceBelow ? 'up' : 'down';
		const available = Math.max(48, direction === 'up' ? spaceAbove - gap : spaceBelow - gap);
		const maxHeight = Math.min(288, available);
		const top =
			direction === 'up'
				? Math.max(pad, rect.top - gap - Math.min(menuHeight, maxHeight))
				: Math.min(window.innerHeight - pad - 48, rect.bottom + gap);
		const width = Math.min(Math.max(rect.width, 220), window.innerWidth - pad * 2);
		const left = Math.min(Math.max(pad, rect.left), Math.max(pad, window.innerWidth - width - pad));
		menuStyle = `--sel-top:${top}px;--sel-left:${left}px;--sel-width:${width}px;--sel-max:${maxHeight}px;`;
	}

	async function openMenu() {
		if (disabled) return;
		positionMenu();
		open = true;
		await tick();
		positionMenu();
	}

	function choose(option: SelectOption) {
		value = option.value;
		onChange?.(option.value);
		open = false;
	}

	function toggle() {
		if (disabled) return;
		if (open) open = false;
		else void openMenu();
	}

	function handleKeydown(event: KeyboardEvent) {
		if (disabled) return;
		if (event.key === 'ArrowDown') {
			event.preventDefault();
			void openMenu();
			activeIndex = (activeIndex + 1) % options.length;
		} else if (event.key === 'ArrowUp') {
			event.preventDefault();
			void openMenu();
			activeIndex = (activeIndex - 1 + options.length) % options.length;
		} else if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			if (open) choose(options[activeIndex]);
			else void openMenu();
		} else if (event.key === 'Escape') {
			open = false;
		}
	}
</script>

<div class="select" bind:this={rootElement} data-open={open}>
	<button
		class="select-trigger"
		type="button"
		aria-haspopup="listbox"
		aria-expanded={open}
		aria-label={ariaLabel}
		{disabled}
		onclick={toggle}
		onkeydown={handleKeydown}
	>
		<span class="select-value" class:placeholder={!selectedOption}>
			{selectedOption?.label ?? placeholder}
		</span>
		<CaretDownIcon size={15} weight="bold" />
	</button>

	{#if open}
		<div
			class="select-menu"
			style={menuStyle}
			use:portal
			bind:this={menuElement}
			role="listbox"
			tabindex="-1"
		>
			{#each options as option, index (option.value)}
				<button
					class="select-option"
					class:active={option.value === value}
					class:focused={index === activeIndex}
					type="button"
					role="option"
					aria-selected={option.value === value}
					onpointerenter={() => (activeIndex = index)}
					onclick={() => choose(option)}
				>
					<span class="option-copy">
						<strong>{option.label}</strong>
						{#if option.description}<small>{option.description}</small>{/if}
					</span>
				</button>
			{/each}
		</div>
	{/if}
</div>

<style>
	.select {
		position: relative;
		display: block;
		min-width: 0;
	}

	.select-trigger {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.6rem;
		width: 100%;
		min-height: 2.6rem;
		padding: 0.6rem 0.8rem;
		border: 1px solid var(--border);
		border-radius: 0.8rem;
		background: var(--surface-inset);
		color: var(--text);
		cursor: pointer;
		font: inherit;
		text-align: left;
		transition: border-color 140ms ease, box-shadow 140ms ease;
	}

	.select-trigger:hover:not(:disabled),
	.select[data-open='true'] .select-trigger {
		border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 12%, transparent);
	}

	.select-trigger:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.select-value {
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-weight: 650;
	}

	.select-value.placeholder {
		color: var(--text-soft);
		font-weight: 550;
	}

	.select-trigger :global(svg) {
		flex: 0 0 auto;
		color: var(--text-soft);
	}

	.select-menu {
		position: fixed;
		z-index: 1300;
		top: var(--sel-top, 0);
		left: var(--sel-left, 0);
		width: var(--sel-width, 14rem);
		max-height: var(--sel-max, 18rem);
		display: grid;
		gap: 0.2rem;
		padding: 0.35rem;
		border: 1px solid var(--card-border);
		border-radius: 0.85rem;
		background: var(--panel-raised);
		box-shadow: 0 20px 48px rgba(0, 0, 0, 0.4), inset 0 1px 0 var(--card-inner-line);
		overflow-y: auto;
		scrollbar-color: var(--scrollbar-thumb) transparent;
		animation: select-pop 140ms ease;
	}

	.select-option {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		padding: 0.5rem 0.6rem;
		border: 1px solid transparent;
		border-radius: 0.6rem;
		background: transparent;
		color: var(--text-muted);
		cursor: pointer;
		font: inherit;
		text-align: left;
	}

	.select-option.focused {
		background: color-mix(in srgb, var(--surface-glass) 70%, transparent);
		color: var(--text);
	}

	.select-option.active {
		border-color: color-mix(in srgb, var(--accent) 30%, var(--border));
		background: color-mix(in srgb, var(--accent-soft) 55%, transparent);
		color: var(--accent-strong);
	}

	.option-copy {
		display: grid;
		gap: 0.05rem;
		min-width: 0;
	}

	.option-copy strong {
		font-weight: 700;
		font-size: 0.9rem;
	}

	.option-copy small {
		color: var(--text-soft);
		font-size: 0.74rem;
	}

	@keyframes select-pop {
		from { opacity: 0; transform: translateY(-4px); }
		to { opacity: 1; transform: translateY(0); }
	}
</style>
