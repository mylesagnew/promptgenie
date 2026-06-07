import difflib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from promptgenie.core.fileio import safe_read_text
from promptgenie.core.generator import estimate_tokens, score_prompt
from promptgenie.core.linter import LintResult, lint
from promptgenie.core.scanner import ScanResult, scan

if TYPE_CHECKING:
    from promptgenie.core.config import PromptGenieConfig


@dataclass
class SectionDelta:
    name: str
    status: str  # "added" | "removed" | "changed" | "unchanged"
    a_lines: list[str] = field(default_factory=list)
    b_lines: list[str] = field(default_factory=list)


@dataclass
class DiffResult:
    # Raw text
    a_text: str
    b_text: str
    a_path: str
    b_path: str

    # Token delta
    a_tokens: int
    b_tokens: int

    # Quality scores
    a_score: dict
    b_score: dict

    # Lint
    a_lint: LintResult
    b_lint: LintResult

    # Security
    a_scan: ScanResult
    b_scan: ScanResult

    # Line-level diff
    unified_diff: list[str] = field(default_factory=list)

    # Section-level changes
    section_deltas: list[SectionDelta] = field(default_factory=list)

    @property
    def token_delta(self) -> int:
        return self.b_tokens - self.a_tokens

    @property
    def score_delta(self) -> int:
        return int(self.b_score["total"]) - int(self.a_score["total"])

    @property
    def lint_delta(self) -> int:
        return len(self.b_lint.issues) - len(self.a_lint.issues)

    @property
    def new_lint_issues(self) -> list:
        a_codes = {i.code for i in self.a_lint.issues}
        return [i for i in self.b_lint.issues if i.code not in a_codes]

    @property
    def resolved_lint_issues(self) -> list:
        b_codes = {i.code for i in self.b_lint.issues}
        return [i for i in self.a_lint.issues if i.code not in b_codes]

    @property
    def new_security_findings(self) -> list:
        a_codes = {f.code for f in self.a_scan.findings}
        return [f for f in self.b_scan.findings if f.code not in a_codes]

    @property
    def resolved_security_findings(self) -> list:
        b_codes = {f.code for f in self.b_scan.findings}
        return [f for f in self.a_scan.findings if f.code not in b_codes]


def _extract_sections(text: str) -> dict[str, list[str]]:
    """Split a prompt into sections keyed by markdown heading."""
    sections: dict[str, list[str]] = {}
    current = "__preamble__"
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if lines:
                sections[current] = lines
            current = line[3:].strip()
            lines = []
        else:
            lines.append(line)
    if lines:
        sections[current] = lines
    return sections


def _section_deltas(a_text: str, b_text: str) -> list[SectionDelta]:
    a_sections = _extract_sections(a_text)
    b_sections = _extract_sections(b_text)
    all_keys = list(dict.fromkeys(list(a_sections) + list(b_sections)))
    deltas = []
    for key in all_keys:
        a_lines = a_sections.get(key, [])
        b_lines = b_sections.get(key, [])
        if key not in a_sections:
            status = "added"
        elif key not in b_sections:
            status = "removed"
        elif a_lines == b_lines:
            status = "unchanged"
        else:
            status = "changed"
        deltas.append(SectionDelta(name=key, status=status, a_lines=a_lines, b_lines=b_lines))
    return deltas


def diff_prompts(
    a_path: str,
    b_path: str,
    target: str = "claude",
    config: "PromptGenieConfig | None" = None,
) -> DiffResult:
    a_text = safe_read_text(a_path)
    b_text = safe_read_text(b_path)

    # Load profile for scoring (best-effort)
    try:
        from promptgenie.core.generator import load_profile

        profile = load_profile(target)
    except Exception:
        profile = {"name": target, "required_sections": [], "forbidden_patterns": []}

    a_tokens = estimate_tokens(a_text)
    b_tokens = estimate_tokens(b_text)

    a_score = score_prompt(a_text, profile)
    b_score = score_prompt(b_text, profile)

    linter_cfg = config.linter if config is not None else None
    scanner_cfg = config.scanner if config is not None else None

    a_lint = lint(a_text, config=linter_cfg)
    b_lint = lint(b_text, config=linter_cfg)

    a_scan = scan(a_text, config=scanner_cfg)
    b_scan = scan(b_text, config=scanner_cfg)

    unified = list(
        difflib.unified_diff(
            a_text.splitlines(keepends=True),
            b_text.splitlines(keepends=True),
            fromfile=a_path,
            tofile=b_path,
            lineterm="",
        )
    )

    deltas = _section_deltas(a_text, b_text)

    return DiffResult(
        a_text=a_text,
        b_text=b_text,
        a_path=a_path,
        b_path=b_path,
        a_tokens=a_tokens,
        b_tokens=b_tokens,
        a_score=a_score,
        b_score=b_score,
        a_lint=a_lint,
        b_lint=b_lint,
        a_scan=a_scan,
        b_scan=b_scan,
        unified_diff=unified,
        section_deltas=deltas,
    )
