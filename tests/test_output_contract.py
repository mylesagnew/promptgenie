"""Tests for structured output contracts — core validator/repair + CLI + run wiring."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from promptgenie.cli import cli
from promptgenie.core.output_contract import (
    OutputContractError,
    RepairResult,
    _builtin_validate,
    load_schema,
    parse_payload,
    repair_payload,
    validate_payload,
)

SCHEMA = {
    "type": "object",
    "required": ["status", "count"],
    "properties": {
        "status": {"type": "string", "enum": ["ok", "fail"]},
        "count": {"type": "integer"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}


def _builtin_errors(obj, schema):
    errors: list[str] = []
    _builtin_validate(obj, schema, "", errors)
    return errors


# ---------------------------------------------------------------------------
# parse_payload
# ---------------------------------------------------------------------------


class TestParsePayload:
    def test_direct_json(self):
        obj, err = parse_payload('{"a": 1}', "json")
        assert err is None and obj == {"a": 1}

    def test_fenced_json(self):
        text = "Here you go:\n```json\n{\"a\": 1}\n```\n"
        obj, err = parse_payload(text, "json")
        assert err is None and obj == {"a": 1}

    def test_invalid_json_reports_error(self):
        obj, err = parse_payload("not json at all", "json")
        assert obj is None and err is not None

    def test_yaml(self):
        obj, err = parse_payload("a: 1\nb: two\n", "yaml")
        assert err is None and obj == {"a": 1, "b": "two"}

    def test_text_passthrough(self):
        obj, err = parse_payload("just text", "text")
        assert err is None and obj == "just text"


# ---------------------------------------------------------------------------
# validate_payload — public API (jsonschema if present, else builtin)
# ---------------------------------------------------------------------------


class TestValidatePayload:
    def test_valid(self):
        assert validate_payload({"status": "ok", "count": 3}, SCHEMA) == []

    def test_missing_required(self):
        errors = validate_payload({"status": "ok"}, SCHEMA)
        assert errors and any("count" in e for e in errors)

    def test_wrong_type(self):
        errors = validate_payload({"status": "ok", "count": "3"}, SCHEMA)
        assert errors

    def test_enum_violation(self):
        errors = validate_payload({"status": "nope", "count": 1}, SCHEMA)
        assert errors


# ---------------------------------------------------------------------------
# Built-in validator — exercised directly (dependency-free path)
# ---------------------------------------------------------------------------


class TestBuiltinValidator:
    def test_valid(self):
        assert _builtin_errors({"status": "ok", "count": 3}, SCHEMA) == []

    def test_missing_required(self):
        assert any("required" in e for e in _builtin_errors({"status": "ok"}, SCHEMA))

    def test_type_mismatch(self):
        assert any("expected type" in e for e in _builtin_errors({"status": 1, "count": 1}, SCHEMA))

    def test_enum(self):
        errors = _builtin_errors({"status": "maybe", "count": 1}, SCHEMA)
        assert any("not one of" in e for e in errors)

    def test_additional_property_rejected(self):
        errors = _builtin_errors({"status": "ok", "count": 1, "extra": 9}, SCHEMA)
        assert any("additional property" in e for e in errors)

    def test_array_item_type(self):
        errors = _builtin_errors({"status": "ok", "count": 1, "tags": ["a", 2]}, SCHEMA)
        assert any("tags[1]" in e for e in errors)

    def test_numeric_bounds(self):
        schema = {"type": "integer", "minimum": 0, "maximum": 10}
        assert _builtin_errors(5, schema) == []
        assert _builtin_errors(20, schema)

    def test_string_pattern(self):
        schema = {"type": "string", "pattern": r"^\d{3}$"}
        assert _builtin_errors("123", schema) == []
        assert _builtin_errors("abc", schema)


# ---------------------------------------------------------------------------
# repair_payload
# ---------------------------------------------------------------------------


class TestRepairPayload:
    def test_coerce_string_to_integer(self):
        res = repair_payload('{"status": "ok", "count": "7"}', SCHEMA)
        assert res.valid
        assert res.obj["count"] == 7
        assert any("integer" in r for r in res.repairs)

    def test_fill_missing_required(self):
        res = repair_payload('{"status": "ok"}', SCHEMA)
        assert "count" in res.obj
        assert any("missing required" in r for r in res.repairs)

    def test_extract_json_from_prose(self):
        text = 'The model says: {"status": "ok", "count": 2} — done.'
        res = repair_payload(text, SCHEMA)
        assert res.valid
        assert any("extracted JSON" in r for r in res.repairs)

    def test_unparseable_returns_no_object(self):
        res = repair_payload("absolutely not json", SCHEMA)
        assert isinstance(res, RepairResult)
        assert res.obj is None and not res.valid

    def test_coerce_boolean(self):
        schema = {"type": "object", "properties": {"flag": {"type": "boolean"}}}
        res = repair_payload('{"flag": "true"}', schema)
        assert res.obj["flag"] is True

    def test_default_used_for_missing_field(self):
        schema = {
            "type": "object",
            "required": ["mode"],
            "properties": {"mode": {"type": "string", "default": "auto"}},
        }
        res = repair_payload("{}", schema)
        assert res.obj["mode"] == "auto"
        assert res.valid


# ---------------------------------------------------------------------------
# load_schema
# ---------------------------------------------------------------------------


class TestLoadSchema:
    def test_load_json(self, tmp_path):
        p = tmp_path / "s.json"
        p.write_text(json.dumps(SCHEMA))
        assert load_schema(p)["type"] == "object"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(OutputContractError, match="not found"):
            load_schema(tmp_path / "nope.json")


# ---------------------------------------------------------------------------
# CLI — validate-output
# ---------------------------------------------------------------------------


def _write_schema(tmp_path):
    p = tmp_path / "schema.json"
    p.write_text(json.dumps(SCHEMA))
    return p


class TestValidateOutputCLI:
    def test_valid_exit_0(self, tmp_path):
        schema = _write_schema(tmp_path)
        resp = tmp_path / "r.json"
        resp.write_text('{"status": "ok", "count": 1}')
        res = CliRunner().invoke(cli, ["validate-output", str(resp), "--schema", str(schema)])
        assert res.exit_code == 0

    def test_invalid_exit_1(self, tmp_path):
        schema = _write_schema(tmp_path)
        resp = tmp_path / "r.json"
        resp.write_text('{"status": "nope"}')
        res = CliRunner().invoke(cli, ["validate-output", str(resp), "--schema", str(schema)])
        assert res.exit_code == 1

    def test_json_report(self, tmp_path):
        schema = _write_schema(tmp_path)
        resp = tmp_path / "r.json"
        resp.write_text('{"status": "ok", "count": 1}')
        res = CliRunner().invoke(
            cli, ["validate-output", str(resp), "--schema", str(schema), "--format", "json"]
        )
        data = json.loads(res.stdout)
        assert data["valid"] is True and data["errors"] == []

    def test_parse_error_exit_2(self, tmp_path):
        schema = _write_schema(tmp_path)
        resp = tmp_path / "r.json"
        resp.write_text("not json")
        res = CliRunner().invoke(cli, ["validate-output", str(resp), "--schema", str(schema)])
        assert res.exit_code == 2


# ---------------------------------------------------------------------------
# CLI — output repair
# ---------------------------------------------------------------------------


class TestOutputRepairCLI:
    def test_repair_to_stdout(self, tmp_path):
        schema = _write_schema(tmp_path)
        resp = tmp_path / "r.txt"
        resp.write_text('result: {"status": "ok", "count": "9"}')
        res = CliRunner().invoke(cli, ["output", "repair", str(resp), "--schema", str(schema)])
        assert res.exit_code == 0
        assert '"count": 9' in res.stdout

    def test_repair_to_out_file(self, tmp_path):
        schema = _write_schema(tmp_path)
        resp = tmp_path / "r.txt"
        resp.write_text('{"status": "ok"}')
        dest = tmp_path / "fixed.json"
        res = CliRunner().invoke(
            cli,
            ["output", "repair", str(resp), "--schema", str(schema), "--out", str(dest)],
        )
        assert res.exit_code == 0
        assert dest.exists()
        assert json.loads(dest.read_text())["count"] == 0  # filled default

    def test_repair_json_report(self, tmp_path):
        schema = _write_schema(tmp_path)
        resp = tmp_path / "r.txt"
        resp.write_text('{"status": "ok", "count": "4"}')
        res = CliRunner().invoke(
            cli, ["output", "repair", str(resp), "--schema", str(schema), "--format", "json"]
        )
        data = json.loads(res.stdout)
        assert data["valid"] is True
        assert data["repaired"]["count"] == 4


# ---------------------------------------------------------------------------
# run wiring — _validate_output_contract
# ---------------------------------------------------------------------------


class TestRunOutputContract:
    def _spec(self, fmt="json", schema=None):
        from promptgenie.core.spec import OutputContract, PromptSpec

        return PromptSpec(
            version=1,
            name="t",
            target="openai-gpt",
            output_contract=OutputContract(format=fmt, schema=schema or {}),
        )

    def test_no_schema_is_noop(self):
        from promptgenie.commands.run import _validate_output_contract

        # Should not raise even though the response is junk — no contract set.
        _validate_output_contract(
            spec=self._spec(schema={}),
            response="anything",
            schema_path=None,
            output_mode=None,
            ndjson_mode=False,
        )

    def test_valid_response_passes(self):
        from promptgenie.commands.run import _validate_output_contract

        _validate_output_contract(
            spec=self._spec(schema=SCHEMA),
            response='{"status": "ok", "count": 1}',
            schema_path=None,
            output_mode=None,
            ndjson_mode=False,
        )

    def test_invalid_response_exits_failure(self):
        from promptgenie.commands.run import _validate_output_contract

        with pytest.raises(SystemExit) as exc:
            _validate_output_contract(
                spec=self._spec(schema=SCHEMA),
                response='{"status": "nope"}',
                schema_path=None,
                output_mode=None,
                ndjson_mode=False,
            )
        assert exc.value.code == 1

    def test_schema_path_override(self, tmp_path):
        from promptgenie.commands.run import _validate_output_contract

        schema = _write_schema(tmp_path)
        with pytest.raises(SystemExit):
            _validate_output_contract(
                spec=self._spec(schema={}),
                response='{"bad": true}',
                schema_path=str(schema),
                output_mode="json",
                ndjson_mode=False,
            )
