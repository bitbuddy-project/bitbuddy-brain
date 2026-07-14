<script lang="ts">
	import { goto } from '$app/navigation';
	import CodeIcon from 'phosphor-svelte/lib/CodeIcon';
	import { codingStatusLabel } from '$lib/stores/coding.svelte';
	let status = $derived(codingStatusLabel());
</script>

<button type="button" onclick={() => goto('/coding')} aria-label="Open Coding workspace" title={status ? `Coding workflow ${status}` : 'Open Coding workspace'}>
	<CodeIcon size={17} weight="bold" />
	<span>Coding</span>
	{#if status}<i class:waiting={status !== 'running'} aria-label={status}></i>{/if}
</button>

<style>
	button { position: relative; display: inline-flex; align-items: center; gap: .45rem; min-height: 2.55rem; padding: .5rem .85rem; border: 1px solid color-mix(in srgb, var(--bg-soft) 58%, var(--border)); border-radius: .68rem; background: color-mix(in srgb, var(--toggle-bg) 86%, transparent); color: var(--text-soft); font-size: .85rem; font-weight: 760; }
	button:hover { border-color: var(--accent); color: var(--accent); background: var(--toggle-hover-bg); }
	i { width: .48rem; height: .48rem; border-radius: 50%; background: var(--success); box-shadow: 0 0 0 .2rem color-mix(in srgb, var(--success) 16%, transparent); }
	i.waiting { background: var(--warning); box-shadow: 0 0 0 .2rem color-mix(in srgb, var(--warning) 16%, transparent); }
	@media (max-width: 520px) { button span { display: none; } button { padding-inline: .7rem; } }
</style>
