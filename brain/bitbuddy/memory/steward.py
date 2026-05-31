from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .project import project_brief
from ..providers import ProviderClient
from ..tools import ToolCall, ToolResult
from ..utils import log_activity


BROKER_RESULT_CONTENT_CHARS = 12000
BROKER_ASSISTANT_ANSWER_CHARS = 4000
BROKER_PROJECT_BRIEF_CHARS = 8000
MAX_AUTOMATIC_MEMORY_CHARS = 900
MIN_AUTOMATIC_MEMORY_CHARS = 24

PROJECT_MEMORY_CATEGORIES = {"decision", "fact", "task", "architecture"}
PROJECT_SOURCE_TOOLS = {"read_file", "get_project_brief", "get_project_memory", "run_shell_command"}
MEMORY_TOOLS = {"record_project_memory", "record_episode", "update_episode", "forget_episode", "invalid_tool_call"}

DURABLE_DECISION_PATTERNS = (
    r"\bwe\s+(?:need|want|should|will|decided|are going)\b",
    r"\bgoing forward\b",
    r"\bfrom now on\b",
    r"\bremember\s+that\b",
    r"\bnote\s+that\b",
    r"\bthe direction is\b",
    r"\bthe plan is\b",
    r"\bpriority\s+is\b",
    r"\brename\b",
    r"\bremove\b.+\b(?:from|for|in)\b",
    r"\breplace\b.+\bwith\b",
)

TASK_PATTERNS = (
    r"\bnext\s+(?:step|milestone|task)\b",
    r"\bTODO\b",
    r"\bto\s+do\b",
    r"\bneeds?\s+to\s+be\b",
    r"\bfix\b",
    r"\bimplement\b",
)

ARCHITECTURE_PATTERNS = (
    r"\barchitecture\b",
    r"\bruntime\b",
    r"\bbackend\b",
    r"\bfrontend\b",
    r"\bsystem\b",
    r"\bmemory\s+(?:broker|runtime|layer|retrieval|injection)\b",
    r"\btool\s+(?:loop|call|event)\b",
    r"\bprompt\b",
    r"\bcontext\s+(?:pack|injection|surface)\b",
    r"\bwayland\b",
    r"\bcompositor\b",
    r"\bspatial\b",
    r"\bcanvas\b",
    r"\bcluster\b",
)

CORRECTION_PATTERNS = (
    r"\bnot\s+quite\b",
    r"\bpartly\s+correct\b",
    r"\bpartially\s+correct\b",
    r"\bmore\s+specifically\b",
    r"\bactually\b",
    r"\bmainly\b",
    r"\bto\s+be\s+precise\b",
    r"\binstead\b",
)

PURPOSE_CORRECTION_PATTERNS = (
    r"\bpurpose\b",
    r"\bdescription\b",
    r"\bwhat\s+(?:it|this|that)\s+is\b",
    r"\bidentity\b",
)

README_NAMES = {"readme", "readme.md", "readme.txt", "overview.md", "architecture.md", "design.md"}
IMPORTANT_CONFIG_NAMES = {
    "pyproject.toml",
    "package.json",
    "cargo.toml",
    "go.mod",
    "deno.json",
    "vite.config.ts",
    "svelte.config.js",
    "tauri.conf.json",
}
CODE_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".svelte", ".java", ".kt"}
DOC_SUFFIXES = {".md", ".mdx", ".txt", ".rst"}


@dataclass(frozen=True)
class StewardCandidate:
    project_id: str
    tool: str
    summary: str
    content: str
    file_path: str = ""
    truncated: bool = False


@dataclass(frozen=True)
class ProjectMemoryDecision:
    project_id: str
    category: str
    content: str
    reason: str


def project_memory_steward_call(
    *,
    client: ProviderClient,
    model: str | None,
    chat_id: str,
    latest_user_text: str,
    assistant_answer: str,
    tool_result: ToolResult,
    should_cancel: Callable[[], bool] | None = None,
) -> ToolCall | None:
    """Compatibility wrapper for the old steward entry point.

    The previous implementation made a second private model call to decide
    whether memory should be updated.  BitBuddy is now model-first and
    runtime-supported: the visible assistant model answers the user, then this
    deterministic backend broker decides whether a compact durable note should
    be written from the completed tool result.
    """
    _ = (client, model)
    return project_memory_broker_call(
        chat_id=chat_id,
        latest_user_text=latest_user_text,
        assistant_answer=assistant_answer,
        tool_result=tool_result,
        should_cancel=should_cancel,
    )


def project_memory_broker_call(
    *,
    chat_id: str,
    latest_user_text: str,
    assistant_answer: str,
    tool_result: ToolResult,
    should_cancel: Callable[[], bool] | None = None,
) -> ToolCall | None:
    """Return one record_project_memory call when a durable project delta exists.

    This function intentionally does not call an LLM.  It uses conservative
    heuristics and existing project memory as a duplicate guard.  The goal is
    not to be clever; it is to make safe, obvious, useful memory writes while
    leaving nuanced conversation to the primary assistant model.
    """
    if should_cancel is not None and should_cancel():
        return None

    candidate = steward_candidate_from_result(tool_result)
    if candidate is None:
        return None

    try:
        existing_memory = project_brief(candidate.project_id)
    except Exception as error:
        log_activity(
            "memory_broker.skipped",
            "Project memory broker could not load existing project brief",
            {"project_id": candidate.project_id, "error": str(error)},
        )
        return None

    decision = decide_project_memory_update(
        candidate=candidate,
        latest_user_text=latest_user_text,
        assistant_answer=assistant_answer,
        existing_memory=existing_memory,
    )
    if decision is None:
        log_activity(
            "memory_broker.no_update",
            "Project memory broker found no durable update",
            {"project_id": candidate.project_id, "tool": candidate.tool, "file_path": candidate.file_path},
        )
        return None

    if should_cancel is not None and should_cancel():
        return None

    return ToolCall(
        tool="record_project_memory",
        arguments={
            "project_id": decision.project_id,
            "category": decision.category,
            "content": decision.content,
        },
    )


def decide_project_memory_update(
    *,
    candidate: StewardCandidate,
    latest_user_text: str,
    assistant_answer: str,
    existing_memory: str,
) -> ProjectMemoryDecision | None:
    conversation_text = compact_whitespace("\n".join([latest_user_text, assistant_answer]))

    correction = correction_memory_note(
        project_id=candidate.project_id,
        text=conversation_text,
        source_tool=candidate.tool,
        file_path=candidate.file_path,
    )
    if correction and not already_in_memory(correction.content, existing_memory):
        return correction

    explicit_decision = explicit_decision_note(
        project_id=candidate.project_id,
        text=conversation_text,
        source_tool=candidate.tool,
        file_path=candidate.file_path,
    )
    if explicit_decision and not already_in_memory(explicit_decision.content, existing_memory):
        return explicit_decision

    if candidate.tool == "read_file":
        note = read_file_memory_note(candidate)
        if note and not already_in_memory(note.content, existing_memory):
            return note
        return None

    if candidate.tool == "run_shell_command":
        note = shell_result_memory_note(candidate, latest_user_text, assistant_answer)
        if note and not already_in_memory(note.content, existing_memory):
            return note
        return None

    # get_project_brief/get_project_memory are retrieval tools.  Writing their
    # output back into memory usually duplicates what already exists.
    return None


def correction_memory_note(
    *,
    project_id: str,
    text: str,
    source_tool: str,
    file_path: str = "",
) -> ProjectMemoryDecision | None:
    text = strip_system_reminder_blocks(text)
    if not text:
        return None

    if not any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in CORRECTION_PATTERNS):
        return None

    sentence = correction_memory_sentence(text)
    if not sentence:
        return None

    if contains_any_pattern(text, PURPOSE_CORRECTION_PATTERNS) or re.search(
        r"\b(?:more\s+specifically|mainly|primarily)\b.*\b(?:a|an|the)\b",
        sentence,
        flags=re.IGNORECASE,
    ):
        purpose = correction_sentence_as_purpose(project_id, sentence)
        if purpose:
            try:
                from .project import update_project_purpose
                update_project_purpose(project_id, purpose)
            except Exception:
                pass

    source = f" after {source_tool}"
    if file_path:
        source += f" on `{file_path}`"

    category = "architecture" if contains_any_pattern(sentence, ARCHITECTURE_PATTERNS) else "fact"
    content = sanitize_memory_content(f"Correction{source}: {sentence}")
    if not valid_memory_note(category, content):
        return None

    return ProjectMemoryDecision(
        project_id=project_id,
        category=category,
        content=content,
        reason="project correction language",
    )


def correction_sentence_as_purpose(project_id: str, sentence: str) -> str:
    clean = compact_whitespace(sentence).strip(" .")
    if not clean:
        return ""

    clean = re.sub(r"(?i)^.*?\b(?:more\s+specifically|mainly|primarily|actually|to\s+be\s+precise)\b[:,]?\s*", "", clean).strip()

    clean = re.sub(
        r"(?i)^(?:no,?\s*)?(?:not\s+quite\.?\s*)?(?:partly|partially)\s+correct(?:,?\s*but)?\s*",
        "",
        clean,
    ).strip()

    clean = re.sub(
        r"(?i)^(?:no,?\s*)?(?:not\s+quite\.?\s*)?(?:more\s+specifically|actually|to\s+be\s+precise|rather|instead|mainly|primarily)[:,]?\s*",
        "",
        clean,
    ).strip()

    try:
        from .project import load_project
        project_name = load_project(project_id).name
    except Exception:
        project_name = project_id

    clean = re.sub(r"(?i)^(?:it's|its|it\s+is|this\s+is|that\s+is)\b", f"{project_name} is", clean, count=1)
    if not clean.lower().startswith(project_name.lower()) and re.match(r"(?i)^(?:a|an|the)\s+", clean):
        clean = f"{project_name} is {clean}"

    if clean and clean[0].islower():
        clean = clean[0].upper() + clean[1:]
    return clean[:650]


def correction_memory_sentence(text: str) -> str:
    clean = compact_whitespace(strip_code_blocks(strip_system_reminder_blocks(text)))
    if not clean:
        return ""

    for pattern in (
        r"(?:^|[.!?]\s+)([^.!?]*\b(?:more\s+specifically|mainly|primarily|actually|to\s+be\s+precise)\b[^.!?]*(?:[.!?]|$))",
        r"(?:^|[.!?]\s+)([^.!?]*\b(?:partly|partially)\s+correct\b[^.!?]*(?:[.!?]|$))",
        r"(?:^|[.!?]\s+)([^.!?]*\bnot\s+quite\b[^.!?]*(?:[.!?]|$))",
    ):
        match = re.search(pattern, clean, flags=re.IGNORECASE)
        if match:
            sentence = match.group(1).strip(" -•\t")
            if len(sentence) >= 24:
                return sentence[:650]

    return best_memory_sentence(clean)


def explicit_decision_note(
    *,
    project_id: str,
    text: str,
    source_tool: str,
    file_path: str = "",
) -> ProjectMemoryDecision | None:
    if not text:
        return None

    if not any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in DURABLE_DECISION_PATTERNS):
        return None

    source = f" after {source_tool}"
    if file_path:
        source += f" on `{file_path}`"

    category = "architecture" if contains_any_pattern(text, ARCHITECTURE_PATTERNS) else "decision"
    if contains_any_pattern(text, TASK_PATTERNS):
        category = "task" if not contains_any_pattern(text, ARCHITECTURE_PATTERNS) else category

    content = best_memory_sentence(text)
    if not content:
        return None

    content = f"Decision{source}: {content}"
    content = sanitize_memory_content(content)
    if not valid_memory_note(category, content):
        return None

    return ProjectMemoryDecision(
        project_id=project_id,
        category=category,
        content=content,
        reason="explicit durable decision language",
    )


def read_file_memory_note(candidate: StewardCandidate) -> ProjectMemoryDecision | None:
    file_path = candidate.file_path.strip()
    if not file_path:
        return None

    path = Path(file_path)
    lowered_name = path.name.lower()
    suffix = path.suffix.lower()
    content = candidate.content.strip()
    summary = compact_whitespace(candidate.summary)

    important = is_important_file(path)
    if not important:
        return None

    document_content = unwrap_read_file_content(content, file_path)
    title = extract_markdown_title(document_content, fallback_path=file_path)
    overview = extract_markdown_overview(document_content, title=title)
    symbols = extract_named_symbols(content, suffix=suffix)

    if lowered_name in README_NAMES or suffix in DOC_SUFFIXES:
        # For documentation files, do not save/update purpose from the tool's
        # synthetic "# README.md" wrapper, badge/header HTML, or title-only
        # content.  A durable project purpose needs at least one meaningful
        # descriptive sentence from the document body.
        if not overview:
            return None

        pieces: list[str] = []
        if title:
            pieces.append(f"title `{title}`")
        pieces.append(f"overview: {overview}")

        # Also update the canonical project_profile purpose so the librarian
        # surfaces it without needing to parse project_notes.
        from .project import update_project_purpose
        update_project_purpose(candidate.project_id, document_purpose(title, overview))

        category = "architecture" if contains_any_pattern(" ".join(pieces), ARCHITECTURE_PATTERNS) else "fact"
        note = f"`{file_path}` is a project documentation entry point: " + "; ".join(pieces)
        note = sanitize_memory_content(note)
        if valid_memory_note(category, note):
            return ProjectMemoryDecision(candidate.project_id, category, note, "important documentation file read")
        return None

    if lowered_name in IMPORTANT_CONFIG_NAMES:
        config_hint = config_file_hint(content, lowered_name)
        if not config_hint and not summary:
            return None
        note = f"`{file_path}` is a project configuration/dependency entry point."
        if config_hint:
            note += f" {config_hint}"
        elif summary:
            note += f" {summary}"
        note = sanitize_memory_content(note)
        if valid_memory_note("architecture", note):
            return ProjectMemoryDecision(candidate.project_id, "architecture", note, "important config file read")
        return None

    if suffix in CODE_SUFFIXES:
        pieces = []
        if symbols:
            pieces.append("defines " + ", ".join(symbols[:10]))
        if summary:
            pieces.append(summary)
        if not pieces:
            return None

        note = f"`{file_path}` is important runtime/source code: " + "; ".join(pieces)
        note = sanitize_memory_content(note)
        if valid_memory_note("architecture", note):
            return ProjectMemoryDecision(candidate.project_id, "architecture", note, "important source code read")

    return None


def shell_result_memory_note(
    candidate: StewardCandidate,
    latest_user_text: str,
    assistant_answer: str,
) -> ProjectMemoryDecision | None:
    command = ""
    # ToolResult.arguments_summary normally carries command, but StewardCandidate
    # deliberately stores a compact subset.  Preserve old behavior by using the
    # summary/content only unless command is present in the summary.
    combined = compact_whitespace("\n".join([candidate.summary, candidate.content, assistant_answer]))
    user = latest_user_text.lower()

    if not any(word in user for word in ["test", "build", "run", "command", "error", "fix", "debug"]):
        return None

    if re.search(r"\b(?:failed|error|traceback|panic|exception|cannot|could not)\b", combined, flags=re.IGNORECASE):
        status = "reported a failure/error"
    elif re.search(r"\b(?:passed|success|succeeded|ok|0 failed)\b", combined, flags=re.IGNORECASE):
        status = "completed successfully"
    else:
        return None

    note = f"Recent project command result{f' for `{command}`' if command else ''}: {status}. {best_memory_sentence(combined)}"
    note = sanitize_memory_content(note)
    if not valid_memory_note("task", note):
        return None

    return ProjectMemoryDecision(candidate.project_id, "task", note, "project command result")


def steward_candidate_from_result(result: ToolResult) -> StewardCandidate | None:
    if not result.ok:
        return None

    if result.tool in MEMORY_TOOLS:
        return None

    arguments = result.arguments_summary if isinstance(result.arguments_summary, dict) else {}
    project_id = str(arguments.get("project_id") or "").strip()
    if not project_id:
        return None

    tool = str(result.tool or "").strip()
    if tool not in PROJECT_SOURCE_TOOLS:
        return None

    content = str(result.content or "").strip()
    summary = str(result.summary or "").strip()
    if not content and not summary:
        return None

    return StewardCandidate(
        project_id=project_id,
        tool=tool,
        summary=summary,
        content=clipped_text(content, BROKER_RESULT_CONTENT_CHARS),
        file_path=str(arguments.get("file_path") or "").strip(),
        truncated=bool(result.truncated),
    )


def is_important_file(path: Path) -> bool:
    lowered_name = path.name.lower()
    lowered_path = path.as_posix().lower()

    if lowered_name in README_NAMES or lowered_name in IMPORTANT_CONFIG_NAMES:
        return True

    if any(part in lowered_path for part in ["architecture", "design", "docs/", "doc/"]):
        return True

    if any(part in lowered_path for part in ["memory", "prompt", "runtime", "tools", "router", "routing", "agent"]):
        return True

    if path.suffix.lower() in CODE_SUFFIXES and any(
        part in lowered_path
        for part in ["main", "server", "runtime", "memory", "prompt", "tool", "chat", "librarian", "steward"]
    ):
        return True

    return False


def config_file_hint(content: str, filename: str) -> str:
    if filename == "package.json":
        name = extract_jsonish_string(content, "name")
        scripts = sorted(set(re.findall(r'"([A-Za-z0-9:_-]+)"\s*:', content)))[:8]
        pieces = []
        if name:
            pieces.append(f"package name `{name}`")
        useful_scripts = [script for script in scripts if script not in {"name", "version", "scripts", "dependencies", "devDependencies"}]
        if useful_scripts:
            pieces.append("scripts include " + ", ".join(f"`{script}`" for script in useful_scripts[:6]))
        return "; ".join(pieces)

    if filename in {"pyproject.toml", "cargo.toml"}:
        name = re.search(r'^\s*name\s*=\s*["\']([^"\']+)["\']', content, flags=re.MULTILINE)
        if name:
            return f"project/package name `{name.group(1).strip()}`."

    return ""


def extract_jsonish_string(content: str, key: str) -> str:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"([^"]+)"', content)
    return match.group(1).strip() if match else ""


def unwrap_read_file_content(content: str, file_path: str) -> str:
    """Remove the read_file tool's synthetic markdown header from file text.

    read_file returns content as "# <display_path>\n\n<actual file>" so the
    model can see the path.  That wrapper is useful in chat, but the memory
    steward must not treat it as the document's real title or purpose.
    """
    lines = content.splitlines()
    if not lines:
        return ""

    first_index = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first_index is None:
        return ""

    first = lines[first_index].strip()
    if first.startswith("# "):
        header = compact_whitespace(first[2:])
        expected = {file_path, Path(file_path).name}
        if header in expected:
            remaining = lines[:first_index] + lines[first_index + 1 :]
            while remaining and not remaining[0].strip():
                remaining.pop(0)
            return "\n".join(remaining).strip()

    return content.strip()


def extract_markdown_title(content: str, fallback_path: str = "") -> str:
    fallback_names = {Path(fallback_path).name.lower(), Path(fallback_path).stem.lower()} if fallback_path else set()

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue

        match = re.match(r"^#\s+(.+?)\s*$", stripped)
        if not match:
            match = re.match(r"^<h1\b[^>]*>(.*?)</h1>\s*$", stripped, flags=re.IGNORECASE)

        if not match:
            continue

        title = clean_document_inline(match.group(1))[:120]
        if title and title.lower() not in fallback_names:
            return title

    return ""


def extract_markdown_overview(content: str, title: str = "") -> str:
    lines = content.splitlines()
    primary_heading_indexes: list[int] = []
    fallback_heading_indexes: list[int] = []

    for index, line in enumerate(lines):
        normalized = clean_heading_text(line)
        if normalized in {"overview", "purpose", "what is this", "about"}:
            primary_heading_indexes.append(index)
        elif normalized in {"architecture", "design"}:
            fallback_heading_indexes.append(index)

    indexes = [-1, *primary_heading_indexes, *fallback_heading_indexes]
    for start_index in indexes:
        paragraph = first_paragraph_after(lines, start_index, title=title)
        if paragraph:
            return paragraph

    return ""


def first_paragraph_after(lines: list[str], start_index: int, title: str = "") -> str:
    paragraph: list[str] = []
    in_code_block = False

    for line in lines[start_index + 1 :]:
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue

        if not stripped:
            if paragraph:
                break
            continue

        if is_document_heading_line(stripped):
            if paragraph:
                break
            continue

        if is_noise_document_line(stripped):
            continue

        clean = clean_document_inline(stripped).strip(" -–—•")
        if not is_meaningful_overview_line(clean, title=title):
            continue

        paragraph.append(clean)
        if len(" ".join(paragraph)) >= 420:
            break

    return compact_whitespace(" ".join(paragraph))[:500]


def document_purpose(title: str, overview: str) -> str:
    overview = compact_whitespace(overview)
    title = compact_whitespace(title)
    if not overview:
        return ""
    if title and re.match(r"(?i)^(?:a|an|the)\s+", overview):
        return f"{title} is {overview[0].lower() + overview[1:]}"[:650]
    if title and not overview.lower().startswith(title.lower()):
        return f"{title}: {overview}"[:650]
    return overview[:650]


def clean_heading_text(line: str) -> str:
    stripped = line.strip()
    stripped = re.sub(r"^#+\s*", "", stripped)
    stripped = re.sub(r"</?h[1-6]\b[^>]*>", "", stripped, flags=re.IGNORECASE)
    return clean_document_inline(stripped).lower().strip(" :#")


def is_document_heading_line(line: str) -> bool:
    return bool(
        re.match(r"^#{1,6}\s+", line)
        or re.match(r"^<h[1-6]\b[^>]*>.*?</h[1-6]>\s*$", line, flags=re.IGNORECASE)
    )


def is_noise_document_line(line: str) -> bool:
    lowered = line.lower().strip()

    if lowered.startswith(">") and not re.search(r"\b(?:is|are|provides|offers|targets|builds)\b", lowered):
        return True

    if lowered.startswith(("|", "<!--", "[![", "![", "<p", "</p", "<div", "</div", "<br", "<a ", "</a")):
        return True

    if any(marker in lowered for marker in ("img.shields.io", "badge", "badgen.net", "github.com/", "readthedocs", "license-", "license_")):
        return True

    if re.fullmatch(r"[-=*_~`\s]+", lowered):
        return True

    return False


def clean_document_inline(value: str) -> str:
    clean = html.unescape(value)
    clean = re.sub(r"!\[[^\]]*]\([^)]*\)", " ", clean)
    clean = re.sub(r"\[([^\]]+)]\([^)]*\)", r"\1", clean)
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = re.sub(r"`([^`]+)`", r"\1", clean)
    clean = clean.replace("**", "").replace("__", "").replace("*", "")
    return compact_whitespace(clean)


def is_meaningful_overview_line(line: str, title: str = "") -> bool:
    if len(line) < 32:
        return False

    lowered = line.lower()
    title_lower = title.lower().strip()
    if title_lower and lowered == title_lower:
        return False

    generic_noise = {
        "table of contents",
        "installation",
        "usage",
        "requirements",
        "license",
        "todo",
        "coming soon",
        "work in progress",
    }
    if lowered.strip(" :") in generic_noise:
        return False

    word_count = len(re.findall(r"[a-zA-Z][a-zA-Z0-9_-]+", line))
    if word_count < 6:
        return False

    return True


def extract_named_symbols(content: str, suffix: str) -> list[str]:
    patterns: list[tuple[str, str]] = []

    if suffix == ".py":
        patterns = [
            ("class", r"^\s*class\s+([A-Za-z_][\w]*)"),
            ("function", r"^\s*(?:async\s+)?def\s+([A-Za-z_][\w]*)"),
        ]
    elif suffix in {".ts", ".tsx", ".js", ".jsx", ".svelte"}:
        patterns = [
            ("class", r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)"),
            ("function", r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)"),
            ("function", r"^\s*(?:export\s+)?const\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\("),
        ]
    elif suffix == ".rs":
        patterns = [
            ("item", r"^\s*(?:pub\s+)?(?:async\s+)?(?:fn|struct|enum|trait)\s+([A-Za-z_][\w]*)"),
        ]
    elif suffix == ".go":
        patterns = [("function", r"^\s*func\s+(?:\([^)]*\)\s*)?([A-Za-z_][\w]*)")]

    names: list[str] = []
    seen: set[str] = set()
    for label, pattern in patterns:
        for match in re.finditer(pattern, content, flags=re.MULTILINE):
            name = match.group(1).strip()
            if name.startswith("_") or name in seen:
                continue
            seen.add(name)
            names.append(f"{label} `{name}`")
            if len(names) >= 12:
                return names
    return names


def contains_any_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def best_memory_sentence(text: str) -> str:
    clean = compact_whitespace(strip_code_blocks(strip_system_reminder_blocks(text)))
    if not clean:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", clean)
    scored: list[tuple[int, str]] = []
    for sentence in sentences:
        trimmed = sentence.strip(" -•\t")
        if len(trimmed) < 24:
            continue
        score = 0
        if contains_any_pattern(trimmed, DURABLE_DECISION_PATTERNS):
            score += 5
        if contains_any_pattern(trimmed, ARCHITECTURE_PATTERNS):
            score += 3
        if contains_any_pattern(trimmed, TASK_PATTERNS):
            score += 2
        if "user" in trimmed.lower() or "assistant" in trimmed.lower():
            score -= 2
        scored.append((score, trimmed))

    if scored:
        scored.sort(key=lambda item: item[0], reverse=True)
        return scored[0][1][:650]

    return clean[:650]


def strip_code_blocks(text: str) -> str:
    return re.sub(r"```.*?```", " ", text, flags=re.DOTALL)


def strip_system_reminder_blocks(text: str) -> str:
    return re.sub(r"(?is)<system-reminder\b[^>]*>.*?(?:</system-reminder>|$)", " ", text)


def sanitize_memory_content(text: str) -> str:
    clean = compact_whitespace(strip_code_blocks(strip_system_reminder_blocks(text)))
    clean = re.sub(r"(?i)result_content_private_working_context:\s*", "", clean)
    clean = clean.replace("tool_call:", "tool call:")
    if len(clean) > MAX_AUTOMATIC_MEMORY_CHARS:
        clean = clean[:MAX_AUTOMATIC_MEMORY_CHARS].rstrip() + "..."
    return clean


def valid_memory_note(category: str, content: str) -> bool:
    if category not in PROJECT_MEMORY_CATEGORIES:
        return False
    if len(content.strip()) < MIN_AUTOMATIC_MEMORY_CHARS:
        return False
    if looks_like_raw_dump(content):
        return False
    return True


def looks_like_raw_dump(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True

    if stripped.count("\n") > 8:
        return True

    code_markers = ["def ", "class ", "import ", "from ", "function ", "const ", "pub fn", "use "]
    if sum(1 for marker in code_markers if marker in stripped) >= 3:
        return True

    if len(re.findall(r"[{}[\];]", stripped)) > 80:
        return True

    return False


def already_in_memory(note: str, existing_memory: str) -> bool:
    note_norm = normalize_for_compare(note)
    existing_norm = normalize_for_compare(clipped_text(existing_memory, BROKER_PROJECT_BRIEF_CHARS))

    if not note_norm or not existing_norm:
        return False

    if note_norm in existing_norm:
        return True

    note_words = significant_words(note_norm)
    if len(note_words) < 5:
        return False

    existing_words = set(significant_words(existing_norm))
    overlap = len([word for word in note_words if word in existing_words]) / max(1, len(note_words))
    return overlap >= 0.82


def significant_words(text: str) -> list[str]:
    stop = {
        "the",
        "and",
        "that",
        "this",
        "with",
        "from",
        "into",
        "for",
        "project",
        "memory",
        "file",
        "read",
        "important",
        "runtime",
    }
    return [word for word in re.findall(r"[a-z0-9_]{3,}", text.lower()) if word not in stop]


def normalize_for_compare(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-zA-Z0-9_./ -]", " ", text.lower())).strip()


def compact_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def clipped_text(text: str, limit: int) -> str:
    clean = str(text or "").strip()
    if len(clean) <= limit:
        return clean

    omitted = len(clean) - limit
    suffix = f"\n\n[truncated for memory broker: omitted {omitted} characters]"
    keep = max(0, limit - len(suffix))
    return clean[:keep].rstrip() + suffix
