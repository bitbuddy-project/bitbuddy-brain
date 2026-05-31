<script lang="ts">
	import { page } from '$app/state';
	import BookOpenIcon from 'phosphor-svelte/lib/BookOpenIcon';
	import BrainIcon from 'phosphor-svelte/lib/BrainIcon';
	import BlueprintIcon from 'phosphor-svelte/lib/BlueprintIcon';
	import ChatCircleTextIcon from 'phosphor-svelte/lib/ChatCircleTextIcon';
	import ClockCounterClockwiseIcon from 'phosphor-svelte/lib/ClockCounterClockwiseIcon';
	import DevicesIcon from 'phosphor-svelte/lib/DevicesIcon';
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
				{ label: 'Autonomy', href: '/autonomy', icon: SparkleIcon, hint: 'Background life' }
			]
		},
		{
			label: 'Workspace',
			items: [
				{ label: 'Projects', href: '/projects', icon: BlueprintIcon, hint: 'Context maps' },
				{ label: 'Memories', href: '/memory', icon: BrainIcon, hint: 'Recall' },
				{ label: 'Skills', href: '/skills', icon: BookOpenIcon, hint: 'Playbooks' }
			]
		},
		{
			label: 'Control',
			items: [
				{ label: 'Permissions', href: '/permissions', icon: ShieldCheckIcon, hint: 'Trust gates' },
				{ label: 'Devices', href: '/devices', icon: DevicesIcon, hint: 'Companions' }
			]
		}
	];

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
				<BrainIcon size={24} weight="duotone" />
				<span class="pulse-ring"></span>
			</div>
			<span class="brand-copy">
				<strong>BitBuddy</strong>
				<small>local evolving agent</small>
			</span>
		</a>

		<div class="status-card" aria-label="BitBuddy status">
			<span class="status-dot"></span>
			<div class="status-copy">
				<strong>Awake</strong>
				<small>memory close · autonomy bounded</small>
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
								<span class="icon-shell"><item.icon size={21} weight={isActive(item.href) ? 'fill' : 'regular'} /></span>
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
		<a
			class="nav-link settings-link compact-settings"
			class:active={page.url.pathname === '/settings'}
			href="/settings"
			title={collapsed ? 'Settings' : undefined}
			onclick={onNavigate}
		>
			<span class="active-rail"></span>
			<span class="icon-shell"><GearSixIcon size={21} weight={page.url.pathname === '/settings' ? 'fill' : 'regular'} /></span>
			<span class="nav-copy">
				<span class="nav-label">Settings</span>
				<small>Model + trust</small>
			</span>
		</a>
	</div>
</aside>

<style>
	.sidebar {
		position: sticky;
		top: 0;
		height: 100vh;
		padding: 1rem;
		display: grid;
		grid-template-rows: minmax(0, 1fr) auto;
		gap: 1.35rem;
		border-right: 1px solid color-mix(in srgb, var(--border-strong) 72%, transparent);
		background:
			linear-gradient(180deg, color-mix(in srgb, var(--bg-soft) 94%, transparent), color-mix(in srgb, var(--panel) 92%, transparent)),
			radial-gradient(circle at 20% 0%, color-mix(in srgb, var(--accent) 18%, transparent), transparent 18rem);
		backdrop-filter: blur(22px) saturate(1.15);
		overflow: hidden;
		transition: padding 180ms cubic-bezier(0.22, 1, 0.36, 1);
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
		border: 1px solid color-mix(in srgb, var(--accent) 46%, transparent);
		border-radius: 1rem;
		background:
			linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--success) 82%, var(--accent))),
			var(--panel-raised);
		color: var(--on-accent);
		box-shadow: 0 12px 34px color-mix(in srgb, var(--accent) 24%, transparent);
	}

	.pulse-ring {
		position: absolute;
		inset: -4px;
		border: 1px solid color-mix(in srgb, var(--accent) 34%, transparent);
		border-radius: 1.2rem;
		opacity: 0.65;
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
		padding: 0.85rem;
		border: 1px solid var(--border);
		border-radius: 1rem;
		background: color-mix(in srgb, var(--surface-glass) 78%, transparent);
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
		box-shadow: 0 0 0 5px color-mix(in srgb, var(--success) 12%, transparent), 0 0 18px color-mix(in srgb, var(--success) 68%, transparent);
	}

	.nav-list {
		display: grid;
		gap: 1rem;
	}

	.nav-group {
		display: grid;
		gap: 0.4rem;
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
		gap: 0.28rem;
	}

	.nav-link {
		position: relative;
		min-height: 3.2rem;
		padding: 0.58rem 0.68rem;
		display: flex;
		align-items: center;
		gap: 0.72rem;
		border: 1px solid transparent;
		border-radius: 1rem;
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
		border-color: var(--border);
		background: color-mix(in srgb, var(--surface-glass) 90%, transparent);
		color: var(--text);
	}

	.nav-link.active {
		border-color: color-mix(in srgb, var(--accent) 38%, var(--border));
		background:
			linear-gradient(90deg, color-mix(in srgb, var(--accent) 17%, transparent), transparent),
			color-mix(in srgb, var(--surface-glass) 85%, transparent);
		color: var(--accent-strong);
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
	}

	.active-rail {
		position: absolute;
		left: -1px;
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
		width: 2rem;
		height: 2rem;
		flex: 0 0 auto;
		display: grid;
		place-items: center;
		border-radius: 0.78rem;
		background: color-mix(in srgb, var(--surface-card) 80%, transparent);
	}

	.nav-link.active .icon-shell {
		background: color-mix(in srgb, var(--accent-soft) 80%, transparent);
	}

	.compact-settings {
		min-height: 2.7rem;
		padding-block: 0.42rem;
		border-radius: 0.9rem;
	}

	.compact-settings .icon-shell {
		width: 2rem;
		height: 2rem;
		border-radius: 0.78rem;
	}

	.compact-settings .nav-copy small {
		display: block;
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
		gap: 0.05rem;
	}

	.nav-label {
		white-space: nowrap;
	}

	.sidebar.collapsed .brand-copy,
	.sidebar.collapsed .nav-copy {
		width: 0;
		opacity: 0;
		overflow: hidden;
		transform: translateX(-0.4rem);
		pointer-events: none;
	}

	.sidebar.collapsed .status-card,
	.sidebar.collapsed .group-label {
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
		border-radius: 1rem;
	}

	.sidebar.collapsed .brand-mark,
	.sidebar.collapsed .icon-shell,
	.sidebar.collapsed .compact-settings .icon-shell {
		width: 2.1rem;
		height: 2.1rem;
		border-radius: 0.8rem;
	}

	.sidebar.collapsed .brand-mark {
		box-shadow: 0 8px 22px color-mix(in srgb, var(--accent) 20%, transparent);
	}

	.sidebar.collapsed .settings-link {
		margin-top: 0;
	}

	.sidebar.collapsed .nav-link:hover {
		transform: translateX(0) translateY(-1px);
	}

	.sidebar.collapsed .active-rail {
		left: 0.12rem;
	}

	@media (max-width: 760px) {
		.sidebar {
			position: fixed;
			inset: 0 auto 0 0;
			z-index: 40;
			width: min(19.5rem, calc(100vw - 2.4rem));
			height: 100dvh;
			padding: 1rem;
			gap: 1.5rem;
			border-right: 1px solid var(--border);
			background: var(--panel);
			box-shadow: 18px 0 48px rgba(0, 0, 0, 0.38);
			justify-content: flex-start;
			transform: translateX(-105%);
			transition:
				transform 220ms cubic-bezier(0.22, 1, 0.36, 1),
				padding 180ms cubic-bezier(0.22, 1, 0.36, 1);
		}

		.sidebar.mobile-open {
			transform: translateX(0);
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
