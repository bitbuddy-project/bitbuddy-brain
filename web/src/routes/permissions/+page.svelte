<script lang="ts">
	import { onMount } from 'svelte';
	import Skeleton from '$lib/components/Skeleton.svelte';
	import PageHeader from '$lib/components/PageHeader.svelte';
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
	<PageHeader icon={ShieldCheck} eyebrow="Security & Control" title="Permissions" subtitle="Review and audit tool permission requests.">
		{#snippet action()}
				<div class="log-status">
					<ClockCounterClockwise size={18} />
					<span>Audit Log</span>
				</div>
			{/snippet}
	</PageHeader>
	<div class="permissions-card">

		<div class="activity-toolbar">
			<span>Permission Logs</span>
		</div>

		<div class="card-content">
			{#if loading}
				<Skeleton variant="row" count={5} />
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
		flex-direction: column;
		gap: 0.7rem;
		min-height: 0;
		animation: fade-in 0.35s cubic-bezier(0.16, 1, 0.3, 1);
	}

	@keyframes fade-in {
		from { opacity: 0; transform: translateY(12px); }
		to { opacity: 1; transform: translateY(0); }
	}

	.permissions-card {
		--page-accent: var(--accent);
		--page-soft: color-mix(in srgb, var(--accent-soft) 72%, transparent);
		--page-border: color-mix(in srgb, var(--accent) 20%, var(--border));
		--page-glow: color-mix(in srgb, var(--accent) 10%, transparent);

		width: 100%;
		flex: 1 1 auto;
		min-height: 0;
		display: flex;
		flex-direction: column;
		border: 1px solid var(--page-border);
		border-radius: 1.45rem;
		background:
			linear-gradient(135deg, var(--glass-overlay), transparent 22rem),
			radial-gradient(circle at top right, var(--page-glow), transparent 30rem),
			radial-gradient(circle at bottom left, color-mix(in srgb, var(--success) 5.5%, transparent), transparent 34rem),
			var(--panel);
		box-shadow: var(--shadow-chat);
		overflow: hidden;
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
		border-radius: var(--radius-panel);
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

	@media (max-width: 760px) {
		.permissions-page,
		.permissions-card {
			height: auto;
			max-height: none;
		}

		.log-status {
			width: 100%;
		}
	}
</style>
