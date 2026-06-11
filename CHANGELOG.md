# Changelog

All notable changes to PromptGenie are documented here.

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

*Nothing yet — next milestone is Phase 3.*

---

## [1.2.0] — 2026-06-11  ·  Phase 2 — PromptSpec and Run Engine

Turns PromptGenie from a prompt generator into a prompt execution platform. Introduces a declarative spec format, end-to-end run pipeline, streaming responses, a multi-source context builder, and a first-class provider abstraction layer with built-in support for Anthropic, OpenAI, Ollama, and any OpenAI-compatible endpoint.

### Added

- **Declarative PromptSpec** (`promptgenie/core/spec.py`, `promptgenie/schemas/promptspec.schema.json`) — YAML/JSON spec format with fields: `version`, `name`, `target`, `template`, `mode`, `vars`, `context`, `policy`, `provider`, `model`, `system_prompt`, `prompt`, `output_contract`, `run`. JSON Schema at `promptgenie/schemas/promptspec.schema.json`. Full validation on load with clear per-field error messages.

  ```yaml
  version: 1
  name: code-review
  target: claude-code
  mode: chat
  prompt: Review {{component}} changes in {{env}}.
  vars:
    env: staging
  context:
    - type: git_diff
    - type: glob
      pattern: "src/**/*.py"
  policy:
    - no-secrets
  output_contract:
    format: markdown
    max_tokens: 2048
  run:
    stream: true
    timeout: 120
    require_clean: true
  ```

- **`promptgenie spec` command group** (`promptgenie/commands/spec.py`):
  - `spec init <name>` — scaffold a new spec file (`--target`, `--out`, `--force`)
  - `spec validate <file>` — validate structure, exit 0/2, `--format json`
  - `spec render <file>` — resolve variables and print the assembled prompt without calling a provider (`--var`, `--vars`, `--no-input`, `--format json`, `--show-context`)
  - `spec schema` — print the JSON Schema (`--format json|yaml`)

- **`promptgenie run`** (`promptgenie/commands/run.py`, `promptgenie/core/run_engine.py`) — end-to-end execution pipeline:

  Pipeline stages: load spec → resolve vars → build context → lint/scan/policy gate → render prompt → send to provider → stream response → persist run

  Flags:
  | Flag | Description |
  |---|---|
  | `--dry-run` | Resolve vars + build context without calling provider |
  | `--stream / --no-stream` | Streaming or non-streaming response |
  | `--require-clean` | Abort if git working tree is dirty |
  | `--provider NAME` | Override provider from providers.yaml |
  | `--model NAME` | Override model (e.g. gpt-4o, llama3) |
  | `--timeout SECONDS` | Abort provider call after N seconds |
  | `--no-history` | Skip run persistence |
  | `--var KEY=VAL` | Inline variable override (repeatable) |
  | `--vars FILE` | YAML/JSON variable file |
  | `--max-context-tokens N` | Context token budget |
  | `--context-strategy` | `manual` \| `newest` \| `smallest` \| `git-relevant` |
  | `--allow-url` | Permit URL-type context sources |
  | `--tee FILE` | Write response to file while streaming to stdout |
  | `--format text\|ndjson` | Structured NDJSON event stream |
  | `--show-context` | Print context manifest before running |

  ```bash
  promptgenie run my-prompt.yaml
  promptgenie run my-prompt.yaml --dry-run --show-context
  promptgenie run my-prompt.yaml --provider ollama --model llama3 --stream
  promptgenie run my-prompt.yaml --var env=prod --tee response.md
  promptgenie run my-prompt.yaml --format ndjson | jq 'select(.event=="done")'
  ```

- **Streaming response mode** — asyncio-based provider stream. NDJSON event types: `start`, `token`, `warning`, `tool_call`, `error`, `done`. TTY: raw token stream printed in-place. Non-TTY: same raw tokens or full NDJSON with `--format ndjson`. `--tee output.md` writes the final assembled response to a file while streaming to stdout.

- **Run history** (`promptgenie/core/history.py`) — runs persisted to `~/.local/share/promptgenie/runs/<YYYY-MM-DD>/<run-id>.ndjson` as event streams. Each file starts with a `start` event (metadata) and ends with a `done` event (duration, token counts, status). `list_runs()` and `load_run(run_id)` for programmatic access.

- **Variable files and env binding** (`promptgenie/commands/vars.py`):
  - `vars list <spec>` — list all `{{variable}}` placeholders in a spec's prompt
  - `vars inspect <spec>` — show resolved value + source (cli/file/env/default/unresolved) for every variable (`--var`, `--vars`, `--env-prefix`, `--redacted`, `--format json|yaml`)
  - Secret variables (names containing "secret") masked as `***` with `--redacted`

  ```bash
  promptgenie vars list my-prompt.yaml
  promptgenie vars inspect my-prompt.yaml --var env=prod --redacted
  promptgenie vars inspect my-prompt.yaml --vars prod.yaml --format json
  ```

- **Context builder** (`promptgenie/core/context_builder.py`, `promptgenie/commands/context.py`) — assembles context from 8 source types: `file`, `glob`, `stdin`, `env`, `cmd`, `git_diff`, `git_staged`, `url` (policy-gated). Respects `.promptignore`. Emits a `ContextManifest` with per-source SHA-256, token estimate, and inclusion status. `--max-tokens` budget with four trimming strategies.

  `promptgenie context build` command:
  ```bash
  promptgenie context build --glob "src/**/*.py" --max-tokens 8000
  promptgenie context build --git-diff --git-staged --format json | jq '.manifest'
  promptgenie context build --file README.md --out context.md
  git diff | promptgenie context build --stdin
  ```

- **Provider abstraction** (`promptgenie/core/providers.py`) — async `BaseProvider` protocol with `complete()` and `stream()` methods. `ProviderCapabilities` dataclass with `streaming`, `structured_output`, `max_context_tokens`, `local`, `supports_tools` flags. Config at `~/.config/promptgenie/providers.yaml`. Three built-in provider types:
  - `AnthropicProvider` — uses `anthropic` Python SDK when installed, falls back to raw `httpx`
  - `OpenAICompatProvider` — any OpenAI chat-completions endpoint (OpenAI, Ollama, LocalAI, LM Studio, vLLM)

- **`promptgenie provider` command group** (`promptgenie/commands/provider.py`):
  - `provider list` — table of all configured providers (`--format json|yaml`)
  - `provider add <name>` — add/update provider (`--type`, `--base-url`, `--api-key-env`, `--model`, `--local`)
  - `provider remove <name>` — remove with confirmation
  - `provider show <name>` — show config + capabilities
  - `provider doctor <name>` — probe reachability (local: `/models` endpoint; cloud: API key presence)

  ```bash
  # Add Ollama (local)
  promptgenie provider add ollama \
    --base-url http://localhost:11434/v1 --model llama3 --local

  # Add LM Studio
  promptgenie provider add lm-studio \
    --base-url http://localhost:1234/v1 --model local-model --local

  # Test reachability
  promptgenie provider doctor ollama
  promptgenie provider doctor anthropic

  # List all
  promptgenie provider list
  ```

### New files

| File | Purpose |
|---|---|
| `promptgenie/schemas/promptspec.schema.json` | JSON Schema for PromptSpec v1 |
| `promptgenie/core/spec.py` | PromptSpec dataclasses, loader, validator, renderer |
| `promptgenie/core/context_builder.py` | Multi-source context assembler + `.promptignore` |
| `promptgenie/core/providers.py` | Provider protocol, built-in adapters, config I/O |
| `promptgenie/core/history.py` | NDJSON run persistence + query functions |
| `promptgenie/core/run_engine.py` | End-to-end async run pipeline |
| `promptgenie/commands/spec.py` | `spec init/render/validate/schema` |
| `promptgenie/commands/run.py` | `run` command |
| `promptgenie/commands/context.py` | `context build` |
| `promptgenie/commands/provider.py` | `provider list/add/remove/show/doctor` |
| `promptgenie/commands/vars.py` | `vars list/inspect` |

### Tests

858 tests, 85%+ coverage. New test files: `test_spec.py` (32), `test_context_builder.py` (26), `test_providers.py` (14), `test_run_engine.py` (21).

### Dependency changes

- New optional extra `[providers]`: `httpx>=0.27` + `anthropic>=0.100`
- `httpx` enables raw HTTP fallback for Anthropic and all OpenAI-compatible providers when the SDK is not installed

---

## [1.1.0] — 2026-06-11  ·  Phase 1 — Terminal and Pipeline Foundations

All 8 Phase 1 features shipped. PromptGenie is now a full UNIX-composable CLI with stable output contracts, strict exit codes, and self-service tooling for shell setup and health checks.

### Added

- **Universal stdin/stdout — `-` sentinel** (`promptgenie/core/fileio.py`) — `lint`, `scan`, `diff`, and `adapt` all accept `-` in place of a file path, reading from `sys.stdin.buffer` with the same 1 MB size guard. Display label in all output formats (Rich, JSON `"file"` field, SARIF `artifactLocation.uri`) is `<stdin>`. `diff - -` is rejected with a clear `UsageError`. `scan -` enters single-file mode. All downstream callers (`core/adapter.py`, `core/differ.py`) gain stdin support automatically via `safe_read_text`.

  ```bash
  cat prompt.md | promptgenie lint - --format json | jq '.issues[]'
  cat prompt.md | promptgenie scan - --format sarif | upload-sarif
  cat new-draft.md | promptgenie diff - v1.md
  ```

- **Strict exit code contract** (`promptgenie/core/errors.py`) — centralized `EXIT_*` constants and a single `PromptGenieError(message, code, hint)` exception class. `handle_error()` always writes to stderr so structured stdout output is never polluted. `install_interrupt_handler()` ensures Ctrl-C exits 130 (not 1). All commands updated.

  | Code | Meaning |
  |---|---|
  | 0 | OK — clean run |
  | 1 | Failure — findings / threshold exceeded |
  | 2 | Usage / config error |
  | 3 | Provider / network failure |
  | 4 | Template / profile error |
  | 5 | Test assertion failures (`promptgenie test`) |
  | 6 | Secrets gate triggered |
  | 7 | Timeout |
  | 130 | Interrupted (Ctrl-C / SIGINT) |

- **Stable structured output — `schema_version: "1.0"`** — added to every JSON formatter (`lint_to_json`, `scan_to_json`, `multi_scan_to_json`, `diff_to_json`, `doctor --format json`). Enables downstream parsers to version-gate on the envelope. `is_structured_mode(format)` predicate (`json|sarif|yaml|ndjson`) gates banner and status-line suppression so Rich panels never pollute piped output.

- **Renderer profiles** (`promptgenie/renderers/rich.py`) — `ColorMode` enum (`auto|always|never`), `make_console(mode, stderr)` factory, `init_renderer(mode)` re-initialises both module-level singletons at startup. `diag_console` (stderr) now handles all diagnostic output (config paths, status lines, warnings) so `console` (stdout) carries only data. `NO_COLOR` / `FORCE_COLOR` env vars respected in `auto` mode. Global `--color auto|always|never` flag added to the CLI group (also reads `PG_COLOR` env var).

  ```bash
  promptgenie --color never lint prompt.md          # plain text, no ANSI
  promptgenie --color always lint prompt.md         # force colour even in pipe
  NO_COLOR=1 promptgenie scan prompt.md             # env-var equivalent
  ```

- **Side-by-side diff** (`promptgenie/core/differ.py` + `promptgenie/commands/diff.py`) — `--side-by-side` / `-s` renders a Rich two-column table with `SequenceMatcher`-based line pairing and colour-coded `equal|insert|delete|replace` rows. New `--format` choices for machine-readable output: `json` (`schema_version: "1.0"`), `yaml`, and `markdown` (GitHub-flavoured summary table with emoji deltas, section change list, new/resolved lint and security findings).

  ```bash
  promptgenie diff v1.md v2.md --side-by-side
  promptgenie diff v1.md v2.md --format markdown > DIFF.md
  promptgenie diff v1.md v2.md --format json | jq '.summary.score'
  ```

- **Interactive variable resolver** (`promptgenie/core/variables.py`) — `{{name}}`, `{{name:type}}`, `{{name:type:default}}` placeholder syntax detected in generated prompts. Resolution order: `--var key=val` CLI flag → `--vars file.yaml` → `PG_<UPPER_NAME>` env var → interactive `click.prompt` → inline default → `VarResolutionError` (exits 2). `--vars-schema schema.yaml` provides types (`string|int|float|bool|secret`), `required`, `allowed_values`, `description`. Secrets masked in display output. `--no-input` mode exits 2 immediately on any unresolved required variable.

  ```bash
  promptgenie generate "deploy {{service}} to {{env:string:staging}}" \
    --var service=api --no-input
  promptgenie generate "review {{component}}" --vars vars.yaml
  ```

- **`promptgenie doctor`** (`promptgenie/commands/doctor.py`) — self-check command. Checks Python ≥ 3.10, package version, `.promptgenie.yaml`, policy files, optional extras (`anthropic`, `tiktoken`), `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, local Ollama reachability, shell completion status per shell, `NO_COLOR`/`FORCE_COLOR` env vars. Hard failures (red ✗) exit 1; optional warnings (yellow ⚠) exit 0. Each failing check carries a `remediation` hint. `--format json` emits `schema_version: "1.0"` with `passed`, `failure_count`, `warning_count`, and per-group check details.

  ```bash
  promptgenie doctor
  promptgenie doctor --format json | jq '.groups[] | select(.title=="Providers")'
  ```

- **Shell completion** (`promptgenie/commands/completion.py`) — four sub-commands:
  - `promptgenie completion install zsh|bash|fish` — writes the shell script and appends activation to the RC file
  - `promptgenie completion show zsh|bash|fish` — prints the script to stdout without installing
  - `promptgenie completion status` — shows per-shell installation state and cache freshness
  - `promptgenie completion refresh-cache` — rebuilds `~/.cache/promptgenie/completions.json` (targets, templates, context packs) for dynamic completions

  Installation targets: `~/.zsh/completions/_promptgenie`, `~/.bash_completion.d/promptgenie`, `~/.config/fish/completions/promptgenie.fish`.

- **128 new tests** across 6 new test files: `test_errors.py` (20), `test_variables.py` (35), `test_renderer.py` (21), `test_differ_extended.py` (27), `test_doctor.py` (14), `test_completion.py` (11).
- **Total: 765 tests · 85%+ coverage.**

### Changed

- `promptgenie test` exits **5** (`EXIT_TEST`) on assertion failures instead of 1 — CI pipelines can now distinguish "test failure" (`5`) from "tool error" (`1`).
- Config/usage errors exit **2** (`EXIT_USAGE`) consistently across all commands (was inconsistently `1`).
- Diagnostic output (config path, status spinner notices, warnings) now routes through `diag_console` (stderr) — never pollutes piped `--format json|sarif|yaml` output.
- `diff --format` extended from `rich` only to `rich|json|yaml|markdown`.
- `generate` gains `--var`, `--vars`, `--vars-schema`, `--no-input` flags.

---

## [1.0.19] — 2026-06-08

### Security

- **Registry strict mode — checksums required by default:** `update_registry()` now defaults to `require_checksum=True`. Packs without a `sha256` field in the registry index are refused unless `require_checksum=False` is passed explicitly. `pack install` and `pack update` CLI commands expose `--allow-unverified` as the only escape hatch (prints a visible yellow warning when used).
- **Built-in registry checksums populated:** all 14 entries in `promptgenie/registry/index.yaml` now carry verified SHA-256 digests — the registry can self-verify without network trust on first install.
- **VS Code extension dependencies patched:** upgraded `@typescript-eslint/eslint-plugin` and `@typescript-eslint/parser` to latest, resolving 6 high-severity vulnerabilities in the `minimatch` transitive chain (`npm audit` now reports 0 vulnerabilities).

### Added

- **`policy --format sarif`** — emits a combined SARIF v2.1.0 document with separate lint and scan runs, suitable for direct upload to GitHub Code Scanning with `github/codeql-action/upload-sarif`.
- **Expired allowlist reporting in `policy`** — expired or malformed `AllowlistEntry` dates are surfaced as `allowlist_warnings` in JSON output and as `⚠ Allowlist:` lines in text output, making stale suppressions visible in CI rather than silently inactive.
- **VS Code extension CI job** — new `vscode-extension` job in `.github/workflows/ci.yml`: `npm ci` (locked install), `npm audit --audit-level=high`, `npm run compile`, `npm run lint`, upload compiled artifact. Extension now has parity with the Python CI quality posture.
- **`vscode-extension/package-lock.json` committed** — enables reproducible `npm ci` installs in CI and local development.

### Fixed

- **Coverage gate restored to 85%** — `tests/test_policy.py` (29 tests) brings `promptgenie/commands/policy.py` to 100% coverage; overall project coverage is 85.03%.
- **`ruff format` applied to 3 test files** — `test_benchmarker.py`, `test_coverage_gaps.py`, `test_registry.py` were not reformatted in v1.0.18; format check now passes cleanly.
- **`uv.lock` updated** — lockfile was pinned at v1.0.17; updated to reflect v1.0.18/v1.0.19 package metadata.
- **`TestUpdateRegistryMocked` test fixed** — `test_successful_update_installs_packs` now passes `require_checksum=False` since mock entries carry no SHA-256; test was broken by the new strict-mode default.

### Changed

- `update_registry()` signature gains `require_checksum: bool = True` parameter.
- `install_pack()` `require_checksum` default remains `False` for direct API calls; CLI commands default to strict mode via `not allow_unverified`.
- `.gitignore` updated: `vscode-extension/node_modules/` and `vscode-extension/out/` excluded from version control.

---

## [1.0.18] — 2026-06-08

### Security

- **Registry hardening — YAML parse errors no longer silently skipped in rule-pack loader:** `load_scan_rules_from_dirs()` and `load_lint_rules_from_dirs()` now raise `ValueError` when a file that declares `scanner_rules`/`lint_rules` fails to parse (fail-closed; malformed YAML files with no rule key are still silently skipped).
- **Allowlist expiry is now fail-closed:** `AllowlistEntry.is_expired()` returns `True` (expired) for malformed date strings instead of `False`, so a corrupt expiry never silently keeps a suppression alive.

### Changed

- **Unique SEC_SECRET rule IDs** — all nine secret-detection rules now carry distinct codes (`SEC_SECRET_APIKEY`, `SEC_SECRET_TOKEN`, `SEC_SECRET_OPENAI`, `SEC_SECRET_GOOGLE`, `SEC_SECRET_SLACK`, `SEC_SECRET_PRIVKEY`, `SEC_SECRET_GITHUB`, `SEC_SECRET_AWS_KEY`, `SEC_SECRET_AWS_SECRET`). The `SEC_SECRET` alias set (`SEC_SECRET_CODES` frozenset) provides backwards-compatible filtering.
- **`SecurityFinding` now carries `category` and `source` fields** — scan JSON output and the `policy` command include both fields per finding.
- **`ScanResult.risk_level` returns `"NONE"` (not `"LOW"`) when there are no findings** — callers checking for `"LOW"` should update to handle `"NONE"`.
- **Multiple-match support with per-rule cap** — scanner uses `re.finditer` + `enumerate()` and caps each rule at `MAX_FINDINGS_PER_RULE = 5` matches per prompt.

### Added

- **`policy` command** — CI gate: `promptgenie policy <file> [--max-risk HIGH] [--max-findings 0] [--min-score 0] [--format text|json]`. Exits 0 (pass), 1 (violations), or 2 (usage error). Text output uses a Rich table; JSON output is machine-readable.
- **`benchmark.py` secret check updated** — `_presend_check()` now correctly detects all `SEC_SECRET_*` sub-rules via `SEC_SECRET_CODES`.

### Fixed

- All test files updated for `SEC_SECRET` → `SEC_SECRET_*` rename (`test_scanner.py`, `test_sarif_locations.py`, `test_coverage_gaps.py`, `test_scanner_adversarial.py`, `test_registry.py`).
- `test_registry.py::test_malformed_date_not_expired` renamed to `test_malformed_date_is_expired_fail_closed` and assertion inverted to match new fail-closed behaviour.
- `test_scanner.py::test_risk_level_low_when_clean` updated to assert `"NONE"` not `"LOW"`.

---

## [1.0.17] — 2026-06-08

### Added

- **VS Code / Cursor extension** (`vscode-extension/`) — TypeScript extension that brings PromptGenie lint and security scan inline into the editor.

  **Core behaviour:**
  - **Inline lint diagnostics while typing** — lint runs on every text change (debounced, default 800 ms) and maps `LintIssue` objects to VS Code squiggly underlines in the correct diagnostic collection (`"PromptGenie Lint"`).
  - **Full lint + scan on save** — both commands run together when the file is saved; `ScanFinding` objects appear in a separate `"PromptGenie Scan"` diagnostic collection.
  - **Status bar quality score** — shows `PG: 85/100 · 3 issues` in the bottom-right corner for the active prompt file; colour-codes red (<50), yellow (<75), green (≥75); clicking triggers a full lint & scan.
  - **High-risk alert notifications** — a warning pop-up appears when any `HIGH` or `CRITICAL` security finding is detected, with a "Show Problems" action that focuses the Problems panel.

  **Supported file types:** `.md`, `.txt`, `.prompt`, `.promptgenie` (configurable via `promptgenie.enabledFileExtensions`).

  **Commands (Command Palette and context menu):**
  - `PromptGenie: Lint File`
  - `PromptGenie: Scan File`
  - `PromptGenie: Lint & Scan` (also available as an editor title bar icon)
  - `PromptGenie: Clear Diagnostics`

  **Extension settings:**
  | Setting | Default | Description |
  |---|---|---|
  | `promptgenie.cliPath` | `"promptgenie"` | CLI executable path |
  | `promptgenie.target` | `""` | Default `--target` profile |
  | `promptgenie.config` | `""` | Path to `.promptgenie.yaml` |
  | `promptgenie.runOnSave` | `true` | Lint + scan on save |
  | `promptgenie.runOnChange` | `true` | Lint on change (debounced) |
  | `promptgenie.debounceMs` | `800` | On-change debounce delay (ms) |
  | `promptgenie.showScoreInStatusBar` | `true` | Score in status bar |
  | `promptgenie.severityMapping` | `{HIGH: error, …}` | Risk level → VS Code severity |

  **Architecture:** `runner.ts` spawns the CLI as a child process with `--format json` and parses the output; `diagnostics.ts` converts typed output to `vscode.Diagnostic` objects; `statusBar.ts` owns the status bar item; `extension.ts` wires all events and registers commands.

  **Build:** `npm run compile` → TypeScript → `out/`; `npm run package` → `.vsix` for distribution.

---

## [1.0.16] — 2026-06-08

### Added

- **Community profile and template packs** — 11 new built-in registry packs covering model families, domain templates, and governance context. Registry grows from 3 to 14 packs.

  **Profile packs** (usable as `--target` after `promptgenie pack install <id>`):
  - `gpt-4o` — OpenAI GPT-4o: multimodal, function-calling, structured-output guidance; required sections, forbidden patterns, security controls for tool-calling deployments.
  - `mistral` — Mistral AI (7B / Mixtral 8x7B / Mistral Large): multilingual strengths, concise enumeration style, function-calling variant notes.
  - `llama3` — Meta Llama 3 (8B / 70B / 405B): open-weights deployment guidance, Llama Guard recommendation, fine-tuning considerations.
  - `github-copilot` — GitHub Copilot Chat and inline completion: IDE context requirements, CodeQL / Autofix security guidance, code-only output format.

  **Template packs** (usable as `--template` after install):
  - `devops-templates` — 6 templates: Incident Runbook, Postmortem / Blameless RCA, CI/CD Pipeline Review, On-Call Handoff, Capacity Planning Analysis, Infrastructure-as-Code Review.
  - `data-science-templates` — 6 templates: Exploratory Data Analysis, Model Evaluation Report, Feature Engineering Plan, ML Experiment Design, Model Card, Data Pipeline Review.
  - `legal-compliance-templates` — 5 templates: Contract Analysis, GDPR DPIA, Policy Review, Regulatory Gap Analysis, Third-Party Risk Assessment.
  - `product-management-templates` — 6 templates: PRD, User Story, OKR Alignment Review, Sprint Retrospective Summary, Competitive Analysis, Feature Prioritisation.
  - `customer-support-templates` — 6 templates: Support Ticket Triage, Escalation Summary, Knowledge Base Article, CSAT / NPS Analysis, Customer Onboarding Email, Renewal Risk Assessment.

  **Context packs** (injectable via `promptgenie pack inject`):
  - `responsible-ai-context` — 5 context items covering fairness principles, explainability guidelines, harm prevention checklist, transparency disclosure standards, and ethical review process.
  - `regulated-industries-context` — 5 context items covering HIPAA PHI constraints, SOX financial controls, PCI-DSS cardholder data rules, FCA / SEC AI guidance, and a regulated-industry deployment checklist.

- **Registry index `tags` field** — all 14 packs now carry a `tags` list in `index.yaml` (e.g. `[security, owasp, scanner]`, `[profile, community]`, `[context, hipaa, compliance]`) enabling future tag-based `pack search` filtering.

### Fixed

- **`registry.py` TOCTOU race** — replaced deprecated `tempfile.mktemp()` (bandit B306) with `tempfile.mkstemp()` + `os.write()` / `os.close()`. No TOCTOU window between file creation and write; `# noqa: S306` suppression removed.
- **`context_packs.py` operator precedence** — `not data.get("scanner_rules") and not data.get("lint_rules")` evaluated incorrectly: `and` binds tighter than `not`, so a rule pack with `scanner_rules` but no `lint_rules` was misclassified as a valid context pack. Fixed to `not (data.get("scanner_rules") or data.get("lint_rules"))`.
- **`scanner.py` redundant `enabled_rules` pre-loop filter** — the pre-loop filter on `active_rules` was redundant with the post-loop filter and, critically, did not guard the special-case `SEC_B64` and `SEC_CHAIN` detection blocks, allowing those findings to bypass the `enabled_rules` whitelist. Pre-loop filter removed; the post-loop filter now handles all findings uniformly.

### Tests

- 528 passed, 85%+ coverage, ruff clean.

---

## [1.0.15] — 2026-06-08

### Security / Changed (BREAKING for typo scenarios)

- **Fail-closed configuration loading** — `generate`, `scan`, `lint`, `adapt`, and `workflow` commands now abort with an explicit error when a requested profile, template, or config file cannot be found, instead of silently falling back to built-in defaults and producing plausibly correct but degraded output. This was previously a MEDIUM SecDevOps finding: a typo in `--target`, `--template`, or `--config` would produce output without any warning, making mistakes invisible.
  - `generator.generate_prompt(best_effort=False)` — raises `FileNotFoundError` on bad target/template.
  - `adapter.adapt(best_effort=False)` — raises `FileNotFoundError` on bad from/to profile.
  - `workflow.generate_workflow(best_effort=False)` — raises `FileNotFoundError` on bad profile or context pack.
  - `_resolve_config()` in `scan`, `lint`, `generate` — raises on bad `--config` path instead of printing a yellow warning and continuing.

### Added

- **`--best-effort` flag** on `generate`, `scan`, `lint`, `adapt`, and `workflow` — restores the previous lenient fallback behaviour for pipelines where partial output is acceptable. Explicit opt-in required; not the default.

### Tests

- Updated `test_workflow_full.py::test_unknown_target_falls_back_gracefully` → split into two tests:
  - `test_unknown_target_raises_by_default` — asserts `FileNotFoundError` without `best_effort`.
  - `test_unknown_target_falls_back_with_best_effort` — asserts fallback works with `best_effort=True`.
- 528 tests total, 85.20% coverage (above 85% gate), ruff clean.

---

## [1.0.14] — 2026-06-07

### Added

- **Plugin/profile registry** — versioned remote rule and context packs with `promptgenie pack update`.
  - Built-in registry index (`promptgenie/registry/index.yaml`) ships three starter packs:
    - `owasp-llm-top10` — 6 scanner rules mapping to OWASP LLM Top 10 (2025 edition)
    - `enterprise-lint` — 3 governance lint rules (placeholder detection, over-broad scope, inline credentials)
    - `ai-safety-context` — AI safety context pack for alignment-aware prompt engineering
  - `promptgenie pack search [query]` — search the registry index for available packs.
  - `promptgenie pack install <id>` — download and install a single pack from the registry.
  - `promptgenie pack update [--url URL]` — fetch the remote index and install/update all packs; caches index locally.
  - `promptgenie pack dirs` — show all registry and user rules directories.
- **`enabled_rules` config** — whitelist mode for scanner and linter: only listed rule codes are run. Takes precedence over `disabled_rules`. Supports targeting specific pack rule sets.
- **`rules_dirs` config** — extra directories scanned for rule pack YAML files. Supports `~` expansion. Works for both scanner and linter.
- **Expiring allowlist entries** — `AllowlistEntry.expires` (ISO date string) and `AllowlistEntry.reason` (free-text documentation). Suppressions are automatically deactivated after the expiry date. `is_expired()` method added.
- **Context pack search path extended** — `load_pack()` now searches `~/.promptgenie/registry/packs/` in addition to built-in context-packs, enabling registry-installed context packs to be used with `promptgenie pack inject`.
- **`pyproject.toml` package data** — added `registry/*.yaml` and `registry/packs/*.yaml` glob patterns so the built-in registry ships correctly with the package.

### Changed

- `promptgenie pack` group description updated to "Manage context packs and registry rule packs."
- Scanner `scan()` and linter `lint()` now load rules from `rules_dirs` before applying `enabled_rules` whitelist.

---

## [1.0.13] — 2026-06-07

### Fixed

- **Broken benchmark secret detection** — `_presend_check()` filtered `f.code.startswith("SECRET")` which never matched the scanner's actual code `"SEC_SECRET"`. Changed to exact match `f.code == "SEC_SECRET"`. Secrets are now correctly detected before external transmission.
- **`_presend_check()` used unbounded file read** — replaced `Path(prompt_file).read_text()` with `safe_read_text()` so the 1 MB limit applies consistently.
- **`_presend_check()` return value was ignored** — function now returns `True` when secrets are found; callers act on the result.
- **`--yes` bypassed secret gate** — secrets now unconditionally abort the benchmark command regardless of `--yes`. Added `--allow-secrets` flag as the explicit opt-in override.
- **Coverage gate failing in CI** — total coverage was 83.57% against a `fail_under = 85` gate. Added 26 targeted tests across config error paths, benchmark presend, scan/lint `--out` file-write paths, and the adapt command. Coverage is now 88.26%.
- **CI ruff scope excluded `tests/`** — ruff found 3 issues in `tests/test_benchmarker.py` that CI was silently skipping. Fixed the two SIM117 (nested `with`) and one I001 (import order) issues; extended CI ruff check and format to include `tests/`.
- **`.coverage` tracked in git** — removed from the index; added to `.gitignore`.

### Added

- **`--allow-secrets` flag on `benchmark`** — explicit opt-in to send a prompt externally even when potential secrets are detected. Requires both `--yes` and `--allow-secrets` to proceed non-interactively with secrets present.

### Tests

**483 passed (was 457). Coverage 88.26% (was 83.57%). 0 ruff issues across `promptgenie/` and `tests/`.**
New tests: `TestConfigCustomRuleErrors` (9), `TestPresendCheck` (4), `TestScanLintOutPaths` (8), `TestAdaptCommand` (4), `TestBenchmarkRunOverallScore.test_total_tokens_sums_in_and_out` (1).

---

## [1.0.12] — 2026-06-07

### Added

- **CodeQL analysis** (`.github/workflows/codeql.yml`) — GitHub Advanced Security CodeQL for Python on every push/PR to `main` and on a weekly schedule (Monday 03:00 UTC). Runs the `security-and-quality` query suite and uploads SARIF to the GitHub Security tab. Actions SHA-pinned (`github/codeql-action@v3`). Permissions: `contents: read`, `security-events: write`.
- **OpenSSF Scorecard** (`.github/workflows/scorecard.yml`) — weekly Scorecard analysis (Monday 04:00 UTC) plus push-to-`main` trigger. Uses `ossf/scorecard-action@v2.4.0` (SHA-pinned). SARIF uploaded to GitHub Security tab via the existing `codeql-action/upload-sarif`. `publish_results: true` enables the public Scorecard badge. `permissions: read-all` at workflow level; `security-events` and `id-token` scoped to the job.
- **Container image** (`Dockerfile` + `.dockerignore`) — minimal non-root image on `python:3.12-slim`. Dedicated `promptgenie` user and group (uid/gid 1001, no login shell). Dependency layer separate from source copy so Docker cache survives code-only changes. Installs `benchmark` and `tokenizer` extras. `.dockerignore` excludes `.git`, tests, docs, dist, and secrets baseline to keep the image lean. `ENTRYPOINT ["promptgenie"]`; `CMD ["--help"]`.
- **`ModelProvider` protocol** (`promptgenie/core/benchmarker.py`) — runtime-checkable `Protocol` with three methods: `complete(model, prompt, system) → (text, usage)`, `judge_model() → str`, and `estimate_cost(...) → float`. Decouples the benchmarker from the Anthropic SDK, making it provider-agnostic.
- **`AnthropicProvider`** — built-in `ModelProvider` implementation wrapping the Anthropic SDK (unchanged behaviour). Raises `ImportError` with install instructions if `anthropic` is not installed; raises `ValueError` if no API key is found.
- **`run_benchmark()` `provider=` parameter** — accepts any `ModelProvider`-conforming object. When omitted, an `AnthropicProvider` is created automatically using `api_key` / `ANTHROPIC_API_KEY` (fully backward-compatible).

### Changed

- **`_judge()` takes a `ModelProvider`** instead of a raw Anthropic client — judge model and judge calls are now fully provider-routed.
- **`benchmark` command** constructs `AnthropicProvider` explicitly before calling `run_benchmark()`, surfacing import and key errors early with a clean CLI error message.

### Security

- **Benchmark external-send disclosure** — `benchmark` command now prints an explicit transmission notice (file path + destination: Anthropic model + judge) before any API call. Runs the scanner on the prompt file first and surfaces any secret findings with line numbers before proceeding. Requires interactive confirmation (`y/N`, defaulting to `N`) unless `--yes` / `-y` is passed.
- **Typed rule registry** — scanner and linter rules migrated from raw Python tuples into `ScanRule` and `LintRule` dataclasses with stable `id`, `category`, `pattern`, `risk`/`severity`, `confidence`, `message`, `recommendation`, and `false_positive_note` fields.
- **Honest severity framing in scan output** — CLI panel title changed to `Prompt Security Scan (heuristic)`. `HIGH`/`CRITICAL` labels now carry an explicit note that they reflect the *severity of the pattern class*, not detection certainty.

### Fixed

- **CI and release workflow dependency gap** — `ci.yml` and `release.yml` install steps now include `--extra benchmark` so benchmarker tests pass in CI.

### Tests

**24 benchmarker tests (12 new)** — `TestModelProviderProtocol` (4 tests: protocol conformance, custom provider, cost delegation, multi-run), `TestAnthropicProvider` (5 tests: missing key, missing package, judge model, cost estimation, unknown model fallback), `TestCompareBenchmarks` (2 tests), `TestBenchmarkRunOverallScore` gains `test_total_tokens_sums_in_and_out`. All 457 tests pass. Coverage maintained ≥87%. 0 ruff issues.

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

[Unreleased]: https://github.com/mylesagnew/promptgenie/compare/v1.2.0...HEAD
[1.2.0]: https://github.com/mylesagnew/promptgenie/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/mylesagnew/promptgenie/compare/v1.0.11...v1.1.0
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
