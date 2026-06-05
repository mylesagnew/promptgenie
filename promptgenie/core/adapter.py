"""
adapt.py — translate a prompt from one target profile to another.

Strategy:
1. Parse the source prompt into named sections (## headings) + a preamble.
2. Load source and target profiles.
3. For each section in the source:
   - Keep it if the target profile also needs it.
   - Drop it if the target profile explicitly forbids or doesn't use it.
   - Rewrite content that contains source-specific language (model names,
     tool-specific instructions, forbidden patterns).
4. Add sections required by the target that are missing from the source.
5. Replace the header line to reference the new target.
6. Return the adapted text plus a change log.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from promptgenie.core.generator import estimate_tokens, load_profile, score_prompt

# Sections that are universally portable — always keep them.
PORTABLE_SECTIONS = {
    "objective",
    "context",
    "background",
    "task",
    "goal",
    "output format",
    "output",
    "acceptance criteria",
    "done when",
}

# Sections that are agentic/safety-specific — only keep for agentic targets.
AGENTIC_SECTIONS = {
    "stop conditions",
    "forbidden actions",
    "security controls",
    "constraints",
    "scope",
    "verification",
}

AGENTIC_CATEGORIES = {"agentic-coding", "ide-coding"}

# Source-model name patterns to strip from content when re-targeting.
MODEL_NAME_PATTERNS = [
    (r"\bClaude Code\b", ""),
    (r"\bClaude\b", ""),
    (r"\bChatGPT\b", ""),
    (r"\bCursor\b", ""),
    (r"\bGemini\b", ""),
    (r"\bGPT-[0-9.]+\b", ""),
    (r"# Prompt for .+", ""),  # strip header line
]


@dataclass
class SectionChange:
    name: str
    action: str  # "kept" | "dropped" | "added" | "rewritten"
    reason: str


@dataclass
class AdaptResult:
    source_target: str
    dest_target: str
    original_text: str
    adapted_text: str
    changes: list[SectionChange] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source_tokens: int = 0
    adapted_tokens: int = 0
    source_score: dict = field(default_factory=dict)
    adapted_score: dict = field(default_factory=dict)


def _parse_sections(text: str) -> list[tuple[str, list[str]]]:
    """Return list of (heading, lines). Heading '' = preamble."""
    sections: list[tuple[str, list[str]]] = []
    current_heading = ""
    current_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            sections.append((current_heading, current_lines))
            current_heading = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)
    sections.append((current_heading, current_lines))
    return sections


def _sections_to_text(sections: list[tuple[str, list[str]]]) -> str:
    parts = []
    for heading, lines in sections:
        if heading:
            parts.append(f"## {heading}")
        if lines:
            parts.append("\n".join(lines))
    return "\n\n".join(p for p in parts if p.strip())


def _rewrite_content(
    lines: list[str], from_profile: dict, to_profile: dict
) -> tuple[list[str], bool]:
    """Replace source-model-specific language. Returns (new_lines, was_changed)."""
    text = "\n".join(lines)
    original = text

    # Swap model name in body text
    from_name = from_profile.get("name", "")
    to_name = to_profile.get("name", "")
    if from_name and to_name and from_name != to_name:
        text = re.sub(re.escape(from_name), to_name, text, flags=re.IGNORECASE)

    # Remove forbidden patterns of the destination profile from the content
    for pattern in to_profile.get("forbidden_patterns", []):
        if pattern.lower() in text.lower():
            text = re.sub(
                re.escape(pattern),
                "[REMOVED — forbidden by target profile]",
                text,
                flags=re.IGNORECASE,
            )

    changed = text != original
    return text.splitlines(), changed


def _build_added_section(section_name: str, profile: dict) -> list[str]:
    """Generate default content for a section the target requires but the source lacks."""
    name_lower = section_name.lower()
    if name_lower == "stop conditions":
        stops = profile.get("stop_conditions", [])
        if stops:
            return ["Stop and ask for approval if:"] + [f"- {s}" for s in stops]
        return ["Stop and ask for approval before proceeding past the defined scope."]
    if name_lower == "forbidden actions":
        patterns = profile.get("forbidden_patterns", [])
        if patterns:
            return [f"- {p}" for p in patterns]
        return ["- Do not exceed the defined scope without approval."]
    if name_lower == "scope":
        return [profile.get("scope_guidance", "Work only within explicitly stated boundaries.")]
    if name_lower == "security controls":
        controls = profile.get("security_controls", [])
        return (
            [f"- {c}" for c in controls] if controls else ["- Follow least-privilege principles."]
        )
    if name_lower == "output format":
        return [profile.get("default_output_format", "Respond in structured markdown.")]
    if name_lower == "acceptance criteria":
        return ["Done when:", "- All objectives are met", "- Output matches the requested format"]
    return [f"[Add {section_name} content here]"]


def adapt(
    source_path: str, from_target: str, to_target: str, strip_agentic_safety: bool = False
) -> AdaptResult:
    original_text = Path(source_path).read_text()

    try:
        from_profile = load_profile(from_target)
    except FileNotFoundError:
        from_profile = {
            "name": from_target,
            "category": "",
            "required_sections": [],
            "forbidden_patterns": [],
            "stop_conditions": [],
            "security_controls": [],
        }

    try:
        to_profile = load_profile(to_target)
    except FileNotFoundError:
        to_profile = {
            "name": to_target,
            "category": "",
            "required_sections": [],
            "forbidden_patterns": [],
            "stop_conditions": [],
            "security_controls": [],
        }

    to_name = to_profile.get("name", to_target)
    _to_required = {s.lower() for s in to_profile.get("required_sections", [])}
    to_is_agentic = to_profile.get("category", "") in AGENTIC_CATEGORIES
    from_is_agentic = from_profile.get("category", "") in AGENTIC_CATEGORIES

    parsed = _parse_sections(original_text)
    adapted: list[tuple[str, list[str]]] = []
    changes: list[SectionChange] = []
    warnings: list[str] = []
    seen_sections: set[str] = set()

    for heading, lines in parsed:
        # Preamble: replace the "# Prompt for X" header line
        if heading == "":
            new_lines = []
            for line in lines:
                if re.match(r"#\s+Prompt for .+", line):
                    new_lines.append(f"# Prompt for {to_name}")
                else:
                    new_lines.append(line)
            adapted.append(("", new_lines))
            continue

        heading_lower = heading.lower()
        seen_sections.add(heading_lower)

        # Drop agentic-only sections only when caller explicitly opts in
        if heading_lower in AGENTIC_SECTIONS and not to_is_agentic and from_is_agentic:
            if strip_agentic_safety:
                changes.append(
                    SectionChange(
                        name=heading,
                        action="dropped",
                        reason=f"{to_name} is not an agentic tool — stripped via --strip-agentic-safety.",
                    )
                )
                continue
            # Default: preserve safety sections with a note
            changes.append(
                SectionChange(
                    name=heading,
                    action="kept",
                    reason="Agentic safety section preserved by default. Use --strip-agentic-safety to remove.",
                )
            )

        # Rewrite content to replace source-specific language
        new_lines, was_changed = _rewrite_content(lines, from_profile, to_profile)

        if was_changed:
            adapted.append((heading, new_lines))
            changes.append(
                SectionChange(
                    name=heading,
                    action="rewritten",
                    reason=f"Replaced {from_profile.get('name', from_target)}-specific language for {to_name}.",
                )
            )
        else:
            adapted.append((heading, lines))
            changes.append(
                SectionChange(name=heading, action="kept", reason="Content is portable.")
            )

    # Add sections required by target that were missing in source
    for required in to_profile.get("required_sections", []):
        if required.lower() not in seen_sections:
            new_lines = _build_added_section(required, to_profile)
            adapted.append((required, new_lines))
            changes.append(
                SectionChange(
                    name=required,
                    action="added",
                    reason=f"Required by {to_name} profile but absent in source.",
                )
            )

    # Warn if target profile has security controls the source lacked
    if to_profile.get("security_controls") and not from_profile.get("security_controls"):
        warnings.append(
            f"{to_name} has security controls not present in the source prompt. "
            "Review the Security Controls section before use."
        )

    # Warn if adapting from agentic to non-agentic with stop conditions dropped
    dropped = [c for c in changes if c.action == "dropped"]
    if dropped:
        warnings.append(
            f"{len(dropped)} agentic safety section(s) were removed. "
            "Verify the adapted prompt is still safe for its intended use."
        )

    adapted_text = _sections_to_text(adapted)

    source_tokens = estimate_tokens(original_text)
    adapted_tokens = estimate_tokens(adapted_text)
    source_score = score_prompt(original_text, from_profile)
    adapted_score = score_prompt(adapted_text, to_profile)

    return AdaptResult(
        source_target=from_target,
        dest_target=to_target,
        original_text=original_text,
        adapted_text=adapted_text,
        changes=changes,
        warnings=warnings,
        source_tokens=source_tokens,
        adapted_tokens=adapted_tokens,
        source_score=source_score,
        adapted_score=adapted_score,
    )
