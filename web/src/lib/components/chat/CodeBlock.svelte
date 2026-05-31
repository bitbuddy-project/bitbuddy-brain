<script lang="ts">
	import hljs from 'highlight.js/lib/core';
	import bash from 'highlight.js/lib/languages/bash';
	import css from 'highlight.js/lib/languages/css';
	import javascript from 'highlight.js/lib/languages/javascript';
	import json from 'highlight.js/lib/languages/json';
	import markdown from 'highlight.js/lib/languages/markdown';
	import python from 'highlight.js/lib/languages/python';
	import shell from 'highlight.js/lib/languages/shell';
	import sql from 'highlight.js/lib/languages/sql';
	import typescript from 'highlight.js/lib/languages/typescript';
	import xml from 'highlight.js/lib/languages/xml';
	import yaml from 'highlight.js/lib/languages/yaml';
	import { escapeHtml, normalizeLanguage } from '$lib/markdown';

	hljs.registerLanguage('bash', bash);
	hljs.registerLanguage('css', css);
	hljs.registerLanguage('html', xml);
	hljs.registerLanguage('javascript', javascript);
	hljs.registerLanguage('js', javascript);
	hljs.registerLanguage('json', json);
	hljs.registerLanguage('markdown', markdown);
	hljs.registerLanguage('md', markdown);
	hljs.registerLanguage('python', python);
	hljs.registerLanguage('py', python);
	hljs.registerLanguage('shell', shell);
	hljs.registerLanguage('sh', bash);
	hljs.registerLanguage('sql', sql);
	hljs.registerLanguage('svelte', xml);
	hljs.registerLanguage('typescript', typescript);
	hljs.registerLanguage('ts', typescript);
	hljs.registerLanguage('tsx', typescript);
	hljs.registerLanguage('xml', xml);
	hljs.registerLanguage('yaml', yaml);
	hljs.registerLanguage('yml', yaml);

	let { code, language = 'text' } = $props<{
		code: string;
		language?: string;
	}>();

	let copied = $state(false);
	let resetTimer: ReturnType<typeof setTimeout> | undefined;
	let displayLanguage = $derived(normalizeLanguage(language));
	let rawHighlighted = $derived(highlightCode(code.replace('%%BITBUDDY_CARET%%', ''), displayLanguage));
	let highlighted = $derived(code.includes('%%BITBUDDY_CARET%%')
		? rawHighlighted + '<span class="typing-caret" aria-hidden="true">|</span>'
		: rawHighlighted);

	async function copyCode() {
		if (typeof navigator === 'undefined' || !navigator.clipboard) return;
		await navigator.clipboard.writeText(code);
		copied = true;
		if (resetTimer) clearTimeout(resetTimer);
		resetTimer = setTimeout(() => {
			copied = false;
		}, 1400);
	}

	function highlightCode(value: string, languageName: string): string {
		if (languageName && languageName !== 'text' && hljs.getLanguage(languageName)) {
			return hljs.highlight(value, { language: languageName, ignoreIllegals: true }).value;
		}
		return escapeHtml(value);
	}
</script>

<div class="code-block">
	<div class="code-header">
		<span>{displayLanguage === 'text' ? 'text' : displayLanguage}</span>
		<button type="button" onclick={copyCode}>{copied ? 'Copied' : 'Copy'}</button>
	</div>
	<pre><code class={`language-${displayLanguage}`}>{@html highlighted}</code></pre>
</div>

<style>
	.code-block {
		margin: 0.85rem 0;
		overflow: hidden;
		border: 1px solid rgba(255, 255, 255, 0.12);
		border-radius: 0.85rem;
		background: rgba(3, 7, 18, 0.72);
		box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
	}

	.code-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.8rem;
		padding: 0.48rem 0.65rem 0.48rem 0.8rem;
		border-bottom: 1px solid rgba(255, 255, 255, 0.1);
		background: rgba(255, 255, 255, 0.045);
		color: #a9bad2;
		font-size: 0.72rem;
		font-weight: 850;
		letter-spacing: 0.06em;
		text-transform: uppercase;
	}

	button {
		border: 1px solid rgba(255, 255, 255, 0.14);
		border-radius: 999px;
		padding: 0.22rem 0.55rem;
		background: rgba(255, 255, 255, 0.06);
		color: #eef5ff;
		font: inherit;
		font-size: 0.68rem;
		letter-spacing: 0.04em;
		cursor: pointer;
	}

	button:hover {
		border-color: var(--mode-border, rgba(255, 255, 255, 0.24));
		background: rgba(255, 255, 255, 0.1);
	}

	pre {
		margin: 0;
		padding: 0.9rem;
		overflow: auto;
	}

	code {
		display: block;
		min-width: max-content;
		background: transparent;
		color: #d8dee9;
		font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', monospace;
		font-size: 0.86rem;
		line-height: 1.6;
		tab-size: 2;
	}

	:global(.hljs-keyword),
	:global(.hljs-selector-tag),
	:global(.hljs-title.function_) {
		color: #c792ea;
	}

	:global(.hljs-string),
	:global(.hljs-attr),
	:global(.hljs-symbol) {
		color: #c3e88d;
	}

	:global(.hljs-number),
	:global(.hljs-literal),
	:global(.hljs-built_in) {
		color: #f78c6c;
	}

	:global(.hljs-comment),
	:global(.hljs-quote) {
		color: #7f8c98;
		font-style: italic;
	}

	:global(.hljs-name),
	:global(.hljs-tag),
	:global(.hljs-property) {
		color: #82aaff;
	}
</style>
