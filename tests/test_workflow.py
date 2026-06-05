"""Tests for workflow validation and cycle detection (Wave 2.2)."""

import pytest

from promptgenie.core.workflow import WorkflowStep, WorkflowValidationError, validate_workflow


def _step(id, name="Step", objective="Do something", depends_on=None):
    return WorkflowStep(id=id, name=name, objective=objective, depends_on=depends_on)


class TestValidWorkflow:
    def test_linear_chain_passes(self):
        steps = [
            _step("a"),
            _step("b", depends_on="a"),
            _step("c", depends_on="b"),
        ]
        validate_workflow(steps)  # must not raise

    def test_single_step_passes(self):
        validate_workflow([_step("only")])

    def test_parallel_steps_pass(self):
        validate_workflow([_step("a"), _step("b"), _step("c")])

    def test_diamond_dag_passes(self):
        steps = [
            _step("root"),
            _step("left", depends_on="root"),
            _step("right", depends_on="root"),
            _step("merge", depends_on="left"),
        ]
        validate_workflow(steps)


class TestDuplicateIds:
    def test_duplicate_id_rejected(self):
        steps = [_step("a"), _step("a")]
        with pytest.raises(WorkflowValidationError, match="Duplicate step ID"):
            validate_workflow(steps)


class TestUnknownDependency:
    def test_unknown_depends_on_rejected(self):
        steps = [_step("a", depends_on="nonexistent")]
        with pytest.raises(WorkflowValidationError, match="unknown step"):
            validate_workflow(steps)


class TestCycleDetection:
    def test_self_reference_rejected(self):
        steps = [_step("a", depends_on="a")]
        with pytest.raises(WorkflowValidationError, match="cycle"):
            validate_workflow(steps)

    def test_two_step_cycle_rejected(self):
        steps = [_step("a", depends_on="b"), _step("b", depends_on="a")]
        with pytest.raises(WorkflowValidationError, match="cycle"):
            validate_workflow(steps)

    def test_three_step_cycle_rejected(self):
        steps = [
            _step("a", depends_on="c"),
            _step("b", depends_on="a"),
            _step("c", depends_on="b"),
        ]
        with pytest.raises(WorkflowValidationError, match="cycle"):
            validate_workflow(steps)


class TestRequiredFields:
    def test_empty_id_rejected(self):
        steps = [WorkflowStep(id="", name="Step", objective="Do it")]
        with pytest.raises(WorkflowValidationError, match="'id'"):
            validate_workflow(steps)

    def test_empty_name_rejected(self):
        steps = [WorkflowStep(id="a", name="", objective="Do it")]
        with pytest.raises(WorkflowValidationError, match="'name'"):
            validate_workflow(steps)

    def test_empty_objective_rejected(self):
        steps = [WorkflowStep(id="a", name="Step", objective="")]
        with pytest.raises(WorkflowValidationError, match="'objective'"):
            validate_workflow(steps)

    def test_whitespace_only_id_rejected(self):
        steps = [WorkflowStep(id="   ", name="Step", objective="Do it")]
        with pytest.raises(WorkflowValidationError, match="'id'"):
            validate_workflow(steps)
