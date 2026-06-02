<script lang="ts">
	import DevicesIcon from 'phosphor-svelte/lib/DevicesIcon';
	import ArrowLeftIcon from 'phosphor-svelte/lib/ArrowLeftIcon';
</script>

<div class="placeholder-page">
	<header class="page-header">
		<div class="fancy-title">
			<div class="title-icon">
				<DevicesIcon size={32} weight="duotone" />
			</div>
			<div class="title-text">
				<h1>Devices</h1>
				<p>Connect and manage your local and remote companion devices.</p>
			</div>
		</div>
	</header>

	<div class="content">
		<div class="icon-wrap">
			<DevicesIcon size={48} weight="duotone" />
		</div>
		<p>Sync your memories and activity across your desktop, mobile, and other BitBuddy devices.</p>
		<span class="badge">Coming Soon</span>
	</div>
</div>

<style>
	.placeholder-page {
		--page-accent: #2dd4bf;
		--page-soft: rgba(45, 212, 191, 0.12);
		--page-border: rgba(45, 212, 191, 0.25);

		width: 100%;
		max-width: 100%;
		padding: 0 1rem;
		margin: 0 auto;
		animation: fade-in 0.3s ease-out;
	}

	@keyframes fade-in {
		from { opacity: 0; transform: translateY(10px); }
		to { opacity: 1; transform: translateY(0); }
	}

	.page-header {
		margin-bottom: 2.5rem;
	}

	.fancy-title {
		display: flex;
		align-items: center;
		gap: 1.25rem;
	}

	.title-icon {
		width: 4rem;
		height: 4rem;
		display: grid;
		place-items: center;
		border-radius: 1.25rem;
		background: var(--surface-glass);
		border: 1px solid var(--page-border);
		color: var(--page-accent);
		box-shadow: 0 0 20px var(--page-soft);
	}

	.title-text h1 {
		font-size: 2.5rem;
		font-weight: 900;
		letter-spacing: -0.02em;
		margin-bottom: 0.25rem;
	}

	.title-text p {
		color: var(--text-soft);
		font-size: 1.05rem;
	}

	.content {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 1.5rem;
		padding: 5rem 2rem;
		border: 1px dashed var(--border-strong);
		border-radius: 2rem;
		background: var(--surface-card);
		text-align: center;
	}

	.icon-wrap {
		width: 6rem;
		height: 6rem;
		display: grid;
		place-items: center;
		border-radius: 2rem;
		background: var(--page-soft);
		color: var(--page-accent);
		margin-bottom: 1rem;
	}

	p {
		color: var(--text-soft);
		font-size: 1.1rem;
		max-width: 24rem;
	}

	.badge {
		padding: 0.4rem 1rem;
		border-radius: 999px;
		background: var(--bg-soft);
		border: 1px solid var(--border);
		color: var(--text-muted);
		font-size: 0.75rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.1em;
	}
</style>
