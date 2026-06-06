<script lang="ts">
	let { isTyping = false, isThinking = false, size = '2.8rem' } = $props<{
		isTyping?: boolean;
		isThinking?: boolean;
		size?: string;
	}>();

	let blinkState = $state(false);
	let eyeOffsetX = $state(0);
	let eyeOffsetY = $state(0);

	$effect(() => {
		const blinkInterval = window.setInterval(() => {
			blinkState = true;
			window.setTimeout(() => (blinkState = false), 150);
		}, 3800 + Math.random() * 2000);

		const lookInterval = window.setInterval(() => {
			eyeOffsetX = (Math.random() - 0.5) * 3;
			eyeOffsetY = (Math.random() - 0.5) * 2;
		}, 2500);

		return () => {
			window.clearInterval(blinkInterval);
			window.clearInterval(lookInterval);
		};
	});
</script>

<div class="face-wrap" class:typing={isTyping} class:thinking={isThinking} style={`--face-size: ${size}`} aria-label="BitBuddy">
	<svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" class="face-svg">
		<defs>
			<linearGradient id="bodyGold" x1="15%" y1="0%" x2="90%" y2="100%">
				<stop offset="0%" stop-color="#fff1bf" />
				<stop offset="46%" stop-color="#ffd98a" />
				<stop offset="100%" stop-color="#c78a32" />
			</linearGradient>
			<linearGradient id="bodyEdge" x1="0%" y1="0%" x2="100%" y2="100%">
				<stop offset="0%" stop-color="#fff7d7" />
				<stop offset="100%" stop-color="#7b531f" />
			</linearGradient>
			<linearGradient id="eyeFill" x1="0%" y1="0%" x2="0%" y2="100%">
				<stop offset="0%" stop-color="#d4fbff" />
				<stop offset="46%" stop-color="#5be8ff" />
				<stop offset="100%" stop-color="#1397e8" />
			</linearGradient>
			<radialGradient id="eyeGlow" cx="50%" cy="50%" r="50%">
				<stop offset="0%" stop-color="#ffffff" />
				<stop offset="58%" stop-color="#cdf8ff" />
				<stop offset="100%" stop-color="#52e3ff" />
			</radialGradient>
			<filter id="dropShadow" x="-20%" y="-20%" width="140%" height="140%">
				<feDropShadow dx="0" dy="4" stdDeviation="4" flood-color="#000" flood-opacity="0.3" />
			</filter>
		</defs>

		<rect x="11" y="10" width="98" height="100" rx="15" fill="url(#bodyEdge)" filter="url(#dropShadow)" />
		<rect x="14" y="13" width="92" height="94" rx="13" fill="url(#bodyGold)" />
		<rect x="20" y="28" width="80" height="70" rx="6" fill="#020617" opacity="0.98" />
		<rect x="23" y="31" width="74" height="64" rx="4" fill="rgba(0, 0, 0, 0.7)" stroke="rgba(255, 255, 255, 0.08)" />

		<rect x="27" y="19" width="6" height="6" rx="1" fill="#00a7ff" opacity="0.9" />
		<rect x="72" y="18" width="5" height="10" rx="1" fill="#1f1406" opacity="0.82" />
		<rect x="82" y="18" width="5" height="10" rx="1" fill="#1f1406" opacity="0.82" />
		<rect x="92" y="18" width="5" height="10" rx="1" fill="#1f1406" opacity="0.82" />

		<g transform={`translate(${eyeOffsetX}, ${eyeOffsetY})`}>
			<rect x="34" y="43" width="15" height="32" rx="7" fill="#0b6fc8" class="eye" class:blink={blinkState} />
			<rect x="37" y="46" width="9" height="25" rx="5" fill="url(#eyeFill)" class="eye" class:blink={blinkState} />
			<ellipse cx="41" cy="50" rx="4" ry="4" fill="url(#eyeGlow)" opacity="0.92" />

			<rect x="71" y="43" width="15" height="32" rx="7" fill="#0b6fc8" class="eye" class:blink={blinkState} />
			<rect x="74" y="46" width="9" height="25" rx="5" fill="url(#eyeFill)" class="eye" class:blink={blinkState} />
			<ellipse cx="78" cy="50" rx="4" ry="4" fill="url(#eyeGlow)" opacity="0.92" />
		</g>

		<path d="M 49 79 Q 60 88 71 79" stroke="#075fae" stroke-width="5" fill="none" stroke-linecap="round" opacity="0.95" />
		<rect x="31" y="101" width="17" height="8" rx="2" fill="#b98231" opacity="0.9" />
		<rect x="72" y="101" width="17" height="8" rx="2" fill="#b98231" opacity="0.9" />
	</svg>
	{#if isThinking}
		<div class="thought-bubbles" aria-hidden="true">
			<span></span>
			<span></span>
			<span></span>
		</div>
	{/if}
</div>

<style>
	.face-wrap {
		position: relative;
		width: var(--face-size, 2.8rem);
		height: var(--face-size, 2.8rem);
		display: grid;
		place-items: center;
		flex-shrink: 0;
		animation: float 4s ease-in-out infinite;
	}

	.face-svg {
		width: 100%;
		height: 100%;
		display: block;
	}

	.eye {
		transform-origin: center;
		transition: transform 0.15s ease;
	}

	.eye.blink {
		transform: scaleY(0.1);
	}

	.face-wrap.typing .face-svg {
		animation: face-bob 0.6s ease-in-out infinite alternate;
	}

	.face-wrap.thinking .face-svg {
		animation: thinking-tilt 1.8s ease-in-out infinite;
	}

	.face-wrap.thinking .eye {
		animation: thinking-squint 1.8s ease-in-out infinite;
	}

	.thought-bubbles {
		position: absolute;
		top: -0.2rem;
		right: -0.55rem;
		width: 1.35rem;
		height: 1.2rem;
		pointer-events: none;
	}

	.thought-bubbles span {
		position: absolute;
		display: block;
		border-radius: 999px;
		background: color-mix(in srgb, var(--mode-color, #79b8ff) 80%, white);
		box-shadow: 0 0 10px color-mix(in srgb, var(--mode-color, #79b8ff) 45%, transparent);
		opacity: 0;
		animation: thought-pop 1.55s ease-in-out infinite;
	}

	.thought-bubbles span:nth-child(1) {
		left: 0.05rem;
		bottom: 0.05rem;
		width: 0.26rem;
		height: 0.26rem;
	}

	.thought-bubbles span:nth-child(2) {
		left: 0.42rem;
		bottom: 0.36rem;
		width: 0.34rem;
		height: 0.34rem;
		animation-delay: 0.18s;
	}

	.thought-bubbles span:nth-child(3) {
		left: 0.86rem;
		bottom: 0.72rem;
		width: 0.44rem;
		height: 0.44rem;
		animation-delay: 0.36s;
	}

	@keyframes face-bob {
		from {
			transform: translateY(0);
		}
		to {
			transform: translateY(-2px);
		}
	}

	@keyframes thinking-tilt {
		0%, 100% {
			transform: rotate(-3deg) translateY(0);
		}
		50% {
			transform: rotate(4deg) translateY(-1px);
		}
	}

	@keyframes thinking-squint {
		0%, 100% {
			transform: scaleY(1);
		}
		50% {
			transform: scaleY(0.72);
		}
	}

	@keyframes thought-pop {
		0%, 18% {
			opacity: 0;
			transform: translateY(0.18rem) scale(0.75);
		}
		38%, 72% {
			opacity: 0.95;
			transform: translateY(0) scale(1);
		}
		100% {
			opacity: 0;
			transform: translateY(-0.1rem) scale(0.86);
		}
	}

	@keyframes float {
		0%, 100% {
			transform: translateY(0);
		}
		50% {
			transform: translateY(-3px);
		}
	}
</style>
