"""Regression tests for the 2026-10 security-audit leads (Cloudflare security-audit
skill, quick-profile run against 9fcdb6e).

Each class pins one fix: the trust gate on ``spec render --show-context``, the
``cmd`` allowlist, remote pack-id containment, registry token/origin binding,
signed-reference binding, ``secret_vars`` trust, consent-prompt escaping, the
URL fail-closed path, ``probe_provider`` base_url validation, key-shape scanner
rules, and the ReDoS pattern guard.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from click.testing import CliRunner
from rich.console import Console

from promptgenie.core import registry, registry_auth
from promptgenie.core.context_builder import SecurityError, _validate_cmd_allowed

# ---------------------------------------------------------------------------
# spec render --show-context must apply the spec trust gate
# ---------------------------------------------------------------------------


class TestSpecRenderTrustGate:
    @pytest.fixture(autouse=True)
    def _isolate_trust(self, tmp_path, monkeypatch):
        from promptgenie.core import trust

        monkeypatch.setattr(trust, "_TRUST_FILE", tmp_path / "trust.json")

    def _spec(self, tmp_path: Path) -> Path:
        spec = tmp_path / "s.promptgenie.yaml"
        spec.write_text(
            "version: 1\nname: s\ntarget: claude\nprompt: hi\n"
            "context:\n  - {type: cmd, command: 'echo pg-render-marker'}\n",
            encoding="utf-8",
        )
        return spec

    def test_untrusted_spec_is_refused_non_interactively(self, tmp_path):
        from promptgenie.cli import cli

        res = CliRunner().invoke(
            cli, ["spec", "render", str(self._spec(tmp_path)), "--show-context", "--no-input"]
        )
        assert res.exit_code != 0
        assert "pg-render-marker" not in res.output

    def test_trust_flag_allows_context(self, tmp_path):
        from promptgenie.cli import cli

        res = CliRunner().invoke(
            cli,
            [
                "spec",
                "render",
                str(self._spec(tmp_path)),
                "--show-context",
                "--no-input",
                "--trust",
            ],
        )
        assert res.exit_code == 0, res.output
        assert "pg-render-marker" in res.output

    def test_render_without_show_context_needs_no_trust(self, tmp_path):
        from promptgenie.cli import cli

        res = CliRunner().invoke(cli, ["spec", "render", str(self._spec(tmp_path)), "--no-input"])
        assert res.exit_code == 0, res.output


# ---------------------------------------------------------------------------
# cmd allowlist: bare names only, no exec/write-capable options
# ---------------------------------------------------------------------------


class TestCmdAllowlistHardening:
    @pytest.mark.parametrize(
        "command",
        [
            "./tools/cat README.md",
            "/tmp/evil/git status",
            "bin/grep x file",
            "git --git-dir=evil --work-tree=. status",
            "git -C other status",
            "git --config-env=diff.external=SHELL diff",
            "git diff --no-index --output=out.txt a b",
            "git log --output=out.txt",
            "git diff --ext-diff",
            "git show --textconv HEAD",
            "git tag v9.9.9",
            "git branch -D main",
            "git remote add evil https://example.invalid/x.git",
            "sort -o out.txt in.txt",
            "sort -ro out.txt in.txt",
            "sort --output=out.txt in.txt",
            "sort --compress-program=./payload -S 1K big.txt",
            "uniq in.txt out.txt",
        ],
    )
    def test_rejected(self, command):
        with pytest.raises(SecurityError):
            _validate_cmd_allowed(command)

    @pytest.mark.parametrize(
        "command",
        [
            "git status --short",
            "git log --oneline -5",
            "git diff --staged",
            "git branch -a",
            "git tag -l",
            "git remote -v",
            "sort -r names.txt",
            "uniq -d names.txt",
            "uniq -f 1 names.txt",
            "cat README.md",
        ],
    )
    def test_allowed(self, command):
        assert _validate_cmd_allowed(command)


# ---------------------------------------------------------------------------
# Remote pack-index ids must not escape the install directory
# ---------------------------------------------------------------------------


class TestPackIdContainment:
    @pytest.mark.parametrize("bad_id", ["../../../.promptgenie", "/abs/target", "a/b", "..\\x"])
    def test_install_pack_rejects_traversal(self, tmp_path, bad_id):
        entry = registry.RegistryEntry(
            id=bad_id,
            name="x",
            version="1",
            description="",
            type="rules",
            url="https://example.invalid/p.yaml",
            sha256="0" * 64,
        )
        install = tmp_path / "home" / ".promptgenie" / "registry" / "packs"
        with (
            patch.object(registry, "_download_to_temp") as dl,
            pytest.raises(ValueError, match="Unsafe or invalid pack id"),
        ):
            registry.install_pack(entry, install_dir=install)
        dl.assert_not_called()

    def test_update_registry_records_error_and_writes_nothing_outside(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        install = home / ".promptgenie" / "registry" / "packs"
        monkeypatch.setattr(registry, "CACHED_INDEX_PATH", home / ".promptgenie" / "index.yaml")
        body = b"scanner: {disabled_rules: [DUMMY-MARKER]}\n"
        entries = [
            registry.RegistryEntry(
                id="../../../.promptgenie",
                name="x",
                version="1",
                description="",
                type="rules",
                url="https://example.invalid/p.yaml",
                sha256=hashlib.sha256(body).hexdigest(),
            )
        ]

        def fake_download(url, timeout=30):
            p = tmp_path / "dl.tmp"
            p.write_bytes(body)
            return p

        monkeypatch.setattr(registry, "fetch_remote_index", lambda url, timeout=10: entries)
        monkeypatch.setattr(registry, "_download_to_temp", fake_download)
        result = registry.update_registry(
            url="https://example.invalid/index.yaml", install_dir=install
        )
        assert result.errors and "Unsafe or invalid pack id" in result.errors[0]
        assert not (home / ".promptgenie.yaml").exists()


# ---------------------------------------------------------------------------
# Registry token: bound to its host; never sent to another upload origin
# ---------------------------------------------------------------------------


class TestRegistryUploadOrigin:
    def _store(self, location: str, seen: list[httpx.Request]):
        from promptgenie.core.registry_remote import RemoteRegistryStore

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            if request.method == "HEAD":
                return httpx.Response(404)
            if request.method == "POST":
                return httpx.Response(202, headers={"Location": location})
            return httpx.Response(201)

        client = httpx.Client(
            base_url="https://registry.example",
            headers={"Authorization": "Bearer dummy-marker"},
            transport=httpx.MockTransport(handler),
        )
        return RemoteRegistryStore(
            "https://registry.example", "org/x", token="dummy-marker", client=client
        )

    @pytest.mark.parametrize(
        "location",
        ["http://third.example/up", "https://third.example/up", "http://registry.example/up"],
    )
    def test_cross_origin_location_refused(self, location):
        from promptgenie.core.registry_store import RegistryError

        seen: list[httpx.Request] = []
        store = self._store(location, seen)
        with pytest.raises(RegistryError, match="different origin"):
            store.put_blob(b"x", media_type="application/octet-stream")
        assert all(r.url.host == "registry.example" and r.url.scheme == "https" for r in seen)

    @pytest.mark.parametrize(
        "location",
        ["/v2/org/x/blobs/uploads/u1", "https://registry.example/v2/org/x/blobs/uploads/u1?s=1"],
    )
    def test_same_origin_location_used(self, location):
        seen: list[httpx.Request] = []
        self._store(location, seen).put_blob(b"x", media_type="application/octet-stream")
        put = [r for r in seen if r.method == "PUT"][0]
        assert put.url.host == "registry.example"
        assert put.url.path == "/v2/org/x/blobs/uploads/u1"

    def test_env_token_not_returned_for_unbound_host(self, monkeypatch):
        monkeypatch.setattr(registry_auth, "_keyring", lambda: None)
        monkeypatch.setattr(registry_auth, "_AUTH_FILE", Path("/nonexistent/auth.json"))
        monkeypatch.setenv(registry_auth.ENV_TOKEN, "envtok")
        monkeypatch.setenv(registry_auth.ENV_TOKEN_HOST, "ghcr.io")
        assert registry_auth.get_token("other.example") is None


# ---------------------------------------------------------------------------
# --require-signed binds the signed name/tag to the requested reference
# ---------------------------------------------------------------------------


class TestSignedReferenceBinding:
    def _ref(self, s: str):
        from promptgenie.core.registry_store import Reference

        return Reference.parse(s)

    def test_matching_reference_ok(self):
        from promptgenie.commands.registry_cmd import _signed_reference_mismatch

        ann = {"org.promptgenie.name": "a", "org.promptgenie.tag": "v2"}
        assert _signed_reference_mismatch(ann, self._ref("a:v2")) is None

    def test_other_repository_rejected(self):
        from promptgenie.commands.registry_cmd import _signed_reference_mismatch

        ann = {"org.promptgenie.name": "b", "org.promptgenie.tag": "v1"}
        assert "repository" in (_signed_reference_mismatch(ann, self._ref("a:v1")) or "")

    def test_rollback_to_other_tag_rejected(self):
        from promptgenie.commands.registry_cmd import _signed_reference_mismatch

        ann = {"org.promptgenie.name": "a", "org.promptgenie.tag": "v1"}
        assert "tag" in (_signed_reference_mismatch(ann, self._ref("a:v2")) or "")

    def test_missing_annotations_fail_closed(self):
        from promptgenie.commands.registry_cmd import _signed_reference_mismatch

        assert _signed_reference_mismatch({}, self._ref("a:v1")) is not None


# ---------------------------------------------------------------------------
# secret_vars (from_env) need trust and are shown in the trust prompt
# ---------------------------------------------------------------------------


class TestSecretVarsTrust:
    def _spec(self, tmp_path: Path):
        from promptgenie.core.spec import load_spec

        p = tmp_path / "s.promptgenie.yaml"
        p.write_text(
            "version: 1\nname: s\ntarget: claude\nprompt: 'value {{k}}'\n"
            "vars:\n  k: {from_env: ANTHROPIC_API_KEY}\n",
            encoding="utf-8",
        )
        return load_spec(str(p))

    def test_requires_trust(self, tmp_path):
        from promptgenie.core.trust import spec_requires_trust

        assert spec_requires_trust(self._spec(tmp_path)) is True

    def test_listed_in_trust_prompt(self, tmp_path):
        from promptgenie.commands.run import _describe_sources

        lines = _describe_sources(self._spec(tmp_path))
        assert any("ANTHROPIC_API_KEY" in line for line in lines)


# ---------------------------------------------------------------------------
# Consent prompts render untrusted text literally
# ---------------------------------------------------------------------------


class TestConsentPromptEscaping:
    def _render(self, text: str) -> tuple[str, str]:
        """Return (plain text, raw ANSI) as the trust prompt would print it."""
        buf = io.StringIO()
        con = Console(file=buf, force_terminal=True, width=500, highlight=False, record=True)
        con.print(f"[yellow]{text}[/yellow]")
        return con.export_text(), buf.getvalue()

    def test_makefile_commands_escaped(self):
        from promptgenie.commands.make_cmd import _describe_commands
        from promptgenie.core.make import Makefile, MakeTask

        cmd = "promptgenie lint a.md; : [conceal]; echo PWNED #[/conceal]"
        mf = Makefile(tasks={"lint": MakeTask(name="lint", run=[cmd])})
        plain, ansi = self._render(_describe_commands(mf)[0])
        assert cmd in plain and "[lint]" in plain
        assert "\x1b[8m" not in ansi  # no SGR 8 (conceal)

    def test_control_characters_made_visible(self):
        from promptgenie.renderers.rich import escape_markup

        assert escape_markup("a\x1b[8mb\rc") == "a\\x1b[8mb\\x0dc"


# ---------------------------------------------------------------------------
# URL context: no unpinned fallback; probe_provider validates base_url
# ---------------------------------------------------------------------------


class TestProbeProviderBaseUrl:
    def test_cleartext_remote_rejected_without_request(self, monkeypatch):
        import asyncio

        from promptgenie.core import providers

        cfg = providers.ProviderConfig(
            name="p",
            type="openai_compat",
            base_url="http://10.0.0.2:8080/v1",
            api_key_env="DUMMY_KEY",
        )
        monkeypatch.setenv("DUMMY_KEY", "dummy-not-a-secret")
        monkeypatch.setattr(providers, "load_providers_config", lambda: {"p": cfg})
        with patch("httpx.AsyncClient") as client:
            ok, msg = asyncio.run(providers.probe_provider("p"))
        assert ok is False and "cleartext" in msg
        client.assert_not_called()


# ---------------------------------------------------------------------------
# Scanner: hyphenated sk- keys and fine-grained GitHub PATs are detected
# ---------------------------------------------------------------------------


class TestKeyShapeRules:
    @pytest.mark.parametrize(
        "value",
        ["sk-ant-api03-" + "A" * 80, "sk-proj-" + "B" * 100, "github_pat_" + "C" * 82],
    )
    def test_detected_as_critical_secret(self, value):
        from promptgenie.core.scanner import scan

        result = scan(f"value {value}")
        assert any(
            f.code.startswith("SEC_SECRET") and f.risk == "CRITICAL" for f in result.findings
        )


# ---------------------------------------------------------------------------
# ReDoS guard: nested repeats are rejected even through inner groups
# ---------------------------------------------------------------------------


class TestValidatePattern:
    @pytest.mark.parametrize("pattern", ["((a)+)+$", "(?:(\\w+)\\s?)*$", "(a+)+", "x" * 501])
    def test_rejected(self, pattern):
        from promptgenie.core.scanner import validate_pattern

        with pytest.raises(ValueError):
            validate_pattern(pattern, "T")

    @pytest.mark.parametrize("pattern", ["\\w+", "(foo|bar)+", "(ab)?c+", "api[_-]?key\\s*[:=]"])
    def test_accepted(self, pattern):
        from promptgenie.core.scanner import validate_pattern

        validate_pattern(pattern, "T")
