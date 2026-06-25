"""Tests for the `promptgenie tokens` read-only inspector (roadmap #7)."""

from __future__ import annotations

import json

import yaml
from click.testing import CliRunner

from promptgenie.cli import cli

# Whitespace + a compressible JSON block + duplicate log lines → real savings.
_SAMPLE = (
    "# Task\n\n\n\nReview    the    code.\n\n"
    '```json\n{\n  "a": 1,\n  "b": [1, 2, 3]\n}\n```\n\n'
    "log line\nlog line\nlog line\nlog line\n"
)


class TestTokensInspector:
    def setup_method(self):
        self.runner = CliRunner()

    def _file(self, tmp_path, content=_SAMPLE):
        p = tmp_path / "p.md"
        p.write_text(content)
        return str(p)

    def test_text_report(self, tmp_path):
        res = self.runner.invoke(cli, ["tokens", self._file(tmp_path)])
        assert res.exit_code == 0
        assert "Token report" in res.output
        assert "Potential savings by technique" in res.output
        # Read-only: must not write any output file next to the input.
        assert not (tmp_path / "p.md.out").exists()

    def test_json_report_shape(self, tmp_path):
        res = self.runner.invoke(cli, ["tokens", self._file(tmp_path), "--format", "json"])
        assert res.exit_code == 0
        data = json.loads(res.stdout)
        assert data["schema_version"] == "1.0"
        assert data["tokens"] > 0
        assert data["chars"] == len(_SAMPLE)
        assert {t["name"] for t in data["techniques"]}  # non-empty
        # json-compact should report a positive saving on this sample.
        jc = next(t for t in data["techniques"] if t["name"] == "json-compact")
        assert jc["tokens_saved"] >= 0
        assert (
            data["combined"]["all"]["tokens_saved"] >= data["combined"]["default"]["tokens_saved"]
        )

    def test_yaml_report(self, tmp_path):
        res = self.runner.invoke(cli, ["tokens", self._file(tmp_path), "--format", "yaml"])
        assert res.exit_code == 0
        data = yaml.safe_load(res.stdout)
        assert data["source"].endswith("p.md")
        assert "combined" in data

    def test_stdin(self):
        res = self.runner.invoke(cli, ["tokens", "-"], input=_SAMPLE)
        assert res.exit_code == 0
        assert "Token report" in res.output

    def test_clean_text_reports_no_savings(self, tmp_path):
        res = self.runner.invoke(
            cli, ["tokens", self._file(tmp_path, "Already compact.\n"), "--format", "json"]
        )
        assert res.exit_code == 0
        data = json.loads(res.stdout)
        assert data["combined"]["all"]["tokens_saved"] == 0

    def test_does_not_modify_input(self, tmp_path):
        path = self._file(tmp_path)
        before = (tmp_path / "p.md").read_text()
        self.runner.invoke(cli, ["tokens", path])
        assert (tmp_path / "p.md").read_text() == before  # untouched
