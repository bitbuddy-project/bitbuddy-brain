/**
 * Move a node to <body> so overlays/menus escape parent stacking + overflow
 * contexts. Ported from the sparekey pattern. Use as `use:portal`.
 */
export function portal(node: HTMLElement) {
	document.body.appendChild(node);
	return {
		destroy() {
			node.remove();
		}
	};
}
