<script lang="ts">
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { getAutonomyStatus, getLifecycleStatus, type AutonomyStatus, type LifecycleState } from '$lib/api/bitbuddy';
	import { chatSession } from '$lib/stores/chat.svelte';
	import ProviderSwitcher from './ProviderSwitcher.svelte';
	import BookOpenIcon from 'phosphor-svelte/lib/BookOpenIcon';
	import BrainIcon from 'phosphor-svelte/lib/BrainIcon';
	import BlueprintIcon from 'phosphor-svelte/lib/BlueprintIcon';
	import CalendarBlankIcon from 'phosphor-svelte/lib/CalendarBlankIcon';
	import ChatCircleTextIcon from 'phosphor-svelte/lib/ChatCircleTextIcon';
	import ClockCounterClockwiseIcon from 'phosphor-svelte/lib/ClockCounterClockwiseIcon';
	import DevicesIcon from 'phosphor-svelte/lib/DevicesIcon';
	import EnvelopeSimpleIcon from 'phosphor-svelte/lib/EnvelopeSimpleIcon';
	import HouseLineIcon from 'phosphor-svelte/lib/HouseLineIcon';
	import GearSixIcon from 'phosphor-svelte/lib/GearSixIcon';
	import ShieldCheckIcon from 'phosphor-svelte/lib/ShieldCheckIcon';
	import SparkleIcon from 'phosphor-svelte/lib/SparkleIcon';
	import TargetIcon from 'phosphor-svelte/lib/TargetIcon';

	let {
		collapsed = false,
		mobileOpen = false,
		onNavigate = () => {}
	} = $props<{
		collapsed?: boolean;
		mobileOpen?: boolean;
		onNavigate?: () => void;
	}>();

	const navGroups = [
		{
			label: 'Core',
			items: [
				{ label: 'Chat', href: '/', icon: ChatCircleTextIcon, hint: 'Talk' },
				{ label: 'History', href: '/history', icon: ClockCounterClockwiseIcon, hint: 'Past chats' },
				{ label: 'Goals', href: '/goals', icon: TargetIcon, hint: 'Self direction' },
				{ label: 'Calendar', href: '/calendar', icon: CalendarBlankIcon, hint: 'Schedule' },
				{ label: 'Email', href: '/email', icon: EnvelopeSimpleIcon, hint: 'Inbox' },
				{ label: 'Autonomy', href: '/autonomy', icon: SparkleIcon, hint: 'Background life' }
			]
		},
		{
			label: 'Workspace',
			items: [
				{ label: 'AI Space', href: '/space', icon: HouseLineIcon, hint: 'Notes and drafts' },
				{ label: 'Projects', href: '/projects', icon: BlueprintIcon, hint: 'Context maps' },
				{ label: 'Memories', href: '/memory', icon: BrainIcon, hint: 'Recall' },
				{ label: 'Skills', href: '/skills', icon: BookOpenIcon, hint: 'Playbooks' }
			]
		},
		{
			label: 'Control',
			items: [
				{ label: 'Permissions', href: '/permissions', icon: ShieldCheckIcon, hint: 'Trust gates' },
				{ label: 'Devices', href: '/devices', icon: DevicesIcon, hint: 'Coming soon' },
				{ label: 'Settings', href: '/settings', icon: GearSixIcon, hint: 'Model + trust' }
			]
		}
	];

	let autonomyStatus = $state<AutonomyStatus | null>(null);
	let lifecycleStatus = $state<LifecycleState | null>(null);

	let statusTone = $derived.by(() => {
		if (!chatSession.initialized) return 'pending';
		if (!chatSession.serverAvailable) return 'offline';
		if (chatSession.isStreaming) return 'thinking';
		if (lifecycleStatus?.state === 'Dreaming') return 'dreaming';
		if (lifecycleStatus?.state === 'Sleep') return 'quiet';
		if (autonomyStatus?.state === 'running') return 'working';
		if (autonomyStatus?.state === 'scheduled') return 'scheduled';
		if (autonomyStatus?.state === 'disabled') return 'quiet';
		if (autonomyStatus?.state === 'blocked_by_lifecycle' || lifecycleStatus?.quiet_mode) return 'quiet';
		return 'ready';
	});

	let statusLabel = $derived.by(() => {
		if (!chatSession.initialized) return 'Starting';
		if (!chatSession.serverAvailable) return 'Offline';
		if (chatSession.isStreaming) return 'Thinking';
		if (lifecycleStatus?.state === 'Dreaming') return 'Dreaming';
		if (lifecycleStatus?.state === 'Sleep') return 'Sleeping';
		if (autonomyStatus?.state === 'running') return 'Working';
		if (autonomyStatus?.state === 'scheduled') return 'Scheduled';
		if (autonomyStatus?.state === 'disabled') return 'Manual';
		if (autonomyStatus?.state === 'blocked_by_lifecycle' || lifecycleStatus?.quiet_mode) return 'Quiet';
		return 'Ready';
	});

	let statusDetail = $derived.by(() => {
		if (!chatSession.initialized) return 'booting local state';
		if (!chatSession.serverAvailable) return 'server unavailable';
		if (chatSession.isStreaming) return 'answering now';
		if (lifecycleStatus?.state === 'Dreaming') return 'night work active';
		if (lifecycleStatus?.state === 'Sleep') return 'resting until activity';
		if (autonomyStatus?.state === 'running') return autonomyStatus.message || 'autonomy in progress';
		if (autonomyStatus?.state === 'scheduled') return autonomyStatus.message || 'autonomy queued';
		if (autonomyStatus?.state === 'disabled') return 'autonomy disabled';
		if (autonomyStatus?.state === 'blocked_by_lifecycle' || lifecycleStatus?.quiet_mode) return 'autonomy paused';
		return 'memory close · autonomy bounded';
	});

	let statusTitle = $derived(`${statusLabel}: ${statusDetail}`);

	onMount(() => {
		let cancelled = false;
		let timer: ReturnType<typeof setInterval> | undefined;

		async function refreshStatus() {
			if (!chatSession.serverAvailable) return;
			try {
				const [nextAutonomy, nextLifecycle] = await Promise.all([getAutonomyStatus(), getLifecycleStatus()]);
				if (cancelled) return;
				autonomyStatus = nextAutonomy;
				lifecycleStatus = nextLifecycle;
			} catch {
				// The chat store already owns server availability. Keep the last known sidebar state.
			}
		}

		void refreshStatus();
		timer = setInterval(() => void refreshStatus(), 15000);
		return () => {
			cancelled = true;
			if (timer) clearInterval(timer);
		};
	});

	function isActive(href: string) {
		return href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(href);
	}
</script>

<aside class="sidebar" class:collapsed class:mobile-open={mobileOpen} aria-label="Primary navigation">
	<div class="ambient-orb orb-one"></div>
	<div class="ambient-orb orb-two"></div>

	<div class="sidebar-top">
		<a class="brand" href="/" aria-label="BitBuddy home" onclick={onNavigate}>
			<div class="brand-mark">
				<img src="/bitbuddy-app.png" alt="" aria-hidden="true" />
				<span class="pulse-ring"></span>
			</div>
			<span class="brand-copy">
				<strong>BitBuddy</strong>
				<small>local evolving agent</small>
			</span>
		</a>

		<div class="status-card" aria-label={`BitBuddy status: ${statusTitle}`} title={statusTitle}>
			<span class={`status-dot ${statusTone}`}></span>
			<div class="status-copy">
				<strong>{statusLabel}</strong>
				<small>{statusDetail}</small>
			</div>
		</div>

		<nav class="nav-list">
			{#each navGroups as group}
				<section class="nav-group" class:collapsed-section={collapsed} aria-label={group.label}>
					<div class="group-label">{group.label}</div>
					<div class="group-links">
						{#each group.items as item}
							<a
								class="nav-link"
								class:active={isActive(item.href)}
								href={item.href}
								title={collapsed ? `${item.label} — ${item.hint}` : undefined}
								onclick={onNavigate}
							>
								<span class="active-rail"></span>
								<span class="icon-shell"><item.icon size={19} weight={isActive(item.href) ? 'fill' : 'regular'} /></span>
								<span class="nav-copy">
									<span class="nav-label">{item.label}</span>
									<small>{item.hint}</small>
								</span>
							</a>
						{/each}
					</div>
				</section>
			{/each}
		</nav>
	</div>

	<div class="sidebar-bottom">
		<ProviderSwitcher {collapsed} {onNavigate} />
	</div>
</aside>

<style>
	.sidebar {
		position: sticky;
		top: 1rem;
		width: calc(var(--sidebar-width) - 1rem);
		height: calc(100vh - 2rem);
		margin: 1rem 0 1rem 1rem;
		padding: 1rem;
		display: grid;
		grid-template-rows: minmax(0, 1fr) auto;
		gap: 1.35rem;
		border: 1px solid color-mix(in srgb, var(--bg-soft) 60%, var(--border-strong));
		border-radius: 1.35rem;
		background:
			linear-gradient(
				180deg,
				color-mix(in srgb, var(--panel-raised) 76%, #10233d) 0%,
				color-mix(in srgb, var(--panel) 92%, #01050d) 28%,
				color-mix(in srgb, var(--bg-soft) 96%, #01050d) 100%
			);
		box-shadow:
			0 20px 48px rgba(0, 0, 0, 0.26),
			inset 0 1px 0 rgba(255, 255, 255, 0.075);
		backdrop-filter: blur(22px) saturate(1.15);
		overflow: hidden;
		transition: padding 180ms cubic-bezier(0.22, 1, 0.36, 1);
	}

	.sidebar::before {
		content: '';
		position: absolute;
		inset: 0;
		border-top: 1px solid rgba(255, 255, 255, 0.22);
		border-radius: inherit;
		pointer-events: none;
	}

	:global(:root.light) .sidebar {
		border-color: rgba(73, 104, 145, 0.2);
		background:
			linear-gradient(
				180deg,
				color-mix(in srgb, #d8e6f4 82%, var(--panel) 18%) 0%,
				#d3e1ef 34%,
				#cbdbea 100%
			);
		box-shadow:
			0 18px 42px rgba(50, 80, 118, 0.13),
			inset 0 1px 0 rgba(255, 255, 255, 0.78);
	}

	:global(:root.light) .sidebar::before {
		border-top-color: rgba(255, 255, 255, 0.84);
	}

	.sidebar {
		scrollbar-width: none;
		-ms-overflow-style: none;
	}

	.sidebar::-webkit-scrollbar {
		width: 0;
		height: 0;
	}

	.ambient-orb {
		display: none;
		position: fixed;
		border-radius: 999px;
		filter: blur(28px);
		opacity: 0.36;
		pointer-events: none;
	}

	.orb-one {
		width: 7rem;
		height: 7rem;
		top: -2.6rem;
		right: -2.8rem;
		background: var(--accent);
	}

	.orb-two {
		width: 5rem;
		height: 5rem;
		bottom: -2rem;
		left: -2.5rem;
		background: var(--success);
	}

	.sidebar.collapsed {
		padding: 1rem 0;
	}

	.sidebar-top,
	.sidebar-bottom {
		position: relative;
		z-index: 1;
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.sidebar-top {
		flex: 1;
		min-height: 0;
		padding-right: 0.18rem;
		padding-bottom: 0.35rem;
		overflow-y: auto;
		overflow-x: hidden;
		scroll-padding-bottom: 0.35rem;
		scrollbar-width: none;
		-ms-overflow-style: none;
	}

	.sidebar-top::-webkit-scrollbar {
		width: 0;
		height: 0;
	}

	.sidebar-bottom {
		flex-shrink: 0;
	}

	.brand {
		min-width: 0;
		padding: 0.35rem;
		display: flex;
		align-items: center;
		gap: 0.78rem;
		border-radius: 1.2rem;
	}

	.brand-mark {
		position: relative;
		width: 2.75rem;
		height: 2.75rem;
		flex: 0 0 auto;
		display: grid;
		place-items: center;
		border: 0;
		border-radius: 0;
		background: transparent;
		color: var(--on-accent);
		box-shadow: none;
		overflow: visible;
	}

	.brand-mark img {
		position: relative;
		z-index: 1;
		width: 100%;
		height: 100%;
		object-fit: contain;
	}

	.pulse-ring {
		display: none;
	}

	.brand strong,
	.brand small,
	.status-copy strong,
	.status-copy small {
		display: block;
	}

	.brand strong {
		font-weight: 850;
		letter-spacing: -0.025em;
	}

	.brand small,
	.status-copy small,
	.nav-copy small {
		color: var(--text-soft);
		font-size: 0.68rem;
		font-weight: 650;
		letter-spacing: 0.035em;
		text-transform: uppercase;
	}

	.status-card {
		margin-top: 1.15rem;
		padding: 0.85rem;
		border: 1px solid color-mix(in srgb, var(--bg-soft) 54%, var(--border));
		border-radius: 0.92rem;
		background:
			linear-gradient(135deg, rgba(255, 255, 255, 0.035), transparent 64%),
			color-mix(in srgb, var(--surface-glass) 62%, transparent);
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
	}

	.status-card {
		display: flex;
		align-items: center;
		gap: 0.7rem;
	}

	.status-dot {
		width: 0.62rem;
		height: 0.62rem;
		flex: 0 0 auto;
		border-radius: 999px;
		background: var(--success);
		box-shadow: 0 0 0 5px color-mix(in srgb, var(--success) 12%, transparent), 0 0 18px color-mix(in srgb, var(--success) 58%, transparent);
	}

	.status-dot.pending,
	.status-dot.scheduled {
		background: var(--accent);
		box-shadow: 0 0 0 5px color-mix(in srgb, var(--accent) 12%, transparent), 0 0 18px color-mix(in srgb, var(--accent) 54%, transparent);
	}

	.status-dot.thinking,
	.status-dot.working,
	.status-dot.dreaming {
		background: var(--warning);
		box-shadow: 0 0 0 5px color-mix(in srgb, var(--warning) 13%, transparent), 0 0 18px color-mix(in srgb, var(--warning) 54%, transparent);
	}

	.status-dot.quiet {
		background: var(--text-soft);
		box-shadow: 0 0 0 5px color-mix(in srgb, var(--text-soft) 10%, transparent), 0 0 14px color-mix(in srgb, var(--text-soft) 32%, transparent);
	}

	.status-dot.offline {
		background: var(--danger);
		box-shadow: 0 0 0 5px color-mix(in srgb, var(--danger) 12%, transparent), 0 0 18px color-mix(in srgb, var(--danger) 48%, transparent);
	}

	.nav-list {
		display: grid;
		gap: 0.7rem;
	}

	.nav-group {
		display: grid;
		gap: 0.3rem;
	}

	.group-label {
		padding-inline: 0.65rem;
		color: var(--text-soft);
		font-size: 0.68rem;
		font-weight: 800;
		letter-spacing: 0.09em;
		text-transform: uppercase;
	}

	.group-links {
		display: grid;
		gap: 0.2rem;
	}

	.nav-link {
		position: relative;
		min-height: 2.65rem;
		padding: 0.42rem 0.62rem;
		display: flex;
		align-items: center;
		gap: 0.62rem;
		border: 1px solid transparent;
		border-radius: 0.92rem;
		color: var(--text-muted);
		font-weight: 650;
		transition:
			transform 140ms ease,
			background 140ms ease,
			border-color 140ms ease,
			color 140ms ease;
	}

	.nav-link:hover {
		transform: translateX(2px);
		border-color: color-mix(in srgb, var(--bg-soft) 52%, var(--border));
		background: color-mix(in srgb, var(--surface-glass) 66%, transparent);
		color: var(--text);
	}

	.nav-link.active {
		border-color: color-mix(in srgb, var(--accent) 18%, var(--border));
		/* The accent rail is the sole left-edge indicator — drop the border's
		   left side so it doesn't double up into a heavier left outline. */
		border-left-color: transparent;
		background:
			linear-gradient(90deg, rgba(79, 156, 255, 0.16), transparent),
			color-mix(in srgb, var(--surface-glass) 70%, transparent);
		color: var(--accent-strong);
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
	}

	.active-rail {
		position: absolute;
		left: 0;
		width: 3px;
		height: 1.35rem;
		border-radius: 999px;
		background: var(--accent);
		opacity: 0;
		transform: scaleY(0.6);
		transition: 140ms ease;
	}

	.nav-link.active .active-rail {
		opacity: 1;
		transform: scaleY(1);
	}

	.icon-shell {
		width: 1.78rem;
		height: 1.78rem;
		flex: 0 0 auto;
		display: grid;
		place-items: center;
		border-radius: 0.65rem;
		background: color-mix(in srgb, var(--surface-card) 64%, transparent);
	}

	.nav-link.active .icon-shell {
		background: color-mix(in srgb, var(--accent-soft) 80%, transparent);
	}

	.nav-copy,
	.brand-copy,
	.status-copy,
	.group-label {
		min-width: 0;
		transition:
			opacity 120ms ease,
			width 180ms cubic-bezier(0.22, 1, 0.36, 1),
			transform 180ms cubic-bezier(0.22, 1, 0.36, 1);
	}

	.nav-copy {
		display: grid;
		gap: 0;
		line-height: 1.15;
	}

	.nav-label {
		white-space: nowrap;
		font-size: 0.92rem;
	}

	.sidebar.collapsed .brand-copy,
	.sidebar.collapsed .nav-copy {
		width: 0;
		opacity: 0;
		overflow: hidden;
		transform: translateX(-0.4rem);
		pointer-events: none;
	}

	.sidebar.collapsed .group-label {
		display: none;
	}

	.sidebar.collapsed .status-card {
		width: 3.2rem;
		height: 3.2rem;
		min-height: 3.2rem;
		padding: 0;
		display: grid;
		place-items: center;
		border-radius: 0.92rem;
	}

	.sidebar.collapsed .status-copy {
		display: none;
	}

	.sidebar.collapsed {
		gap: 1rem;
	}

	.sidebar.collapsed .sidebar-top,
	.sidebar.collapsed .sidebar-bottom,
	.sidebar.collapsed .nav-list,
	.sidebar.collapsed .group-links {
		width: 100%;
		align-items: center;
		justify-items: center;
	}

	.sidebar.collapsed .sidebar-top {
		gap: 1rem;
		padding-right: 0;
		padding-bottom: 0.45rem;
	}

	.sidebar.collapsed .sidebar-bottom {
		gap: 0;
	}

	.sidebar.collapsed .nav-list {
		gap: 0.34rem;
	}

	.sidebar.collapsed .nav-group {
		display: grid;
		gap: 0.34rem;
		justify-items: center;
	}

	.sidebar.collapsed .collapsed-section:not(:first-child)::before {
		content: '';
		display: block;
		width: 2.2rem;
		height: 1px;
		margin: 0.38rem auto;
		border-radius: 999px;
		background: linear-gradient(90deg, transparent, var(--border-strong), transparent);
	}

	.sidebar.collapsed .group-links {
		gap: 0.34rem;
	}

	.sidebar.collapsed .brand,
	.sidebar.collapsed .nav-link {
		width: 3.2rem;
		height: 3.2rem;
		min-height: 3.2rem;
		margin-inline: auto;
		align-self: center;
		justify-content: center;
		gap: 0;
		padding: 0;
		border-radius: 0.92rem;
	}

	.sidebar.collapsed .brand-mark,
	.sidebar.collapsed .icon-shell {
		width: 2.1rem;
		height: 2.1rem;
		border-radius: 0.8rem;
	}

	.sidebar.collapsed .brand-mark {
		box-shadow: none;
	}

	.sidebar.collapsed .nav-link:hover {
		transform: translateX(0) translateY(-1px);
	}

	.sidebar.collapsed .active-rail {
		left: 0.12rem;
	}

	@media (max-width: 1100px) {
		.sidebar {
			position: fixed;
			inset: 1rem auto 1rem 1rem;
			z-index: 40;
			width: min(21rem, calc(100vw - 2.4rem));
			height: calc(100dvh - 2rem);
			margin: 0;
			padding: 1rem;
			gap: 1.5rem;
			border: 1px solid color-mix(in srgb, var(--bg-soft) 60%, var(--border-strong));
			border-radius: 1.35rem;
			background:
				linear-gradient(
					180deg,
					color-mix(in srgb, var(--panel-raised) 76%, #10233d) 0%,
					color-mix(in srgb, var(--panel) 92%, #01050d) 28%,
					color-mix(in srgb, var(--bg-soft) 96%, #01050d) 100%
				);
			box-shadow: 18px 0 52px rgba(0, 0, 0, 0.42);
			justify-content: flex-start;
			transform: translateX(calc(-100% - 1.2rem));
			transition:
				transform 220ms cubic-bezier(0.22, 1, 0.36, 1),
				padding 180ms cubic-bezier(0.22, 1, 0.36, 1);
		}

		.sidebar.mobile-open {
			transform: translateX(0);
		}

		:global(:root.light) .sidebar {
			border-color: rgba(73, 104, 145, 0.2);
			background:
				linear-gradient(
					180deg,
					color-mix(in srgb, #d8e6f4 82%, var(--panel) 18%) 0%,
					#d3e1ef 34%,
					#cbdbea 100%
				);
			box-shadow: 18px 0 52px rgba(50, 80, 118, 0.24);
		}

		.sidebar.collapsed .brand-copy,
		.sidebar.collapsed .status-card,
		.sidebar.collapsed .group-label,
		.sidebar.collapsed .nav-copy {
			display: initial;
			width: auto;
			opacity: 1;
			transform: none;
			pointer-events: auto;
		}

		.sidebar.collapsed .status-card {
			display: flex;
			width: auto;
			height: auto;
			min-height: auto;
			padding: 0.85rem;
		}

		.sidebar.collapsed .status-copy {
			display: block;
		}

		.sidebar.collapsed .group-label {
			display: block;
		}

		.sidebar.collapsed .collapsed-section:not(:first-child)::before {
			display: none;
		}

		.sidebar.collapsed .nav-copy,
		.sidebar.collapsed .brand-copy {
			display: grid;
		}

		.sidebar.collapsed .nav-group {
			display: grid;
		}

		.sidebar.collapsed .sidebar-bottom {
			gap: 1rem;
		}

		.sidebar.collapsed .brand,
		.sidebar.collapsed .nav-link {
			justify-content: flex-start;
			gap: 0.72rem;
			padding: 0.58rem 0.68rem;
		}
	}
</style>
