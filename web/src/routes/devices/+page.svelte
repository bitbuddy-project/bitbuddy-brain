<script lang="ts">
	import DevicesIcon from 'phosphor-svelte/lib/DevicesIcon';
	import MicrophoneIcon from 'phosphor-svelte/lib/MicrophoneIcon';
	import EyeIcon from 'phosphor-svelte/lib/EyeIcon';
	import SparkleIcon from 'phosphor-svelte/lib/SparkleIcon';

	const signals = [
		{ icon: MicrophoneIcon, label: 'Voice' },
		{ icon: EyeIcon, label: 'Face' },
		{ icon: DevicesIcon, label: 'Presence' },
		{ icon: SparkleIcon, label: 'Reactions' }
	];
</script>

<div class="devices-page">
	<section class="devices-panel" aria-label="BitBuddy devices">
		<header class="devices-header">
			<div class="title-mark" aria-hidden="true"><DevicesIcon size={30} weight="duotone" /></div>
			<div class="title-copy">
				<p class="eyebrow">Physical Presence</p>
				<h1>Devices</h1>
				<p>Not phone sync. Something more personal is being built here.</p>
			</div>
			<span class="status-pill">Coming soon</span>
		</header>

		<div class="devices-content">
			<section class="coming-card">
				<div class="device-orb" aria-hidden="true"></div>
				<div class="device-glyph"><img src="/bitbuddy-app.png" alt="" aria-hidden="true" /></div>
				<div class="coming-copy">
					<p class="eyebrow">Next Layer</p>
					<h2>BitBuddy is getting closer to the room.</h2>
					<p>
						This space will eventually connect the desktop mind to a local companion presence: voice, an expressive face, environmental awareness, and physical reactions that stay private and user-controlled.
					</p>
					<div class="signal-row" aria-label="Planned device signals">
						{#each signals as signal}
							<div class="signal-chip">
								<signal.icon size={18} weight="duotone" />
								<span>{signal.label}</span>
							</div>
						{/each}
					</div>
				</div>
			</section>

			<section class="teaser-card">
				<p class="eyebrow">Still under wraps</p>
				<h2>The details stay quiet for now.</h2>
				<p>
					The important part: this will not be cloud gadget sync. It is the beginning of BitBuddy becoming more present while staying local, modular, inspectable, and yours.
				</p>
			</section>
		</div>
	</section>
</div>

<style>
	.devices-page {
		--page-accent: var(--accent);
		--page-soft: color-mix(in srgb, var(--accent-soft) 72%, transparent);
		--page-border: color-mix(in srgb, var(--accent) 20%, var(--border));
		--page-glow: color-mix(in srgb, var(--accent) 10%, transparent);

		width: 100%;
		max-width: 100%;
		padding: 0 1rem;
		height: 100%;
		margin: 0 auto;
		display: flex;
		min-height: 0;
		animation: fade-in 0.35s cubic-bezier(0.16, 1, 0.3, 1);
	}

	@keyframes fade-in {
		from { opacity: 0; transform: translateY(12px); }
		to { opacity: 1; transform: translateY(0); }
	}

	.devices-panel {
		width: 100%;
		height: 100%;
		max-height: calc(100vh - 3rem);
		min-height: 0;
		display: flex;
		flex-direction: column;
		border: 1px solid var(--page-border);
		border-radius: 1.45rem;
		background:
			linear-gradient(135deg, var(--glass-overlay), transparent 22rem),
			radial-gradient(circle at top right, var(--page-glow), transparent 30rem),
			var(--panel-shell, var(--panel));
		box-shadow: var(--shadow-chat);
		overflow: hidden;
	}

	.devices-header {
		flex: 0 0 auto;
		padding: 1.35rem 1.5rem;
		display: flex;
		align-items: center;
		gap: 1rem;
		border-bottom: 1px solid var(--card-border, var(--border));
		background:
			linear-gradient(135deg, var(--page-soft), transparent 70%),
			var(--panel-header, var(--header-bg));
	}

	.title-mark,
	.signal-chip {
		display: grid;
		place-items: center;
		border: 1px solid var(--page-border);
		background: var(--chip-bg, var(--surface-glass));
		color: var(--page-accent);
	}

	.title-mark {
		width: 3.5rem;
		height: 3.5rem;
		border-radius: 1.1rem;
		box-shadow: 0 0 20px var(--page-soft);
		flex: 0 0 auto;
	}

	.title-copy {
		min-width: 0;
		flex: 1;
	}

	.eyebrow {
		color: var(--page-accent);
		font-size: 0.72rem;
		font-weight: 850;
		letter-spacing: 0.09em;
		text-transform: uppercase;
	}

	h1,
	h2 {
		letter-spacing: -0.04em;
		line-height: 1.05;
	}

	h1 {
		font-size: 1.65rem;
		font-weight: 900;
	}

	h2 {
		font-size: clamp(2.2rem, 6vw, 4.8rem);
		font-weight: 950;
	}

	.title-copy p:last-child,
	.coming-copy p,
	.teaser-card p {
		color: var(--text-soft);
	}

	.status-pill {
		padding: 0.3rem 0.7rem;
		border: 1px solid var(--chip-border, var(--border));
		border-radius: 999px;
		background: var(--chip-bg, var(--surface-glass));
		color: var(--page-accent);
		font-size: 0.72rem;
		font-weight: 850;
		letter-spacing: 0.07em;
		text-transform: uppercase;
	}

	.devices-content {
		min-height: 0;
		flex: 1 1 auto;
		padding: 1.25rem;
		display: grid;
		grid-template-rows: minmax(0, 1fr) auto;
		gap: 1rem;
		overflow-y: auto;
		scrollbar-color: var(--scrollbar-thumb) transparent;
	}

	.coming-card,
	.teaser-card {
		position: relative;
		overflow: hidden;
		border: 1px solid var(--card-border, var(--border));
		border-radius: 1.35rem;
		background: var(--card-bg, var(--surface-card));
	}

	.coming-card {
		min-height: 28rem;
		padding: clamp(1.4rem, 4vw, 3rem);
		display: grid;
		grid-template-columns: auto minmax(0, 1fr);
		gap: clamp(1rem, 3vw, 2rem);
		align-items: center;
	}

	.device-orb {
		position: absolute;
		inset: -8rem -6rem auto auto;
		width: 24rem;
		height: 24rem;
		border-radius: 999px;
		background: radial-gradient(circle, color-mix(in srgb, var(--page-accent) 18%, transparent), transparent 68%);
		filter: blur(18px);
		pointer-events: none;
	}

	.device-glyph {
		position: relative;
		width: clamp(5.5rem, 12vw, 8rem);
		height: clamp(5.5rem, 12vw, 8rem);
	}

	.device-glyph img {
		width: 100%;
		height: 100%;
		object-fit: contain;
	}

	.coming-copy {
		position: relative;
		min-width: 0;
		display: grid;
		gap: 0.8rem;
	}

	.coming-copy p:last-of-type {
		max-width: 58rem;
		font-size: 1.04rem;
		line-height: 1.65;
	}

	.signal-row {
		display: flex;
		flex-wrap: wrap;
		gap: 0.55rem;
		margin-top: 0.4rem;
	}

	.signal-chip {
		grid-auto-flow: column;
		gap: 0.4rem;
		padding: 0.38rem 0.7rem;
		border-radius: 999px;
		font-size: 0.75rem;
		font-weight: 850;
		letter-spacing: 0.05em;
		text-transform: uppercase;
	}

	.teaser-card {
		padding: 1.1rem 1.2rem;
		display: grid;
		gap: 0.45rem;
		background:
			linear-gradient(135deg, color-mix(in srgb, var(--page-soft) 64%, transparent), transparent),
			var(--event-bg, var(--surface-card));
	}

	.teaser-card h2 {
		font-size: clamp(1.2rem, 2.4vw, 1.7rem);
	}

	.teaser-card p {
		max-width: 58rem;
		line-height: 1.6;
	}

	@media (max-width: 980px) {
		.devices-page,
		.devices-panel {
			height: auto;
			max-height: none;
		}

		.devices-content {
			grid-template-rows: auto auto;
		}
	}

	@media (max-width: 640px) {
		.devices-page {
			padding: 0;
		}

		.devices-header {
			align-items: flex-start;
			flex-wrap: wrap;
		}

		.coming-card {
			grid-template-columns: 1fr;
		}

		.status-pill {
			width: 100%;
			text-align: center;
		}
	}
</style>
