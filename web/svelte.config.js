import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	compilerOptions: {
		// Force runes mode for the project, except for libraries. Can be removed in svelte 6.
		runes: ({ filename }) => (filename.split(/[/\\]/).includes('node_modules') ? undefined : true)
	},
	kit: {
		// Build a self-contained SPA that the BitBuddy backend serves on its own
		// port. `fallback` lets client-side routes (e.g. /projects) resolve to the
		// SPA entry point. See src/routes/+layout.ts for the ssr/prerender opt-out.
		adapter: adapter({
			pages: 'build',
			assets: 'build',
			fallback: 'index.html',
			strict: false
		})
	}
};

export default config;
