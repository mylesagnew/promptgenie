"""Extended tests for core/workflow.py — render, generate, save (Wave 5 coverage)."""

import tempfile
from pathlib import Path

import pytest
import yaml

from promptgenie.core.workflow import (
    WorkflowResult,
    WorkflowValidationError,
    generate_workflow,
    save_workflow,
)


def _write_workflow(data: dict) -> Path:
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "test.workflow.yaml"
    path.write_text(yaml.dump(data))
    return path


SIMPLE_WORKFLOW = {
    "name": "test-workflow",
    "description": "A simple test workflow",
    "target": "claude-code",
    "mode": "standard",
    "steps": [
        {
            "id": "inspect",
            "name": "Inspect",
            "objective": "Map the current architecture",
            "output": "Architecture summary",
        },
        {
            "id": "implement",
            "name": "Implement",
            "objective": "Build the feature",
            "depends_on": "inspect",
            "output": "Diff of changes",
            "requires_approval": False,
        },
        {
            "id": "review",
            "name": "Review",
            "objective": "Security review",
            "depends_on": "implement",
            "requires_approval": True,
            "output": "Findings table",
        },
    ],
}


class TestGenerateWorkflow:
    def test_returns_workflow_result(self):
        path = _write_workflow(SIMPLE_WORKFLOW)
        result = generate_workflow(str(path))
        assert isinstance(result, WorkflowResult)

    def test_step_count_matches(self):
        path = _write_workflow(SIMPLE_WORKFLOW)
        result = generate_workflow(str(path))
        assert len(result.steps) == 3

    def test_step_ordering_respects_depends_on(self):
        path = _write_workflow(SIMPLE_WORKFLOW)
        result = generate_workflow(str(path))
        ids = [rs.step.id for rs in result.steps]
        assert ids.index("inspect") < ids.index("implement")
        assert ids.index("implement") < ids.index("review")

    def test_approval_gates_detected(self):
        path = _write_workflow(SIMPLE_WORKFLOW)
        result = generate_workflow(str(path))
        gates = result.approval_gates
        assert len(gates) == 1
        assert gates[0].step.id == "review"

    def test_total_tokens_nonzero(self):
        path = _write_workflow(SIMPLE_WORKFLOW)
        result = generate_workflow(str(path))
        assert result.total_tokens > 0

    def test_step_prompt_contains_objective(self):
        path = _write_workflow(SIMPLE_WORKFLOW)
        result = generate_workflow(str(path))
        first_step = result.steps[0]
        assert "Map the current architecture" in first_step.prompt_text

    def test_handoff_section_present_in_later_steps(self):
        path = _write_workflow(SIMPLE_WORKFLOW)
        result = generate_workflow(str(path))
        second_step = result.steps[1]
        assert "Handoff" in second_step.prompt_text

    def test_approval_gate_text_in_prompt(self):
        path = _write_workflow(SIMPLE_WORKFLOW)
        result = generate_workflow(str(path))
        review_step = result.steps[2]
        assert "Approval Gate" in review_step.prompt_text

    def test_scope_section_rendered(self):
        wf = dict(SIMPLE_WORKFLOW)
        wf["steps"] = [
            {
                "id": "step1",
                "name": "Scoped Step",
                "objective": "Do only this",
                "scope": ["src/auth/"],
                "output": "Done",
            }
        ]
        path = _write_workflow(wf)
        result = generate_workflow(str(path))
        assert "src/auth/" in result.steps[0].prompt_text

    def test_forbidden_actions_rendered(self):
        wf = dict(SIMPLE_WORKFLOW)
        wf["steps"] = [
            {
                "id": "step1",
                "name": "Restricted Step",
                "objective": "Be careful",
                "forbidden": ["Do not touch migrations"],
                "output": "Done",
            }
        ]
        path = _write_workflow(wf)
        result = generate_workflow(str(path))
        assert "Do not touch migrations" in result.steps[0].prompt_text

    def test_unknown_target_raises_by_default(self):
        """Fail-closed: unknown target is a FileNotFoundError, not silent fallback."""
        import pytest

        wf = dict(SIMPLE_WORKFLOW)
        wf["target"] = "totally-unknown-model-xyz"
        wf["steps"] = [{"id": "s1", "name": "Step", "objective": "Do it", "output": "Done"}]
        path = _write_workflow(wf)
        with pytest.raises(FileNotFoundError, match="totally-unknown-model-xyz"):
            generate_workflow(str(path))

    def test_unknown_target_falls_back_with_best_effort(self):
        """--best-effort: unknown target produces output using built-in defaults."""
        wf = dict(SIMPLE_WORKFLOW)
        wf["target"] = "totally-unknown-model-xyz"
        wf["steps"] = [{"id": "s1", "name": "Step", "objective": "Do it", "output": "Done"}]
        path = _write_workflow(wf)
        result = generate_workflow(str(path), best_effort=True)
        assert result.steps

    def test_cycle_raises_validation_error(self):
        wf = {
            "name": "cyclic",
            "target": "claude-code",
            "steps": [
                {"id": "a", "name": "A", "objective": "Do A", "depends_on": "b"},
                {"id": "b", "name": "B", "objective": "Do B", "depends_on": "a"},
            ],
        }
        path = _write_workflow(wf)
        with pytest.raises(WorkflowValidationError):
            generate_workflow(str(path))

    def test_minimal_mode_workflow(self):
        wf = dict(SIMPLE_WORKFLOW)
        wf["mode"] = "minimal"
        path = _write_workflow(wf)
        result = generate_workflow(str(path))
        assert result.steps


class TestSaveWorkflow:
    def test_saves_one_file_per_step(self):
        path = _write_workflow(SIMPLE_WORKFLOW)
        result = generate_workflow(str(path))
        with tempfile.TemporaryDirectory() as out_dir:
            saved = save_workflow(result, out_dir)
            assert len(saved) == 3
            for p in saved:
                assert p.exists()
                assert p.stat().st_size > 0

    def test_filenames_include_step_number(self):
        path = _write_workflow(SIMPLE_WORKFLOW)
        result = generate_workflow(str(path))
        with tempfile.TemporaryDirectory() as out_dir:
            saved = save_workflow(result, out_dir)
            names = [p.name for p in saved]
            assert any("01" in n for n in names)
            assert any("02" in n for n in names)

    def test_file_content_matches_prompt(self):
        path = _write_workflow(SIMPLE_WORKFLOW)
        result = generate_workflow(str(path))
        with tempfile.TemporaryDirectory() as out_dir:
            saved = save_workflow(result, out_dir)
            content = saved[0].read_text()
            assert result.steps[0].prompt_text == content
