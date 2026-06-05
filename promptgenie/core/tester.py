"""
tester.py — prompt unit tests with declarative YAML test suites.

Test file format (.prompt-test.yaml):

    prompt: path/to/my-prompt.md        # prompt under test
    target: claude-code                 # profile used for scoring
    description: "Auth refactor prompt" # optional

    tests:
      - name: has stop conditions
        must_include:
          - "Stop and ask"
          - "approval"
        must_not_include:
          - "deploy to production"

      - name: scope is restricted
        must_include:
          - "src/auth"
        must_not_include:
          - "entire codebase"
          - "all files"

      - name: quality score threshold
        min_score: 80

      - name: no high lint issues
        max_lint_severity: MEDIUM      # fail if any issue is worse than this

      - name: no security findings
        max_security_risk: LOW         # fail if any finding is worse than this

      - name: token budget
        max_tokens: 1000

      - name: required sections present
        required_sections:
          - Objective
          - Scope
          - Stop Conditions
          - Acceptance Criteria
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from promptgenie.core.generator import estimate_tokens, load_profile, score_prompt
from promptgenie.core.linter import lint
from promptgenie.core.scanner import scan

SEVERITY_ORDER = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}
RISK_ORDER = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}


@dataclass
class TestAssertion:
    kind: str
    detail: str
    passed: bool
    actual: str = ""


@dataclass
class TestCaseResult:
    name: str
    passed: bool
    assertions: list[TestAssertion] = field(default_factory=list)

    @property
    def failure_count(self) -> int:
        return sum(1 for a in self.assertions if not a.passed)


@dataclass
class TestSuiteResult:
    prompt_path: str
    target: str
    description: str
    cases: list[TestCaseResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.cases)

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def pass_count(self) -> int:
        return sum(1 for c in self.cases if c.passed)

    @property
    def fail_count(self) -> int:
        return self.total - self.pass_count


def _run_case(
    case: dict,
    prompt_text: str,
    profile: dict,
    lint_result,
    scan_result,
    token_count: int,
    score: dict,
) -> TestCaseResult:
    name = case.get("name", "unnamed")
    assertions: list[TestAssertion] = []

    # must_include
    for phrase in case.get("must_include", []):
        found = phrase.lower() in prompt_text.lower()
        assertions.append(
            TestAssertion(
                kind="must_include",
                detail=f'Must contain: "{phrase}"',
                passed=found,
                actual="found" if found else "not found",
            )
        )

    # must_not_include
    for phrase in case.get("must_not_include", []):
        found = phrase.lower() in prompt_text.lower()
        assertions.append(
            TestAssertion(
                kind="must_not_include",
                detail=f'Must NOT contain: "{phrase}"',
                passed=not found,
                actual="not found" if not found else f'found: "{phrase}"',
            )
        )

    # min_score
    if "min_score" in case:
        threshold = int(case["min_score"])
        actual_score = score["total"]
        assertions.append(
            TestAssertion(
                kind="min_score",
                detail=f"Quality score ≥ {threshold}",
                passed=actual_score >= threshold,
                actual=str(actual_score),
            )
        )

    # max_tokens
    if "max_tokens" in case:
        limit = int(case["max_tokens"])
        assertions.append(
            TestAssertion(
                kind="max_tokens",
                detail=f"Token count ≤ {limit}",
                passed=token_count <= limit,
                actual=str(token_count),
            )
        )

    # max_lint_severity
    if "max_lint_severity" in case:
        allowed = SEVERITY_ORDER.get(case["max_lint_severity"].upper(), 99)
        violations = [i for i in lint_result.issues if SEVERITY_ORDER.get(i.severity, 0) > allowed]
        assertions.append(
            TestAssertion(
                kind="max_lint_severity",
                detail=f"No lint issues worse than {case['max_lint_severity'].upper()}",
                passed=len(violations) == 0,
                actual="ok"
                if not violations
                else f"{len(violations)} violation(s): "
                + ", ".join(f"[{v.severity}] {v.code}" for v in violations),
            )
        )

    # max_security_risk
    if "max_security_risk" in case:
        allowed = RISK_ORDER.get(case["max_security_risk"].upper(), 99)
        violations = [f for f in scan_result.findings if RISK_ORDER.get(f.risk, 0) > allowed]
        assertions.append(
            TestAssertion(
                kind="max_security_risk",
                detail=f"No security findings worse than {case['max_security_risk'].upper()}",
                passed=len(violations) == 0,
                actual="ok"
                if not violations
                else f"{len(violations)} violation(s): "
                + ", ".join(f"[{v.risk}] {v.code}" for v in violations),
            )
        )

    # required_sections
    for section in case.get("required_sections", []):
        present = bool(
            re.search(rf"^##\s+{re.escape(section)}", prompt_text, re.MULTILINE | re.IGNORECASE)
        )
        assertions.append(
            TestAssertion(
                kind="required_section",
                detail=f"Section present: ## {section}",
                passed=present,
                actual="present" if present else "missing",
            )
        )

    # regex_match — coerce to str in case YAML parsed as list/other
    for pattern in [str(p) for p in case.get("regex_match", [])]:
        try:
            matched = bool(re.search(pattern, prompt_text, re.IGNORECASE))
            assertions.append(
                TestAssertion(
                    kind="regex_match",
                    detail=f"Regex match: {pattern}",
                    passed=matched,
                    actual="matched" if matched else "no match",
                )
            )
        except re.error as exc:
            assertions.append(
                TestAssertion(
                    kind="regex_match",
                    detail=f"Regex match: {pattern}",
                    passed=False,
                    actual=f"invalid regex: {exc}",
                )
            )

    # regex_not_match — coerce to str in case YAML parsed as list/other
    for pattern in [str(p) for p in case.get("regex_not_match", [])]:
        try:
            matched = bool(re.search(pattern, prompt_text, re.IGNORECASE))
            assertions.append(
                TestAssertion(
                    kind="regex_not_match",
                    detail=f"Regex must NOT match: {pattern}",
                    passed=not matched,
                    actual="no match" if not matched else "matched (unexpected)",
                )
            )
        except re.error as exc:
            assertions.append(
                TestAssertion(
                    kind="regex_not_match",
                    detail=f"Regex must NOT match: {pattern}",
                    passed=False,
                    actual=f"invalid regex: {exc}",
                )
            )

    passed = all(a.passed for a in assertions)
    return TestCaseResult(name=name, passed=passed, assertions=assertions)


def run_test_suite(test_file: str) -> TestSuiteResult:
    test_path = Path(test_file)
    with open(test_path) as f:
        suite_def = yaml.safe_load(f)

    prompt_ref = suite_def.get("prompt", "")
    # Resolve relative to the test file's directory
    prompt_path = (test_path.parent / prompt_ref).resolve() if prompt_ref else None
    if not prompt_path or not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_ref}")

    prompt_text = prompt_path.read_text()
    target = suite_def.get("target", "claude")
    description = suite_def.get("description", "")

    try:
        profile = load_profile(target)
    except FileNotFoundError:
        profile = {"name": target, "required_sections": [], "forbidden_patterns": []}

    token_count = estimate_tokens(prompt_text)
    score = score_prompt(prompt_text, profile)
    lint_result = lint(prompt_text)
    scan_result = scan(prompt_text)

    results = TestSuiteResult(
        prompt_path=str(prompt_path),
        target=target,
        description=description,
    )

    for case in suite_def.get("tests", []):
        results.cases.append(
            _run_case(case, prompt_text, profile, lint_result, scan_result, token_count, score)
        )

    return results
