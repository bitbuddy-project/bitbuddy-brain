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
from ..self_model import add_self_journal, create_goal, get_recent_conversation_signals, get_self_state, list_goals, update_self_state, upsert_personality_evolution
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
                        "Create 1 to 3 future questions/comments BitBuddy may want to mention later.",
                        "Before proposing any question, use the provided known memory/context as already-known truth.",
                        "Do not ask questions whose answers are already present in memory; convert those to comments only if useful, otherwise omit them.",
                        "Questions must be important: decision-relevant, blocking, preference-discovering, safety-related, or tied to a concrete project/personality thread.",
                        "Reject filler like 'Want to talk about X?' unless the reason explains why it matters now.",
                        "Comments may be playful or silly only when the context clearly supports that tone.",
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
                        "If you discover a useful question/comment to bring back to Dustin later, include intentions: [{\"kind\":\"question\",\"content\":\"...\",\"reason\":\"...\",\"importance\":1-5,\"playfulness\":0-5}].",
                        "Questions must be important, specific, and worth interrupting later; comments can be playful only when context supports that tone.",
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
            {"role": "system", "content": "Reflect briefly on these web search snippets. Return JSON: {\"summary\":\"...\",\"worth_remembering\":true,false,\"intention\":{\"kind\":\"comment\",\"content\":\"...\",\"reason\":\"...\"}}"},
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
    for item in intentions[:3]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        kind = str(item.get("kind") or "comment")
        if kind == "question":
            if question_count >= config.autonomy.max_new_questions_per_cycle:
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
        try:
            created.append(
                create_intention(
                    kind,
                    content,
                    str(item.get("reason") or ""),
                    source_cycle_id=cycle_id,
                    metadata={"source_activity": source_activity, "quality": quality, **(metadata or {})},
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
        "clarify", "tradeoff", "should we keep", "should we change", "before editing",
    )
    filler_patterns = (
        "want to talk about", "want to revisit", "should we talk about", "should we revisit", "do you want to talk",
        "do you want to revisit", "what do you think about", "any thoughts on",
    )

    if kind == "question":
        has_signal = importance >= 4 or any(marker in text for marker in important_markers)
        looks_filler = any(pattern in text for pattern in filler_patterns)
        if not has_signal or (looks_filler and importance < 4):
            return {
                "accepted": False,
                "reason": "question_not_important_enough",
                "importance": importance,
                "playfulness": playfulness,
                "source_activity": source_activity,
            }

    if kind in {"comment", "suggestion", "curiosity", "follow_up"} and playfulness >= 3:
        playful_support = any(marker in text for marker in ("user likes", "playful", "silly", "fun", "joke", "personality"))
        if not playful_support:
            return {
                "accepted": False,
                "reason": "playful_comment_without_tone_support",
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


def parse_intentions_json(text: str) -> list[dict[str, str]]:
    try:
        parsed = json.loads(extract_json_object(text))
    except (json.JSONDecodeError, ValueError):
        return []
    rows = parsed.get("intentions") if isinstance(parsed, dict) else []
    if not isinstance(rows, list):
        return []
    result: list[dict[str, str]] = []
    for row in rows[:3]:
        if not isinstance(row, dict):
            continue
        content = str(row.get("content") or "").strip()
        if content:
            result.append({"kind": str(row.get("kind") or "comment"), "content": content, "reason": str(row.get("reason") or "")})
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
