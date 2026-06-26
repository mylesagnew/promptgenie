import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, TypeGuard, get_args

if TYPE_CHECKING:
    from promptgenie.core.config import LinterConfig

Severity = Literal["HIGH", "MEDIUM", "LOW", "INFO"]
Confidence = Literal["HIGH", "MEDIUM", "LOW"]


def _is_severity(v: str) -> TypeGuard[Severity]:
    return v in get_args(Severity)


def coerce_severity(raw: str, context: str = "") -> Severity:
    """Validate and narrow a raw string to ``Severity``."""
    upper = raw.strip().upper()
    if not _is_severity(upper):
        ctx = f" ({context})" if context else ""
        raise ValueError(
            f"Invalid severity {raw!r}{ctx}; must be one of {', '.join(get_args(Severity))}"
        )
    return upper


def _offset_to_line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a byte offset into 1-based (line, col)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - before.rfind("\n")
    return line, col


@dataclass
class LintIssue:
    severity: Severity
    code: str
    message: str
    suggestion: str = ""
    confidence: Confidence = "MEDIUM"
    line: int = 0
    col: int = 0


@dataclass
class LintResult:
    issues: list[LintIssue] = field(default_factory=list)

    @property
    def score(self) -> int:
        penalty = sum(
            {"HIGH": 20, "MEDIUM": 10, "LOW": 5, "INFO": 1}.get(i.severity, 0) for i in self.issues
        )
        return max(0, 100 - penalty)

    def by_severity(self, sev: Severity) -> list[LintIssue]:
        return [i for i in self.issues if i.severity == sev]


@dataclass
class LintRule:
    """A single linter rule entry.

    Fields:
        id                Stable rule code (e.g. AGENT_001).
        category          Logical grouping: task_quality | agentic_risk | structure.
        pattern           Python regex pattern. For negate=True rules, the issue is emitted
                          when the pattern does NOT match (used for missing-section checks).
        severity          Issue severity: HIGH | MEDIUM | LOW | INFO.
        confidence        Detector confidence: HIGH | MEDIUM | LOW.
        message           Short human-readable issue description.
        suggestion        Actionable fix guidance shown to the user.
        false_positive_note  Common false-positive scenarios to help reviewers triage.
        negate            When True, emit the issue only when pattern does NOT match.
                          Use for "missing section" rules.
        requires_agentic  When True, only apply this rule to agentic/substantial prompts
                          (prompts with agentic keywords or length > 200 chars).
    """

    id: str
    category: str
    pattern: str
    severity: Severity
    confidence: Confidence
    message: str
    suggestion: str
    false_positive_note: str = ""
    negate: bool = False
    requires_agentic: bool = False


# Vague verbs checked as a word-boundary list (single finding per prompt).
VAGUE_VERBS = [
    "help",
    "fix",
    "improve",
    "make better",
    "make it better",
    "do something",
    "handle it",
    "deal with",
    "sort out",
    "look at",
    "check it",
    "work on",
]

# ── Built-in rule registry ────────────────────────────────────────────────────

LINT_RULES: list[LintRule] = [
    # Agentic risk patterns
    LintRule(
        id="AGENT_001",
        category="agentic_risk",
        pattern=r"do whatever it takes",
        severity="HIGH",
        confidence="HIGH",
        message="Unbounded agent instruction.",
        suggestion="Add explicit constraints and approval gates.",
    ),
    LintRule(
        id="AGENT_002",
        category="agentic_risk",
        pattern=r"fix everything",
        severity="HIGH",
        confidence="HIGH",
        message="Overly broad scope — agent will interpret liberally.",
        suggestion="Add explicit constraints and approval gates.",
    ),
    LintRule(
        id="AGENT_003",
        category="agentic_risk",
        pattern=r"use your judgement",
        severity="MEDIUM",
        confidence="MEDIUM",
        message="Defers decisions to model; add explicit stop conditions.",
        suggestion="Add explicit constraints and approval gates.",
    ),
    LintRule(
        id="AGENT_004",
        category="agentic_risk",
        pattern=r"install (any|all|whatever|the) (dependencies|packages|libs)",
        severity="HIGH",
        confidence="HIGH",
        message="Allows unrestricted package installation.",
        suggestion="Add explicit constraints and approval gates.",
    ),
    LintRule(
        id="AGENT_005",
        category="agentic_risk",
        pattern=r"deploy to (production|prod|live)",
        severity="HIGH",
        confidence="HIGH",
        message="Prompt allows production deployment without approval gate.",
        suggestion="Add explicit constraints and approval gates.",
    ),
    LintRule(
        id="AGENT_006",
        category="agentic_risk",
        pattern=r"drop (the |all )?(table|database|db|schema)",
        severity="HIGH",
        confidence="HIGH",
        message="Prompt allows destructive database operations.",
        suggestion="Add explicit constraints and approval gates.",
    ),
    LintRule(
        id="AGENT_007",
        category="agentic_risk",
        pattern=r"delete (all|every|the whole|everything)",
        severity="HIGH",
        confidence="HIGH",
        message="Prompt allows mass deletion.",
        suggestion="Add explicit constraints and approval gates.",
    ),
    LintRule(
        id="AGENT_008",
        category="agentic_risk",
        pattern=r"run (as|with) (root|admin|sudo)",
        severity="HIGH",
        confidence="HIGH",
        message="Prompt requests elevated privileges.",
        suggestion="Add explicit constraints and approval gates.",
    ),
    # Missing structural sections (negate=True: emit when pattern NOT found)
    LintRule(
        id="STRUCT_001",
        category="structure",
        pattern=r"stop if|stop and ask|halt|pause|do not proceed|wait for approval",
        severity="MEDIUM",
        confidence="MEDIUM",
        message="No stop conditions found for agentic prompt.",
        suggestion="Add a stop condition section.",
        negate=True,
        requires_agentic=True,
    ),
    LintRule(
        id="STRUCT_002",
        category="structure",
        pattern=r"only|limit|restrict|scope|bounded|the following files|these files",
        severity="MEDIUM",
        confidence="MEDIUM",
        message="No file/task scope defined.",
        suggestion="Add a scope definition section.",
        negate=True,
        requires_agentic=True,
    ),
    LintRule(
        id="STRUCT_003",
        category="structure",
        pattern=r"do not|forbidden|must not|never|avoid|prohibited",
        severity="LOW",
        confidence="MEDIUM",
        message="No forbidden actions listed.",
        suggestion="Add a forbidden actions section.",
        negate=True,
        requires_agentic=True,
    ),
    LintRule(
        id="STRUCT_004",
        category="structure",
        pattern=r"output|format|respond with|return|json|markdown|table|list",
        severity="LOW",
        confidence="MEDIUM",
        message="No output format specified.",
        suggestion="Add an output format section.",
        negate=True,
        requires_agentic=True,
    ),
    LintRule(
        id="STRUCT_005",
        category="structure",
        pattern=r"done when|acceptance|success|test pass|complete when|verify that",
        severity="LOW",
        confidence="MEDIUM",
        message="No acceptance criteria or success definition.",
        suggestion="Add a success criteria section.",
        negate=True,
        requires_agentic=True,
    ),
    # Task quality — over-broad scope
    LintRule(
        id="TASK_004",
        category="task_quality",
        pattern=r"(the whole|entire|whole|all of the) (app|codebase|repo|project|system)",
        severity="MEDIUM",
        confidence="HIGH",
        message="Scope is too broad — references the whole app/codebase.",
        suggestion="Narrow scope to specific modules, files, or functions.",
    ),
]

# Keywords that signal an agentic/substantial prompt context.
_AGENTIC_KEYWORDS = [
    "refactor",
    "implement",
    "build",
    "create",
    "migrate",
    "agent",
    "claude code",
    "cursor",
]


def lint(prompt: str, config: "LinterConfig | None" = None) -> LintResult:
    from promptgenie.core.config import LinterConfig as _LinterConfig

    cfg: _LinterConfig = config if config is not None else _LinterConfig()
    result = LintResult()
    lower = prompt.lower()

    is_agentic = any(w in lower for w in _AGENTIC_KEYWORDS) or len(prompt) > 200

    effective_vague_verbs = list(VAGUE_VERBS) + cfg.custom_vague_verbs

    # Vague verb check — one finding per class, break after first match
    for verb in effective_vague_verbs:
        m = re.search(rf"\b{re.escape(verb)}\b", lower)
        if m:
            line, col = _offset_to_line_col(lower, m.start())
            result.issues.append(
                LintIssue(
                    severity="MEDIUM",
                    code="TASK_001",
                    message=f'Vague verb detected: "{verb}".',
                    suggestion='Replace with a specific, measurable action (e.g. "refactor", "extract", "add unit tests for").',
                    confidence="HIGH",
                    line=line,
                    col=col,
                )
            )
            break

    # Multiple tasks check
    task_markers = ["also", "and then", "additionally", "as well as", "plus also", "furthermore"]
    found_markers = [m for m in task_markers if m in lower]
    if len(found_markers) >= 2:
        result.issues.append(
            LintIssue(
                severity="MEDIUM",
                code="TASK_002",
                message="Prompt may contain multiple tasks (chained with: "
                + ", ".join(found_markers[:3])
                + ").",
                suggestion="Split into separate focused prompts or use a staged workflow.",
                confidence="MEDIUM",
                line=1,
                col=1,
            )
        )

    # Missing target check
    if not any(
        t in lower
        for t in ["claude", "chatgpt", "gpt", "cursor", "gemini", "midjourney", "stable diffusion"]
    ):
        result.issues.append(
            LintIssue(
                severity="HIGH",
                code="TASK_003",
                message="No target AI tool specified.",
                suggestion="Add the intended tool (Claude, Claude Code, ChatGPT, Cursor, etc.).",
                confidence="HIGH",
                line=1,
                col=1,
            )
        )

    # Load rules from rules_dirs (registry packs and custom rule dirs)
    dir_rules: list[LintRule] = []
    if cfg.rules_dirs:
        from promptgenie.core.registry import load_lint_rules_from_dirs

        dir_rules = load_lint_rules_from_dirs(cfg.rules_dirs)

    # Rule registry — agentic risk and structure rules
    active_rules = LINT_RULES + dir_rules + list(cfg.custom_lint_rules)

    # enabled_rules whitelist — if set, only run rules whose id is in the list
    if cfg.enabled_rules:
        active_rules = [r for r in active_rules if r.id in cfg.enabled_rules]
    for rule in active_rules:
        if rule.requires_agentic and not is_agentic:
            continue

        matched = re.search(rule.pattern, lower)

        if rule.negate:
            # Emit issue only when pattern is NOT found (missing section rules)
            if matched:
                continue
            result.issues.append(
                LintIssue(
                    severity=rule.severity,
                    code=rule.id,
                    message=rule.message,
                    suggestion=rule.suggestion,
                    confidence=rule.confidence,
                    line=1,
                    col=1,
                )
            )
        else:
            if not matched:
                continue
            line, col = _offset_to_line_col(lower, matched.start())
            result.issues.append(
                LintIssue(
                    severity=rule.severity,
                    code=rule.id,
                    message=rule.message,
                    suggestion=rule.suggestion,
                    confidence=rule.confidence,
                    line=line,
                    col=col,
                )
            )

    # Apply config: filter disabled rules; if enabled_rules set, filter to only those
    if cfg.enabled_rules:
        result.issues = [i for i in result.issues if i.code in cfg.enabled_rules]
    elif cfg.disabled_rules:
        result.issues = [i for i in result.issues if i.code not in cfg.disabled_rules]

    return result
