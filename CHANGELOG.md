# Changelog

All notable changes to PromptGenie are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

_Nothing yet._

---

## [1.0.1] — 2026-06-05

### Fixed

- **Adapter safety regression** — agentic safety sections (stop conditions, forbidden actions, scope, constraints, verification) were silently dropped when adapting a prompt from an agentic target (e.g. `claude-code`) to a non-agentic target (e.g. `chatgpt` or `gemini`). These sections are now preserved by default. The previous drop-on-adapt behaviour is available as an explicit opt-in via `--strip-agentic-safety` on the `adapt` command, or `strip_agentic_safety=True` in the `adapt()` Python API.

### Changed

- `adapt` CLI command: added `--strip-agentic-safety` flag (off by default).
- `adapt()` core function: added `strip_agentic_safety: bool = False` parameter.
- Adapter change log: agentic safety sections kept by default now appear as `KEPT` with a note; dropped sections (when flag is set) show an updated reason string referencing `--strip-agentic-safety`.

### Tests

- `TestAgenticToGeneralAdaptation` updated to assert safe default behaviour (sections preserved, no drops, no token reduction).
- New `TestAgenticToGeneralStripOptIn` class covers the explicit opt-in path (drops, warnings, token reduction, text removal).

---

## [1.0.0] — 2026-05-28

Initial public release.

### Added

#### Core commands

- **`generate`** — build an optimised, section-structured prompt from a rough task description. Options: `--target`, `--template`, `--context`, `--constraints`, `--output-format`, `--mode` (minimal / standard / exhaustive), `--out`, `--pack`, `--no-lint`, `--no-scan`.
- **`lint`** — static analysis for prompt quality and agentic safety. 15+ rules across four categories (task clarity, agentic risk, structure, scope). Exits 1 on HIGH severity. Options: `--format rich|json|sarif`, `--out`.
- **`scan`** — security scanner for secrets, prompt injection, agent permission abuse, and RAG risks. Exits 1 on HIGH or CRITICAL. Options: `--format rich|json|sarif`, `--out`.
- **`diff`** — compare two prompt versions with token delta, quality score delta, per-section line diffs, lint change delta, and security finding delta. Options: `--target`, `--unified`.
- **`adapt`** — translate a prompt from one target profile to another. Rewrites model-specific language, adds missing required sections, replaces forbidden patterns. Outputs a colour-coded change log and score/token summary.
- **`test`** — declarative prompt unit tests via `.prompt-test.yaml` files. Eight assertion types: `must_include`, `must_not_include`, `required_sections`, `regex_match`, `regex_not_match`, `min_score`, `max_tokens`, `max_lint_severity`, `max_security_risk`. Exits 0/1 — safe in CI.
- **`benchmark`** — run a prompt against a Claude model and score the response across six rubric dimensions (relevance, completeness, format compliance, safety compliance, conciseness, actionability) using a separate judge call. Supports multi-run averaging, head-to-head comparison, cost estimation, and cache token reporting.
- **`workflow`** — generate a staged prompt chain from a `.workflow.yaml` file. Each step gets its own focused prompt with handoffs, approval gates, per-step scope locks, stop conditions, and forbidden actions. Options: `--summary`, `--step N`, `--out DIR`.
- **`pack list|show|inject|init`** — reusable project context blocks. Packs capture stack, architecture, coding style, forbidden changes, known pitfalls, and terminology. Three render modes: minimal / standard / exhaustive.
- **`ci init|status`** — scaffold GitHub Actions and pre-commit hooks for prompt quality gates. Creates `.github/workflows/prompt-check.yml`, `.pre-commit-config.yaml`, and `.promptignore`.
- **`list-targets`** — list all available model profiles.
- **`list-templates`** — list all available prompt templates.

#### Profiles

Five target profiles: `claude`, `claude-code`, `chatgpt`, `cursor`, `gemini`. Each defines required sections, forbidden patterns, stop conditions, security controls, scope guidance, and a default output format.

#### Templates

Seven prompt templates: `agentic-task`, `threat-model`, `secure-code-review`, `soc-triage`, `pentest`, `iac-review`, `prompt-injection-test`.

#### Context packs

Three starter packs: `react-supabase-app`, `django-rest-api`, `cyber-security-team`.

#### Structured output

`--format json` and `--format sarif` on `lint` and `scan`. SARIF 2.1.0 output is compatible with GitHub code scanning upload.

#### Quality scoring

Every prompt is scored across seven dimensions: target fit, task clarity, context sufficiency, output contract, safety controls, token efficiency, testability. Scores ≥80 are considered production-ready.

#### CI pipeline

`ci.yml` runs on every push and PR to `main`:

- **test** — pytest across Python 3.10 / 3.11 / 3.12
- **lint** — `ruff check` + `ruff format --check`
- **security** — `bandit` + `pip-audit`
- **build** — `python -m build`, `twine check`, CLI smoke test

#### Packaging

`pyproject.toml` with `setuptools` build backend, dev dependency group, Python classifiers, and project URLs. Supports `pip install -e ".[dev]"`.

#### Documentation

`README.md` with full command reference, option tables, format docs, workflow YAML schema, context pack schema, quality score breakdown, and project structure map.

`SECURITY.md` with vulnerability reporting process, scanner scope and limitations, safe secret handling policy.

---

[Unreleased]: https://github.com/mylesagnew/promptgenie/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/mylesagnew/promptgenie/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/mylesagnew/promptgenie/releases/tag/v1.0.0
