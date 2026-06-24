"""change_detector.py — Git-aware changed-prompt detector.

Determines which prompt/spec files have changed relative to a base ref
(default: origin/main) so that lint, scan, test, and evaluate commands
can run only on affected files rather than the entire repo.

Dependency-aware expansion rules
---------------------------------
- A changed PromptSpec (.yaml) → include itself
- A changed template (*.md / *.txt referenced by specs) → include all
  specs that reference it
- A changed policy file → include ALL specs in the working tree
- A changed vars file → include all specs that reference it

Public API
----------
  ``detect_changed_prompts(...)``   → ChangedSet
  ``ChangedSet``                    — dataclass with files and reason map
  ``expand_dependencies(...)``      → ChangedSet  (add transitive files)
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_SPEC_EXTS = {".yaml", ".yml"}
_PROMPT_EXTS = {".md", ".txt", ".prompt"}
_POLICY_NAMES = {
    ".promptgenie.policy.yaml",
    "promptgenie.policy.yaml",
}
_VARS_EXTS = {".yaml", ".yml", ".env", ".vars"}

# Regex to detect references inside a PromptSpec to template/vars files
_TEMPLATE_REF_RE = re.compile(
    r"template\s*:\s*['\"]?([^\s'\"]+)['\"]?", re.IGNORECASE
)
_VARS_REF_RE = re.compile(
    r"vars_file\s*:\s*['\"]?([^\s'\"]+)['\"]?", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ChangedSet:
    files: list[Path] = field(default_factory=list)
    reason: dict[str, str] = field(default_factory=dict)  # path → reason string
    policy_changed: bool = False
    all_specs_affected: bool = False

    def add(self, path: Path, reason: str) -> None:
        if path not in self.files:
            self.files.append(path)
        self.reason[str(path)] = reason

    def __len__(self) -> int:
        return len(self.files)

    def __iter__(self):
        return iter(self.files)


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git_changed_files(base_ref: str = "origin/main") -> list[Path]:
    """Return list of files changed relative to *base_ref* (git diff)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            # Fallback: diff working tree vs HEAD
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                capture_output=True, text=True, timeout=30,
            )
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        return [Path(l) for l in lines]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def _git_staged_files() -> list[Path]:
    """Return list of staged (index) files."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, timeout=15,
        )
        lines = [l.strip() for l in result.stdout.splitlines() if l.strip()]
        return [Path(l) for l in lines]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []


def _is_in_git_repo() -> bool:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=5,
        )
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# ---------------------------------------------------------------------------
# Spec dependency graph
# ---------------------------------------------------------------------------

def _build_dependency_graph(
    root: Path,
) -> tuple[dict[Path, list[Path]], dict[Path, list[Path]]]:
    """
    Scan all PromptSpec YAML files under *root*.

    Returns:
        template_deps: {template_path: [spec_paths that reference it]}
        vars_deps: {vars_path: [spec_paths that reference it]}
    """
    template_deps: dict[Path, list[Path]] = {}
    vars_deps: dict[Path, list[Path]] = {}

    for spec_file in root.rglob("*.yaml"):
        try:
            text = spec_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        for m in _TEMPLATE_REF_RE.finditer(text):
            tmpl = (spec_file.parent / m.group(1)).resolve()
            template_deps.setdefault(tmpl, []).append(spec_file)

        for m in _VARS_REF_RE.finditer(text):
            vf = (spec_file.parent / m.group(1)).resolve()
            vars_deps.setdefault(vf, []).append(spec_file)

    return template_deps, vars_deps


def _all_spec_files(root: Path) -> list[Path]:
    """Return all PromptSpec YAML files under *root*."""
    return list(root.rglob("*.yaml")) + list(root.rglob("*.yml"))


# ---------------------------------------------------------------------------
# Main detector
# ---------------------------------------------------------------------------

def detect_changed_prompts(
    base_ref: str = "origin/main",
    *,
    include_staged: bool = False,
    root: Path | None = None,
    expand_deps: bool = True,
) -> ChangedSet:
    """
    Return the set of prompt/spec files affected by recent changes.

    Parameters
    ----------
    base_ref:
        Git ref to diff against (e.g. ``"origin/main"``, ``"HEAD~1"``).
    include_staged:
        Also include git-staged files.
    root:
        Repository root for dependency scanning. Defaults to cwd.
    expand_deps:
        If True, expand template/vars/policy changes to dependent specs.
    """
    root = root or Path(".")
    changed_set = ChangedSet()

    raw_changed = _git_changed_files(base_ref)
    if include_staged:
        for p in _git_staged_files():
            if p not in raw_changed:
                raw_changed.append(p)

    if not raw_changed:
        return changed_set

    # Check if policy file changed → affects everything
    policy_changed = any(p.name in _POLICY_NAMES for p in raw_changed)
    if policy_changed:
        changed_set.policy_changed = True
        changed_set.all_specs_affected = True
        for spec in _all_spec_files(root):
            changed_set.add(spec, "policy file changed — all specs affected")
        return changed_set

    # Direct spec/prompt changes
    for p in raw_changed:
        if p.suffix in _SPEC_EXTS:
            changed_set.add(p, "directly modified")
        elif p.suffix in _PROMPT_EXTS:
            changed_set.add(p, "directly modified")

    if not expand_deps:
        return changed_set

    # Dependency expansion
    template_deps, vars_deps = _build_dependency_graph(root)

    for p in raw_changed:
        # Template file changed → add all dependent specs
        resolved = (root / p).resolve()
        if resolved in template_deps:
            for spec in template_deps[resolved]:
                changed_set.add(spec, f"template {p.name} changed")

        # Vars file changed → add all dependent specs
        if resolved in vars_deps:
            for spec in vars_deps[resolved]:
                changed_set.add(spec, f"vars file {p.name} changed")

    return changed_set


# ---------------------------------------------------------------------------
# Filter helpers for CLI commands
# ---------------------------------------------------------------------------

def filter_to_changed(
    file_paths: Iterable[str | Path],
    base_ref: str = "origin/main",
    *,
    include_staged: bool = False,
    root: Path | None = None,
) -> list[Path]:
    """
    Given a list of files (from CLI globs or discovery), return only those
    that appear in the changed set.

    Useful for: ``promptgenie lint --changed``, ``promptgenie test --changed``
    """
    changed = detect_changed_prompts(
        base_ref, include_staged=include_staged, root=root
    )
    changed_resolved = {p.resolve() for p in changed.files}
    return [
        Path(f) for f in file_paths
        if Path(f).resolve() in changed_resolved
    ]
