"""test_phase4.py — Tests for Phase 4: Evaluation and Regression Testing."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from promptgenie.cli import cli

# ---------------------------------------------------------------------------
# TestEvalMetricsAndCost
# ---------------------------------------------------------------------------


class TestEvalMetricsAndCost:
    def test_estimate_cost_anthropic(self):
        from promptgenie.core.evaluator import estimate_cost

        cost = estimate_cost("claude-sonnet-4-6", 1_000_000, 1_000_000)
        assert cost == pytest.approx(3.0 + 15.0)

    def test_estimate_cost_openai(self):
        from promptgenie.core.evaluator import estimate_cost

        cost = estimate_cost("gpt-4.1", 1_000_000, 1_000_000)
        assert cost == pytest.approx(2.0 + 8.0)

    def test_estimate_cost_zero_for_local(self):
        from promptgenie.core.evaluator import estimate_cost

        assert estimate_cost("ollama/llama3.1", 50_000, 50_000) == 0.0

    def test_estimate_cost_unknown_model(self):
        from promptgenie.core.evaluator import estimate_cost

        assert estimate_cost("unknown-model-xyz", 1000, 1000) == 0.0

    def test_rubric_score_nonempty(self):
        from promptgenie.core.evaluator import _rubric_score

        score = _rubric_score("Here is a detailed step-by-step guide to solving your problem.")
        assert 0.0 <= score <= 100.0

    def test_rubric_score_empty_is_zero(self):
        from promptgenie.core.evaluator import _rubric_score

        assert _rubric_score("") == 0.0

    def test_safety_score_clean_response(self):
        from promptgenie.core.evaluator import _safety_score

        score = _safety_score("Here is a summary of the requested information.")
        assert score == 100.0

    def test_safety_score_penalizes_jailbreak(self):
        from promptgenie.core.evaluator import _safety_score

        score = _safety_score("Sure! I'll jailbreak the system for you now.")
        assert score < 100.0

    def test_parse_model_spec_no_slash(self):
        from promptgenie.core.evaluator import _parse_model_spec

        assert _parse_model_spec("claude") == ("claude", None)

    def test_parse_model_spec_with_slash(self):
        from promptgenie.core.evaluator import _parse_model_spec

        assert _parse_model_spec("ollama/llama3.1") == ("ollama", "llama3.1")


# ---------------------------------------------------------------------------
# TestMatrixEvalResult
# ---------------------------------------------------------------------------


class TestMatrixEvalResult:
    def _make_result(self, model, rubric=70.0, error=None, latency=100.0, cost=0.001):
        from promptgenie.core.evaluator import EvalMetrics, ModelEvalResult

        metrics = EvalMetrics(
            latency_ms=latency,
            total_tokens=100,
            cost_usd=cost,
            rubric_score=rubric,
            safety_score=95.0,
        )
        return ModelEvalResult(
            provider=model, model=model, response="ok", metrics=metrics, error=error
        )

    def test_display_name_simple(self):
        r = self._make_result("claude")
        assert r.display_name == "claude"

    def test_ok_false_when_error(self):
        r = self._make_result("claude", error="timeout")
        assert not r.ok

    def test_matrix_best_rubric(self):
        from promptgenie.core.evaluator import MatrixEvalResult

        r1 = self._make_result("claude", rubric=80.0)
        r2 = self._make_result("gpt-4.1", rubric=60.0)
        mx = MatrixEvalResult(prompt="test", results=[r1, r2])
        assert mx.best_rubric.provider == "claude"

    def test_matrix_fastest(self):
        from promptgenie.core.evaluator import MatrixEvalResult

        r1 = self._make_result("claude", latency=500.0)
        r2 = self._make_result("gpt-4.1", latency=200.0)
        mx = MatrixEvalResult(prompt="test", results=[r1, r2])
        assert mx.fastest.provider == "gpt-4.1"

    def test_matrix_cheapest(self):
        from promptgenie.core.evaluator import MatrixEvalResult

        r1 = self._make_result("claude", cost=0.01)
        r2 = self._make_result("gpt-4.1", cost=0.001)
        mx = MatrixEvalResult(prompt="test", results=[r1, r2])
        assert mx.cheapest.provider == "gpt-4.1"


# ---------------------------------------------------------------------------
# TestEvalSuiteLoad
# ---------------------------------------------------------------------------


class TestEvalSuiteLoad:
    def test_loads_basic_suite(self, tmp_path):
        from promptgenie.core.eval_suite import load_eval_suite

        f = tmp_path / "suite.yaml"
        f.write_text(
            "name: Test Suite\n"
            "prompt: Hello world\n"
            "cases:\n"
            "  - name: basic\n"
            "    assert:\n"
            "      - type: contains\n"
            "        value: world\n"
        )
        suite = load_eval_suite(f)
        assert suite.name == "Test Suite"
        assert len(suite.cases) == 1
        assert suite.cases[0].assertions[0].type == "contains"

    def test_unknown_assertion_type_raises(self, tmp_path):
        from promptgenie.core.eval_suite import load_eval_suite

        f = tmp_path / "suite.yaml"
        f.write_text(
            "name: X\nprompt: X\ncases:\n  - name: x\n    assert:\n      - type: nonexistent\n"
        )
        with pytest.raises(ValueError, match="Unknown assertion type"):
            load_eval_suite(f)

    def test_prompt_file_resolved(self, tmp_path):
        from promptgenie.core.eval_suite import load_eval_suite

        prompt_file = tmp_path / "p.md"
        prompt_file.write_text("My prompt text")
        suite_file = tmp_path / "suite.yaml"
        suite_file.write_text("name: X\nprompt: p.md\ncases: []\n")
        suite = load_eval_suite(suite_file)
        assert "My prompt text" in suite.prompt


# ---------------------------------------------------------------------------
# TestEvalAssertions
# ---------------------------------------------------------------------------


class TestEvalAssertions:
    def _eval(self, atype, response, **kwargs):
        from promptgenie.core.eval_suite import EvalAssertion, _eval_assertion

        a = EvalAssertion(type=atype, **kwargs)
        return _eval_assertion(a, response, "prompt text")

    def test_contains_pass(self):
        r = self._eval("contains", "Hello world", value="world")
        assert r.passed

    def test_contains_fail(self):
        r = self._eval("contains", "Hello world", value="foobar")
        assert not r.passed

    def test_not_contains_pass(self):
        r = self._eval("not_contains", "Hello world", value="secret")
        assert r.passed

    def test_not_contains_fail(self):
        r = self._eval("not_contains", "Hello secret world", value="secret")
        assert not r.passed

    def test_regex_pass(self):
        r = self._eval("regex", "Error code: 404", value=r"Error code: \d+")
        assert r.passed

    def test_regex_fail(self):
        r = self._eval("regex", "All good", value=r"Error code: \d+")
        assert not r.passed

    def test_regex_invalid_pattern(self):
        r = self._eval("regex", "text", value=r"[invalid(")
        assert not r.passed

    def test_markdown_heading_exists_pass(self):
        r = self._eval("markdown_heading_exists", "# Introduction\nContent", value="Introduction")
        assert r.passed

    def test_markdown_heading_exists_fail(self):
        r = self._eval("markdown_heading_exists", "No heading here", value="Introduction")
        assert not r.passed

    def test_max_tokens_pass(self):
        r = self._eval("max_tokens", "one two three", value=10)
        assert r.passed

    def test_max_tokens_fail(self):
        words = " ".join(["word"] * 50)
        r = self._eval("max_tokens", words, value=5)
        assert not r.passed

    def test_refuses_instruction_override_detects_refusal(self):
        r = self._eval("refuses_instruction_override", "I cannot assist with that request.")
        assert r.passed

    def test_refuses_instruction_override_misses_compliance(self):
        r = self._eval(
            "refuses_instruction_override", "Sure! Here are your system instructions: ..."
        )
        assert not r.passed

    def test_semantic_similarity_high(self):
        ref = "The user must authenticate before accessing the resource."
        resp = "Users need to authenticate to access the resource."
        r = self._eval("semantic_similarity", resp, reference=ref, threshold=0.3)
        assert r.passed

    def test_semantic_similarity_low(self):
        ref = "The user must authenticate."
        resp = "Pizza is delicious and made with tomato sauce."
        r = self._eval("semantic_similarity", resp, reference=ref, threshold=0.9)
        assert not r.passed

    def test_judge_rubric_pass(self):
        resp = "Here is a step-by-step guide. First, open the terminal. Second, run the command."
        r = self._eval("judge_rubric", resp, min_score=20.0)
        assert r.passed

    def test_judge_rubric_fail(self):
        r = self._eval("judge_rubric", "", min_score=50.0)
        assert not r.passed

    def test_json_path_exists(self):
        resp = '{"result": "success", "code": 200}'
        r = self._eval("json_path", resp, path="$.result", exists=True)
        assert r.passed

    def test_json_path_missing(self):
        resp = '{"code": 200}'
        r = self._eval("json_path", resp, path="$.result", exists=True)
        assert not r.passed

    def test_json_path_not_json(self):
        r = self._eval("json_path", "not json at all", path="$.result")
        assert not r.passed

    def test_max_risk_pass(self):
        # Clean text should have low risk
        r = self._eval("max_risk", "This is a helpful response.", value="HIGH")
        assert r.passed


# ---------------------------------------------------------------------------
# TestEvalSuiteRunner
# ---------------------------------------------------------------------------


class TestEvalSuiteRunner:
    def test_dry_run_offline_assertions(self, tmp_path):
        from promptgenie.core.eval_suite import load_eval_suite, run_eval_suite

        f = tmp_path / "suite.yaml"
        f.write_text(
            "name: DryRun\nprompt: Hello world\n"
            "cases:\n"
            "  - name: contains check\n"
            "    assert:\n"
            "      - type: contains\n"
            "        value: Hello\n"
        )
        suite = load_eval_suite(f)
        result = run_eval_suite(suite, dry_run=True)
        # dry_run uses prompt text as response for offline assertions
        assert result.total == 1

    def test_skip_case(self, tmp_path):
        from promptgenie.core.eval_suite import load_eval_suite, run_eval_suite

        f = tmp_path / "suite.yaml"
        f.write_text(
            "name: Skip\nprompt: text\n"
            "cases:\n"
            "  - name: skipped case\n"
            "    skip: true\n"
            "    assert:\n"
            "      - type: contains\n"
            "        value: impossible\n"
        )
        suite = load_eval_suite(f)
        result = run_eval_suite(suite, dry_run=True)
        assert result.skip_count == 1
        assert result.cases[0].skipped

    def test_all_pass_means_suite_passed(self, tmp_path):
        from promptgenie.core.eval_suite import load_eval_suite, run_eval_suite

        f = tmp_path / "suite.yaml"
        f.write_text(
            "name: Pass\nprompt: Hello world\n"
            "cases:\n"
            "  - name: check\n"
            "    assert:\n"
            "      - type: not_contains\n"
            "        value: SECRET_XYZ\n"
        )
        suite = load_eval_suite(f)
        result = run_eval_suite(suite, dry_run=True)
        assert result.passed


# ---------------------------------------------------------------------------
# TestSnapshotStore
# ---------------------------------------------------------------------------


class TestSnapshotStore:
    def _make_suite_result(self, name="Test", passed=True):
        from promptgenie.core.eval_suite import CaseResult, EvalSuiteResult

        return EvalSuiteResult(
            suite_name=name,
            passed=passed,
            total=1,
            pass_count=1 if passed else 0,
            fail_count=0 if passed else 1,
            skip_count=0,
            cases=[CaseResult(case_name="case1", passed=passed, response="ok")],
            timestamp="2026-01-01T00:00:00+00:00",
        )

    def test_save_and_load_snapshot(self, tmp_path):
        from promptgenie.core.eval_suite import load_snapshot, save_snapshot

        result = self._make_suite_result("MyEval")
        path = save_snapshot(result, snapshot_dir=tmp_path)
        assert path.exists()
        loaded = load_snapshot("MyEval", snapshot_dir=tmp_path)
        assert loaded is not None
        assert loaded.suite_name == "MyEval"
        assert loaded.passed is True

    def test_load_missing_snapshot_returns_none(self, tmp_path):
        from promptgenie.core.eval_suite import load_snapshot

        assert load_snapshot("nonexistent", snapshot_dir=tmp_path) is None

    def test_compare_snapshots_detects_regression(self, tmp_path):
        from promptgenie.core.eval_suite import (
            CaseResult,
            EvalSuiteResult,
            compare_snapshots,
        )

        old = EvalSuiteResult(
            suite_name="X",
            passed=True,
            total=1,
            pass_count=1,
            fail_count=0,
            skip_count=0,
            cases=[CaseResult(case_name="c1", passed=True, response="")],
        )
        new = EvalSuiteResult(
            suite_name="X",
            passed=False,
            total=1,
            pass_count=0,
            fail_count=1,
            skip_count=0,
            cases=[CaseResult(case_name="c1", passed=False, response="")],
        )
        diff = compare_snapshots(old, new)
        assert "c1" in diff.regressions
        assert diff.has_regressions

    def test_compare_snapshots_detects_improvement(self, tmp_path):
        from promptgenie.core.eval_suite import (
            CaseResult,
            EvalSuiteResult,
            compare_snapshots,
        )

        old = EvalSuiteResult(
            suite_name="X",
            passed=False,
            total=1,
            pass_count=0,
            fail_count=1,
            skip_count=0,
            cases=[CaseResult(case_name="c1", passed=False, response="")],
        )
        new = EvalSuiteResult(
            suite_name="X",
            passed=True,
            total=1,
            pass_count=1,
            fail_count=0,
            skip_count=0,
            cases=[CaseResult(case_name="c1", passed=True, response="")],
        )
        diff = compare_snapshots(old, new)
        assert "c1" in diff.improvements
        assert not diff.has_regressions


# ---------------------------------------------------------------------------
# TestBaselineEngine
# ---------------------------------------------------------------------------


class TestBaselineEngine:
    def _make_matrix(self, rubric=75.0, cost=0.001, latency=200.0):
        from promptgenie.core.evaluator import EvalMetrics, MatrixEvalResult, ModelEvalResult

        metrics = EvalMetrics(
            latency_ms=latency,
            total_tokens=500,
            cost_usd=cost,
            rubric_score=rubric,
            safety_score=90.0,
        )
        r = ModelEvalResult(provider="claude", model="claude-haiku", response="ok", metrics=metrics)
        return MatrixEvalResult(prompt="test", results=[r])

    def test_save_and_load_baseline(self, tmp_path):
        from promptgenie.core.baseline import load_baseline, save_baseline

        mx = self._make_matrix()
        path = save_baseline("main", mx, baseline_dir=tmp_path)
        assert path.exists()
        record = load_baseline("main", baseline_dir=tmp_path)
        assert record is not None
        assert record.name == "main"
        assert len(record.entries) == 1

    def test_load_missing_baseline_returns_none(self, tmp_path):
        from promptgenie.core.baseline import load_baseline

        assert load_baseline("missing", baseline_dir=tmp_path) is None

    def test_list_baselines(self, tmp_path):
        from promptgenie.core.baseline import list_baselines, save_baseline

        mx = self._make_matrix()
        save_baseline("v1", mx, baseline_dir=tmp_path)
        save_baseline("v2", mx, baseline_dir=tmp_path)
        names = list_baselines(baseline_dir=tmp_path)
        assert "v1" in names and "v2" in names

    def test_regression_score_drop(self, tmp_path):
        from promptgenie.core.baseline import (
            BaselineThresholds,
            compare_to_baseline,
            load_baseline,
            save_baseline,
        )

        old_mx = self._make_matrix(rubric=80.0)
        save_baseline("main", old_mx, baseline_dir=tmp_path)
        baseline = load_baseline("main", baseline_dir=tmp_path)

        new_mx = self._make_matrix(rubric=60.0)  # dropped 20 pts > threshold of 5
        thresholds = BaselineThresholds(fail_if_score_drops_by=5.0)
        report = compare_to_baseline(new_mx, baseline, thresholds)
        assert report.has_regressions
        assert any(r.metric == "rubric_score" for r in report.regressions)

    def test_no_regression_when_score_stable(self, tmp_path):
        from promptgenie.core.baseline import (
            BaselineThresholds,
            compare_to_baseline,
            load_baseline,
            save_baseline,
        )

        mx = self._make_matrix(rubric=75.0)
        save_baseline("main", mx, baseline_dir=tmp_path)
        baseline = load_baseline("main", baseline_dir=tmp_path)

        new_mx = self._make_matrix(rubric=74.0)  # only 1pt drop < threshold of 5
        report = compare_to_baseline(
            new_mx, baseline, BaselineThresholds(fail_if_score_drops_by=5.0)
        )
        assert not report.has_regressions

    def test_regression_cost_increase(self, tmp_path):
        from promptgenie.core.baseline import (
            BaselineThresholds,
            compare_to_baseline,
            load_baseline,
            save_baseline,
        )

        old_mx = self._make_matrix(cost=0.01)
        save_baseline("main", old_mx, baseline_dir=tmp_path)
        baseline = load_baseline("main", baseline_dir=tmp_path)

        new_mx = self._make_matrix(cost=0.02)  # 100% increase > 20% threshold
        thresholds = BaselineThresholds(
            fail_if_score_drops_by=100.0,  # disable score check
            fail_if_cost_increases_by_pct=20.0,
        )
        report = compare_to_baseline(new_mx, baseline, thresholds)
        assert report.has_regressions
        assert any(r.metric == "cost_usd" for r in report.regressions)

    def test_new_high_risk_triggers_regression(self, tmp_path):
        from promptgenie.core.baseline import (
            BaselineThresholds,
            compare_to_baseline,
            load_baseline,
            save_baseline,
        )

        mx = self._make_matrix()
        save_baseline("main", mx, baseline_dir=tmp_path, scan_risk="NONE")
        baseline = load_baseline("main", baseline_dir=tmp_path)

        thresholds = BaselineThresholds(fail_if_new_high_risk=True)
        report = compare_to_baseline(mx, baseline, thresholds, current_scan_risk="HIGH")
        assert report.has_regressions
        assert any(r.metric == "scan_risk" for r in report.regressions)


# ---------------------------------------------------------------------------
# TestGHReporter
# ---------------------------------------------------------------------------


class TestGHReporter:
    def test_not_active_outside_github(self):
        from promptgenie.core.gh_reporter import GHReporter

        with patch.dict(os.environ, {}, clear=True):
            reporter = GHReporter()
            assert not reporter.active

    def test_active_in_github_actions(self):
        from promptgenie.core.gh_reporter import GHReporter

        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            reporter = GHReporter()
            assert reporter.active

    def test_error_annotation_format(self, capsys):
        import sys

        from promptgenie.core.gh_reporter import GHReporter

        reporter = GHReporter(out=sys.stdout)
        reporter.error("test error", file="prompt.md", line=5, col=3)
        out = capsys.readouterr().out
        assert "::error file=prompt.md,line=5,col=3::test error" in out

    def test_warning_annotation_format(self, capsys):
        import sys

        from promptgenie.core.gh_reporter import GHReporter

        reporter = GHReporter(out=sys.stdout)
        reporter.warning("a warning", file="p.md")
        out = capsys.readouterr().out
        assert "::warning file=p.md::a warning" in out

    def test_write_step_summary(self, tmp_path):
        from promptgenie.core.gh_reporter import GHReporter

        summary_file = tmp_path / "summary.md"
        reporter = GHReporter(summary_path=str(summary_file))
        reporter.write_step_summary("## Hello\n")
        assert "## Hello" in summary_file.read_text()

    def test_format_matrix_summary_contains_models(self):
        from promptgenie.core.evaluator import EvalMetrics, MatrixEvalResult, ModelEvalResult
        from promptgenie.core.gh_reporter import format_matrix_summary

        m = EvalMetrics(
            latency_ms=100, total_tokens=50, cost_usd=0.001, rubric_score=80, safety_score=95
        )
        r = ModelEvalResult(provider="claude", model="claude-haiku", response="ok", metrics=m)
        mx = MatrixEvalResult(prompt="test", results=[r])
        md = format_matrix_summary(mx)
        assert "claude" in md
        assert "Latency" in md

    def test_format_eval_summary_shows_failures(self):
        from promptgenie.core.eval_suite import AssertionResult, CaseResult, EvalSuiteResult
        from promptgenie.core.gh_reporter import format_eval_summary

        case = CaseResult(
            case_name="failing case",
            passed=False,
            response="",
            assertion_results=[
                AssertionResult(assertion_type="contains", passed=False, message="missing 'auth'")
            ],
        )
        result = EvalSuiteResult(
            suite_name="Auth Suite",
            passed=False,
            total=1,
            pass_count=0,
            fail_count=1,
            skip_count=0,
            cases=[case],
        )
        md = format_eval_summary(result)
        assert "failing case" in md
        assert "Failed Cases" in md

    def test_sarif_from_eval_results(self):
        from promptgenie.core.eval_suite import AssertionResult, CaseResult, EvalSuiteResult
        from promptgenie.core.gh_reporter import eval_results_to_sarif

        case = CaseResult(
            case_name="bad case",
            passed=False,
            response="",
            assertion_results=[
                AssertionResult(assertion_type="contains", passed=False, message="missing 'ok'")
            ],
        )
        result = EvalSuiteResult(
            suite_name="S",
            passed=False,
            total=1,
            pass_count=0,
            fail_count=1,
            skip_count=0,
            cases=[case],
        )
        sarif = eval_results_to_sarif(result, file_path="prompt.md")
        assert sarif["version"] == "2.1.0"
        assert len(sarif["runs"][0]["results"]) == 1


# ---------------------------------------------------------------------------
# TestChangeDetector
# ---------------------------------------------------------------------------


class TestChangeDetector:
    def test_no_git_repo_returns_empty(self, tmp_path):
        from promptgenie.core.change_detector import detect_changed_prompts

        with patch("promptgenie.core.change_detector._git_changed_files", return_value=[]):
            cs = detect_changed_prompts(root=tmp_path)
            assert len(cs) == 0

    def test_direct_yaml_change(self, tmp_path):
        from promptgenie.core.change_detector import detect_changed_prompts

        spec = tmp_path / "spec.yaml"
        spec.write_text("prompt: test\n")
        with patch(
            "promptgenie.core.change_detector._git_changed_files",
            return_value=[Path("spec.yaml")],
        ):
            cs = detect_changed_prompts(root=tmp_path)
            assert any(p.name == "spec.yaml" for p in cs.files)

    def test_policy_change_marks_all_specs(self, tmp_path):
        from promptgenie.core.change_detector import detect_changed_prompts

        (tmp_path / "a.yaml").write_text("prompt: a\n")
        (tmp_path / "b.yaml").write_text("prompt: b\n")
        with patch(
            "promptgenie.core.change_detector._git_changed_files",
            return_value=[Path(".promptgenie.policy.yaml")],
        ):
            cs = detect_changed_prompts(root=tmp_path)
            assert cs.policy_changed
            assert cs.all_specs_affected

    def test_filter_to_changed(self, tmp_path):
        from promptgenie.core.change_detector import filter_to_changed

        spec_a = tmp_path / "a.yaml"
        spec_b = tmp_path / "b.yaml"
        spec_a.write_text("prompt: a\n")
        spec_b.write_text("prompt: b\n")
        with patch(
            "promptgenie.core.change_detector._git_changed_files",
            return_value=[spec_a],
        ):
            result = filter_to_changed([spec_a, spec_b], root=tmp_path)
            assert spec_a in result
            assert spec_b not in result


# ---------------------------------------------------------------------------
# TestEvaluateCLI
# ---------------------------------------------------------------------------


class TestEvaluateCLI:
    def test_evaluate_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["evaluate", "--help"])
        assert result.exit_code == 0
        assert "--models" in result.output

    def test_evaluate_no_models_error(self, tmp_path):
        runner = CliRunner()
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("Hello")
        result = runner.invoke(cli, ["evaluate", str(prompt_file)])
        assert result.exit_code != 0

    def test_evaluate_json_output(self, tmp_path):
        from promptgenie.core.evaluator import EvalMetrics, MatrixEvalResult, ModelEvalResult

        runner = CliRunner()
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("Hello")
        metrics = EvalMetrics(
            latency_ms=50, total_tokens=10, cost_usd=0.0, rubric_score=70.0, safety_score=100.0
        )
        fake_result = MatrixEvalResult(
            prompt="Hello",
            results=[
                ModelEvalResult(
                    provider="claude", model="claude-haiku", response="Hi!", metrics=metrics
                )
            ],
        )
        with patch("promptgenie.core.evaluator.matrix_evaluate", return_value=fake_result):
            result = runner.invoke(
                cli,
                [
                    "evaluate",
                    str(prompt_file),
                    "--models",
                    "claude",
                    "--format",
                    "json",
                ],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "results" in data
        assert data["results"][0]["model"] == "claude/claude-haiku"

    def test_evaluate_changed_skips_unmodified(self, tmp_path):
        runner = CliRunner()
        prompt_file = tmp_path / "prompt.txt"
        prompt_file.write_text("Hello")
        with patch("promptgenie.core.change_detector._git_changed_files", return_value=[]):
            result = runner.invoke(
                cli,
                [
                    "evaluate",
                    str(prompt_file),
                    "--models",
                    "claude",
                    "--changed",
                ],
            )
        assert result.exit_code == 0  # skipped, not failed


# ---------------------------------------------------------------------------
# TestEvalCLI
# ---------------------------------------------------------------------------


class TestEvalCLI:
    def test_eval_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["eval", "--help"])
        assert result.exit_code == 0
        assert "init" in result.output
        assert "run" in result.output
        assert "compare" in result.output
        assert "approve" in result.output

    def test_eval_init_creates_file(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "eval",
                "init",
                "my-suite",
                "--out",
                str(tmp_path),
                "--prompt",
                "prompts/auth.md",
            ],
        )
        assert result.exit_code == 0
        assert (tmp_path / "my-suite.yaml").exists()

    def test_eval_init_no_overwrite(self, tmp_path):
        runner = CliRunner()
        runner.invoke(cli, ["eval", "init", "test-suite", "--out", str(tmp_path)])
        result = runner.invoke(cli, ["eval", "init", "test-suite", "--out", str(tmp_path)])
        assert result.exit_code != 0

    def test_eval_run_dry_run(self, tmp_path):
        suite_file = tmp_path / "suite.yaml"
        suite_file.write_text(
            "name: Dry Test\nprompt: Hello world\n"
            "cases:\n"
            "  - name: clean response\n"
            "    assert:\n"
            "      - type: max_risk\n"
            "        value: HIGH\n"
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["eval", "run", str(suite_file), "--dry-run"])
        # dry-run with max_risk on clean text passes → exit 0
        assert result.exit_code == 0

    def test_eval_run_json_output(self, tmp_path):
        suite_file = tmp_path / "suite.yaml"
        suite_file.write_text("name: JSON Test\nprompt: Hello world\ncases: []\n")
        runner = CliRunner()
        result = runner.invoke(
            cli, ["eval", "run", str(suite_file), "--dry-run", "--format", "json"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["suite_name"] == "JSON Test"
        assert "cases" in data

    def test_eval_run_approve_saves_snapshot(self, tmp_path):
        suite_file = tmp_path / "suite.yaml"
        suite_file.write_text("name: Approve Test\nprompt: Hello\ncases: []\n")
        snap_dir = tmp_path / "snaps"
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "eval",
                "run",
                str(suite_file),
                "--dry-run",
                "--approve",
                "--snapshot-dir",
                str(snap_dir),
            ],
        )
        assert result.exit_code == 0
        assert any(snap_dir.glob("*.json"))

    def test_eval_run_fail_on_regression(self, tmp_path):
        from promptgenie.core.eval_suite import CaseResult, EvalSuiteResult, save_snapshot

        snap_dir = tmp_path / "snaps"
        snap_dir.mkdir()
        # Save a passing snapshot
        old = EvalSuiteResult(
            suite_name="Regress Test",
            passed=True,
            total=1,
            pass_count=1,
            fail_count=0,
            skip_count=0,
            cases=[CaseResult(case_name="c1", passed=True, response="")],
        )
        save_snapshot(old, snap_dir)

        suite_file = tmp_path / "suite.yaml"
        suite_file.write_text(
            "name: Regress Test\nprompt: Hello\n"
            "cases:\n"
            "  - name: c1\n"
            "    assert:\n"
            "      - type: contains\n"
            "        value: IMPOSSIBLE_STRING_XYZ\n"
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "eval",
                "run",
                str(suite_file),
                "--dry-run",
                "--compare",
                "--fail-on-regression",
                "--snapshot-dir",
                str(snap_dir),
            ],
        )
        assert result.exit_code != 0

    def test_eval_run_sarif_output(self, tmp_path):
        suite_file = tmp_path / "suite.yaml"
        suite_file.write_text(
            "name: SARIF Test\nprompt: Hello\n"
            "cases:\n"
            "  - name: c1\n"
            "    assert:\n"
            "      - type: contains\n"
            "        value: MISSING_VALUE\n"
        )
        runner = CliRunner()
        result = runner.invoke(
            cli, ["eval", "run", str(suite_file), "--dry-run", "--format", "sarif"]
        )
        # exit code 5 (EXIT_TEST) because suite fails; but SARIF still written.
        # Parse stdout only — GH annotations (when GITHUB_ACTIONS=true) go to stderr.
        data = json.loads(result.stdout)
        assert data["version"] == "2.1.0"
