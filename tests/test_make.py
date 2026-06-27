"""Tests for the ``promptgenie make`` task-graph runner (core engine + command)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from promptgenie.cli import cli
from promptgenie.core.make import (
    MakefileError,
    compute_dirty,
    load_makefile,
    resolve_targets,
    run_makefile,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeRunner:
    """Records commands and returns a configured exit code per command."""

    def __init__(self, exits: dict[str, int] | None = None):
        self.exits = exits or {}
        self.calls: list[str] = []

    def __call__(self, command: str) -> tuple[int, str]:
        self.calls.append(command)
        return self.exits.get(command, 0), f"ran: {command}\n"


def _write(tmp_path: Path, body: str) -> Path:
    f = tmp_path / "promptgenie.make.yaml"
    f.write_text(body, encoding="utf-8")
    return f


MAKEFILE = """
tasks:
  lint:
    run: echo lint
    inputs: ["prompts/**/*.md"]
    desc: Lint prompts
  scan:
    run: ["echo scan-a", "echo scan-b"]
    inputs: ["prompts/**/*.md"]
  ci:
    needs: [lint, scan]
"""


# ---------------------------------------------------------------------------
# Loading & validation
# ---------------------------------------------------------------------------


class TestLoad:
    def test_load_valid(self, tmp_path: Path):
        mf = load_makefile(_write(tmp_path, MAKEFILE))
        assert set(mf.tasks) == {"lint", "scan", "ci"}
        assert mf.tasks["lint"].run == ["echo lint"]
        assert mf.tasks["scan"].run == ["echo scan-a", "echo scan-b"]
        assert mf.tasks["ci"].needs == ["lint", "scan"]
        assert mf.tasks["lint"].description == "Lint prompts"

    def test_missing_file(self, tmp_path: Path):
        with pytest.raises(MakefileError, match="not found"):
            load_makefile(tmp_path / "nope.yaml")

    def test_missing_tasks_key(self, tmp_path: Path):
        with pytest.raises(MakefileError, match="tasks"):
            load_makefile(_write(tmp_path, "other: 1\n"))

    def test_task_body_must_be_mapping(self, tmp_path: Path):
        with pytest.raises(MakefileError, match="must be a mapping"):
            load_makefile(_write(tmp_path, "tasks:\n  a: 5\n"))

    def test_null_task_body_is_noop(self, tmp_path: Path):
        mf = load_makefile(_write(tmp_path, "tasks:\n  noop:\n"))
        assert mf.tasks["noop"].run == []

    def test_unknown_dependency(self, tmp_path: Path):
        body = "tasks:\n  a:\n    needs: [ghost]\n"
        with pytest.raises(MakefileError, match="unknown task 'ghost'"):
            load_makefile(_write(tmp_path, body))

    def test_cycle_detected(self, tmp_path: Path):
        body = "tasks:\n  a:\n    needs: [b]\n  b:\n    needs: [a]\n"
        with pytest.raises(MakefileError, match="cycle"):
            load_makefile(_write(tmp_path, body))


# ---------------------------------------------------------------------------
# Target resolution & ordering
# ---------------------------------------------------------------------------


class TestResolve:
    def test_closure_and_topo_order(self, tmp_path: Path):
        mf = load_makefile(_write(tmp_path, MAKEFILE))
        order = resolve_targets(mf, ["ci"])
        assert order[-1] == "ci"
        assert order.index("lint") < order.index("ci")
        assert order.index("scan") < order.index("ci")

    def test_no_targets_runs_all(self, tmp_path: Path):
        mf = load_makefile(_write(tmp_path, MAKEFILE))
        order = resolve_targets(mf, [])
        assert set(order) == {"lint", "scan", "ci"}

    def test_unknown_target(self, tmp_path: Path):
        mf = load_makefile(_write(tmp_path, MAKEFILE))
        with pytest.raises(MakefileError, match="Unknown target"):
            resolve_targets(mf, ["ghost"])

    def test_partial_closure_excludes_unrequested(self, tmp_path: Path):
        mf = load_makefile(_write(tmp_path, MAKEFILE))
        order = resolve_targets(mf, ["lint"])
        assert order == ["lint"]


# ---------------------------------------------------------------------------
# Changed-file filtering
# ---------------------------------------------------------------------------


class TestDirty:
    def test_input_glob_matches(self, tmp_path: Path):
        mf = load_makefile(_write(tmp_path, MAKEFILE))
        order = resolve_targets(mf, ["ci"])
        dirty = compute_dirty(mf, order, ["prompts/auth/login.md"])
        assert dirty["lint"] is True
        assert dirty["scan"] is True
        assert dirty["ci"] is True  # aggregator inherits

    def test_no_match_skips(self, tmp_path: Path):
        mf = load_makefile(_write(tmp_path, MAKEFILE))
        order = resolve_targets(mf, ["ci"])
        dirty = compute_dirty(mf, order, ["src/app.py"])
        assert dirty["lint"] is False
        assert dirty["ci"] is False

    def test_aggregator_dirty_if_any_dep_dirty(self, tmp_path: Path):
        body = (
            "tasks:\n"
            "  a:\n    run: echo a\n    inputs: ['a/**']\n"
            "  b:\n    run: echo b\n    inputs: ['b/**']\n"
            "  all:\n    needs: [a, b]\n"
        )
        mf = load_makefile(_write(tmp_path, body))
        order = resolve_targets(mf, ["all"])
        dirty = compute_dirty(mf, order, ["b/x.md"])
        assert dirty["a"] is False
        assert dirty["b"] is True
        assert dirty["all"] is True

    def test_no_inputs_no_needs_always_dirty(self, tmp_path: Path):
        mf = load_makefile(_write(tmp_path, "tasks:\n  clean:\n    run: echo clean\n"))
        dirty = compute_dirty(mf, ["clean"], [])
        assert dirty["clean"] is True

    def test_double_star_matches_nested(self, tmp_path: Path):
        body = "tasks:\n  t:\n    run: echo t\n    inputs: ['prompts/**/*.md']\n"
        mf = load_makefile(_write(tmp_path, body))
        assert compute_dirty(mf, ["t"], ["prompts/a.md"])["t"] is True
        assert compute_dirty(mf, ["t"], ["prompts/x/y/z.md"])["t"] is True
        assert compute_dirty(mf, ["t"], ["other/a.md"])["t"] is False


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


class TestRun:
    def test_runs_in_dependency_order(self, tmp_path: Path):
        mf = load_makefile(_write(tmp_path, MAKEFILE))
        runner = FakeRunner()
        run = run_makefile(mf, ["ci"], runner=runner)
        assert run.ok
        # scan has two commands; both run.
        assert runner.calls == ["echo lint", "echo scan-a", "echo scan-b"]
        assert [r.name for r in run.results] == ["lint", "scan", "ci"]
        assert all(r.status == "pass" for r in run.results)

    def test_multi_command_fail_fast_within_task(self, tmp_path: Path):
        mf = load_makefile(_write(tmp_path, MAKEFILE))
        runner = FakeRunner({"echo scan-a": 7})
        run = run_makefile(mf, ["scan"], runner=runner)
        assert not run.ok
        scan = next(r for r in run.results if r.name == "scan")
        assert scan.status == "fail"
        assert scan.exit_code == 7
        # Second command must not run after the first fails.
        assert "echo scan-b" not in runner.calls

    def test_dependency_failure_skips_dependent(self, tmp_path: Path):
        mf = load_makefile(_write(tmp_path, MAKEFILE))
        runner = FakeRunner({"echo lint": 1})
        run = run_makefile(mf, ["ci"], runner=runner)
        statuses = {r.name: r.status for r in run.results}
        assert statuses["lint"] == "fail"
        # scan is independent of lint → still aborted (fail-fast default).
        assert statuses["ci"] == "skipped"
        assert not run.ok

    def test_keep_going_runs_independent_but_skips_failed_dep(self, tmp_path: Path):
        body = (
            "tasks:\n"
            "  build:\n    run: build-cmd\n"
            "  deploy:\n    needs: [build]\n    run: deploy-cmd\n"
            "  other:\n    run: other-cmd\n"
        )
        mf = load_makefile(_write(tmp_path, body))
        runner = FakeRunner({"build-cmd": 2})
        run = run_makefile(mf, [], keep_going=True, runner=runner)
        statuses = {r.name: r.status for r in run.results}
        assert statuses["build"] == "fail"
        assert statuses["deploy"] == "skipped"  # cannot run on a failed dep
        assert statuses["other"] == "pass"  # independent → keeps going
        assert "deploy-cmd" not in runner.calls
        assert "other-cmd" in runner.calls

    def test_changed_filter_skips_clean_tasks(self, tmp_path: Path):
        mf = load_makefile(_write(tmp_path, MAKEFILE))
        runner = FakeRunner()
        run = run_makefile(mf, ["ci"], changed=["src/app.py"], runner=runner)
        assert runner.calls == []  # nothing matched the prompt globs
        assert all(r.status == "skipped" for r in run.results)
        assert run.ok  # skips are not failures

    def test_dry_run_executes_nothing(self, tmp_path: Path):
        mf = load_makefile(_write(tmp_path, MAKEFILE))
        runner = FakeRunner()
        run = run_makefile(mf, ["ci"], dry_run=True, runner=runner)
        assert runner.calls == []
        assert {r.status for r in run.results} == {"dry-run"}

    def test_parallel_runs_all(self, tmp_path: Path):
        body = "tasks:\n" + "".join(
            f"  t{i}:\n    run: cmd{i}\n" for i in range(6)
        )
        mf = load_makefile(_write(tmp_path, body))
        runner = FakeRunner()
        run = run_makefile(mf, [], parallel=4, runner=runner)
        assert run.ok
        assert sorted(runner.calls) == sorted(f"cmd{i}" for i in range(6))
        assert len(run.results) == 6

    def test_on_complete_callback(self, tmp_path: Path):
        mf = load_makefile(_write(tmp_path, MAKEFILE))
        seen: list[str] = []
        run_makefile(mf, ["ci"], runner=FakeRunner(), on_complete=lambda r: seen.append(r.name))
        assert set(seen) == {"lint", "scan", "ci"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


class TestMakeCommand:
    def _make(self, tmp_path: Path, body: str = MAKEFILE) -> None:
        _write(tmp_path, body)

    def test_run_success_exit_0(self, tmp_path: Path):
        self._make(tmp_path)
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "promptgenie.make.yaml").write_text(MAKEFILE, encoding="utf-8")
            res = runner.invoke(cli, ["make", "lint"])
        assert res.exit_code == 0

    def test_failure_exit_1(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "promptgenie.make.yaml").write_text(
                "tasks:\n  bad:\n    run: \"sh -c 'exit 4'\"\n", encoding="utf-8"
            )
            res = runner.invoke(cli, ["make", "bad"])
        assert res.exit_code == 1

    def test_list(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "promptgenie.make.yaml").write_text(MAKEFILE, encoding="utf-8")
            res = runner.invoke(cli, ["make", "--list"])
        assert res.exit_code == 0
        assert "lint" in res.output and "ci" in res.output

    def test_json_report(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "promptgenie.make.yaml").write_text(MAKEFILE, encoding="utf-8")
            res = runner.invoke(cli, ["make", "lint", "--format", "json"])
        assert res.exit_code == 0
        data = json.loads(res.output)
        assert data["schema_version"] == "1.0"
        assert data["ok"] is True
        assert data["tasks"][0]["name"] == "lint"

    def test_dry_run(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "promptgenie.make.yaml").write_text(MAKEFILE, encoding="utf-8")
            res = runner.invoke(cli, ["make", "ci", "--dry-run"])
        assert res.exit_code == 0
        assert "Plan" in res.output

    def test_unknown_target_exit_2(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "promptgenie.make.yaml").write_text(MAKEFILE, encoding="utf-8")
            res = runner.invoke(cli, ["make", "ghost"])
        assert res.exit_code == 2

    def test_missing_makefile_exit_2(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            res = runner.invoke(cli, ["make"])
        assert res.exit_code == 2

    def test_changed_without_git_exit_2(self, tmp_path: Path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            (Path(fs) / "promptgenie.make.yaml").write_text(MAKEFILE, encoding="utf-8")
            res = runner.invoke(cli, ["make", "ci", "--changed"])
        # isolated_filesystem is not a git repo.
        assert res.exit_code == 2
