from __future__ import annotations

import dataclasses
import json
import queue
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..config import load_config
from ..interactions import (
    QuestionRequest,
    parse_question_request,
    question_answers_tool_result,
    question_request_to_json,
    validate_question_answers,
)
from ..memory.project_registry import load_project
from ..memory.project_validation import run_validation_recipe, validation_run_to_json
from ..providers import ProviderClient
from ..toolbox.base import READ_ONLY_TOOLS, ToolCall, ToolExecutor, ToolParseError, ToolRegistry, ToolResult, needs_permission, openai_tools_schema, parse_tool_calls, tool_instruction_message
from ..toolbox.registry import default_tool_registry
from ..utils import log_activity
from .runs import coding_run_to_json, complete_coding_run, get_coding_run, record_coding_run_step, start_coding_run, tool_phase, update_coding_run
from .workflows import CodingStage, CodingWorkflow, get_workflow, stage_to_json, validate_stages, workflow_to_json

MAX_STAGE_TOOL_ROUNDS = 10
TERMINAL_STATUSES = {"completed", "needs_attention", "cancelled", "failed"}


class CodingCancelled(Exception):
    pass


@dataclass
class ActiveCodingWorkflow:
    coding_run_id: str
    project_id: str
    task: str
    workflow: CodingWorkflow
    attachments: list[dict[str, Any]] = field(default_factory=list)
    status: str = "running"
    stage_id: str = ""
    stage_name: str = ""
    attempt: int = 0
    repair_count: int = 0
    subscribers: list[queue.Queue[dict[str, Any]]] = field(default_factory=list)
    cancel_requested: threading.Event = field(default_factory=threading.Event)
    permission_request: dict[str, Any] | None = None
    permission_response: threading.Event = field(default_factory=threading.Event)
    permission_granted: bool = False
    question_request: QuestionRequest | None = None
    question_response: threading.Event = field(default_factory=threading.Event)
    question_answers: dict[str, str] = field(default_factory=dict)
    gate_request: dict[str, Any] | None = None
    gate_response: threading.Event = field(default_factory=threading.Event)
    gate_action: str = ""
    gate_feedback: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)
    thread: threading.Thread | None = None

    def subscribe(self) -> queue.Queue[dict[str, Any]]:
        subscriber: queue.Queue[dict[str, Any]] = queue.Queue()
        with self.lock:
            self.subscribers.append(subscriber)
            subscriber.put({"kind": "snapshot", "run": coding_run_to_json(get_coding_run(self.coding_run_id))})
            if self.permission_request is not None:
                subscriber.put({"kind": "permission_request", **self.permission_request})
            if self.question_request is not None:
                subscriber.put({"kind": "question_request", "request": question_request_to_json(self.question_request)})
            if self.gate_request is not None:
                subscriber.put({"kind": "gate_request", **self.gate_request})
            if self.status in TERMINAL_STATUSES:
                subscriber.put({"kind": "done", "status": self.status, "done": True})
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[dict[str, Any]]) -> None:
        with self.lock:
            if subscriber in self.subscribers:
                self.subscribers.remove(subscriber)

    def broadcast(self, event: dict[str, Any]) -> None:
        with self.lock:
            subscribers = list(self.subscribers)
        for subscriber in subscribers:
            subscriber.put(event)

    def cancel(self) -> None:
        self.cancel_requested.set()
        self.permission_response.set()
        self.question_response.set()
        self.gate_response.set()


ACTIVE_CODING_RUNS: dict[str, ActiveCodingWorkflow] = {}
ACTIVE_CODING_LOCK = threading.Lock()


def active_coding_run(coding_run_id: str) -> ActiveCodingWorkflow | None:
    with ACTIVE_CODING_LOCK:
        return ACTIVE_CODING_RUNS.get(coding_run_id)


def active_workflow_runs() -> list[ActiveCodingWorkflow]:
    with ACTIVE_CODING_LOCK:
        return [run for run in ACTIVE_CODING_RUNS.values() if run.status not in TERMINAL_STATUSES]


def _normalize_attachments(raw: list[Any] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "file")
        if kind not in {"image", "text", "file"}:
            kind = "file"
        try:
            size = max(0, int(item.get("size") or 0))
        except (TypeError, ValueError):
            size = 0
        clean: dict[str, Any] = {
            "id": str(item.get("id") or "")[:80],
            "name": str(item.get("name") or "uploaded file")[:240],
            "mime_type": str(item.get("mime_type") or "application/octet-stream")[:120],
            "size": size,
            "kind": kind,
        }
        if kind == "image" and isinstance(item.get("data"), str):
            clean["data"] = str(item["data"])
        if kind == "text" and isinstance(item.get("text"), str):
            clean["text"] = str(item["text"])
        result.append(clean)
        if len(result) >= 8:
            break
    return result


def start_workflow_run(*, project_id: str, task: str, workflow_id: str, attachments: list[Any] | None = None) -> ActiveCodingWorkflow:
    if active_workflow_runs():
        raise ValueError("Another coding workflow is already active.")
    clean_task = task.strip()
    if not clean_task:
        raise ValueError("A coding task is required.")
    load_project(project_id)
    workflow = get_workflow(workflow_id)
    validate_stages(workflow.stages)
    clean_attachments = _normalize_attachments(attachments)
    coding_run = start_coding_run(
        chat_id="",
        run_id=str(uuid.uuid4()),
        project_id=project_id,
        user_request=clean_task,
        metadata={
            "source": "workflow",
            "workflow_id": workflow.id,
            "workflow_snapshot": workflow_to_json(workflow),
            "active_stage_id": "",
            "repair_count": 0,
            "attachments": clean_attachments,
        },
    )
    active = ActiveCodingWorkflow(coding_run.id, project_id, clean_task, workflow, clean_attachments)
    with ACTIVE_CODING_LOCK:
        ACTIVE_CODING_RUNS[coding_run.id] = active
    thread = threading.Thread(target=_run_workflow, args=(active,), name=f"bitbuddy-coding-{coding_run.id[:8]}", daemon=True)
    active.thread = thread
    thread.start()
    return active


def _run_workflow(active: ActiveCodingWorkflow) -> None:
    plan_outputs: list[str] = []
    build_output = ""
    try:
        build_index = next(index for index, stage in enumerate(active.workflow.stages) if stage.kind == "build")
        for stage in active.workflow.stages[:build_index]:
            output = _run_stage_with_gate(active, stage, _stage_context(active, stage, plan_outputs, build_output, []))
            plan_outputs.append(output)

        build_stage = active.workflow.stages[build_index]
        build_output = _run_stage_with_gate(active, build_stage, _stage_context(active, build_stage, plan_outputs, "", []))
        checks = active.workflow.stages[build_index + 1 :]
        findings = _run_check_stages(active, checks, plan_outputs, build_output)

        if findings:
            active.repair_count = 1
            update_coding_run(active.coding_run_id, metadata_patch={"repair_count": 1})
            repair_context = _stage_context(active, build_stage, plan_outputs, build_output, findings)
            repair_context += "\n\nThis is the single automatic repair pass. Fix every supported finding, then summarize the repairs."
            build_output = _run_stage_with_gate(active, build_stage, repair_context, repair=True)
            findings = _run_check_stages(active, checks, plan_outputs, build_output)

        final_status = "needs_attention" if findings else "completed"
        summary = "Checks still need attention after the repair pass." if findings else "Coding workflow completed successfully."
        if findings:
            summary += " " + " ".join(findings)[:1400]
        complete_coding_run(active.coding_run_id, status=final_status, summary=summary)
        active.status = final_status
        active.broadcast({"kind": "done", "status": final_status, "summary": summary, "run": coding_run_to_json(get_coding_run(active.coding_run_id)), "done": True})
    except CodingCancelled:
        complete_coding_run(active.coding_run_id, status="cancelled", summary="Coding workflow stopped. Completed changes were preserved.")
        active.status = "cancelled"
        active.broadcast({"kind": "done", "status": "cancelled", "done": True})
    except Exception as error:
        complete_coding_run(active.coding_run_id, status="failed", summary=str(error))
        active.status = "failed"
        active.broadcast({"kind": "error", "text": str(error)})
        active.broadcast({"kind": "done", "status": "failed", "done": True})
        log_activity("coding_workflow.failed", "Coding workflow failed", {"coding_run_id": active.coding_run_id, "error": str(error)})


def _run_check_stages(active: ActiveCodingWorkflow, stages: tuple[CodingStage, ...], plans: list[str], build_output: str) -> list[str]:
    findings: list[str] = []
    for stage in stages:
        output = _run_stage_with_gate(active, stage, _stage_context(active, stage, plans, build_output, []))
        upper = output.upper()
        failed = "VERDICT: FAIL" in upper or "VERDICT: CHANGES_REQUESTED" in upper or "VERDICT: CHANGES REQUESTED" in upper
        step = get_coding_run(active.coding_run_id).steps[-1]
        if bool(step.metadata.get("validation_failed")):
            failed = True
        if failed:
            findings.append(f"{stage.name}: {output[:1800]}")
    return findings


def _stage_context(active: ActiveCodingWorkflow, stage: CodingStage, plans: list[str], build_output: str, findings: list[str]) -> str:
    parts = [f"Coding task:\n{active.task}", f"Registered project id: {active.project_id}"]
    attachment_parts: list[str] = []
    attachment_chars = 0
    for attachment in active.attachments:
        name = str(attachment.get("name") or "uploaded file")
        if attachment.get("kind") == "text" and isinstance(attachment.get("text"), str):
            remaining = max(0, 40000 - attachment_chars)
            if remaining:
                excerpt = str(attachment["text"])[: min(20000, remaining)]
                attachment_parts.append(f"Attached text file {name}:\n{excerpt}")
                attachment_chars += len(excerpt)
        else:
            attachment_parts.append(f"Attached {attachment.get('kind', 'file')} file: {name} ({attachment.get('mime_type', 'application/octet-stream')})")
    if attachment_parts:
        parts.append("Task attachments:\n" + "\n\n".join(attachment_parts))
    if plans:
        parts.append("Approved planning artifacts:\n" + "\n\n".join(f"Plan {index + 1}:\n{plan}" for index, plan in enumerate(plans)))
    if build_output:
        parts.append("Latest Build summary:\n" + build_output)
    if findings:
        parts.append("Review and test findings to repair:\n" + "\n\n".join(findings))
    return "\n\n".join(parts)


def _run_stage_with_gate(active: ActiveCodingWorkflow, stage: CodingStage, context: str, *, repair: bool = False) -> str:
    feedback = ""
    while True:
        output = _execute_stage(active, stage, context, feedback=feedback, repair=repair)
        if not stage.approval_gate:
            return output
        action, feedback = _wait_for_gate(active, stage, output)
        if action == "approve":
            return output
        if action == "stop":
            raise CodingCancelled()


def _execute_stage(active: ActiveCodingWorkflow, stage: CodingStage, context: str, *, feedback: str = "", repair: bool = False) -> str:
    _throw_if_cancelled(active)
    active.stage_id = stage.id
    active.stage_name = stage.name
    active.attempt += 1
    phase = stage.kind
    update_coding_run(
        active.coding_run_id,
        status="running",
        phase=phase,
        metadata_patch={"active_stage_id": stage.id, "active_stage_name": stage.name, "attempt": active.attempt},
    )
    active.broadcast({"kind": "stage_started", "stage": stage_to_json(stage), "attempt": active.attempt, "repair": repair})
    validation_runs: list[dict[str, Any]] = []
    if stage.kind == "test":
        for recipe in stage.validation_recipes:
            _throw_if_cancelled(active)
            result = run_validation_recipe(active.project_id, recipe)
            validation_runs.append(validation_run_to_json(result))
            active.broadcast({"kind": "validation_result", "stage_id": stage.id, "result": validation_runs[-1]})

    provider = _resolve_stage_provider(stage)
    client = ProviderClient(provider)
    registry = _stage_registry(stage)
    executor_mode = "plan" if stage.kind in {"plan", "review"} else "chat"
    executor = ToolExecutor(registry, mode=executor_mode, mode_context=active.task)
    native_tools = client.supports_native_tools(stage.model)
    tools_schema = openai_tools_schema(registry, "chat") if native_tools else None
    verdict_instruction = ""
    if stage.kind == "review":
        verdict_instruction = "End with exactly `VERDICT: PASS` or `VERDICT: CHANGES_REQUESTED`."
    elif stage.kind == "test":
        verdict_instruction = "End with exactly `VERDICT: PASS` or `VERDICT: FAIL`."
    system = "\n\n".join(
        part
        for part in [
            f"You are the {stage.name} stage in a private BitBuddy coding workflow.",
            stage.instructions,
            _stage_policy(stage),
            verdict_instruction,
            "Ask the user with request_user_input only when an answer materially changes the implementation, safety, or an important preference. Do not ask for facts you can inspect.",
            tool_instruction_message(registry, native_tools=native_tools)["content"],
        ]
        if part
    )
    user_context = context
    if validation_runs:
        user_context += "\n\nSelected validation results:\n" + json.dumps(validation_runs, indent=2)[:40000]
    if feedback:
        user_context += f"\n\nThe user asked you to revise this stage:\n{feedback}"
    user_message: dict[str, Any] = {"role": "user", "content": user_context}
    image_attachments = [attachment for attachment in active.attachments if attachment.get("kind") == "image" and attachment.get("data")]
    if image_attachments:
        user_message["attachments"] = image_attachments
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}, user_message]
    output = ""
    tool_results: list[ToolResult] = []
    for round_index in range(MAX_STAGE_TOOL_ROUNDS):
        _throw_if_cancelled(active)
        chunks = list(client.stream_chat(messages, model=stage.model, should_cancel=active.cancel_requested.is_set, thinking_enabled=stage.reasoning_effort != "off", tools=tools_schema))
        response = "".join(str(getattr(chunk, "text", "")) for chunk in chunks if getattr(chunk, "kind", "") == "response").strip()
        calls = _native_calls(chunks) if native_tools else _text_calls(response)
        if not calls:
            output = response
            if output:
                active.broadcast({"kind": "stage_output", "stage_id": stage.id, "text": output})
            break
        for call in calls:
            _throw_if_cancelled(active)
            result = _execute_stage_tool(active, stage, registry, executor, call)
            tool_results.append(result)
            record_coding_run_step(
                active.coding_run_id,
                phase=tool_phase(call.tool, call.arguments) if tool_phase(call.tool, call.arguments) != "requested" else phase,
                kind="tool",
                tool=call.tool,
                status="completed" if result.ok else "error",
                summary=result.summary,
                metadata={"stage_id": stage.id, "arguments_summary": result.arguments_summary, "error": result.error, **(result.metadata or {})},
            )
            active.broadcast({"kind": "tool_result", "stage_id": stage.id, "tool": call.tool, "ok": result.ok, "summary": result.summary, "error": result.error, "metadata": result.metadata or {}})
            messages.append(result.to_model_message())
    if not output:
        output = "Stage reached its tool-round limit without a final report."
    validation_failed = any(int(item.get("exit_code", 1)) != 0 for item in validation_runs)
    record_coding_run_step(
        active.coding_run_id,
        phase=phase,
        kind="stage",
        status="completed",
        summary=output[:2000],
        metadata={
            "stage_id": stage.id,
            "stage": stage_to_json(stage),
            "attempt": active.attempt,
            "repair": repair,
            "output": output[:16000],
            "validation_runs": validation_runs,
            "validation_failed": validation_failed,
        },
    )
    active.broadcast({"kind": "stage_completed", "stage": stage_to_json(stage), "attempt": active.attempt, "output": output, "validation_failed": validation_failed})
    return output


def _execute_stage_tool(active: ActiveCodingWorkflow, stage: CodingStage, registry: ToolRegistry, executor: ToolExecutor, call: ToolCall) -> ToolResult:
    arguments = dict(call.arguments)
    if call.tool in {"glob_files", "list_directory", "search_text", "get_project_brief", "get_project_memory", "list_project_validation", "run_project_validation", "read_file", "read_file_range", "write_file", "patch_file", "make_directory", "run_shell_command"} and "project_id" not in arguments:
        arguments["project_id"] = active.project_id
    call = ToolCall(call.tool, arguments)
    if call.tool == "request_user_input":
        request = parse_question_request(call.arguments)
        with active.lock:
            active.question_request = request
            active.question_answers = {}
            active.question_response.clear()
        update_coding_run(active.coding_run_id, status="waiting_for_question", phase="waiting")
        record_coding_run_step(active.coding_run_id, phase="waiting", kind="interaction", status="running", summary="Waiting for the user's answer.", metadata={"interaction": "question", "stage_id": stage.id, "request": question_request_to_json(request)})
        active.broadcast({"kind": "question_request", "request": question_request_to_json(request)})
        while not active.question_response.is_set():
            _throw_if_cancelled(active)
            active.question_response.wait(timeout=0.25)
        _throw_if_cancelled(active)
        content = question_answers_tool_result(request, active.question_answers)
        with active.lock:
            active.question_request = None
            active.question_answers = {}
        update_coding_run(active.coding_run_id, status="running", phase=stage.kind)
        record_coding_run_step(active.coding_run_id, phase=stage.kind, kind="interaction", status="completed", summary="User answered the stage questions.", metadata={"interaction": "question", "stage_id": stage.id, "interaction_id": request.id})
        active.broadcast({"kind": "question_answered", "interaction_id": request.id})
        return ToolResult(call.tool, True, content, "User answered the requested questions.", {"interaction_id": request.id})

    mode_error = executor.check_mode_restrictions(call)
    if mode_error:
        return ToolResult(call.tool, False, "", f"Blocked in {stage.kind} stage", {}, error=mode_error)
    required, reason = needs_permission(call, registry.definition(call.tool))
    if required:
        with active.lock:
            active.permission_request = {"tool": call.tool, "reason": reason, "arguments": call.arguments}
            active.permission_granted = False
            active.permission_response.clear()
        update_coding_run(active.coding_run_id, status="waiting_for_permission", phase="waiting")
        record_coding_run_step(active.coding_run_id, phase="waiting", kind="interaction", status="running", summary=reason, metadata={"interaction": "permission", "stage_id": stage.id, "tool": call.tool, "arguments": call.arguments})
        active.broadcast({"kind": "permission_request", **active.permission_request})
        while not active.permission_response.is_set():
            _throw_if_cancelled(active)
            active.permission_response.wait(timeout=0.25)
        _throw_if_cancelled(active)
        if not active.permission_granted:
            raise CodingCancelled()
        with active.lock:
            active.permission_request = None
        update_coding_run(active.coding_run_id, status="running", phase=stage.kind)
        record_coding_run_step(active.coding_run_id, phase=stage.kind, kind="interaction", status="completed", summary=f"Permission granted for {call.tool}.", metadata={"interaction": "permission", "stage_id": stage.id, "tool": call.tool})
    return executor.execute(call)


def _wait_for_gate(active: ActiveCodingWorkflow, stage: CodingStage, output: str) -> tuple[str, str]:
    request = {"stage_id": stage.id, "stage_name": stage.name, "output": output, "attempt": active.attempt}
    with active.lock:
        active.gate_request = request
        active.gate_action = ""
        active.gate_feedback = ""
        active.gate_response.clear()
    update_coding_run(active.coding_run_id, status="waiting_for_approval", phase="waiting")
    record_coding_run_step(active.coding_run_id, phase="waiting", kind="interaction", status="running", summary=f"Waiting for approval after {stage.name}.", metadata={"interaction": "gate", **request})
    active.broadcast({"kind": "gate_request", **request})
    while not active.gate_response.is_set():
        _throw_if_cancelled(active)
        active.gate_response.wait(timeout=0.25)
    _throw_if_cancelled(active)
    action, feedback = active.gate_action, active.gate_feedback
    with active.lock:
        active.gate_request = None
    update_coding_run(active.coding_run_id, status="running", phase=stage.kind)
    record_coding_run_step(active.coding_run_id, phase=stage.kind, kind="interaction", status="completed", summary=f"Gate {action} for {stage.name}.", metadata={"interaction": "gate", "stage_id": stage.id, "action": action, "feedback": feedback})
    active.broadcast({"kind": "gate_resolved", "stage_id": stage.id, "action": action})
    return action, feedback


def answer_coding_question(coding_run_id: str, interaction_id: str, raw_answers: object) -> None:
    active = _require_active(coding_run_id)
    with active.lock:
        request = active.question_request
        if request is None:
            raise ValueError("No pending user question.")
        if interaction_id and interaction_id != request.id:
            raise ValueError("Question interaction is no longer active.")
        active.question_answers = validate_question_answers(request, raw_answers)
        active.question_response.set()


def respond_to_gate(coding_run_id: str, action: str, feedback: str = "") -> None:
    active = _require_active(coding_run_id)
    clean_action = action.strip().lower()
    if clean_action not in {"approve", "revise", "stop"}:
        raise ValueError("Gate action must be approve, revise, or stop.")
    if clean_action == "revise" and not feedback.strip():
        raise ValueError("Revision feedback is required.")
    with active.lock:
        if active.gate_request is None:
            raise ValueError("No stage is waiting for approval.")
        active.gate_action = clean_action
        active.gate_feedback = feedback.strip()[:4000]
        active.gate_response.set()


def respond_to_coding_permission(coding_run_id: str, granted: bool) -> None:
    active = _require_active(coding_run_id)
    with active.lock:
        if active.permission_request is None:
            raise ValueError("No pending permission request.")
        active.permission_granted = granted
        active.permission_response.set()


def cancel_workflow_run(coding_run_id: str) -> bool:
    active = active_coding_run(coding_run_id)
    if active is None or active.status in TERMINAL_STATUSES:
        return False
    active.cancel()
    return True


def _require_active(coding_run_id: str) -> ActiveCodingWorkflow:
    active = active_coding_run(coding_run_id)
    if active is None or active.status in TERMINAL_STATUSES:
        raise ValueError("No active coding workflow found.")
    return active


def _resolve_stage_provider(stage: CodingStage):
    config = load_config()
    provider = next((item for item in config.providers if (item.key or item.type) == stage.provider_key), None)
    if provider is None:
        raise ValueError(f"Provider `{stage.provider_key}` is no longer configured for stage `{stage.name}`.")
    return dataclasses.replace(provider, model=stage.model, reasoning_effort=stage.reasoning_effort)


def _stage_registry(stage: CodingStage) -> ToolRegistry:
    source = default_tool_registry()
    if stage.kind in {"plan", "review"}:
        allowed = set(READ_ONLY_TOOLS) - {"run_subagent"}
    elif stage.kind == "test":
        allowed = (set(READ_ONLY_TOOLS) | {"run_project_validation"}) - {"run_subagent"}
    else:
        allowed = {definition.name for definition in source.definitions()} - {"run_subagent"}
    registry = ToolRegistry()
    for name in sorted(allowed):
        definition = source.definition(name)
        handler = source.handler(name)
        if definition is not None and handler is not None:
            registry.register(definition, handler)
    return registry


def _stage_policy(stage: CodingStage) -> str:
    if stage.kind == "plan":
        return "Inspect deeply and produce a concrete plan. You are read-only and must not edit or run mutating build/test commands."
    if stage.kind == "review":
        return "Review independently. You are read-only; inspect the actual project and report specific findings rather than editing them yourself."
    if stage.kind == "test":
        return "Validate the actual implementation. You may run validation and approved shell checks, but you must not edit project files."
    return "Implement the task in the selected project. Inspect before editing, make focused changes, and verify them. Do not commit, reset, or discard user work."


def _native_calls(chunks: list[Any]) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for chunk in chunks:
        if getattr(chunk, "kind", "") != "tool_call":
            continue
        stream_call = getattr(chunk, "tool_call", None)
        if stream_call is None or not getattr(stream_call, "name", ""):
            continue
        try:
            arguments = json.loads(getattr(stream_call, "arguments", "") or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(arguments, dict):
            calls.append(ToolCall(str(stream_call.name), arguments))
    return calls


def _text_calls(response: str) -> list[ToolCall]:
    try:
        return parse_tool_calls(response)
    except ToolParseError:
        return []


def _throw_if_cancelled(active: ActiveCodingWorkflow) -> None:
    if active.cancel_requested.is_set():
        raise CodingCancelled()
