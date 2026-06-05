"""
workflow.py — staged prompt chains for complex agentic tasks.

A workflow breaks a complex task into a sequence of focused prompts.
Each step has its own objective, scope, stop conditions, expected output,
and a handoff summary that feeds into the next step.

This solves a real problem: agentic tools perform better with staged prompts
than with one large mega-prompt. Splitting reduces scope creep, makes failures
recoverable, and keeps each step verifiable.

Workflow file format (.workflow.yaml):

    name: secure-login-feature
    description: "Build a secure login system end-to-end"
    target: claude-code
    context_pack: react-supabase-app   # optional
    mode: standard

    steps:
      - id: inspect
        name: Inspect existing auth
        objective: "Map the current authentication architecture"
        scope:
          - src/auth/
          - src/middleware/
        output: "Architecture summary with file map and identified gaps"

      - id: plan
        name: Propose implementation plan
        depends_on: inspect
        objective: "Propose a JWT implementation plan based on the inspection"
        output: "Step-by-step plan with file list and risk notes"
        requires_approval: true

      - id: implement
        name: Implement middleware
        depends_on: plan
        objective: "Implement JWT middleware only"
        scope:
          - src/middleware/auth.ts
        forbidden:
          - Do not touch any other files
          - Do not install packages without approval
        stop_conditions:
          - Tests fail
          - A file outside scope needs changing
        output: "Diff of changed files + test results"

      - id: test
        name: Add tests
        depends_on: implement
        objective: "Write unit tests for the new JWT middleware"
        scope:
          - src/middleware/auth.test.ts
        output: "Test file with passing results"

      - id: review
        name: Security review
        depends_on: test
        objective: "Security review of the JWT implementation"
        output: "Findings table: issue / severity / recommendation"
        requires_approval: true
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import yaml

from promptgenie.core.context_packs import render_pack
from promptgenie.core.generator import estimate_tokens, load_profile


@dataclass
class WorkflowStep:
    id: str
    name: str
    objective: str
    depends_on: str | None = None
    scope: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)
    stop_conditions: list[str] = field(default_factory=list)
    output: str = ""
    requires_approval: bool = False
    context_note: str = ""


@dataclass
class RenderedStep:
    step: WorkflowStep
    prompt_text: str
    token_estimate: int
    step_number: int
    total_steps: int


@dataclass
class WorkflowResult:
    name: str
    description: str
    target: str
    steps: list[RenderedStep] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return sum(s.token_estimate for s in self.steps)

    @property
    def approval_gates(self) -> list[RenderedStep]:
        return [s for s in self.steps if s.step.requires_approval]


def _render_step(
    step: WorkflowStep,
    step_number: int,
    total_steps: int,
    profile: dict,
    mode: str,
    context_pack_block: str = "",
    prev_step: WorkflowStep | None = None,
) -> RenderedStep:
    _target_name = profile.get("name", "AI")
    parts: list[str] = []

    # Header
    parts.append(f"# Workflow Step {step_number}/{total_steps} — {step.name}\n")
    parts.append(f"**Workflow objective:** {step.objective}\n")

    # Context pack (minimal — just stack for downstream steps)
    if context_pack_block:
        parts.append(context_pack_block)

    # Handoff from previous step
    if prev_step:
        parts.append(
            f"## Handoff from Step {step_number - 1}: {prev_step.name}\n"
            f"The previous step produced: **{prev_step.output}**\n"
            f"Review that output before proceeding."
        )

    # Objective
    parts.append(f"## Objective\n{step.objective}")

    # Scope
    if step.scope:
        scope_list = "\n".join(f"- `{s}`" for s in step.scope)
        parts.append(f"## Scope\nWork only within:\n{scope_list}")
    elif profile.get("scope_guidance"):
        parts.append(f"## Scope\n{profile['scope_guidance']}")

    # Forbidden actions — merge step-level + profile-level
    forbidden = list(step.forbidden)
    if mode == "exhaustive":
        forbidden += profile.get("forbidden_patterns", [])
    if forbidden:
        parts.append("## Forbidden Actions\n" + "\n".join(f"- {f}" for f in forbidden))

    # Stop conditions — merge step-level + profile-level
    stops = list(step.stop_conditions)
    if not stops:
        stops = profile.get("stop_conditions", [])
    if stops:
        parts.append(
            "## Stop Conditions\nStop and ask for approval if:\n"
            + "\n".join(f"- {s}" for s in stops)
        )

    # Approval gate
    if step.requires_approval:
        parts.append(
            "## Approval Gate\n"
            "**Do not proceed to the next step** until the human has reviewed\n"
            "and explicitly approved the output of this step."
        )

    # Output
    expected_output = step.output or profile.get("default_output_format", "Structured markdown.")
    parts.append(f"## Expected Output\n{expected_output}")

    # Acceptance criteria
    parts.append(
        "## Acceptance Criteria\nThis step is complete when:\n"
        f"- The objective is fully met\n"
        f"- Output matches: {expected_output}\n"
        + ("- Human approval has been given\n" if step.requires_approval else "")
        + "- No forbidden actions were taken"
    )

    # Step context note
    if step.context_note:
        parts.append(f"## Notes\n{step.context_note}")

    prompt_text = "\n\n".join(parts)
    return RenderedStep(
        step=step,
        prompt_text=prompt_text,
        token_estimate=estimate_tokens(prompt_text),
        step_number=step_number,
        total_steps=total_steps,
    )


class WorkflowValidationError(Exception):
    """Raised when a workflow definition fails structural validation."""


def validate_workflow(steps: list[WorkflowStep]) -> None:
    """
    Validate a list of WorkflowSteps before rendering.

    Checks:
    - No duplicate step IDs
    - All depends_on references exist
    - No dependency cycles
    - Required fields are non-empty (id, name, objective)

    Raises WorkflowValidationError with a descriptive message on any failure.
    """
    # Required fields
    for i, step in enumerate(steps):
        for field_name in ("id", "name", "objective"):
            if not getattr(step, field_name, "").strip():
                raise WorkflowValidationError(
                    f"Step {i + 1}: required field '{field_name}' is missing or empty."
                )

    # Duplicate IDs
    seen_ids: set[str] = set()
    for step in steps:
        if step.id in seen_ids:
            raise WorkflowValidationError(f"Duplicate step ID: '{step.id}'.")
        seen_ids.add(step.id)

    # Unknown dependency references
    for step in steps:
        if step.depends_on and step.depends_on not in seen_ids:
            raise WorkflowValidationError(
                f"Step '{step.id}' depends_on unknown step '{step.depends_on}'."
            )

    # Cycle detection via DFS
    index = {s.id: s for s in steps}
    visiting: set[str] = set()
    visited: set[str] = set()

    def _dfs(step_id: str, path: list[str]) -> None:
        if step_id in visited:
            return
        if step_id in visiting:
            cycle = " → ".join(path + [step_id])
            raise WorkflowValidationError(f"Dependency cycle detected: {cycle}")
        visiting.add(step_id)
        dep = index[step_id].depends_on
        if dep and dep in index:
            _dfs(dep, path + [step_id])
        visiting.discard(step_id)
        visited.add(step_id)

    for s in steps:
        _dfs(s.id, [])


def _resolve_order(steps: list[WorkflowStep]) -> list[WorkflowStep]:
    """Topological sort respecting depends_on (assumes validate_workflow already ran)."""
    index = {s.id: s for s in steps}
    ordered: list[WorkflowStep] = []
    visited: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visited:
            return
        step = index[step_id]
        if step.depends_on and step.depends_on in index:
            visit(step.depends_on)
        visited.add(step_id)
        ordered.append(step)

    for s in steps:
        visit(s.id)
    return ordered


def load_workflow(workflow_path: str) -> dict:
    with open(workflow_path) as f:
        return cast(dict, yaml.safe_load(f))


def generate_workflow(workflow_path: str) -> WorkflowResult:
    data = load_workflow(workflow_path)

    name = data.get("name", "workflow")
    description = data.get("description", "")
    target = data.get("target", "claude-code")
    mode = data.get("mode", "standard")
    pack_id = data.get("context_pack")

    try:
        profile = load_profile(target)
    except FileNotFoundError:
        profile = {
            "name": target,
            "required_sections": [],
            "forbidden_patterns": [],
            "stop_conditions": [],
            "scope_guidance": "",
        }

    # Render context pack once (minimal mode for step injection)
    context_pack_block = ""
    if pack_id:
        with contextlib.suppress(FileNotFoundError):
            context_pack_block = render_pack(pack_id, mode="minimal")

    raw_steps = data.get("steps", [])
    steps = [
        WorkflowStep(
            id=s.get("id", f"step_{i}"),
            name=s.get("name", f"Step {i + 1}"),
            objective=s.get("objective", ""),
            depends_on=s.get("depends_on"),
            scope=s.get("scope", []),
            forbidden=s.get("forbidden", []),
            stop_conditions=s.get("stop_conditions", []),
            output=s.get("output", ""),
            requires_approval=s.get("requires_approval", False),
            context_note=s.get("context_note", ""),
        )
        for i, s in enumerate(raw_steps)
    ]

    validate_workflow(steps)
    ordered = _resolve_order(steps)
    total = len(ordered)
    _step_index = {s.id: s for s in ordered}

    rendered: list[RenderedStep] = []
    for i, step in enumerate(ordered):
        prev = ordered[i - 1] if i > 0 else None
        rs = _render_step(
            step=step,
            step_number=i + 1,
            total_steps=total,
            profile=profile,
            mode=mode,
            context_pack_block=context_pack_block if i == 0 else "",
            prev_step=prev,
        )
        rendered.append(rs)

    return WorkflowResult(
        name=name,
        description=description,
        target=target,
        steps=rendered,
    )


def save_workflow(result: WorkflowResult, output_dir: str) -> list[Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for rs in result.steps:
        safe_name = re.sub(r"[^\w\-]", "_", rs.step.name.lower())
        filename = f"step_{rs.step_number:02d}_{safe_name}.md"
        path = out / filename
        path.write_text(rs.prompt_text)
        paths.append(path)
    return paths
