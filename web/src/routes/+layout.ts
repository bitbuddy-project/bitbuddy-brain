// BitBuddy's web UI is a pure client-side SPA served by the backend (see
// svelte.config.js). It reads window/localStorage at load (API base + token),
// so there is no server-side rendering and nothing is prerendered.
export const ssr = false;
export const prerender = false;
