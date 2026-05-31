<script lang="ts">
	import type { ActivityItem } from '$lib/api/bitbuddy';
	import { formatTimestamp } from '$lib/stores/time.svelte';

	let { activity, error } = $props<{
		activity: ActivityItem[];
		error: string;
	}>();

	function asStrings(value: unknown): string[] {
		return Array.isArray(value) ? value.map(String) : [];
	}

	const pathKeys = ['roots', 'paths', 'changed_paths', 'deleted_paths', 'skipped_paths'];

	function metadataStrings(metadata: Record<string, unknown>, key: string): string[] {
		return asStrings(metadata[key]);
	}

	function scalarEntries(metadata: Record<string, unknown>) {
		return Object.entries(metadata).filter(([key, value]) => !pathKeys.includes(key) && !Array.isArray(value));
	}

	function labelFor(key: string): string {
		return key.replaceAll('_', ' ');
	}

	function displayValue(key: string, value: unknown): string {
		if (value === null || value === undefined || value === '') return 'None';
		if (key === 'error' && String(value).trim() === '') return 'None';
		if (typeof value === 'object') {
			const entries = Object.entries(value as Record<string, unknown>).filter(([, nested]) => nested !== null && nested !== undefined && nested !== '');
			if (entries.length === 0) return 'None';
			return entries.map(([nestedKey, nestedValue]) => {
				const strVal = typeof nestedValue === 'object' ? JSON.stringify(nestedValue) : String(nestedValue);
				return `${labelFor(nestedKey)}: ${strVal}`;
			}).join(', ');
		}
		return String(value);
	}
</script>

<div class="activity-list">
	{#if error}
		<div class="activity-item warning">
			<span>Offline</span>
			<p>{error}</p>
		</div>
	{:else if activity.length === 0}
		<div class="empty-state">
			<p>No permission logs yet.</p>
		</div>
	{:else}
		{#each activity as item}
			<div class="activity-item">
				<span>{formatTimestamp(item.created_at)}</span>
				<div>
					<strong>{item.kind}</strong>
					<p>{item.message}</p>

					{#if scalarEntries(item.metadata).length}
						<dl class="metadata-grid">
							{#each scalarEntries(item.metadata) as [key, value]}
								<div>
									<dt>{labelFor(key)}</dt>
									<dd>{displayValue(key, value)}</dd>
								</div>
							{/each}
						</dl>
					{/if}

					{#if metadataStrings(item.metadata, 'roots').length}
						<div class="metadata-block path-list">
							<span>Roots scanned</span>
							{#each metadataStrings(item.metadata, 'roots') as root}
								<code>{root}</code>
							{/each}
						</div>
					{/if}

					{#if metadataStrings(item.metadata, 'paths').length}
						<div class="metadata-block path-list">
							<span>Project paths</span>
							{#each metadataStrings(item.metadata, 'paths') as path}
								<code>{path}</code>
							{/each}
						</div>
					{/if}

					{#if metadataStrings(item.metadata, 'changed_paths').length}
						<div class="metadata-block path-list changed">
							<span>Changed files</span>
							{#each metadataStrings(item.metadata, 'changed_paths') as path}
								<code>{path}</code>
							{/each}
						</div>
					{/if}

					{#if metadataStrings(item.metadata, 'deleted_paths').length}
						<div class="metadata-block path-list deleted">
							<span>Deleted files</span>
							{#each metadataStrings(item.metadata, 'deleted_paths') as path}
								<code>{path}</code>
							{/each}
						</div>
					{/if}

					{#if metadataStrings(item.metadata, 'skipped_paths').length}
						<div class="metadata-block path-list">
							<span>Skipped files</span>
							{#each metadataStrings(item.metadata, 'skipped_paths') as path}
								<code>{path}</code>
							{/each}
						</div>
					{/if}
				</div>
			</div>
		{/each}
	{/if}
</div>

<style>
	.activity-list {
		padding-top: 1rem;
		min-height: 0;
		overflow: visible;
		padding-right: 0.35rem;
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(min(34rem, 100%), 1fr));
		align-content: start;
		gap: 0.75rem;
		scrollbar-color: rgba(255, 255, 255, 0.18) transparent;
	}

	.activity-item {
		padding: 1rem;
		display: grid;
		grid-template-columns: minmax(9rem, auto) minmax(0, 1fr);
		gap: 1rem;
		max-height: 24rem;
		overflow-y: auto;
		border: 1px solid var(--border);
		border-radius: 1rem;
		background: var(--surface-glass);
	}

	.activity-item > div {
		min-width: 0;
		overflow-wrap: break-word;
	}

	.activity-item.warning {
		border-color: rgba(255, 209, 102, 0.35);
	}

	.activity-item span {
		color: var(--text-soft);
		font-size: 0.86rem;
	}

	.activity-item strong {
		display: block;
		margin-bottom: 0.25rem;
		color: var(--accent-strong);
	}

	.activity-item p {
		color: var(--text-muted);
	}

	.empty-state {
		padding: 3rem 1rem;
		text-align: center;
	}

	.empty-state p {
		color: var(--text-soft);
		font-size: 0.9rem;
	}

	.metadata-block {
		margin-top: 0.75rem;
		display: flex;
		flex-wrap: wrap;
		gap: 0.35rem;
	}

	.metadata-grid {
		margin-top: 0.85rem;
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
		gap: 0.5rem;
	}

	.metadata-grid div {
		padding: 0.55rem 0.65rem;
		border: 1px solid var(--border);
		border-radius: 0.75rem;
		background: var(--surface-inset);
		overflow-wrap: break-word;
	}

	dt {
		color: var(--text-soft);
		font-size: 0.68rem;
		font-weight: 800;
		letter-spacing: 0.05em;
		text-transform: uppercase;
	}

	dd {
		margin-top: 0.15rem;
		color: var(--text-muted);
		font-size: 0.86rem;
		font-weight: 700;
	}

	.metadata-block span {
		width: 100%;
		color: var(--text-soft);
		font-size: 0.75rem;
		font-weight: 800;
		letter-spacing: 0.04em;
		text-transform: uppercase;
	}

	.metadata-block code {
		padding: 0.2rem 0.45rem;
		border: 1px solid var(--border);
		border-radius: 0.55rem;
		background: var(--surface-code);
		color: var(--text-muted);
		font-size: 0.78rem;
		white-space: normal;
		word-break: break-word;
	}

	.path-list code {
		width: auto;
		flex: 1 1 18rem;
	}

	.metadata-block.changed code {
		border-color: rgba(89, 214, 141, 0.22);
		color: var(--success);
	}

	.metadata-block.deleted code {
		border-color: rgba(255, 107, 122, 0.25);
		color: var(--danger);
	}

	@media (max-width: 760px) {
		.activity-item {
			grid-template-columns: 1fr;
		}
	}
</style>
