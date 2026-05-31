<script lang="ts">
	import { parseMarkdownSegments, renderMarkdown } from '$lib/markdown';
	import CodeBlock from './CodeBlock.svelte';

	let { content, compact = false } = $props<{
		content: string;
		compact?: boolean;
	}>();

	let segments = $derived(parseMarkdownSegments(content));

	function injectCaret(html: string): string {
		return html.replace('%%BITBUDDY_CARET%%', '<span class="typing-caret" aria-hidden="true">|</span>');
	}
</script>

<div class:compact class="markdown-message">
	{#each segments as segment}
		{#if segment.kind === 'code'}
			<CodeBlock code={segment.code} language={segment.language} />
		{:else if segment.content.trim() || segment.content.includes('%%BITBUDDY_CARET%%')}
			<div class="markdown-fragment">{@html injectCaret(renderMarkdown(segment.content))}</div>
		{/if}
	{/each}
</div>

<style>
	.markdown-message {
		min-width: 0;
	}

	.markdown-fragment :global(p) {
		margin: 0 0 0.85rem;
	}

	.markdown-fragment :global(p:last-child) {
		margin-bottom: 0;
	}

	.markdown-fragment :global(p),
	.markdown-fragment :global(li) {
		color: var(--text);
		font-size: 0.96rem;
		line-height: 1.65;
	}

	.compact .markdown-fragment :global(p),
	.compact .markdown-fragment :global(li) {
		color: var(--text-muted);
		font-size: 0.86rem;
		line-height: 1.45;
	}

	.markdown-fragment :global(h1),
	.markdown-fragment :global(h2),
	.markdown-fragment :global(h3),
	.markdown-fragment :global(h4) {
		margin: 1rem 0 0.5rem;
		color: var(--text);
		font-family: var(--font-body);
		line-height: 1.2;
	}

	.markdown-fragment :global(h1:first-child),
	.markdown-fragment :global(h2:first-child),
	.markdown-fragment :global(h3:first-child),
	.markdown-fragment :global(h4:first-child) {
		margin-top: 0;
	}

	.markdown-fragment :global(ul),
	.markdown-fragment :global(ol) {
		margin: 0.55rem 0 0.75rem 1.2rem;
		list-style: revert;
	}

	.markdown-fragment :global(code) {
		padding: 0.12rem 0.32rem;
		border-radius: 0.35rem;
		background: var(--surface-code);
		color: var(--accent-strong);
		font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', monospace;
		font-size: 0.88em;
	}

	.markdown-fragment :global(a) {
		color: var(--mode-color);
		text-decoration: underline;
	}

	.markdown-fragment :global(blockquote) {
		margin: 0.75rem 0;
		padding-left: 0.9rem;
		border-left: 3px solid var(--mode-border, var(--border));
		color: var(--text-muted);
	}

	.markdown-fragment :global(table) {
		width: 100%;
		margin: 0.75rem 0;
		border-collapse: collapse;
		font-size: 0.9rem;
	}

	.markdown-fragment :global(th),
	.markdown-fragment :global(td) {
		padding: 0.45rem 0.55rem;
		border: 1px solid var(--border);
		text-align: left;
	}

	.markdown-fragment :global(th) {
		background: var(--surface-glass);
		color: var(--text);
	}
</style>
