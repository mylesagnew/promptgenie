# Changelog

All notable changes to PromptGenie are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Security

- **Benchmark external-send disclosure** — `benchmark` command now prints an explicit transmission notice (file path + destination: Anthropic model + judge) before any API call. Runs the scanner on the prompt file first and surfaces any secret findings with line numbers before proceeding. Requires interactive confirmation (`y/N`, defaulting to `N`) unless `--yes` / `-y` is passed. For a security-branded CLI, silent external transmission of prompt content was unacceptable regardless of the benchmark use case.
- **Typed rule registry** — scanner and linter rules migrated from raw Python tuples into `ScanRule` and `LintRule` dataclasses with stable `id`, `category`, `pattern`, `risk`/`severity`, `confidence`, `message`, `recommendation`, and `false_positive_note` fields. This makes rule intent, scope, and false-positive guidance legible to reviewers and ensures rule IDs remain stable across changes.
- **Honest severity framing in scan output** — CLI panel title changed to `Prompt Security Scan (heuristic)`. `HIGH`/`CRITICAL` labels now carry an explicit note that they reflect the *severity of the pattern class*, not detection certainty. Scanner note footer expanded to: findings indicate risk patterns, not confirmed vulnerabilities; review required before treating as authoritative.

### Added

- **`benchmark --yes` / `-y` flag** — skips the interactive external-send confirmation prompt for CI and non-interactive use. Without it, the command defaults to `N` (safe by default).
- **Custom rules from `.promptgenie.yaml`** — `scanner.custom_rules` and `linter.custom_rules` accept user-defined rules with full metadata. Scanner rules support `use_original_text` (for case-sensitive patterns) and `flags` (e.g. `re.DOTALL`). Lint rules support `negate` (emit when pattern absent — for missing-section checks) and `requires_agentic`.
- **`ScanRule` dataclass** (`promptgenie/core/scanner.py`) — typed rule object replacing 5 separate Python tuple lists (`SECRET_PATTERNS`, `INJECTION_PATTERNS`, `AGENT_PERMISSION_PATTERNS`, `RAG_PATTERNS`, `SPLIT_OVERRIDE_PATTERNS`). Single unified scan loop with per-rule flag and text-source control.
- **`LintRule` dataclass** (`promptgenie/core/linter.py`) — typed rule object replacing `AGENTIC_RISK_PATTERNS` and `MISSING_SECTIONS` tuples. Adds `negate` and `requires_agentic` fields.

### Fixed

- **CI and release workflow dependency gap** — `ci.yml` and `release.yml` installed only `--extra dev` but `tests/test_benchmarker.py::TestJudgeParsing::test_judge_parse_failed_flag_set` calls `run_benchmark()`, which imports `anthropic` (optional `benchmark` extra). Result: `1 failed, 418 passed` in CI. Fixed by adding `--extra benchmark` to both install steps. All three install lines now read `uv sync --frozen --extra dev --extra benchmark`.

### Changed

- **README scan section** — "What it detects" → "What it flags (heuristic patterns)"; added confidence/severity callout block; quality score section now notes scores are local heuristic estimates, not objective measurements.
- **README configuration section** — added `custom_rules` YAML examples for scanner and linter.
- **README benchmark options** — added `--yes` / `-y` to the options table.
- **SECURITY.md scanner limitations** — updated to reflect: allowlist is now shipped (not planned); benchmark external-send disclosure is now enforced; typed rule registry with `false_positive_note` is available.

### Tests

**419 passed (unchanged — all existing tests pass against the refactored rule registry). Coverage maintained ≥87%.**

---

## [1.0.11] — 2026-06-07

### Added

- **`promptgenie/core/fileio.py`** — new safe I/O module with three public helpers:
  - `safe_read_text(path, max_bytes=1 MB)` — UTF-8 read with size guard; raises `FileTooLargeError` if the file exceeds the limit.
  - `safe_read_yaml(path, max_bytes=512 KB)` — bounded YAML read using `safe_read_text` + `yaml.safe_load`; smaller default limit than prompts since config files have no reason to be large.
  - `safe_write_text(path, content, force=False)` — atomic write via tempfile-then-`os.replace`; raises `FileExistsProtectedError` unless `force=True`; creates parent directories; never leaves a partially-written file on crash.
- **`FileTooLargeError`** and **`FileExistsProtectedError`** — typed exceptions with `.path`, `.size`, `.limit` attributes for programmatic handling.
- **`--force` flag** on `scan`, `lint`, `generate`, `adapt`, `pack inject`, and `benchmark` — required to overwrite an existing `--out` file. Default is now safe-by-default (refuse to overwrite).

### Changed

- All 38 `Path.read_text()`, `open()`, and `Path.write_text()` call sites across core and command modules migrated to `safe_read_text`, `safe_read_yaml`, or `safe_write_text`:
  - Core: `config.py`, `generator.py`, `context_packs.py`, `tester.py`, `differ.py`, `adapter.py`, `benchmarker.py`, `workflow.py`, `ci.py`
  - Commands: `scan.py`, `lint.py`, `generate.py`, `adapt.py`, `pack.py`, `benchmark.py`, `validate.py`
- All file reads now use explicit `encoding="utf-8"`.
- YAML config/data reads use the smaller 512 KB limit; prompt/workflow/response reads use the 1 MB limit.
- `ci init` scaffold writes now go through `safe_write_text` (atomic, UTF-8).
- `workflow save_workflow` step files now go through `safe_write_text(force=True)` — workflow re-renders intentionally overwrite.
- `context_packs init_pack` uses `safe_write_text(force=False)` — duplicate pack IDs now raise cleanly instead of silently overwriting (the `init_pack` command already checked for duplicates, but the write was unprotected).

### Tests

**26 new tests in `tests/test_fileio.py`** — `TestSafeReadText` (8 tests), `TestSafeReadYaml` (7 tests), `TestSafeWriteText` (9 tests), `TestRoundTrip` (2 tests). Cover: UTF-8 content, emoji, string/Path args, exact-at-limit, one-over-limit, custom limit, error message format, force/no-force, atomic cleanup, parent directory creation, YAML parse errors, round-trip.

**445 passed (was 419). Coverage maintained ≥87%. 0 ruff issues.**

---

## [1.0.10] — 2026-06-06

### Security

- **Unicode normalization in scanner** — all text is now NFKC-normalized before pattern matching. Fullwidth ASCII letters (`ｉｇｎｏｒｅ`), compatibility ligatures, and other Unicode compatibility forms are collapsed to their canonical ASCII equivalents. Closes the most common Unicode-homoglyph evasion path against the injection and permission patterns. Note: unrelated look-alike characters (Turkish dotless ı, U+0131) are not mapped; see `TestMisses`.
- **Split/multiline instruction override detection** (`SEC_SPLIT_001–004`) — new pattern group catches instruction overrides split across line breaks (between words), inside HTML `<!-- -->` comments, and inside `/* */` block comments. Patterns use `re.DOTALL` so `.` crosses newlines. Matched text is capped at 120 chars for clarity.
- **Base64 payload detection** (`SEC_B64`) — new scan pass flags base64 blobs ≥40 chars that decode to >70% printable ASCII text. Catches obfuscated instruction payloads. Short blobs (UUIDs, short tokens) and binary-heavy content are excluded to limit false positives.
- **Scanner limitations footer in rich output** — every `scan` invocation in rich mode now prints a one-line note confirming the scanner is static regex + Unicode-normalised matching and does not detect synonym substitution, indirect reference, or multi-turn attacks. Keeps `--format json` and `--format sarif` output clean.

### Changed

- **`anthropic` made optional** (`promptgenie[benchmark]`) — was a mandatory runtime dependency; only `benchmark` subcommand uses it. Install with `pip install promptgenie[benchmark]` to enable benchmarking. Default install no longer pulls in the full Anthropic SDK.
- **`tiktoken` made optional** (`promptgenie[tokenizer]`) — was a mandatory runtime dependency; `generator.py` already had a `len(text)//4` fallback. Install with `pip install promptgenie[tokenizer]` for accurate token counts. Default install uses the fallback estimator.
- **Generated CI scaffold hardened** — `ci init` now scaffolds:
  - SHA-pinned `actions/checkout` (`34e114876b0b11c390a56381ad16ebd13914f8d5`, v4) instead of mutable `@v4`
  - SHA-pinned `astral-sh/setup-uv` (`d0cc045d04ccac9d8b7881df0226f9e82c39688e`, v6) instead of `actions/setup-python@v5` + pip
  - `uv pip install --system "promptgenie==<current-version>"` instead of `pip install promptgenie --quiet` (pinned to running version, not floating latest)
  - `permissions: contents: read` top-level (least-privilege)
  - `while IFS= read -r file` loop instead of `for file in $(find ...)` (safe for filenames with spaces)

### Added

- `promptgenie[benchmark]` optional extra — pulls in `anthropic>=0.100`
- `promptgenie[tokenizer]` optional extra — pulls in `tiktoken>=0.7`

### Tests

**5 new `TestDetects` tests** — fullwidth Unicode normalization, split-line override, base64 payload, HTML comment smuggling, short-blob false-positive guard.
**2 updated `TestMisses` tests** — renamed to accurately describe remaining gaps (within-word split, non-NFKC homoglyphs).

**419 passed (was 414). Coverage maintained ≥87%.**

---

## [1.0.9] — 2026-06-06

### Fixed

- **Config wiring — `.promptgenie.yaml` now actually applied by the CLI** — `scan`, `lint`, `generate`, `test`, and `diff` commands previously ignored `.promptgenie.yaml` entirely; `load_config()` existed and `ScannerConfig`/`LinterConfig` were accepted by core functions, but no command ever loaded the file. All five commands now auto-discover and load `.promptgenie.yaml` from cwd and parent directories on every invocation.

### Added

- **`--config PATH` flag** on `scan`, `lint`, `generate`, `test`, `diff` — explicit path to a `.promptgenie.yaml` file, bypassing auto-discovery.
- **`--no-config` flag** on `scan`, `lint`, `generate`, `test`, `diff` — run with default settings, ignoring any `.promptgenie.yaml` present in the directory tree.
- **Config file disclosure in rich output** — when a config file is loaded, its path is printed as a dim line before results (e.g. `Config: /project/.promptgenie.yaml`). JSON and SARIF outputs are unaffected.
- **Graceful config error handling** — a missing or malformed `--config` file emits a `Warning:` line and falls back to defaults rather than crashing with an unhandled exception.
- **`config` param on `diff_prompts()` and `run_test_suite()`** — both core functions now accept `config: PromptGenieConfig | None`; `diff` passes `config.linter` and `config.scanner` to both sides of the comparison; `test` applies config to the lint and scan assertions run against the prompt under test.
- **13 new `TestConfigWiring` tests** — prove end-to-end that CLI behaviour changes with config: disabled rules suppress findings, allowlists reduce scan findings, custom vague verbs trigger lint issues, all five commands accept `--config` and `--no-config`, a missing config file emits a warning instead of crashing.

### Tests

**414 passed (was 401). Coverage maintained ≥87%.**

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

[Unreleased]: https://github.com/mylesagnew/promptgenie/compare/v1.0.11...HEAD
[1.0.11]: https://github.com/mylesagnew/promptgenie/compare/v1.0.10...v1.0.11
[1.0.10]: https://github.com/mylesagnew/promptgenie/compare/v1.0.9...v1.0.10
[1.0.9]: https://github.com/mylesagnew/promptgenie/compare/v1.0.8...v1.0.9
[1.0.8]: https://github.com/mylesagnew/promptgenie/compare/v1.0.7...v1.0.8
[1.0.7]: https://github.com/mylesagnew/promptgenie/compare/v1.0.6...v1.0.7
[1.0.6]: https://github.com/mylesagnew/promptgenie/compare/v1.0.5...v1.0.6
[1.0.5]: https://github.com/mylesagnew/promptgenie/compare/v1.0.4...v1.0.5
[1.0.4]: https://github.com/mylesagnew/promptgenie/compare/v1.0.3...v1.0.4
[1.0.3]: https://github.com/mylesagnew/promptgenie/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/mylesagnew/promptgenie/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/mylesagnew/promptgenie/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/mylesagnew/promptgenie/releases/tag/v1.0.0
