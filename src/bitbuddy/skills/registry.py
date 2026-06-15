from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from ..paths import SKILLS_DIR, ensure_app_dirs


MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_SKILL_CONTENT_CHARS = 100_000
MAX_SUPPORT_FILE_CHARS = 100_000
SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
ALLOWED_SUPPORT_DIRS = {"references", "templates", "scripts", "assets"}
USAGE_FILE = ".usage.json"


@dataclass(frozen=True)
class SkillValidation:
    ok: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    version: str
    path: Path
    body: str
    frontmatter: dict[str, Any]
    metadata: dict[str, Any]
    usage: dict[str, Any]
    archived: bool = False


STARTER_SKILLS: dict[str, str] = {
    "skill-authoring": """---
name: skill-authoring
description: Use when creating, improving, reviewing, or organizing BitBuddy skills under ~/.bitbuddy/skills/.
version: 1.0.0
metadata:
  bitbuddy:
    tags: [skills, authoring, self-maintenance]
    related_skills: [skill-curation]
    risk_level: medium
    maintained_by: bitbuddy
---

# Skill Authoring

## Overview

Use this workflow to create or improve reusable BitBuddy procedures. Skills are procedural memory: they describe how to do a class of work. Do not use skills for one-off facts, preferences, secrets, or project notes that belong in memory.

## When To Use

- The user asks BitBuddy to create, update, or maintain a skill.
- A workflow is repeated often enough that future BitBuddy sessions should remember the process.
- An existing skill is vague, stale, or missing verification steps.

## Workflow

1. Inspect existing skills before creating a new one.
2. Prefer patching a related skill over creating a narrow duplicate.
3. Use a lowercase hyphenated name under 64 characters.
4. Keep `description` trigger-focused: "Use when ...".
5. Include Overview, When To Use, Workflow, Common Pitfalls, and Verification.
6. Put large references in `references/`, templates in `templates/`, optional helper scripts in `scripts/`, and media in `assets/`.
7. Validate the skill after writing it.

## Common Pitfalls

- Creating skills that only apply to a single completed task.
- Putting durable facts in skills instead of memory.
- Writing broad descriptions that make activation unreliable.
- Adding scripts and assuming they will run automatically. They will not.

## Verification

- The skill has valid frontmatter and non-empty body.
- The description clearly says when to use it.
- The skill does not duplicate another active skill.
- Supporting files stay inside the skill folder.
""",
    "skill-curation": """---
name: skill-curation
description: Use when auditing, merging, archiving, or improving the quality of BitBuddy's skill library.
version: 1.0.0
metadata:
  bitbuddy:
    tags: [skills, curation, maintenance]
    related_skills: [skill-authoring]
    risk_level: low
    maintained_by: bitbuddy
---

# Skill Curation

## Overview

Use this skill to keep `~/.bitbuddy/skills/` small, useful, and easy to activate. Skill curation is about reducing duplication and sharpening triggers.

## When To Use

- The user asks what skills exist or which skills need cleanup.
- Multiple skills overlap.
- A skill has not been used and appears stale.
- BitBuddy is about to add a new skill and should check for duplicates.

## Workflow

1. List active skills and review names/descriptions first.
2. Group skills by domain and trigger.
3. Merge narrow duplicate procedures into the strongest existing skill.
4. Archive stale or misleading skills instead of deleting them.
5. Patch descriptions so each skill has a clear activation boundary.
6. Validate changed skills.

## Common Pitfalls

- Deleting user-authored skills instead of archiving them.
- Optimizing for many tiny skills rather than useful reusable workflows.
- Changing a skill's name without considering references from related skills.

## Verification

- Duplicate triggers are reduced.
- Archived skills are hidden from normal prompt discovery.
- Active skills still have valid frontmatter.
""",
    "systematic-debugging": """---
name: systematic-debugging
description: Use when diagnosing bugs, test failures, crashes, regressions, or unexpected technical behavior before fixing.
version: 1.0.0
metadata:
  bitbuddy:
    tags: [debugging, root-cause, tests]
    related_skills: []
    risk_level: low
    maintained_by: bitbuddy
---

# Systematic Debugging

## Overview

Find the root cause before changing code. Quick guesses often mask the real issue and create regressions.

## When To Use

- Tests fail.
- The app behaves differently than expected.
- A stack trace, error message, or regression appears.
- A previous fix did not work.

## Workflow

1. Read the exact error and relevant code.
2. Reproduce the issue with the smallest command or interaction possible.
3. Check recent changes and nearby working patterns.
4. Trace the bad value or behavior to its source.
5. Make the smallest fix that addresses the source.
6. Run the targeted verification, then broader checks if needed.

## Common Pitfalls

- Fixing the symptom visible in the stack trace without tracing upstream.
- Making multiple speculative changes at once.
- Ignoring warnings because there are no hard errors.

## Verification

- The failure is reproducible before the fix.
- The fix is minimal and source-level.
- The relevant test or check now passes.
""",
    "frontend-svelte-workflow": """---
name: frontend-svelte-workflow
description: Use when editing BitBuddy's SvelteKit/Svelte 5 frontend components, stores, or UI styling.
version: 1.0.0
metadata:
  bitbuddy:
    tags: [frontend, svelte, ui]
    related_skills: []
    risk_level: low
    maintained_by: bitbuddy
---

# Frontend Svelte Workflow

## Overview

Use BitBuddy's existing Svelte 5 patterns and keep UI edits minimal, scoped, and verified.

## When To Use

- Editing `web/src/**/*.svelte` or `web/src/lib/stores/*.svelte.ts`.
- Fixing chat UI, layout, styling, or Svelte reactivity issues.
- Adding frontend API calls or UI state.

## Workflow

1. Search for the component or CSS class before editing.
2. Follow Svelte 5 runes already used in the codebase: `$props`, `$state`, `$derived`, `$effect`.
3. Keep styles scoped to the component unless a global token is needed.
4. Preserve established visual language unless the user asks for redesign.
5. Run `npm run check` from `web/` after frontend changes.

## Common Pitfalls

- Adding legacy `export let` props in rune-based components.
- Editing generated `.svelte-kit` output instead of source files.
- Adding global CSS for a local component issue.

## Verification

- `npm run check` passes or only known unrelated warnings remain.
- The changed component still works on narrow and wide layouts when relevant.
""",
    "bitbuddy-development": """---
name: bitbuddy-development
description: Use when modifying BitBuddy's Python backend, Svelte web app, local config, tools, memory, autonomy, or skills code.
version: 1.0.0
metadata:
  bitbuddy:
    tags: [bitbuddy, backend, frontend, architecture]
    related_skills: [frontend-svelte-workflow, systematic-debugging, skill-authoring]
    risk_level: medium
    maintained_by: bitbuddy
---

# BitBuddy Development

## Overview

BitBuddy is a local-first companion with a Python backend under `src/bitbuddy`, a SvelteKit web app under `web/`, and user data under `~/.bitbuddy`.

## When To Use

- Working on BitBuddy itself.
- Adding backend tools, prompt context, HTTP API routes, memory behavior, autonomy behavior, or skills.
- Debugging interactions between the Python server and web UI.

## Workflow

1. Inspect source before assuming architecture.
2. Keep changes small and source-level.
3. Add or update targeted tests for backend behavior.
4. For frontend edits, run `npm run check` in `web/`.
5. For backend edits, run focused `pytest` tests first.
6. Never edit generated `.svelte-kit` files.

## Key Paths

- Backend: `src/bitbuddy/`
- Tools: `src/bitbuddy/toolbox/`
- Prompt construction: `src/bitbuddy/prompt_builder.py`
- HTTP API: `src/bitbuddy/http_api.py`
- Frontend: `web/src/`
- Local user data: `~/.bitbuddy/`

## Verification

- Relevant Python tests pass.
- Relevant Svelte checks pass for frontend work.
- User data writes stay under `~/.bitbuddy` unless explicitly requested.
""",
    "kicad-project-generation": """---
name: kicad-project-generation
description: Use when creating, editing, validating, or exporting KiCad electronics projects, schematics, PCB layouts, footprints, or generated KiCad artifact files.
version: 1.0.0
metadata:
  bitbuddy:
    tags: [kicad, electronics, artifacts, cad]
    related_skills: []
    risk_level: medium
    maintained_by: bitbuddy
---

# KiCad Project Generation

## Overview

Prefer deterministic file/script generation over GUI automation. KiCad project files are text-based enough that many tasks can be completed by generating `.kicad_pro`, `.kicad_sch`, `.kicad_pcb`, symbol, footprint, BOM, or helper script files directly, then validating with `kicad-cli` when available.

## When To Use

- The user asks to create a KiCad project, schematic, PCB, footprint, or electronics design artifact.
- The user asks to modify existing KiCad files.
- The user asks to export KiCad outputs such as SVG, PDF, Gerber, drill, or BOM files.
- The user wants KiCad opened or inspected after generated files exist.

## Workflow

1. Clarify requirements only when necessary: board purpose, connectors, voltage/current, dimensions, layers, components, and desired outputs.
2. Create generated work under `~/.bitbuddy/artifacts/<project-name>/` unless the user explicitly asks to edit an existing project.
3. Use `make_directory` and `write_file` for project files and helper scripts. Avoid shell heredocs for large file content.
4. For complex KiCad S-expressions, write a small Python generator script first, then run it with `run_shell_command` using `working_directory`.
5. Prefer command-line validation/export with `kicad-cli` when installed. Useful checks include `kicad-cli --help`, `kicad-cli sch export ...`, and `kicad-cli pcb export ...`.
6. If `kicad-cli` is missing or a GUI-only operation is required, use desktop MCP only after files exist: inspect windows/apps, open KiCad, then verify state.
7. Report generated paths, validation commands run, and any limitations or assumptions.

## File Strategy

- `.kicad_pro`: project metadata/config shell.
- `.kicad_sch`: schematic S-expression; generate stable UUIDs and keep references readable.
- `.kicad_pcb`: board S-expression; include board outline, footprints, nets, tracks, zones when known.
- `scripts/`: Python generators, BOM helpers, conversion scripts.
- `exports/`: generated PDF/SVG/Gerber/drill/BOM outputs.

## Common Pitfalls

- Using GUI automation before trying direct file generation.
- Inventing exact electrical constraints without asking or stating assumptions.
- Editing an existing user project without permission.
- Generating syntactically plausible files without running any available validation/export step.
- Treating old KiCad formats and KiCad 6/7/8 S-expression formats as interchangeable.

## Verification

- Generated files exist under the intended artifact/project path.
- Helper scripts run successfully if used.
- `kicad-cli` validation/export commands pass when available.
- If opened in KiCad, desktop MCP verifies the project/schematic/PCB window is visible and relevant content loaded.
""",
    "personal-check-in": """---
name: personal-check-in
description: Use when the user seems to want emotional support, is venting, mentions stress or frustration, or when starting a conversation after a gap with no clear task.
version: 1.0.0
metadata:
  bitbuddy:
    tags: [companion, emotional, check-in, wellbeing]
    risk_level: low
    maintained_by: bitbuddy
---

# Personal Check-In

## Overview

A check-in is not a therapy session. It is a moment of real contact — acknowledge what's present, stay grounded, and let the user lead. Resist the urge to fix, advise, or pivot to tasks.

## Reading the Room

**Low-energy signals**: short messages, typos, "ugh", "whatever", "idk", one-word replies, trailing off.
**High-stress signals**: "I'm so frustrated", "nothing is working", "I don't know what to do", capitalised words, multiple exclamation marks.
**Distracted/rushed signals**: fragmented sentences, context-switching mid-message, "quick question" openers on obviously large topics.
**Return after a gap**: resume naturally — reference what you were working on if relevant, but don't force continuity if they open with something new.

## When Checking In

1. Acknowledge what they said before asking anything. "That sounds exhausting" beats "How are you feeling about that?"
2. Ask **one** grounded question, not several. Let the conversation breathe.
3. Match their energy level. If they're brief, be brief. If they want to talk, stay present.
4. Avoid: "I'm here for you!", "That must be hard!", generic affirmations, unsolicited advice, pivoting to productivity mid-check-in.
5. If they shift to a task, follow them. Don't hold them in the emotional register.

## Common Pitfalls

- Over-labeling emotions: "It sounds like you're feeling overwhelmed and anxious and..." — pick one, or none.
- Mirroring too literally — paraphrasing their exact words back at them feels clinical.
- Injecting optimism before they've been heard.
- Offering three solutions when they didn't ask for solutions.

## Verification

- The user felt heard, not processed.
- You asked at most one question.
- You didn't give unsolicited advice in the first response.
""",
    "research-synthesis": """---
name: research-synthesis
description: Use when the user asks you to research, investigate, compare, or summarize a topic that requires gathering and cross-referencing multiple sources.
version: 1.0.0
metadata:
  bitbuddy:
    tags: [research, synthesis, web, knowledge]
    risk_level: low
    maintained_by: bitbuddy
---

# Research Synthesis

## Overview

Good research synthesis surfaces the **shape of the answer**, not just facts. Your job is to find where sources agree, where they conflict, and what still isn't known — then present it in a way that helps the user make a decision or take action.

## Source Priority

1. **Memory first**: Check episodic and semantic memory for things you already know. Avoid redundant searches.
2. **Web search**: Use `web_search` for current information, specific claims, documentation, or anything where recency matters.
3. **Ask the user**: If the question is ambiguous or the goal matters for how to frame the answer, ask before diving deep.

## Synthesis Workflow

1. Identify the real question. "What is X?" is often a proxy for "Should I use X?" or "How does X compare to Y?"
2. Gather from 2-4 sources minimum before synthesizing.
3. Look for: consensus, contradictions, recency gaps, missing perspectives.
4. Structure the output as: **tl;dr → main findings → caveats/open questions**.
5. Cite uncertainty explicitly: "As of [date]…", "Sources conflict on this…", "I don't have reliable data on…"

## Presenting Results

- Lead with what the user can act on.
- Surface contradictions rather than smoothing them over.
- If sources are thin or low-quality, say so. Don't manufacture confidence.
- Keep the tl;dr scannable — one to three sentences max.

## Common Pitfalls

- Summarizing only the first result found.
- Presenting conflicting information as settled.
- Over-qualifying every sentence to the point of uselessness.
- Burying the actionable answer at the end.

## Verification

- The tl;dr is independently useful without reading the rest.
- Contradictions or gaps in sources are noted.
- Uncertainty is calibrated, not absent or excessive.
""",
    "writing-collaborator": """---
name: writing-collaborator
description: Use when the user wants help drafting, editing, reviewing, or improving a piece of writing — emails, docs, READMEs, posts, or any other text.
version: 1.0.0
metadata:
  bitbuddy:
    tags: [writing, editing, drafting, communication]
    risk_level: low
    maintained_by: bitbuddy
---

# Writing Collaborator

## Overview

Writing help comes in three distinct modes. Identify which one applies before proceeding — they require different approaches.

- **Draft for me**: User wants you to write from scratch. Ask about audience and tone once if unclear; then produce.
- **Edit mine**: User has a draft. Your job is to improve it while preserving their voice. Don't rewrite.
- **Review mine**: User wants feedback, not a rewrite. Identify specific issues and explain why, but don't silently fix.

## Principles

**Voice preservation**: When editing, keep the user's phrasing where it works. Don't homogenize toward "clean professional prose" unless that's what they asked for.

**Audience first**: Good writing is calibrated to who reads it. If you don't know the audience, ask once. Don't ask multiple clarifying questions before starting.

**One pass, clear scope**: Don't silently fix everything. If you're doing a review, name the issues without fixing them. If you're editing, fix but don't restructure unless they asked.

## Mode-Specific Guidance

### Drafting
1. Confirm: audience, length, tone (if not clear from context).
2. Produce a complete draft. Don't write placeholders.
3. Offer one variant if the tone is uncertain.

### Editing
1. Fix: grammar, clarity, flow, word choice.
2. Preserve: sentence structure they clearly intended, idiomatic phrases, deliberate informality.
3. Flag (don't fix): structural changes, missing sections, possible tone mismatches.

### Reviewing
1. Identify the 2-3 most impactful issues first.
2. Be specific: quote the problem sentence, explain why it's a problem.
3. Don't fix unless asked.

## Common Pitfalls

- Rewriting in "editor voice" rather than the user's voice.
- Fixing style and grammar but not flagging unclear logic or missing information.
- Over-asking: one clarifying question max, then proceed.
- Smoothing over intentional stylistic choices (sentence fragments, em dashes, etc.).

## Verification

- Mode was correctly identified (draft / edit / review).
- User's voice is recognizable in edited output.
- Feedback is specific, not generic ("this paragraph is unclear" is not feedback).
""",
    "task-breakdown": """---
name: task-breakdown
description: Use when the user has a vague goal, a large task, or wants help planning or prioritizing work before starting.
version: 1.0.0
metadata:
  bitbuddy:
    tags: [planning, tasks, productivity, breakdown]
    risk_level: low
    maintained_by: bitbuddy
---

# Task Breakdown

## Overview

Breaking down tasks is only useful if it helps the user start or decide. Avoid producing elaborate plans that don't survive contact with reality. Favor identifying the **first concrete action** over mapping the whole project.

## Constraint Gathering (ask once, then proceed)

Before breaking down, check if you know:
- **Deadline or horizon**: When does this need to be done?
- **Blockers or dependencies**: Is anything blocked on something external?
- **Energy/capacity**: Is this a high-focus task or something to fill slack time with?

Don't ask all three questions at once. Ask the most important one, or infer from context and proceed.

## Breakdown Structure

Produce a tiered list:

**Must** — The minimum viable outcome. What has to be done for this to count as done?
**Should** — High-value additions that improve the result if time allows.
**Nice-to-have** — Things to do only if must + should are complete and time remains.

## Finding the First Action

After the breakdown, identify:
1. The one thing most likely to be blocked (dependency, unclear spec, waiting on someone) — surface it immediately.
2. The single best first action given current energy/context.

## Scope Control

- If the user's "task" is actually a project (multiple independent deliverables), name that explicitly and break at the project level first.
- Don't detail a phase until they've agreed on the shape of the whole.
- Resist adding tasks for tasks' sake ("write tests for everything", "document all functions") unless they asked.

## Common Pitfalls

- Producing a 20-step plan for a 2-hour task.
- Missing the implicit constraint (e.g., it has to run on their current machine, it needs to match their existing style).
- Not identifying what's actually blocked vs. what just feels hard.
- Asking for all constraints before producing anything.

## Verification

- Must/should/nice-to-have are distinct and correctly categorized.
- The first concrete action is named.
- Any blockers are surfaced before the plan proceeds past them.
""",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_skills_dir() -> None:
    ensure_app_dirs()
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)


def seed_starter_skills() -> None:
    ensure_skills_dir()
    for name, content in STARTER_SKILLS.items():
        skill_dir = SKILLS_DIR / name
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            continue
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_file.write_text(content, encoding="utf-8")
        usage = load_usage()
        usage.setdefault(
            name,
            {
                "created_at": now_iso(),
                "created_by": "bitbuddy",
                "last_used_at": None,
                "last_viewed_at": None,
                "last_patched_at": None,
                "patch_count": 0,
                "pinned": False,
                "state": "active",
                "use_count": 0,
                "view_count": 0,
            },
        )
        save_usage(usage)


def list_skills(include_archived: bool = False) -> list[Skill]:
    seed_starter_skills()
    skills = []
    for skill_file in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        try:
            skill = parse_skill_file(skill_file)
        except ValueError:
            continue
        if skill.archived and not include_archived:
            continue
        skills.append(skill)
    return skills


def load_skill(name: str, *, mark_viewed: bool = True) -> Skill:
    seed_starter_skills()
    clean = validate_skill_name(name)
    skill_file = skill_dir_for(clean) / "SKILL.md"
    if not skill_file.exists():
        raise ValueError(f"Skill not found: {clean}")
    skill = parse_skill_file(skill_file)
    if mark_viewed:
        update_usage(clean, viewed=True, used=True)
        skill = parse_skill_file(skill_file)
    return skill


def validate_skill(name: str) -> SkillValidation:
    try:
        clean = validate_skill_name(name)
        skill_file = skill_dir_for(clean) / "SKILL.md"
        if not skill_file.exists():
            return SkillValidation(False, (f"Skill not found: {clean}",))
        parse_skill_file(skill_file, strict=True)
        warnings = []
        skill_dir = skill_dir_for(clean)
        for child in skill_dir.iterdir():
            if child.name == "SKILL.md":
                continue
            if child.name not in ALLOWED_SUPPORT_DIRS:
                warnings.append(f"Unexpected support path: {child.name}")
        return SkillValidation(True, warnings=tuple(warnings))
    except ValueError as error:
        return SkillValidation(False, (str(error),))


def create_skill(name: str, description: str, body: str, *, version: str = "1.0.0", metadata: dict[str, Any] | None = None) -> Skill:
    seed_starter_skills()
    clean = validate_skill_name(name)
    skill_file = skill_dir_for(clean) / "SKILL.md"
    if skill_file.exists():
        raise ValueError(f"Skill already exists: {clean}")
    frontmatter = {
        "name": clean,
        "description": clean_description(description),
        "version": str(version or "1.0.0"),
        "author": "BitBuddy",
        "metadata": metadata if isinstance(metadata, dict) else {"bitbuddy": {"tags": [], "related_skills": [], "risk_level": "medium", "maintained_by": "bitbuddy"}},
    }
    content = format_skill_content(frontmatter, body)
    skill_file.parent.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(content, encoding="utf-8")
    parse_skill_file(skill_file, strict=True)
    update_usage(clean, created=True)
    return parse_skill_file(skill_file)


def patch_skill(name: str, old_text: str, new_text: str) -> Skill:
    skill = load_skill(name, mark_viewed=False)
    if not old_text:
        raise ValueError("old_text is required.")
    content = skill.path.read_text(encoding="utf-8")
    if old_text not in content:
        raise ValueError("old_text was not found in the skill.")
    updated = content.replace(old_text, new_text, 1)
    if len(updated) > MAX_SKILL_CONTENT_CHARS:
        raise ValueError(f"Skill content exceeds {MAX_SKILL_CONTENT_CHARS} characters.")
    skill.path.write_text(updated, encoding="utf-8")
    parse_skill_file(skill.path, strict=True)
    update_usage(skill.name, patched=True)
    return parse_skill_file(skill.path)


def archive_skill(name: str) -> Skill:
    skill = load_skill(name, mark_viewed=False)
    usage = load_usage()
    entry = ensure_usage_entry(usage, skill.name)
    entry["state"] = "archived"
    entry["archived_at"] = now_iso()
    save_usage(usage)
    return parse_skill_file(skill.path)


def write_skill_file(name: str, relative_path: str, content: str) -> Path:
    clean = validate_skill_name(name)
    if not (skill_dir_for(clean) / "SKILL.md").exists():
        raise ValueError(f"Skill not found: {clean}")
    path = resolve_support_file(clean, relative_path)
    text = str(content)
    if len(text) > MAX_SUPPORT_FILE_CHARS:
        raise ValueError(f"Support file content exceeds {MAX_SUPPORT_FILE_CHARS} characters.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    update_usage(clean, patched=True)
    return path


def skill_catalog_prompt(max_skills: int = 12) -> str:
    skills = list_skills()[:max_skills]
    if not skills:
        return ""
    lines = [
        "[Available Skills]",
        "Skills are reusable procedures stored under ~/.bitbuddy/skills/. Use them when they clearly match the user's task.",
        "Call load_skill before relying on a skill's detailed workflow. Do not invent skills that are not listed.",
        "",
    ]
    for skill in skills:
        tags = skill.metadata.get("bitbuddy", {}).get("tags", []) if isinstance(skill.metadata.get("bitbuddy"), dict) else []
        tag_text = f" tags={', '.join(str(tag) for tag in tags[:5])}" if tags else ""
        lines.append(f"- {skill.name}: {skill.description}{tag_text}")
    return "\n".join(lines)


def skill_to_json(skill: Skill, *, include_content: bool = False) -> dict[str, Any]:
    data = {
        "name": skill.name,
        "description": skill.description,
        "version": skill.version,
        "path": str(skill.path.parent),
        "metadata": skill.metadata,
        "usage": skill.usage,
        "archived": skill.archived,
    }
    if include_content:
        data["frontmatter"] = skill.frontmatter
        data["body"] = skill.body
        data["content"] = skill.path.read_text(encoding="utf-8")
    return data


def parse_skill_file(path: Path, *, strict: bool = False) -> Skill:
    root = SKILLS_DIR.resolve()
    resolved = path.resolve()
    if root not in resolved.parents:
        raise ValueError("Skill file path escapes the skills directory.")
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError("Skill files and skill directories may not be symlinks.")
    content = path.read_text(encoding="utf-8")
    if len(content) > MAX_SKILL_CONTENT_CHARS:
        raise ValueError(f"Skill content exceeds {MAX_SKILL_CONTENT_CHARS} characters: {path}")
    if not content.startswith("---\n"):
        raise ValueError("SKILL.md must start with YAML frontmatter at byte 0.")
    end = content.find("\n---\n", 4)
    if end < 0:
        raise ValueError("SKILL.md frontmatter must close with a standalone --- line.")
    raw_frontmatter = content[4:end]
    body = content[end + 5 :].strip()
    if not body:
        raise ValueError("SKILL.md body must be non-empty.")
    frontmatter = yaml.safe_load(raw_frontmatter) or {}
    if not isinstance(frontmatter, dict):
        raise ValueError("Skill frontmatter must be a YAML mapping.")
    name = validate_skill_name(str(frontmatter.get("name") or ""))
    if name != path.parent.name:
        raise ValueError("Skill frontmatter name must match its folder name.")
    description = clean_description(str(frontmatter.get("description") or ""))
    version = str(frontmatter.get("version") or "1.0.0")
    metadata = frontmatter.get("metadata") if isinstance(frontmatter.get("metadata"), dict) else {}
    usage = load_usage().get(name, {})
    archived = str(usage.get("state") or "active") == "archived"
    if strict:
        validate_metadata(metadata)
    return Skill(name, description, version, path, body, frontmatter, metadata, usage, archived)


def validate_skill_name(name: str) -> str:
    clean = str(name or "").strip()
    if not clean:
        raise ValueError("Skill name is required.")
    if len(clean) > MAX_NAME_LENGTH or not SKILL_NAME_RE.fullmatch(clean):
        raise ValueError("Skill name must be lowercase, hyphenated, and 1-64 characters.")
    return clean


def clean_description(description: str) -> str:
    clean = " ".join(str(description or "").split())
    if not clean:
        raise ValueError("Skill description is required.")
    if len(clean) > MAX_DESCRIPTION_LENGTH:
        raise ValueError(f"Skill description exceeds {MAX_DESCRIPTION_LENGTH} characters.")
    return clean


def validate_metadata(metadata: dict[str, Any]) -> None:
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be a mapping when present.")


def format_skill_content(frontmatter: dict[str, Any], body: str) -> str:
    clean_body = str(body or "").strip()
    if not clean_body:
        raise ValueError("Skill body is required.")
    content = f"---\n{yaml.safe_dump(frontmatter, sort_keys=False)}---\n\n{clean_body}\n"
    if len(content) > MAX_SKILL_CONTENT_CHARS:
        raise ValueError(f"Skill content exceeds {MAX_SKILL_CONTENT_CHARS} characters.")
    return content


def skill_dir_for(name: str) -> Path:
    clean = validate_skill_name(name)
    ensure_skills_dir()
    path = (SKILLS_DIR / clean).resolve()
    root = SKILLS_DIR.resolve()
    if path != root and root in path.parents:
        return path
    raise ValueError("Resolved skill path escapes the skills directory.")


def resolve_support_file(name: str, relative_path: str) -> Path:
    skill_dir = skill_dir_for(name)
    relative = Path(str(relative_path or ""))
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("Support file path must be relative and stay inside the skill folder.")
    if relative.parts[0] not in ALLOWED_SUPPORT_DIRS:
        raise ValueError(f"Support files must live under one of: {', '.join(sorted(ALLOWED_SUPPORT_DIRS))}.")
    if relative.name == "SKILL.md":
        raise ValueError("Use patch_skill to edit SKILL.md.")
    path = (skill_dir / relative).resolve()
    if skill_dir.resolve() not in path.parents:
        raise ValueError("Resolved support file path escapes the skill folder.")
    return path


def load_usage() -> dict[str, dict[str, Any]]:
    ensure_skills_dir()
    path = SKILLS_DIR / USAGE_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def save_usage(usage: dict[str, dict[str, Any]]) -> None:
    ensure_skills_dir()
    (SKILLS_DIR / USAGE_FILE).write_text(json.dumps(usage, indent=2, sort_keys=True), encoding="utf-8")


def ensure_usage_entry(usage: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    return usage.setdefault(
        name,
        {
            "created_at": now_iso(),
            "created_by": "agent",
            "last_used_at": None,
            "last_viewed_at": None,
            "last_patched_at": None,
            "patch_count": 0,
            "pinned": False,
            "state": "active",
            "use_count": 0,
            "view_count": 0,
        },
    )


def update_usage(name: str, *, created: bool = False, viewed: bool = False, used: bool = False, patched: bool = False) -> None:
    clean = validate_skill_name(name)
    usage = load_usage()
    entry = ensure_usage_entry(usage, clean)
    current = now_iso()
    if created:
        entry.setdefault("created_at", current)
        entry.setdefault("created_by", "agent")
    if viewed:
        entry["last_viewed_at"] = current
        entry["view_count"] = int(entry.get("view_count") or 0) + 1
    if used:
        entry["last_used_at"] = current
        entry["use_count"] = int(entry.get("use_count") or 0) + 1
    if patched:
        entry["last_patched_at"] = current
        entry["patch_count"] = int(entry.get("patch_count") or 0) + 1
    entry.setdefault("state", "active")
    save_usage(usage)
