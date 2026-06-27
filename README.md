<p align="center">
  <img src="assets/logo.png" alt="PromptGenie" width="600" />
</p>

# PromptGenie

**Secure prompt engineering for AI agents and engineering teams.**

PromptGenie is a CLI that turns rough task descriptions into optimised, tool-specific, security-checked prompts — and executes them end-to-end. It ships a built-in linter, multi-file security scanner, diff engine, test runner, model benchmarker, context pack system, workflow engine, CI integration, quality scoring, token estimation, full UNIX-composable pipeline, and a declarative run engine that sends prompts to any provider (Anthropic, OpenAI, Ollama, LM Studio, vLLM) with streaming, variable resolution, context assembly, policy gates, and run history. v1.6.0 adds a unified `EventBus` / `EventFormatter` infrastructure so every lifecycle event — run tokens, lint findings, policy violations, eval results — flows through a single typed channel that commands, tests, and future integrations all subscribe to. v1.7.0 adds a formal JSON Schema for `.promptgenie.yaml`, `workspace:` and `defaults:` config blocks, `config validate` for CI-safe schema checking, and `config init` to scaffold a new config with editor autocomplete wired up.

---

## Documentation

- **[docs/commands.md](docs/commands.md)** — full command reference
- **[docs/configuration.md](docs/configuration.md)** — `.promptgenie.yaml` and the config CLI
- **[SECURITY.md](SECURITY.md)** — security policy and run-engine security model
- **[THREAT_MODEL.md](THREAT_MODEL.md)** — assets, trust boundaries, and threat→control mapping
- **[ROADMAP.md](ROADMAP.md)** · **[CONTRIBUTING.md](CONTRIBUTING.md)** · **[CHANGELOG.md](CHANGELOG.md)**

---

## Why

Most prompt engineering is done by hand, rewritten constantly, and never tested. Prompts for agentic tools (Claude Code, Cursor, Devin) are especially risky: a vague scope or missing stop condition can cause scope creep, destructive edits, or unintended deployments.

PromptGenie makes prompts:

- **Structured** — section-by-section output matched to the target tool's requirements
- **Linted** — catches vague verbs, missing scope, broad tasks, and agentic risks before you send
- **Scanned** — multi-file, directory, and zip scanning; flags heuristic patterns consistent with secrets, prompt injection, and unsafe agent permissions; opt-in LLM semantic analysis layer with pre-send secret redaction
- **Diffed** — compare two versions with token delta, score delta, section changes, and risk changes
- **Tested** — declarative unit tests assert quality, safety, structure, and content before you ship
- **Benchmarked** — run prompts against real Claude models and score responses across 6 rubric dimensions
- **Context-aware** — reusable project context packs inject stack, architecture, pitfalls, and style into every prompt
- **Workflow-driven** — break complex tasks into staged prompt chains with approval gates, handoffs, and per-step scope locks
- **CI-integrated** — GitHub Actions workflow and pre-commit hooks keep bad prompts out of your repo
- **Machine-readable** — `--format json` and `--format sarif` on every lint and scan for CI pipelines and GitHub code scanning
- **UNIX-composable** — every command accepts `-` to read from stdin; pipe directly into `jq`, `sarif-fmt`, or your own tools without temp files
- **Scored** — rates every prompt across 7 quality dimensions
- **Repeatable** — YAML model profiles, templates, and context packs versioned alongside your code
- **Executable** — `promptgenie run spec.yaml` executes a PromptSpec end-to-end: resolves variables, assembles context, enforces policy, streams the response, and persists the run
- **Provider-agnostic** — built-in adapters for Anthropic, OpenAI, Ollama, LM Studio, LocalAI, vLLM, and NousResearch Hermes; add any OpenAI-compatible endpoint with one command; no API key needed for local providers
- **Hermes-ready** — first-class NousResearch Hermes support: a `hermes` target profile for `generate`/`adapt`/`lint`/scoring, plus a built-in OpenAI-compatible `hermes` provider (Nous Portal, `NOUS_API_KEY`) for `run`/`benchmark`/`evaluate`

---

## Quickstart

```bash
git clone https://github.com/mylesagnew/promptgenie.git
cd promptgenie
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# Generate a security-checked prompt for Claude Code
promptgenie generate "review this repo for security issues" --target claude-code

# Scan a prompt file for secrets and injection risks
promptgenie scan examples/auth-refactor.md

# Lint a prompt for quality issues
promptgenie lint examples/auth-refactor.md

# Check your installation health
promptgenie doctor

# Install shell tab-completion
promptgenie completion install zsh

# Launch the guided interactive menu
promptgenie interactive
```

**Event bus (v1.6.0+):**

```python
from promptgenie.core.event_bus import EventBus
from promptgenie.core.event_formatters import NDJSONFormatter
from promptgenie.core.events import Event, EventKind
from promptgenie.core.run_engine import run_spec

bus = EventBus()
tokens: list[str] = []
bus.subscribe(EventKind.RUN_TOKEN, lambda e: tokens.append(e.text))
bus.subscribe_all(lambda e: print(e.to_ndjson()))   # log everything

result = run_spec(spec, dry_run=False, event_bus=bus)
print("".join(tokens))  # assembled response
print(f"Events: {len(bus)}, tokens: {len(bus.of_kind(EventKind.RUN_TOKEN))}")
```

**Pipe-friendly (v1.1.0+):**

```bash
# Lint from stdin, extract issues with jq
cat prompt.md | promptgenie lint - --format json | jq '.issues[]'

# Scan and feed results directly to GitHub SARIF upload
cat prompt.md | promptgenie scan - --format sarif > findings.sarif

# Side-by-side diff with markdown output
promptgenie diff v1.md v2.md --side-by-side
promptgenie diff v1.md v2.md --format markdown > DIFF.md

# Generate with template variables
promptgenie generate "deploy {{service}} to {{env:string:staging}}" \
  --target claude-code --var service=api --no-input
```

**PromptSpec and run engine (v1.2.0+):**

```bash
# Install provider support (httpx + Anthropic SDK)
pip install "promptgenie[providers]"

# Scaffold a declarative PromptSpec
promptgenie spec init code-review --target claude-code
# → creates code-review.prompt.yaml

# Validate the spec
promptgenie spec validate code-review.prompt.yaml

# Preview the assembled prompt without calling any provider
promptgenie spec render code-review.prompt.yaml --var env=prod

# Add a local Ollama provider (no API key needed)
promptgenie provider add ollama \
  --base-url http://localhost:11434/v1 --model llama3 --local
promptgenie provider doctor ollama

# NousResearch Hermes (built-in provider — just set your key)
export NOUS_API_KEY=...
promptgenie provider doctor hermes
promptgenie generate "summarise this incident" --target hermes
promptgenie run code-review.prompt.yaml --provider hermes --model Hermes-4-405B --stream

# Execute the spec end-to-end
promptgenie run code-review.prompt.yaml --provider ollama --stream

# Dry run — resolve vars, build context, no provider call
promptgenie run code-review.prompt.yaml --dry-run --show-context

# Stream to stdout and write final response to file
promptgenie run code-review.prompt.yaml --tee response.md

# NDJSON event stream (pipeline-friendly)
promptgenie run code-review.prompt.yaml --format ndjson \
  | jq 'select(.event=="done")'

# Assemble context from git diff + all Python files
promptgenie context build --git-diff --glob "src/**/*.py" --max-tokens 8000

# Inspect how spec variables would resolve
promptgenie vars inspect code-review.prompt.yaml --var env=prod
```

Expected output: a structured, linted, scored prompt ready to paste into your AI tool.

---

## Demo

**Generate a structured, scored prompt:**

```
$ promptgenie generate "review this repo for security issues" --target claude-code

╭─ Generated Prompt  target: claude-code  template: agentic-task  mode: standard ─╮
│ # Prompt for Claude Code                                                         │
│                                                                                  │
│ ## Objective                                                                     │
│ review this repo for security issues                                             │
│                                                                                  │
│ ## Scope                                                                         │
│ Work only within the explicitly listed files or directories.                     │
│ Do not modify files outside this scope without asking first.                     │
│                                                                                  │
│ ## Stop Conditions                                                               │
│ Stop and ask for approval if:                                                    │
│ - Any file outside the defined scope needs to be modified                        │
│ - A new dependency would be added                                                │
│ - A database schema change is required                                           │
│ - Tests fail and the fix is non-obvious                                          │
│ - The task would require a deployment                                            │
│                                                                                  │
│ ## Output Format                                                                 │
│ Show diffs for each changed file.                                                │
│ Run tests and report results.                                                    │
│ Summarise what changed and why.                                                  │
│                                                                                  │
│ ## Acceptance Criteria                                                           │
│ Done when all objectives are met, output matches the requested format,           │
│ and no forbidden actions were taken.                                             │
╰──────────────────────────────────────────────────────────────────────────────────╯
╭──────────────────────── Prompt Quality Score ──────────────────────────────────╮
│                                                                                │
│   Target Fit            83    Task Clarity          90                         │
│   Context Sufficiency   75    Output Contract       90                         │
│   Safety Controls       82    Token Efficiency      95                         │
│   Testability           90                                                     │
│                                                                                │
│   Overall           86/100   Token estimate        150                         │
│                                                                                │
╰────────────────────────────────────────────────────────────────────────────────╯
```

**Scan a prompt for static prompt-risk patterns:**

```
$ promptgenie scan examples/auth-refactor.md

╭──────────── Security Scan  Risk: HIGH  examples/auth-refactor.md ────────────╮
│ [HIGH] [PERM_006] Unrestricted package installation.                         │
│   → Restrict agent permissions to minimum required scope.                    │
│     Add explicit approval gates.                                             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

> **Scanner scope:** `scan` is a regex/heuristic tripwire with Unicode normalization (NFKC). It catches obvious prompt-injection vocabulary, hardcoded secrets, unsafe agent permission patterns, split/multiline overrides, HTML and block-comment smuggling, base64-encoded payloads (≥40 chars, >70% printable), and fullwidth Unicode obfuscation. It does **not** catch within-word character splits, non-NFKC Unicode homoglyphs (e.g. Turkish ı), synonym substitution, or indirect reference attacks. See `tests/test_scanner_adversarial.py` for a full list of documented detection gaps.

> **Custom rule safety:** patterns loaded from `.promptgenie.yaml` `custom_rules` or registry-installed rule packs are validated at load time for syntax errors and nested quantifiers (`(a+)+`, `(\w+)*`, etc.) — the primary cause of catastrophic backtracking (ReDoS). Invalid or dangerous patterns are rejected with a clear error before they reach the scanner.

**Lint a prompt for quality issues:**

```
$ promptgenie lint examples/auth-refactor.md

╭────────────── Lint Results  80/100  examples/auth-refactor.md ───────────────╮
│ [HIGH] [AGENT_004] Allows unrestricted package installation.                 │
│   → Add explicit constraints and approval gates.                             │
╰──────────────────────────────────────────────────────────────────────────────╯
```

**Validate all built-in profiles against the schema:**

```
$ promptgenie validate-profiles

Validating 5 profile(s) in promptgenie/profiles

✓  [profile] chatgpt.yaml
✓  [profile] claude-code.yaml
✓  [profile] claude.yaml
✓  [profile] cursor.yaml
✓  [profile] gemini.yaml

All 5 file(s) valid.
```

**Validate everything at once (profiles, templates, context packs):**

```
$ promptgenie validate --all

✓  [profile]      chatgpt.yaml
✓  [profile]      claude-code.yaml
✓  [profile]      claude.yaml
✓  [profile]      cursor.yaml
✓  [profile]      gemini.yaml
✓  [template]     cyber_templates.yaml  (7 templates)
✓  [context-pack] cyber-security-team.yaml
✓  [context-pack] django-rest-api.yaml
✓  [context-pack] react-supabase-app.yaml

All 15 file(s) valid.
```

Errors fail CI (exit 1). Warnings are advisory (exit 0). Use `--no-warnings` to suppress them.

---

## Architecture: Workspace schema (v1.7.0)

`.promptgenie.yaml` now has a published JSON Schema at `promptgenie/schemas/workspace.schema.json`. Wire it to VS Code for inline autocomplete and error highlighting:

```json
// .vscode/settings.json
{
  "yaml.schemas": {
    "./promptgenie/schemas/workspace.schema.json": ".promptgenie.yaml"
  }
}
```

Or use the `yaml-language-server` comment that `config init` writes automatically:

```yaml
# yaml-language-server: $schema=https://promptgenie.dev/schemas/workspace.schema.json
$schema: "https://promptgenie.dev/schemas/workspace.schema.json"

workspace:
  name: "my-project"
  team: "platform-eng"
  policy: ".promptgenie-policy.yaml"

defaults:
  provider: anthropic
  model: claude-opus-4-5
  target: claude-code

security:
  airgap: false
  block_secrets: true
```

Validate any config with `promptgenie config validate` — catches unknown keys, type mismatches, invalid enum values, bad `expires` dates, and missing required rule fields:

```bash
# Validate and exit 0/1 (CI-safe)
promptgenie config validate

# Machine-readable output
promptgenie config validate --format json | jq '.errors[]'

# Scaffold a new config with schema pointer pre-wired
promptgenie config init --name "my-project"
```

---

## Architecture: Event model (v1.6.0)

Every observable lifecycle moment in PromptGenie is an `Event` — a frozen, NDJSON-serialisable value object with a typed `EventKind`.

```
EventKind domains
─────────────────────────────────────────────────────
run.*      start · token · warning · error · tool_call · done · dry
lint.*     finding
scan.*     finding
policy.*   pass · violation
diff.*     computed
eval.*     result
ci.*       check
audit.*    write
```

Commands emit events; formatters and subscribers consume them:

```
EventBus  ──subscribe(kind, fn)──► Listener callbacks
          ──subscribe_all(fn)────► Catch-all (audit, telemetry)
          ──emit(event)──────────► dispatches to all matching listeners
          ──emit_to(event, fmt)──► dispatch + format + write in one call
          ──collected / of_kind──► test assertions without stdout mocking
```

Built-in formatters implement the `EventFormatter` protocol (`format(event) → str | None`):

| Formatter | Emits | Suppresses |
|---|---|---|
| `NDJSONFormatter` | all events as JSON lines | — |
| `TokenOnlyFormatter` | `run.token` text only | everything else |
| `RichFormatter` | human-readable Rich markup | `run.token` |
| `SilentFormatter` | nothing | everything |

`run_spec()` accepts `event_bus=` alongside the legacy `on_token=` / `on_event=` callbacks — fully backward-compatible. A subscriber exception never propagates into the run pipeline.

---

## Install

```bash
git clone https://github.com/mylesagnew/promptgenie.git
cd promptgenie
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

Optional extras:

| Extra | What it adds | Install |
|---|---|---|
| `benchmark` | `anthropic` SDK — required for `promptgenie benchmark` | `pip install "promptgenie[benchmark]"` |
| `tokenizer` | `tiktoken` — accurate token counts (falls back to `len/4` without it) | `pip install "promptgenie[tokenizer]"` |
| `providers` | `httpx` + `anthropic` SDK — required to run prompts against providers | `pip install "promptgenie[providers]"` |
| _(no extra)_ | `openai` SDK — required for `promptgenie scan --llm` (not packaged as an extra) | `pip install openai` |

### Docker

```bash
# Build
docker build -t promptgenie .

# Run any command
docker run --rm promptgenie generate "review this repo for security issues" --target claude-code

# Benchmark (requires API key)
docker run --rm -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -v "$PWD":/prompts promptgenie benchmark /prompts/my-prompt.md --yes
```

The image runs as a non-root user (`promptgenie`, uid 1001). Mount a local directory with `-v` to read and write prompt files.

---

## Command reference

The full per-command reference — every flag and example for `generate`, `lint`, `scan`, `policy`, `diff`, `adapt`, `compress`/`optimize`, `tokens`, `fmt`, `make`, `test`, `benchmark`, `workflow`, `pack`, `registry`, `ci`, `spec`, `run`, `context`, `provider` (incl. **Hermes**), `vars`, `evaluate`/`eval`, `analyze`, `redact`, `redteam`, `auth`, `audit`, `config`, `tui`, `wizard`, `palette`, `history`, `watch`, `template`, `lock`, `plugin` — lives in **[docs/commands.md](docs/commands.md)**. Run `promptgenie --help` for the live list.

---

## Target Profiles

| ID | Name | Category |
|---|---|---|
| `claude` | Claude | General assistant |
| `claude-code` | Claude Code | Agentic coding |
| `chatgpt` | ChatGPT | General assistant |
| `cursor` | Cursor | IDE coding |
| `gemini` | Gemini | General assistant / multimodal |

Each profile defines required sections, forbidden patterns, stop conditions, security controls, and a default output format. Stored in `promptgenie/profiles/*.yaml`.

---

## Templates

| ID | Name | Category |
|---|---|---|
| `agentic-task` | Agentic Task Brief | Coding |
| `threat-model` | Threat Model | Security |
| `secure-code-review` | Secure Code Review | Security |
| `soc-triage` | SOC Alert Triage | Security operations |
| `pentest` | Penetration Test Plan | Security |
| `iac-review` | IaC Security Review | Security |
| `prompt-injection-test` | Prompt Injection Test Suite | Security |

Stored in `promptgenie/templates/*.yaml`.

---

## Quality Score

Every generated prompt is scored across 7 dimensions:

| Dimension | What it measures |
|---|---|
| Target Fit | Required sections present for the target tool |
| Task Clarity | Absence of vague verbs and ambiguous framing |
| Context Sufficiency | Enough context for the model to act without guessing |
| Output Contract | Output format explicitly defined |
| Safety Controls | Stop conditions, forbidden actions, constraints present |
| Token Efficiency | Prompt length relative to complexity |
| Testability | Acceptance criteria or success definition present |

Score of 80+ is considered production-ready. Below 60 triggers lint warnings automatically.

> **Score note:** quality scores are local heuristic estimates based on structural markers (sections present, vague words, length, output format signals). They are not an objective measurement of prompt effectiveness — treat them as a relative hygiene signal, not a grade.

---

## Project structure

```
promptgenie/
├── cli.py                      # Click group + command registration
├── commands/
│   ├── generate.py             # generate command
│   ├── lint.py                 # lint command
│   ├── scan.py                 # scan command
│   ├── diff.py                 # diff command
│   ├── adapt.py                # adapt command
│   ├── test.py                 # test command
│   ├── benchmark.py            # benchmark command
│   ├── workflow.py             # workflow command
│   ├── ci.py                   # ci group (init, status)
│   ├── pack.py                 # pack group (list, show, inject, init, search, install, update, dirs)
│   ├── policy.py               # policy command — CI gate (exit 0/1/2)
│   ├── targets.py              # list-targets, list-templates
│   └── interactive.py          # guided interactive menu mode
├── renderers/
│   └── rich.py                 # console, color constants, shared formatting helpers
├── core/
│   ├── generator.py            # Prompt builder, scoring, token estimation
│   ├── linter.py               # Lint rules engine
│   ├── scanner.py              # Security scanner
│   ├── differ.py               # Diff engine — token, score, section, risk delta
│   ├── adapter.py              # Adapt engine — cross-profile prompt translation
│   ├── tester.py               # Test runner — declarative prompt unit tests
│   ├── benchmarker.py          # Benchmark engine — model calls, rubric scoring, cost
│   ├── context_packs.py        # Context pack engine — load, render, inject, init
│   ├── workflow.py             # Workflow engine — staged prompt chains
│   ├── ci.py                   # CI scaffolder — GitHub Actions + pre-commit
│   ├── config.py               # .promptgenie.yaml config loader
│   ├── registry.py             # Pack registry — remote index, install, update, rule loading
│   ├── input_handler.py        # Multi-file collector — files, dirs, zips; zip-slip protection; byte/file caps
│   ├── llm_analyzer.py         # Opt-in LLM semantic analysis; pre-send secret redaction; privacy mode
│   └── formatters.py           # Structured output — JSON and SARIF v2.1.0; multi-file aggregation
├── registry/
│   ├── index.yaml              # Built-in registry index (14 packs)
│   └── packs/
│       ├── owasp-llm-top10.yaml            # OWASP LLM Top 10 scanner rules
│       ├── enterprise-lint.yaml            # Enterprise governance lint rules
│       ├── gpt-4o.yaml                     # OpenAI GPT-4o profile
│       ├── mistral.yaml                    # Mistral AI profile
│       ├── llama3.yaml                     # Meta Llama 3 profile
│       ├── github-copilot.yaml             # GitHub Copilot profile
│       ├── devops-templates.yaml           # DevOps & SRE templates
│       ├── data-science-templates.yaml     # Data Science & ML templates
│       ├── legal-compliance-templates.yaml # Legal & Compliance templates
│       ├── product-management-templates.yaml # Product Management templates
│       ├── customer-support-templates.yaml # Customer Support templates
│       ├── ai-safety-context.yaml          # AI safety context pack
│       ├── responsible-ai-context.yaml     # Responsible AI context pack
│       └── regulated-industries-context.yaml # Regulated industries context
├── profiles/
│   ├── claude.yaml
│   ├── claude-code.yaml
│   ├── chatgpt.yaml
│   ├── cursor.yaml
│   └── gemini.yaml
├── templates/
│   └── cyber_templates.yaml    # 7 security and coding templates
├── context-packs/
│   ├── react-supabase-app.yaml             # React + Supabase SaaS
│   ├── django-rest-api.yaml                # Django + DRF + PostgreSQL
│   └── cyber-security-team.yaml           # Security engineering team
├── examples/
│   ├── auth-refactor.md                    # Example prompt
│   ├── auth-refactor.prompt-test.yaml      # Example test suite
│   └── secure-login.workflow.yaml          # Example 6-step workflow
├── .github/
│   └── workflows/
│       └── prompt-check.yml                # GitHub Actions — lint, scan, test
├── .github/
│   ├── CODEOWNERS                          # Code ownership (all files → @mylesagnew)
│   └── workflows/
│       ├── ci.yml                          # Pytest (3.10–3.12), ruff, mypy, bandit, pip-audit, build
│       ├── prompt-check.yml                # Lint, scan, and test prompt files on every PR
│       └── release.yml                     # Tag-triggered PyPI publish + SBOM + GitHub Release
├── .pre-commit-config.yaml                 # Pre-commit hooks
├── .promptgenie.yaml.example               # Example project config (rules, suppressions, overrides)
├── SECURITY.md                             # Vulnerability reporting and scanner limitations
├── CONTRIBUTING.md                         # Contributor guide, rule authoring, profile/template schema
├── CHANGELOG.md                            # Version history
├── ROADMAP.md                              # Product roadmap — 5 phases, top-10 features, architecture principles
├── vscode-extension/                       # VS Code / Cursor extension
│   ├── package.json                        # Extension manifest (commands, settings, activation events)
│   ├── package-lock.json                   # Locked npm dependencies (required for npm ci in CI)
│   ├── tsconfig.json
│   ├── src/
│   │   ├── extension.ts                    # Activate / deactivate, event wiring
│   │   ├── runner.ts                       # CLI subprocess wrapper (lint/scan → JSON)
│   │   ├── diagnostics.ts                  # LintOutput / ScanOutput → VS Code Diagnostics
│   │   ├── statusBar.ts                    # Score + issue count in the status bar
│   │   └── types.ts                        # TypeScript interfaces for CLI JSON output
│   └── README.md                           # Extension-specific docs
└── pyproject.toml                          # Modern packaging, coverage gate, dev dependency groups
```

---

## Roadmap

> Full roadmap with technical implementation details: **[ROADMAP.md](ROADMAP.md)**

**Strategic position:** PromptGenie is the secure, terminal-native prompt engineering workbench for developers and DevOps teams — not just a prompt generator.

Prompt lifecycle: **Author → Render → Lint → Scan → Test → Run → Evaluate → Diff → Gate → Audit**

---

### Shipped (v1.0.x)

- [x] `generate`, `lint`, `scan`, `diff`, `adapt`, `test`, `benchmark`, `workflow`, `interactive`, `policy`, `validate`, `pack`, `ci` — full command surface
- [x] Multi-file / directory / zip scanning with zip-slip protection; opt-in LLM semantic analysis (`--llm`) with pre-send secret redaction
- [x] Context packs, workflow mode, plugin registry (14 packs), OWASP LLM Top 10 rules, enterprise lint rules
- [x] GitHub Actions CI (`ci.yml`): pytest 3.10–3.12 with a coverage gate, ruff, mypy, bandit, pip-audit, gitleaks secret scan, version-drift gate, VS Code extension CI, build + wheel smoke test
- [x] SARIF output on lint, scan, and policy for GitHub Code Scanning upload
- [x] Policy-as-code: `policy` command with `--max-risk`, `--min-score`, `--format sarif`, expired allowlist reporting
- [x] Registry hardening: SHA-256 checksums required, HTTPS-only, 1 MiB download cap, fail-closed YAML parsing
- [x] VS Code / Cursor extension: inline diagnostics, status bar score, command palette, bounded subprocess output
- [x] Native token compression (`compress` / `optimize`) — content-routed, fence-aware, dependency-free — plus `tokens` (read-only savings inspector)
- [x] NousResearch Hermes integration — `hermes` target profile + built-in OpenAI-compatible provider
- [x] Security posture: metadata-only run history by default, SBOM attestation + build provenance, CodeQL, OpenSSF Scorecard, Dependabot, and a formal [THREAT_MODEL.md](THREAT_MODEL.md)
- [x] 1,541 tests · ~82% coverage (gate 81%) · 0 ruff issues · 0 mypy errors

---

### Phase 1 — Terminal and Pipeline Foundations

- [x] Universal stdin/stdout — `-` sentinel on `lint`, `scan`, `diff`, `adapt`; `safe_read_text("-")` reads stdin with same size guard; `<stdin>` label in all output formats
- [x] Stable structured output — `schema_version: "1.0"` on all JSON outputs; `diag_console` (stderr) for diagnostics; `is_structured_mode()` suppresses banners in JSON/SARIF/YAML/NDJSON modes
- [x] Strict exit code contract — `0` OK · `1` failure · `2` usage · `3` provider · `4` template · `5` test · `6` secrets · `7` timeout · `130` interrupted; `PromptGenieError(code, hint)`; `handle_error()` writes to stderr; SIGINT → 130
- [x] Shell completion — `promptgenie completion install zsh|bash|fish`; `show`, `status`, `refresh-cache`; dynamic cache at `~/.cache/promptgenie/completions.json`
- [x] `promptgenie doctor` — Python version, config, optional extras, provider keys, Ollama, shell completion; remediation hints; `--format json` with `schema_version: "1.0"`
- [x] Side-by-side diff — `diff --side-by-side` Rich two-column table; semantic section matching; `diff --format json|yaml|markdown`
- [x] Renderer profiles — `ColorMode` (auto|always|never); `--color` global flag; `NO_COLOR`/`FORCE_COLOR` env vars; `diag_console` separates data from diagnostics; `init_renderer()` wired into CLI group
- [x] Interactive variable resolver — `{{name}}`, `{{name:type:default}}` placeholders; `--var`, `--vars`, `--vars-schema`, `--no-input` on `generate`; env `PG_<NAME>`; secret masking; type coercion; `VarResolutionError` exits 2

---

### Phase 2 — PromptSpec and Run Engine

- [x] Declarative PromptSpec YAML/JSON — `version: 1` with `name`, `target`, `template`, `mode`, `vars`, `context`, `policy`, `provider`, `model`, `output_contract`, `run`; JSON Schema at `promptgenie/schemas/promptspec.schema.json`; `spec init/render/validate/schema`
- [x] `promptgenie run` — load spec → resolve vars → build context → secrets gate → render → send to provider → stream response → persist run; `--dry-run`, `--stream`, `--require-clean`, `--provider`, `--model`, `--timeout`, `--no-history`, `--tee`, `--format ndjson`
- [x] Streaming response mode — `asyncio`-based; NDJSON events (`start/token/warning/error/done`); `--tee output.md` writes assembled response to file; `--format ndjson` for piping
- [x] Variable files and env binding — `--vars prod.yaml`, `--var k=v`, `--env-prefix PG_`; secret masking; `vars list` + `vars inspect --redacted` shows source per variable
- [x] Context builder — 8 source types: `file`, `glob`, `stdin`, `env`, `cmd`, `git_diff`, `git_staged`, `url`; `.promptignore`; 4 strategies; SHA-256 + token estimates; `context build` command
- [x] Provider abstraction — `BaseProvider` with `async complete()` + `stream()`; `ProviderCapabilities`; `AnthropicProvider` + `OpenAICompatProvider`; config at `~/.config/promptgenie/providers.yaml`
- [x] `promptgenie provider add/list/remove/show/doctor` — first-class Ollama/local provider management; `provider doctor` probes reachability

---

### Phase 3 — SecDevOps Guardrails ✅

- [x] `promptgenie analyze` — aggregate `lint + scan + policy + custom rules`; unified OWASP-aligned finding model; SARIF/JSON/Rich output
- [x] Policy-as-code v2: `--policy promptgenie.policy.yaml`; `--explain` mode; `external_model_send` gate; policy discovery chain; SARIF multi-run output
- [x] Data leakage detector: JWTs, database URLs, internal hostnames, emails, phone numbers, credit cards, SSNs; `promptgenie redact`; `[REDACTED:LABEL]` placeholders; `--diff`
- [x] `promptgenie redteam` — 13 OWASP LLM Top 10 attack packs; offline heuristic susceptibility judge; `--categories`, `--fail-on-susceptible`
- [x] Local-first routing policy: `RoutingConfig`; condition rules (`contains_secrets`, `classification ==`, `*`); `routing.default` fallback
- [x] Credential management: `promptgenie auth login|logout|status`; keyring, env, 1Password, AWS SSM, GCP Secret Manager, Azure Key Vault; `ref:` pointer resolution at runtime
- [x] Audit log: `promptgenie audit list|show|export|verify`; SQLite; SHA-256 tamper-evident hash chain; JSON/CSV/NDJSON export
- [x] Air-gapped mode: `security.airgap: true` in config; blocks all external provider calls; local providers (Ollama) still work

---

### Phase 4 — Evaluation and Regression Testing ✅

- [x] Multi-model matrix evaluation: `--models claude,gpt-4.1,ollama/llama3.1`; `asyncio` parallel with semaphore; per-model latency/cost/safety/rubric metrics; `--runs N`
- [x] Eval suites: `promptgenie eval init|run|compare|approve`; 11 assertion types: `contains`, `regex_match`, `json_path`, `semantic_similarity`, `judge_rubric`, `refuses_instruction_override`, and more; snapshot store at `evals/.snapshots/`
- [x] Baseline regression gates: `--save-baseline`, `--compare --fail-on-regression`; per-metric thresholds; exits `EXIT_REGRESSION = 8` on breach
- [x] GitHub Actions native reporter: `::error`/`::warning` annotations; Markdown step summary; SARIF 2.1.0 upload; auto-detected via `GITHUB_ACTIONS`
- [x] Changed-prompt detection: `--changed`; `git diff --name-only`; dependency-aware (template → dependents, policy → all specs)

---

### Phase 5½ — Event Infrastructure and Workspace Schema ✅

- [x] Unified Event model (`EventKind`, `Event`, `EventBus`, `EventFormatter`) — typed pub/sub for every lifecycle moment; NDJSON serialisation; `run_spec()` `event_bus=` kwarg; backward-compatible with `on_token=`/`on_event=` callbacks (v1.6.0)
- [x] Four built-in `EventFormatter` implementations: `NDJSONFormatter`, `TokenOnlyFormatter`, `RichFormatter`, `SilentFormatter` — `@runtime_checkable` Protocol for custom formatters (v1.6.0)
- [x] Policy command hardening: `max_risk` gate scoped to scan findings only (not lint); expired allowlist warnings in text/JSON/SARIF output; threshold detail in violation messages (v1.6.0)
- [x] `promptgenie/schemas/workspace.schema.json` — JSON Schema (Draft 2020-12) for `.promptgenie.yaml`; `additionalProperties: false` at every level; VS Code `yaml-language-server` compatible (v1.7.0)
- [x] `WorkspaceConfig` + `DefaultsConfig` dataclasses on `PromptGenieConfig`; `load_config()` parses `workspace:` and `defaults:` blocks (v1.7.0)
- [x] `validate_workspace_config()` — pure-Python structural validator; no `jsonschema` dep; catches unknown keys, type errors, bad enums, ISO date formats, missing required fields (v1.7.0)
- [x] `config validate` — CI-safe schema validation command; exits 0/1/2; `--format json` for machine-readable output (v1.7.0)
- [x] `config init` — scaffold `.promptgenie.yaml` with `$schema` pointer and `yaml-language-server` comment; `--name`, `--force` (v1.7.0)

---

### Phase 5 — Advanced TUI and Ecosystem ✅

- [x] Full-screen Textual TUI: `promptgenie tui`; file-tree navigator, Markdown editor, findings panel, score/token/provider status bar; `Ctrl+S/R/L/D/T/Q` bindings; graceful degradation without `textual`
- [x] Guided prompt wizard: `promptgenie wizard`; 8-step Q&A → PromptSpec YAML + rendered Markdown; `--out`, `--spec-out`, `--no-spec`
- [x] Smart command palette: `promptgenie palette`; Textual fuzzy finder across commands, templates, context packs, and recent history; readline fallback; `--print-only` for shell piping
- [x] Prompt history: `promptgenie history list|show|diff|replay|export|clear`; SQLite; SHA-256 content-hash deduplication; `--search`, `--provider`, `--status` filters
- [x] Watch mode: `promptgenie watch`; `watchfiles` optional extra with polling fallback; `--debounce`; debounced Rich `Live` dashboard
- [x] Template command group: `promptgenie template list|show|render|validate|new|edit`; layered resolution (project → user → built-in); `$EDITOR` integration; re-validates after `edit`
- [x] Prompt lockfiles: `promptgenie lock`; SHA-256 hashes of spec, template, policy, context sources, provider/model; `--check` for CI; `--strict` for missing optional files
- [x] Plugin SDK: 5 entry-point groups (`promptgenie.providers`, `.rules`, `.renderers`, `.context_sources`, `.evaluators`); `plugin list|doctor|scaffold|install`

---

### Phase 6 — Governance, SSO, and Cloud Sync *(in progress)*

- [x] `promptgenie fmt` — canonical formatter for Markdown prompts and PromptSpec YAML: ATX heading normalisation, blank-line structure, trailing-whitespace trim, single final newline, canonical key sort; fence-aware; comment-preserving YAML reorder via optional `ruamel.yaml` (`promptgenie[fmt]`); in-place by default, `--check` (CI-safe), `--diff`, `--format json`; idempotent
- [x] `promptgenie make` — YAML task graph (`promptgenie.make.yaml`): `needs:` dependency ordering, `--changed` filtering on per-task `inputs:` globs, `--parallel N`, fail-fast with `--keep-going`, `--dry-run`, `--list`, `--format json`; compatible with Make, just, Taskfile
- [x] Prompt registry — `promptgenie registry push|pull|list|tags|show|verify|rm|prune|search`; content-addressable OCI-inspired store; signed manifests (minisign/cosign), fail-closed digest verification, digest pins; **Phase B.1**: remote OCI registries (`--remote`, `registry login/logout`, blob dedup, untrusted-server verification) via `promptgenie[registry-remote]`. See [docs/registry-design.md](docs/registry-design.md)
- [ ] SSO / OIDC credential binding — `registry login --sso`; OIDC device flow; per-user audit attribution; `PROMPTGENIE_TOKEN` env var for CI *(registry Phase B.2)*
- [ ] Team policy server — central policy fetch on every run; org-wide `disabled_rules`, allowlists, routing rules; policy version pinned in lockfile
- [ ] Remote eval runners — offload matrix evaluations to a cloud runner pool; cost and latency budgets enforced server-side
- [ ] VSCode extension — Phase 2 (inline eval results, baseline delta badge, history sidebar, lockfile status)

---

## Configuration

See **[docs/configuration.md](docs/configuration.md)** for the full `.promptgenie.yaml` reference — scanner/linter rule config, allowlists, routing, security settings — and the `promptgenie config` commands.

---

## Development

Dependencies are locked in `uv.lock`. Install [uv](https://docs.astral.sh/uv/) then:

```bash
git clone https://github.com/mylesagnew/promptgenie.git
cd promptgenie
uv sync --extra dev
```

**Run tests:**
```bash
uv run pytest tests/
```

**Lint and format:**
```bash
uv run ruff check promptgenie/
uv run ruff format promptgenie/
uv run mypy promptgenie
```

**Security checks:**
```bash
uv run bandit -r promptgenie/ -ll
uv run pip-audit --skip-editable --progress-spinner off
```

**Build:**
```bash
uv build
uv run --with twine twine check dist/*
```

**Generate SBOM:**
```bash
uv run cyclonedx-py environment --output-format json --outfile sbom.cyclonedx.json
```

**Releasing** (maintainers only):
1. Update `version` in `pyproject.toml` and add a `[X.Y.Z]` entry to `CHANGELOG.md`.
2. Run `uv lock` to update the lockfile.
3. Commit, push to `main`, then push a semver tag: `git tag vX.Y.Z && git push origin vX.Y.Z`.
4. The `release.yml` workflow runs the full gate, builds, publishes to PyPI via Trusted Publishing, generates GitHub artifact attestations, generates a CycloneDX SBOM, and creates a GitHub Release — all without a stored API token.

> **One-time setup required:** Create a `release` protected environment in GitHub Settings → Environments (add required reviewer). Configure a PyPI Trusted Publisher for this repo pointing at `.github/workflows/release.yml`.

See [SECURITY.md](SECURITY.md) for the vulnerability reporting process and scanner limitations.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the contributor guide, rule authoring docs, and profile/template schema reference.

See [CHANGELOG.md](CHANGELOG.md) for a full version history.

See [ROADMAP.md](ROADMAP.md) for the full product roadmap with implementation details, architecture principles, and the optional extras plan.

---

## License

MIT
