# Contributing to PromptGenie

Thanks for taking the time. Contributions of all sizes are welcome — bug reports, new lint rules, new profiles, new templates, documentation fixes, and code.

---

## Table of contents

- [Getting started](#getting-started)
- [Running tests](#running-tests)
- [Code style](#code-style)
- [How to add a lint rule](#how-to-add-a-lint-rule)
- [How to add a scanner rule](#how-to-add-a-scanner-rule)
- [How to add a compression technique](#how-to-add-a-compression-technique)
- [How to extend the workspace schema](#how-to-extend-the-workspace-schema)
- [Profile schema reference](#profile-schema-reference)
- [Template schema reference](#template-schema-reference)
- [How to add a profile](#how-to-add-a-profile)
- [How to add a template](#how-to-add-a-template)
- [Submitting a pull request](#submitting-a-pull-request)
- [Reporting a bug](#reporting-a-bug)

---

## Getting started

```bash
git clone https://github.com/mylesagnew/promptgenie.git
cd promptgenie
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

This installs the CLI in editable mode plus the full dev dependency set: pytest, ruff, bandit, pip-audit, mypy, build, and twine.

Verify the install:

```bash
promptgenie --version
promptgenie list-targets
```

---

## Running tests

```bash
# Full test suite
pytest tests/

# Single module
pytest tests/test_linter.py -v

# With coverage
pytest tests/ --cov=promptgenie --cov-report=term-missing
```

CI runs the suite against Python 3.10, 3.11, and 3.12. Write tests for Python 3.10-compatible syntax.

---

## Code style

```bash
# Check
ruff check promptgenie/

# Fix automatically
ruff check --fix promptgenie/

# Format check
ruff format --check promptgenie/

# Format
ruff format promptgenie/
```

Key conventions:

- Line length: 100 characters (configured in `pyproject.toml`)
- No comments that explain *what* the code does — only *why* (non-obvious constraints, workarounds, invariants)
- No multi-line docstrings on internal functions
- Prefer `dataclass` for structured return types; avoid plain dicts in public APIs
- Type annotations on all public functions

Security checks:

```bash
bandit -r promptgenie/ -ll
pip-audit --skip-editable
```

`bandit` skips `B101` (assert in tests). If you add a new `# nosec` comment, explain why in the PR.

---

## How to add a lint rule

Lint rules live in [`promptgenie/core/linter.py`](promptgenie/core/linter.py). There are three ways to add one.

### 1. Vague verb

Add the verb string to `VAGUE_VERBS`:

```python
VAGUE_VERBS = [
    "help", "fix", "improve", ...,
    "your new verb here",
]
```

The linter reports one `TASK_001` issue per prompt (not per match) to avoid noise.

### 2. Agentic risk pattern

Add a 4-tuple to `AGENTIC_RISK_PATTERNS`:

```python
AGENTIC_RISK_PATTERNS = [
    ...
    (r"your regex here", "HIGH", "AGENT_NNN", "Human-readable message."),
]
```

| Field | Type | Notes |
|---|---|---|
| regex | `str` | Matched case-insensitively against the full prompt |
| severity | `"HIGH"` \| `"MEDIUM"` \| `"LOW"` | HIGH exits CI with code 1 |
| code | `str` | Unique `AGENT_NNN` identifier — check existing codes before picking one |
| message | `str` | Short description shown to the user |

A suggestion is auto-applied ("Add explicit constraints and approval gates."). If you need a custom suggestion, extend `lint()` directly instead of using the pattern list.

### 3. Missing section check

Add a 5-tuple to `MISSING_SECTIONS`:

```python
MISSING_SECTIONS = [
    ...
    ("section label", ["keyword1", "keyword2"], "LOW", "STRUCT_NNN", "Human-readable message."),
]
```

| Field | Type | Notes |
|---|---|---|
| section label | `str` | Human-readable name used in the suggestion text |
| keywords | `list[str]` | If *any* keyword is found in the lowercased prompt, the check passes |
| severity | `Severity` | LOW for structure, MEDIUM for agentic safety |
| code | `str` | Unique `STRUCT_NNN` identifier |
| message | `str` | Shown when the section is missing |

Missing section checks only fire when the prompt looks agentic or is longer than 200 characters.

### Writing lint rule tests

Add a test to `tests/test_linter.py`. Use `pytest.mark.parametrize` where you are testing multiple variants of a pattern.

```python
def test_my_new_rule_fires():
    result = lint("a prompt that triggers the rule")
    codes = [i.code for i in result.issues]
    assert "AGENT_NNN" in codes

def test_my_new_rule_does_not_fire_on_safe_prompt():
    result = lint("a prompt that should be clean")
    codes = [i.code for i in result.issues]
    assert "AGENT_NNN" not in codes
```

Both a trigger case and a clean case are required for every new rule.

---

## How to add a scanner rule

Security scanner rules live in [`promptgenie/core/scanner.py`](promptgenie/core/scanner.py). There are four rule groups.

### Secret pattern

Add a 2-tuple to `SECRET_PATTERNS`:

```python
SECRET_PATTERNS = [
    ...
    (r"your_regex_here", "Human-readable label"),
]
```

All secret matches are reported as `CRITICAL` with code `SEC_SECRET`. The scanner reports the **label** (e.g. "Stripe secret key"), never the matched value.

### Prompt injection pattern

Add a 4-tuple to `INJECTION_PATTERNS`:

```python
INJECTION_PATTERNS = [
    ...
    (r"your regex", "HIGH", "SEC_NNN", "Short message."),
]
```

### Agent permission pattern

Add a 4-tuple to `AGENT_PERMISSION_PATTERNS`:

```python
AGENT_PERMISSION_PATTERNS = [
    ...
    (r"your regex", "CRITICAL", "PERM_NNN", "Short message."),
]
```

### RAG / data handling pattern

Add a 4-tuple to `RAG_PATTERNS`:

```python
RAG_PATTERNS = [
    ...
    (r"your regex", "HIGH", "RAG_NNN", "Short message."),
]
```

### Risk levels

| Level | Meaning | CI behaviour |
|---|---|---|
| `CRITICAL` | Active exploit pattern or credential leak | Exits 1 |
| `HIGH` | Serious risk, likely unintentional | Exits 1 |
| `MEDIUM` | Suspicious pattern, may be intentional | Reported, does not fail CI |
| `LOW` | Informational | Reported only |

### Writing scanner tests

```python
def test_my_rule_fires(fixture_file):
    result = scan(Path(fixture_file).read_text())
    codes = [f.code for f in result.findings]
    assert "SEC_NNN" in codes

def test_my_rule_clean():
    result = scan("a completely benign prompt")
    assert result.risk_level == "LOW"
```

Test fixtures live in `tests/fixtures/`. Add a new `.md` file there if your rule needs a dedicated fixture.

---

## How to add a compression technique

Token compression techniques live in [`promptgenie/core/compressor.py`](promptgenie/core/compressor.py) and power `promptgenie compress` / `promptgenie optimize`. Each technique is a pure function that takes text and returns `(new_text, occurrences)`.

### 1. Write the technique function

```python
def _my_technique(text: str) -> tuple[str, int]:
    new, n = _SOME_RE.subn("", text)
    return new, n
```

If the transform could corrupt code (collapsing spaces, stripping symbols), wrap it with `_apply_to_prose()` so fenced ```` ``` ```` code blocks are left untouched:

```python
def _my_technique(text: str) -> tuple[str, int]:
    return _apply_to_prose(text, lambda seg: _SOME_RE.subn("", seg))
```

The second return value (`occurrences`) is the number of edits made — return `0` when nothing changed so the technique is reported as not applied.

### 2. Register it

Add a `Technique` to `_TECHNIQUE_LIST`:

```python
Technique("my-technique", _my_technique, aggressive=False,
          "One-line description shown by --list-techniques."),
```

| Field | Notes |
|---|---|
| name | kebab-case identifier used in `--techniques` and output |
| fn | the `(text) -> (new_text, occurrences)` function |
| aggressive | `False` for lossless / near-lossless (runs by default); `True` for mildly lossy (opt-in via `--aggressive` or a `--max-tokens` budget) |
| description | shown by `compress --list-techniques` |

`DEFAULT_TECHNIQUES`, `AGGRESSIVE_TECHNIQUES`, and `ALL_TECHNIQUES` are derived from this list automatically — no other registration is needed.

### Writing compression tests

Add tests to `tests/test_compress.py`. A technique needs at minimum a positive case and a no-op case, plus a fence-safety case if it touches prose only:

```python
def test_my_technique_applies():
    result = compress("input that should shrink", techniques=["my-technique"])
    assert result.compressed_text == "expected"
    assert any(t.name == "my-technique" for t in result.applied)

def test_my_technique_preserves_code():
    text = "prose\n\n```python\nkeep  me\n```\n"
    result = compress(text, techniques=["my-technique"])
    assert "keep  me" in result.compressed_text
```

> **Default-tier techniques must be lossless or near-lossless for Markdown prompts.** Anything that changes meaning (dropping content, summarising, reordering) belongs in the aggressive tier.

---

## How to extend the workspace schema

The workspace schema lives at `promptgenie/schemas/workspace.schema.json`. When you add a new top-level section or new keys to an existing section, you need to update three places:

1. **`workspace.schema.json`** — add the new property to the appropriate `$defs` object. Keep `additionalProperties: false` so typos are caught. Add a `description` field.

2. **`promptgenie/core/config.py`** — add the key to the relevant `_*_KEYS` frozenset used in `validate_workspace_config()`, and add the corresponding type/enum validation branch. If you're adding a new top-level section, also add it to `_TOP_LEVEL_KEYS` and create a new dataclass + `_parse_*` function.

3. **`tests/test_workspace_schema.py`** — add at least:
   - A test that a valid value for the new key passes validation
   - A test that an unknown key adjacent to the new key is still caught
   - A type-error test if the value has a type constraint

Verify `config init` still produces a file that passes `config validate`:

```bash
promptgenie config init --name testproj --force
promptgenie config validate --format json
```

The JSON Schema file is included in the built wheel via `pyproject.toml`'s `package-data` entry — no extra setup needed.

---

## Profile schema reference

Profiles live in `promptgenie/profiles/<id>.yaml`. The file name (without `.yaml`) is the profile ID used in `--target` and `--from`/`--to` flags.

```yaml
# Required
name: string                   # Human-readable name shown in CLI output and adapted prompts
category: string               # Controls adapter behaviour — see categories below

# Optional — all default to empty lists / strings if omitted
strengths:
  - string                     # Displayed in list-targets; used to describe the tool

risks:
  - string                     # Known agentic risks for this tool (informational)

required_sections:
  - string                     # Section headings the adapter will add if missing
                               # Must match ## Heading capitalisation exactly

forbidden_patterns:
  - string                     # Literal strings replaced by [REMOVED — forbidden by target profile]
                               # during adapt; also flagged by the linter

stop_conditions:
  - string                     # Used to populate the Stop Conditions section when added by adapter

security_controls:
  - string                     # Used to populate the Security Controls section when added by adapter

scope_guidance: |
  string                       # Default content for the Scope section when added by adapter

default_output_format: |
  string                       # Default content for the Output Format section when added by adapter
```

**Categories:**

| Category | Meaning |
|---|---|
| `agentic-coding` | Tool executes code and modifies files autonomously (e.g. Claude Code, Cursor) |
| `ide-coding` | IDE-embedded agent with file access (treated as agentic by the adapter) |
| `general-assistant` | Conversational tool without autonomous file/code execution |

The adapter uses category to determine whether agentic safety sections (scope, stop conditions, forbidden actions, constraints, verification) are relevant to the target. Profiles in `agentic-coding` or `ide-coding` keep safety sections by default; others preserve them unless `--strip-agentic-safety` is passed.

---

## Template schema reference

Templates live in `promptgenie/templates/cyber_templates.yaml` under the top-level `templates:` list. Each template is a map with the following fields:

```yaml
templates:
  - id: string          # Used with --template flag; kebab-case
    name: string        # Human-readable name shown in list-templates
    category: string    # Grouping label (e.g. security, coding, security-operations)
    description: string # One-line description shown in list-templates
    sections:
      - string          # Ordered list of ## Section headings the generator will populate
                        # These become required_sections for scoring purposes
```

**Guidelines for sections:**

- Use title case: `Output Format`, not `output format`
- Include `Objective` and `Output Format` in every template — the generator and linter both expect them
- Agentic templates should include `Scope`, `Stop Conditions`, `Forbidden Actions`, and `Acceptance Criteria`
- Security templates should include whatever is appropriate for the task class (e.g. `Rules of Engagement` for pentest, `Escalation Criteria` for SOC triage)

---

## How to add a profile

1. Create `promptgenie/profiles/<id>.yaml` following the schema above.
2. Add a fixture prompt and update the smoke test if the category is new.
3. Run `promptgenie list-targets` — the profile should appear.
4. Run `promptgenie adapt examples/auth-refactor.md --from claude-code --to <id>` and verify the output is sensible.
5. Add tests to `tests/test_adapter.py` covering adapt-to and adapt-from for the new profile.

Profile file names must be lowercase and use hyphens, not underscores.

---

## How to add a template

1. Add a new entry to the `templates:` list in `promptgenie/templates/cyber_templates.yaml`.
2. Run `promptgenie list-templates` — the template should appear.
3. Run `promptgenie generate "test task" --template <id> --target claude-code` and verify output.
4. Add a test to `tests/test_generator.py` asserting the required sections appear.

---

## Submitting a pull request

1. Fork the repo and create a branch: `git checkout -b feat/my-change`
2. Make your change, add tests, make sure all checks pass:

```bash
pytest tests/
ruff check promptgenie/
ruff format --check promptgenie/
bandit -r promptgenie/ -ll
```

3. Commit with a descriptive message:

```
feat(linter): add AGENT_009 rule for unrestricted shell glob patterns

Fixes #NNN
```

4. Open a PR against `main`. The CI pipeline (test × 3 Python versions, lint, security scan, build) must be green before merge.

**PR checklist:**

- [ ] Tests added for any new rule, profile, or template
- [ ] Both a trigger case and a clean case for any new lint/scanner rule
- [ ] `ruff check` and `ruff format --check` pass
- [ ] `bandit` passes (no new HIGH/MEDIUM findings without justification)
- [ ] README updated if a user-visible behaviour changed

---

## Reporting a bug

Open an issue at [github.com/mylesagnew/promptgenie/issues](https://github.com/mylesagnew/promptgenie/issues).

Include:

- PromptGenie version (`promptgenie --version`)
- Python version (`python3 --version`)
- The command you ran
- The full output or error
- The prompt file if relevant (redact any secrets)

For security vulnerabilities, follow the process in [SECURITY.md](SECURITY.md).
