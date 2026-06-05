# Changelog

All notable changes to PromptGenie are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

_Nothing yet._

---

## [1.0.8] — 2026-06-06

### Fixed

- **Scanner allowlist — scoped suppression replacing broken whole-prompt match** — previous behaviour suppressed *all* findings if any allowlist phrase appeared *anywhere* in the prompt. New behaviour: each allowlist entry checks only the finding's `matched_text` (the text the regex actually matched). Rule-scoped entries additionally filter by rule code before checking matched text.
- **`SecurityFinding.matched_text` field** — every regex-matched finding now records the exact matched string, enabling precise allowlist scoping.
- **Coverage gate (80% → 87%)** — declared `fail_under = 85` was failing locally. Fixed by: adding 25 targeted tests for uncovered paths; marking `interactive.py` terminal UI functions `# pragma: no cover` (untestable without a TTY).
- **ruff not running against `tests/`** — CI only linted `promptgenie/`. Extended ruff to `tests/`; fixed all 39 issues (unsorted imports, unused imports, pointless f-strings, `NamedTemporaryFile` context-manager violations, unused variables).
- **`commands/validate.py` formatting** — file would have been reformatted by `ruff format`; now clean.

### Added

- **`AllowlistEntry` dataclass** — replaces bare `list[str]` allowlist. Two YAML formats:
  - Simple string: `- "phrase"` — suppresses any finding whose matched text contains the phrase.
  - Scoped object: `- {phrase: "phrase", rules: [SEC_001]}` — suppresses only named rule codes.
- **Adversarial scanner test suite** (`tests/test_scanner_adversarial.py`, 30 tests):
  - `TestDetects` — 15 canonical patterns the scanner catches, including HTML comment injection and `matched_text` integrity.
  - `TestMisses` — 8 documented gaps (multiline splits, Unicode homoglyphs, word-spacing evasion, indirect reference, role-shift without keywords, synonym substitution, base64 encoding, markdown bold). Each asserts the expected miss so any future improvement is immediately visible.
  - `TestScopedAllowlist` — 7 regression tests for the fixed allowlist, including an explicit check that old whole-prompt suppression no longer applies.

### Tests

**401 passed (was 345). Coverage: 87% (gate: 85%). 0 ruff issues across `promptgenie/` and `tests/`.**

---

## [1.0.7] — 2026-06-05

### Added

- **`promptgenie/models.py` — typed config and result models** — `Profile`, `Template`, `ContextPackMeta`, `GenerateResult`, and `ValidationResult` dataclasses with `from_dict()` constructors and `validate()` methods.
- **`promptgenie validate` command** — validates YAML config artefacts (profiles, templates, context packs, workflows, prompt-test suites); auto-detects kind from filename; exits 1 on errors; `--all` validates all built-in artefacts.

### Tests

26 + 7 + 12 + 16 + 17 + 8 + 21 = **107 new tests** across `test_tester.py`, `test_ci_core.py`, `test_context_packs_full.py`, `test_workflow_full.py`, `test_models.py`, `test_validate_cmd.py`, `test_cli_commands.py`.

**Coverage: 83% (was 65%). Total tests: 306 (was 199).**

---

## [1.0.6] — 2026-06-05

### Added

- **Line-level SARIF locations** — `SecurityFinding` and `LintIssue` gain `line`, `col`, and `confidence` fields. Every pattern-matched finding now records its exact 1-based position via `_offset_to_line_col()`. SARIF output emits `physicalLocation.region` with `startLine`/`startColumn` and a `properties.confidence` field. JSON output also includes `line`, `col`, `confidence`.
- **`TOOL_VERSION` from metadata** — `formatters.py` reads version from `importlib.metadata` instead of a hard-coded string.
- **Hardened pre-commit hooks** — `.pre-commit-config.yaml` rebuilt with SHA-pinned upstream repos: `astral-sh/ruff-pre-commit`, `pre-commit/pre-commit-hooks` (check-yaml, check-toml, whitespace, merge-conflict, large-file guards), `Yelp/detect-secrets`. `.secrets.baseline` committed.

### Tests

17 new tests in `tests/test_sarif_locations.py`. **Total tests: 199 (was 182).**

---

## [1.0.5] — 2026-06-05

### Added

- **`uv.lock`** — 108 packages pinned with hashes. CI installs via `uv sync --frozen --extra dev`; all jobs migrated from `pip` + `actions/setup-python` to `astral-sh/setup-uv` (SHA-pinned). `cyclonedx-bom` added to dev deps.
- **Dependabot** — `.github/dependabot.yml` schedules weekly PRs for `uv` Python packages (dev deps grouped) and `github-actions` pins.
- **Release workflow** — `.github/workflows/release.yml` triggered by semver tags: verify gate → `uv build` + CycloneDX SBOM → PyPI Trusted Publishing via OIDC (no stored token) → Sigstore artifact attestations → GitHub Release with wheel, sdist, and SBOM attached. Runs inside a protected `release` environment.

---

## [1.0.4] — 2026-06-05

### Security

- **Context pack path traversal fix** — `load_pack()` and `init_pack()` validate `pack_id` against `^[A-Za-z0-9_-]+$` and enforce path containment. Traversal attempts (`../`, absolute paths, unicode, null bytes) raise `ValueError`.
- **Benchmark judge prompt injection hardening** — `JUDGE_SYSTEM` prompt explicitly marks evaluated content as untrusted data that must not be followed as instructions.

### Fixed

- **Benchmark judge parse failure explicit** — `_judge()` raises `BenchmarkEvaluationError` instead of silently returning score-50. `run_benchmark()` sets `judge_parse_failed=True` and the CLI emits a warning.
- **ReDoS protection** — `_safe_search()` rejects patterns over 500 chars and applies a 5-second `SIGALRM` timeout (POSIX) before `re.search`.

### Changed

- **Workflow validation** — `validate_workflow()` runs before rendering. Checks required fields, unique IDs, known dependencies, and cycles (DFS). Raises `WorkflowValidationError` with a descriptive message.
- **Benchmark `--runs` bounded** — `click.IntRange(min=1, max=10)`; API call count printed before execution.

### Tests

42 new tests in `test_context_packs.py`, `test_workflow.py`, `test_tester_regex.py`, `test_benchmarker.py`. **Total tests: 182 (was 140).**

---

## [1.0.3] — 2026-06-05

### Fixed

- **CI: invalid `pip-audit` flag** — `-q` replaced with `--progress-spinner off`.
- **CI: 61 ruff issues** — unused variables, import order, bare `try/except/pass` → `contextlib.suppress`; 22 files reformatted.
- **CI: 13 mypy errors** — `re.PatternError` → `re.error`; `cast(Risk/Severity/dict)` at rule-tuple and `yaml.safe_load` sites; `init_ci` return type; `score_delta` cast.
- **Versioning single source of truth** — `__init__.py` and `cli.py` read version from `importlib.metadata`; `pyproject.toml` aligned to `1.0.3`.

### Changed

- **CI: mypy added to lint job.**
- **CI: GitHub Actions SHA-pinned** — `actions/checkout` and `actions/setup-python` pinned to full commit SHAs.
- **CI: least-privilege permissions** — `permissions: contents: read` added top-level; no job receives the default broad token.

---

## [1.0.2] — 2026-06-05

### Changed

- **CLI refactor** — `cli.py` reduced from 888 lines to 35. All command logic moved into `promptgenie/commands/` and rendering consolidated into `promptgenie/renderers/rich.py`. No user-facing behaviour changes; all 140 tests pass unchanged.
- **Docs** — added `CONTRIBUTING.md` and `CHANGELOG.md`.

---

## [1.0.1] — 2026-06-05

### Fixed

- **Adapter safety regression** — agentic safety sections were silently dropped when adapting to a non-agentic target. Now preserved by default; opt out with `--strip-agentic-safety`.

### Changed

- `adapt` CLI: added `--strip-agentic-safety` flag (off by default).
- `adapt()` core: added `strip_agentic_safety: bool = False` parameter.

---

## [1.0.0] — 2026-05-28

Initial public release.

### Added

- **`generate`** — build structured prompts from rough task descriptions.
- **`lint`** — 15+ static analysis rules for prompt quality and agentic safety.
- **`scan`** — security scanner for secrets, prompt injection, agent permission abuse, and RAG risks.
- **`diff`** — compare two prompt versions (token, score, section, lint, and security deltas).
- **`adapt`** — translate a prompt between target profiles.
- **`test`** — declarative prompt unit tests via `.prompt-test.yaml` (8 assertion types, CI-safe).
- **`benchmark`** — run a prompt against Claude and score with a rubric judge model.
- **`workflow`** — staged prompt chains from `.workflow.yaml` with approval gates and handoffs.
- **`pack list|show|inject|init`** — reusable project context blocks (3 render modes).
- **`ci init|status`** — scaffold GitHub Actions and pre-commit prompt quality gates.
- **`list-targets` / `list-templates`** — enumerate available profiles and templates.
- Five target profiles: `claude`, `claude-code`, `chatgpt`, `cursor`, `gemini`.
- Seven prompt templates: `agentic-task`, `threat-model`, `secure-code-review`, `soc-triage`, `pentest`, `iac-review`, `prompt-injection-test`.
- Three starter context packs: `react-supabase-app`, `django-rest-api`, `cyber-security-team`.
- SARIF 2.1.0 output on `lint` and `scan` (compatible with GitHub code scanning).
- Quality scoring across seven dimensions; scores ≥80 considered production-ready.

---

[Unreleased]: https://github.com/mylesagnew/promptgenie/compare/v1.0.7...HEAD
[1.0.7]: https://github.com/mylesagnew/promptgenie/compare/v1.0.6...v1.0.7
[1.0.6]: https://github.com/mylesagnew/promptgenie/compare/v1.0.5...v1.0.6
[1.0.5]: https://github.com/mylesagnew/promptgenie/compare/v1.0.4...v1.0.5
[1.0.4]: https://github.com/mylesagnew/promptgenie/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/mylesagnew/promptgenie/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/mylesagnew/promptgenie/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/mylesagnew/promptgenie/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/mylesagnew/promptgenie/releases/tag/v1.0.0
