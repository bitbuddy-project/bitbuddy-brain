<script lang="ts">
	import { onMount } from 'svelte';
	import ListIcon from 'phosphor-svelte/lib/ListIcon';
	import NotificationToaster from '$lib/components/notifications/NotificationToaster.svelte';
	import Sidebar from '$lib/components/shell/Sidebar.svelte';
	import { theme } from '$lib/stores/theme.svelte';
	import { initializeChat } from '$lib/stores/chat.svelte';
	import { initializeNotifications } from '$lib/stores/notifications.svelte';
	import { initializeTimePreferences } from '$lib/stores/time.svelte';
	import { initializeCoding } from '$lib/stores/coding.svelte';
	import '../app.css';

	let { children } = $props();
	let sidebarCollapsed = $state(false);
	let userSidebarCollapsed = $state(false);
	let viewportZone = $state<'desktop' | 'drawer'>('desktop');
	let mobileSidebarOpen = $state(false);

	const drawerQuery = '(max-width: 1100px)';

	onMount(() => {
		initializeChat();
		initializeNotifications();
		void initializeTimePreferences();
		void initializeCoding();

		const drawerMedia = window.matchMedia(drawerQuery);
		const syncSidebarForViewport = () => {
			const nextZone = drawerMedia.matches ? 'drawer' : 'desktop';

			if (nextZone === viewportZone) return;
			viewportZone = nextZone;
			mobileSidebarOpen = false;

			if (nextZone === 'desktop') {
				sidebarCollapsed = userSidebarCollapsed;
			}
		};

		syncSidebarForViewport();
		drawerMedia.addEventListener('change', syncSidebarForViewport);

		return () => {
			drawerMedia.removeEventListener('change', syncSidebarForViewport);
		};
	});

	function toggleSidebar() {
		if (viewportZone === 'drawer') {
			mobileSidebarOpen = !mobileSidebarOpen;
			return;
		}

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

	<Sidebar collapsed={viewportZone === 'drawer' ? false : sidebarCollapsed} mobileOpen={mobileSidebarOpen} onNavigate={closeMobileSidebar} />
	<button
		class="sidebar-toggle"
		type="button"
		aria-label={viewportZone === 'drawer' ? (mobileSidebarOpen ? 'Close navigation' : 'Open navigation') : sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
		aria-pressed={viewportZone === 'drawer' ? mobileSidebarOpen : sidebarCollapsed}
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
		background:
			radial-gradient(circle at 18% 0%, color-mix(in srgb, var(--accent-soft) 72%, transparent), transparent 34rem),
			radial-gradient(circle at 92% 100%, rgba(110, 231, 183, 0.045), transparent 32rem),
			linear-gradient(180deg, color-mix(in srgb, var(--bg-soft) 36%, var(--bg)), var(--bg) 34rem);
		position: relative;
		transition: grid-template-columns 180ms cubic-bezier(0.22, 1, 0.36, 1);
	}

	:global(:root.light) .app-shell {
		background:
			radial-gradient(circle at 18% 0%, rgba(37, 99, 235, 0.09), transparent 34rem),
			radial-gradient(circle at 92% 100%, rgba(4, 120, 87, 0.035), transparent 32rem),
			linear-gradient(180deg, #dce9f5, var(--bg) 36rem);
	}

	.app-shell.sidebar-collapsed {
		--sidebar-width: 5.5rem;
	}

	.sidebar-toggle {
		position: fixed;
		top: 4.9rem;
		left: var(--sidebar-width);
		z-index: 20;
		width: 2.25rem;
		height: 2.25rem;
		display: grid;
		place-items: center;
		border: 1px solid color-mix(in srgb, var(--bg-soft) 60%, var(--border-strong));
		border-radius: 0.82rem;
		background:
			linear-gradient(
				180deg,
				color-mix(in srgb, var(--panel-raised) 76%, #10233d) 0%,
				color-mix(in srgb, var(--panel) 92%, #01050d) 100%
			);
		color: rgba(255, 255, 255, 0.86);
		box-shadow:
			0 10px 24px rgba(0, 0, 0, 0.22),
			inset 0 1px 0 rgba(255, 255, 255, 0.07);
		transform: translateX(-50%);
		transition:
			left 180ms cubic-bezier(0.22, 1, 0.36, 1),
			background 120ms ease,
			color 120ms ease,
			border-color 120ms ease;
	}

	.sidebar-toggle:hover {
		border-color: var(--accent);
		background:
			linear-gradient(
				180deg,
				color-mix(in srgb, var(--accent) 12%, var(--panel-raised)) 0%,
				color-mix(in srgb, var(--panel) 92%, #01050d) 100%
			);
		color: var(--accent);
	}

	:global(:root.light) .sidebar-toggle {
		border-color: rgba(73, 104, 145, 0.2);
		background:
			linear-gradient(
				180deg,
				color-mix(in srgb, #d8e6f4 82%, var(--panel) 18%) 0%,
				#cbdbea 100%
			);
		color: #24364d;
		box-shadow:
			0 10px 24px rgba(50, 80, 118, 0.12),
			inset 0 1px 0 rgba(255, 255, 255, 0.74);
	}

	:global(:root.light) .sidebar-toggle:hover {
		background:
			linear-gradient(
				180deg,
				color-mix(in srgb, var(--accent) 12%, #d8e6f4) 0%,
				#cbdbea 100%
			);
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
		background: transparent;
	}

	:global(:root.light) .main-content {
		background: transparent;
	}

	@media (max-width: 1100px) {
		.app-shell {
			grid-template-columns: 1fr;
		}

		.sidebar-toggle {
			top: 0.9rem;
			left: 0.9rem;
			z-index: 50;
			width: 2.6rem;
			height: 2.6rem;
			transform: none;
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

	@media (max-width: 760px) {
		.main-content {
			padding: 1rem;
		}
	}
</style>
