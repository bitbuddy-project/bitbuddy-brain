/*
 * Display-layer masking for sensitive info (verification codes, card numbers,
 * SSNs, IBANs, API keys). This only hides values in the UI — the underlying
 * text is unchanged, so the assistant still sees the real content and can help.
 * Masked spans reveal on click.
 */

export type MaskKind = 'otp' | 'card' | 'ssn' | 'iban' | 'key';

export interface MaskRange {
	start: number;
	end: number;
	kind: MaskKind;
}

export type MaskSegment =
	| { masked: false; text: string }
	| { masked: true; text: string; display: string; kind: MaskKind };

const SSN_RE = /\b\d{3}-\d{2}-\d{4}\b/g;
const IBAN_RE = /\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}[ ]?[A-Z0-9]{1,3}\b/g;
const CARD_RE = /\b(?:\d[ -]?){13,19}\b/g;
const KEY_PREFIX_RE = /\b(?:sk|pk|rk|ghp|gho|ghs|ghu|xox[baprs])[-_][A-Za-z0-9_-]{16,}\b/g;
// Context-anchored one-time codes: a keyword followed shortly by a 4–8 digit run.
const OTP_RE =
	/\b(?:code|otp|pin|passcode|password|verification|verify|confirm(?:ation)?|one[- ]?time|2fa|mfa|token)\b[^0-9\n]{0,24}?(\d{4,8})\b/gi;

function addRange(ranges: MaskRange[], start: number, end: number, kind: MaskKind): void {
	ranges.push({ start, end, kind });
}

function looksLikeToken(value: string): boolean {
	// A long opaque string with mixed letters and digits — likely a key/token,
	// not an ordinary word or number.
	if (value.length < 24) return false;
	if (!/[A-Za-z]/.test(value) || !/\d/.test(value)) return false;
	return /^[A-Za-z0-9_-]+$/.test(value);
}

function digitsOnly(value: string): string {
	return value.replace(/\D/g, '');
}

/** Find non-overlapping ranges of sensitive text, sorted by position. */
export function findSensitiveRanges(text: string): MaskRange[] {
	const ranges: MaskRange[] = [];
	let match: RegExpExecArray | null;

	for (const re of [SSN_RE, IBAN_RE, KEY_PREFIX_RE]) {
		re.lastIndex = 0;
		while ((match = re.exec(text)) !== null) {
			const kind: MaskKind = re === SSN_RE ? 'ssn' : re === IBAN_RE ? 'iban' : 'key';
			addRange(ranges, match.index, match.index + match[0].length, kind);
		}
	}

	CARD_RE.lastIndex = 0;
	while ((match = CARD_RE.exec(text)) !== null) {
		const count = digitsOnly(match[0]).length;
		if (count >= 13 && count <= 19) {
			addRange(ranges, match.index, match.index + match[0].length, 'card');
		}
	}

	// Generic long tokens (whitespace-delimited).
	const TOKEN_RE = /\S{24,}/g;
	while ((match = TOKEN_RE.exec(text)) !== null) {
		if (looksLikeToken(match[0])) {
			addRange(ranges, match.index, match.index + match[0].length, 'key');
		}
	}

	OTP_RE.lastIndex = 0;
	while ((match = OTP_RE.exec(text)) !== null) {
		const digits = match[1];
		const start = match.index + match[0].lastIndexOf(digits);
		addRange(ranges, start, start + digits.length, 'otp');
	}

	// Resolve overlaps: sort by start, then by longest, dropping any that overlap a kept range.
	ranges.sort((a, b) => a.start - b.start || b.end - a.end);
	const result: MaskRange[] = [];
	let lastEnd = -1;
	for (const range of ranges) {
		if (range.start >= lastEnd) {
			result.push(range);
			lastEnd = range.end;
		}
	}
	return result;
}

function displayFor(text: string, kind: MaskKind): string {
	if (kind === 'card') {
		const last4 = digitsOnly(text).slice(-4);
		return `•••• ${last4}`;
	}
	return '••••••';
}

/** Split text into masked / unmasked segments for component rendering. */
export function maskSegments(text: string): MaskSegment[] {
	const ranges = findSensitiveRanges(text);
	if (ranges.length === 0) return [{ masked: false, text }];

	const segments: MaskSegment[] = [];
	let cursor = 0;
	for (const range of ranges) {
		if (range.start > cursor) {
			segments.push({ masked: false, text: text.slice(cursor, range.start) });
		}
		const raw = text.slice(range.start, range.end);
		segments.push({ masked: true, text: raw, display: displayFor(raw, range.kind), kind: range.kind });
		cursor = range.end;
	}
	if (cursor < text.length) {
		segments.push({ masked: false, text: text.slice(cursor) });
	}
	return segments;
}

export function hasSensitive(text: string): boolean {
	return findSensitiveRanges(text).length > 0;
}

function escapeAttr(value: string): string {
	return value
		.replace(/&/g, '&amp;')
		.replace(/"/g, '&quot;')
		.replace(/</g, '&lt;')
		.replace(/>/g, '&gt;');
}

function chipHtml(raw: string, kind: MaskKind): string {
	const display = displayFor(raw, kind);
	return `<span class="masked-chip" role="button" tabindex="0" data-reveal="${escapeAttr(raw)}" data-masked="1" title="Click to reveal hidden value">${escapeAttr(display)}</span>`;
}

/*
 * Mask sensitive runs inside an already-rendered HTML string, touching only the
 * text between tags so markup and attributes are left intact. Pair with the
 * delegated click handler in `revealMaskedChips` so chips toggle on click.
 */
export function maskHtml(html: string): string {
	return html
		.split(/(<[^>]+>)/)
		.map((part) => {
			if (!part || part.startsWith('<')) return part;
			const ranges = findSensitiveRanges(part);
			if (ranges.length === 0) return part;
			let out = '';
			let cursor = 0;
			for (const range of ranges) {
				out += part.slice(cursor, range.start);
				out += chipHtml(part.slice(range.start, range.end), range.kind);
				cursor = range.end;
			}
			out += part.slice(cursor);
			return out;
		})
		.join('');
}

/*
 * Svelte action: delegate clicks/Enter on `.masked-chip` elements within the
 * node to toggle between the masked display and the revealed value. Works for
 * chips injected via {@html} (chat) since it uses event delegation.
 */
export function revealMaskedChips(node: HTMLElement) {
	function toggle(chip: HTMLElement) {
		const masked = chip.dataset.masked === '1';
		if (masked) {
			chip.dataset.display = chip.textContent ?? '';
			chip.textContent = chip.dataset.reveal ?? '';
			chip.dataset.masked = '0';
			chip.classList.add('revealed');
		} else {
			chip.textContent = chip.dataset.display ?? '••••••';
			chip.dataset.masked = '1';
			chip.classList.remove('revealed');
		}
	}

	function onClick(event: MouseEvent) {
		const chip = (event.target as HTMLElement | null)?.closest('.masked-chip') as HTMLElement | null;
		if (chip && node.contains(chip)) {
			event.preventDefault();
			event.stopPropagation();
			toggle(chip);
		}
	}

	function onKey(event: KeyboardEvent) {
		if (event.key !== 'Enter' && event.key !== ' ') return;
		const chip = (event.target as HTMLElement | null)?.closest('.masked-chip') as HTMLElement | null;
		if (chip && node.contains(chip)) {
			event.preventDefault();
			toggle(chip);
		}
	}

	node.addEventListener('click', onClick);
	node.addEventListener('keydown', onKey);
	return {
		destroy() {
			node.removeEventListener('click', onClick);
			node.removeEventListener('keydown', onKey);
		}
	};
}
