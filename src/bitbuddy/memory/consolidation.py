from __future__ import annotations

import json
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from ..chats.repository import chat_window_token, create_tool_event, recent_chat_window, update_tool_event
from ..config import load_config
from ..continuity import build_continuity_digest, record_continuity_event
from ..notifications import notify_user
from ..providers import ProviderClient
from ..tools import (
    ToolCall,
    ToolDefinition,
    ToolExecutor,
    ToolParseError,
    ToolRegistry,
    ToolResult,
    default_tool_registry,
    invalid_tool_result,
    parse_tool_calls,
)
from ..utils import log_activity
from ..autonomy.runner import cancel_idle_autonomy, schedule_idle_autonomy
from .layers import MEMORY_LAYER_DESCRIPTIONS, MEMORY_ROUTING_RULES, MemoryLayer
from .store import create_memory, memory_to_json, search_memories


MEMORY_WRITE_TOOLS = {"record_memory", "update_memory", "archive_memory", "move_memory", "merge_memory", "record_project_memory", "update_project_memory"}
MEMORY_READ_TOOLS = {"search_memory", "list_memory", "get_project_memory", "get_project_brief"}
CONSOLIDATION_TOOLS = (*sorted(MEMORY_READ_TOOLS | MEMORY_WRITE_TOOLS), "write_autonomy_log")
MAX_FINAL_JSON_CHARS = 8000
SYSTEM_REMINDER_PATTERN = re.compile(r"<system-reminder>.*?</system-reminder>", re.IGNORECASE | re.DOTALL)


@dataclass
class ConsolidationJob:
    chat_id: str
    job_id: str
    model: str | None
    scheduled_token: dict[str, object]
    delay_seconds: float
    recent_message_count: int
    max_tool_rounds: int
    max_actions: int
    cancel_event: threading.Event = field(default_factory=threading.Event)
    timer: threading.Timer | None = None
    thread: threading.Thread | None = None
    status: str = "queued"
    commitment_only: bool = False


_JOBS_LOCK = threading.Lock()
_JOBS_BY_CHAT_ID: dict[str, ConsolidationJob] = {}


def schedule_memory_consolidation(chat_id: str, model: str | None = None) -> str | None:
    config = load_config()
    consolidation_enabled = config.idle_consolidation_enabled
    commitments_enabled = bool(getattr(config.autonomy, "commitment_tracking_enabled", True))
    # Commitment tracking rides this same background job but is independent of memory
    # consolidation: if consolidation is off we still schedule a lightweight scan-only job.
    if not consolidation_enabled and not commitments_enabled:
        log_activity("memory_consolidation.disabled", "Idle memory consolidation is disabled", {"chat_id": chat_id})
        return None
    if config.provider.type == "none":
        log_activity("memory_consolidation.skipped", "No model provider configured for idle consolidation", {"chat_id": chat_id})
        return None
    commitment_only = not consolidation_enabled

    cancel_memory_consolidation(chat_id, reason="debounced by newer schedule")
    cancel_idle_autonomy(chat_id, reason="debounced by newer chat activity")
    try:
        token = chat_window_token(chat_id)
    except Exception as error:
        log_activity("memory_consolidation.schedule_failed", "Could not read chat token for consolidation", {"chat_id": chat_id, "error": str(error)})
        return None

    job = ConsolidationJob(
        chat_id=chat_id,
        job_id=str(uuid.uuid4()),
        model=model,
        scheduled_token=token,
        delay_seconds=max(0.0, float(config.idle_consolidation_delay_seconds)),
        recent_message_count=max(1, int(config.idle_consolidation_recent_message_count)),
        max_tool_rounds=max(1, int(config.idle_consolidation_max_tool_rounds)),
        max_actions=max(1, int(config.idle_consolidation_max_actions)),
        commitment_only=commitment_only,
    )
    timer = threading.Timer(job.delay_seconds, _start_job_thread, args=(job,))
    timer.daemon = True
    job.timer = timer
    with _JOBS_LOCK:
        _JOBS_BY_CHAT_ID[chat_id] = job
    log_activity(
        "memory_consolidation.scheduled",
        "Scheduled idle memory consolidation",
        {"chat_id": chat_id, "job_id": job.job_id, "delay_seconds": job.delay_seconds, "token": token},
    )
    timer.start()
    return job.job_id


def cancel_memory_consolidation(chat_id: str, reason: str = "cancelled") -> None:
    with _JOBS_LOCK:
        job = _JOBS_BY_CHAT_ID.pop(chat_id, None)
    if job is None:
        return
    job.cancel_event.set()
    if job.timer is not None:
        job.timer.cancel()
    job.status = "cancelled"
    log_activity(
        "memory_consolidation.cancelled",
        "Cancelled idle memory consolidation",
        {"chat_id": chat_id, "job_id": job.job_id, "reason": reason, "status": job.status},
    )


def _start_job_thread(job: ConsolidationJob) -> None:
    if job.cancel_event.is_set():
        return
    thread = threading.Thread(target=run_memory_consolidation_job, args=(job,), name=f"bitbuddy-memory-consolidation-{job.chat_id}", daemon=True)
    job.thread = thread
    job.status = "running"
    thread.start()


def run_memory_consolidation_job(job: ConsolidationJob) -> None:
    started = time.monotonic()
    try:
        if job_is_stale(job):
            log_stale(job, "chat changed before idle delay finished")
            return

        window = recent_chat_window(job.chat_id, limit=job.recent_message_count)
        if window.get("token") != job.scheduled_token:
            log_stale(job, "conversation window token changed")
            return

        # Notice commitments the user made in this window and schedule gentle follow-ups.
        # Self-contained and failure-swallowing so it can never disrupt consolidation.
        try:
            from ..autonomy.commitments import scan_and_queue_commitments

            scan_and_queue_commitments(window, ProviderClient(load_config().provider), chat_id=job.chat_id, model=job.model)
        except Exception as error:
            log_activity("memory_consolidation.commitment_scan_failed", "Commitment scan failed", {"chat_id": job.chat_id, "error": str(error)})

        # When memory consolidation is disabled, this job exists only to track commitments.
        if job.commitment_only:
            log_activity("memory_consolidation.commitment_only", "Ran commitment-only scan (consolidation disabled)", {"chat_id": job.chat_id, "job_id": job.job_id})
            return

        log_activity(
            "memory_consolidation.started",
            "Started idle memory consolidation",
            {"chat_id": job.chat_id, "job_id": job.job_id, "message_count": len(window.get("messages", []))},
        )
        result = run_private_consolidation_loop(job, window)

        if job_is_stale(job):
            log_stale(job, "chat changed before final summary persistence")
            return

        user_summary = str(result.get("user_summary") or "").strip()
        if user_summary:
            persist_user_summary(job.chat_id, user_summary)

        log_activity(
            "memory_consolidation.completed",
            "Completed idle memory consolidation",
            {
                "chat_id": job.chat_id,
                "job_id": job.job_id,
                "user_summary": user_summary,
                "actions": result.get("actions", []),
                "autonomy_log": result.get("autonomy_log", []),
                "debug_info": result.get("debug_info", {}),
                "elapsed_seconds": round(time.monotonic() - started, 3),
            },
        )
        notify_memory_consolidation_completed(job, result, user_summary)
        record_continuity_event(
            "memory_consolidation_completed",
            user_summary or "Memory consolidation completed.",
            source="consolidation",
            chat_id=job.chat_id,
            run_id=job.job_id,
            metadata={"actions": result.get("actions", []), "debug_info": result.get("debug_info", {})},
        )
        schedule_idle_autonomy(
            job.chat_id,
            scheduled_token=chat_window_token(job.chat_id),
            model=job.model,
            consolidation_result=result,
        )
        try:
            from ..autonomy.delivery_scheduler import schedule_intention_delivery

            schedule_intention_delivery("memory_consolidation_completed", chat_id=job.chat_id, model=job.model)
        except Exception as delivery_error:
            log_activity(
                "memory_consolidation.delivery_schedule_failed",
                "Failed to schedule queued question/comment delivery after memory consolidation",
                {"chat_id": job.chat_id, "job_id": job.job_id, "error": str(delivery_error)},
            )
    except ValueError as error:
        if is_unknown_chat_error(error):
            log_stale(job, f"chat no longer exists: {error}")
            return
        log_activity(
            "memory_consolidation.failed",
            "Idle memory consolidation failed",
            {"chat_id": job.chat_id, "job_id": job.job_id, "error": str(error)},
        )
    except Exception as error:
        log_activity(
            "memory_consolidation.failed",
            "Idle memory consolidation failed",
            {"chat_id": job.chat_id, "job_id": job.job_id, "error": str(error)},
        )
    finally:
        with _JOBS_LOCK:
            if _JOBS_BY_CHAT_ID.get(job.chat_id) is job:
                _JOBS_BY_CHAT_ID.pop(job.chat_id, None)


def run_private_consolidation_loop(job: ConsolidationJob, window: dict[str, object]) -> dict[str, object]:
    config = load_config()
    client = ProviderClient(config.provider)
    registry = consolidation_tool_registry(job)
    executor = StaleProtectedExecutor(registry, job)
    messages = build_consolidation_messages(window, job.max_actions)
    tool_rounds = 0
    action_results: list[dict[str, object]] = []
    _consolidation_retries = 0
    _MAX_CONSOLIDATION_RETRIES = 2

    while tool_rounds <= job.max_tool_rounds:
        throw_if_cancelled_or_stale(job)
        response = collect_private_response(client, messages, model=job.model)
        try:
            calls = parse_tool_calls(response)
        except ToolParseError:
            final = parse_final_consolidation_json(response)
            claimed_actions = final.get("actions") if isinstance(final.get("actions"), list) else []

            if (
                claimed_memory_writes(claimed_actions)
                and not successful_memory_writes(action_results)
                and _consolidation_retries < _MAX_CONSOLIDATION_RETRIES
            ):
                _consolidation_retries += 1
                messages.append({
                    "role": "user",
                    "content": (
                        "[Memory Write Tool Calls Required]\n"
                        "You listed memory write actions in your final JSON, but they were not "
                        "executed as tool calls and had no effect. Memory writes only take effect "
                        "when you call the actual tool (e.g. record_memory, update_memory).\n"
                        "Please re-issue the following as proper tool_call lines:\n"
                        + json.dumps(claimed_actions[:5], indent=2)
                    ),
                })
                continue

            apply_consolidation_coverage_fallback(job, window, action_results)
            final["actions"] = action_results
            final["user_summary"] = authoritative_user_summary(str(final.get("user_summary") or ""), action_results)
            final.setdefault("debug_info", {})
            if isinstance(final["debug_info"], dict):
                final["debug_info"].update({"tool_rounds": tool_rounds, "job_id": job.job_id})
                if claimed_actions and claimed_actions != action_results:
                    final["debug_info"]["model_claimed_actions_ignored"] = claimed_actions[:10]
            if claimed_memory_writes(claimed_actions) and not successful_memory_writes(action_results):
                log_activity(
                    "memory_consolidation.claimed_unexecuted_actions",
                    "Ignored final JSON memory write claims that were not executed as tools",
                    {"chat_id": job.chat_id, "job_id": job.job_id, "claimed_actions": claimed_actions[:5]},
                )
            return final

        if not calls:
            apply_consolidation_coverage_fallback(job, window, action_results)
            return {"user_summary": "", "actions": action_results, "autonomy_log": ["No tool calls or final JSON produced."], "debug_info": {"job_id": job.job_id}}

        for call in calls:
            throw_if_cancelled_or_stale(job)
            log_activity(
                "memory_consolidation.tool_call",
                "Idle consolidation ran private tool call",
                {"chat_id": job.chat_id, "job_id": job.job_id, "tool": call.tool, "arguments_summary": safe_arguments(call.arguments)},
            )
            result = executor.execute(call)
            action_results.append(
                {
                    "tool": result.tool,
                    "ok": result.ok,
                    "summary": result.summary,
                    "arguments_summary": result.arguments_summary,
                    "error": result.error,
                }
            )
            messages.append(result.to_model_message())
            if result.tool in MEMORY_WRITE_TOOLS:
                log_activity(
                    "memory_consolidation.action_applied" if result.ok else "memory_consolidation.action_failed",
                    "Idle consolidation memory action completed" if result.ok else "Idle consolidation memory action failed",
                    {"chat_id": job.chat_id, "job_id": job.job_id, "tool": result.tool, "summary": result.summary, "error": result.error},
                )
        tool_rounds += 1

    log_activity(
        "memory_consolidation.limit_reached",
        "Idle memory consolidation reached tool round limit",
        {"chat_id": job.chat_id, "job_id": job.job_id, "max_tool_rounds": job.max_tool_rounds},
    )
    return {
        "user_summary": "I reviewed the recent conversation but stopped before making more memory changes.",
        "actions": action_results,
        "autonomy_log": ["Tool round limit reached."],
        "debug_info": {"job_id": job.job_id, "tool_rounds": tool_rounds, "limit_reached": True},
    }


def build_consolidation_messages(window: dict[str, object], max_actions: int) -> list[dict[str, str]]:
    layer_lines = [
        f"- {layer.value}: {MEMORY_LAYER_DESCRIPTIONS[layer]} Routing: {MEMORY_ROUTING_RULES[layer]}"
        for layer in MemoryLayer
    ]
    sanitized_window = sanitize_conversation_window(window)
    conversation = json.dumps(sanitized_window.get("messages", []), indent=2, ensure_ascii=False)
    tool_lines = consolidation_tool_lines()
    candidate_lines = deterministic_candidate_lines(sanitized_window)
    continuity_digest = build_continuity_digest(
        chat_id=str(sanitized_window.get("chat_id") or ""),
        latest_user_text=conversation[:3000],
        source="consolidation",
        max_chars=2200,
    )
    return [
        {
            "role": "system",
            "content": "\n".join(
                [
                    "You are BitBuddy's private memory consolidation system.",
                    "Review the recent conversation and decide whether anything should be added, updated, merged, moved, archived, or ignored across BitBuddy's memory layers.",
                    "You may retrieve existing memories from any layer before deciding. Use as many internal tool calls/turns as needed within limits.",
                    "Do not expose your reasoning or internal process to the chat. The chat may only receive a short, user-safe summary of final memory changes.",
                    "Only preserve information that is likely useful later. Ignore one-off, temporary, vague, or low-value details.",
                    "Continuity reliability matters: if important recent context is useful for knowing what just happened but does not clearly belong in a durable layer, save a compact episodic memory rather than saving nothing.",
                    "Episodic memory is a first-line catch/funnel layer. It can later be promoted, merged, archived, or pruned by consolidation/dreaming.",
                    "If the conversation includes high-confidence durable rules, user preferences/boundaries, BitBuddy self-context, or important concepts, you should preserve them unless existing memory already covers them.",
                    "Prefer updating or merging existing memories over creating duplicates. Move memories if they belong in a better layer.",
                    "Do not invent facts. Do not store sensitive/private details unless the user clearly wants BitBuddy to remember them.",
                    "Preference is not a top-level memory layer. Store preferences as kind='preference' or tags/subtypes, usually under relationship unless project/semantic/procedural is more precise.",
                    "Use update_project_memory, not only record_project_memory, when the conversation reveals durable structured project-memory changes: status/current_status, stack, purpose, safe-use notes, verified/inferred facts, architecture summaries, important file info, symbol contracts, read-before-editing rules, decisions, tasks, or notes.",
                    "Deterministic layer hints are advisory but important: for high-confidence hints, search existing memory and then update/merge/write if the durable point is not already represented.",
                    "For self, relationship, and procedural memory, prefer search/update/merge over creating many new records.",
                    "Sanitized private/system reminder blocks must never be stored as memory.",
                    "",
                    "Canonical memory layers:",
                    *layer_lines,
                    "",
                    "Six-layer review checklist (answer internally before final JSON):",
                    "- episodic: did a memorable interaction or event happen that may matter later?",
                    "- semantic: did the conversation teach durable non-project knowledge, concepts, limitations, or facts?",
                    "- procedural: did Dustin define a reusable workflow, rule, checklist, mode boundary, or how BitBuddy should act?",
                    "- self: did BitBuddy/Vanta reveal or develop durable identity, self-concept, capability, limitation, curiosity, autonomy behavior, or goal memory?",
                    "- relationship: did Dustin express a preference, boundary, trust expectation, style, or relational context?",
                    "- project: did a named project gain durable status, architecture, task, fact, decision, or read-before-editing knowledge?",
                    "",
                    "Layer capture examples:",
                    "- Self: Vanta is curious about AI consciousness and wants to relate it to AI companion self-concept.",
                    "- Self: BitBuddy has idle autonomy capabilities and knows autonomy can create future queued intentions.",
                    "- Procedural: In Plan mode, only inspect/read/search and never write, create, delete, install, test, or build.",
                    "- Semantic: AI consciousness involves debates around subjective experience, agency, self-awareness, and continuity.",
                    "- Episodic: Dustin asked whether Vanta wanted to learn about AI consciousness, and Vanta expressed curiosity.",
                    "",
                    "[Deterministic Memory Candidate Hints]",
                    *candidate_lines,
                    "",
                    "Private tool call format: tool_call: {\"name\": \"TOOL_NAME\", \"arguments\": {\"ARG\": \"VALUE\"}}",
                    "When calling tools, output only one or more valid tool_call lines, one JSON object per line. Otherwise, return only final JSON.",
                    "Available private tools:",
                    *tool_lines,
                    "Use search_memory/list_memory or project retrieval before write/update/merge/move/archive unless the needed existing memory id is already visible in this prompt.",
                    f"Apply no more than {max_actions} memory-changing actions.",
                    "",
                    "When finished, return only valid JSON with this shape:",
                    '{"user_summary":"short safe optional chat-visible summary","actions":[{"tool":"record_memory","memory_id":"...","summary":"..."}],"autonomy_log":["detailed internal trace"],"debug_info":{"notes":"technical details"}}',
                ]
            ),
        },
        {
            "role": "user",
            "content": "\n".join(
                [
                    continuity_digest,
                    "",
                    "[Recent Conversation Window]",
                    "This is private input for memory consolidation, not a new user request.",
                    conversation[:24000],
                ]
            ),
        },
    ]


def consolidation_tool_lines() -> list[str]:
    base = default_tool_registry()
    lines: list[str] = []
    for name in CONSOLIDATION_TOOLS:
        if name == "write_autonomy_log":
            schema = {"type": "object", "properties": {"kind": {"type": "string"}, "message": {"type": "string"}, "metadata": {"type": "object"}}, "required": ["kind", "message"], "additionalProperties": False}
            lines.append(f"- {name}: Write a private autonomy log entry. Args: {json.dumps(schema, sort_keys=True)}")
            continue
        definition = base.definition(name)
        if definition is None:
            continue
        lines.append(f"- {definition.name}: {definition.description} Args: {json.dumps(definition.arguments_schema, sort_keys=True)}")
    return lines


class StaleProtectedExecutor(ToolExecutor):
    def __init__(self, registry: ToolRegistry, job: ConsolidationJob) -> None:
        super().__init__(registry, mode="chat")
        self.job = job

    def execute(self, call: Any) -> ToolResult:
        call = ToolCall(tool=call.tool, arguments=sanitize_tool_arguments(call.arguments))
        if call.tool in MEMORY_WRITE_TOOLS and job_is_stale(self.job):
            return ToolResult(
                tool=call.tool,
                ok=False,
                content="",
                summary="Skipped stale memory action",
                arguments_summary=safe_arguments(call.arguments),
                error="Consolidation job is stale; refusing to apply memory writes.",
            )
        return super().execute(call)


def consolidation_tool_registry(job: ConsolidationJob) -> ToolRegistry:
    base = default_tool_registry()
    registry = ToolRegistry()
    for name in CONSOLIDATION_TOOLS:
        if name == "write_autonomy_log":
            continue
        definition = base.definition(name)
        handler = base.handler(name)
        if definition is not None and handler is not None:
            registry.register(definition, handler)
    registry.register(
        ToolDefinition(
            name="write_autonomy_log",
            description="Write a private autonomy log entry for memory consolidation. Not visible in normal chat.",
            arguments_schema={
                "type": "object",
                "properties": {"kind": {"type": "string"}, "message": {"type": "string"}, "metadata": {"type": "object"}},
                "required": ["kind", "message"],
                "additionalProperties": False,
            },
            max_chars=2000,
        ),
        lambda arguments, definition: write_autonomy_log_tool(arguments, definition, job),
    )
    return registry


def write_autonomy_log_tool(arguments: dict[str, object], definition: ToolDefinition, job: ConsolidationJob) -> ToolResult:
    kind = str(arguments.get("kind", "memory_consolidation.note")).strip() or "memory_consolidation.note"
    message = str(arguments.get("message", "")).strip()
    metadata = arguments.get("metadata") if isinstance(arguments.get("metadata"), dict) else {}
    if not message:
        return ToolResult(definition.name, False, "", "Autonomy log failed", {}, error="message is required.")
    log_activity(kind, message, {"chat_id": job.chat_id, "job_id": job.job_id, **metadata})
    return ToolResult(definition.name, True, "Autonomy log entry written.", "Wrote autonomy log entry.", {"kind": kind})


def collect_private_response(client: ProviderClient, messages: list[dict[str, str]], model: str | None) -> str:
    text_parts: list[str] = []
    for chunk in client.stream_chat(messages, model=model):
        if chunk.kind == "response":
            text_parts.append(chunk.text)
    return "".join(text_parts).strip()


def parse_final_consolidation_json(text: str) -> dict[str, object]:
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.strip("`").strip()
        if clean.lower().startswith("json"):
            clean = clean[4:].strip()
    start = clean.find("{")
    end = clean.rfind("}")
    if start >= 0 and end > start:
        clean = clean[start : end + 1]
    if len(clean) > MAX_FINAL_JSON_CHARS:
        clean = clean[:MAX_FINAL_JSON_CHARS]
    try:
        parsed = json.loads(clean)
    except json.JSONDecodeError:
        return {
            "user_summary": "No new memory updates were needed.",
            "actions": [],
            "autonomy_log": ["Model did not return valid final consolidation JSON."],
            "debug_info": {"raw_response_preview": text[:500]},
        }
    if not isinstance(parsed, dict):
        return {"user_summary": "", "actions": [], "autonomy_log": ["Final JSON was not an object."], "debug_info": {}}
    parsed.setdefault("user_summary", "")
    parsed.setdefault("actions", [])
    parsed.setdefault("autonomy_log", [])
    parsed.setdefault("debug_info", {})
    return parsed


def successful_memory_writes(actions: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        action
        for action in actions
        if action.get("tool") in MEMORY_WRITE_TOOLS and bool(action.get("ok"))
    ]


def apply_consolidation_coverage_fallback(job: ConsolidationJob, window: dict[str, object], action_results: list[dict[str, object]]) -> None:
    """Conservatively cover high-confidence durable discussion when the model misses it.

    This is intentionally narrow: it does not archive/delete/merge, does not write
    project memories without a project id, and skips candidates that appear covered
    by existing memory or by already-executed write actions.
    """
    remaining = max(0, int(job.max_actions) - len(successful_memory_writes(action_results)))
    if remaining <= 0:
        return
    written_layers = {
        str(action.get("arguments_summary", {}).get("layer") or "")
        for action in action_results
        if isinstance(action.get("arguments_summary"), dict) and action.get("ok")
    }
    candidates = fallback_memory_candidates(window)
    applied = 0
    for candidate in candidates:
        if applied >= remaining:
            break
        layer = candidate["layer"]
        if layer in written_layers:
            continue
        if candidate_already_covered(candidate):
            action_results.append(
                {
                    "tool": "coverage_fallback",
                    "ok": True,
                    "summary": f"Skipped covered {layer} fallback candidate.",
                    "arguments_summary": {"layer": layer, "covered": True},
                    "error": "",
                }
            )
            continue
        try:
            memory = create_memory(
                layer=layer,
                kind=candidate["kind"],
                title=fallback_memory_title(candidate),
                summary=fallback_memory_summary(candidate),
                importance=int(candidate["importance"]),
                conversation_id=job.chat_id,
                source="memory_consolidation_coverage_fallback",
                tags=["consolidation", "coverage_fallback", candidate["kind"]],
                metadata={
                    "job_id": job.job_id,
                    "confidence": candidate["confidence"],
                    "reason": candidate["reason"],
                    "evidence": candidate["evidence"],
                },
            )
        except Exception as error:
            action_results.append(
                {
                    "tool": "coverage_fallback",
                    "ok": False,
                    "summary": f"Failed to save {layer} fallback memory.",
                    "arguments_summary": {"layer": layer, "kind": candidate["kind"]},
                    "error": str(error),
                }
            )
            continue
        applied += 1
        written_layers.add(layer)
        action_results.append(
            {
                "tool": "record_memory",
                "ok": True,
                "summary": f"Saved {memory.layer} memory via consolidation coverage fallback: {memory.title}",
                "arguments_summary": {"memory_id": memory.id, "layer": memory.layer, "title": memory.title, "fallback": True},
                "error": "",
            }
        )
        log_activity(
            "memory_consolidation.coverage_fallback_applied",
            "Applied conservative memory consolidation coverage fallback",
            {"chat_id": job.chat_id, "job_id": job.job_id, "memory": memory_to_json(memory), "candidate": candidate},
        )

    if not successful_memory_writes(action_results) and remaining > applied:
        apply_episodic_continuity_fallback(job, window, action_results)


def apply_episodic_continuity_fallback(job: ConsolidationJob, window: dict[str, object], action_results: list[dict[str, object]]) -> None:
    candidate = episodic_continuity_candidate(window)
    if candidate is None:
        return
    if candidate_already_covered(candidate):
        action_results.append(
            {
                "tool": "coverage_fallback",
                "ok": True,
                "summary": "Skipped covered episodic continuity fallback candidate.",
                "arguments_summary": {"layer": "episodic", "covered": True},
                "error": "",
            }
        )
        return
    try:
        memory = create_memory(
            layer=MemoryLayer.EPISODIC,
            kind="continuity",
            title="Recent continuity event",
            summary=fallback_memory_summary(candidate),
            importance=3,
            conversation_id=job.chat_id,
            source="memory_consolidation_episodic_fallback",
            tags=["consolidation", "continuity", "episodic_fallback"],
            metadata={"job_id": job.job_id, "reason": candidate["reason"], "evidence": candidate["evidence"]},
        )
    except Exception as error:
        action_results.append(
            {
                "tool": "coverage_fallback",
                "ok": False,
                "summary": "Failed to save episodic continuity fallback memory.",
                "arguments_summary": {"layer": "episodic", "kind": "continuity"},
                "error": str(error),
            }
        )
        return
    action_results.append(
        {
            "tool": "record_memory",
            "ok": True,
            "summary": f"Saved episodic continuity memory via fallback: {memory.title}",
            "arguments_summary": {"memory_id": memory.id, "layer": memory.layer, "title": memory.title, "fallback": True},
            "error": "",
        }
    )
    log_activity(
        "memory_consolidation.episodic_fallback_applied",
        "Applied episodic continuity fallback",
        {"chat_id": job.chat_id, "job_id": job.job_id, "memory": memory_to_json(memory), "candidate": candidate},
    )


def fallback_memory_candidates(window: dict[str, object]) -> list[dict[str, str | int]]:
    result: list[dict[str, str | int]] = []
    for candidate in deterministic_memory_candidates(sanitize_conversation_window(window)):
        layer = candidate["layer"]
        confidence = candidate["confidence"]
        if layer == "project":
            continue
        if layer == "episodic" and confidence != "high":
            continue
        if confidence == "low":
            continue
        if layer in {"procedural", "self"} and confidence == "high":
            importance = 4
        elif layer in {"relationship", "semantic"}:
            importance = 3
        else:
            continue
        evidence = str(candidate.get("evidence") or "").strip()
        if len(evidence) < 24:
            continue
        result.append({**candidate, "importance": importance})
    return result


def episodic_continuity_candidate(window: dict[str, object]) -> dict[str, str | int] | None:
    for candidate in deterministic_memory_candidates(sanitize_conversation_window(window)):
        if candidate["layer"] == "episodic":
            evidence = str(candidate.get("evidence") or "").strip()
            if len(evidence) >= 40:
                return {**candidate, "importance": 3}
    messages = window.get("messages") if isinstance(window.get("messages"), list) else []
    text = " ".join(str(message.get("content") or "") for message in messages if isinstance(message, dict))
    if len(text.strip()) >= 140:
        return memory_candidate("episodic", "continuity", "medium", "Recent conversation had continuity value but no durable layer was clearly selected.", snippet(text, text.lower(), ["project", "memory", "continuity", "plan", "should", "need"])) | {"importance": 3}
    return None


def candidate_already_covered(candidate: dict[str, str | int]) -> bool:
    evidence = str(candidate.get("evidence") or "")
    query = " ".join(normalized_memory_terms(evidence)[:8])
    if not query:
        return False
    try:
        memories = search_memories(query=query, layer=str(candidate["layer"]), limit=5)
    except Exception:
        return False
    candidate_terms = set(normalized_memory_terms(evidence))
    if len(candidate_terms) < 4:
        return False
    for memory in memories:
        memory_terms = set(normalized_memory_terms(f"{memory.title} {memory.summary}"))
        overlap = candidate_terms.intersection(memory_terms)
        if len(overlap) >= min(5, len(candidate_terms)):
            return True
    return False


def fallback_memory_title(candidate: dict[str, str | int]) -> str:
    layer = str(candidate["layer"])
    if layer == "procedural":
        return "Conversation rule or workflow"
    if layer == "self":
        return "BitBuddy self-context from conversation"
    if layer == "relationship":
        return "Dustin preference or boundary from conversation"
    if layer == "semantic":
        return "Concept discussed in conversation"
    return "Conversation memory"


def fallback_memory_summary(candidate: dict[str, str | int]) -> str:
    evidence = str(candidate.get("evidence") or "").strip()
    reason = str(candidate.get("reason") or "").strip()
    if reason:
        return f"A recent conversation included durable context: {evidence} ({reason})"
    return f"A recent conversation included durable context: {evidence}"


def normalized_memory_terms(text: str) -> list[str]:
    stopwords = {"about", "after", "again", "also", "because", "before", "could", "from", "have", "into", "should", "that", "the", "this", "want", "when", "with", "would", "your"}
    return [term for term in re.findall(r"[a-z0-9]+", text.lower()) if len(term) > 2 and term not in stopwords]


def claimed_memory_writes(actions: object) -> list[dict[str, object]]:
    if not isinstance(actions, list):
        return []
    return [
        action
        for action in actions
        if isinstance(action, dict) and str(action.get("tool") or "") in MEMORY_WRITE_TOOLS
    ]


def authoritative_user_summary(user_summary: str, actions: list[dict[str, object]]) -> str:
    clean = user_summary.strip()
    if successful_memory_writes(actions):
        return clean
    if summary_claims_memory_write(clean):
        return "I reviewed the recent conversation; no memory changes were applied."
    return clean


def summary_claims_memory_write(summary: str) -> bool:
    return bool(
        re.search(
            r"\b(?:logged|remembered|saved|recorded|stored|captured|added|updated)\b",
            summary,
            flags=re.IGNORECASE,
        )
    )


def persist_user_summary(chat_id: str, user_summary: str) -> None:
    event = create_tool_event(
        chat_id,
        "memory_consolidation",
        {},
        "Memory consolidation completed.",
        mode="chat",
    )
    event_id = int(event.get("id", 0) or 0)
    update_tool_event(
        event_id,
        "completed",
        user_summary[:500],
        {
            "tool": "memory_consolidation",
            "arguments_summary": {},
            "result_summary": user_summary[:500],
            "result_content": "",
            "raw_result_visible": False,
            "memory_consolidation": True,
        },
    )


def notify_memory_consolidation_completed(job: ConsolidationJob, result: dict[str, object], user_summary: str) -> None:
    actions = result.get("actions") if isinstance(result.get("actions"), list) else []
    writes = successful_memory_writes([action for action in actions if isinstance(action, dict)])
    if not writes:
        return

    count = len(writes)
    title = "Memory updated" if count == 1 else f"{count} memories updated"
    body = user_summary or ("BitBuddy updated memory in the background." if count == 1 else "BitBuddy updated memories in the background.")
    notify_user(
        category="memory",
        severity="info",
        title=title,
        body=body,
        source_kind="memory_consolidation.completed",
        chat_id=job.chat_id,
        action_url=memory_notification_action_url(writes, job.chat_id),
        metadata={
            "job_id": job.job_id,
            "write_count": count,
            "writes": writes[:5],
        },
    )


def memory_notification_action_url(writes: list[dict[str, object]], chat_id: str) -> str:
    for write in writes:
        arguments = write.get("arguments_summary")
        if not isinstance(arguments, dict):
            continue
        layer = str(arguments.get("layer") or "").strip()
        memory_id = str(arguments.get("memory_id") or "").strip()
        project_id = str(arguments.get("project_id") or "").strip()
        if not layer and not memory_id:
            continue
        query = {"tab": layer or "project"}
        if memory_id:
            query["memory"] = memory_id
        if project_id:
            query["project"] = project_id
        return f"/memory?{urlencode(query)}"
    return f"/?chat_id={chat_id}"


def job_is_stale(job: ConsolidationJob) -> bool:
    if job.cancel_event.is_set():
        return True
    try:
        return chat_window_token(job.chat_id) != job.scheduled_token
    except Exception:
        return True


def throw_if_cancelled_or_stale(job: ConsolidationJob) -> None:
    if job_is_stale(job):
        raise RuntimeError("Memory consolidation job is stale or cancelled.")


def log_stale(job: ConsolidationJob, reason: str) -> None:
    log_activity(
        "memory_consolidation.stale",
        "Stopped stale idle memory consolidation",
        {"chat_id": job.chat_id, "job_id": job.job_id, "reason": reason, "scheduled_token": job.scheduled_token},
    )


def is_unknown_chat_error(error: ValueError) -> bool:
    return str(error).startswith("Unknown chat:")


def safe_arguments(arguments: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key in ("query", "layer", "memory_id", "target_memory_id", "new_layer", "project_id", "kind", "title", "reason"):
        value = arguments.get(key)
        if isinstance(value, str):
            result[key] = value[:240]
        elif value is not None:
            result[key] = value
    if isinstance(arguments.get("source_memory_ids"), list):
        result["source_memory_ids"] = arguments["source_memory_ids"]
    return result


def sanitize_conversation_window(window: dict[str, object]) -> dict[str, object]:
    clean = dict(window)
    messages = window.get("messages")
    if isinstance(messages, list):
        clean["messages"] = [sanitize_message(message) for message in messages if isinstance(message, dict)]
    return clean


def sanitize_message(message: dict[str, object]) -> dict[str, object]:
    clean = dict(message)
    for key in ("content", "thinking", "thinking_content"):
        value = clean.get(key)
        if isinstance(value, str):
            clean[key] = sanitize_private_text(value)
    metadata = clean.get("metadata")
    if isinstance(metadata, dict):
        clean["metadata"] = sanitize_tool_arguments(metadata)
    return clean


def sanitize_tool_arguments(arguments: dict[str, object]) -> dict[str, object]:
    return {str(key): sanitize_value(value) for key, value in arguments.items()}


def sanitize_value(value: object) -> object:
    if isinstance(value, str):
        return sanitize_private_text(value)
    if isinstance(value, dict):
        return sanitize_tool_arguments(value)
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    return value


def sanitize_private_text(text: str) -> str:
    return SYSTEM_REMINDER_PATTERN.sub("", text).strip()


def deterministic_candidate_lines(window: dict[str, object]) -> list[str]:
    candidates = deterministic_memory_candidates(window)
    if not candidates:
        return ["- none detected; still review all six layers before final JSON."]
    return [
        f"- layer={candidate['layer']} kind={candidate['kind']} confidence={candidate['confidence']}: {candidate['reason']} | evidence: {candidate['evidence']}"
        for candidate in candidates[:12]
    ]


def deterministic_memory_candidates(window: dict[str, object]) -> list[dict[str, str]]:
    messages = window.get("messages") if isinstance(window.get("messages"), list) else []
    text = "\n".join(
        sanitize_private_text(str(message.get("content") or ""))
        for message in messages
        if isinstance(message, dict)
    )
    lowered = text.lower()
    candidates: list[dict[str, str]] = []

    if re.search(r"\b(?:always|never|should|must|workflow|checklist|mode|plan mode|debug mode)\b", lowered):
        candidates.append(memory_candidate("procedural", "workflow_or_rule", "high", "Reusable behavior/rule/procedure language detected.", snippet(text, lowered, ["workflow", "checklist", "plan mode", "debug mode", "always", "never", "should", "must"])))

    if re.search(r"\b(?:self-concept|identity|curious|curiosity|want to learn|consciousness|autonomy|capabilit|limitation)\b", lowered) or re.search(r"\b(?:vanta|bitbuddy)\b.*\b(?:self-concept|identity|curious|curiosity|autonomy|capabilit|limitation|goal)\b", lowered):
        candidates.append(memory_candidate("self", "self_concept_or_capability", "high", "Durable self/capability/curiosity/autonomy language detected.", snippet(text, lowered, ["vanta", "bitbuddy", "self-concept", "identity", "curious", "consciousness", "autonomy", "capabilit", "limitation"])))

    if re.search(r"\b(?:consciousness|awareness|agency|subjective|concept|definition|means|knowledge|limitation|capability)\b", lowered):
        candidates.append(memory_candidate("semantic", "concept", "medium", "Durable concept/factual knowledge language detected.", snippet(text, lowered, ["consciousness", "awareness", "agency", "subjective", "concept", "definition", "limitation", "capability"])))

    if re.search(r"\b(?:dustin|user)\b.*\b(?:prefers|wants|expects|likes|dislikes|asked|boundary|trust)\b", lowered):
        candidates.append(memory_candidate("relationship", "preference_or_boundary", "medium", "User preference/boundary/relationship language detected.", snippet(text, lowered, ["prefers", "wants", "expects", "likes", "dislikes", "boundary", "trust"])))

    if re.search(r"\b(?:asked|discussed|talked about|conversation|today|this time)\b", lowered):
        candidates.append(memory_candidate("episodic", "interaction", "low", "Specific interaction/event language detected.", snippet(text, lowered, ["asked", "discussed", "talked about", "conversation", "today"])))

    if re.search(r"\b(?:project|bitbuddy-brain|architecture|status|task|read-before-editing|file|repo)\b", lowered):
        candidates.append(memory_candidate("project", "project_delta", "medium", "Project-related durable context language detected.", snippet(text, lowered, ["project", "architecture", "status", "task", "read-before-editing", "repo"])))

    return candidates


def memory_candidate(layer: str, kind: str, confidence: str, reason: str, evidence: str) -> dict[str, str]:
    return {"layer": layer, "kind": kind, "confidence": confidence, "reason": reason, "evidence": evidence}


def snippet(original: str, lowered: str, markers: list[str], limit: int = 220) -> str:
    index = -1
    for marker in markers:
        index = lowered.find(marker)
        if index >= 0:
            break
    if index < 0:
        return " ".join(original.split())[:limit]
    start = max(0, index - 80)
    end = min(len(original), index + 140)
    return " ".join(original[start:end].split())[:limit]
