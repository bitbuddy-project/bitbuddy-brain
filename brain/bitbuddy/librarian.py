"""Librarian / context whisper system.

Before each chat response, the librarian gathers the most relevant project
memory entries and injects them as a structured "whisper" into the system
prompt.  This keeps raw model context lean while still giving the model
operational awareness of the projects it works on.

Storage: SQLite at ~/.bitbuddy/librarian.sqlite (one card per project).
Retrieval: simple keyword + substring matching against the user's current
message and recent conversation history.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .database import db_connection
from .activity import log_activity
from .paths import APP_DIR, ensure_app_dirs
from .memory.project import (
    load_project,
    project_has_completed_scan,
    list_projects,
    project_map,
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FileRef:
    """A single important file in a project card."""
    path: str
    role: str
    read_when: str = ""
    related_files: str = ""


@dataclass
class ProjectCard:
    """Structured memory card for one project.

    Fields map directly to the whisper sections so the formatter can
    render them without extra logic.
    """
    project_id: str
    project_name: str
    verified_facts: list[str] = field(default_factory=list)
    inferences: list[str] = field(default_factory=list)
    important_files: list[FileRef] = field(default_factory=list)
    read_before_editing: list[str] = field(default_factory=list)
    recent_decisions: list[str] = field(default_factory=list)
    important_behavior: list[str] = field(default_factory=list)
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "verified_facts": self.verified_facts,
            "inferences": self.inferences,
            "important_files": [f.__dict__ for f in self.important_files],
            "read_before_editing": self.read_before_editing,
            "recent_decisions": self.recent_decisions,
            "important_behavior": self.important_behavior,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True)
class ProjectContextSelection:
    """Pre-response project-memory selection result."""

    card: ProjectCard
    score: float
    confidence: str
    reason: str
    source: str


# ---------------------------------------------------------------------------
# SQLite store
# ---------------------------------------------------------------------------

LIBRARIAN_DB_PATH = APP_DIR / "librarian.sqlite"

_CREATE_CARDS_SQL = """
create table if not exists cards (
    project_id text primary key,
    project_name text not null,
    verified_facts text not null default '',
    inferences text not null default '',
    important_files text not null default '',
    read_before_editing text not null default '',
    recent_decisions text not null default '',
    important_behavior text not null default '',
    updated_at text default current_timestamp
)
"""


def _ensure_librarian_db() -> None:
    ensure_app_dirs()
    with db_connection(LIBRARIAN_DB_PATH) as conn:
        conn.execute(_CREATE_CARDS_SQL)


def _json_list(text: str) -> list[str]:
    """Deserialize a JSON-serialized list from the DB, or return empty."""
    if not text or text == "":
        return []
    try:
        import json
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return [text]


def _json_files(text: str) -> list[FileRef]:
    """Deserialize a JSON-serialized list of FileRef dicts."""
    if not text or text == "":
        return []
    try:
        import json
        raw = json.loads(text)
        return [FileRef(**item) for item in raw]
    except (json.JSONDecodeError, TypeError, KeyError):
        return []


def _save_card(card: ProjectCard) -> None:
    """Insert or replace a card in the librarian store."""
    import json
    with db_connection(LIBRARIAN_DB_PATH) as conn:
        conn.execute(
            """
            insert into cards (project_id, project_name, verified_facts,
                               inferences, important_files, read_before_editing,
                               recent_decisions, important_behavior, updated_at)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(project_id) do update set
                project_name = excluded.project_name,
                verified_facts = excluded.verified_facts,
                inferences = excluded.inferences,
                important_files = excluded.important_files,
                read_before_editing = excluded.read_before_editing,
                recent_decisions = excluded.recent_decisions,
                important_behavior = excluded.important_behavior,
                updated_at = excluded.updated_at
            """,
            (
                card.project_id,
                card.project_name,
                json.dumps(card.verified_facts),
                json.dumps(card.inferences),
                json.dumps([f.__dict__ for f in card.important_files]),
                json.dumps(card.read_before_editing),
                json.dumps(card.recent_decisions),
                json.dumps(card.important_behavior),
                card.updated_at or "current_timestamp",
            ),
        )


def get_card(project_id: str) -> ProjectCard | None:
    """Load a single card by project id."""
    _ensure_librarian_db()
    with db_connection(LIBRARIAN_DB_PATH) as conn:
        row = conn.execute(
            "select * from cards where project_id = ?", (project_id,)
        ).fetchone()
    if row is None:
        return None
    return ProjectCard(
        project_id=row[0],
        project_name=row[1],
        verified_facts=_json_list(row[2]),
        inferences=_json_list(row[3]),
        important_files=_json_files(row[4]),
        read_before_editing=_json_list(row[5]),
        recent_decisions=_json_list(row[6]),
        important_behavior=_json_list(row[7]),
        updated_at=row[8],
    )


def list_cards() -> list[ProjectCard]:
    """Return all cards in the store."""
    _ensure_librarian_db()
    with db_connection(LIBRARIAN_DB_PATH) as conn:
        rows = conn.execute("select * from cards order by project_name").fetchall()
    return [
        ProjectCard(
            project_id=r[0],
            project_name=r[1],
            verified_facts=_json_list(r[2]),
            inferences=_json_list(r[3]),
            important_files=_json_files(r[4]),
            read_before_editing=_json_list(r[5]),
            recent_decisions=_json_list(r[6]),
            important_behavior=_json_list(r[7]),
            updated_at=r[8],
        )
        for r in rows
    ]


def delete_card(project_id: str) -> bool:
    """Remove a card. Returns True if something was deleted."""
    _ensure_librarian_db()
    with db_connection(LIBRARIAN_DB_PATH) as conn:
        cursor = conn.execute("delete from cards where project_id = ?", (project_id,))
    return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Card generation — pull structured data from existing project memory
# ---------------------------------------------------------------------------

def build_card_from_project(project_id_or_name: str) -> ProjectCard | None:
    """Read the existing project-memory DB and produce a ProjectCard.

    Returns None if the project has no completed scan or can't be loaded.
    """
    try:
        project = load_project(project_id_or_name)
    except Exception:
        return None

    if not project_has_completed_scan(project.id):
        return None

    card = ProjectCard(
        project_id=project.id,
        project_name=project.name,
        updated_at="current_timestamp",
    )

    try:
        import sqlite3 as _sqlite3
        db_path = project.database_path
        if not db_path.exists():
            return card  # no DB yet — empty card is fine

        with db_connection(db_path) as conn:
            # Project profile (verified + inferred facts, stack, status)
            profile = conn.execute(
                "select repo_path, stack, purpose, current_status, "
                "verified_facts, inferred_facts, needs_read "
                "from project_profile where id = 1"
            ).fetchone()
            if profile:
                repo_path, stack, purpose, status, vf, inf, nr = profile
                profile_facts: list[str] = []
                if purpose:
                    profile_facts.append(f"purpose: {purpose}")
                profile_facts.extend(_json_list(vf) or [
                    f"path: {repo_path}",
                    f"stack: {stack}",
                    f"status: {status}",
                ])
                card.verified_facts = []
                for fact in profile_facts:
                    if fact and not any(_normalize(fact) == _normalize(existing) for existing in card.verified_facts):
                        card.verified_facts.append(fact)
                card.inferences = _json_list(inf) or []

            # Architecture summary
            arch = conn.execute(
                "select backend_layout, frontend_layout, major_responsibilities "
                "from architecture_summary where id = 1"
            ).fetchone()
            if arch:
                bl, fl, mr = arch
                card.important_behavior.extend([
                    f"Architecture — backend: {bl}",
                    f"Architecture — frontend: {fl}",
                    f"Architecture — responsibilities: {mr}",
                ])

            # Read-before-editing rules
            rules = conn.execute(
                "select area, files_to_read, reason from read_before_editing_rules order by area limit 10"
            ).fetchall()
            for area, files, reason in rules:
                card.read_before_editing.append(f"{area}: read {files}. Reason: {reason}")

            # Important files
            important_rows = conn.execute(
                "select path, role from file_index where important = 1 order by path limit 20"
            ).fetchall()
            for rel_path, role in important_rows:
                card.important_files.append(FileRef(path=rel_path, role=role))

            # Decisions / preferences
            decisions = conn.execute(
                "select decision, constraint_text from decisions_preferences order by id limit 10"
            ).fetchall()
            for dec, constraint in decisions:
                card.recent_decisions.append(f"{dec}: {constraint}")

            # Current task memory
            tasks = conn.execute(
                "select task, status, notes from current_task_memory order by id limit 5"
            ).fetchall()
            for task, status, notes in tasks:
                card.important_behavior.append(f"Task [{status}]: {task} — {notes}")

            # Project notes (steward / explicit model memory writes)
            notes_rows = conn.execute(
                "select category, content from project_notes order by id desc limit 20"
            ).fetchall()
            for note_category, note_content in notes_rows:
                if not _note_is_redundant(note_content, card):
                    if note_category == "fact":
                        card.verified_facts.append(note_content)
                    elif note_category == "architecture":
                        card.important_behavior.append(note_content)
                    elif note_category == "decision":
                        card.recent_decisions.append(note_content)
                    elif note_category == "task":
                        card.important_behavior.append(f"Note: {note_content}")

    except Exception:
        log_activity("librarian.card_build_error", f"Failed to build card for {project_id_or_name}", {})

    return card


def _note_is_redundant(note_content: str, card: ProjectCard) -> bool:
    """Return True if the note content is already represented in the card."""
    note_norm = _normalize(note_content)
    all_existing: list[str] = []
    all_existing.extend(card.verified_facts)
    all_existing.extend(card.inferences)
    all_existing.extend(card.recent_decisions)
    all_existing.extend(card.important_behavior)
    all_existing.extend(card.read_before_editing)
    for existing in all_existing:
        if note_norm in _normalize(existing) or _normalize(existing) in note_norm:
            return True
    return False


def regenerate_card(project_id_or_name: str) -> ProjectCard | None:
    """Delete existing card (if any) and rebuild from project memory."""
    delete_card(project_id_or_name)
    card = build_card_from_project(project_id_or_name)
    if card is not None:
        _save_card(card)
        log_activity("librarian.card_regenerated", f"Regenerated librarian card for {project_id_or_name}", {})
    return card


def index_all_projects() -> list[ProjectCard]:
    """Build (or rebuild) librarian cards for every registered project."""
    from .memory.project import list_projects as _list_projects

    cards: list[ProjectCard] = []
    for proj in _list_projects():
        card = build_card_from_project(proj.id)
        if card is not None:
            _save_card(card)
            cards.append(card)
    log_activity("librarian.index_all", f"Indexed {len(cards)} librarian cards", {})
    return cards


# ---------------------------------------------------------------------------
# Keyword matching / retrieval
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """Lowercase + strip diacritics for fuzzy keyword comparison."""
    text = text.lower()
    # Remove combining characters (accents, etc.)
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    return text


def _extract_keywords(query: str) -> list[str]:
    """Pull meaningful tokens from a query string.

    Keeps words >= 3 chars and any explicit file paths or identifiers.
    """
    # Extract file-like paths first (e.g. src/lib/api.ts)
    paths = re.findall(r"[A-Za-z0-9_/.~-]+(?:\.[a-z]{1,6}){1,3}", query)

    # Tokenize words >= 3 chars
    words = re.findall(r"\b[a-z]{3,}\b", _normalize(query))

    # Deduplicate while preserving order
    seen: set[str] = set()
    tokens: list[str] = []
    for w in words + [p.lower().replace("/", " ") for p in paths]:
        if w not in seen and len(w) >= 2:
            seen.add(w)
            tokens.append(w)
    return tokens


def _score_card(card: ProjectCard, query: str) -> float:
    """Score how relevant a card is to the given query.

    Returns a float score; higher = more relevant. Cards with score 0 are
    excluded from the whisper.
    """
    normalized_query = _normalize(query)
    tokens = _extract_keywords(query)
    if not tokens:
        return 0.0

    score = 0.0

    # Project name / ID match (highest weight)
    for token in tokens:
        if token in _normalize(card.project_name):
            score += 10.0
        if token in card.project_id.lower():
            score += 8.0

    # Verified facts
    fact_text = " ".join(card.verified_facts).lower()
    for token in tokens:
        if token in fact_text:
            score += 3.0

    # Inferences
    inf_text = " ".join(card.inferences).lower()
    for token in tokens:
        if token in inf_text:
            score += 1.5

    # File paths
    file_text = " ".join(f.path.lower() for f in card.important_files)
    for token in tokens:
        if token in file_text:
            score += 4.0

    # Read-before-editing rules
    rbe_text = " ".join(card.read_before_editing).lower()
    for token in tokens:
        if token in rbe_text:
            score += 2.5

    # Decisions
    dec_text = " ".join(card.recent_decisions).lower()
    for token in tokens:
        if token in dec_text:
            score += 2.0

    # Important behavior
    beh_text = " ".join(card.important_behavior).lower()
    for token in tokens:
        if token in beh_text:
            score += 1.5

    return score


def get_relevant_whisper(
    query: str,
    max_cards: int = 3,
    min_score: float = 2.0,
) -> list[ProjectCard]:
    """Return the most relevant cards for a given query string.

    Args:
        query: The user's current message (or concatenated recent messages).
        max_cards: Maximum number of cards to return.
        min_score: Minimum relevance score to include a card.

    Returns:
        List of ProjectCard instances sorted by relevance (highest first).
    """
    _ensure_librarian_db()
    cards = list_cards()
    if not cards:
        return []

    scored = [(card, _score_card(card, query)) for card in cards]
    scored.sort(key=lambda x: x[1], reverse=True)

    return [card for card, score in scored if score >= min_score][:max_cards]


def select_project_context(
    query: str,
    *,
    active_project_ids: list[str] | None = None,
    max_cards: int = 2,
) -> list[ProjectContextSelection]:
    """Select project cards for pre-response memory injection.

    Project identity comes from explicit names/ids/paths or clear active-chat
    affinity. Generic words like "project" or "repo" are intent signals only;
    they are not enough to choose a project by themselves.
    """
    clean_query = sanitize_context_query(query)
    if not clean_query:
        return []

    projects = list_projects()
    if not projects:
        return []

    active_project_ids = [project_id for project_id in (active_project_ids or []) if project_id]
    by_id = {project.id: project for project in projects}
    selections: list[ProjectContextSelection] = []
    selected_ids: set[str] = set()

    try:
        from .projects.routing import ranked_project_reference_matches
        matches = ranked_project_reference_matches(clean_query, projects)
    except Exception:
        matches = []

    for match in matches:
        if match.score < 15.0:
            continue
        card = card_for_project(match.project.id)
        if card is None:
            continue
        confidence = "high" if match.score >= 35.0 else "medium"
        selections.append(
            ProjectContextSelection(
                card=card,
                score=match.score,
                confidence=confidence,
                reason=match.reason or "project reference match",
                source="reference",
            )
        )
        selected_ids.add(card.project_id)
        if len(selections) >= max_cards:
            return selections

    if not selections and active_project_ids and query_has_active_project_reference(clean_query):
        for project_id in active_project_ids:
            if project_id in selected_ids or project_id not in by_id:
                continue
            card = card_for_project(project_id)
            if card is None:
                continue
            selections.append(
                ProjectContextSelection(
                    card=card,
                    score=22.0,
                    confidence="medium",
                    reason="active chat project reference",
                    source="active_chat",
                )
            )
            selected_ids.add(project_id)
            if len(selections) >= max_cards:
                return selections

    if selections:
        return selections[:max_cards]

    # Keyword cards are a fallback only.  Require a higher score so generic
    # language like "project memory" does not inject unrelated context.
    fallback_cards = get_relevant_whisper(clean_query, max_cards=max_cards, min_score=8.0)
    return [
        ProjectContextSelection(
            card=card,
            score=_score_card(card, clean_query),
            confidence="low",
            reason="keyword relevance fallback",
            source="keyword",
        )
        for card in fallback_cards
    ]


def card_for_project(project_id: str) -> ProjectCard | None:
    card = get_card(project_id)
    if card is not None:
        return card
    return regenerate_card(project_id)


def sanitize_context_query(query: str) -> str:
    """Remove runtime/prompt scaffolding before project-memory selection."""
    clean = re.sub(r"(?is)<system-reminder\b[^>]*>.*?(?:</system-reminder>|$)", " ", query or "")
    clean = re.sub(r"(?is)<think\b[^>]*>.*?(?:</think>|$)", " ", clean)
    clean = re.sub(r"(?im)^\s*(?:tool_call:|\[Tool Result|\[Previous Tool|result_content_private_working_context:).*$", " ", clean)
    return re.sub(r"\s+", " ", clean).strip()


def query_has_active_project_reference(query: str) -> bool:
    lowered = _normalize(query)
    return bool(
        re.search(
            r"\b(?:this|that|current)\s+(?:project|repo|repository|codebase)\b"
            r"|\b(?:the|this|that)\s+(?:readme|repo|repository|project|codebase)\b"
            r"|\b(?:read|open|summari[sz]e|check)\s+(?:the\s+)?(?:readme|project|repo|repository)\b",
            lowered,
        )
    )


# ---------------------------------------------------------------------------
# Whisper formatting
# ---------------------------------------------------------------------------

def format_whisper(cards: list[ProjectCard]) -> str:
    """Render a list of ProjectCards into the structured whisper text.

    The output is designed to be injected into the system prompt before
    the conversation messages. It is compact, clearly labeled, and
    separates verified facts from inferences.
    """
    if not cards:
        return ""

    sections: list[str] = ["PROJECT CONTEXT WHISPER"]

    for card in cards:
        sections.append(f"\n## {card.project_name} ({card.project_id})")

        if card.verified_facts:
            sections.append("\nVerified facts:")
            for fact in card.verified_facts[:10]:
                sections.append(f"* {fact}")

        if card.inferences:
            sections.append("\nInferences:")
            for inf in card.inferences[:6]:
                sections.append(f"* {inf}")

        if card.important_files:
            sections.append("\nImportant file map:")
            for f in card.important_files[:12]:
                line = f"* `{f.path}` — {f.role}"
                if f.read_when:
                    line += f" (read when: {f.read_when})"
                if f.related_files:
                    line += f" | related: {f.related_files}"
                sections.append(line)

        if card.read_before_editing:
            sections.append("\nRead-before-editing rules:")
            for rule in card.read_before_editing[:8]:
                sections.append(f"* {rule}")

        if card.recent_decisions:
            sections.append("\nRecent decisions:")
            for dec in card.recent_decisions[:6]:
                sections.append(f"* {dec}")

        if card.important_behavior:
            sections.append("\nImportant behavior:")
            for beh in card.important_behavior[:5]:
                sections.append(f"* {beh}")

    return "\n".join(sections)


@dataclass
class ContextPlan:
    project_id: str
    detected_project_name: str
    intent: str
    detail_level: str
    token_budget: int

def plan_context(project_id: str, project_name: str, query: str) -> ContextPlan:
    query_norm = _normalize(query)

    intent = "code_edit"
    detail_level = "task"
    budget = 8000

    if any(k in query_norm for k in ["full dossier", "everything about", "whole project", "deep", "all details"]):
        intent = "whole_project_review"
        detail_level = "deep"
        budget = 20000
    elif any(k in query_norm for k in ["what do you know", "overview", "summary", "briefing"]):
        intent = "project_overview"
        detail_level = "briefing"
        budget = 2000
    elif any(k in query_norm for k in ["do you understand", "understand", "are you familiar", "can you"]):
        intent = "project_understanding_check"
        detail_level = "briefing"
        budget = 1500
    elif any(k in query_norm for k in ["fix", "bug", "error", "issue", "crash"]):
        intent = "debug_error"
        detail_level = "task"
        budget = 8000
    elif any(k in query_norm for k in ["implement", "add feature", "new feature", "create"]):
        intent = "implement_feature"
        detail_level = "task"
        budget = 8000
    elif any(k in query_norm for k in ["explain file", "how does"]):
        intent = "explain_file"
        detail_level = "operational"
        budget = 4000
    elif any(k in query_norm for k in ["find file", "where is"]):
        intent = "find_file"
        detail_level = "operational"
        budget = 4000
    elif any(k in query_norm for k in ["identity"]):
        intent = "project_overview"
        detail_level = "identity"
        budget = 500

    return ContextPlan(
        project_id=project_id,
        detected_project_name=project_name,
        intent=intent,
        detail_level=detail_level,
        token_budget=budget,
    )

def build_whisper_message(query: str, max_cards: int = 3, min_score: float = 2.0) -> dict[str, str] | None:
    """Convenience function: get relevant cards and format as a whisper message.

    Returns a dict with role='system' and content=whisper text, or None if
    no relevant cards were found. This can be injected between the system
    prompt and the conversation messages.
    """
    query_norm = _normalize(query)

    # 1. Resolve the project from the registry
    mentioned_projects = []
    for p in list_projects():
        if _normalize(p.name) in query_norm or p.id.lower() in query_norm:
            mentioned_projects.append(p)

    if mentioned_projects:
        print(f"[DEBUG] Detected project mentions: {[p.name for p in mentioned_projects]}")
        whisper_parts = []
        for p in mentioned_projects:
            # Plan context level
            plan = plan_context(p.id, p.name, query)
            print(f"[DEBUG] ContextPlan for {p.name}: intent={plan.intent}, detail_level={plan.detail_level}, token_budget={plan.token_budget}")

            # 2. Load the saved project dossier
            if not project_has_completed_scan(p.id):
                # If only the path exists and no dossier exists, say that clearly
                print(f"[DEBUG] Injected missing dossier whisper for {p.name}")
                log_activity("librarian.whisper_injected", f"Injected missing dossier whisper for {p.name}", {"project_id": p.id, "intent": plan.intent, "detail_level": plan.detail_level})
                whisper_parts.append(f"## {p.name} ({p.id})\nPath: {p.paths[0]}\nI only have the registry entry right now; I have not scanned or saved a project dossier yet.")
            else:
                try:
                    dossier = project_map(p.id, detail_level=plan.detail_level)
                    print(f"[DEBUG] Injected project dossier whisper for {p.name} (level: {plan.detail_level})")
                    log_activity("librarian.whisper_injected", f"Injected project dossier whisper for {p.name}", {"project_id": p.id, "intent": plan.intent, "detail_level": plan.detail_level})
                    whisper_parts.append(dossier)
                except Exception as e:
                    whisper_parts.append(f"## {p.name} ({p.id})\nPath: {p.paths[0]}\nI only have the registry entry right now; I have not scanned or saved a project dossier yet. (Error: {e})")

        return {
            "role": "system",
            "content": f"[Librarian Context Whisper — auto-selected from project memory]\n\n" + "\n\n---\n\n".join(whisper_parts)
        }

    # Fallback to legacy keyword search if no explicit mention found
    cards = get_relevant_whisper(query, max_cards=max_cards, min_score=min_score)
    if not cards:
        return None

    whisper_text = format_whisper(cards)
    return {
        "role": "system",
        "content": f"[Librarian Context Whisper — auto-selected from project memory]\n\n{whisper_text}",
    }


def build_advisory_whisper_message(
    query: str,
    max_cards: int = 2,
    max_chars: int = 1200,
    active_project_ids: list[str] | None = None,
) -> dict[str, str] | None:
    """Build a compact, advisory whisper message for AI-first context.

    This is a memory surface, not a router.  The model can use it, ignore it,
    answer directly, or choose a tool naturally.  The runtime must not force a
    project/tool workflow merely because this whisper exists.
    """
    clean_query = sanitize_context_query(query)
    if not clean_query:
        return None

    selections = select_project_context(clean_query, active_project_ids=active_project_ids, max_cards=max_cards)
    if not selections:
        return None

    parts: list[str] = [
        "[Relevant Project Context — advisory memory surface]",
        "The following project memory was selected before the model response.",
        "For high-level overview questions like 'what do you know about X?', answer directly from this context instead of calling a project-memory tool again.",
        "Use tools only when the user asks to read/verify source, needs exact file behavior, or this context is insufficient.",
    ]

    for selection in selections:
        card = selection.card
        project_lines = [f"\n## {card.project_name} ({card.project_id})"]
        project_lines.append(
            f"Selection: {selection.confidence} confidence via {selection.source}; {selection.reason}."
        )

        if card.verified_facts:
            facts = " | ".join(card.verified_facts[:3])
            project_lines.append(f"Facts: {facts}")

        if card.inferences:
            inferences = " | ".join(card.inferences[:2])
            project_lines.append(f"Inferences: {inferences}")

        if card.important_files:
            file_refs = ", ".join(f"`{f.path}`" for f in card.important_files[:4])
            project_lines.append(f"Key files: {file_refs}")

        parts.extend(project_lines)

    parts.append("\n[End of advisory context]")

    content = "\n".join(parts)
    if len(content) > max_chars:
        content = content[:max_chars].rstrip() + "\n[Context truncated]"

    return {"role": "system", "content": content}
