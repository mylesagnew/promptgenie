"""Tests for commands/validate.py — the new validate command (Wave 5)."""

import tempfile
from pathlib import Path

import yaml
from click.testing import CliRunner

from promptgenie.cli import cli


class TestValidateCommand:
    def setup_method(self):
        self.runner = CliRunner()

    def test_validate_all_builtin(self):
        result = self.runner.invoke(cli, ["validate", "--all"])
        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    def test_validate_valid_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            wf = {
                "name": "test",
                "target": "claude-code",
                "steps": [
                    {"id": "a", "name": "Step A", "objective": "Do A", "output": "Done"},
                ],
            }
            path = Path(tmp) / "test.workflow.yaml"
            path.write_text(yaml.dump(wf))
            result = self.runner.invoke(cli, ["validate", str(path)])
            assert result.exit_code == 0
            assert "✓" in result.output

    def test_validate_cyclic_workflow_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            wf = {
                "name": "cyclic",
                "target": "claude-code",
                "steps": [
                    {"id": "a", "name": "A", "objective": "Do A", "depends_on": "b"},
                    {"id": "b", "name": "B", "objective": "Do B", "depends_on": "a"},
                ],
            }
            path = Path(tmp) / "bad.workflow.yaml"
            path.write_text(yaml.dump(wf))
            result = self.runner.invoke(cli, ["validate", str(path)])
            assert result.exit_code == 1
            assert "✗" in result.output

    def test_validate_valid_prompt_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompt = Path(tmp) / "prompt.md"
            prompt.write_text("## Objective\nDo it.")
            suite = {
                "prompt": "prompt.md",
                "target": "claude",
                "tests": [{"name": "t", "must_include": ["Objective"]}],
            }
            suite_path = Path(tmp) / "suite.prompt-test.yaml"
            suite_path.write_text(yaml.dump(suite))
            result = self.runner.invoke(cli, ["validate", str(suite_path)])
            assert result.exit_code == 0

    def test_validate_prompt_test_missing_prompt_field_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            suite = {"tests": [{"name": "t"}]}
            suite_path = Path(tmp) / "bad.prompt-test.yaml"
            suite_path.write_text(yaml.dump(suite))
            result = self.runner.invoke(cli, ["validate", str(suite_path)])
            assert result.exit_code == 1

    def test_validate_nonexistent_file(self):
        result = self.runner.invoke(cli, ["validate", "/nonexistent/path.yaml"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower() or "✗" in result.output

    def test_validate_no_args_no_all(self):
        result = self.runner.invoke(cli, ["validate"])
        assert result.exit_code == 0
        assert "Nothing to validate" in result.output

    def test_validate_valid_context_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = {"name": "My App", "description": "Test pack", "stack": ["Python"]}
            path = Path(tmp) / "my-app.yaml"
            path.write_text(yaml.dump(pack))
            result = self.runner.invoke(cli, ["validate", str(path)])
            assert result.exit_code == 0
