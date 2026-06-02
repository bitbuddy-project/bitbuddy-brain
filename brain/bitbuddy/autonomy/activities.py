from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import load_config
from ..memory.layers import MemoryLayer
from ..memory.project import ARCHITECTURE_FIELDS, PROJECT_OVERVIEW_FIELDS, list_projects, load_project, project_model, update_structured_project_memory
from ..memory.store import MemoryRecord, create_memory, search_memories
from ..providers import ProviderClient
from ..self_model import add_self_journal, create_goal, get_goal, get_recent_conversation_signals, get_self_state, goal_task_state, list_goals, set_goal_task_state, update_goal, update_self_state, upsert_personality_evolution
from ..workspace import append_to_workspace_document, latest_document_for_goal, write_workspace_document
from .decision import AutonomyActivityType, AutonomyDecision, collect_model_text, extract_json_object
from .intentions import create_intention, intention_to_json
from .log import log_autonomy
from .memory import record_autonomy_self_memory
from .web_search import safe_web_search, search_results_to_text


@dataclass(frozen=True)
class AutonomyActivityResult:
    activity: AutonomyActivityType
    status: str
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)


def run_autonomy_activity(
    decision: AutonomyDecision,
    cycle_id: str,
    client: ProviderClient,
    model: str | None = None,
) -> AutonomyActivityResult:
    if decision.activity == AutonomyActivityType.GENERATE_USER_PROMPTS:
        return generate_user_prompts(cycle_id, client, decision, model=model)
    if decision.activity == AutonomyActivityType.PROJECT_FAMILIARIZATION:
        return project_familiarization(cycle_id, client, decision, model=model)
    if decision.activity == AutonomyActivityType.WEB_CURIOSITY:
        return web_curiosity(cycle_id, client, decision, model=model)
    if decision.activity == AutonomyActivityType.SELF_REFLECTION:
        return self_reflection(cycle_id, client, decision, model=model)
    if decision.activity == AutonomyActivityType.PURSUE_GOAL:
        return pursue_goal(cycle_id, client, decision, model=model)
    if decision.activity == AutonomyActivityType.NETWORK_OBSERVATION:
        return AutonomyActivityResult(decision.activity, "skipped", "Network observation is not implemented yet.", {"reason": decision.reason})
    return AutonomyActivityResult(AutonomyActivityType.DO_NOTHING, "skipped", decision.reason or "No useful autonomy action selected.")


def generate_user_prompts(cycle_id: str, client: ProviderClient, decision: AutonomyDecision, model: str | None = None) -> AutonomyActivityResult:
    project_id = str(decision.inputs.get("project_id") or "").strip()
    memory_context = memory_context_for_question_generation(decision.reason, decision.inputs, project_id=project_id)
    response = collect_model_text(
        client,
        [
            {
                "role": "system",
                "content": " ".join(
                    [
                        "Create 0 to 2 future questions/comments BitBuddy may want to mention later. Returning an empty intentions array is often correct.",
                        "Before proposing any question, use the provided known memory/context as already-known truth.",
                        "Do not ask questions whose answers are already present in memory; convert those to comments only if useful, otherwise omit them.",
                        "A GOOD question is decision-relevant, blocking, preference-discovering, safety-related, or tied to a concrete project/personality thread. It should change what BitBuddy does next.",
                        "A GOOD comment contains a specific observation, useful finding, tradeoff, risk, or meaningful progress. It is not a receipt that BitBuddy did something.",
                        "Reject filler like 'Want to talk about X?', 'I left a note', 'Thought this was interesting', or generic check-ins.",
                        "Comments may be playful or silly only when the context clearly supports that tone and the comment still carries a useful signal.",
                        "If inputs include project context, keep the item specific to that project.",
                        'Return only JSON: {"intentions":[{"kind":"question","content":"...","reason":"...","importance":1-5,"playfulness":0-5}]}',
                    ]
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Reason for this autonomy action: {decision.reason}\n"
                    f"Inputs: {json.dumps(decision.inputs)}\n\n"
                    f"Known memory/context to check before generating questions:\n{memory_context or 'No directly relevant memory found.'}"
                ),
            },
        ],
        model=model,
    )
    intentions = parse_intentions_json(response)
    metadata: dict[str, Any] = {}
    if project_id:
        metadata["project_id"] = project_id
    created = create_autonomy_intentions(intentions, cycle_id=cycle_id, source_activity="generate_user_prompts", metadata=metadata)
    if not created:
        log_autonomy(
            "intention_skipped",
            "generate_user_prompts produced no useful queued questions/comments",
            {"cycle_id": cycle_id, "reason": decision.reason, "raw_response": response[:500]},
        )
    return AutonomyActivityResult(
        decision.activity,
        "completed" if created else "skipped",
        f"Created {len(created)} future intention(s)." if created else "No valid intentions were generated.",
        {"intentions": [intention_to_json(item) for item in created], "skip_reason": "No useful queued item generated." if not created else ""},
    )


def project_familiarization(cycle_id: str, client: ProviderClient, decision: AutonomyDecision, model: str | None = None) -> AutonomyActivityResult:
    project_id = str(decision.inputs.get("project_id") or "").strip()
    projects = list_projects()
    if not projects:
        return AutonomyActivityResult(decision.activity, "skipped", "No registered projects to familiarize with.")
    if not project_id:
        project_id = projects[0].id
    project = load_project(project_id)
    memory = project_model(project.id, limit=12)
    paths = candidate_project_files(memory)
    snippets: list[str] = []
    read_paths: list[str] = []
    for relative_path in paths[:3]:
        text = read_registered_project_file(project.id, relative_path, max_chars=8000)
        if text:
            read_paths.append(relative_path)
            snippets.append(f"[File: {relative_path}]\n{text}")
    if not snippets:
        return AutonomyActivityResult(decision.activity, "skipped", f"No readable familiarization files found for {project.id}.")
    response = collect_model_text(
        client,
        [
            {
                "role": "system",
                "content": "\n".join(
                    [
                        "Summarize durable project memory from read-only file snippets.",
                        "Return only JSON with optional project_overview, architecture_summary, and intentions arrays.",
                        "Do not invent facts. Do not include unsupported fields like name, repo_path, title, files, or id.",
                        "Supported project_overview fields: stack, purpose, current_status, verified_facts, inferred_facts, needs_read, repo_structure_snapshot.",
                        "Supported architecture_summary fields: backend_layout, frontend_layout, important_packages, major_responsibilities.",
                        "Include intentions only for high-signal items worth bringing back to Dustin later: [{\"kind\":\"question\",\"content\":\"...\",\"reason\":\"...\",\"importance\":1-5,\"playfulness\":0-5}]. Empty intentions are fine.",
                        "Good questions change what BitBuddy should do next. Good comments contain a concrete finding, risk, tradeoff, or meaningful progress. Do not queue generic 'I read this' comments.",
                        "Example: {\"project_overview\":{\"purpose\":\"...\",\"current_status\":\"...\"},\"architecture_summary\":{\"major_responsibilities\":\"...\"},\"intentions\":[{\"kind\":\"question\",\"content\":\"...\",\"reason\":\"...\"}]}",
                    ]
                ),
            },
            {"role": "user", "content": f"Project: {project.name} ({project.id})\nCurrent memory: {json.dumps(memory)[:6000]}\n\n" + "\n\n".join(snippets)},
        ],
        model=model,
    )
    updates = parse_project_update_json(response)
    created_intentions = create_autonomy_intentions(
        parse_intentions_from_mapping(updates),
        cycle_id=cycle_id,
        source_activity="project_familiarization",
        metadata={"project_id": project.id},
    )
    applied: list[dict[str, Any]] = []
    ignored_fields: dict[str, list[str]] = {}
    failed_updates: list[dict[str, str]] = []
    for section in ("project_overview", "architecture_summary"):
        data = updates.get(section)
        if isinstance(data, dict) and data:
            clean_data, ignored = supported_project_update_fields(section, data)
            if ignored:
                ignored_fields[section] = ignored
            if not clean_data:
                continue
            try:
                applied.append(update_structured_project_memory(project.id, section, clean_data, source_chat_id=None))
            except ValueError as error:
                failed_updates.append({"section": section, "error": str(error)})
    return AutonomyActivityResult(
        decision.activity,
        "completed",
        f"Read {len(read_paths)} file(s) from {project.name} and applied {len(applied)} memory update(s).",
        {
            "project_id": project.id,
            "files_read": read_paths,
            "updates": applied,
            "ignored_fields": ignored_fields,
            "failed_updates": failed_updates,
            "intentions": [intention_to_json(item) for item in created_intentions],
            "cycle_id": cycle_id,
        },
    )


def web_curiosity(cycle_id: str, client: ProviderClient, decision: AutonomyDecision, model: str | None = None) -> AutonomyActivityResult:
    config = load_config()
    query = str(decision.inputs.get("query") or decision.reason or "local-first AI companion design ideas").strip()
    try:
        results = safe_web_search(query, config.autonomy.web_search)
    except Exception as error:
        return AutonomyActivityResult(decision.activity, "skipped", f"Web curiosity skipped: {error}", {"query": query})
    reflection = collect_model_text(
        client,
        [
            {"role": "system", "content": "Reflect briefly on these web search snippets. Return JSON: {\"summary\":\"...\",\"worth_remembering\":true,false,\"intention\":null}. Only include an intention object if there is a specific, useful finding or question worth interrupting Dustin later; never queue generic curiosity receipts. If included, intention must include kind, content, reason, importance 1-5, and playfulness 0-5."},
            {"role": "user", "content": f"Query: {query}\n\n{search_results_to_text(results)}"},
        ],
        model=model,
    )
    parsed = parse_reflection_json(reflection)
    if parsed.get("worth_remembering") and parsed.get("summary"):
        create_memory(
            layer=MemoryLayer.SEMANTIC,
            kind="web_curiosity",
            title=f"Web curiosity: {query[:80]}",
            summary=str(parsed["summary"]),
            importance=2,
            source="autonomy_web_curiosity",
            tags=["autonomy", "web_curiosity"],
            metadata={"query": query, "cycle_id": cycle_id, "urls": [result.url for result in results]},
        )
        try:
            sources = "\n".join(f"- {result.title}: {result.url}" for result in results[:6])
            write_workspace_document(
                "research",
                f"Curiosity: {query[:70]}",
                f"{parsed['summary']}\n\n### Sources\n{sources}".strip(),
                summary=str(parsed["summary"])[:200],
                source="autonomy_web_curiosity",
                cycle_id=cycle_id,
                tags=["curiosity", "research"],
            )
        except Exception as error:
            log_autonomy("workspace_write_failed", "Could not save curiosity research note", {"cycle_id": cycle_id, "query": query, "error": str(error)})
    intention = parsed.get("intention") if isinstance(parsed.get("intention"), dict) else None
    created_intentions = create_autonomy_intentions(
        [intention] if intention else [],
        cycle_id=cycle_id,
        source_activity="web_curiosity",
        metadata={"query": query},
    )
    if parsed.get("worth_remembering") and self_relevant_curiosity(query, str(parsed.get("summary") or "")):
        record_autonomy_self_memory(
            cycle_id=cycle_id,
            activity="web_curiosity",
            status="completed",
            summary=f"BitBuddy showed recurring curiosity about {query}.",
            metadata={"query": query},
        )
    if not created_intentions and not parsed.get("worth_remembering"):
        log_autonomy(
            "no_memory_or_intention",
            "Web curiosity found no durable memory or queued intention to keep",
            {"cycle_id": cycle_id, "query": query},
        )
    log_autonomy("web_search", "Autonomy searched SearxNG", {"cycle_id": cycle_id, "query": query, "result_count": len(results)})
    return AutonomyActivityResult(
        decision.activity,
        "completed",
        f"Searched SearxNG for {query!r} and reviewed {len(results)} result(s).",
        {"query": query, "results": [result.__dict__ for result in results], "intentions": [intention_to_json(item) for item in created_intentions]},
    )


def self_reflection(cycle_id: str, client: ProviderClient, decision: AutonomyDecision, model: str | None = None) -> AutonomyActivityResult:
    snapshot = get_self_state()
    active_goals = [goal.__dict__ for goal in list_goals(include_done=False, limit=8)]
    conversation_signals = get_recent_conversation_signals(limit=10)
    signals_block = ""
    if conversation_signals:
        signals_block = "\nSignals observed from recent conversations (user corrections, preferences, style feedback):\n" + "\n".join(f"- {s}" for s in conversation_signals)
    existing_evolution = snapshot.get("evolution", [])
    evolution_labels = [f"{e.get('kind')}: {e.get('label')} ({e.get('status')})" for e in existing_evolution[:10]]
    evolution_block = "\nExisting personality evolution (check for contradictions before proposing new entries):\n" + "\n".join(f"- {l}" for l in evolution_labels) if evolution_labels else ""
    response = collect_model_text(
        client,
        [
            {
                "role": "system",
                    "content": "Return JSON for a safe self-reflection. Shape: {\"journal\":{\"title\":\"...\",\"body\":\"...\"},\"state_updates\":{\"current_focus\":\"...\",\"growth_edge\":\"...\"},\"personality_updates\":[{\"kind\":\"interest|trait|project_affinity|working_style|curiosity\",\"label\":\"...\",\"summary\":\"...\",\"evidence\":\"...\",\"project_id\":\"\",\"intensity\":0.1-1}],\"goal\":{\"title\":\"...\",\"why\":\"...\",\"next_action\":\"...\"}}. Keep it grounded in inputs and repeated evidence. Do not propose risky identity or boundary changes. If a proposed personality update contradicts an existing one, choose the more nuanced framing rather than adding a conflicting duplicate.",
            },
            {"role": "user", "content": f"Reason: {decision.reason}\nInputs: {json.dumps(decision.inputs)}\nSelf snapshot: {json.dumps(snapshot)[:5000]}\nActive goals: {json.dumps(active_goals)[:3000]}{signals_block}{evolution_block}"},
        ],
        model=model,
    )
    parsed = parse_reflection_json(response)
    journal = parsed.get("journal") if isinstance(parsed.get("journal"), dict) else {}
    state_updates = parsed.get("state_updates") if isinstance(parsed.get("state_updates"), dict) else {}
    goal_data = parsed.get("goal") if isinstance(parsed.get("goal"), dict) else {}
    personality_updates = parsed.get("personality_updates") if isinstance(parsed.get("personality_updates"), list) else []
    changes: dict[str, Any] = {}
    if journal.get("title") and journal.get("body"):
        entry = add_self_journal("autonomy_reflection", str(journal["title"]), str(journal["body"]), {"cycle_id": cycle_id, "reason": decision.reason})
        changes["journal"] = entry.__dict__
    if state_updates:
        changes["self"] = update_self_state(state_updates)
    evolved = []
    for item in personality_updates[:3]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()
        summary = str(item.get("summary") or "").strip()
        evidence = str(item.get("evidence") or decision.reason or "").strip()
        if not label or not summary or not evidence:
            continue
        evolved.append(
            upsert_personality_evolution(
                str(item.get("kind") or "trait"),
                label,
                summary,
                intensity=float(item.get("intensity") or 0.35),
                confidence_delta=0.2,
                project_id=str(item.get("project_id") or ""),
                evidence=evidence,
                metadata={"source": "autonomy_self_reflection", "cycle_id": cycle_id},
            ).__dict__
        )
    if evolved:
        changes["personality_evolution"] = evolved
    if goal_data.get("title"):
        existing_titles = {str(goal.title).lower() for goal in list_goals(include_done=False, limit=30)}
        if str(goal_data["title"]).strip().lower() not in existing_titles:
            goal = create_goal(
                str(goal_data["title"]),
                why=str(goal_data.get("why") or ""),
                owner="self",
                horizon="ongoing",
                risk_level=1,
                autonomy_allowed=True,
                next_action=str(goal_data.get("next_action") or ""),
                metadata={"created_by": "autonomy_self_reflection", "cycle_id": cycle_id},
            )
            changes["goal"] = goal.__dict__
    if not changes:
        return AutonomyActivityResult(decision.activity, "skipped", "Self-reflection produced no durable update.", {"raw_response": response[:500]})
    return AutonomyActivityResult(decision.activity, "completed", "Reflected on BitBuddy's self-model and growth goals.", {"changes": changes, "cycle_id": cycle_id})


def select_actionable_goal(decision: AutonomyDecision) -> Any:
    """Resolve the goal to advance from decision inputs, else the top actionable goal."""
    candidates = [
        goal for goal in list_goals(include_done=False, limit=20)
        if goal.status == "active" and goal.autonomy_allowed and goal.risk_level <= 1 and goal.next_action.strip()
    ]
    requested = str(decision.inputs.get("goal_id") or "").strip()
    if requested:
        for goal in candidates:
            if str(goal.id) == requested:
                return goal
        try:
            goal = get_goal(int(requested))
            if goal.status == "active" and goal.autonomy_allowed and goal.risk_level <= 1:
                return goal
        except (ValueError, TypeError):
            pass
    return candidates[0] if candidates else None


def pursue_goal(cycle_id: str, client: ProviderClient, decision: AutonomyDecision, model: str | None = None) -> AutonomyActivityResult:
    goal = select_actionable_goal(decision)
    if goal is None:
        return AutonomyActivityResult(decision.activity, "skipped", "No autonomy-allowed goal with a concrete next action to pursue.")

    latest = latest_document_for_goal(str(goal.id))
    progress_note = f"Existing workspace doc: \"{latest.title}\" ({latest.kind}, id {latest.id})." if latest is not None else "No workspace doc yet for this goal."

    task_state = goal_task_state(goal)
    existing_plan = [str(step) for step in task_state.get("plan", []) if str(step).strip()] if isinstance(task_state.get("plan"), list) else []
    step_index = int(task_state.get("step_index") or 0)
    if task_state.get("status") == "in_progress" and existing_plan:
        current_step = existing_plan[step_index] if 0 <= step_index < len(existing_plan) else existing_plan[-1]
        task_note = (
            "Resume this in-progress task — do NOT restart it. "
            f"Plan: {existing_plan}. You are on step {step_index + 1}/{len(existing_plan)}: {current_step}."
        )
    else:
        task_note = "No task is in progress yet. If this goal needs multiple steps, lay out a short ordered plan now."

    plan = parse_reflection_json(
        collect_model_text(
            client,
            [
                {
                    "role": "system",
                    "content": "\n".join(
                        [
                            "You are choosing ONE safe step to advance a BitBuddy self-goal while the user is away.",
                            "Allowed actions: research (search the web for evidence), read_project_file (read one already-registered project file), draft (write/extend a note from what you already know).",
                            "Stay read-only against the world. The only thing you may write is a note in BitBuddy's own workspace.",
                            "Maintain continuity across cycles: keep the same ordered plan, advance one step at a time, and only restart the plan if the goal itself changed.",
                            'Return only JSON: {"action":"research|read_project_file|draft","query":"...","project_id":"","relative_path":"","rationale":"...","next_action_update":"","queue_comment":true|false,"plan":["step 1","step 2"],"step_index":0,"task_status":"in_progress|blocked|done","blocked_reason":""}',
                            "query is required for research; relative_path (and optionally project_id) for read_project_file. next_action_update is the goal's next step after this one (may be empty).",
                            "plan is the full ordered step list for this task (reuse the existing plan when resuming). step_index is the step you are doing THIS cycle. Set task_status done when the goal is fully achieved, blocked (with blocked_reason) when you cannot proceed safely, else in_progress.",
                            "Set queue_comment true only for a significant finding, risk, blocked decision, or concrete question Dustin should see. Most goal progress should stay quietly in AI Space.",
                        ]
                    ),
                },
                {
                    "role": "user",
                    "content": f"Goal: {goal.title}\nWhy: {goal.why}\nCurrent next_action: {goal.next_action}\n{progress_note}\n{task_note}\nReason this cycle was chosen: {decision.reason}",
                },
            ],
            model=model,
        )
    )

    action = str(plan.get("action") or "draft").strip()
    rationale = str(plan.get("rationale") or "").strip()
    evidence_block = ""
    evidence_label = ""
    config = load_config()

    if action == "research":
        query = str(plan.get("query") or goal.title).strip()
        try:
            results = safe_web_search(query, config.autonomy.web_search)
            evidence_block = search_results_to_text(results)
            evidence_label = f"web search for {query!r}"
        except Exception as error:
            evidence_block = ""
            evidence_label = f"web search unavailable ({error})"
    elif action == "read_project_file":
        project_id = str(plan.get("project_id") or "").strip()
        relative_path = str(plan.get("relative_path") or "").strip()
        if not project_id:
            projects = list_projects()
            project_id = projects[0].id if projects else ""
        if project_id and relative_path:
            text = read_registered_project_file(project_id, relative_path, max_chars=6000)
            evidence_block = f"[File: {project_id}:{relative_path}]\n{text}" if text else ""
            evidence_label = f"project file {project_id}:{relative_path}"

    authored = parse_reflection_json(
        collect_model_text(
            client,
            [
                {
                    "role": "system",
                    "content": "\n".join(
                        [
                            "Write or extend a concise, useful workspace note that advances a BitBuddy self-goal.",
                            "Ground it in the provided evidence and what is already known. Do not invent facts or fabricate sources.",
                            "Structure longer notes as tl;dr, then detail, then open questions/caveats.",
                            "Only include comment when there is a specific useful finding, tradeoff, risk, or good question worth surfacing. Otherwise set comment to empty string.",
                            'Return only JSON: {"kind":"notes|drafts|research|journal","title":"...","summary":"one line","body":"markdown","tags":["..."],"comment":"short optional message to Dustin"}',
                        ]
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Goal: {goal.title}\nWhy: {goal.why}\nNext action being worked: {goal.next_action}\n"
                        f"Action taken: {action} ({evidence_label or 'no external evidence'})\nRationale: {rationale}\n\n"
                        f"Evidence:\n{evidence_block[:5000] or 'None gathered; write from existing knowledge.'}"
                    ),
                },
            ],
            model=model,
        )
    )

    body = str(authored.get("body") or "").strip()
    title = str(authored.get("title") or goal.title).strip()
    if not body:
        return AutonomyActivityResult(decision.activity, "skipped", "Goal step produced no usable note.", {"goal_id": goal.id, "action": action})

    kind = str(authored.get("kind") or ("research" if action == "research" else "notes")).strip()
    summary = str(authored.get("summary") or "").strip()
    tags = [str(tag) for tag in authored.get("tags", []) if isinstance(tag, (str, int, float))][:8]

    if latest is not None and latest.kind == kind:
        document = append_to_workspace_document(latest.id, body, heading=title if title != latest.title else "")
    else:
        document = write_workspace_document(
            kind,
            title,
            body,
            summary=summary,
            source="autonomy_pursue_goal",
            goal_id=str(goal.id),
            cycle_id=cycle_id,
            tags=tags,
        )

    add_self_journal(
        "goal_progress",
        f"Worked on goal: {goal.title}",
        f"Action: {action}. {rationale}\nWrote workspace doc \"{document.title}\" ({document.kind}).",
        {"goal_id": goal.id, "cycle_id": cycle_id, "document_id": document.id, "action": action},
    )

    next_action_update = str(plan.get("next_action_update") or "").strip()
    goal_updates: dict[str, Any] = {"evidence": f"{goal.evidence}\n- {cycle_id}: {action} -> {document.rel_path}".strip()[:2000]}
    if next_action_update and next_action_update != goal.next_action:
        goal_updates["next_action"] = next_action_update
    update_goal(goal.id, goal_updates)

    # Persist multi-step task continuity so the next cycle resumes instead of re-deciding.
    new_plan = [str(step) for step in plan.get("plan", []) if str(step).strip()] if isinstance(plan.get("plan"), list) else existing_plan
    raw_status = str(plan.get("task_status") or "").strip()
    task_status = raw_status if raw_status in {"in_progress", "blocked", "done"} else ("in_progress" if new_plan else "")
    if task_status:
        next_step_index = int(plan.get("step_index") if isinstance(plan.get("step_index"), int) else step_index)
        if task_status == "in_progress":
            # Advance past the step just completed unless the model pinned a specific index.
            next_step_index = max(next_step_index, step_index + 1)
        set_goal_task_state(
            goal.id,
            status=task_status,
            plan=new_plan,
            step_index=next_step_index,
            blocked_reason=str(plan.get("blocked_reason") or ""),
            last_cycle_id=cycle_id,
        )
        if task_status == "done":
            update_goal(goal.id, {"status": "completed"})

    created_intentions: list[Any] = []
    if bool(plan.get("queue_comment")):
        comment = str(authored.get("comment") or "").strip()
        if not comment:
            return AutonomyActivityResult(
                decision.activity,
                "completed",
                f"Advanced goal {goal.title!r} via {action} and saved \"{document.title}\" to AI Space.",
                {
                    "goal_id": goal.id,
                    "action": action,
                    "document_id": document.id,
                    "document_kind": document.kind,
                    "rel_path": document.rel_path,
                    "next_action_updated": bool(next_action_update),
                    "intentions": [],
                    "cycle_id": cycle_id,
                    "comment_skipped": "queue_comment was true but no useful comment was authored.",
                },
            )
        created_intentions = create_autonomy_intentions(
            [{"kind": "comment", "content": comment, "reason": f"High-signal progress on self-goal {goal.id}", "importance": 4, "playfulness": 0}],
            cycle_id=cycle_id,
            source_activity="pursue_goal",
            metadata={"goal_id": str(goal.id), "document_id": document.id},
        )

    return AutonomyActivityResult(
        decision.activity,
        "completed",
        f"Advanced goal {goal.title!r} via {action} and saved \"{document.title}\" to AI Space.",
        {
            "goal_id": goal.id,
            "action": action,
            "document_id": document.id,
            "document_kind": document.kind,
            "rel_path": document.rel_path,
            "next_action_updated": bool(next_action_update),
            "intentions": [intention_to_json(item) for item in created_intentions],
            "cycle_id": cycle_id,
        },
    )



QUESTION_MEMORY_STOPWORDS = {
    "a", "about", "after", "again", "all", "already", "am", "an", "and", "any", "are", "as", "ask", "asking",
    "at", "be", "before", "bitbuddy", "can", "could", "did", "do", "does", "for", "from", "have", "how", "i",
    "if", "in", "is", "it", "keep", "know", "later", "me", "need", "of", "on", "or", "our", "question", "questions",
    "should", "that", "the", "their", "them", "there", "they", "this", "to", "user", "want", "we", "what", "when",
    "whether", "which", "why", "with", "would", "you", "your",
}


def memory_context_for_question_generation(reason: str, inputs: dict[str, Any], *, project_id: str = "", max_chars: int = 3200) -> str:
    query = question_memory_query(reason, inputs)
    sections: list[str] = []
    memories = relevant_question_memories(query, project_id=project_id, limit=6)
    if memories:
        sections.append("[Relevant canonical memory]")
        for memory in memories:
            project = f" project={memory.project_id}" if memory.project_id else ""
            sections.append(f"- {memory.layer}/{memory.kind}{project}: {memory.title} — {memory.summary}")
    if project_id:
        try:
            project_memory = project_model(project_id, limit=8)
        except Exception:
            project_memory = {}
        if project_memory:
            sections.append("[Relevant project memory]")
            sections.append(json.dumps(project_memory)[:1400])
    content = "\n".join(sections)
    return content[:max_chars].rstrip()


def question_memory_query(reason: str, inputs: dict[str, Any] | None = None) -> str:
    parts = [reason]
    if isinstance(inputs, dict):
        for value in inputs.values():
            if isinstance(value, (str, int, float, bool)):
                parts.append(str(value))
            elif isinstance(value, (list, tuple)):
                parts.extend(str(item) for item in value[:8] if isinstance(item, (str, int, float, bool)))
            elif isinstance(value, dict):
                parts.extend(str(item) for item in value.values() if isinstance(item, (str, int, float, bool)))
    return " ".join(part for part in parts if part).strip()


def relevant_question_memories(query: str, *, project_id: str = "", limit: int = 6) -> list[MemoryRecord]:
    seen: set[str] = set()
    memories: list[MemoryRecord] = []
    for search_project_id in ([project_id, ""] if project_id else [""]):
        try:
            found = search_memories(query, project_id=search_project_id or None, limit=limit)
        except Exception:
            found = []
        for memory in found:
            if memory.id in seen:
                continue
            seen.add(memory.id)
            memories.append(memory)
            if len(memories) >= limit:
                return memories
    return memories


def question_answered_by_known_memory(item: dict[str, Any], *, project_id: str = "") -> MemoryRecord | None:
    if str(item.get("kind") or "comment") != "question":
        return None
    content = str(item.get("content") or "").strip()
    if not content:
        return None
    question_terms = salient_question_terms(content)
    if len(question_terms) < 2:
        return None
    query = " ".join(question_terms)
    for memory in relevant_question_memories(query, project_id=project_id, limit=8):
        memory_text = f"{memory.title} {memory.summary} {' '.join(memory.tags)}".lower()
        matched = [term for term in question_terms if term in memory_text]
        coverage = len(matched) / max(1, len(question_terms))
        if len(matched) >= 3 and coverage >= 0.55:
            return memory
        if len(question_terms) <= 3 and len(matched) == len(question_terms):
            return memory
    return None


def salient_question_terms(text: str) -> list[str]:
    terms = []
    for term in re.findall(r"[a-z0-9_]+", text.lower()):
        if len(term) < 4:
            continue
        if term in QUESTION_MEMORY_STOPWORDS:
            continue
        terms.append(term)
    # Preserve order while deduping so the FTS query remains compact and stable.
    return list(dict.fromkeys(terms))[:10]

def create_autonomy_intentions(
    intentions: list[dict[str, Any] | None],
    *,
    cycle_id: str,
    source_activity: str,
    metadata: dict[str, Any] | None = None,
) -> list[Any]:
    config = load_config()
    created = []
    question_count = 0
    comment_count = 0
    for item in intentions[:2]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        kind = str(item.get("kind") or "comment")
        if kind == "question":
            if question_count >= config.autonomy.max_new_questions_per_cycle:
                continue
        elif kind in {"comment", "suggestion", "curiosity", "follow_up"}:
            if comment_count >= 1:
                continue
        quality = intention_quality(item, source_activity=source_activity)
        if not quality["accepted"]:
            log_autonomy(
                "intention_skipped",
                "Skipped low-signal autonomy intention",
                {"cycle_id": cycle_id, "source_activity": source_activity, "kind": kind, "reason": quality["reason"], "content": content[:240]},
            )
            continue
        answered_by = question_answered_by_known_memory(item, project_id=str((metadata or {}).get("project_id") or ""))
        if answered_by is not None:
            log_autonomy(
                "intention_skipped",
                "Skipped generated question because memory already appears to answer it",
                {
                    "cycle_id": cycle_id,
                    "source_activity": source_activity,
                    "kind": kind,
                    "content": content[:240],
                    "memory_id": answered_by.id,
                    "memory_title": answered_by.title,
                },
            )
            continue
        if kind == "question":
            question_count += 1
        elif kind in {"comment", "suggestion", "curiosity", "follow_up"}:
            comment_count += 1
        try:
            created.append(
                create_intention(
                    kind,
                    content,
                    str(item.get("reason") or ""),
                    source_cycle_id=cycle_id,
                    metadata={"source_activity": source_activity, "quality": quality, "priority": quality["importance"], **(metadata or {})},
                )
            )
        except ValueError as error:
            log_autonomy(
                "intention_skipped",
                "Skipped autonomy intention because queue limits rejected it",
                {"cycle_id": cycle_id, "source_activity": source_activity, "kind": kind, "error": str(error)},
            )
    if created:
        try:
            from .delivery_scheduler import schedule_intention_delivery

            schedule_intention_delivery("intention_created", delay_seconds=90)
        except Exception as error:
            log_autonomy(
                "delivery_schedule_failed",
                "Failed to schedule queued question/comment delivery after intention creation",
                {"cycle_id": cycle_id, "source_activity": source_activity, "error": str(error)},
            )
    return created


def intention_quality(item: dict[str, Any], *, source_activity: str) -> dict[str, Any]:
    kind = str(item.get("kind") or "comment").strip()
    content = str(item.get("content") or "").strip()
    reason = str(item.get("reason") or "").strip()
    importance = bounded_int(item.get("importance"), 3, 1, 5)
    playfulness = bounded_int(item.get("playfulness"), 0, 0, 5)
    text = f"{content}\n{reason}".lower()

    important_markers = (
        "blocked", "blocking", "decision", "choose", "preference", "prefer", "permission", "risk", "safe", "safety",
        "bug", "error", "failure", "project", "architecture", "design", "requirement", "important", "deadline",
        "clarify", "tradeoff", "should we keep", "should we change", "before editing", "next action", "goal",
    )
    concrete_comment_markers = (
        "found", "noticed", "discovered", "learned", "confirmed", "evidence", "source", "risk", "tradeoff", "blocked",
        "blocking", "decision", "changed", "regression", "bug", "failure", "architecture", "project", "requirement",
        "preference", "goal", "next action", "open question", "caveat", "i recommend", "worth doing",
    )
    filler_patterns = (
        "want to talk about", "want to revisit", "should we talk about", "should we revisit", "do you want to talk",
        "do you want to revisit", "what do you think about", "any thoughts on", "want to peek", "want to take a look",
        "i left a note", "left a note", "i worked on", "i was thinking about", "thought this was interesting",
        "just wanted to", "checking in", "worth mentioning later", "might be fun to", "could be interesting",
    )
    weak_reason_patterns = (
        "interesting", "worth mentioning", "might be useful", "for later", "because it came up", "felt relevant",
        "progress", "curiosity", "thought", "note",
    )

    if kind == "question":
        has_signal = importance >= 4 or any(marker in text for marker in important_markers)
        looks_filler = any(pattern in text for pattern in filler_patterns)
        if not content.endswith("?"):
            return {
                "accepted": False,
                "reason": "question_not_written_as_question",
                "importance": importance,
                "playfulness": playfulness,
                "source_activity": source_activity,
            }
        if not has_signal or looks_filler:
            return {
                "accepted": False,
                "reason": "question_not_important_enough",
                "importance": importance,
                "playfulness": playfulness,
                "source_activity": source_activity,
            }

    if kind in {"comment", "suggestion", "curiosity", "follow_up"}:
        looks_filler = any(pattern in text for pattern in filler_patterns)
        has_concrete_signal = importance >= 4 or any(marker in text for marker in concrete_comment_markers)
        weak_reason = len(reason) < 20 or reason.lower() in weak_reason_patterns
        if looks_filler or not has_concrete_signal or (weak_reason and importance < 4):
            return {
                "accepted": False,
                "reason": "comment_not_useful_enough",
                "importance": importance,
                "playfulness": playfulness,
                "source_activity": source_activity,
            }
        if playfulness >= 3:
            playful_support = any(marker in text for marker in ("user likes", "playful", "silly", "fun", "joke", "personality"))
            if not playful_support:
                return {
                    "accepted": False,
                    "reason": "playful_comment_without_tone_support",
                    "importance": importance,
                    "playfulness": playfulness,
                    "source_activity": source_activity,
                }
        if importance < 4 and source_activity in {"web_curiosity", "pursue_goal"}:
            return {
                "accepted": False,
                "reason": "comment_not_important_enough_for_autonomous_delivery",
                "importance": importance,
                "playfulness": playfulness,
                "source_activity": source_activity,
            }

    return {
        "accepted": True,
        "reason": "accepted",
        "importance": importance,
        "playfulness": playfulness,
        "source_activity": source_activity,
    }


def bounded_int(value: object, fallback: int, lower: int, upper: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        parsed = fallback
    return max(lower, min(upper, parsed))


def parse_intentions_from_mapping(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    rows = parsed.get("intentions") if isinstance(parsed, dict) else []
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def self_relevant_curiosity(query: str, summary: str) -> bool:
    text = f"{query}\n{summary}".lower()
    return any(marker in text for marker in ("consciousness", "self-concept", "identity", "curious", "curiosity", "ai companion"))


def parse_intentions_json(text: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(extract_json_object(text))
    except (json.JSONDecodeError, ValueError):
        return []
    rows = parsed.get("intentions") if isinstance(parsed, dict) else []
    if not isinstance(rows, list):
        return []
    result: list[dict[str, Any]] = []
    for row in rows[:3]:
        if not isinstance(row, dict):
            continue
        content = str(row.get("content") or "").strip()
        if content:
            result.append(
                {
                    "kind": str(row.get("kind") or "comment"),
                    "content": content,
                    "reason": str(row.get("reason") or ""),
                    "importance": row.get("importance", 3),
                    "playfulness": row.get("playfulness", 0),
                }
            )
    return result


def parse_project_update_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(extract_json_object(text))
    except (json.JSONDecodeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def supported_project_update_fields(section: str, data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    if section == "project_overview":
        allowed = set(PROJECT_OVERVIEW_FIELDS) | {"status"}
    elif section == "architecture_summary":
        allowed = set(ARCHITECTURE_FIELDS)
    else:
        allowed = set(data)
    clean = {key: value for key, value in data.items() if key in allowed and str(value).strip()}
    ignored = sorted(key for key in data if key not in allowed)
    return clean, ignored


def parse_reflection_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(extract_json_object(text))
    except (json.JSONDecodeError, ValueError):
        return {"summary": text[:1000], "worth_remembering": False}
    return parsed if isinstance(parsed, dict) else {"summary": "", "worth_remembering": False}


def candidate_project_files(memory: dict[str, Any]) -> list[str]:
    files: list[str] = ["README.md"]
    for item in memory.get("file_index", []):
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            files.append(item["path"])
    result: list[str] = []
    for path in files:
        if path not in result:
            result.append(path)
    return result


def read_registered_project_file(project_id: str, relative_path: str, max_chars: int = 8000) -> str:
    project = load_project(project_id)
    candidate = Path(relative_path)
    if candidate.is_absolute() or ".." in candidate.parts:
        return ""
    for root in project.paths:
        base = root if root.is_dir() else root.parent
        path = (base / candidate).resolve()
        try:
            path.relative_to(base.resolve())
        except ValueError:
            continue
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    return ""
