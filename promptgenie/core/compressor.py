"""compressor.py — native, dependency-free token compression for prompts.

A pure-Python reimplementation of the lossless / low-risk structural
techniques popularised by headroom (https://github.com/headroomlabs-ai/headroom):
content-routed compressors that shrink the token footprint of a prompt or
its assembled context *before* it reaches the model — same answer, fewer
tokens — without pulling in a Rust toolchain, tree-sitter, or ONNX.

Design
------
Compression is a pipeline of independent *techniques*. Each technique takes
text and returns ``(new_text, occurrences)`` where ``occurrences`` is how many
edits it made. Techniques are fence-aware: transforms that could corrupt code
(collapsing runs of spaces, for example) skip fenced ```code``` blocks.

Two tiers, mirroring headroom's "safe by default, aggressive on request" split:

* **default** — lossless or near-lossless for Markdown / prompt text:
  trailing-whitespace trim, blank-line collapse, JSON compaction.
* **aggressive** — higher savings, mildly lossy, enabled explicitly or when a
  ``max_tokens`` budget forces it: HTML-comment stripping, repeated-space
  collapse, consecutive-duplicate-line folding (build logs / stack traces).

A third, structural phase — **summarisation** — drops whole low-value sections
(examples, changelogs, appendices, log dumps) either unconditionally or, when a
``max_tokens`` budget is set, until the document fits. It is opt-in
(``summarise=True``), heuristic, and dependency-free — no LLM, no network.

Public API
----------
  ``compress(text, techniques=None, max_tokens=None, summarise=False)`` → CompressResult
  ``prune_sections(text, max_tokens=None)`` → (new_text, list[DroppedSection])
  ``CompressResult`` / ``DroppedSection``              — result dataclasses
  ``DEFAULT_TECHNIQUES`` / ``AGGRESSIVE_TECHNIQUES`` / ``ALL_TECHNIQUES``
  ``TECHNIQUES``                                       — name → metadata
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from promptgenie.core.generator import estimate_tokens

# ---------------------------------------------------------------------------
# Fence handling — split text into prose vs fenced code segments
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^(\s*)(`{3,}|~{3,})", re.MULTILINE)


def _split_fences(text: str) -> list[tuple[bool, str]]:
    """Split *text* into ``(is_code, segment)`` parts on Markdown code fences.

    A segment flagged ``is_code=True`` includes the opening and closing fence
    lines so that re-joining the parts reproduces the original exactly.
    """
    lines = text.splitlines(keepends=True)
    segments: list[tuple[bool, str]] = []
    buf: list[str] = []
    in_code = False
    fence_marker = ""

    def flush(is_code: bool) -> None:
        if buf:
            segments.append((is_code, "".join(buf)))
            buf.clear()

    for line in lines:
        stripped = line.lstrip()
        is_fence = stripped.startswith("```") or stripped.startswith("~~~")
        marker = stripped[:3] if is_fence else ""
        if not in_code and is_fence:
            flush(False)
            in_code = True
            fence_marker = marker
            buf.append(line)
        elif in_code and is_fence and marker == fence_marker:
            buf.append(line)
            flush(True)
            in_code = False
            fence_marker = ""
        else:
            buf.append(line)
    flush(in_code)
    return segments


def _apply_to_prose(text: str, fn) -> tuple[str, int]:
    """Run ``fn(segment) -> (new, count)`` over prose segments only.

    Fenced code segments are passed through untouched.
    """
    out: list[str] = []
    total = 0
    for is_code, seg in _split_fences(text):
        if is_code:
            out.append(seg)
            continue
        new, count = fn(seg)
        out.append(new)
        total += count
    return "".join(out), total


# ---------------------------------------------------------------------------
# Techniques — each returns (new_text, occurrences)
# ---------------------------------------------------------------------------

_TRAILING_WS_RE = re.compile(r"[ \t]+(\r?\n)")
_BLANK_RUN_RE = re.compile(r"(?:[ \t]*\r?\n){3,}")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_MULTISPACE_RE = re.compile(r"(?<=\S) {2,}(?=\S)")


def _trim_trailing_ws(text: str) -> tuple[str, int]:
    new, n = _TRAILING_WS_RE.subn(r"\1", text)
    return new, n


def _collapse_blank_lines(text: str) -> tuple[str, int]:
    """Collapse runs of 3+ newlines (≥2 blank lines) down to one blank line."""

    def repl(m: re.Match[str]) -> str:
        return "\n\n"

    new, n = _BLANK_RUN_RE.subn(repl, text)
    return new, n


def _strip_html_comments(text: str) -> tuple[str, int]:
    def fn(seg: str) -> tuple[str, int]:
        return _HTML_COMMENT_RE.subn("", seg)

    return _apply_to_prose(text, fn)


def _collapse_repeated_spaces(text: str) -> tuple[str, int]:
    """Collapse 2+ inline spaces to one — prose only, never indentation."""

    def fn(seg: str) -> tuple[str, int]:
        out_lines: list[str] = []
        count = 0
        for line in seg.splitlines(keepends=True):
            nl = ""
            body = line
            if line.endswith("\n"):
                body, nl = line[:-1], "\n"
            # Preserve leading indentation; only squeeze interior runs.
            stripped = body.lstrip(" ")
            indent = body[: len(body) - len(stripped)]
            new_body, n = _MULTISPACE_RE.subn(" ", stripped)
            count += n
            out_lines.append(indent + new_body + nl)
        return "".join(out_lines), count

    return _apply_to_prose(text, fn)


_JSON_FENCE_RE = re.compile(
    r"(```|~~~)[ \t]*(json|jsonc)?[ \t]*\r?\n(.*?)(\r?\n)(\1)",
    re.DOTALL | re.IGNORECASE,
)


def _compact_json_text(blob: str) -> str | None:
    """Return a minified JSON string if *blob* is valid JSON, else None."""
    s = blob.strip()
    if not s or s[0] not in "{[":
        return None
    try:
        obj = json.loads(s)
    except (ValueError, RecursionError):
        return None
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def _json_compact(text: str) -> tuple[str, int]:
    """Minify whole-document JSON, or JSON inside ```json fenced blocks."""
    # Whole document is JSON → compact it directly.
    whole = _compact_json_text(text)
    if whole is not None and whole != text.strip():
        return whole, 1

    # Otherwise compact fenced JSON blocks.
    count = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal count
        fence, lang, body, _nl, close = m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
        compact = _compact_json_text(body)
        if compact is None or compact == body.strip():
            return m.group(0)
        count += 1
        lang_tag = lang or "json"
        return f"{fence}{lang_tag}\n{compact}\n{close}"

    new = _JSON_FENCE_RE.sub(repl, text)
    return new, count


def _dedupe_log_lines(text: str) -> tuple[str, int]:
    """Fold runs of identical consecutive lines into ``line  (×N)``.

    Targets build logs and repeated stack frames. Operates on prose only and
    ignores blank lines so Markdown spacing is preserved.
    """

    def fn(seg: str) -> tuple[str, int]:
        lines = seg.splitlines(keepends=True)
        out: list[str] = []
        folded = 0
        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]
            if line.strip() == "":
                out.append(line)
                i += 1
                continue
            j = i + 1
            while j < n and lines[j] == line:
                j += 1
            run = j - i
            if run >= 3:
                body = line.rstrip("\r\n")
                nl = line[len(body) :]
                out.append(f"{body}  (×{run}){nl}")
                folded += 1
            else:
                out.extend(lines[i:j])
            i = j
        return "".join(out), folded

    return _apply_to_prose(text, fn)


# ---------------------------------------------------------------------------
# Summarisation — heuristic low-value-section removal
# ---------------------------------------------------------------------------
#
# Unlike the techniques above (which rewrite text in place), summarisation works
# at the *section* level: it drops whole low-value sections — examples,
# changelogs, appendices, log dumps — either unconditionally or, when a
# ``max_tokens`` budget is set, until the document fits. It is fully
# dependency-free and deterministic (no LLM, no network).

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")

# Heading keywords that mark a section as high-value — never dropped.
_PROTECT_KEYWORDS: frozenset[str] = frozenset(
    {
        "objective",
        "task",
        "instruction",
        "scope",
        "requirement",
        "constraint",
        "rule",
        "role",
        "system",
        "persona",
        "goal",
        "deliverable",
        "output",
        "format",
        "context",
        "input",
        "policy",
        "forbidden",
        "must",
        "do not",
        "guardrail",
        "safety",
    }
)

# Heading keywords that mark a section as low-value — dropped first.
_LOW_VALUE_KEYWORDS: frozenset[str] = frozenset(
    {
        "example",
        "appendix",
        "changelog",
        "change log",
        "history",
        "footnote",
        "reference",
        "acknowledg",
        "license",
        "licence",
        "related work",
        "further reading",
        "see also",
        "faq",
        "troubleshooting",
        "disclaimer",
        "credits",
        "contributing",
        "table of contents",
        "appendices",
    }
)


@dataclass
class DroppedSection:
    """A section removed by summarisation."""

    heading: str
    level: int
    tokens: int
    reason: str  # "low_value" | "budget"


@dataclass(frozen=True)
class _Section:
    heading: str | None  # heading text (without leading #), None for the preamble
    level: int  # 0 for the preamble, 1–6 for ATX headings
    text: str  # the full block, including the heading line
    tokens: int
    protected: bool
    low_value: bool


def _heading_matches(heading: str, keywords: frozenset[str]) -> bool:
    hl = heading.lower()
    return any(kw in hl for kw in keywords)


def _make_section(heading: str | None, level: int, block: str) -> _Section:
    protected = heading is not None and _heading_matches(heading, _PROTECT_KEYWORDS)
    low_value = (
        heading is not None
        and not protected
        and _heading_matches(heading, _LOW_VALUE_KEYWORDS)
    )
    return _Section(
        heading=heading,
        level=level,
        text=block,
        tokens=estimate_tokens(block),
        protected=protected,
        low_value=low_value,
    )


def _split_sections(text: str) -> list[_Section]:
    """Split *text* into sections on ATX (``#``) headings, fence-aware.

    The text before the first heading is the *preamble* (level 0, never
    dropped). ``#`` lines inside fenced code blocks are not treated as headings.
    """
    lines = text.splitlines(keepends=True)
    blocks: list[tuple[str | None, int, list[str]]] = []
    cur_heading: str | None = None
    cur_level = 0
    cur_lines: list[str] = []
    in_code = False
    fence_marker = ""

    for line in lines:
        stripped = line.lstrip()
        is_fence = stripped.startswith("```") or stripped.startswith("~~~")
        if is_fence:
            marker = stripped[:3]
            if not in_code:
                in_code, fence_marker = True, marker
            elif marker == fence_marker:
                in_code, fence_marker = False, ""
            cur_lines.append(line)
            continue

        m = None if in_code else _HEADING_RE.match(line.rstrip("\r\n"))
        if m:
            if cur_lines or cur_heading is not None:
                blocks.append((cur_heading, cur_level, cur_lines))
            cur_heading = m.group(2).strip()
            cur_level = len(m.group(1))
            cur_lines = [line]
        else:
            cur_lines.append(line)

    if cur_lines or cur_heading is not None:
        blocks.append((cur_heading, cur_level, cur_lines))

    return [_make_section(h, lv, "".join(ls)) for h, lv, ls in blocks]


def prune_sections(
    text: str, max_tokens: int | None = None
) -> tuple[str, list[DroppedSection]]:
    """Drop low-value sections from *text*, returning ``(new_text, dropped)``.

    Behaviour:

    * ``max_tokens is None`` — unconditionally remove sections whose heading
      looks low-value (examples, changelog, appendix, …).
    * ``max_tokens`` set — remove low-value sections first, then other
      non-protected sections (largest first) until the document fits the budget,
      or there is nothing left to drop.

    A heading drops together with its descendant subsections. A section (or
    subtree) containing any protected heading is never dropped.
    """
    sections = _split_sections(text)
    n = len(sections)
    heading_idx = [i for i in range(n) if sections[i].heading is not None]

    def subtree_end(i: int) -> int:
        level = sections[i].level
        j = i + 1
        while j < n and sections[j].level > level:
            j += 1
        return j

    ranges = {i: subtree_end(i) for i in heading_idx}

    def subtree_protected(i: int) -> bool:
        return any(sections[k].protected for k in range(i, ranges[i]))

    candidates = [i for i in heading_idx if not subtree_protected(i)]
    drop_set: set[int] = set()
    dropped: list[DroppedSection] = []
    remaining = estimate_tokens(text)

    def _drop(order: list[int], reason: str, budgeted: bool) -> None:
        nonlocal remaining
        for i in order:
            if i in drop_set:
                continue  # already removed as part of an ancestor subtree
            if budgeted and remaining <= max_tokens:  # type: ignore[operator]
                return
            end = ranges[i]
            toks = sum(sections[k].tokens for k in range(i, end) if k not in drop_set)
            for k in range(i, end):
                drop_set.add(k)
            dropped.append(
                DroppedSection(
                    heading=sections[i].heading or "",
                    level=sections[i].level,
                    tokens=toks,
                    reason=reason,
                )
            )
            remaining -= toks

    low_value = sorted(
        (i for i in candidates if sections[i].low_value),
        key=lambda i: -sum(sections[k].tokens for k in range(i, ranges[i])),
    )
    others = sorted(
        (i for i in candidates if not sections[i].low_value),
        key=lambda i: -sum(sections[k].tokens for k in range(i, ranges[i])),
    )

    if max_tokens is None:
        _drop(low_value, reason="low_value", budgeted=False)
    elif remaining > max_tokens:
        _drop(low_value, reason="low_value", budgeted=True)
        _drop(others, reason="budget", budgeted=True)

    if not drop_set:
        return text, []

    new_text = "".join(sections[k].text for k in range(n) if k not in drop_set)
    return new_text, dropped


# ---------------------------------------------------------------------------
# Technique registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Technique:
    name: str
    fn: object  # Callable[[str], tuple[str, int]]
    aggressive: bool
    description: str


_TECHNIQUE_LIST: list[Technique] = [
    Technique(
        "trim-trailing-ws", _trim_trailing_ws, False, "Strip trailing whitespace at line ends."
    ),
    Technique(
        "collapse-blank-lines",
        _collapse_blank_lines,
        False,
        "Collapse 2+ consecutive blank lines into one.",
    ),
    Technique(
        "json-compact",
        _json_compact,
        False,
        "Minify whole-document JSON and ```json fenced blocks.",
    ),
    Technique(
        "strip-html-comments",
        _strip_html_comments,
        True,
        "Remove <!-- HTML comments --> from prose.",
    ),
    Technique(
        "collapse-spaces",
        _collapse_repeated_spaces,
        True,
        "Collapse runs of inline spaces in prose (keeps indentation).",
    ),
    Technique(
        "dedupe-log-lines",
        _dedupe_log_lines,
        True,
        "Fold 3+ identical consecutive lines into 'line (×N)'.",
    ),
]

TECHNIQUES: dict[str, Technique] = {t.name: t for t in _TECHNIQUE_LIST}
DEFAULT_TECHNIQUES: list[str] = [t.name for t in _TECHNIQUE_LIST if not t.aggressive]
AGGRESSIVE_TECHNIQUES: list[str] = [t.name for t in _TECHNIQUE_LIST if t.aggressive]
ALL_TECHNIQUES: list[str] = [t.name for t in _TECHNIQUE_LIST]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class TechniqueResult:
    name: str
    occurrences: int
    chars_saved: int


@dataclass
class CompressResult:
    original_text: str
    compressed_text: str
    tokens_before: int
    tokens_after: int
    applied: list[TechniqueResult] = field(default_factory=list)
    budget_met: bool | None = None  # None when no max_tokens budget was set
    dropped_sections: list[DroppedSection] = field(default_factory=list)

    @property
    def chars_before(self) -> int:
        return len(self.original_text)

    @property
    def chars_after(self) -> int:
        return len(self.compressed_text)

    @property
    def tokens_saved(self) -> int:
        return self.tokens_before - self.tokens_after

    @property
    def ratio(self) -> float:
        """Fraction of tokens removed (0.0–1.0)."""
        if self.tokens_before == 0:
            return 0.0
        return self.tokens_saved / self.tokens_before

    @property
    def changed(self) -> bool:
        return self.compressed_text != self.original_text


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


class UnknownTechniqueError(ValueError):
    """Raised when an unknown technique name is requested."""


def _resolve_techniques(
    techniques: list[str] | None,
    max_tokens: int | None,
) -> list[str]:
    if techniques is not None:
        unknown = [t for t in techniques if t not in TECHNIQUES]
        if unknown:
            raise UnknownTechniqueError(
                f"Unknown technique(s): {', '.join(unknown)}. "
                f"Available: {', '.join(ALL_TECHNIQUES)}"
            )
        # Preserve canonical order.
        return [t for t in ALL_TECHNIQUES if t in set(techniques)]
    # No explicit list: defaults, escalating to all when a budget is set.
    return list(ALL_TECHNIQUES) if max_tokens is not None else list(DEFAULT_TECHNIQUES)


def compress(
    text: str,
    techniques: list[str] | None = None,
    max_tokens: int | None = None,
    summarise: bool = False,
) -> CompressResult:
    """Compress *text*, returning a :class:`CompressResult`.

    Parameters
    ----------
    text:
        Prompt or context text to compress.
    techniques:
        Explicit ordered subset of technique names. ``None`` selects the
        default (safe) tier, or every technique when *max_tokens* is given.
    max_tokens:
        Optional token budget. When set, all techniques are eligible and
        ``CompressResult.budget_met`` reports whether the result fits.
    summarise:
        When ``True``, run heuristic low-value-section removal after the
        in-place techniques. Without a *max_tokens* budget this drops only
        sections whose heading looks low-value (examples, changelog, …); with a
        budget it additionally drops other non-protected sections (largest
        first) until the document fits. Dropped sections are reported on
        ``CompressResult.dropped_sections``.

    Raises
    ------
    UnknownTechniqueError
        If *techniques* names a technique that does not exist.
    """
    selected = _resolve_techniques(techniques, max_tokens)
    tokens_before = estimate_tokens(text)

    current = text
    applied: list[TechniqueResult] = []
    for name in selected:
        tech = TECHNIQUES[name]
        before_len = len(current)
        new_text, occurrences = tech.fn(current)  # type: ignore[operator]
        if occurrences and new_text != current:
            applied.append(
                TechniqueResult(
                    name=name,
                    occurrences=occurrences,
                    chars_saved=before_len - len(new_text),
                )
            )
            current = new_text

    dropped_sections: list[DroppedSection] = []
    if summarise:
        pruned, dropped_sections = prune_sections(current, max_tokens)
        if dropped_sections:
            # Tidy up blank lines left where sections were removed.
            pruned, _ = _collapse_blank_lines(pruned)
            current = pruned

    tokens_after = estimate_tokens(current)
    budget_met = None if max_tokens is None else tokens_after <= max_tokens

    return CompressResult(
        original_text=text,
        compressed_text=current,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        applied=applied,
        budget_met=budget_met,
        dropped_sections=dropped_sections,
    )
