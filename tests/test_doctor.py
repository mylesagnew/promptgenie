"""Tests for promptgenie.commands.doctor — self-check command."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from promptgenie.cli import cli
from promptgenie.commands.doctor import (
    CheckResult,
    run_doctor,
    _check_python_version,
    _check_package_version,
    _check_extra,
)


class TestCheckResult:
    def test_passed_check(self):
        r = CheckResult(label="test", passed=True, detail="all good")
        assert r.passed is True
        assert r.warning is False

    def test_warning_check(self):
        r = CheckResult(label="test", passed=False, warning=True, detail="optional")
        assert r.passed is False
        assert r.warning is True

    def test_remediation_field(self):
        r = CheckResult(label="test", passed=False, remediation="pip install x")
        assert r.remediation == "pip install x"


class TestIndividualChecks:
    def test_python_version_passes_on_current(self):
        result = _check_python_version()
        import sys
        # Current Python is ≥ 3.10 (required by the project)
        assert result.passed is True

    def test_package_version_passes(self):
        result = _check_package_version()
        assert result.passed is True
        assert "1." in result.detail  # version starts with 1.

    def test_extra_installed_for_existing_package(self):
        result = _check_extra("json", "json-stdlib", "pip install json")
        assert result.passed is True  # json is always available

    def test_extra_not_installed_for_fake_package(self):
        result = _check_extra("_definitely_not_installed_xyz", "fake", "pip install fake")
        assert result.passed is False
        assert result.warning is True  # extras are warnings, not hard failures


class TestRunDoctor:
    def test_returns_groups(self):
        groups = run_doctor()
        assert len(groups) > 0

    def test_all_groups_have_results(self):
        groups = run_doctor()
        for group in groups:
            assert len(group.results) > 0

    def test_runtime_group_present(self):
        groups = run_doctor()
        titles = [g.title for g in groups]
        assert "Runtime" in titles

    def test_configuration_group_present(self):
        groups = run_doctor()
        titles = [g.title for g in groups]
        assert "Configuration" in titles


class TestDoctorCommand:
    def setup_method(self):
        self.runner = CliRunner()

    def test_doctor_exits_0_or_1(self):
        result = self.runner.invoke(cli, ["doctor"])
        assert result.exit_code in (0, 1)

    def test_doctor_json_format(self):
        import json
        result = self.runner.invoke(cli, ["doctor", "--format", "json"])
        assert result.exit_code in (0, 1)
        data = json.loads(result.output)
        assert data["command"] == "doctor"
        assert data["schema_version"] == "1.0"
        assert "groups" in data
        assert "passed" in data

    def test_doctor_json_has_version(self):
        import json
        result = self.runner.invoke(cli, ["doctor", "--format", "json"])
        data = json.loads(result.output)
        assert "version" in data
        assert data["version"] != "unknown"

    def test_doctor_json_failure_count_non_negative(self):
        import json
        result = self.runner.invoke(cli, ["doctor", "--format", "json"])
        data = json.loads(result.output)
        assert data["failure_count"] >= 0
        assert data["warning_count"] >= 0
