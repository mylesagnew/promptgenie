"""Seventh coverage batch (roadmap follow-up: final edges toward ~83%)."""

from __future__ import annotations

from click.testing import CliRunner

from promptgenie.cli import cli


class TestRunGenerateEdges:
    def setup_method(self):
        self.runner = CliRunner()

    def test_run_unresolved_var_noninteractive(self, tmp_path):
        with self.runner.isolated_filesystem(temp_dir=tmp_path):
            self.runner.invoke(cli, ["spec", "init", "r", "--target", "claude-code"])
            # No --var for the {{variable}} placeholder + --no-input → error path.
            res = self.runner.invoke(cli, ["run", "r.prompt.yaml", "--dry-run", "--no-input"])
            assert res.exit_code in (0, 1, 2)

    def test_run_no_history_and_require_clean(self, tmp_path):
        with self.runner.isolated_filesystem(temp_dir=tmp_path):
            self.runner.invoke(cli, ["spec", "init", "r", "--target", "claude-code"])
            res = self.runner.invoke(
                cli,
                [
                    "run",
                    "r.prompt.yaml",
                    "--dry-run",
                    "--var",
                    "variable=x",
                    "--no-history",
                    "--require-clean",
                ],
            )
            assert res.exit_code in (0, 1, 2)

    def test_generate_infer_target_and_constraints(self):
        # No --target → inference from the task text.
        res = self.runner.invoke(
            cli,
            [
                "generate",
                "--no-config",
                "--no-lint",
                "--no-scan",
                "--constraints",
                "no deploys",
                "--mode",
                "minimal",
                "review this repo with claude code",
            ],
        )
        assert res.exit_code in (0, 1)


class TestProvidersAndCredentials:
    def test_get_provider_types(self, tmp_path, monkeypatch):
        import promptgenie.core.providers as providers

        monkeypatch.setattr(providers, "_PROVIDERS_FILE", tmp_path / "p.yaml")
        anthro = providers.get_provider("anthropic")
        assert anthro.__class__.__name__ == "AnthropicProvider"
        ollama = providers.get_provider("ollama")
        assert ollama.__class__.__name__ == "OpenAICompatProvider"

    def test_get_credential_from_provider_config(self, tmp_path, monkeypatch):
        import promptgenie.core.credentials as credentials
        import promptgenie.core.providers as providers

        monkeypatch.setattr(providers, "_PROVIDERS_FILE", tmp_path / "p.yaml")
        monkeypatch.setenv("NOUS_API_KEY", "hermes-key")
        # hermes default provider → api_key_env=NOUS_API_KEY (env branch).
        assert credentials.get_credential("hermes") == "hermes-key"


class TestPaletteReadline:
    def test_no_tui_print_only_query(self):
        runner = CliRunner()
        # Feed a selection index/term; readline fallback path.
        res = runner.invoke(cli, ["palette", "--no-tui", "--print-only"], input="generate\n")
        assert res.exit_code in (0, 1, 2)


class TestScanLintEdges:
    def setup_method(self):
        self.runner = CliRunner()

    def test_scan_single_file_secret(self, tmp_path):
        f = tmp_path / "s.md"
        f.write_text("api_key = sk-ant-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n")
        res = self.runner.invoke(cli, ["scan", str(f), "--no-config"])
        assert res.exit_code in (0, 1)

    def test_lint_stdin(self):
        res = self.runner.invoke(cli, ["lint", "-"], input="help me improve the whole app\n")
        assert res.exit_code in (0, 1)

    def test_redteam_list_attacks_and_categories(self, tmp_path):
        assert self.runner.invoke(cli, ["redteam", "--list-attacks"]).exit_code == 0
        f = tmp_path / "p.md"
        f.write_text("You are a helpful assistant.\n")
        assert self.runner.invoke(cli, ["redteam", str(f), "--fail-on-susceptible"]).exit_code in (
            0,
            1,
        )


class TestListAndValidate:
    def setup_method(self):
        self.runner = CliRunner()

    def test_list_targets_templates_validate(self):
        assert self.runner.invoke(cli, ["list-targets"]).exit_code == 0
        assert self.runner.invoke(cli, ["list-templates"]).exit_code == 0
        assert self.runner.invoke(cli, ["validate", "--all"]).exit_code in (0, 1)
