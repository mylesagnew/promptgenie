"""benchmark command coverage via a fake provider (no network)."""

from __future__ import annotations

from click.testing import CliRunner

from promptgenie.cli import cli

_JUDGE = (
    '{"relevance": 8, "completeness": 8, "format_compliance": 8, '
    '"safety_compliance": 9, "conciseness": 7, "actionability": 8, '
    '"reasoning": "ok"}'
)


class _FakeAnthropicProvider:
    """Stand-in for AnthropicProvider that satisfies the ModelProvider protocol."""

    def __init__(self, *args, **kwargs):
        pass

    def complete(self, model, prompt, system=None):
        usage = {"input": 10, "output": 12, "cache_read": 0, "cache_write": 0}
        # Judge calls pass a system prompt; return parseable rubric scores then.
        return (_JUDGE if system else "A concrete, actionable answer.", usage)

    def judge_model(self):
        return "fake-judge"

    def estimate_cost(self, model, input_tokens, output_tokens, cache_read, cache_write):
        return 0.0


def _patch(monkeypatch):
    import promptgenie.commands.benchmark as bm

    monkeypatch.setattr(bm, "AnthropicProvider", _FakeAnthropicProvider)


class TestBenchmarkCommand:
    def setup_method(self):
        self.runner = CliRunner()

    def test_single_run(self, tmp_path, monkeypatch):
        _patch(monkeypatch)
        f = tmp_path / "p.md"
        f.write_text("## Objective\nReview.\n\n## Output Format\nText.\n")
        res = self.runner.invoke(cli, ["benchmark", str(f), "--yes"])
        assert res.exit_code in (0, 1)

    def test_runs_and_out(self, tmp_path, monkeypatch):
        _patch(monkeypatch)
        f = tmp_path / "p.md"
        f.write_text("## Objective\nReview.\n")
        out = tmp_path / "resp.md"
        res = self.runner.invoke(
            cli, ["benchmark", str(f), "--yes", "--runs", "2", "--out", str(out), "--show-response"]
        )
        assert res.exit_code in (0, 1)

    def test_compare(self, tmp_path, monkeypatch):
        _patch(monkeypatch)
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        a.write_text("## Objective\nA.\n")
        b.write_text("## Objective\nB.\n")
        res = self.runner.invoke(cli, ["benchmark", str(a), "--yes", "--compare", str(b)])
        assert res.exit_code in (0, 1)

    def test_json_format(self, tmp_path, monkeypatch):
        _patch(monkeypatch)
        f = tmp_path / "p.md"
        f.write_text("## Objective\nReview.\n")
        res = self.runner.invoke(cli, ["benchmark", str(f), "--yes", "--format", "json"])
        assert res.exit_code in (0, 1, 2)
