from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from ..librarian import ProjectCard, build_card_from_project, get_relevant_whisper
from ..memory.project import Project, list_projects, project_has_completed_scan, project_model


PROJECT_KEYWORDS = {
    "api",
    "backend",
    "branch",
    "bug",
    "build",
    "class",
    "cli",
    "code",
    "coding",
    "commit",
    "component",
    "database",
    "debug",
    "error",
    "feature",
    "file",
    "files",
    "fix",
    "frontend",
    "function",
    "implement",
    "memory",
    "module",
    "project",
    "pr",
    "pull",
    "refactor",
    "repo",
    "repository",
    "route",
    "server",
    "source",
    "sqlite",
    "test",
    "tests",
    "work",
    "workspace",
}
PROJECT_DESIGN_TERMS = {
    "album",
    "albums",
    "app",
    "apps",
    "backend",
    "component",
    "database",
    "feature",
    "folder",
    "folders",
    "frontend",
    "gallery",
    "image",
    "images",
    "model",
    "notes",
    "route",
    "system",
}
DEEP_PROJECT_TERMS = {
    "architecture",
    "architectural",
    "autonomy",
    "behavior",
    "bug",
    "bugs",
    "code",
    "context",
    "decision",
    "decisions",
    "deep",
    "design",
    "direction",
    "edit",
    "feature",
    "fix",
    "implementation",
    "implement",
    "issue",
    "memory",
    "permissions",
    "provider",
    "refactor",
    "retrieval",
    "roadmap",
    "routing",
    "runtime",
    "scaling",
    "sqlite",
    "structure",
    "system",
    "tradeoff",
    "tool",
    "tools",
}
FILE_OR_CODE_TERMS = {
    "code",
    "edit",
    "file",
    "files",
    "function",
    "implementation",
    "line",
    "module",
    "readme",
    "source",
}
DEEP_PROJECT_PATTERNS = (
    r"\bhow\s+(?:should|would|could|do|does|can)\b",
    r"\bwhat\s+(?:should|would|could|do|does|is|are)\b",
    r"\bwhy\s+(?:does|is|are|would|should|can't|can)\b",
    r"\b(?:best|better|right|wrong|works|scale|scales|scaling)\b",
    r"\b(?:think|recommend|guidance|professional|deep|architecture|design|implementation|tradeoff)\b",
    r"\b(?:current|currently|existing|already|before|decided|direction|plan)\b",
)
IMPLEMENTATION_ESTIMATE_PATTERNS = (
    r"\bhow hard would it be\b",
    r"\bhow hard is it\b",
    r"\bhow difficult would it be\b",
    r"\bhow much work\b",
    r"\bwhat would it take\b",
    r"\bwhat would need to change\b",
    r"\bhow big of a change\b",
    r"\bhow easy would it be\b",
    r"\bcan we add\b",
    r"\bcould we add\b",
    r"\badd\b.+\bto\b",
)
FEATURE_COMPARISON_PATTERNS = (
    r"\blike the\b.+\bapp\b",
    r"\blike image gallery\b",
    r"\bsimilar to\b",
    r"\bsame as\b",
)

OMITTED_RESERVE = 500
TRUNCATED_SUFFIX = "\n\n[Omitted: context pack truncated to budget]"


@dataclass(frozen=True)
class ProjectContextDecision:
    project: Project
    depth: str
    required: bool
    reason: str


@dataclass
class ProjectContextPack:
    max_chars: int
    parts: list[str] = field(default_factory=list)
    omitted: list[str] = field(default_factory=list)

    @property
    def soft_limit(self) -> int:
        if self.max_chars <= OMITTED_RESERVE * 2:
            return max(0, self.max_chars - 120)
        return self.max_chars - OMITTED_RESERVE

    def add_preamble(self, mode: str) -> None:
        self.parts.extend(
            [
                "[Project Context Pack — runtime-selected project memory]",
                "The runtime selected this project context before the model response. Treat loaded project memory as critical orientation, not optional hints.",
                "For deep project questions, use the loaded project memory before answering. If memory is missing or shallow, say so instead of guessing.",
                "For exact source behavior or code edits, read the actual files first; project memory is orientation, not line-level proof.",
                f"Mode: {mode or 'chat'}",
            ]
        )

    def add_section(self, title: str, lines: list[str], item_limit: int | None = None) -> None:
        clean_lines = [line for line in lines if line.strip()]
        if not clean_lines:
            return

        if item_limit is not None and len(clean_lines) > item_limit:
            skipped = len(clean_lines) - item_limit
            clean_lines = clean_lines[:item_limit]
            self.omitted.append(f"{title}: {skipped} item(s) omitted by section cap")

        section_lines = [f"\n## {title}", *clean_lines]
        added_any = False
        for line in section_lines:
            if self._fits(line):
                self.parts.append(line)
                added_any = True
                continue
            if line.startswith("\n## "):
                self.omitted.append(f"{title}: section omitted due to budget")
                return
            self.omitted.append(f"{title}: additional item(s) omitted due to budget")
            return

        if not added_any:
            self.omitted.append(f"{title}: section omitted due to budget")

    def render(self) -> str:
        text = "\n".join(self.parts)
        if self.omitted:
            omitted_lines = ["\n## Omitted due to budget", *[f"- {item}" for item in self.omitted[:20]]]
            if len(self.omitted) > 20:
                omitted_lines.append(f"- omitted list truncated: {len(self.omitted) - 20} more item(s)")
            text = "\n".join([text, *omitted_lines])
        return hard_cap(text, self.max_chars)

    def _fits(self, line: str) -> bool:
        current = "\n".join(self.parts)
        candidate = line if not current else f"{current}\n{line}"
        return len(candidate) <= self.soft_limit


def build_project_context_pack(
    messages: list[dict[str, str]],
    mode: str,
    max_chars: int = 12000,
) -> str | None:
    latest_user_text = latest_user_message(messages)
    user_text = recent_user_text(messages)
    projects = list_projects()
    if not projects:
        return None

    normalized_text = normalize(user_text)
    explicit_projects = detect_explicit_projects(projects, normalized_text)
    relevant_cards = get_relevant_whisper(user_text, max_cards=3, min_score=1.5)

    if not (
        explicit_projects
        or relevant_cards
        or contains_project_design_intent(normalized_text)
        or contains_project_keyword(normalized_text)
    ):
        return None

    depth = classify_project_context_depth(normalized_text, mode)
    decisions = project_context_decisions(
        projects=projects,
        explicit_projects=explicit_projects,
        relevant_cards=relevant_cards,
        depth=depth,
        normalized_text=normalized_text,
    )

    pack = ProjectContextPack(max_chars=max_chars)
    pack.add_preamble(mode)
    pack.add_section("Registered projects", registry_lines(projects), item_limit=20)

    routing_lines = routing_status_lines(
        latest_user_text=latest_user_text,
        decisions=decisions,
        has_explicit_projects=bool(explicit_projects),
        has_relevant_cards=bool(relevant_cards),
        depth=depth,
    )
    pack.add_section("Runtime project routing status", routing_lines)

    if decisions:
        for decision in decisions[:3]:
            add_project_memory_sections(pack, decision)
    elif relevant_cards:
        pack.add_section(
            "Possible project matches",
            possible_match_lines(relevant_cards),
            item_limit=8,
        )
    elif contains_project_keyword(normalized_text) or contains_project_design_intent(normalized_text):
        pack.add_section(
            "Project memory policy",
            [
                "- Project-like language was detected, but no registered project was confidently resolved.",
                "- Do not pretend project-specific memory was loaded.",
                "- If the user asks a deep project-specific question, ask which project or use the registered-project list to resolve it first.",
            ],
        )

    return pack.render()


def latest_user_message(messages: list[dict[str, str]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            return message.get("content", "")
    return ""


def recent_user_text(messages: list[dict[str, str]], limit: int = 6) -> str:
    user_messages = [message.get("content", "") for message in messages if message.get("role") == "user"]
    return " ".join(user_messages[-limit:])


def project_context_decisions(
    *,
    projects: list[Project],
    explicit_projects: list[Project],
    relevant_cards: list[ProjectCard],
    depth: str,
    normalized_text: str,
) -> list[ProjectContextDecision]:
    decisions: list[ProjectContextDecision] = []
    seen: set[str] = set()
    deep = depth in {"memory", "deep", "files"}

    for project in explicit_projects:
        if project.id in seen:
            continue
        seen.add(project.id)
        decisions.append(
            ProjectContextDecision(
                project=project,
                depth=depth,
                required=deep,
                reason="explicit project mention" + (" + deep/project-specific question" if deep else ""),
            )
        )

    # If no explicit project was named, use librarian matches as a lighter routing
    # signal.  These are useful for continuity, but should not be treated with the
    # same confidence as an explicit name/id mention.
    if not decisions:
        project_by_id = {project.id: project for project in projects}
        for card in relevant_cards[:2]:
            project = project_by_id.get(card.project_id)
            if project is None or project.id in seen:
                continue
            seen.add(project.id)
            card_depth = "card" if not deep else "memory"
            decisions.append(
                ProjectContextDecision(
                    project=project,
                    depth=card_depth,
                    required=False,
                    reason="librarian relevance match; lower confidence than explicit mention",
                )
            )

    if not decisions and contains_project_design_intent(normalized_text):
        # Keep this as policy-only.  Loading a random project for generic product
        # design questions creates cross-project contamination.
        return []

    return decisions


def classify_project_context_depth(normalized_text: str, mode: str) -> str:
    tokens = set(re.findall(r"\b[a-z][a-z0-9_-]{2,}\b", normalized_text))

    if mode in {"debug", "plan"}:
        return "files"

    if tokens & FILE_OR_CODE_TERMS and any(
        re.search(pattern, normalized_text)
        for pattern in (
            r"\b(?:read|open|inspect|review|edit|change|patch|fix|debug|implement|refactor)\b",
            r"\b(?:source|file|files|module|function|class|line|code)\b",
        )
    ):
        return "files"

    if contains_deep_project_question(normalized_text):
        return "memory"

    return "card"


def contains_deep_project_question(normalized_text: str) -> bool:
    if not normalized_text:
        return False

    tokens = set(re.findall(r"\b[a-z][a-z0-9_-]{2,}\b", normalized_text))
    has_deep_term = bool(tokens & DEEP_PROJECT_TERMS)
    has_deep_pattern = any(re.search(pattern, normalized_text) for pattern in DEEP_PROJECT_PATTERNS)
    has_estimate = any(re.search(pattern, normalized_text) for pattern in IMPLEMENTATION_ESTIMATE_PATTERNS)

    return has_deep_term and (has_deep_pattern or has_estimate or "?" in normalized_text)


def routing_status_lines(
    *,
    latest_user_text: str,
    decisions: list[ProjectContextDecision],
    has_explicit_projects: bool,
    has_relevant_cards: bool,
    depth: str,
) -> list[str]:
    lines = [
        f"- Latest user message: {truncate(clean_value(latest_user_text), 240)}",
        f"- Requested context depth: {depth}",
        f"- Explicit project mention detected: {'yes' if has_explicit_projects else 'no'}",
        f"- Librarian project-card match detected: {'yes' if has_relevant_cards else 'no'}",
    ]

    if decisions:
        for decision in decisions[:3]:
            lines.append(
                f"- Selected project: {decision.project.name} [{decision.project.id}] | depth={decision.depth} | memory_required={'yes' if decision.required else 'no'} | reason={decision.reason}"
            )
    else:
        lines.append("- Selected project: none")

    return lines


def add_project_memory_sections(pack: ProjectContextPack, decision: ProjectContextDecision) -> None:
    project = decision.project
    path = project.paths[0] if project.paths else "unknown"
    scanned = project_has_completed_scan(project.id)
    card = build_card_from_project(project.id) if scanned else None

    pack.add_section(
        f"Project memory status — {project.name}",
        [
            f"- Project ID: {project.id}",
            f"- Path: {path}",
            f"- Completed project scan: {'yes' if scanned else 'no'}",
            f"- Runtime-selected depth: {decision.depth}",
            f"- Project memory required before deep answer: {'yes' if decision.required else 'no'}",
            f"- Selection reason: {decision.reason}",
        ],
    )

    if not scanned:
        pack.add_section(
            f"Missing project memory — {project.name}",
            [
                "- Only the registered project entry is available right now; no completed scan/dossier exists.",
                "- For deep project questions, tell the user this memory is missing instead of answering as if project details were loaded.",
                "- If tools are available, use project tools to scan/read specific files before exact claims.",
            ],
        )
        return

    if decision.depth == "card":
        if card is not None:
            pack.add_section(f"Project card — {project.name}", compact_card_lines(card), item_limit=14)
        else:
            add_project_model_sections(pack, project, card=None, depth="card")
        return

    add_project_model_sections(pack, project, card=card, depth=decision.depth)


def add_project_model_sections(
    pack: ProjectContextPack,
    project: Project,
    card: ProjectCard | None,
    depth: str,
) -> None:
    try:
        limit = 160 if depth == "deep" else 100 if depth == "files" else 80
        model = project_model(project.id, limit=limit)
    except Exception as error:
        pack.add_section(
            f"Project memory load failed — {project.name}",
            [
                f"- Could not load project_model for {project.name} [{project.id}].",
                f"- Error: {error}",
                "- Do not make project-specific claims from missing memory.",
            ],
        )
        return

    project_card = as_dict(model.get("project_card"))
    architecture = as_dict(model.get("architecture_summary"))

    pack.add_section(f"Verified facts/status — {project.name}", verified_fact_lines(project_card), item_limit=10)
    pack.add_section(f"Inferences/purpose — {project.name}", inference_lines(project_card), item_limit=6)
    pack.add_section(f"Architecture summary — {project.name}", architecture_lines(architecture), item_limit=8)
    pack.add_section(f"Current task memory — {project.name}", task_lines(model), item_limit=8)
    pack.add_section(f"Decisions/preferences — {project.name}", decision_lines(model), item_limit=12)
    pack.add_section(f"Project notes — {project.name}", project_note_lines(model), item_limit=12)
    pack.add_section(f"Important behavior — {project.name}", behavior_lines(project_card, card), item_limit=10)
    pack.add_section(f"Read-before-editing rules — {project.name}", read_rule_lines(model), item_limit=10)
    pack.add_section(f"Important files — {project.name}", file_lines(model), item_limit=16)

    if card is not None and depth in {"files", "deep"}:
        pack.add_section(f"Librarian file refs — {project.name}", file_ref_lines(card), item_limit=12)

    pack.add_section(
        f"Retrieval policy — {project.name}",
        [
            f"- {clean_value(model.get('retrieval_policy'))}",
            "- This project memory has already been checked by the runtime for this turn.",
            "- If the user asks for exact code behavior, call read_file on the relevant files before claiming line-level details.",
        ],
    )


def registry_lines(projects: list[Project]) -> list[str]:
    lines = ["Available projects for BitBuddy routing/tools:"]
    for project in projects:
        path = project.paths[0] if project.paths else "unknown"
        lines.append(f"- Name: {project.name} | ID: {project.id} | Path: {path}")
    return lines


def detect_explicit_projects(projects: list[Project], normalized_text: str) -> list[Project]:
    if not normalized_text:
        return []

    text_tokens = set(re.split(r"[^a-z0-9]+", normalized_text))

    matches: list[Project] = []
    for project in projects:
        project_id_norm = re.sub(r"[^a-z0-9]+", " ", project.id.lower()).strip()
        project_name_norm = re.sub(r"[^a-z0-9]+", " ", project.name.lower()).strip()
        project_tokens = set(project_id_norm.split()) | set(project_name_norm.split())

        # Exact name/id mentions are strongest and avoid accidental routing for
        # generic one-word project terms.
        if project_name_norm and re.search(rf"(?:^|\s){re.escape(project_name_norm)}(?:\s|$)", normalized_text):
            matches.append(project)
            continue
        if project_id_norm and re.search(rf"(?:^|\s){re.escape(project_id_norm)}(?:\s|$)", normalized_text):
            matches.append(project)
            continue

        # Fallback for slug/id fragments.  Require a meaningful token length to
        # keep a project named with a generic term from stealing context.
        significant_tokens = {token for token in project_tokens if len(token) >= 4}
        if significant_tokens and any(token in text_tokens for token in significant_tokens):
            matches.append(project)

    return matches


def contains_project_keyword(normalized_text: str) -> bool:
    tokens = set(re.findall(r"\b[a-z][a-z0-9_-]{2,}\b", normalized_text))
    return bool(tokens & PROJECT_KEYWORDS)


def contains_project_design_intent(normalized_text: str) -> bool:
    if not normalized_text:
        return False
    tokens = set(re.findall(r"\b[a-z][a-z0-9_-]{2,}\b", normalized_text))
    design_target = bool(tokens & PROJECT_DESIGN_TERMS) or any(
        phrase in normalized_text
        for phrase in (
            "folder system",
            "notes app",
            "gallery app",
            "image gallery",
        )
    )
    if not design_target:
        return False
    estimate_intent = any(re.search(pattern, normalized_text) for pattern in IMPLEMENTATION_ESTIMATE_PATTERNS)
    comparison_intent = any(re.search(pattern, normalized_text) for pattern in FEATURE_COMPARISON_PATTERNS)
    return estimate_intent or comparison_intent


def possible_match_lines(cards: list[ProjectCard]) -> list[str]:
    lines = [
        "- No explicit project name/id was detected, but librarian search found possible project matches.",
        "- Treat these as low-confidence orientation only; do not answer as if project memory was definitely loaded.",
    ]
    for card in cards:
        facts = "; ".join(card.verified_facts[:2]) if card.verified_facts else "no compact facts"
        lines.append(f"- {card.project_name} [{card.project_id}]: {truncate(facts, 220)}")
    return lines


def compact_card_lines(card: ProjectCard) -> list[str]:
    lines = [f"- Project: {card.project_name} [{card.project_id}]", f"- Card updated at: {card.updated_at or 'unknown'}"]
    lines.extend(f"- Fact: {truncate(item, 220)}" for item in card.verified_facts[:5])
    lines.extend(f"- Inference: {truncate(item, 220)}" for item in card.inferences[:3])
    lines.extend(f"- Recent decision: {truncate(item, 220)}" for item in card.recent_decisions[:4])
    lines.extend(f"- Important behavior: {truncate(item, 220)}" for item in card.important_behavior[:4])
    if card.important_files:
        lines.append("- Key files: " + ", ".join(f"`{file_ref.path}`" for file_ref in card.important_files[:6]))
    if card.read_before_editing:
        lines.extend(f"- Read-before-editing: {truncate(item, 220)}" for item in card.read_before_editing[:4])
    return lines


def verified_fact_lines(project_card: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key in ("repo_path", "stack", "current_status"):
        value = clean_value(project_card.get(key))
        if value:
            lines.append(f"- {key}: {value}")
    lines.extend(f"- {fact}" for fact in split_fact_string(clean_value(project_card.get("verified_facts"))))
    return lines


def inference_lines(project_card: dict[str, Any]) -> list[str]:
    inferred = split_fact_string(clean_value(project_card.get("inferred_facts")))
    if inferred:
        return [f"- {item}" for item in inferred]
    purpose = clean_value(project_card.get("purpose"))
    return [f"- {purpose}"] if purpose else []


def architecture_lines(architecture: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for key in ("backend_layout", "frontend_layout", "important_packages", "major_responsibilities"):
        value = clean_value(architecture.get(key))
        if value:
            lines.append(f"- {key}: {truncate(value, 320)}")
    return lines


def read_rule_lines(model: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for rule in as_list(model.get("read_before_editing_rules")):
        item = as_dict(rule)
        area = clean_value(item.get("area"))
        files = ", ".join(str(path) for path in as_list(item.get("files_to_read")))
        reason = clean_value(item.get("reason"))
        lines.append(truncate(f"- {area}: read {files}. Reason: {reason}", 260))
    return lines


def decision_lines(model: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for decision in as_list(model.get("decisions_preferences")):
        item = as_dict(decision)
        lines.append(truncate(f"- {clean_value(item.get('decision'))}: {clean_value(item.get('constraint'))}", 220))
    return lines


def task_lines(model: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for task in as_list(model.get("current_task_memory")):
        item = as_dict(task)
        lines.append(
            truncate(
                f"- {clean_value(item.get('task'))} [{clean_value(item.get('status'))}]: {clean_value(item.get('notes'))}",
                220,
            )
        )
    return lines


def project_note_lines(model: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for note in as_list(model.get("project_notes")):
        item = as_dict(note)
        category = clean_value(item.get("category"))
        content = clean_value(item.get("content"))
        created_at = clean_value(item.get("created_at"))
        lines.append(truncate(f"- {category} ({created_at}): {content}", 260))
    return lines


def file_lines(model: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for file_item in as_list(model.get("file_index")):
        item = as_dict(file_item)
        path = clean_value(item.get("path"))
        role = clean_value(item.get("role"))
        when = clean_value(item.get("when_to_read"))
        stale = " stale" if item.get("stale") else ""
        lines.append(truncate(f"- {path}{stale}: {role}. Read when: {when}", 260))
    return lines


def behavior_lines(project_card: dict[str, Any], card: ProjectCard | None) -> list[str]:
    lines: list[str] = []
    needs_read = clean_value(project_card.get("needs_read"))
    if needs_read:
        lines.append(f"- {needs_read}")
    if card is not None:
        lines.extend(f"- {truncate(item, 220)}" for item in card.important_behavior)
    return lines


def file_ref_lines(card: ProjectCard) -> list[str]:
    lines: list[str] = []
    for file_ref in card.important_files:
        related = f" Related: {file_ref.related_files}." if file_ref.related_files else ""
        when = f" Read when: {file_ref.read_when}." if file_ref.read_when else ""
        lines.append(truncate(f"- {file_ref.path}: {file_ref.role}.{when}{related}", 260))
    return lines


def bullet_lines(values: list[str]) -> list[str]:
    return [f"- {truncate(value, 220)}" for value in values if value]


def split_fact_string(value: str) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in re.split(r";\s*", value) if part.strip()]


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def clean_value(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())


def truncate(value: str, max_length: int) -> str:
    value = " ".join(value.split())
    if len(value) <= max_length:
        return value
    suffix = "..."
    return value[: max(0, max_length - len(suffix))].rstrip() + suffix


def hard_cap(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= len(TRUNCATED_SUFFIX):
        return text[:max_chars]
    return text[: max_chars - len(TRUNCATED_SUFFIX)].rstrip() + TRUNCATED_SUFFIX


def normalize(text: str) -> str:
    text = text.lower()
    return "".join(character for character in unicodedata.normalize("NFD", text) if unicodedata.category(character) != "Mn")
