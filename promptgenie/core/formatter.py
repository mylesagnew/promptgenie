"""formatter.py — native, dependency-free formatter for prompts and PromptSpecs.

``promptgenie fmt`` is to prompt files what ``gofmt``/``black``/``prettier`` are
to source code: a deterministic normaliser that produces one canonical layout so
that diffs stay small and reviews stay focused on content, not whitespace.

Two file shapes are handled:

* **Markdown** (``.md``, ``.markdown``, and the default for stdin): fence-aware
  normalisation — trailing-whitespace trim, blank-line collapse, ATX heading
  normalisation (single space after ``#``, no closing hashes), one blank line
  around headings, and a single trailing newline. Fenced ```code``` blocks are
  preserved byte-for-byte so significant whitespace is never touched.

* **PromptSpec YAML** (``.yaml``, ``.yml``): the same text-level whitespace
  normalisation plus an optional **canonical key sort** that orders the
  top-level keys (and the ``output_contract`` / ``run`` sub-maps) the same way
  the :class:`~promptgenie.core.spec.PromptSpec` dataclass declares them, so
  every spec in a repo reads top-to-bottom in the same order.

Comment handling for YAML
-------------------------
Reordering YAML keys without dropping ``# comments`` requires a round-trip
parser. When the optional :mod:`ruamel.yaml` extra is installed it is used to
reorder keys *and* preserve comments. Otherwise the formatter degrades safely:

* a spec with **no comments** is reordered with the stdlib-friendly PyYAML path;
* a spec that **contains comments** is left in its original key order (only
  whitespace is normalised) so a comment is never silently lost.

This keeps the base install dependency-free (``click`` + ``rich`` + ``pyyaml``)
while still giving comment-preserving key sort to anyone who installs
``promptgenie[fmt]``.

Public API
----------
  ``format_text(text, file_type=...)``  → :class:`FormatResult`
  ``detect_file_type(path)``            → ``"markdown"`` | ``"yaml"``
  ``FormatResult`` / ``RuleApplication`` — result dataclasses
  ``CANONICAL_SPEC_KEYS``                — top-level PromptSpec key order
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import yaml

try:  # optional extra: comment-preserving YAML round-trip
    from ruamel.yaml import YAML as _RuamelYAML

    _HAS_RUAMEL = True
except ImportError:  # pragma: no cover - exercised only when ruamel is absent
    _RuamelYAML = None  # type: ignore[assignment,misc]
    _HAS_RUAMEL = False


# ---------------------------------------------------------------------------
# Canonical PromptSpec key order — mirrors PromptSpec dataclass field order
# ---------------------------------------------------------------------------

CANONICAL_SPEC_KEYS: tuple[str, ...] = (
    "version",
    "name",
    "target",
    "template",
    "mode",
    "vars",
    "secret_vars",
    "context",
    "policy",
    "provider",
    "model",
    "system_prompt",
    "prompt",
    "output_contract",
    "run",
)

# Nested maps that also get a canonical key order.
_NESTED_KEY_ORDER: dict[str, tuple[str, ...]] = {
    "output_contract": ("format", "schema", "max_tokens", "min_tokens"),
    "run": ("dry_run", "stream", "timeout", "retries", "require_clean", "no_history"),
}


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------


@dataclass
class RuleApplication:
    """A single formatting rule and how many edits it made."""

    name: str
    occurrences: int


@dataclass
class FormatResult:
    """Outcome of formatting one document."""

    formatted_text: str
    file_type: str
    rules: list[RuleApplication] = field(default_factory=list)
    original_text: str = ""

    @property
    def changed(self) -> bool:
        return self.formatted_text != self.original_text


# ---------------------------------------------------------------------------
# File-type detection
# ---------------------------------------------------------------------------

_MARKDOWN_EXTS = {".md", ".markdown", ".mdown", ".mkd"}
_YAML_EXTS = {".yaml", ".yml"}


def detect_file_type(path: str) -> str:
    """Return ``"markdown"`` or ``"yaml"`` for *path* (by extension).

    Unknown extensions — and stdin (``"-"``) — default to ``"markdown"``.
    """
    lower = path.lower()
    for ext in _YAML_EXTS:
        if lower.endswith(ext):
            return "yaml"
    for ext in _MARKDOWN_EXTS:
        if lower.endswith(ext):
            return "markdown"
    return "markdown"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def format_text(text: str, *, file_type: str = "markdown") -> FormatResult:
    """Format *text* as ``file_type`` (``"markdown"`` or ``"yaml"``)."""
    if file_type == "yaml":
        return _format_yaml(text)
    return _format_markdown(text)


# ---------------------------------------------------------------------------
# Fence handling (shared)
# ---------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


def _code_mask(lines: list[str]) -> list[bool]:
    """Return a per-line mask where ``True`` marks a fenced-code line.

    Both the opening and closing fence lines are flagged so they are preserved
    verbatim alongside their contents.
    """
    mask = [False] * len(lines)
    fence: str | None = None
    for i, line in enumerate(lines):
        m = _FENCE_RE.match(line)
        if fence is None:
            if m:
                fence = m.group(1)[0]  # ` or ~
                mask[i] = True
        else:
            mask[i] = True
            stripped = line.strip()
            if stripped and set(stripped) == {fence} and len(stripped) >= 3:
                fence = None
    return mask


# ---------------------------------------------------------------------------
# Markdown formatter
# ---------------------------------------------------------------------------

_ATX_RE = re.compile(r"^(#{1,6})(\s.*)?$")


def _format_markdown(text: str) -> FormatResult:
    original = text
    lines = text.split("\n")
    # ``split("\n")`` on a trailing newline yields a final "" element; track it
    # so final-newline handling is explicit rather than accidental.
    code = _code_mask(lines)

    counts: dict[str, int] = {}

    def bump(rule: str, n: int = 1) -> None:
        if n:
            counts[rule] = counts.get(rule, 0) + n

    # Pass 1 — per-line: trailing whitespace + heading normalisation (prose only).
    norm: list[str] = []
    is_heading: list[bool] = []
    for line, in_code in zip(lines, code, strict=True):
        if in_code:
            norm.append(line)
            is_heading.append(False)
            continue
        new = line.rstrip()
        if new != line:
            bump("trim-trailing-ws")
        head = _normalize_heading(new)
        if head is not None:
            if head != new:
                bump("normalize-heading")
            norm.append(head)
            is_heading.append(True)
        else:
            norm.append(new)
            is_heading.append(False)

    # Pass 2 — blank-line structure: collapse blank runs and pad headings.
    out: list[str] = []
    out_heading: list[bool] = []

    def emit(line: str, heading: bool = False) -> None:
        out.append(line)
        out_heading.append(heading)

    n = len(norm)
    for i in range(n):
        line = norm[i]
        in_code = code[i]
        blank = (not in_code) and line.strip() == ""

        if blank:
            # Collapse consecutive blank prose lines to a single blank.
            if out and out[-1] == "":
                bump("collapse-blank-lines")
                continue
            emit("")
            continue

        if is_heading[i]:
            # Ensure a blank line *before* the heading (unless at top).
            if out and out[-1] != "":
                emit("")
                bump("blank-around-heading")
            emit(line, heading=True)
            continue

        emit(line)

    # Pad a blank line *after* each heading (unless followed by blank/EOF).
    padded: list[str] = []
    for i, line in enumerate(out):
        padded.append(line)
        if out_heading[i]:
            nxt = out[i + 1] if i + 1 < len(out) else None
            if nxt is not None and nxt != "":
                padded.append("")
                bump("blank-around-heading")

    # Strip leading blank lines.
    start = 0
    while start < len(padded) and padded[start] == "":
        start += 1
    if start:
        bump("trim-leading-blank-lines", start)
    body = padded[start:]

    # Strip trailing blank lines, then guarantee exactly one final newline.
    end = len(body)
    while end > 0 and body[end - 1] == "":
        end -= 1
    body = body[:end]

    formatted = ("\n".join(body) + "\n") if body else ""
    # The final-newline rule fires when the original lacked a clean single
    # trailing newline (missing newline, or two-plus trailing blank lines).
    if original and (not original.endswith("\n") or original.endswith("\n\n")):
        bump("final-newline")

    rules = [RuleApplication(k, v) for k, v in counts.items() if v]
    return FormatResult(
        formatted_text=formatted,
        file_type="markdown",
        rules=sorted(rules, key=lambda r: r.name),
        original_text=original,
    )


def _normalize_heading(line: str) -> str | None:
    """Return the normalised ATX heading, or ``None`` if *line* is not a heading.

    ``##Title``      → ``## Title``
    ``##  Title  ##`` → ``## Title``
    ``###``          → ``###`` (empty heading kept as-is)
    """
    m = _ATX_RE.match(line)
    if not m:
        return None
    hashes = m.group(1)
    rest = m.group(2)
    if rest is None:
        return hashes
    content = rest.strip()
    # Drop a trailing run of closing hashes (``## Title ##``).
    content = re.sub(r"\s+#+\s*$", "", content).rstrip()
    if not content:
        return hashes
    return f"{hashes} {content}"


# ---------------------------------------------------------------------------
# YAML formatter
# ---------------------------------------------------------------------------

_YAML_COMMENT_RE = re.compile(r"(^\s*#)|(\s#)")


def _has_comments(text: str) -> bool:
    """Heuristic: does *text* contain YAML ``# comments``?

    Conservative — a ``#`` inside a quoted string or URL also counts, so the
    formatter errs toward *preserving* a file (skipping key reorder) rather than
    risking comment loss in the PyYAML fallback path.
    """
    return any(_YAML_COMMENT_RE.search(line) for line in text.split("\n"))


def _format_yaml(text: str) -> FormatResult:
    original = text
    counts: dict[str, int] = {}

    reordered: str | None = None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        data = None

    # Only regenerate the document when keys are genuinely out of canonical
    # order — otherwise an already-ordered file is left to the (comment-safe)
    # whitespace pass, which keeps styling and attributes its own edits.
    if isinstance(data, dict) and _needs_reorder(data):
        if _HAS_RUAMEL:
            reordered = _reorder_yaml_ruamel(text)
        elif not _has_comments(text):
            reordered = _reorder_yaml_pyyaml(data)

    base = reordered if reordered is not None else text
    if reordered is not None and _strip_for_compare(reordered) != _strip_for_compare(text):
        counts["sort-keys"] = 1

    # Text-level whitespace normalisation (always applied, comment-safe).
    cleaned, ws_counts = _normalize_yaml_whitespace(base)
    for k, v in ws_counts.items():
        counts[k] = counts.get(k, 0) + v

    rules = [RuleApplication(k, v) for k, v in counts.items() if v]
    return FormatResult(
        formatted_text=cleaned,
        file_type="yaml",
        rules=sorted(rules, key=lambda r: r.name),
        original_text=original,
    )


def _strip_for_compare(text: str) -> str:
    """Normalise whitespace so key-sort detection ignores formatting noise."""
    return "\n".join(line.rstrip() for line in text.strip("\n").split("\n"))


def _normalize_yaml_whitespace(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    lines = text.split("\n")
    out: list[str] = []
    for line in lines:
        new = line.rstrip()
        if new != line:
            counts["trim-trailing-ws"] = counts.get("trim-trailing-ws", 0) + 1
        if new == "" and out and out[-1] == "":
            counts["collapse-blank-lines"] = counts.get("collapse-blank-lines", 0) + 1
            continue
        out.append(new)
    # Strip leading/trailing blank lines, ensure single final newline.
    while out and out[0] == "":
        out.pop(0)
    while out and out[-1] == "":
        out.pop()
    formatted = ("\n".join(out) + "\n") if out else ""
    if formatted != text:
        counts.setdefault("final-newline", 0)
        if not text.endswith("\n") or text.endswith("\n\n"):
            counts["final-newline"] = 1
    return formatted, {k: v for k, v in counts.items() if v}


def _needs_reorder(data: dict) -> bool:
    """True if *data*'s top-level or nested keys are not in canonical order."""
    if list(data.keys()) != _ordered_keys(data, CANONICAL_SPEC_KEYS):
        return True
    for parent, nested in _NESTED_KEY_ORDER.items():
        child = data.get(parent)
        if isinstance(child, dict) and list(child.keys()) != _ordered_keys(child, nested):
            return True
    return False


def _ordered_keys(data: dict, order: tuple[str, ...]) -> list[str]:
    """Known keys in *order* first, then any extra keys in their original order."""
    known = [k for k in order if k in data]
    extra = [k for k in data if k not in order]
    return known + extra


def _canonicalise(data: dict) -> dict:
    out: dict = {}
    for key in _ordered_keys(data, CANONICAL_SPEC_KEYS):
        value = data[key]
        nested = _NESTED_KEY_ORDER.get(key)
        if nested is not None and isinstance(value, dict):
            value = {k: value[k] for k in _ordered_keys(value, nested)}
        out[key] = value
    return out


def _reorder_yaml_pyyaml(data: dict) -> str:
    """Reorder keys via PyYAML (drops comments — only used when there are none)."""
    canonical = _canonicalise(data)
    return yaml.dump(canonical, default_flow_style=False, sort_keys=False, allow_unicode=True)


def _reorder_yaml_ruamel(text: str) -> str | None:
    """Reorder keys while preserving comments, using ruamel.yaml.

    Returns ``None`` on any parse/dump failure so the caller falls back to the
    comment-safe text path rather than corrupting the file.
    """
    if not _HAS_RUAMEL:  # pragma: no cover - guarded by caller
        return None
    import io
    from typing import Any, cast

    try:
        ryaml = _RuamelYAML()
        ryaml.preserve_quotes = True
        # ruamel's CommentedMap is an ordered, dict-like mapping with
        # ``move_to_end``; it is untyped, so treat it as Any (an isinstance
        # check would narrow it to a plain dict, which lacks move_to_end).
        data: Any = ryaml.load(text)
        if not hasattr(data, "move_to_end"):
            return None
        for key in reversed(_ordered_keys(dict(data), CANONICAL_SPEC_KEYS)):
            data.move_to_end(key, last=False)
        for parent, nested in _NESTED_KEY_ORDER.items():
            child: Any = data.get(parent)
            if hasattr(child, "move_to_end"):
                for key in reversed(_ordered_keys(dict(child), nested)):
                    child.move_to_end(key, last=False)
        buf = io.StringIO()
        ryaml.dump(data, buf)
        return cast(str, buf.getvalue())
    except Exception:  # pragma: no cover - defensive fallback
        return None
