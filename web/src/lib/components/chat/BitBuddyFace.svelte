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
			<radialGradient id="headGrad" cx="35%" cy="30%" r="65%">
				<stop offset="0%" stop-color="#8ec9ff" />
				<stop offset="40%" stop-color="#4a9eff" />
				<stop offset="100%" stop-color="#1a5fcf" />
			</radialGradient>
			<radialGradient id="headGradLight" cx="30%" cy="25%" r="55%">
				<stop offset="0%" stop-color="#a8d8ff" />
				<stop offset="50%" stop-color="#5aadff" />
				<stop offset="100%" stop-color="#2a7ae0" />
			</radialGradient>
			<linearGradient id="metalGrad" x1="0%" y1="0%" x2="100%" y2="100%">
				<stop offset="0%" stop-color="rgba(255,255,255,0.35)" />
				<stop offset="50%" stop-color="rgba(255,255,255,0.08)" />
				<stop offset="100%" stop-color="rgba(255,255,255,0.02)" />
			</linearGradient>
			<radialGradient id="eyeGlow" cx="50%" cy="50%" r="50%">
				<stop offset="0%" stop-color="#ffffff" />
				<stop offset="70%" stop-color="#e8f4ff" />
				<stop offset="100%" stop-color="#b8d8ff" />
			</radialGradient>
			<filter id="dropShadow" x="-20%" y="-20%" width="140%" height="140%">
				<feDropShadow dx="0" dy="3" stdDeviation="4" flood-color="#000" flood-opacity="0.25" />
			</filter>
			<filter id="innerShadow">
				<feOffset dx="0" dy="2" />
				<feGaussianBlur stdDeviation="2" result="offset-blur" />
				<feComposite operator="out" in="SourceGraphic" in2="offset-blur" result="inverse" />
				<feFlood flood-color="black" flood-opacity="0.2" result="color" />
				<feComposite operator="in" in="color" in2="inverse" result="shadow" />
				<feComposite operator="over" in="shadow" in2="SourceGraphic" />
			</filter>
		</defs>

		<!-- Ear/communication nodes -->
		<circle cx="18" cy="60" r="8" fill="#2563eb" opacity="0.8">
			<animate attributeName="opacity" values="0.8;0.4;0.8" dur="2s" repeatCount="indefinite" />
		</circle>
		<circle cx="102" cy="60" r="8" fill="#2563eb" opacity="0.8">
			<animate attributeName="opacity" values="0.8;0.4;0.8" dur="2s" begin="1s" repeatCount="indefinite" />
		</circle>
		<line x1="26" y1="60" x2="32" y2="60" stroke="#2563eb" stroke-width="2" opacity="0.5" />
		<line x1="88" y1="60" x2="94" y2="60" stroke="#2563eb" stroke-width="2" opacity="0.5" />

		<!-- Main head sphere -->
		<circle cx="60" cy="60" r="44" fill="url(#headGrad)" filter="url(#dropShadow)" />
		<circle cx="60" cy="60" r="44" fill="url(#metalGrad)" opacity="0.6" />

		<!-- 3D highlight sheen -->
		<ellipse cx="46" cy="38" rx="20" ry="14" fill="rgba(255,255,255,0.18)" transform="rotate(-25, 46, 38)" />
		<ellipse cx="72" cy="82" rx="16" ry="10" fill="rgba(0,0,0,0.1)" transform="rotate(-25, 72, 82)" />

		<!-- Face plate / visor area -->
		<rect x="28" y="40" width="64" height="42" rx="16" ry="16" fill="rgba(5,15,35,0.55)" filter="url(#innerShadow)" />
		<rect x="30" y="42" width="60" height="38" rx="14" ry="14" fill="rgba(10,25,50,0.4)" />

		<!-- Eyes -->
		<g transform={`translate(${eyeOffsetX}, ${eyeOffsetY})`}>
			<!-- Left eye -->
			<ellipse cx="45" cy="56" rx="6" ry="10" fill="white" class="eye" class:blink={blinkState} />
			<ellipse cx="45" cy="56" rx="6" ry="10" fill="url(#eyeGlow)" opacity="0.3" class="eye" class:blink={blinkState} />
			<!-- Right eye -->
			<ellipse cx="75" cy="56" rx="6" ry="10" fill="white" class="eye" class:blink={blinkState} />
			<ellipse cx="75" cy="56" rx="6" ry="10" fill="url(#eyeGlow)" opacity="0.3" class="eye" class:blink={blinkState} />
		</g>

		<!-- Mouth -->
		<path d="M 50 76 Q 60 82 70 76" stroke="#79b8ff" stroke-width="2.5" fill="none" stroke-linecap="round" opacity="0.9" />

		<!-- Antenna -->
		<line class="antenna" x1="60" y1="16" x2="60" y2="8" stroke="#4a9eff" stroke-width="2.5" stroke-linecap="round" />
		<circle class="antenna-tip" cx="60" cy="6" r="4" fill="#79b8ff">
			<animate attributeName="opacity" values="1;0.5;1" dur="1.5s" repeatCount="indefinite" />
		</circle>

		<!-- Circuit detail lines -->
		<path d="M 32 88 L 32 94 L 40 94" stroke="rgba(121,184,255,0.3)" stroke-width="1.2" fill="none" stroke-linecap="round" />
		<path d="M 88 88 L 88 94 L 80 94" stroke="rgba(121,184,255,0.3)" stroke-width="1.2" fill="none" stroke-linecap="round" />
		<circle cx="40" cy="94" r="1.5" fill="rgba(121,184,255,0.5)">
			<animate attributeName="opacity" values="0.5;1;0.5" dur="3s" repeatCount="indefinite" />
		</circle>
		<circle cx="80" cy="94" r="1.5" fill="rgba(121,184,255,0.5)">
			<animate attributeName="opacity" values="0.5;1;0.5" dur="3s" begin="1.5s" repeatCount="indefinite" />
		</circle>
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

	.face-wrap.thinking .antenna-tip {
		filter: drop-shadow(0 0 6px rgba(121, 184, 255, 0.85));
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
