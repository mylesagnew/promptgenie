"""test_phase5.py — Phase 5 test suite.

Covers:
  - Full-screen TUI command (offline / graceful degradation)
  - Guided prompt wizard
  - Smart command palette (catalogue building, fuzzy match)
  - Prompt history DB (SQLite CRUD, search, export, dedup)
  - Watch mode (runners, debounce)
  - Template command group
  - Prompt lockfiles
  - Plugin SDK
  - Signed enterprise packs (pack diff, promote, unit test)
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
from click.testing import CliRunner

from promptgenie.cli import cli

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def invoke(*args: str, **kw):
    runner = CliRunner()
    return runner.invoke(cli, list(args), catch_exceptions=False, **kw)


# ===========================================================================
# TUI command
# ===========================================================================


class TestTuiCmd:
    def test_help(self):
        result = invoke("tui", "--help")
        assert result.exit_code == 0
        assert "full-screen" in result.output.lower() or "tui" in result.output.lower()

    def test_no_textual_shows_error(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "textual" or name.startswith("textual."):
                raise ImportError("No module named 'textual'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        runner = CliRunner()
        result = runner.invoke(cli, ["tui"], catch_exceptions=False)
        # Should exit with EXIT_USAGE (2) and mention install
        assert result.exit_code == 2
        assert "pip install" in result.output.lower() or "textual" in result.output.lower()


# ===========================================================================
# Wizard command
# ===========================================================================


class TestWizardCmd:
    def test_help(self):
        result = invoke("wizard", "--help")
        assert result.exit_code == 0
        assert "wizard" in result.output.lower()

    def test_wizard_produces_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        # Simulate full wizard interaction
        inputs = (
            "\n".join(
                [
                    "Review all PRs for security issues",  # objective
                    "All code in the pull request",  # scope
                    "Infrastructure code",  # out_of_scope
                    "Never expose secrets",  # forbidden
                    "markdown",  # output_format
                    "CI passes and reviewer approves",  # verification
                    "code-review",  # target
                    "",  # no packs
                ]
            )
            + "\n"
        )
        result = runner.invoke(
            cli,
            ["wizard", "--no-spec"],
            input=inputs,
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        # A .md file should have been written
        md_files = list(tmp_path.rglob("*.md"))
        assert len(md_files) >= 1

    def test_wizard_with_spec(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        inputs = (
            "\n".join(
                [
                    "Generate docstrings for Python functions",
                    "src/ directory only",
                    "Tests and CI config",
                    "Do not modify tests",
                    "code",
                    "Output compiles and tests pass",
                    "documentation",
                    "",
                ]
            )
            + "\n"
        )
        result = runner.invoke(
            cli,
            ["wizard"],
            input=inputs,
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        yaml_files = list(tmp_path.rglob("*.yaml"))
        assert len(yaml_files) >= 1

    def test_wizard_empty_objective_exits(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["wizard"],
            input="\n",  # blank objective
            catch_exceptions=False,
        )
        assert result.exit_code == 2  # EXIT_USAGE

    def test_wizard_custom_out(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        out_file = str(tmp_path / "my-prompt.md")
        inputs = (
            "\n".join(
                [
                    "Summarize code changes",
                    "Changed files only",
                    "Unrelated files",
                    "Never rewrite tests",
                    "markdown",
                    "Human reads and approves",
                    "documentation",
                    "",
                ]
            )
            + "\n"
        )
        result = runner.invoke(
            cli,
            ["wizard", "--no-spec", "--out", out_file],
            input=inputs,
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert Path(out_file).exists()


# ===========================================================================
# Palette command
# ===========================================================================


class TestPaletteCmd:
    def test_help(self):
        result = invoke("palette", "--help")
        assert result.exit_code == 0

    def test_fuzzy_match(self):
        from promptgenie.commands.palette_cmd import _fuzzy_match

        assert _fuzzy_match("lint", "lint a file") is True
        assert _fuzzy_match("sca", "scan for issues") is True
        assert _fuzzy_match("xyz", "run the prompt") is False
        assert _fuzzy_match("", "anything") is True

    def test_filter_items(self):
        from promptgenie.commands.palette_cmd import PaletteItem, _filter_items

        items = [
            PaletteItem("lint file", "command", "promptgenie lint", "Lint a prompt"),
            PaletteItem("scan file", "command", "promptgenie scan", "Scan for secrets"),
            PaletteItem("template list", "template", "promptgenie template list", ""),
        ]
        result = _filter_items(items, "lint")
        assert len(result) == 1
        assert result[0].label == "lint file"

    def test_build_catalogue_returns_items(self):
        from promptgenie.commands.palette_cmd import _build_catalogue

        items = _build_catalogue()
        assert len(items) > 10
        labels = [it.label for it in items]
        assert any("lint" in lbl for lbl in labels)
        assert any("scan" in lbl for lbl in labels)
        assert any("wizard" in lbl for lbl in labels)

    def test_palette_no_tui_cancel(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["palette", "--no-tui"],
            input="lint\n0\n",  # filter then cancel
            catch_exceptions=False,
        )
        assert result.exit_code == 0

    def test_palette_no_tui_select(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["palette", "--no-tui", "--print-only"],
            input="lint\n1\n",  # filter=lint, select first
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "promptgenie" in result.output


# ===========================================================================
# History DB
# ===========================================================================


class TestHistoryDb:
    def _make_db(self, tmp_path: Path):
        from promptgenie.core.history_db import HistoryDB

        db_path = tmp_path / "history.db"
        return HistoryDB(db_path), db_path

    def test_write_and_get(self, tmp_path):
        from promptgenie.core.history_db import HistoryDB

        db = HistoryDB(tmp_path / "h.db")
        run_id = db.write_run(
            spec_name="test-spec",
            provider="claude",
            model="claude-haiku-4-5",
            prompt_text="Hello world",
            response_text="Hi there",
            status="ok",
            duration_s=1.2,
        )
        assert isinstance(run_id, str)
        record = db.get_run(run_id)
        assert record is not None
        assert record.provider == "claude"
        assert record.spec_name == "test-spec"

    def test_list_runs(self, tmp_path):
        from promptgenie.core.history_db import HistoryDB

        db = HistoryDB(tmp_path / "h.db")
        for i in range(5):
            db.write_run(
                spec_name=f"spec-{i}",
                provider="claude",
                model="claude-haiku-4-5",
                prompt_text=f"prompt {i}",
                response_text=f"response {i}",
                status="ok",
            )
        runs = db.list_runs(limit=3)
        assert len(runs) == 3

    def test_search_runs(self, tmp_path):
        from promptgenie.core.history_db import HistoryDB

        db = HistoryDB(tmp_path / "h.db")
        db.write_run(
            spec_name="auth-spec",
            provider="claude",
            model="claude-haiku-4-5",
            prompt_text="authentication review",
            response_text="looks good",
            status="ok",
        )
        db.write_run(
            spec_name="other-spec",
            provider="openai",
            model="gpt-4.1",
            prompt_text="refactor this",
            response_text="done",
            status="ok",
        )
        results = db.search_runs("auth")
        assert len(results) >= 1
        assert any("auth" in r.spec_name for r in results)

    def test_content_hash_deduplication(self, tmp_path):
        from promptgenie.core.history_db import HistoryDB

        db = HistoryDB(tmp_path / "h.db")
        db.write_run(
            provider="claude",
            model="claude-haiku-4-5",
            prompt_text="same prompt",
            response_text="same response",
            status="ok",
        )
        db.write_run(
            provider="claude",
            model="claude-haiku-4-5",
            prompt_text="same prompt",
            response_text="same response",
            status="ok",
        )
        dupes = db.find_duplicates("same prompt")
        assert len(dupes) >= 1

    def test_delete_run(self, tmp_path):
        from promptgenie.core.history_db import HistoryDB

        db = HistoryDB(tmp_path / "h.db")
        run_id = db.write_run(
            provider="claude",
            model="claude-haiku-4-5",
            prompt_text="temp",
            response_text="temp resp",
            status="ok",
        )
        db.delete_run(run_id)
        assert db.get_run(run_id) is None

    def test_total_count(self, tmp_path):
        from promptgenie.core.history_db import HistoryDB

        db = HistoryDB(tmp_path / "h.db")
        for _ in range(4):
            db.write_run(
                provider="claude",
                model="claude-haiku-4-5",
                prompt_text="p",
                response_text="r",
                status="ok",
            )
        assert db.total_count() == 4

    def test_export_json(self, tmp_path):
        from promptgenie.core.history_db import HistoryDB

        db = HistoryDB(tmp_path / "h.db")
        db.write_run(
            provider="claude",
            model="claude-haiku-4-5",
            prompt_text="export test",
            response_text="result",
            status="ok",
        )
        output = db.export("json")
        data = json.loads(output)
        assert isinstance(data, list)
        assert len(data) == 1

    def test_export_csv(self, tmp_path):
        from promptgenie.core.history_db import HistoryDB

        db = HistoryDB(tmp_path / "h.db")
        db.write_run(
            provider="claude",
            model="claude-haiku-4-5",
            prompt_text="csv test",
            response_text="result",
            status="ok",
        )
        output = db.export("csv")
        assert "provider" in output
        assert "claude" in output

    def test_export_ndjson(self, tmp_path):
        from promptgenie.core.history_db import HistoryDB

        db = HistoryDB(tmp_path / "h.db")
        db.write_run(
            provider="claude",
            model="claude-haiku-4-5",
            prompt_text="nd test",
            response_text="result",
            status="ok",
        )
        output = db.export("ndjson")
        lines = [ln for ln in output.strip().splitlines() if ln]
        assert len(lines) == 1
        json.loads(lines[0])  # valid JSON


class TestHistoryCli:
    def test_history_help(self):
        result = invoke("history", "--help")
        assert result.exit_code == 0

    def test_history_list_empty(self, tmp_path):
        runner = CliRunner()
        db_path = str(tmp_path / "h.db")
        result = runner.invoke(
            cli,
            ["history", "list", "--db", db_path],
            catch_exceptions=False,
        )
        assert result.exit_code == 0

    def test_history_export_json(self, tmp_path):
        from promptgenie.core.history_db import HistoryDB

        db_path = tmp_path / "h.db"
        db = HistoryDB(db_path)
        db.write_run(
            provider="claude",
            model="claude-haiku-4-5",
            prompt_text="hello",
            response_text="world",
            status="ok",
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["history", "export", "--format", "json", "--db", str(db_path)],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)

    def test_history_clear_confirmed(self, tmp_path):
        from promptgenie.core.history_db import HistoryDB

        db_path = tmp_path / "h.db"
        db = HistoryDB(db_path)
        db.write_run(
            provider="claude",
            model="claude-haiku-4-5",
            prompt_text="x",
            response_text="y",
            status="ok",
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["history", "clear", "--db", str(db_path)],
            input="y\n",
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert db.total_count() == 0

    def test_history_diff_two_runs(self, tmp_path):
        from promptgenie.core.history_db import HistoryDB

        db_path = tmp_path / "h.db"
        db = HistoryDB(db_path)
        id1 = db.write_run(
            provider="claude",
            model="claude-haiku-4-5",
            prompt_text="p",
            response_text="hello world",
            status="ok",
        )
        id2 = db.write_run(
            provider="claude",
            model="claude-haiku-4-5",
            prompt_text="p",
            response_text="hello there",
            status="ok",
        )
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["history", "diff", id1, id2, "--db", str(db_path)],
            catch_exceptions=False,
        )
        assert result.exit_code == 0


# ===========================================================================
# Watch mode
# ===========================================================================


class TestWatcher:
    def test_help(self):
        result = invoke("watch", "--help")
        assert result.exit_code == 0

    def test_make_pipeline_lint(self):
        from promptgenie.core.watcher import make_pipeline

        pipeline = make_pipeline("lint")
        assert pipeline.name == "lint"
        assert callable(pipeline.run_fn)

    def test_make_pipeline_scan(self):
        from promptgenie.core.watcher import make_pipeline

        pipeline = make_pipeline("scan")
        assert pipeline.name == "scan"

    def test_make_pipeline_policy(self):
        from promptgenie.core.watcher import make_pipeline

        pipeline = make_pipeline("policy")
        assert pipeline.name == "policy"

    def test_watch_result_dataclass(self):
        from promptgenie.core.watcher import WatchResult

        r = WatchResult(
            file_path=Path("test.md"),
            pipeline_name="lint",
            passed=True,
            summary="ok",
            findings_count=0,
        )
        assert r.passed is True
        assert r.findings_count == 0


# ===========================================================================
# Template command group
# ===========================================================================


class TestTemplateStore:
    def test_list_all_templates(self):
        from promptgenie.core.template_store import list_all_templates

        templates = list_all_templates()
        assert isinstance(templates, list)

    def test_resolve_nonexistent_returns_none(self):
        from promptgenie.core.template_store import resolve_template

        result = resolve_template("does-not-exist-xyz-123")
        assert result is None

    def test_render_template_substitution(self):
        from promptgenie.core.template_store import (
            TemplateRecord,
            TemplateVariable,
            render_template,
        )

        record = TemplateRecord(
            id="test-render",
            name="Test",
            description="",
            category="test",
            system="",
            prompt="Hello {{name}}, welcome to {{place}}.",
            variables=[
                TemplateVariable(name="name", description="", default="", required=True),
                TemplateVariable(name="place", description="", default="", required=True),
            ],
        )
        rendered = render_template(record, {"name": "Alice", "place": "Wonderland"})
        assert "Alice" in rendered
        assert "Wonderland" in rendered

    def test_validate_template_missing_name(self):
        from promptgenie.core.template_store import TemplateRecord, validate_template

        record = TemplateRecord(
            id="valid-id",
            name="",  # missing
            description="",
            category="test",
            system="",
            prompt="Some prompt {{var}}",
            variables=[],
        )
        errors = validate_template(record)
        assert any("name" in e.lower() for e in errors)

    def test_validate_template_missing_prompt(self):
        from promptgenie.core.template_store import TemplateRecord, validate_template

        record = TemplateRecord(
            id="valid-id",
            name="Valid Name",
            description="",
            category="test",
            system="",
            prompt="",  # missing
            variables=[],
        )
        errors = validate_template(record)
        assert any("prompt" in e.lower() for e in errors)

    def test_validate_template_undeclared_var(self):
        from promptgenie.core.template_store import (
            TemplateRecord,
            validate_template,
        )

        record = TemplateRecord(
            id="test-id",
            name="Test",
            description="",
            category="test",
            system="",
            prompt="Hello {{undeclared_var}}",
            variables=[],
        )
        errors = validate_template(record)
        assert any("undeclared" in e.lower() or "undeclared_var" in e for e in errors)

    def test_save_and_load_user_template(self, tmp_path, monkeypatch):
        import promptgenie.core.template_store as ts

        user_dir = tmp_path / "user-templates"
        monkeypatch.setattr(ts, "_USER_DIR", user_dir)
        monkeypatch.setattr(ts, "TEMPLATE_SEARCH_ORDER", (user_dir,))
        from promptgenie.core.template_store import (
            TemplateRecord,
            resolve_template,
            save_user_template,
        )

        record = TemplateRecord(
            id="my-custom-template",
            name="My Custom",
            description="A test template",
            category="test",
            system="",
            prompt="Do {{task}} for {{target}}.",
            variables=[],
        )
        saved_path = save_user_template(record)
        assert saved_path.exists()
        loaded = resolve_template("my-custom-template")
        assert loaded is not None
        assert loaded.name == "My Custom"


class TestTemplateCli:
    def test_template_list_help(self):
        result = invoke("template", "--help")
        assert result.exit_code == 0

    def test_template_list(self):
        result = invoke("template", "list")
        assert result.exit_code == 0

    def test_template_list_json(self):
        result = invoke("template", "list", "--format", "json")
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)

    def test_template_show_nonexistent(self):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["template", "show", "does-not-exist-xyz"], catch_exceptions=False
        )
        assert result.exit_code != 0

    def test_template_validate_nonexistent(self):
        runner = CliRunner()
        result = runner.invoke(
            cli, ["template", "validate", "does-not-exist-xyz"], catch_exceptions=False
        )
        assert result.exit_code != 0


# ===========================================================================
# Lockfile
# ===========================================================================


class TestLockfile:
    def test_create_and_write_lockfile(self, tmp_path):
        from promptgenie.core.lockfile import create_lockfile, load_lockfile, write_lockfile

        spec = tmp_path / "prompt.yaml"
        spec.write_text("name: test\nprovider: claude\nmodel: claude-haiku-4-5\n")
        record = create_lockfile(spec)
        assert record.spec == str(spec)
        assert record.spec_hash.startswith("sha256:")
        lock_path = write_lockfile(record)
        assert lock_path.exists()
        loaded = load_lockfile(lock_path)
        assert loaded is not None
        assert loaded.spec == str(spec)

    def test_check_lockfile_passes_when_unchanged(self, tmp_path):
        from promptgenie.core.lockfile import (
            check_lockfile,
            create_lockfile,
            load_lockfile,
            write_lockfile,
        )

        spec = tmp_path / "prompt.yaml"
        spec.write_text("name: test\nprovider: claude\n")
        record = create_lockfile(spec)
        lock_path = write_lockfile(record)
        loaded = load_lockfile(lock_path)
        result = check_lockfile(loaded)
        assert result.passed

    def test_check_lockfile_detects_drift(self, tmp_path):
        from promptgenie.core.lockfile import (
            check_lockfile,
            create_lockfile,
            load_lockfile,
            write_lockfile,
        )

        spec = tmp_path / "prompt.yaml"
        spec.write_text("name: test\nprovider: claude\n")
        record = create_lockfile(spec)
        lock_path = write_lockfile(record)
        # Modify the spec
        spec.write_text("name: test\nprovider: openai\n")
        loaded = load_lockfile(lock_path)
        result = check_lockfile(loaded)
        assert not result.passed
        assert len(result.stale) >= 1

    def test_lockfile_with_template_ref(self, tmp_path):
        from promptgenie.core.lockfile import create_lockfile

        tmpl = tmp_path / "my-template.yaml"
        tmpl.write_text("id: my-template\nprompt: Hello\n")
        spec = tmp_path / "prompt.yaml"
        spec.write_text("name: test\ntemplate: my-template.yaml\nprovider: claude\n")
        record = create_lockfile(spec)
        template_entries = [e for e in record.entries if e.kind == "template"]
        assert len(template_entries) == 1
        assert template_entries[0].hash.startswith("sha256:")


class TestLockCli:
    def test_lock_help(self):
        result = invoke("lock", "--help")
        assert result.exit_code == 0

    def test_lock_create(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        spec = tmp_path / "prompt.yaml"
        spec.write_text("name: test\nprovider: claude\nmodel: claude-haiku-4-5\n")
        result = invoke("lock", str(spec))
        assert result.exit_code == 0
        lock_file = tmp_path / "prompt.yaml.lock"
        assert lock_file.exists()

    def test_lock_check_passes(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from promptgenie.core.lockfile import create_lockfile, write_lockfile

        spec = tmp_path / "prompt.yaml"
        spec.write_text("name: test\nprovider: claude\n")
        record = create_lockfile(spec)
        lock_path = write_lockfile(record)
        result = invoke("lock", str(lock_path), "--check")
        assert result.exit_code == 0

    def test_lock_check_fails_on_drift(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        from promptgenie.core.lockfile import create_lockfile, write_lockfile

        spec = tmp_path / "prompt.yaml"
        spec.write_text("name: test\nprovider: claude\n")
        record = create_lockfile(spec)
        lock_path = write_lockfile(record)
        spec.write_text("name: modified\nprovider: openai\n")
        runner = CliRunner()
        result = runner.invoke(cli, ["lock", str(lock_path), "--check"], catch_exceptions=False)
        assert result.exit_code == 1

    def test_lock_json_format(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        spec = tmp_path / "prompt.yaml"
        spec.write_text("name: test\nprovider: claude\n")
        result = invoke("lock", str(spec), "--format", "json")
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "spec_hash" in data


# ===========================================================================
# Plugin SDK
# ===========================================================================


class TestPluginSdk:
    def test_plugin_list_help(self):
        result = invoke("plugin", "--help")
        assert result.exit_code == 0

    def test_plugin_list(self):
        result = invoke("plugin", "list")
        assert result.exit_code == 0

    def test_plugin_list_json(self):
        result = invoke("plugin", "list", "--format", "json")
        assert result.exit_code == 0
        # May be empty list printed as JSON, or a "No plugins" message
        try:
            data = json.loads(result.output)
            assert isinstance(data, list)
        except json.JSONDecodeError:
            assert "plugin" in result.output.lower() or "install" in result.output.lower()

    def test_plugin_doctor(self):
        result = invoke("plugin", "doctor")
        assert result.exit_code == 0

    def test_plugin_scaffold(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "plugin",
                "scaffold",
                "my-plugin",
                "--group",
                "promptgenie.rules",
                "--out",
                str(tmp_path),
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        stub_files = list(tmp_path.rglob("*.py"))
        assert len(stub_files) >= 1

    def test_list_plugins_returns_list(self):
        from promptgenie.core.plugin import list_plugins

        plugins = list_plugins()
        assert isinstance(plugins, list)

    def test_check_plugin_compat_unknown_group(self):
        from promptgenie.core.plugin import PluginManifest, check_plugin_compat

        manifest = PluginManifest(
            name="test",
            group="promptgenie.renderers",
            entry_point="test:Test",
            package="test-pkg",
            version="1.0.0",
            dist_name="test-pkg",
            origin="pypi",
            loaded=False,
            load_error=None,
            obj=None,
        )
        warnings = check_plugin_compat(manifest)
        assert isinstance(warnings, list)

    def test_scaffold_plugin_content(self, tmp_path):
        from promptgenie.core.plugin import scaffold_plugin

        path = scaffold_plugin("my-provider", "promptgenie.providers", output_dir=tmp_path)
        content = Path(path).read_text()
        assert (
            "promptgenie.providers" in content or "TODO" in content or "plugin" in content.lower()
        )


# ===========================================================================
# Signed enterprise packs
# ===========================================================================


class TestPackSigning:
    def test_verify_minisign_missing_sig_file(self, tmp_path):
        from promptgenie.core.pack_signing import verify_pack_signature

        pack = tmp_path / "pack.yaml"
        pack.write_text("name: test\nrules: []\n")
        with pytest.raises(FileNotFoundError):
            verify_pack_signature(pack, "fake-key.pub", method="minisign")

    def test_verify_cosign_missing_sig_file(self, tmp_path):
        from promptgenie.core.pack_signing import verify_pack_signature

        pack = tmp_path / "pack.yaml"
        pack.write_text("name: test\nrules: []\n")
        with pytest.raises(FileNotFoundError):
            verify_pack_signature(pack, "fake-key.pub", method="cosign")

    def test_verify_unknown_method(self, tmp_path):
        from promptgenie.core.pack_signing import verify_pack_signature

        pack = tmp_path / "pack.yaml"
        pack.write_text("name: test\nrules: []\n")
        with pytest.raises(ValueError):
            verify_pack_signature(pack, "fake-key.pub", method="pgp")

    def test_diff_packs_no_changes(self, tmp_path):
        from promptgenie.core.pack_signing import diff_packs

        content = "version: '1.0'\nname: TestPack\nrules:\n  - id: RULE_001\n    pattern: foo\n"
        old = tmp_path / "old.yaml"
        new = tmp_path / "new.yaml"
        old.write_text(content)
        new.write_text(content)
        diff = diff_packs(old, new)
        assert not diff.has_changes
        assert diff.summary() == "no rule changes"

    def test_diff_packs_added_rule(self, tmp_path):
        from promptgenie.core.pack_signing import diff_packs

        old = tmp_path / "old.yaml"
        new = tmp_path / "new.yaml"
        old.write_text("version: '1.0'\nrules:\n  - id: RULE_001\n    pattern: foo\n")
        new.write_text(
            "version: '1.1'\nrules:\n  - id: RULE_001\n    pattern: foo\n  - id: RULE_002\n    pattern: bar\n"
        )
        diff = diff_packs(old, new)
        assert "RULE_002" in diff.added_rules
        assert diff.has_changes

    def test_diff_packs_removed_rule(self, tmp_path):
        from promptgenie.core.pack_signing import diff_packs

        old = tmp_path / "old.yaml"
        new = tmp_path / "new.yaml"
        old.write_text(
            "version: '1.0'\nrules:\n  - id: RULE_001\n    pattern: foo\n  - id: RULE_002\n    pattern: bar\n"
        )
        new.write_text("version: '1.1'\nrules:\n  - id: RULE_001\n    pattern: foo\n")
        diff = diff_packs(old, new)
        assert "RULE_002" in diff.removed_rules

    def test_diff_packs_modified_rule(self, tmp_path):
        from promptgenie.core.pack_signing import diff_packs

        old = tmp_path / "old.yaml"
        new = tmp_path / "new.yaml"
        old.write_text("version: '1.0'\nrules:\n  - id: RULE_001\n    pattern: old-pattern\n")
        new.write_text("version: '1.1'\nrules:\n  - id: RULE_001\n    pattern: new-pattern\n")
        diff = diff_packs(old, new)
        assert "RULE_001" in diff.modified_rules

    def test_promote_pack(self, tmp_path):
        from promptgenie.core.pack_signing import promote_pack

        dev_dir = tmp_path / "dev"
        dev_dir.mkdir(parents=True)
        pack_file = dev_dir / "my-pack.yaml"
        pack_file.write_text("name: MyPack\nrules: []\n")
        base = tmp_path
        promoted = promote_pack("my-pack", "dev", "staging", base_dir=base)
        assert promoted.exists()
        assert "staging" in str(promoted)

    def test_promote_pack_missing_raises(self, tmp_path):
        from promptgenie.core.pack_signing import promote_pack

        with pytest.raises(FileNotFoundError):
            promote_pack("nonexistent", "dev", "prod", base_dir=tmp_path)

    def test_pack_unit_test_pass(self, tmp_path):
        from promptgenie.core.pack_signing import run_pack_unit_test

        pack = tmp_path / "pack.yaml"
        pack.write_text(
            textwrap.dedent("""\
            name: test-pack
            version: "1.0"
            rules:
              - id: SECRET_001
                category: secrets
                pattern: "sk-[a-z0-9]{20,}"
                risk: HIGH
                confidence: HIGH
                message: "API key found"
                recommendation: "Remove key"
        """)
        )
        tests = tmp_path / "tests.yaml"
        tests.write_text(
            textwrap.dedent("""\
            cases:
              - name: detects key
                input: "use this key: sk-abcdefghijklmnopqrstuvwxyz123"
                expected_rules:
                  - SECRET_001
              - name: no match
                input: "hello world"
                expected_rules: []
        """)
        )
        result = run_pack_unit_test(pack, tests)
        assert result.total == 2

    def test_pack_diff_cli(self, tmp_path):
        old = tmp_path / "old.yaml"
        new = tmp_path / "new.yaml"
        old.write_text("version: '1.0'\nrules:\n  - id: RULE_001\n    pattern: foo\n")
        new.write_text(
            "version: '1.1'\nrules:\n  - id: RULE_001\n    pattern: foo\n  - id: RULE_002\n    pattern: bar\n"
        )
        result = invoke("pack", "diff", str(old), str(new))
        assert result.exit_code == 0

    def test_pack_test_cli(self, tmp_path):
        pack = tmp_path / "pack.yaml"
        pack.write_text(
            "name: p\nrules:\n  - id: R1\n    pattern: secret\n    category: secrets\n    risk: HIGH\n    confidence: HIGH\n    message: m\n    recommendation: r\n"
        )
        tests = tmp_path / "tests.yaml"
        tests.write_text("cases:\n  - name: clean\n    input: hello\n    expected_rules: []\n")
        result = invoke("pack", "test", str(pack), str(tests))
        assert result.exit_code == 0


# ===========================================================================
# CLI wiring smoke tests (Phase 5 commands are registered)
# ===========================================================================


class TestCliWiring:
    def test_plugin_in_cli(self):
        result = invoke("plugin", "--help")
        assert result.exit_code == 0

    def test_template_in_cli(self):
        result = invoke("template", "--help")
        assert result.exit_code == 0

    def test_history_in_cli(self):
        result = invoke("history", "--help")
        assert result.exit_code == 0

    def test_watch_in_cli(self):
        result = invoke("watch", "--help")
        assert result.exit_code == 0

    def test_lock_in_cli(self):
        result = invoke("lock", "--help")
        assert result.exit_code == 0

    def test_tui_in_cli(self):
        result = invoke("tui", "--help")
        assert result.exit_code == 0

    def test_wizard_in_cli(self):
        result = invoke("wizard", "--help")
        assert result.exit_code == 0

    def test_palette_in_cli(self):
        result = invoke("palette", "--help")
        assert result.exit_code == 0
