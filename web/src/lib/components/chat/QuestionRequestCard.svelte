<script lang="ts">
	import type { ChatMessage, QuestionRequest } from '$lib/api/bitbuddy';
	import { respondToQuestion, stopActiveResponse } from '$lib/stores/chat.svelte';

	let { message } = $props<{ message: ChatMessage }>();
	let request = $derived(message.metadata?.question_request as QuestionRequest | undefined);
	let answers = $state<Record<string, string>>({});
	let custom = $state<Record<string, string>>({});
	let submitting = $state(false);
	let error = $state('');

	function choose(id: string, value: string) {
		answers[id] = value;
		custom[id] = '';
	}

	function setCustom(id: string, value: string) {
		custom[id] = value;
		if (value.trim()) answers[id] = value.trim();
		else delete answers[id];
	}

	async function submit() {
		if (!request || submitting) return;
		if (request.questions.some((question) => !answers[question.id]?.trim())) {
			error = 'Answer each question before continuing.';
			return;
		}
		submitting = true;
		error = '';
		try {
			await respondToQuestion(request.id, answers);
		} catch (caught) {
			error = caught instanceof Error ? caught.message : 'Could not send those answers.';
		} finally {
			submitting = false;
		}
	}
</script>

{#if request && message.status === 'running'}
	<div class="question-overlay" role="presentation">
		<div class="question-card" role="dialog" aria-modal="true" aria-label="BitBuddy has a question">
			<header>
				<span>BitBuddy needs your input</span>
				<small>The active run is paused.</small>
			</header>

			<div class="questions">
				{#each request.questions as item}
					<fieldset>
						<legend><span>{item.header}</span>{item.question}</legend>
						<div class="choices">
							{#each item.options as option}
								<button class:selected={answers[item.id] === option.label && !custom[item.id]} type="button" onclick={() => choose(item.id, option.label)}>
									<strong>{option.label}</strong>
									<small>{option.description}</small>
								</button>
							{/each}
						</div>
						<label>
							<span>Other</span>
							<input value={custom[item.id] ?? ''} oninput={(event) => setCustom(item.id, event.currentTarget.value)} placeholder="Write your own answer" />
						</label>
					</fieldset>
				{/each}
			</div>

			{#if error}<p class="error">{error}</p>{/if}
			<footer>
				<button class="stop" type="button" onclick={stopActiveResponse} disabled={submitting}>Stop run</button>
				<button class="continue" type="button" onclick={submit} disabled={submitting}>{submitting ? 'Sending…' : 'Continue'}</button>
			</footer>
		</div>
	</div>
{/if}

<style>
	.question-overlay { position: fixed; inset: 0; z-index: 10000; display: grid; place-items: center; padding: 1rem; background: color-mix(in srgb, var(--bg) 30%, transparent); backdrop-filter: blur(8px); }
	.question-card { width: min(43rem, 100%); max-height: calc(100vh - 2rem); overflow: auto; border: 1px solid color-mix(in srgb, var(--accent) 45%, var(--border)); border-radius: 1rem; background: var(--panel-raised); box-shadow: var(--shadow-panel); }
	header { display: flex; justify-content: space-between; gap: 1rem; padding: 1.1rem 1.2rem; border-bottom: 1px solid var(--border); }
	header span { font-weight: 780; } header small { color: var(--text-soft); }
	.questions { display: grid; gap: 1rem; padding: 1.2rem; }
	fieldset { border: 0; padding: 0; margin: 0; }
	legend { display: grid; gap: .3rem; margin-bottom: .75rem; color: var(--text); }
	legend span { color: var(--accent); font-size: .72rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
	.choices { display: grid; gap: .55rem; }
	.choices button { display: grid; gap: .2rem; width: 100%; padding: .8rem .9rem; border: 1px solid var(--border); border-radius: .72rem; text-align: left; background: var(--panel); color: var(--text); }
	.choices button:hover, .choices button.selected { border-color: var(--accent); background: color-mix(in srgb, var(--accent-soft) 55%, var(--panel)); }
	.choices small { color: var(--text-soft); line-height: 1.35; }
	label { display: grid; gap: .35rem; margin-top: .6rem; color: var(--text-soft); font-size: .8rem; }
	input { width: 100%; padding: .72rem .8rem; border: 1px solid var(--border); border-radius: .65rem; background: var(--bg-soft); color: var(--text); }
	.error { margin: 0 1.2rem; color: var(--danger); font-size: .86rem; }
	footer { display: flex; justify-content: flex-end; gap: .65rem; padding: 1rem 1.2rem 1.2rem; }
	footer button { padding: .65rem 1rem; border-radius: .65rem; font-weight: 740; }
	.stop { border: 1px solid var(--border); color: var(--text-soft); }
	.continue { background: var(--accent); color: white; }
	@media (max-width: 600px) { header { flex-direction: column; } .question-card { max-height: calc(100vh - 1rem); } }
</style>
