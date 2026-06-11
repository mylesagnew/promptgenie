"""context_builder.py — assemble context from multiple sources.

Supported source types
----------------------
  file        — single file path
  glob        — glob pattern (e.g. src/**/*.py)
  stdin       — read from sys.stdin
  env         — read from an environment variable
  cmd         — run a shell command and capture stdout
  git_diff    — output of ``git diff``
  git_staged  — output of ``git diff --staged``
  url         — HTTP GET (policy-gated by default)

Each gathered chunk is called a *SourceEntry*. After gathering, the builder
trims to a token budget using one of four strategies:

  newest      — newest files first (mtime)
  smallest    — shortest sources first (fewer tokens used)
  git-relevant — sources touched in recent git commits first
  manual      — preserve spec order as-is (default)

Public API
----------
  ``build_context(sources, *, max_tokens, strategy, base_dir, no_url)``
      → ContextManifest

  ``ContextManifest``
      .text       — assembled context string ready to prepend to the prompt
      .entries    — list[SourceEntry] with hash + token_estimate
      .total_tokens — estimated token count of the assembled text
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import re
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from promptgenie.core.errors import EXIT_PROVIDER, EXIT_USAGE, PromptGenieError

# ---------------------------------------------------------------------------
# Token estimator (simple whitespace-based; no tiktoken dep required)
# ---------------------------------------------------------------------------

_CHARS_PER_TOKEN = 4  # rough heuristic


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


# ---------------------------------------------------------------------------
# .promptignore support
# ---------------------------------------------------------------------------


def _load_promptignore(base_dir: Path) -> list[str]:
    ignore_file = base_dir / ".promptignore"
    if not ignore_file.exists():
        return []
    lines = ignore_file.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def _is_ignored(path: Path, patterns: list[str], base_dir: Path) -> bool:
    try:
        rel = str(path.relative_to(base_dir))
    except ValueError:
        rel = str(path)
    for pat in patterns:
        if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(path.name, pat):
            return True
    return False


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SourceEntry:
    label: str  # human-readable label
    source_type: str  # file | glob | stdin | env | cmd | git_diff | git_staged | url
    content: str
    path: str = ""  # file path if applicable
    sha256: str = ""  # hex digest of content
    token_estimate: int = 0
    included: bool = True  # False if trimmed by budget
    mtime: float = 0.0  # for 'newest' strategy


@dataclass
class ContextManifest:
    text: str  # assembled context text
    entries: list[SourceEntry] = field(default_factory=list)
    total_tokens: int = 0
    trimmed_count: int = 0  # number of entries excluded by budget


# ---------------------------------------------------------------------------
# Gatherers
# ---------------------------------------------------------------------------


def _gather_file(path_str: str, label: str, max_bytes: int, base_dir: Path,
                 ignore_patterns: list[str]) -> SourceEntry | None:
    p = Path(path_str)
    if not p.is_absolute():
        p = base_dir / p
    if not p.exists():
        return None
    if _is_ignored(p, ignore_patterns, base_dir):
        return None
    try:
        stat = p.stat()
        raw = p.read_bytes()
        if max_bytes and len(raw) > max_bytes:
            raw = raw[:max_bytes]
        content = raw.decode("utf-8", errors="replace")
        sha = hashlib.sha256(raw).hexdigest()
        lbl = label or str(p.relative_to(base_dir) if p.is_relative_to(base_dir) else p)
        return SourceEntry(
            label=lbl,
            source_type="file",
            content=content,
            path=str(p),
            sha256=sha,
            token_estimate=_estimate_tokens(content),
            mtime=stat.st_mtime,
        )
    except OSError:
        return None


def _gather_glob(pattern: str, label: str, max_bytes: int, base_dir: Path,
                 ignore_patterns: list[str]) -> list[SourceEntry]:
    entries: list[SourceEntry] = []
    for p in sorted(base_dir.glob(pattern)):
        if p.is_file():
            e = _gather_file(str(p), "", max_bytes, base_dir, ignore_patterns)
            if e:
                entries.append(e)
    return entries


def _gather_stdin(label: str) -> SourceEntry:
    content = sys.stdin.read()
    sha = hashlib.sha256(content.encode()).hexdigest()
    return SourceEntry(
        label=label or "<stdin>",
        source_type="stdin",
        content=content,
        sha256=sha,
        token_estimate=_estimate_tokens(content),
    )


def _gather_env(var_name: str, label: str) -> SourceEntry | None:
    value = os.environ.get(var_name)
    if value is None:
        return None
    sha = hashlib.sha256(value.encode()).hexdigest()
    return SourceEntry(
        label=label or f"env:{var_name}",
        source_type="env",
        content=value,
        sha256=sha,
        token_estimate=_estimate_tokens(value),
    )


def _gather_cmd(command: str, label: str, max_bytes: int) -> SourceEntry:
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
        content = result.stdout
        if max_bytes and len(content) > max_bytes:
            content = content[:max_bytes]
        sha = hashlib.sha256(content.encode()).hexdigest()
        return SourceEntry(
            label=label or f"cmd:{command[:60]}",
            source_type="cmd",
            content=content,
            sha256=sha,
            token_estimate=_estimate_tokens(content),
        )
    except subprocess.TimeoutExpired as exc:
        raise PromptGenieError(
            f"Command timed out: {command}", code=EXIT_PROVIDER
        ) from exc


def _gather_git(staged: bool, label: str) -> SourceEntry:
    cmd = ["git", "diff", "--staged"] if staged else ["git", "diff"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        content = result.stdout or "(no diff)\n"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        content = "(git not available)\n"
    sha = hashlib.sha256(content.encode()).hexdigest()
    src_type = "git_staged" if staged else "git_diff"
    return SourceEntry(
        label=label or src_type,
        source_type=src_type,
        content=content,
        sha256=sha,
        token_estimate=_estimate_tokens(content),
    )


def _gather_url(url: str, label: str, max_bytes: int, no_url: bool) -> SourceEntry:
    if no_url:
        raise PromptGenieError(
            f"URL context source '{url}' is blocked (policy-gated). "
            "Pass --allow-url to permit network fetches.",
            code=EXIT_USAGE,
        )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PromptGenie/2.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read(max_bytes or 512_000)
        content = raw.decode("utf-8", errors="replace")
        sha = hashlib.sha256(raw).hexdigest()
        return SourceEntry(
            label=label or url,
            source_type="url",
            content=content,
            sha256=sha,
            token_estimate=_estimate_tokens(content),
        )
    except Exception as exc:
        raise PromptGenieError(
            f"Failed to fetch URL context '{url}': {exc}",
            code=EXIT_PROVIDER,
        ) from exc


# ---------------------------------------------------------------------------
# Strategy sorters
# ---------------------------------------------------------------------------


def _apply_strategy(entries: list[SourceEntry], strategy: str) -> list[SourceEntry]:
    if strategy == "newest":
        return sorted(entries, key=lambda e: e.mtime, reverse=True)
    if strategy == "smallest":
        return sorted(entries, key=lambda e: e.token_estimate)
    if strategy == "git-relevant":
        # Best effort: entries from git_diff/git_staged first, then by mtime
        def _git_key(e: SourceEntry) -> tuple[int, float]:
            git_first = 0 if e.source_type in ("git_diff", "git_staged") else 1
            return (git_first, -e.mtime)
        return sorted(entries, key=_git_key)
    # manual / unknown: preserve order
    return entries


# ---------------------------------------------------------------------------
# Main assembler
# ---------------------------------------------------------------------------


def build_context(
    sources: list[Any],  # list[ContextSource] from spec.py
    *,
    max_tokens: int = 0,
    strategy: str = "manual",
    base_dir: Path | None = None,
    no_url: bool = True,
) -> ContextManifest:
    """Gather all context sources and assemble them into a ContextManifest.

    Parameters
    ----------
    sources:
        List of ContextSource objects (from promptgenie.core.spec).
    max_tokens:
        Budget ceiling. 0 = unlimited.
    strategy:
        Ordering strategy for budget trimming: newest | smallest | git-relevant | manual.
    base_dir:
        Base directory for resolving relative paths. Defaults to cwd.
    no_url:
        If True, block url-type sources unless explicitly allowed.
    """
    base_dir = base_dir or Path.cwd()
    ignore_patterns = _load_promptignore(base_dir)
    raw_entries: list[SourceEntry] = []

    for src in sources:
        src_type = src.type
        lbl = src.label
        mb = src.max_bytes

        if src_type == "file":
            e = _gather_file(src.path, lbl, mb, base_dir, ignore_patterns)
            if e:
                raw_entries.append(e)
        elif src_type == "glob":
            raw_entries.extend(_gather_glob(src.pattern, lbl, mb, base_dir, ignore_patterns))
        elif src_type == "stdin":
            raw_entries.append(_gather_stdin(lbl))
        elif src_type == "env":
            e = _gather_env(src.var, lbl)
            if e:
                raw_entries.append(e)
        elif src_type == "cmd":
            raw_entries.append(_gather_cmd(src.command, lbl, mb))
        elif src_type == "git_diff":
            raw_entries.append(_gather_git(staged=False, label=lbl))
        elif src_type == "git_staged":
            raw_entries.append(_gather_git(staged=True, label=lbl))
        elif src_type == "url":
            gate = src.policy_gated if hasattr(src, "policy_gated") else True
            raw_entries.append(_gather_url(src.url, lbl, mb, no_url=gate and no_url))

    # Apply ordering strategy
    ordered = _apply_strategy(raw_entries, strategy)

    # Budget trimming
    final: list[SourceEntry] = []
    trimmed = 0
    used_tokens = 0
    for entry in ordered:
        if max_tokens and (used_tokens + entry.token_estimate) > max_tokens:
            entry.included = False
            trimmed += 1
        else:
            used_tokens += entry.token_estimate
            entry.included = True
            final.append(entry)

    # Re-insert excluded entries at end (for manifest visibility)
    excluded = [e for e in ordered if not e.included]
    all_entries = final + excluded

    # Assemble text
    parts: list[str] = []
    for entry in final:
        header = f"### [{entry.source_type}] {entry.label}\n"
        parts.append(header + entry.content)

    text = "\n\n".join(parts)

    return ContextManifest(
        text=text,
        entries=all_entries,
        total_tokens=_estimate_tokens(text),
        trimmed_count=trimmed,
    )
