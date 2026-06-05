"""Tests for core/ci.py — scaffold and status (Wave 5 coverage)."""

import tempfile
from pathlib import Path

from promptgenie.core.ci import ci_status, init_ci


class TestInitCi:
    def test_creates_all_files_in_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = init_ci(tmp)
            created = result["created"]
            assert "github_actions" in created
            assert "pre_commit" in created
            assert "promptignore" in created
            assert created["github_actions"].exists()
            assert created["pre_commit"].exists()
            assert created["promptignore"].exists()

    def test_skips_existing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            # First call creates
            init_ci(tmp)
            # Second call skips
            result = init_ci(tmp)
            assert not result["created"]
            assert "github_actions" in result["skipped"]
            assert "pre_commit" in result["skipped"]
            assert "promptignore" in result["skipped"]

    def test_workflow_content_is_yaml(self):
        import yaml
        with tempfile.TemporaryDirectory() as tmp:
            result = init_ci(tmp)
            wf_path = result["created"]["github_actions"]
            data = yaml.safe_load(wf_path.read_text())
            assert "jobs" in data

    def test_partial_create_only_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Pre-create one file
            gha_dir = Path(tmp) / ".github" / "workflows"
            gha_dir.mkdir(parents=True)
            (gha_dir / "prompt-check.yml").write_text("existing")
            result = init_ci(tmp)
            assert "github_actions" in result["skipped"]
            assert "pre_commit" in result["created"]


class TestCiStatus:
    def test_false_in_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            status = ci_status(tmp)
            assert status["github_actions"] is False
            assert status["pre_commit"] is False
            assert status["promptignore"] is False
            assert status["is_git_repo"] is False

    def test_true_after_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_ci(tmp)
            status = ci_status(tmp)
            assert status["github_actions"] is True
            assert status["pre_commit"] is True
            assert status["promptignore"] is True
