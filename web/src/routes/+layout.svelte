<script lang="ts">
	import { onMount } from 'svelte';
	import ListIcon from 'phosphor-svelte/lib/ListIcon';
	import NotificationToaster from '$lib/components/notifications/NotificationToaster.svelte';
	import Sidebar from '$lib/components/shell/Sidebar.svelte';
	import { theme } from '$lib/stores/theme.svelte';
	import { initializeChat } from '$lib/stores/chat.svelte';
	import { initializeNotifications } from '$lib/stores/notifications.svelte';
	import { initializeTimePreferences } from '$lib/stores/time.svelte';
	import '../app.css';

	let { children } = $props();
	let sidebarCollapsed = $state(false);
	let userSidebarCollapsed = $state(false);
	let viewportZone = $state<'desktop' | 'tablet' | 'mobile'>('desktop');
	let mobileSidebarOpen = $state(false);

	const tabletQuery = '(min-width: 761px) and (max-width: 1100px)';
	const mobileQuery = '(max-width: 760px)';

	onMount(() => {
		initializeChat();
		initializeNotifications();
		void initializeTimePreferences();

		const tabletMedia = window.matchMedia(tabletQuery);
		const mobileMedia = window.matchMedia(mobileQuery);
		const syncSidebarForViewport = () => {
			const nextZone = mobileMedia.matches ? 'mobile' : tabletMedia.matches ? 'tablet' : 'desktop';

			if (nextZone === viewportZone) return;
			viewportZone = nextZone;
			mobileSidebarOpen = false;

			if (nextZone === 'tablet') {
				sidebarCollapsed = true;
			} else if (nextZone === 'desktop') {
				sidebarCollapsed = userSidebarCollapsed;
			}
		};

		syncSidebarForViewport();
		tabletMedia.addEventListener('change', syncSidebarForViewport);
		mobileMedia.addEventListener('change', syncSidebarForViewport);

		return () => {
			tabletMedia.removeEventListener('change', syncSidebarForViewport);
			mobileMedia.removeEventListener('change', syncSidebarForViewport);
		};
	});

	function toggleSidebar() {
		if (viewportZone === 'mobile') {
			mobileSidebarOpen = !mobileSidebarOpen;
			return;
		}

		if (viewportZone === 'tablet') return;

		sidebarCollapsed = !sidebarCollapsed;
		userSidebarCollapsed = sidebarCollapsed;
	}

	function closeMobileSidebar() {
		mobileSidebarOpen = false;
	}
</script>

<svelte:head>
	<title>BitBuddy</title>
</svelte:head>

<div class="app-shell" class:sidebar-collapsed={sidebarCollapsed} class:mobile-sidebar-open={mobileSidebarOpen}>
	<button
		class="mobile-sidebar-backdrop"
		type="button"
		aria-label="Close navigation"
		onclick={closeMobileSidebar}
	></button>

	<Sidebar collapsed={viewportZone === 'mobile' ? false : sidebarCollapsed} mobileOpen={mobileSidebarOpen} onNavigate={closeMobileSidebar} />
	<button
		class="sidebar-toggle"
		type="button"
		aria-label={viewportZone === 'mobile' ? (mobileSidebarOpen ? 'Close navigation' : 'Open navigation') : sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
		aria-pressed={viewportZone === 'mobile' ? mobileSidebarOpen : sidebarCollapsed}
		onclick={toggleSidebar}
	>
		<ListIcon size={18} weight="bold" />
	</button>

	<main class="main-content">
		{@render children()}
	</main>
</div>

<NotificationToaster />

<style>
	.app-shell {
		--sidebar-width: 17.5rem;
		min-height: 100vh;
		display: grid;
		grid-template-columns: var(--sidebar-width) 1fr;
		background: var(--bg);
		position: relative;
		transition: grid-template-columns 180ms cubic-bezier(0.22, 1, 0.36, 1);
	}

	.app-shell.sidebar-collapsed {
		--sidebar-width: 5.5rem;
	}

	.sidebar-toggle {
		position: fixed;
		top: 3.25rem;
		left: var(--sidebar-width);
		z-index: 20;
		width: 2.25rem;
		height: 2.25rem;
		display: grid;
		place-items: center;
		border: 1px solid var(--border-strong);
		border-radius: 999px;
		background: var(--bg-soft);
		color: var(--text-muted);
		box-shadow: var(--shadow-panel);
		transform: translateX(-50%);
		transition:
			left 180ms cubic-bezier(0.22, 1, 0.36, 1),
			background 120ms ease,
			color 120ms ease,
			border-color 120ms ease;
	}

	.sidebar-toggle:hover {
		border-color: var(--accent);
		background: var(--panel-raised);
		color: var(--accent);
	}

	.mobile-sidebar-backdrop {
		display: none;
	}

	.main-content {
		min-width: 0;
		height: 100vh;
		display: flex;
		flex-direction: column;
		align-items: center;
		padding: 1.5rem;
		overflow: hidden;
		background:
			radial-gradient(circle at top left, var(--accent-soft), transparent 40rem),
			radial-gradient(circle at bottom right, rgba(110, 231, 183, 0.05), transparent 30rem);
	}

	:global(:root.light) .main-content {
		background: var(--bg);
	}

	@media (max-width: 760px) {
		.app-shell {
			grid-template-columns: 1fr;
		}

		.sidebar-toggle {
			top: 0.9rem;
			left: 0.9rem;
			z-index: 50;
			width: 2.6rem;
			height: 2.6rem;
			background: color-mix(in srgb, var(--panel) 88%, transparent);
			transform: none;
			backdrop-filter: blur(16px);
		}

		.mobile-sidebar-backdrop {
			display: block;
			position: fixed;
			inset: 0;
			z-index: 30;
			border: 0;
			background: rgba(0, 0, 0, 0.45);
			opacity: 0;
			pointer-events: none;
			transition: opacity 180ms ease;
		}

		.app-shell.mobile-sidebar-open .mobile-sidebar-backdrop {
			opacity: 1;
			pointer-events: auto;
		}

		.main-content {
			height: auto;
			min-height: calc(100vh - 5rem);
			padding-top: 4.25rem;
		}
	}

	@media (min-width: 761px) and (max-width: 1100px) {
		.sidebar-toggle {
			display: none;
		}
	}

	@media (max-width: 760px) {
		.main-content {
			padding: 1rem;
		}
	}
</style>
