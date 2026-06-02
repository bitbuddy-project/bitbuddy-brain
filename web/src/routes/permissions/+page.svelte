<script lang="ts">
	import { onMount } from 'svelte';
	import { getPermissionActivity, type ActivityItem } from '$lib/api/bitbuddy';
	import ActivityList from '$lib/components/activity/ActivityList.svelte';
	import ShieldCheck from 'phosphor-svelte/lib/ShieldCheck';
	import ClockCounterClockwise from 'phosphor-svelte/lib/ClockCounterClockwise';

	let activity = $state<ActivityItem[]>([]);
	let error = $state('');
	let loading = $state(true);

	onMount(() => {
		void refreshActivity();
		const timer = window.setInterval(refreshActivity, 5000);
		return () => window.clearInterval(timer);
	});

	async function refreshActivity() {
		try {
			activity = await getPermissionActivity();
			error = '';
		} catch (e: any) {
			error = e.message;
		} finally {
			loading = false;
		}
	}
</script>

<div class="permissions-page">
	<div class="permissions-card">
		<header class="permissions-header">
			<div class="title-mark" aria-hidden="true">
				<ShieldCheck size={30} weight="duotone" />
			</div>
			<div class="title-copy">
				<p class="eyebrow">Security & Control</p>
				<h1>Permissions</h1>
				<p>Review and audit tool permission requests.</p>
			</div>
			<div class="log-status">
				<ClockCounterClockwise size={18} />
				<span>Audit Log</span>
			</div>
		</header>

		<div class="activity-toolbar">
			<span>Permission Logs</span>
		</div>

		<div class="card-content">
			{#if loading}
				<div class="loading-state">
					<div class="spinner"></div>
					<span>Loading activity...</span>
				</div>
			{:else if !error && activity.length === 0}
				<div class="center-state empty-state">
					<div class="empty-icon" aria-hidden="true">
						<ShieldCheck size={42} weight="duotone" />
					</div>
					<h2>No permissions for this session</h2>
					<p>Permission requests will appear here when BitBuddy needs approval for a protected action.</p>
				</div>
			{:else}
				<ActivityList {activity} {error} />
			{/if}
		</div>
	</div>
</div>

<style>
	.permissions-page {
		width: 100%;
		max-width: 100%;
		padding: 0 1rem;
		height: 100%;
		margin: 0 auto;
		display: flex;
		min-height: 0;
		animation: fade-in 0.35s cubic-bezier(0.16, 1, 0.3, 1);
	}

	@keyframes fade-in {
		from { opacity: 0; transform: translateY(12px); }
		to { opacity: 1; transform: translateY(0); }
	}

	.permissions-card {
		--page-accent: #fbbf24;
		--page-soft: rgba(251, 191, 36, 0.12);
		--page-border: rgba(251, 191, 36, 0.25);
		--page-glow: rgba(251, 191, 36, 0.14);

		width: 100%;
		height: 100%;
		max-height: calc(100vh - 3rem);
		min-height: 0;
		display: flex;
		flex-direction: column;
		border: 1px solid var(--page-border);
		border-radius: 1.45rem;
		background:
			linear-gradient(135deg, var(--glass-overlay), transparent 22rem),
			radial-gradient(circle at top right, var(--page-glow), transparent 30rem),
			radial-gradient(circle at bottom left, rgba(110, 231, 183, 0.055), transparent 34rem),
			var(--panel);
		box-shadow: var(--shadow-chat);
		overflow: hidden;
	}

	:global(:root.light) .permissions-card {
		--page-accent: #d97706;
		--page-soft: rgba(217, 119, 6, 0.12);
		--page-border: rgba(217, 119, 6, 0.25);
		--page-glow: rgba(217, 119, 6, 0.14);
	}

	.permissions-header {
		flex: 0 0 auto;
		padding: 1.35rem 1.5rem;
		display: flex;
		align-items: center;
		gap: 1rem;
		border-bottom: 1px solid var(--border);
		background:
			linear-gradient(135deg, var(--page-soft), transparent 70%),
			var(--header-bg);
	}

	.title-mark {
		width: 3.5rem;
		height: 3.5rem;
		display: grid;
		place-items: center;
		border-radius: 1.1rem;
		background: var(--surface-glass);
		border: 1px solid var(--page-border);
		color: var(--page-accent);
		box-shadow: 0 0 20px var(--page-soft);
		flex: 0 0 auto;
	}

	.title-copy {
		min-width: 0;
		flex: 1 1 auto;
	}

	.eyebrow {
		color: var(--page-accent);
		font-size: 0.72rem;
		font-weight: 800;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	h1 {
		font-size: 1.65rem;
		font-weight: 900;
		letter-spacing: -0.03em;
		line-height: 1.1;
	}

	.title-copy p:last-child {
		color: var(--text-soft);
	}

	.log-status,
	.activity-toolbar {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		font-size: 0.85rem;
		font-weight: 700;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.log-status {
		flex: 0 0 auto;
	}

	.activity-toolbar {
		flex: 0 0 auto;
		justify-content: space-between;
		padding: 1rem 1.5rem;
		border-bottom: 1px solid var(--border);
		background: var(--surface-card);
	}

	.card-content {
		min-height: 0;
		flex: 1 1 auto;
		padding: 1.25rem 1.5rem 1.5rem;
		overflow-y: auto;
		scrollbar-color: var(--scrollbar-thumb) transparent;
	}

	.center-state {
		min-height: 22rem;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 1rem;
		text-align: center;
	}

	.center-state h2 {
		color: var(--text);
		font-size: 1.35rem;
		font-weight: 900;
		letter-spacing: -0.02em;
	}

	.center-state p {
		max-width: 28rem;
		color: var(--text-soft);
	}

	.empty-icon {
		width: 5rem;
		height: 5rem;
		display: grid;
		place-items: center;
		border-radius: 1.5rem;
		background: var(--page-soft);
		color: var(--page-accent);
	}

	.loading-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 1rem;
		padding: 4rem;
		color: var(--text-soft);
	}

	.spinner {
		width: 2rem;
		height: 2rem;
		border: 2px solid var(--border);
		border-top-color: var(--page-accent);
		border-radius: 50%;
		animation: spin 1s linear infinite;
	}

	@keyframes spin {
		to { transform: rotate(360deg); }
	}

	@media (max-width: 760px) {
		.permissions-page,
		.permissions-card {
			height: auto;
			max-height: none;
		}

		.permissions-header {
			align-items: flex-start;
			flex-wrap: wrap;
		}

		.title-mark {
			width: 3rem;
			height: 3rem;
		}

		.log-status {
			width: 100%;
		}
	}
</style>
