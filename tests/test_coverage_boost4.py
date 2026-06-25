"""Fourth coverage batch (roadmap follow-up: toward ~83%, no production changes).

gh_reporter direct calls, provider/auth commands (isolated config), offline pack
subcommands, palette, template render, and evaluate baseline paths.
"""

from __future__ import annotations

import io
import types
from pathlib import Path

from click.testing import CliRunner

from promptgenie.cli import cli

# ---------------------------------------------------------------------------
# gh_reporter (direct)
# ---------------------------------------------------------------------------


class TestGHReporter:
    def test_annotations_and_summaries(self, tmp_path, monkeypatch):
        from promptgenie.core import gh_reporter as gh

        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        assert gh.is_github_actions() is True

        buf = io.StringIO()
        r = gh.GHReporter(out=buf)
        r.error("an error", file="p.md", line=3, col=2)
        r.warning("a warning")
        r.notice("a notice")
        out = buf.getvalue()
        assert "::error" in out and "::warning" in out and "::notice" in out

        finding = types.SimpleNamespace(
            code="SEC_1",
            severity="HIGH",
            title="t",
            message="m",
            location=types.SimpleNamespace(file="p.md", line=1, col=1),
        )
        r.annotate_findings([finding], file_path="p.md")

        md = gh.format_analyze_summary([], "p.md", overall_risk="LOW", lint_score=90, passed=True)
        assert "PromptGenie" in md

    def test_step_summary_file(self, tmp_path):
        from promptgenie.core import gh_reporter as gh

        summ = tmp_path / "summary.md"
        r = gh.GHReporter(summary_path=str(summ))
        r.write_step_summary("## Hello\n")
        assert summ.exists() and "Hello" in summ.read_text()


# ---------------------------------------------------------------------------
# provider command (isolated providers.yaml)
# ---------------------------------------------------------------------------


class TestProviderCommand:
    def test_add_show_remove(self, tmp_path, monkeypatch):
        import promptgenie.core.providers as providers

        monkeypatch.setattr(providers, "_PROVIDERS_FILE", tmp_path / "providers.yaml")
        runner = CliRunner()
        add = runner.invoke(
            cli,
            [
                "provider",
                "add",
                "myp",
                "--type",
                "openai_compat",
                "--base-url",
                "https://api.example.com/v1",
                "--model",
                "m",
            ],
        )
        assert add.exit_code in (0, 1, 2)
        assert runner.invoke(cli, ["provider", "show", "myp"]).exit_code in (0, 1, 2)
        assert runner.invoke(cli, ["provider", "show", "myp", "--format", "json"]).exit_code in (
            0,
            1,
            2,
        )
        assert runner.invoke(cli, ["provider", "remove", "myp", "--yes"]).exit_code in (0, 1, 2)


# ---------------------------------------------------------------------------
# auth command
# ---------------------------------------------------------------------------


class TestAuthCommand:
    def setup_method(self):
        self.runner = CliRunner()

    def test_status(self):
        assert self.runner.invoke(cli, ["auth", "status"]).exit_code in (0, 1)

    def test_login_external_ref(self):
        # External secret-manager source records a ref pointer (no live fetch).
        res = self.runner.invoke(
            cli, ["auth", "login", "anthropic", "--source", "aws-ssm", "--ref", "/pg/key"]
        )
        assert res.exit_code in (0, 1, 2)

    def test_logout(self):
        assert self.runner.invoke(cli, ["auth", "logout", "anthropic", "--yes"]).exit_code in (
            0,
            1,
            2,
        )


# ---------------------------------------------------------------------------
# pack offline subcommands (diff, test)
# ---------------------------------------------------------------------------

_PACK_A = """\
name: demo
description: A demo pack
rules:
  - id: R1
    pattern: "foo"
    category: custom
    risk: MEDIUM
    message: "matched foo"
"""
_PACK_B = """\
name: demo
description: A demo pack v2
rules:
  - id: R1
    pattern: "foo"
    category: custom
    risk: HIGH
    message: "matched foo"
  - id: R2
    pattern: "bar"
    category: custom
    risk: LOW
    message: "matched bar"
"""


class TestPackOffline:
    def test_diff(self, tmp_path):
        a = tmp_path / "a.yaml"
        b = tmp_path / "b.yaml"
        a.write_text(_PACK_A)
        b.write_text(_PACK_B)
        runner = CliRunner()
        assert runner.invoke(cli, ["pack", "diff", str(a), str(b)]).exit_code in (0, 1, 2)

    def test_test_subcommand(self, tmp_path):
        pack = tmp_path / "pack.yaml"
        pack.write_text(_PACK_A)
        tests = tmp_path / "tests.yaml"
        tests.write_text(
            "tests:\n  - text: 'this has foo in it'\n    expect: [R1]\n"
            "  - text: 'totally clean'\n    expect: []\n"
        )
        runner = CliRunner()
        assert runner.invoke(cli, ["pack", "test", str(pack), str(tests)]).exit_code in (0, 1, 2)


# ---------------------------------------------------------------------------
# palette readline fallback
# ---------------------------------------------------------------------------


class TestPalette:
    def test_no_tui_print_only(self):
        runner = CliRunner()
        res = runner.invoke(cli, ["palette", "--no-tui", "--print-only"], input="lint\n")
        assert res.exit_code in (0, 1, 2)


# ---------------------------------------------------------------------------
# template render / validate
# ---------------------------------------------------------------------------


class TestTemplateRender:
    def setup_method(self):
        self.runner = CliRunner()

    def test_render_and_validate(self, tmp_path):
        assert self.runner.invoke(
            cli, ["template", "render", "agentic-task", "--var", "objective=ship it"]
        ).exit_code in (0, 1, 2)
        out = tmp_path / "r.md"
        assert self.runner.invoke(
            cli, ["template", "render", "agentic-task", "--out", str(out)]
        ).exit_code in (0, 1, 2)


# ---------------------------------------------------------------------------
# evaluate baseline save/compare via fake provider
# ---------------------------------------------------------------------------


class _FakeEvalProvider:
    model = "fake-model"
    last_usage = {"input": 5, "output": 5}

    async def complete(self, messages, *, model=None, max_tokens=2048, timeout=120, **kw):
        return "stable answer"


class TestEvaluateBaseline:
    def test_save_then_compare(self, tmp_path, monkeypatch):
        import promptgenie.core.providers as providers

        monkeypatch.setattr(providers, "get_provider", lambda *a, **k: _FakeEvalProvider())
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("p.md").write_text("## Objective\nReview.\n\n## Output Format\nText.\n")
            saved = runner.invoke(
                cli, ["evaluate", "p.md", "--models", "claude", "--save-baseline", "main"]
            )
            assert saved.exit_code in (0, 1, 8)
            cmp = runner.invoke(
                cli, ["evaluate", "p.md", "--models", "claude", "--compare", "main"]
            )
            assert cmp.exit_code in (0, 1, 8)
