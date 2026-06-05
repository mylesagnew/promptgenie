import re
from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["HIGH", "MEDIUM", "LOW", "INFO"]


@dataclass
class LintIssue:
    severity: Severity
    code: str
    message: str
    suggestion: str = ""


@dataclass
class LintResult:
    issues: list[LintIssue] = field(default_factory=list)

    @property
    def score(self) -> int:
        penalty = sum({"HIGH": 20, "MEDIUM": 10, "LOW": 5, "INFO": 1}.get(i.severity, 0) for i in self.issues)
        return max(0, 100 - penalty)

    def by_severity(self, sev: Severity) -> list[LintIssue]:
        return [i for i in self.issues if i.severity == sev]


VAGUE_VERBS = [
    "help", "fix", "improve", "make better", "make it better", "do something",
    "handle it", "deal with", "sort out", "look at", "check it", "work on",
]

AGENTIC_RISK_PATTERNS = [
    (r"do whatever it takes", "HIGH", "AGENT_001", "Unbounded agent instruction."),
    (r"fix everything", "HIGH", "AGENT_002", "Overly broad scope — agent will interpret liberally."),
    (r"use your judgement", "MEDIUM", "AGENT_003", "Defers decisions to model; add explicit stop conditions."),
    (r"install (any|all|whatever|the) (dependencies|packages|libs)", "HIGH", "AGENT_004", "Allows unrestricted package installation."),
    (r"deploy to (production|prod|live)", "HIGH", "AGENT_005", "Prompt allows production deployment without approval gate."),
    (r"drop (the |all )?(table|database|db|schema)", "HIGH", "AGENT_006", "Prompt allows destructive database operations."),
    (r"delete (all|every|the whole|everything)", "HIGH", "AGENT_007", "Prompt allows mass deletion."),
    (r"run (as|with) (root|admin|sudo)", "HIGH", "AGENT_008", "Prompt requests elevated privileges."),
]

MISSING_SECTIONS = [
    ("stop condition", ["stop if", "stop and ask", "halt", "pause", "do not proceed", "wait for approval"], "MEDIUM", "STRUCT_001",
     "No stop conditions found for agentic prompt."),
    ("scope definition", ["only", "limit", "restrict", "scope", "bounded", "the following files", "these files"], "MEDIUM", "STRUCT_002",
     "No file/task scope defined."),
    ("forbidden actions", ["do not", "forbidden", "must not", "never", "avoid", "prohibited"], "LOW", "STRUCT_003",
     "No forbidden actions listed."),
    ("output format", ["output", "format", "respond with", "return", "json", "markdown", "table", "list"], "LOW", "STRUCT_004",
     "No output format specified."),
    ("success criteria", ["done when", "acceptance", "success", "test pass", "complete when", "verify that"], "LOW", "STRUCT_005",
     "No acceptance criteria or success definition."),
]


def lint(prompt: str) -> LintResult:
    result = LintResult()
    lower = prompt.lower()

    # Vague verb check
    for verb in VAGUE_VERBS:
        if re.search(rf"\b{re.escape(verb)}\b", lower):
            result.issues.append(LintIssue(
                severity="MEDIUM",
                code="TASK_001",
                message=f'Vague verb detected: "{verb}".',
                suggestion='Replace with a specific, measurable action (e.g. "refactor", "extract", "add unit tests for").',
            ))
            break  # one warning per class

    # Multiple tasks
    task_markers = ["also", "and then", "additionally", "as well as", "plus also", "furthermore"]
    found_markers = [m for m in task_markers if m in lower]
    if len(found_markers) >= 2:
        result.issues.append(LintIssue(
            severity="MEDIUM",
            code="TASK_002",
            message="Prompt may contain multiple tasks (chained with: " + ", ".join(found_markers[:3]) + ").",
            suggestion="Split into separate focused prompts or use a staged workflow.",
        ))

    # Missing target
    if not any(t in lower for t in ["claude", "chatgpt", "gpt", "cursor", "gemini", "midjourney", "stable diffusion"]):
        result.issues.append(LintIssue(
            severity="HIGH",
            code="TASK_003",
            message="No target AI tool specified.",
            suggestion="Add the intended tool (Claude, Claude Code, ChatGPT, Cursor, etc.).",
        ))

    # Agentic risk patterns
    for pattern, sev, code, msg in AGENTIC_RISK_PATTERNS:
        if re.search(pattern, lower):
            result.issues.append(LintIssue(severity=sev, code=code, message=msg,
                                            suggestion="Add explicit constraints and approval gates."))

    # Missing structural sections (only flag if prompt looks agentic/substantial)
    is_agentic = any(w in lower for w in ["refactor", "implement", "build", "create", "migrate", "agent", "claude code", "cursor"])
    if is_agentic or len(prompt) > 200:
        for section_name, keywords, sev, code, msg in MISSING_SECTIONS:
            if not any(k in lower for k in keywords):
                result.issues.append(LintIssue(severity=sev, code=code, message=msg,
                                                suggestion=f"Add a {section_name} section."))

    # Over-broad scope
    if re.search(r"(the whole|entire|whole|all of the) (app|codebase|repo|project|system)", lower):
        result.issues.append(LintIssue(
            severity="MEDIUM",
            code="TASK_004",
            message="Scope is too broad — references the whole app/codebase.",
            suggestion="Narrow scope to specific modules, files, or functions.",
        ))

    return result
