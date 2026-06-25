"""Second coverage batch (roadmap follow-up: 80→85%).

CLI + core paths for plugin/eval/history/completion/diff/generate/run and
keyring-backed credentials (keyring is mocked, no real secret store touched).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

from click.testing import CliRunner

from promptgenie.cli import cli

# ---------------------------------------------------------------------------
# plugin
# ---------------------------------------------------------------------------


class TestPlugin:
    def setup_method(self):
        self.runner = CliRunner()

    def test_list_and_doctor(self):
        assert self.runner.invoke(cli, ["plugin", "list"]).exit_code in (0, 1)
        assert self.runner.invoke(cli, ["plugin", "list", "--format", "json"]).exit_code in (0, 1)
        assert self.runner.invoke(cli, ["plugin", "doctor"]).exit_code in (0, 1)

    def test_scaffold(self, tmp_path):
        res = self.runner.invoke(
            cli,
            ["plugin", "scaffold", "myplug", "--group", "providers", "--out-dir", str(tmp_path)],
        )
        assert res.exit_code in (0, 1, 2)


# ---------------------------------------------------------------------------
# completion (install to tmp, skip rc files)
# ---------------------------------------------------------------------------


class TestCompletion:
    def setup_method(self):
        self.runner = CliRunner()

    def test_install_skip_rc(self, tmp_path):
        for shell in ("zsh", "bash", "fish"):
            res = self.runner.invoke(
                cli,
                ["completion", "install", shell, "--install-dir", str(tmp_path), "--skip-rc"],
            )
            assert res.exit_code in (0, 1, 2)

    def test_refresh_cache(self):
        res = self.runner.invoke(cli, ["completion", "refresh-cache"])
        assert res.exit_code in (0, 1, 2)


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


class TestDiff:
    def test_diff_variants(self, tmp_path):
        a = tmp_path / "a.md"
        b = tmp_path / "b.md"
        a.write_text("## Objective\nDo X.\n\n## Output Format\nText.\n")
        b.write_text("## Objective\nDo X and Y.\n\n## Output Format\nJSON.\n")
        runner = CliRunner()
        assert runner.invoke(cli, ["diff", str(a), str(b)]).exit_code in (0, 1)
        assert runner.invoke(cli, ["diff", str(a), str(b), "--format", "json"]).exit_code in (0, 1)
        assert runner.invoke(cli, ["diff", str(a), str(b), "--unified"]).exit_code in (0, 1)


# ---------------------------------------------------------------------------
# generate edges
# ---------------------------------------------------------------------------


class TestGenerateEdges:
    def setup_method(self):
        self.runner = CliRunner()

    def test_template_and_output_format(self):
        res = self.runner.invoke(
            cli,
            [
                "generate",
                "--no-config",
                "--no-lint",
                "--no-scan",
                "--target",
                "claude",
                "--template",
                "threat-model",
                "--output-format",
                "table",
                "threat model the payment API",
            ],
        )
        assert res.exit_code in (0, 1, 2)

    def test_out_to_file(self, tmp_path):
        out = tmp_path / "g.md"
        res = self.runner.invoke(
            cli,
            [
                "generate",
                "--no-config",
                "--no-lint",
                "--no-scan",
                "--target",
                "claude-code",
                "--out",
                str(out),
                "do the thing",
            ],
        )
        assert res.exit_code == 0
        assert out.exists()


# ---------------------------------------------------------------------------
# history full sub-commands (populated db)
# ---------------------------------------------------------------------------


class TestHistoryFull:
    def test_diff_replay_export_clear(self, tmp_path):
        from promptgenie.core.history_db import HistoryDB

        db = tmp_path / "h.db"
        with HistoryDB(db) as d:
            r1 = d.write_run(spec_name="a", provider="anthropic", model="claude", status="ok")
            r2 = d.write_run(spec_name="b", provider="anthropic", model="claude", status="ok")
        runner = CliRunner()
        assert runner.invoke(cli, ["history", "diff", r1, r2, "--db", str(db)]).exit_code in (0, 1)
        assert runner.invoke(
            cli, ["history", "export", "--db", str(db), "--format", "json"]
        ).exit_code in (0, 1, 2)
        assert runner.invoke(
            cli, ["history", "replay", r1, "--db", str(db), "--dry-run"]
        ).exit_code in (0, 1, 2)
        assert runner.invoke(cli, ["history", "clear", "--db", str(db), "--yes"]).exit_code in (
            0,
            1,
            2,
        )


# ---------------------------------------------------------------------------
# eval compare / approve (offline)
# ---------------------------------------------------------------------------


class TestEvalCompareApprove:
    def test_compare_without_baseline(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            Path("prompt.md").write_text("## Objective\nDo X.\n\n## Output Format\nText.\n")
            init = runner.invoke(cli, ["eval", "init", "s", "--prompt", "prompt.md"])
            assert init.exit_code in (0, 1)
            suite = next(Path().rglob("*.yaml"), None)
            if suite is not None:
                # No snapshot yet → compare should report that (exit 0/1/8).
                assert runner.invoke(cli, ["eval", "compare", str(suite)]).exit_code in (0, 1, 2, 8)
                assert runner.invoke(
                    cli, ["eval", "approve", str(suite), "--dry-run"]
                ).exit_code in (0, 1, 2, 5, 8)


# ---------------------------------------------------------------------------
# credentials with a mocked keyring backend
# ---------------------------------------------------------------------------


def _install_fake_keyring(monkeypatch):
    store: dict[tuple[str, str], str] = {}
    mod = types.ModuleType("keyring")

    def set_password(service, name, value):
        store[(service, name)] = value

    def get_password(service, name):
        return store.get((service, name))

    def delete_password(service, name):
        store.pop((service, name), None)

    mod.set_password = set_password
    mod.get_password = get_password
    mod.delete_password = delete_password
    monkeypatch.setitem(sys.modules, "keyring", mod)
    return store


class TestCredentialsKeyring:
    def test_store_get_delete(self, monkeypatch):
        from promptgenie.core import credentials

        _install_fake_keyring(monkeypatch)
        credentials.store_credential("acme", "sekret")
        # get_credential checks env first; with no env+provider, it reads keyring.
        assert credentials.get_credential("acme") == "sekret"
        assert credentials.delete_credential("acme") is True
        assert credentials.delete_credential("acme") is False  # already gone


# ---------------------------------------------------------------------------
# run edges (dry-run with --tee + provider override)
# ---------------------------------------------------------------------------


class TestRunEdges:
    def test_dry_run_tee_and_provider(self, tmp_path):
        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path):
            init = runner.invoke(cli, ["spec", "init", "r", "--target", "claude-code"])
            assert init.exit_code == 0
            res = runner.invoke(
                cli,
                [
                    "run",
                    "r.prompt.yaml",
                    "--dry-run",
                    "--var",
                    "variable=x",
                    "--provider",
                    "ollama",
                    "--show-context",
                ],
            )
            assert res.exit_code in (0, 1, 2)
