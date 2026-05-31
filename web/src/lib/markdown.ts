import { marked } from 'marked';

export type MarkdownSegment =
	| { kind: 'markdown'; content: string }
	| { kind: 'code'; code: string; language: string };

marked.use({
	gfm: true,
	breaks: false
});

export function parseMarkdownSegments(markdown: string): MarkdownSegment[] {
	const segments: MarkdownSegment[] = [];
	const lines = markdown.split('\n');
	let index = 0;
	let textBuffer: string[] = [];

	function flushText() {
		if (textBuffer.length === 0) return;
		segments.push({ kind: 'markdown', content: textBuffer.join('\n') });
		textBuffer = [];
	}

	while (index < lines.length) {
		const match = lines[index].match(/^```\s*([^`]*)\s*$/);
		if (!match) {
			textBuffer.push(lines[index]);
			index += 1;
			continue;
		}

		flushText();
		const language = normalizeLanguage(match[1]);
		const code: string[] = [];
		index += 1;
		while (index < lines.length && !lines[index].startsWith('```')) {
			code.push(lines[index]);
			index += 1;
		}
		if (index < lines.length) index += 1;
		segments.push({ kind: 'code', code: code.join('\n'), language });
	}

	flushText();
	return segments.length ? segments : [{ kind: 'markdown', content: markdown }];
}

export function renderMarkdown(markdown: string): string {
	return String(marked.parse(escapeRawHtml(markdown), { async: false }));
}

export function renderPlainText(text: string): string {
	return escapeHtml(text).replace(/\n/g, '<br />');
}

export function normalizeLanguage(language: string): string {
	return language.trim().split(/\s+/)[0].toLowerCase() || 'text';
}

function escapeRawHtml(value: string): string {
	return value.replace(/[<>]/g, (character) => (character === '<' ? '&lt;' : '&gt;'));
}

export function escapeHtml(value: string): string {
	return value
		.replace(/&/g, '&amp;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;')
		.replace(/"/g, '&quot;')
		.replace(/'/g, '&#039;');
}

/*
 * Kept only as reference for older persisted HTML expectations; the chat UI now
 * splits fenced blocks into Svelte components so copy buttons can use raw code.
 */
export function renderBasicMarkdown(markdown: string): string {
    const escaped = escapeHtml(markdown);
    const lines = escaped.split('\n');
    const html: string[] = [];
    let index = 0;

	while (index < lines.length) {
		const line = lines[index];
		if (!line.trim()) {
			index += 1;
			continue;
		}

		if (line.startsWith('```')) {
			const language = line.replace(/^```/, '').trim();
			const code: string[] = [];
			index += 1;
			while (index < lines.length && !lines[index].startsWith('```')) {
				code.push(lines[index]);
				index += 1;
			}
			if (index < lines.length) index += 1;
			html.push(`<pre><code class="language-${language}">${code.join('\n')}</code></pre>`);
			continue;
		}

		if (/^#{1,4}\s/.test(line)) {
			const level = line.match(/^#+/)?.[0].length ?? 2;
			html.push(`<h${level}>${renderInline(line.replace(/^#{1,4}\s+/, ''))}</h${level}>`);
			index += 1;
			continue;
		}

		if (/^[-*]\s/.test(line)) {
			const items: string[] = [];
			while (index < lines.length && /^[-*]\s/.test(lines[index])) {
				items.push(`<li>${renderInline(lines[index].replace(/^[-*]\s+/, ''))}</li>`);
				index += 1;
			}
			html.push(`<ul>${items.join('')}</ul>`);
			continue;
		}

		if (/^\d+\.\s/.test(line)) {
			const items: string[] = [];
			while (index < lines.length && /^\d+\.\s/.test(lines[index])) {
				items.push(`<li>${renderInline(lines[index].replace(/^\d+\.\s+/, ''))}</li>`);
				index += 1;
			}
			html.push(`<ol>${items.join('')}</ol>`);
			continue;
		}

		const paragraph: string[] = [];
		while (index < lines.length && lines[index].trim() && !startsBlock(lines[index])) {
			paragraph.push(lines[index]);
			index += 1;
		}
		html.push(`<p>${renderInline(paragraph.join('\n')).replace(/\n/g, '<br />')}</p>`);
	}

    return html.join('');
}

function startsBlock(line: string): boolean {
	return line.startsWith('```') || /^#{1,4}\s/.test(line) || /^[-*]\s/.test(line) || /^\d+\.\s/.test(line);
}

function renderInline(text: string): string {
	return text
		.replace(/`([^`]+)`/g, '<code>$1</code>')
		.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
		.replace(/\*([^*]+)\*/g, '<em>$1</em>')
		.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
}
