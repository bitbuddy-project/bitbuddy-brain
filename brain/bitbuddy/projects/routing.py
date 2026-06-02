from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..memory.project import SKIP_DIRS, list_projects
from ..tools import (
    TOOL_CALL_PREFIX,
    XML_TOOL_CALL_TAGS,
    ToolCall,
    contains_unsupported_tool_output,
)


@dataclass(frozen=True)
class ProjectFileRequestResolution:
    tool_call: ToolCall | None = None
    clarification: str = ""


@dataclass(frozen=True)
class ProjectReferenceMatch:
    project: Any
    score: float
    reason: str = ""


@dataclass(frozen=True)
class CollectedResponse:
    chunks: list[Any]
    response_text: str
    response_emitted: bool = False
    thinking_emitted: bool = False
    tool_calls: list[ToolCall] | None = None


def may_be_tool_call_prefix(text: str) -> bool:
    stripped = text.lstrip()
    if not stripped:
        return True

    lowered = stripped.lower()
    prefixes = [TOOL_CALL_PREFIX, *[f"<{tag}" for tag in XML_TOOL_CALL_TAGS]]
    return any(prefix.startswith(lowered) or lowered.startswith(prefix) for prefix in prefixes)


def may_be_unsupported_tool_prefix(text: str) -> bool:
    stripped = text.lstrip()

    if not stripped:
        return True

    unsupported_prefixes = (
        "[BitBuddy]",
        "[bitbuddy]",
        "[read_file]",
        "[list_directory]",
        "[list_dir]",
        "[Read File:",
        "Reading File:",
        "Reading Files:",
        "<system-reminder>",
        "</system-reminder>",
    )

    return any(
        prefix.lower().startswith(stripped.lower()) or stripped.lower().startswith(prefix.lower())
        for prefix in unsupported_prefixes
    )


def response_text_before_unsupported_marker(text: str) -> str:
    lowered = text.lower()

    markers = (
        "tool_call:",
        "<bitbuddy_tool_call",
        "<tool_call",
        "<system-reminder>",
        "</system-reminder>",
        "[read_file]",
        "[list_directory]",
        "[list_dir]",
        "[read file:",
        "[bitbuddy]",
        "[tool call]",
        "your operational mode has changed",
    )

    indexes = [lowered.find(marker) for marker in markers if lowered.find(marker) != -1]

    if not indexes:
        return text

    return text[: min(indexes)].rstrip()


def shell_read_tool_calls(raw_paths: list[str], projects: list[Any]) -> tuple[list[ToolCall], bool]:
    calls: list[ToolCall] = []

    for raw_path in raw_paths:
        path = Path(raw_path).expanduser()

        if path.is_absolute():
            match = registered_project_relative_path(path, projects)

            if match is None:
                return [], True

            project_id, relative_path = match
            calls.append(ToolCall("read_file", {"project_id": project_id, "file_path": relative_path}))
            continue

        if len(projects) != 1 or not safe_relative_project_path(raw_path):
            return [], True

        calls.append(ToolCall("read_file", {"project_id": projects[0].id, "file_path": str(Path(raw_path))}))

    return calls, False


def registered_project_relative_path(path: Path, projects: list[Any]) -> tuple[str, str] | None:
    matches: dict[str, str] = {}
    resolved_path = path.resolve()

    for project in projects:
        for root in project.paths:
            base = root if root.is_dir() else root.parent

            try:
                relative_path = resolved_path.relative_to(base.resolve())
            except ValueError:
                continue

            if safe_relative_project_path(str(relative_path)):
                matches[project.id] = relative_path.as_posix()

    if len(matches) != 1:
        return None

    project_id, relative_path = next(iter(matches.items()))

    return project_id, relative_path


def safe_relative_project_path(path: str) -> bool:
    candidate = Path(path)
    return bool(path.strip()) and not candidate.is_absolute() and ".." not in candidate.parts


def tool_result_answer(result: Any) -> str:
    if not getattr(result, "ok", False):
        error = getattr(result, "error", "The tool failed.")
        return f"I couldn't read that file: {error}"

    content = str(getattr(result, "content", "")).strip()

    if not content:
        return "The file was read successfully, but it did not contain any text."

    return content


def clean_user_facing_model_response(text: str) -> str:
    """Strip leaked agent/transcript scaffolding from model responses."""
    clean = text.strip()

    if not clean:
        return ""

    if "</think>" in clean.lower():
        parts = re.split(r"</think>", clean, flags=re.IGNORECASE)
        clean = parts[-1].strip()

    response_match = re.search(r"\[Response\]\s*(.*)", clean, flags=re.IGNORECASE | re.DOTALL)

    if response_match:
        clean = response_match.group(1).strip()

    blocked_prefixes = ("[Context]", "[Action]", "[Observation]", "[Thought]", "[Tool]", "[Tool Call]", "[System]")

    kept_lines: list[str] = []
    skip_block = False

    for raw_line in clean.splitlines():
        line = raw_line.strip()

        if line.lower().startswith("<think") or line.lower().startswith("<system-reminder"):
            skip_block = True
            continue

        if "</think>" in line.lower() or "</system-reminder>" in line.lower():
            skip_block = False
            continue

        if skip_block:
            continue

        if any(line.startswith(prefix) for prefix in blocked_prefixes):
            continue

        kept_lines.append(raw_line)

    return "\n".join(kept_lines).strip()


def collected_thinking_text(chunks: list[Any]) -> str:
    return "".join(
        chunk.text
        for chunk in chunks
        if getattr(chunk, "kind", "") == "thinking" and getattr(chunk, "text", "")
    )


def clean_model_thinking_text(text: str, phase: str = "final") -> str:
    """Keep useful model thinking while stripping prompt leakage and tool plans."""
    clean = text.strip()

    if not clean:
        return ""

    clean = re.sub(r"</?think[^>]*>", "", clean, flags=re.IGNORECASE).strip()

    blocked_line_patterns = [
        r"^\s*[-*]\s*(?:I am|Produce|Keep|Do not|Stay focused|Runtime note|User asks|This is|Backend|Runtime)",
        r"^\s*(?:Thinking Process|Here's a thinking process|Analyze User Input|Identify Key Constraints|Identify Core Task|Check System Instructions|Check Constraints|Formulate Response|Determine Required Output|Output Generation|Self-Correction|Verification|Draft|Plan|Final plan|Refined thought)\b",
        r"^\s*\d+\.\s*(?:Analyze|Identify|Check|Formulate|Determine|Draft|Output|Self|Call|Use|Run|Invoke|Execute|Load|Get|Read|If|Then)\b",
        r"^\s*(?:First|Then|Next|After that|Depending on the result|If not found|If .+ found)\b.*\b(?:I|I'll|I will|can|could|should|need to)\b",
        r"^\s*(?:[-*]\s*)?User (?:asks|asked|message|query)\b",
        r"\bThe user is asking\b",
        r"^\s*(?:Wait,?\s*)?(?:Looking at|Looking closely at|Looking back at|Checking|Reviewing)\b.*\b(?:previous turns|conversation history|prompt structure|tool result|current context|conversation flow)\b",
        r"^\s*(?:Wait,?\s*)?(?:I need to|I should|I have to|I am expected to|I'm supposed to)\b.*\b(?:act as if|simulate|hallucinate|be honest|summarize|answer)\b",
        r"\b(?:This implies|This looks like|This is likely|Actually, looking|However, as)\b.*\b(?:tool result|hallucination|previous turn|current context|Vanta)\b",
        r"\bThe user wants\b",
        r"^\s*(?:From|Based on) the registered projects list\b",
        r"^\s*After getting the result\b",
        r"^\s*Reading `?[^`]+`? so the answer can use exact project context\.?$",
        r"\bLooking at the conversation history\b",
        r"\bI am expected to act\b",
        r"\bIf I am simulating\b",
        r"^\s*(?:Wait|Actually|Ah|But),?\b",
        r"\b(?:system prompt|system instructions|prompt says|instructions say|instruction says|constraints|constraint|forbidden|matches constraints|all constraints met|template artifact)\b",
        r"\b(?:must not|must only|do not|cannot|can't|should not|strictly limits|adhering to|as requested by system)\b",
        r"\b(?:thinking-only|routing pass|Thinking panel|user-facing|internal orientation|output should|entire response)\b",
        r"\b(?:backend|runtime)\b.*\b(?:tool|routing|execution|deterministic|handle|handles|handled|owns|will)\b",
        r"\b(?:awaiting|waiting for)\s+(?:backend|runtime)\b",
        r"\b(?:Loaded BitBuddy Project Context|I don't see|do not see|is missing|not provided|no context provided|without external context)\b",
        r"\b(?:general knowledge|public meaning|computer vision|object detection|YOLO|Faster R-CNN|anchor boxes|real estate|company named)\b",
        r"^\s*\[(?:Context|Action|Observation|Thought|Tool|Tool Call|System|Response|get_project_brief|list_projects|get_project_memory|read_file|Output Generation)]",
        r"^\s*(?:Context|Action|Observation|Thought|Tool|Tool Call|System|Response|Plan)\s*:",
        r"\b(?:Let's|Let me)\s+(?:invoke|call|use|run|execute|start|get|load|read|check)\b",
        r"\b(?:I\s+)?(?:should|need to|will|am going to|have to)\s+(?:call|use|run|invoke|execute|get|load|read|check|answer|list|proceed|provide|inform|ask)\b",
        r"\bI can\s+(?:provide|answer|ask|inform|proceed|get|load|read|check)\b",
        r"\btool\s*(?:call|transcript|envelope)\b",
        r"^(?:✅|Output matches|Proceeds|Ready|Done|All good)\b",
    ]

    kept: list[str] = []

    for raw_line in clean.splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in blocked_line_patterns):
            continue

        compact = line.lstrip("-*• \t")

        if compact != line and len(compact.split()) < 4:
            continue

        # Do not let repetitive scratchpad loops fill the visible Thinking panel.
        normalized = " ".join(line.lower().split())
        if any(" ".join(existing.lower().split()) == normalized for existing in kept[-5:]):
            continue

        kept.append(line)

        if len(kept) >= 10:
            break

    result = "\n".join(kept).strip()
    if len(result) > 1200:
        result = result[:1200].rstrip() + "..."
    return result


def contains_model_thinking_tool_plan(text: str) -> bool:
    if not text.strip():
        return False

    leak_patterns = [
        r"^\s*(?:Plan|Action|Observation|Tool Call)\s*:",
        r"\[(?:Action|Observation|Tool Call)]",
    ]

    return any(re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE) for pattern in leak_patterns)


def contains_final_answer_tool_leak(text: str) -> bool:
    """Return True when a supposed final answer is still an agent/tool transcript."""
    if not text.strip():
        return False

    leak_patterns = [
        r"<\s*/?\s*think\b",
        r"\[(?:Context|Action|Observation|Thought|Tool|Tool Call|System|Response)]",
        r"^\s*(?:Context|Action|Observation|Thought|Tool|Tool Call|System)\s*:",
        r"<bitbuddy_tool_call>",
        r"</bitbuddy_tool_call>",
        r"\b(?:I see you mentioned|you mentioned)\b.*\b(?:let me|pull up|look up|check)\b",
        r"\bTool Call\b",
    ]

    return any(re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE) for pattern in leak_patterns)


def normalize_project_reference(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value.lower()).split())


def candidate_project_names_from_text(user_text: str) -> list[str]:
    candidates: list[str] = []

    patterns = [
        r"\b(?:do you know about|what do you know about|tell me about|summari[sz]e|overview of|briefing on|are you familiar with|familiar with|do you know|know about)\s+([A-Za-z0-9_. -]{2,80})",
        r"\b(?:project|repo|repository)\s+([A-Za-z0-9_. -]{2,80})",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, user_text, flags=re.IGNORECASE):
            candidate = match.group(1).strip().strip("?.!,;:")
            candidate = re.split(
                r"\b(?:and|or|please|thanks|now)\b",
                candidate,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip()

            if candidate and not is_generic_project_area_reference(candidate):
                candidates.append(candidate)

    return candidates


def is_generic_project_area_reference(value: str) -> bool:
    normalized = normalize_project_reference(value)

    if not normalized:
        return True

    generic_area_terms = {
        "backend",
        "frontend",
        "front end",
        "web",
        "ui",
        "api",
        "server",
        "database",
        "db",
        "source",
        "code",
        "codebase",
        "portion",
        "part",
        "area",
        "side",
        "piece",
        "section",
        "notes",
        "gallery",
        "folder",
        "folders",
    }

    tokens = set(normalized.split())

    return bool(tokens) and tokens <= generic_area_terms


def meaningful_project_terms(normalized: str) -> set[str]:
    stop = {
        "the",
        "this",
        "that",
        "project",
        "repo",
        "repository",
        "app",
        "code",
        "file",
        "files",
        "about",
        "know",
        "what",
        "tell",
        "show",
        "read",
        "open",
        "please",
        "can",
        "you",
        "bitbuddy",
    }

    return {token for token in normalized.split() if len(token) >= 3 and token not in stop}


def ranked_project_reference_matches(user_text: str, projects: list[Any]) -> list[ProjectReferenceMatch]:
    normalized_text = normalize_project_reference(user_text)

    if not normalized_text:
        return []

    candidate_names = candidate_project_names_from_text(user_text)
    matches: list[ProjectReferenceMatch] = []

    for project in projects:
        project_name = str(project.name)
        project_id = str(project.id)
        normalized_name = normalize_project_reference(project_name)
        normalized_id = normalize_project_reference(project_id)
        project_terms = meaningful_project_terms(normalized_name) | meaningful_project_terms(normalized_id)

        score = 0.0
        reasons: list[str] = []

        if normalized_name and re.search(rf"(?:^| ){re.escape(normalized_name)}(?: |$)", normalized_text):
            score += 40.0
            reasons.append("exact name")
        elif normalized_name and normalized_name in normalized_text:
            score += 32.0
            reasons.append("name substring")

        if normalized_id and re.search(rf"(?:^| ){re.escape(normalized_id)}(?: |$)", normalized_text):
            score += 35.0
            reasons.append("exact id")

        text_terms = meaningful_project_terms(normalized_text)
        shared_terms = project_terms & text_terms

        if shared_terms:
            score += min(18.0, 6.0 * len(shared_terms))
            reasons.append("shared terms: " + ", ".join(sorted(shared_terms)[:4]))

        for candidate in candidate_names:
            candidate_norm = normalize_project_reference(candidate)
            candidate_terms = meaningful_project_terms(candidate_norm)

            if not candidate_norm or not candidate_terms:
                continue

            if candidate_norm == normalized_name or candidate_norm == normalized_id:
                score += 25.0
                reasons.append(f"candidate exact: {candidate}")
                continue

            if candidate_norm in normalized_name or normalized_name in candidate_norm:
                score += 18.0
                reasons.append(f"candidate substring: {candidate}")
                continue

            overlap = candidate_terms & project_terms

            if overlap:
                score += min(12.0, 4.0 * len(overlap))
                reasons.append("candidate overlap")

        if score >= 6.0:
            matches.append(ProjectReferenceMatch(project=project, score=score, reason="; ".join(reasons)))

    return sorted(matches, key=lambda match: match.score, reverse=True)


def resolve_project_file_request(user_text: str, projects: list[Any]) -> ProjectFileRequestResolution | None:
    requested_path = requested_project_file_path(user_text)

    if requested_path is None:
        return None

    if not projects:
        return ProjectFileRequestResolution(
            clarification="No projects are registered yet. Register a project first, then I can read project files through BitBuddy's structured tools."
        )

    matches = ranked_project_reference_matches(user_text, projects)

    if matches:
        best = matches[0]
        tied = [match for match in matches if abs(match.score - best.score) <= 2.0 and match.score >= 10.0]

        if len(tied) > 1:
            return ProjectFileRequestResolution(
                clarification=project_clarification("Which project should I read that file from?", tied)
            )

        if best.score >= 10.0:
            return resolve_project_file_path(best.project, requested_path)

    projects_with_file = [project for project in projects if project_relative_file_exists(project, requested_path)]

    if len(projects_with_file) == 1:
        return resolve_project_file_path(projects_with_file[0], requested_path)

    if len(projects) == 1:
        return resolve_project_file_path(projects[0], requested_path)

    project_names = "\n".join(f"* {project.name}" for project in projects)

    return ProjectFileRequestResolution(
        clarification=f"Which project do you mean? I have these registered:\n\n{project_names}"
    )


def resolve_project_file_path(project: Any, requested_path: str) -> ProjectFileRequestResolution:
    if project_relative_file_exists(project, requested_path):
        return ProjectFileRequestResolution(
            tool_call=ToolCall("read_file", {"project_id": project.id, "file_path": requested_path})
        )

    if requested_path.lower() != "readme.md":
        return ProjectFileRequestResolution(
            tool_call=ToolCall("read_file", {"project_id": project.id, "file_path": requested_path})
        )

    readmes = find_project_readmes(project)

    if len(readmes) == 1:
        return ProjectFileRequestResolution(
            tool_call=ToolCall("read_file", {"project_id": project.id, "file_path": readmes[0]})
        )

    if len(readmes) > 1:
        readme_lines = "\n".join(f"* {path}" for path in readmes)

        return ProjectFileRequestResolution(
            clarification=f"I found multiple README files in {project.name}. Which one do you mean? You can also say \"all\" to read all of them.\n\n{readme_lines}"
        )

    return ProjectFileRequestResolution(clarification=f"I couldn't find a README.md file in {project.name}.")


def project_relative_file_exists(project: Any, relative_path: str) -> bool:
    if not safe_relative_project_path(relative_path):
        return False

    relative = Path(relative_path)

    if any(part in SKIP_DIRS for part in relative.parts):
        return False

    for root in project.paths:
        base = root if root.is_dir() else root.parent

        if (base / relative).is_file():
            return True

    return False


def find_project_readmes(project: Any) -> list[str]:
    readmes: set[str] = set()

    for root in project.paths:
        base = root if root.is_dir() else root.parent

        if not base.exists():
            continue

        for current_root, dirnames, filenames in os.walk(base):
            dirnames[:] = [dirname for dirname in dirnames if dirname not in SKIP_DIRS]
            current_path = Path(current_root)

            for filename in filenames:
                if filename.lower() != "readme.md":
                    continue

                path = current_path / filename

                try:
                    relative = path.relative_to(base).as_posix()
                except ValueError:
                    continue

                if safe_relative_project_path(relative):
                    readmes.add(relative)

    return sorted(readmes)


def requested_project_file_path(user_text: str) -> str | None:
    normalized = user_text.lower()

    wants_file = re.search(
        r"\b(read|show|open|inspect|summari[sz]e|display|look at|check|review|explain)\b",
        normalized,
    )

    if not wants_file:
        return None

    if re.search(r"(?<![\w./-])readme(?:\.md)?(?![\w./-])", normalized):
        return "README.md"

    quoted_path = extract_quoted_project_path(user_text)

    if quoted_path:
        return quoted_path

    inline_path = extract_inline_project_path(user_text)

    if inline_path:
        return inline_path

    return None


def extract_quoted_project_path(text: str) -> str | None:
    for match in re.finditer(r"[`'\"]([^`'\"]+)[`'\"]", text):
        candidate = clean_project_path_candidate(match.group(1))

        if candidate:
            return candidate

    return None


def extract_inline_project_path(text: str) -> str | None:
    path_pattern = r"(?<![\w./-])([A-Za-z0-9_.~-]+(?:/[A-Za-z0-9_.~-]+)+|[A-Za-z0-9_.~-]+\.[A-Za-z0-9]{1,8})(?![\w./-])"

    for match in re.finditer(path_pattern, text):
        candidate = clean_project_path_candidate(match.group(1))

        if candidate:
            return candidate

    return None


def clean_project_path_candidate(value: str) -> str | None:
    candidate = value.strip().strip(".,:;()[]{}")

    if not candidate:
        return None

    if candidate.lower() in {"bitbuddy", "anchorbox"}:
        return None

    if safe_relative_project_path(candidate) and ("/" in candidate or Path(candidate).suffix):
        return Path(candidate).as_posix()

    return None


def explicit_project_reference(user_text: str, projects: list[Any]) -> Any | None:
    matches = ranked_project_reference_matches(user_text, projects)

    if not matches:
        return None

    best = matches[0]
    tied = [match for match in matches if abs(match.score - best.score) <= 2.0 and match.score >= 10.0]

    if len(tied) == 1 and best.score >= 10.0:
        return best.project

    return None


def project_clarification(question: str, matches: list[ProjectReferenceMatch]) -> str:
    lines = "\n".join(f"* {match.project.name}" for match in matches[:8])

    return f"{question} I found multiple likely matches:\n\n{lines}"


def is_registered_project_id(project_id: str) -> bool:
    if not project_id:
        return False

    try:
        return any(project.id == project_id for project in list_projects())
    except Exception:
        return False


def extract_project_identity_from_text(text: str) -> tuple[str, str, str]:
    try:
        parsed = json.loads(text)

        if isinstance(parsed, dict):
            name = str(parsed.get("name", "") or parsed.get("project_name", ""))
            project_id = str(parsed.get("id", "") or parsed.get("project_id", ""))
            path = str(parsed.get("path", "") or parsed.get("repo_path", ""))

            return name, project_id, path
    except json.JSONDecodeError:
        pass

    name = ""
    project_id = ""
    path = ""

    for line in text.splitlines()[:30]:
        stripped = line.strip().strip("#*- ")
        lowered = stripped.lower()

        if lowered.startswith("project:") or lowered.startswith("name:"):
            name = stripped.split(":", 1)[1].strip()
        elif lowered.startswith("project id:") or lowered.startswith("id:"):
            project_id = stripped.split(":", 1)[1].strip().strip("`")
        elif lowered.startswith("path:") or lowered.startswith("repo path:"):
            path = stripped.split(":", 1)[1].strip().strip("`")

    return name, project_id, path


def truncate_for_fallback(text: str, limit: int) -> str:
    clean = text.strip()

    if len(clean) <= limit:
        return clean

    return clean[:limit].rstrip() + "\n..."


def summarize_list_projects_result(body: str) -> str:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return f"I checked the registered projects. Here's what BitBuddy returned:\n\n{truncate_for_fallback(body, 1800)}"

    projects = parsed.get("projects") if isinstance(parsed, dict) else None

    if not isinstance(projects, list) or not projects:
        return "I checked BitBuddy's registered projects, but there aren't any registered yet."

    lines = ["I checked BitBuddy's registered projects. I found:"]

    for project in projects[:12]:
        if not isinstance(project, dict):
            continue

        name = str(project.get("name", "Unnamed project"))
        project_id = str(project.get("id", ""))
        paths = project.get("paths", [])
        first_path = str(paths[0]) if isinstance(paths, list) and paths else ""
        suffix = f" — `{first_path}`" if first_path else ""

        lines.append(f"* {name} `{project_id}`{suffix}")

    if len(projects) > 12:
        lines.append(f"* ...and {len(projects) - 12} more.")

    return "\n".join(lines)


def successful_tool_results(messages: list[dict[str, str]], preferred_tools: list[str]) -> list[tuple[str, str]]:
    preferred = set(preferred_tools)
    results: list[tuple[str, str]] = []

    for message in messages:
        content = message.get("content", "")

        if not isinstance(content, str) or not content.startswith("[BitBuddy Tool Result]"):
            continue

        tool_match = re.search(r"^tool:\s*(.+)$", content, flags=re.MULTILINE)
        status_match = re.search(r"^status:\s*(.+)$", content, flags=re.MULTILINE)

        if not tool_match or not status_match:
            continue

        tool_name = tool_match.group(1).strip()

        if tool_name not in preferred or status_match.group(1).strip().lower() != "success":
            continue

        body = content.split("\n\n", 1)[1].strip() if "\n\n" in content else ""
        results.append((tool_name, body))

    return results


def latest_successful_tool_result(messages: list[dict[str, str]], preferred_tools: list[str]) -> tuple[str, str] | None:
    preferred = set(preferred_tools)

    for message in reversed(messages):
        content = message.get("content", "")

        if not isinstance(content, str) or not content.startswith("[BitBuddy Tool Result]"):
            continue

        tool_match = re.search(r"^tool:\s*(.+)$", content, flags=re.MULTILINE)
        status_match = re.search(r"^status:\s*(.+)$", content, flags=re.MULTILINE)

        if not tool_match or not status_match:
            continue

        tool_name = tool_match.group(1).strip()

        if tool_name not in preferred or status_match.group(1).strip().lower() != "success":
            continue

        body = content.split("\n\n", 1)[1].strip() if "\n\n" in content else ""

        return tool_name, body

    return None
