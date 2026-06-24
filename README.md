<p align="center">
  <img src="assets/logo.png" alt="PromptGenie" width="600" />
</p>

# PromptGenie

**Secure prompt engineering for AI agents and engineering teams.**

PromptGenie is a CLI that turns rough task descriptions into optimised, tool-specific, security-checked prompts — and executes them end-to-end. It ships a built-in linter, multi-file security scanner, diff engine, test runner, model benchmarker, context pack system, workflow engine, CI integration, quality scoring, token estimation, full UNIX-composable pipeline, and a declarative run engine that sends prompts to any provider (Anthropic, OpenAI, Ollama, LM Studio, vLLM) with streaming, variable resolution, context assembly, policy gates, and run history. v1.6.0 adds a unified `EventBus` / `EventFormatter` infrastructure so every lifecycle event — run tokens, lint findings, policy violations, eval results — flows through a single typed channel that commands, tests, and future integrations all subscribe to. v1.7.0 adds a formal JSON Schema for `.promptgenie.yaml`, `workspace:` and `defaults:` config blocks, `config validate` for CI-safe schema checking, and `config init` to scaffold a new config with editor autocomplete wired up.

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

## Commands

| Command | Description |
|---|---|
| `generate` | Build an optimised prompt from a rough task description; resolves `{{variable}}` placeholders |
| `lint` | Check a prompt file for quality and structural issues |
| `scan` | Scan files, directories, and zip archives for security risks; opt-in LLM semantic analysis |
| `policy` | CI policy gate — fail the build if findings breach configurable thresholds; outputs text, JSON, or SARIF |
| `diff` | Compare two prompt versions — token, score, section, and risk delta; `--side-by-side`, `--format json\|yaml\|markdown` |
| `adapt` | Translate a prompt from one target profile to another |
| `test` | Run a declarative prompt test suite (exits 5 on assertion failures) |
| `benchmark` | Run a prompt against a Claude model and score the output |
| `workflow` | Generate a staged prompt chain from a `.workflow.yaml` file |
| `doctor` | Self-check — Python version, config, provider keys, extras, Ollama, shell completion |
| `completion install` | Install tab-completion for zsh, bash, or fish |
| `completion show` | Print the completion script to stdout |
| `completion status` | Show per-shell installation state and cache freshness |
| `completion refresh-cache` | Rebuild the dynamic completion cache |
| **Phase 2** | |
| `spec init` | Scaffold a new PromptSpec YAML file |
| `spec validate` | Validate a PromptSpec against the JSON Schema |
| `spec render` | Resolve variables and preview the assembled prompt |
| `spec schema` | Print the PromptSpec JSON Schema |
| `run` | Execute a PromptSpec end-to-end (vars → context → gate → send → stream) |
| `context build` | Assemble context from files, globs, git diff, stdin, URLs |
| `provider list` | List all configured AI providers |
| `provider add` | Add or update a provider (Ollama, OpenAI, vLLM, LM Studio, …) |
| `provider doctor` | Test provider reachability and configuration |
| `provider show` | Show capabilities and config for a provider |
| `vars list` | List `{{variable}}` placeholders declared in a spec |
| `vars inspect` | Show resolved value + source for each variable |
| `compress` / `optimize` | Shrink a prompt's token footprint with native content-routed compression; `--max-tokens` budget, `--aggressive`, `--format json` |
| `pack list` | List available context packs |
| `pack show` | Preview a context pack's rendered content |
| `pack inject` | Inject a context pack into an existing prompt file |
| `pack init` | Create a new blank context pack |
| `pack search` | Search the registry index for available rule/context packs |
| `pack install` | Download and install a pack from the registry |
| `pack update` | Fetch the remote registry and install/update all packs |
| `pack dirs` | Show registry and user rules directories |
| `ci init` | Scaffold GitHub Actions and pre-commit hooks into a project |
| `ci status` | Check which CI integrations are active |
| `list-targets` | Show all available model profiles |
| `list-templates` | Show all available prompt templates |
| `validate` | Validate YAML config files — profiles, templates, context packs, workflows, prompt tests |
| `validate-profiles` | Validate all profile YAML files against the profile schema |
| `interactive` | Launch the guided menu — generate, lint, scan, diff, test, and more |
| **Phase 3 — SecDevOps** | |
| `analyze` | Aggregate lint + scan with unified OWASP-aligned finding model; SARIF/JSON/Rich |
| `redact` | Replace secrets and PII with `[REDACTED:LABEL]` placeholders |
| `redteam` | 13 offline OWASP LLM Top 10 attack packs; heuristic susceptibility judge |
| `auth login` | Store provider credentials in keyring or env |
| `auth logout` | Remove stored credentials |
| `auth status` | Show credential resolution for all providers |
| `audit list` | View tamper-evident audit log (SQLite, SHA-256 chain) |
| `audit export` | Export audit log to JSON/CSV/NDJSON |
| `audit verify` | Verify the audit chain has not been tampered with |
| `config show` | Show current effective config (rich / JSON / YAML) |
| `config set` | Set a config key (e.g. `security.airgap true`) |
| `config get` | Print the current value of a config key |
| `config validate` | Validate `.promptgenie.yaml` against the workspace schema; exits 0/1/2; `--format json` for CI |
| `config init` | Scaffold a new `.promptgenie.yaml` with JSON Schema pointer and editor autocomplete comment |
| **Phase 4 — Evaluation** | |
| `evaluate` | Multi-model matrix evaluation with latency, cost, safety, and rubric metrics |
| `eval init` | Scaffold a new eval suite YAML file |
| `eval run` | Run an eval suite against a prompt or spec |
| `eval compare` | Compare current run to a baseline; exit 8 on regression |
| `eval approve` | Approve current snapshots as the new baseline |
| **Phase 5 — TUI and Ecosystem** | |
| `tui` | Full-screen Textual TUI (requires `pip install "promptgenie[tui]"`) |
| `wizard` | Guided 8-step prompt-building Q&A |
| `palette` | Fuzzy command palette across commands, templates, and history |
| `history list` | Browse run history with filtering |
| `history show` | Inspect a single run's events and response |
| `history diff` | Diff two historical responses |
| `history replay` | Re-run a historical spec (supports `--dry-run`) |
| `watch` | File watcher — re-runs lint/scan/policy on change |
| `template list` | List templates (project → user → built-in resolution) |
| `template render` | Render a template with variables |
| `lock` | Create a lockfile with SHA-256 hashes of all spec dependencies |
| `plugin list` | List installed plugins |
| `plugin scaffold` | Scaffold a new plugin stub |

---

### `generate`

Generate an optimised prompt from a rough task description.

```bash
promptgenie generate "refactor the auth module to use JWT" \
  --target claude-code \
  --mode exhaustive
```

```bash
promptgenie generate "threat model the payment API" \
  --target claude \
  --template threat-model \
  --context "Django REST API, Stripe integration, PostgreSQL" \
  --out payment-threat-model.md
```

**Options:**

| Flag | Description |
|---|---|
| `--target`, `-t` | Target AI tool. Auto-inferred if omitted. |
| `--template`, `-T` | Template ID (e.g. `threat-model`, `agentic-task`). Auto-inferred if omitted. |
| `--context`, `-c` | Project or task context. |
| `--constraints`, `-x` | Constraints or forbidden actions. |
| `--output-format`, `-f` | Desired output format for the generated prompt. |
| `--mode`, `-m` | `minimal` / `standard` / `exhaustive` |
| `--out`, `-o` | Save prompt to file. |
| `--pack`, `-p` | Context pack ID to inject (e.g. `react-supabase-app`). |
| `--no-lint` | Skip inline lint pass. |
| `--no-scan` | Skip inline security scan. |

**Modes:**

| Mode | Use for |
|---|---|
| `minimal` | Reasoning models, simple tasks, low token budget |
| `standard` | Default — balanced structure and detail |
| `exhaustive` | Agentic tools, complex tasks, security-critical workflows |

---

### `lint`

Check a prompt file for quality and structural issues.

```bash
# Default rich terminal output
promptgenie lint my-prompt.md

# Machine-readable JSON (CI scripts, dashboards)
promptgenie lint my-prompt.md --format json

# SARIF for GitHub code scanning
promptgenie lint my-prompt.md --format sarif --out lint-results.sarif

# Read from stdin — pipe-friendly
cat my-prompt.md | promptgenie lint - --format json
echo "Do the thing." | promptgenie lint - --format json | jq '.issues[]'
```

**What it checks:**

- Vague verbs (`help`, `fix`, `improve`, `make better`)
- Multiple tasks chained in one prompt
- Missing target AI tool
- Overly broad scope (`fix the whole app`, `update all files`)
- Missing stop conditions (agentic prompts)
- Missing scope definition
- Missing forbidden actions
- Missing output format
- Missing success criteria
- Dangerous agentic instructions (`do whatever it takes`, `deploy to production`, `drop the table`)

Exits `1` if any HIGH severity issues are found — safe to use in CI.

**Options:**

| Flag | Description |
|---|---|
| `--format` | Output format: `rich` (default) / `json` / `sarif` |
| `--out`, `-o` | Write output to file instead of stdout |

---

### `scan`

Scan one or more prompt files, directories, or zip archives for security risks, with an optional LLM semantic analysis layer.

```bash
# Single file — original behaviour preserved
promptgenie scan my-prompt.md

# Read from stdin
cat my-prompt.md | promptgenie scan -
cat my-prompt.md | promptgenie scan - --format json | jq '.findings[]'

# Entire directory (recursive)
promptgenie scan ./prompts/

# Zip archive — all contained prompt files scanned, zip-slip protected
promptgenie scan prompts-bundle.zip

# Mix of files, directories, and zips
promptgenie scan prompt1.md ./more-prompts/ archive.zip

# Machine-readable JSON (aggregate output for multi-file scans)
promptgenie scan ./prompts/ --format json

# SARIF for GitHub code scanning upload (all files in one run)
promptgenie scan ./prompts/ --format sarif --out scan-results.sarif

# Opt-in LLM semantic analysis (requires OPENAI_API_KEY)
promptgenie scan my-prompt.md --llm

# Air-gap / privacy mode — suppress all LLM network calls
promptgenie scan my-prompt.md --llm --no-external-llm

# CI gate — fail on any finding at or above MEDIUM
promptgenie scan ./prompts/ --fail-on-severity MEDIUM

# Show which files were skipped (size cap, wrong suffix, quota)
promptgenie scan ./prompts/ --show-skipped
```

**What it flags (heuristic patterns):**

| Category | Pattern examples flagged |
|---|---|
| Secrets | API keys, tokens, AWS credentials, private keys embedded in prompt |
| Prompt injection | Instruction overrides, system prompt extraction, output suppression |
| Agent permissions | Unrestricted filesystem access, arbitrary code execution, unsupervised publishing |
| RAG risks | Instructions that follow retrieved content, untrusted input pipelines |
| Chained risks | Web fetch + action (email/deploy/write) without approval gate |

> **Confidence and severity:** findings use `HIGH`/`CRITICAL` labels to reflect the *severity of the pattern class*, not the certainty of detection. Each finding is a heuristic signal — review before treating as a confirmed vulnerability. The scanner uses static regex with NFKC Unicode normalisation and does not detect synonym substitution, indirect reference, or multi-turn attacks. See `tests/test_scanner_adversarial.py` for documented detection gaps.

Exits `1` on CRITICAL or HIGH findings — safe to use in CI or pre-commit hooks.

The scanner reports the **class** of secret found, never the secret value itself.

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--format` | `rich` | Output format: `rich` / `json` / `sarif` |
| `--out`, `-o` | — | Write output to file instead of stdout |
| `--llm` | off | Enable opt-in LLM semantic analysis (requires `OPENAI_API_KEY`) |
| `--no-external-llm` | off | Suppress all LLM network calls (privacy / air-gap mode) |
| `--max-files N` | 500 | Cap total files collected across all paths |
| `--max-bytes N` | 10485760 | Cap total uncompressed bytes (default 10 MB) |
| `--max-file-bytes N` | 1048576 | Skip individual files over this size (default 1 MB) |
| `--fail-on-severity` | — | Exit 1 when any finding meets or exceeds this level (`LOW`/`MEDIUM`/`HIGH`/`CRITICAL`) |
| `--show-skipped` | off | Print files excluded due to size cap, wrong suffix, or quota |
| `--config PATH` | — | Path to `.promptgenie.yaml` |
| `--no-config` | — | Ignore any `.promptgenie.yaml` |
| `--best-effort` | off | Fall back to built-in defaults on missing config |

**Multi-file resource limits:**

Files are collected before scanning. Limits are applied per-collection run:
- Files with unsupported suffixes are skipped (`wrong_suffix`)
- Files over `--max-file-bytes` are skipped (`too_large`)
- Once total collected bytes reach `--max-bytes` or file count reaches `--max-files`, remaining files are skipped (`quota_exceeded`)
- Use `--show-skipped` to see which files were excluded and why

**Zip archive safety:**

Each zip member path is validated before extraction — absolute paths, `..` traversal sequences, resolved paths escaping the extraction root, and Unix symlinks all raise a hard error and skip the archive. The member count is capped at 1 000.

**LLM semantic analysis (`--llm`):**

Off by default — explicit opt-in required. When enabled:
- Content is pre-scanned for secrets and redacted before any text leaves the host
- Content is capped at 8 000 characters per file before the API call
- API key is read from `OPENAI_API_KEY` (or a custom env var via config)
- Pass `--no-external-llm` to block all network calls even if `--llm` is set (air-gap / CI privacy mode)
- LLM findings are included in JSON output under `files[].llm`; they do not affect the heuristic risk level

> **Privacy:** Never pass `--llm` with prompt files that contain real credentials, PII, or internal architecture details not intended for external transmission. Use `--no-external-llm` in air-gapped CI pipelines.

**Scan JSON output** includes `category` (rule category: `secret`, `injection`, `permission`, `rag`, `obfuscation`) and `source` (`builtin` / `registry` / `custom`) on every finding.

**Secret rule IDs** — each secret pattern has a unique code for precise suppression:

| Code | Pattern |
|---|---|
| `SEC_SECRET_APIKEY` | Generic `sk-` / `api_key` patterns |
| `SEC_SECRET_TOKEN` | Generic bearer tokens |
| `SEC_SECRET_OPENAI` | OpenAI `sk-` keys |
| `SEC_SECRET_GOOGLE` | Google API keys (`AIza…`) |
| `SEC_SECRET_SLACK` | Slack tokens (`xox[bpoas]-…`) |
| `SEC_SECRET_PRIVKEY` | PEM private key headers |
| `SEC_SECRET_GITHUB` | GitHub PATs (`ghp_…`, `github_pat_…`) |
| `SEC_SECRET_AWS_KEY` | AWS access key IDs (`AKIA…`) |
| `SEC_SECRET_AWS_SECRET` | AWS secret access key patterns |

Use `SEC_SECRET` as an alias in `enabled_rules` / `disabled_rules` config to target all secret rules at once.

---

### `policy`

CI policy gate — run lint and scan together and exit non-zero if findings exceed configurable thresholds. Designed to be dropped into any GitHub Actions step or pre-push hook.

```bash
# Fail if any HIGH-or-above security finding exists (default)
promptgenie policy my-prompt.md

# Fail if any CRITICAL finding exists, AND lint score drops below 70
promptgenie policy my-prompt.md --max-risk CRITICAL --min-score 70

# Allow up to 2 MEDIUM findings before failing
promptgenie policy my-prompt.md --max-risk MEDIUM --max-findings 2

# Machine-readable JSON output for CI dashboards
promptgenie policy my-prompt.md --format json
```

**Exit codes:**

| Code | Meaning |
|---|---|
| `0` | All thresholds passed — prompt is clean |
| `1` | One or more thresholds exceeded — findings printed |
| `2` | Usage / configuration error (bad file path, invalid config) |

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--max-risk` | `HIGH` | Fail if any security finding is at or above this level (`CRITICAL` / `HIGH` / `MEDIUM` / `LOW`) |
| `--max-findings` | `0` | Fail if total qualifying findings exceed this count; `0` = any qualifying finding fails |
| `--min-score` | `0` | Fail if lint quality score is below this value; `0` = lint score not checked |
| `--format` | `text` | Output format: `text` (Rich table), `json` (machine-readable), or `sarif` (SARIF v2.1.0) |
| `--config PATH` | — | Path to `.promptgenie.yaml` |
| `--no-config` | — | Ignore any `.promptgenie.yaml` |

**Expired allowlist warnings** — when the loaded config contains allowlist entries that have expired (or have a malformed `expires` date), the policy command surfaces them:
- `--format json`: `allowlist_warnings` array in the output document
- `--format text`: `⚠ Allowlist: …` line per expired entry in the Rich output

This keeps stale suppressions visible in CI rather than silently inactive.

**Example GitHub Actions steps:**

```yaml
# Text output with Rich table — good for human-readable CI logs
- name: PromptGenie policy gate
  run: promptgenie policy my-prompt.md --max-risk HIGH --min-score 75

# SARIF output — upload to GitHub Code Scanning
- name: PromptGenie policy (SARIF)
  run: promptgenie policy my-prompt.md --format sarif --max-risk MEDIUM > policy.sarif

- name: Upload SARIF results
  uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: policy.sarif
```

---

### `diff`

Compare two prompt versions side-by-side — tokens, quality scores, section changes, lint changes, and security finding changes.

```bash
promptgenie diff v1.md v2.md --target claude-code
promptgenie diff v1.md v2.md --target claude-code --unified

# Diff stdin against a saved version
cat new-draft.md | promptgenie diff - v1.md
```

**What it shows:**

| Panel | Content |
|---|---|
| **Summary** | Tokens, quality score, lint count, security findings — A vs B with delta |
| **Quality Score Breakdown** | All 7 dimensions side-by-side with per-dimension delta |
| **Section Changes** | Each `## Section` marked ADDED / REMOVED / CHANGED / UNCHANGED with inline line diffs |
| **Lint Changes** | Issues resolved in v2 vs new issues introduced |
| **Security Changes** | Findings resolved in v2 vs new findings introduced |

**Options:**

| Flag | Description |
|---|---|
| `--target`, `-t` | Profile to use for quality scoring (default: `claude`) |
| `--unified`, `-u` | Show full colour-coded unified diff |

---

### `adapt`

Translate a prompt written for one target into another — rewriting model-specific language, preserving agentic safety sections by default, and adding sections required by the destination profile.

```bash
# Claude Code → Cursor (same agentic category — all safety sections kept)
promptgenie adapt my-prompt.md --from claude-code --to cursor

# Claude Code → ChatGPT (safety sections preserved by default)
promptgenie adapt my-prompt.md --from claude-code --to chatgpt --out chatgpt-prompt.md

# Explicitly strip safety sections when adapting to a non-agentic target
promptgenie adapt my-prompt.md --from claude-code --to chatgpt --strip-agentic-safety

# Show original alongside adapted version
promptgenie adapt my-prompt.md --from claude-code --to gemini --show-original

# Adapt from stdin
cat my-prompt.md | promptgenie adapt - --from claude-code --to cursor
```

**What it does:**

| Scenario | Behaviour |
|---|---|
| Agentic → Agentic (e.g. `claude-code` → `cursor`) | Keeps all sections, rewrites model name |
| Agentic → General, default (e.g. `claude-code` → `chatgpt`) | **Preserves** scope / stop conditions / constraints; notes in change log |
| Agentic → General with `--strip-agentic-safety` | Drops scope / stop conditions / constraints, warns you, trims tokens |
| Missing required sections | Generates default content from the destination profile |
| Forbidden patterns in content | Replaces with `[REMOVED — forbidden by target profile]` |

> **Safety-first default:** agentic safety sections (stop conditions, forbidden actions, scope, constraints, verification) are kept when adapting to a non-agentic target. Use `--strip-agentic-safety` to opt in to stripping them — useful when you need a minimal token footprint and have verified the target context is safe.

Outputs a colour-coded change log (KEPT / REWRITTEN / ADDED / DROPPED per section) and a score and token summary with delta.

**Options:**

| Flag | Description |
|---|---|
| `--from` | Source target profile |
| `--to` | Destination target profile |
| `--out`, `-o` | Save adapted prompt to file |
| `--show-original` | Print original alongside adapted version |
| `--strip-agentic-safety` | Remove agentic safety sections when adapting to a non-agentic target (off by default) |

---

### `compress` / `optimize`

Shrink a prompt's (or assembled context's) token footprint *before* it reaches the model — same content, fewer tokens. A native, dependency-free engine inspired by [headroom](https://github.com/headroomlabs-ai/headroom): content-routed structural techniques, no Rust toolchain or heavy ML deps. `optimize` is an alias for `compress`.

```bash
# Compress to stdout (lossless default tier)
promptgenie compress prompt.md

# Write the smaller version to a file
promptgenie compress prompt.md --out smaller.md

# Hit a token budget — enables every technique, exits 1 if it can't fit
promptgenie compress prompt.md --max-tokens 4000

# Add the aggressive (mildly lossy) tier and show what changed
promptgenie compress prompt.md --aggressive --diff

# Machine-readable savings report
promptgenie compress prompt.md --format json | jq '.tokens_saved'

# Pipe-friendly
cat context.md | promptgenie compress -
```

**Techniques** (fence-aware — fenced ```code``` blocks are never altered):

| Technique | Tier | What it does |
|---|---|---|
| `trim-trailing-ws` | default | Strip trailing whitespace at line ends |
| `collapse-blank-lines` | default | Collapse 2+ consecutive blank lines into one |
| `json-compact` | default | Minify whole-document JSON and ```json fenced blocks |
| `strip-html-comments` | aggressive | Remove `<!-- HTML comments -->` from prose |
| `collapse-spaces` | aggressive | Collapse runs of inline spaces in prose (keeps indentation) |
| `dedupe-log-lines` | aggressive | Fold 3+ identical consecutive lines into `line (×N)` |

The **default** tier is lossless / near-lossless for Markdown prompts. The **aggressive** tier (via `--aggressive`, or automatically when `--max-tokens` is set) trades a little fidelity for higher savings — ideal for build logs, search dumps, and verbose tool output. Run `promptgenie compress --list-techniques` for the live catalogue.

**Options:**

| Flag | Description |
|---|---|
| `--out`, `-o` | Write compressed output to a file instead of stdout |
| `--max-tokens N` | Target token budget; enables all techniques; exits 1 if the result still exceeds N |
| `--techniques T,T` | Run an explicit subset of techniques (overrides the tiers) |
| `--aggressive` | Add the aggressive tier on top of the defaults |
| `--list-techniques` | Print the technique catalogue and exit |
| `--diff` / `--dry-run` | Report per-technique savings to stderr (`--dry-run` skips writing/emitting output) |
| `--format` | Output format: `text` (default) / `json` / `yaml` |

Exits `0` on success, `1` when a `--max-tokens` budget cannot be met, `2` on a bad technique name or unreadable file.

---

### `test`

Run a declarative prompt test suite defined in a `.prompt-test.yaml` file. Assert content, structure, quality scores, token budgets, lint severity, and security risk — all without sending the prompt to a model.

```bash
promptgenie test my-suite.prompt-test.yaml
promptgenie test my-suite.prompt-test.yaml --verbose
```

**Test file format:**

```yaml
prompt: path/to/my-prompt.md   # relative to the test file
target: claude-code
description: "Auth refactor prompt — safety and quality assertions"

tests:
  - name: has explicit stop conditions
    must_include:
      - "Stop and ask"
      - "approval"

  - name: scope is restricted
    must_include:
      - "src/auth"
    must_not_include:
      - "entire codebase"
      - "fix everything"

  - name: no unsafe agentic patterns
    must_not_include:
      - "do whatever it takes"
      - "deploy to production"

  - name: required sections present
    required_sections:
      - Objective
      - Scope
      - Stop Conditions
      - Acceptance Criteria

  - name: quality score threshold
    min_score: 80

  - name: token budget
    max_tokens: 500

  - name: no high lint issues
    max_lint_severity: MEDIUM

  - name: no high security findings
    max_security_risk: MEDIUM

  - name: no production deployment pattern
    regex_not_match:
      - "deploy to (prod|production|live)"
```

**All assertion types:**

| Assertion | What it checks |
|---|---|
| `must_include` | Phrase is present in the prompt (case-insensitive) |
| `must_not_include` | Phrase is absent from the prompt |
| `required_sections` | `## Section` heading exists |
| `regex_match` | Regex matches anywhere in the prompt |
| `regex_not_match` | Regex does not match |
| `min_score` | Quality score ≥ threshold |
| `max_tokens` | Token count ≤ budget |
| `max_lint_severity` | No lint issue worse than HIGH / MEDIUM / LOW |
| `max_security_risk` | No security finding worse than CRITICAL / HIGH / MEDIUM / LOW |

Exits `0` on full pass, `1` on any failure — safe to run in CI or as a pre-commit hook.

**Options:**

| Flag | Description |
|---|---|
| `--verbose`, `-v` | Show all assertions including passing ones |

See [`examples/auth-refactor.prompt-test.yaml`](examples/auth-refactor.prompt-test.yaml) for a full working example.

---

### `benchmark`

Run a prompt against a Claude model, score the response across 6 rubric dimensions using a judge model, and report token usage, latency, and estimated cost. Compare two prompts head-to-head across multiple runs.

```bash
# Requires ANTHROPIC_API_KEY
export ANTHROPIC_API_KEY=sk-ant-...

# Single run
promptgenie benchmark my-prompt.md

# Specific model, print full response
promptgenie benchmark my-prompt.md --model claude-opus-4-8 --show-response

# Average scores across 3 runs
promptgenie benchmark my-prompt.md --runs 3

# Compare two prompt versions head-to-head
promptgenie benchmark v1.md --compare v2.md --runs 3

# Save model response to file
promptgenie benchmark my-prompt.md --out response.md
```

**Rubric dimensions:**

| Dimension | What it measures |
|---|---|
| Relevance | Did the response address the prompt objective? |
| Completeness | Were all tasks, sections, and requirements covered? |
| Format Compliance | Did the output match the requested format? |
| Safety Compliance | Did the response respect constraints and stop conditions? |
| Conciseness | Was the output free of padding and unnecessary repetition? |
| Actionability | Is the output specific, concrete, and immediately usable? |

**What it outputs:**

| Panel | Content |
|---|---|
| **Benchmark** | Score per dimension + overall, model, latency, token usage (with cache breakdown), estimated cost |
| **Judge Reasoning** | One-sentence explanation per dimension from the judge model |
| **Prompt Comparison** | Side-by-side A vs B scores with delta column, when `--compare` is used |

The response is scored by a separate judge call (claude-haiku — fast and cheap) so benchmark results are comparable across models and prompt versions. Prompt caching is applied to the judge system prompt, reducing cost on repeated runs.

**Options:**

| Flag | Description |
|---|---|
| `--model`, `-m` | Claude model to benchmark (default: `claude-sonnet-4-6`) |
| `--runs`, `-n` | Number of runs — scores are averaged (default: 1) |
| `--compare`, `-c` | Second prompt file to benchmark and compare |
| `--api-key` | Anthropic API key (or set `ANTHROPIC_API_KEY`) |
| `--show-response` | Print full model response to terminal |
| `--out`, `-o` | Save model response to file |
| `--yes`, `-y` | Skip external-send confirmation prompt (for CI/non-interactive use) |

**Provider abstraction:**

`benchmark` is backed by a `ModelProvider` protocol. The default is `AnthropicProvider`. To plug in a different backend, implement the three-method interface and pass it to `run_benchmark()` in Python:

```python
from promptgenie.core.benchmarker import run_benchmark, ModelProvider

class MyProvider:
    def complete(self, model, prompt, system=None):
        # returns (response_text, {"input": n, "output": n, "cache_read": 0, "cache_write": 0})
        ...
    def judge_model(self):
        return "my-judge-model"
    def estimate_cost(self, model, input_tokens, output_tokens, cache_read, cache_write):
        return 0.0

results = run_benchmark("my-prompt.md", model="my-model", provider=MyProvider())
```

---

### `workflow`

Break a complex task into a staged prompt chain — one focused prompt per step, with handoffs, approval gates, per-step scope locks, and stop conditions. Agentic tools perform significantly better with staged prompts than with a single large prompt.

```bash
# Show all steps + full prompts
promptgenie workflow my-feature.workflow.yaml

# Summary and step index only
promptgenie workflow my-feature.workflow.yaml --summary

# Show a single step
promptgenie workflow my-feature.workflow.yaml --step 3

# Save all steps as individual .md files
promptgenie workflow my-feature.workflow.yaml --out ./prompts/
```

**`.workflow.yaml` format:**

```yaml
name: secure-login-feature
description: "Build a secure JWT login system end-to-end"
target: claude-code
context_pack: react-supabase-app   # optional — injected into step 1
mode: standard

steps:
  - id: inspect
    name: Inspect existing auth
    objective: "Map the current authentication architecture and identify gaps"
    scope:
      - src/auth/
      - src/middleware/
    output: "Architecture summary with file map and identified gaps"

  - id: plan
    name: Propose implementation plan
    depends_on: inspect
    objective: "Propose a JWT implementation plan based on the inspection"
    output: "Numbered plan with file list and risk notes"
    requires_approval: true        # model stops here for human review

  - id: implement
    name: Implement middleware
    depends_on: plan
    objective: "Implement JWT middleware only, as per the approved plan"
    scope:
      - src/middleware/auth.ts
    forbidden:
      - Do not touch files outside scope
      - Do not install packages without approval
    stop_conditions:
      - Tests fail
      - A file outside scope needs changing
    output: "Diff of changed files + test results"

  - id: security-review
    name: Security review
    depends_on: implement
    objective: "Security review of the JWT implementation"
    output: "Findings table: | Finding | Severity | Recommendation |"
    requires_approval: true
```

**Step fields:**

| Field | Description |
|---|---|
| `id` | Unique step identifier (used in `depends_on`) |
| `name` | Human-readable step name |
| `objective` | What this step must accomplish |
| `depends_on` | ID of the step that must complete first |
| `scope` | Files or directories the model may touch |
| `forbidden` | Actions explicitly prohibited in this step |
| `stop_conditions` | Conditions that require stopping and asking for approval |
| `output` | Expected output format or deliverable |
| `requires_approval` | If `true`, inserts an approval gate — model will not proceed |
| `context_note` | Optional extra notes for this step |

**What each rendered step contains:**

- Workflow header and step number
- Handoff summary from the previous step
- Objective, scope, forbidden actions, stop conditions
- Approval gate notice (if set)
- Expected output and acceptance criteria

**Options:**

| Flag | Description |
|---|---|
| `--summary` | Show step index only — no prompt content |
| `--step N` | Render a single step by number |
| `--out DIR` | Save all steps as `step_01_name.md` files in a directory |

See [`examples/secure-login.workflow.yaml`](examples/secure-login.workflow.yaml) for a full 6-step example with approval gates and a context pack.

---

### `pack`

Context packs are reusable YAML files that capture everything a model needs to know about your project — stack, architecture, coding style, forbidden changes, known pitfalls, and terminology. Use them to stop repeating yourself across every prompt.

PromptGenie also ships a **plugin registry** — a versioned index of rule packs and context packs that can be installed with `pack update` or `pack install`. Registry packs are stored in `~/.promptgenie/registry/packs/` and loaded automatically by the scanner and linter when referenced via `rules_dirs` config.

**Search the registry:**

```bash
promptgenie pack search
promptgenie pack search owasp
```

**Install a specific pack:**

```bash
promptgenie pack install owasp-llm-top10
```

Both `pack install` and `pack update` verify the SHA-256 checksum of every downloaded file against the registry index. Install is refused if no checksum is present. Pass `--allow-unverified` only when using a private registry that does not yet publish checksums (a visible warning is shown):

```bash
# Private registry without checksums — bypass with explicit opt-in
promptgenie pack install my-private-pack --allow-unverified
promptgenie pack update --url https://my-registry.example.com/index.yaml --allow-unverified
```

**Update all packs from the remote registry:**

```bash
promptgenie pack update
```

**Show registry and user directories:**

```bash
promptgenie pack dirs
```

**Built-in packs (shipped with PromptGenie, no network required — 14 total):**

| Pack ID | Type | Description |
|---|---|---|
| `owasp-llm-top10` | rules | OWASP LLM Top 10 scanner rules (2025 edition) |
| `enterprise-lint` | rules | Enterprise prompt governance lint rules |
| `gpt-4o` | profile | OpenAI GPT-4o — multimodal, function-calling, structured output |
| `mistral` | profile | Mistral AI — instruction-following and multilingual tasks |
| `llama3` | profile | Meta Llama 3 — open-source / self-hosted / fine-tuning |
| `github-copilot` | profile | GitHub Copilot — IDE-embedded code generation |
| `devops-templates` | template | DevOps & SRE — runbooks, postmortems, CI/CD, on-call handoffs |
| `data-science-templates` | template | Data Science & ML — EDA, model eval, experiment design, model cards |
| `legal-compliance-templates` | template | Legal & Compliance — contracts, GDPR DPIA, regulatory gap analysis |
| `product-management-templates` | template | Product Management — PRD, user stories, OKRs, retros |
| `customer-support-templates` | template | Customer Support & Success — triage, escalation, KB articles |
| `ai-safety-context` | context | AI safety context pack for alignment-aware prompting |
| `responsible-ai-context` | context | Responsible AI — fairness, explainability, harm prevention |
| `regulated-industries-context` | context | Regulated industries — HIPAA, SOX, PCI-DSS, FCA/SEC |

**Enable registry packs via config:**

```yaml
# .promptgenie.yaml
scanner:
  rules_dirs:
    - ~/.promptgenie/registry/packs   # registry installs
    - ./local-rules                   # project-local rules
  enabled_rules:                      # whitelist — only run these codes
    - OWASP_LLM01_001
    - OWASP_LLM02_001
    - SEC_SECRET                      # alias — expands to all SEC_SECRET_* sub-rules

linter:
  rules_dirs:
    - ~/.promptgenie/registry/packs
  enabled_rules:
    - ENT_001
    - ENT_003
```

**Expiring allowlist entries** — time-limit exceptions with automatic re-activation after the expiry date:

```yaml
scanner:
  allowlist:
    - phrase: "sk-ant-ci-placeholder"
      rules:
        - SEC_SECRET
      expires: "2026-12-31"
      reason: "CI placeholder — rotate before expiry, see ticket #456"
```

**List available packs:**

```bash
promptgenie pack list
```

**Preview a pack's rendered content:**

```bash
promptgenie pack show react-supabase-app
promptgenie pack show react-supabase-app --mode exhaustive
```

**Generate a prompt with a pack injected:**

```bash
promptgenie generate "refactor the auth module" \
  --target claude-code \
  --pack react-supabase-app \
  --mode exhaustive
```

The pack is rendered at the same depth as the prompt mode and injected into the Context section automatically.

**Inject a pack into an existing prompt file:**

```bash
promptgenie pack inject my-prompt.md react-supabase-app
promptgenie pack inject my-prompt.md react-supabase-app --out enriched-prompt.md
```

**Create your own pack:**

```bash
promptgenie pack init my-project --name "My App" --description "Next.js + Prisma SaaS"
# Edit the generated file at promptgenie/context-packs/my-project.yaml
```

**Pack file format:**

```yaml
name: react-supabase-app
description: "React + Supabase SaaS application"

stack:
  - React 18 + TypeScript
  - Supabase (auth, database, storage)
  - Tailwind CSS + shadcn/ui

architecture:
  - SPA with React Router v6
  - Supabase RLS for all data access

coding_style:
  - Functional components only
  - Custom hooks for all data fetching

forbidden_changes:
  - Do not modify Supabase migration files directly
  - Do not disable Row-Level Security on any table

known_pitfalls:
  - RLS policies must be updated when adding new tables
  - Edge functions have a cold start — avoid for latency-sensitive paths

terminology:
  workspace: "Top-level organisational unit"
  member: "A user who belongs to a workspace"

preferred_output_format: "TypeScript with explicit return types"
```

**Render modes:**

| Mode | Sections included |
|---|---|
| `minimal` | Stack only |
| `standard` | Stack, architecture, coding style, terminology |
| `exhaustive` | All sections including forbidden changes and known pitfalls |

**Included starter packs:**

| ID | Stack |
|---|---|
| `react-supabase-app` | React 18 + TypeScript + Supabase + Tailwind CSS |
| `django-rest-api` | Django 5 + DRF + PostgreSQL + Celery |
| `cyber-security-team` | Python + Splunk + Sigma + AWS + Burp Suite |

Packs are stored in `promptgenie/context-packs/*.yaml` and can be committed alongside your code.

---

### `ci`

Add prompt quality gates to any project in one command. Scaffolds a GitHub Actions workflow and pre-commit hooks that automatically run lint, scan, and test on prompt files.

**Set up CI in any project:**

```bash
cd my-project
promptgenie ci init
```

Creates three files if they don't already exist:

| File | Purpose |
|---|---|
| `.github/workflows/prompt-check.yml` | GitHub Actions — 3 parallel jobs: lint, scan, test |
| `.pre-commit-config.yaml` | Pre-commit hooks for staged `.prompt.md` and test files |
| `.promptignore` | Glob patterns to exclude from lint/scan checks |

The main `ci.yml` runs 5 parallel jobs: `test` (Python 3.10–3.12, coverage ≥85%), `lint` (ruff, mypy), `security` (bandit, pip-audit), `vscode-extension` (npm ci, audit, compile, lint), and `build` (wheel smoke test).

**Check what's active:**

```bash
promptgenie ci status
```

```
╭──────────────────────────────────────────────┬──────────╮
│ Integration                                  │  Status  │
├──────────────────────────────────────────────┼──────────┤
│ GitHub Actions (prompt-check.yml)            │ ✓ Active │
│ Pre-commit hooks (.pre-commit-config.yaml)   │ ✓ Active │
│ .promptignore exclusion file                 │ ✓ Active │
│ Git repository                               │ ✓ Active │
╰──────────────────────────────────────────────┴──────────╯
```

**GitHub Actions behaviour:**

The workflow triggers on any push or pull request touching `.md`, `.prompt-test.yaml`, or `.workflow.yaml` files and runs three parallel jobs:

| Job | Command | Fails on |
|---|---|---|
| `prompt-lint` | `promptgenie lint` per file | Any HIGH severity issue |
| `prompt-scan` | `promptgenie scan` per file | Any HIGH or CRITICAL finding |
| `prompt-test` | `promptgenie test` per suite | Any assertion failure |

**Pre-commit hooks:**

```bash
pip install pre-commit && pre-commit install
# Hooks run automatically on every git commit
```

Hooks check staged `.prompt.md` files with lint and scan, and staged `.prompt-test.yaml` files with test — before the commit lands.

**`.promptignore`:**

```
# Exclude these paths from lint/scan
README.md
CHANGELOG.md
docs/**
```

**Options:**

| Flag | Description |
|---|---|
| `--dir` | Target directory (default: current directory) |

---

### `list-targets`

Show all available model profiles.

```bash
promptgenie list-targets
```

---

### `list-templates`

Show all available prompt templates.

```bash
promptgenie list-templates
```

---

### `validate`

Validate YAML config files against their schema. Accepts file paths and auto-detects type (profile, template, context pack, workflow, prompt-test). Use `--all` to validate all built-in files.

```bash
# Validate a single file
promptgenie validate my-profile.yaml

# Validate a workflow
promptgenie validate examples/secure-login.workflow.yaml

# Validate all built-in profiles, templates, and context packs
promptgenie validate --all
```

Errors exit 1 (blocking). Warnings exit 0 (advisory — missing recommended fields, unknown keys).

---

### `validate-profiles`

Validate all profile YAML files against the profile schema. Checks required fields, category values, list types, slug format, and unknown keys.

```bash
# Validate built-in profiles
promptgenie validate-profiles

# Validate profiles in a custom directory
promptgenie validate-profiles --dir ./my-profiles

# Suppress advisory warnings (errors still shown)
promptgenie validate-profiles --no-warnings
```

---

### `doctor`

Run a self-check to verify your PromptGenie installation, environment, and provider credentials. Each check prints a pass (✓), warning (⚠), or failure (✗) with a one-line remediation hint.

```bash
# Rich terminal output (default)
promptgenie doctor

# JSON output — machine-readable, includes schema_version: "1.0"
promptgenie doctor --format json

# Pipe to jq to check a specific group
promptgenie doctor --format json | jq '.groups[] | select(.title=="Providers")'
```

**What it checks:**

| Group | Checks |
|---|---|
| Runtime | Python ≥ 3.10, `promptgenie` package version |
| Configuration | `.promptgenie.yaml` config, policy files, `NO_COLOR`/`FORCE_COLOR` env vars |
| Optional extras | `anthropic` (benchmark), `tiktoken` (tokenizer) |
| Providers | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, local Ollama reachability |
| Shell completion | Per-shell installation state |

Hard failures exit 1; optional warnings exit 0.

---

### `completion`

Install, inspect, or manage tab-completion for your shell.

```bash
# Install for your shell (writes script + updates RC file)
promptgenie completion install zsh
promptgenie completion install bash
promptgenie completion install fish

# Print the script without installing
promptgenie completion show zsh

# Check what's installed and where
promptgenie completion status

# Rebuild the dynamic completion cache (targets, templates, packs)
promptgenie completion refresh-cache
```

After installing, restart your shell or source the RC file:

```bash
source ~/.zshrc     # zsh
source ~/.bashrc    # bash
exec fish           # fish
```

The dynamic completion cache is stored at `~/.cache/promptgenie/completions.json` and includes all available `--target`, `--template`, and context pack names for instant tab-completion.

---

### Variable resolver

`generate` detects `{{variable}}` placeholders in generated prompts and resolves them from multiple sources.

**Placeholder syntax:**

| Syntax | Meaning |
|---|---|
| `{{name}}` | Required string variable, no default |
| `{{name:type}}` | Typed variable (`string`, `int`, `float`, `bool`, `secret`) |
| `{{name:type:default}}` | Optional variable with inline default |

**Resolution order** (highest priority first):

1. `--var key=value` CLI flag
2. `--vars file.yaml` values file
3. `PG_<UPPER_NAME>` environment variable
4. Interactive `click.prompt` (unless `--no-input`)
5. Inline default from the placeholder
6. `VarResolutionError` → exits 2

```bash
# Resolve from CLI flags
promptgenie generate "deploy {{service}} to {{env:string:staging}}" \
  --target claude-code --var service=api --var env=prod

# Resolve from a YAML file
promptgenie generate "review {{component}}" --vars vars.yaml

# Schema with types, required, allowed_values
promptgenie generate "scan {{target_env}}" \
  --vars-schema schema.yaml --no-input

# Pipe-friendly — never prompt, exit 2 if unresolved
cat prompt-template.md | \
  promptgenie generate "{{task}}" --var task="auth refactor" --no-input
```

**Schema YAML** (`--vars-schema schema.yaml`):

```yaml
variables:
  env:
    type: string
    required: true
    allowed_values: [prod, staging, dev]
    description: "Target deployment environment"
  token:
    type: secret
    required: true
  count:
    type: int
    default: 5
    required: false
```

---

## Phase 2 — PromptSpec and Run Engine

### `spec`

Manage declarative PromptSpec YAML files — the portable unit of a prompt execution.

```bash
# Scaffold a new spec
promptgenie spec init code-review --target claude-code
promptgenie spec init deploy-check --target ollama --out specs/deploy.yaml

# Validate structure
promptgenie spec validate my-prompt.yaml
promptgenie spec validate my-prompt.yaml --format json | jq '.errors'

# Preview the assembled prompt without calling any provider
promptgenie spec render my-prompt.yaml --var env=prod
promptgenie spec render my-prompt.yaml --format json | jq .prompt

# Print the JSON Schema (pipe to tools, import into editors)
promptgenie spec schema
promptgenie spec schema --format yaml
```

**PromptSpec fields:**

```yaml
version: 1                     # must be 1
name: code-review              # human-readable name
target: claude-code            # target profile
template: agentic-task         # optional named template
mode: chat                     # chat | completion | agentic
prompt: |                      # inline prompt (or use template:)
  Review {{component}} in {{env}}.
vars:                          # inline variable defaults
  env: staging
context:                       # context sources (assembled before sending)
  - type: git_diff
  - type: glob
    pattern: "src/**/*.py"
    max_bytes: 32768
policy:                        # policy gate
  - no-secrets
provider: anthropic            # optional provider override
model: claude-opus-4-5         # optional model override
system_prompt: |               # injected system prompt
  You are a senior code reviewer.
output_contract:
  format: markdown             # text | json | yaml | markdown | code
  max_tokens: 2048
run:
  stream: true
  timeout: 120
  require_clean: true          # abort if git tree is dirty
  no_history: false
```

---

### `run`

Execute a PromptSpec end-to-end: resolve vars → build context → security gate → render → send to provider → stream response → persist run.

```bash
# Basic run
promptgenie run my-prompt.yaml

# Dry run — resolve vars and build context without calling provider
promptgenie run my-prompt.yaml --dry-run --show-context

# Override provider and model
promptgenie run my-prompt.yaml --provider ollama --model llama3 --stream

# Pass variables
promptgenie run my-prompt.yaml --var env=prod --var component=auth
promptgenie run my-prompt.yaml --vars prod.yaml

# Write response to file while streaming to stdout
promptgenie run my-prompt.yaml --tee response.md

# Machine-readable NDJSON event stream
promptgenie run my-prompt.yaml --format ndjson
promptgenie run my-prompt.yaml --format ndjson | jq 'select(.event=="done")'

# Abort if working tree is dirty
promptgenie run my-prompt.yaml --require-clean

# Never prompt for variables — fail if any are unresolved
promptgenie run my-prompt.yaml --no-input --var env=prod
```

**Flags:**

| Flag | Description |
|---|---|
| `--dry-run` | Resolve vars + build context; no provider call |
| `--stream / --no-stream` | Streaming or non-streaming |
| `--require-clean` | Abort if git working tree is dirty |
| `--provider NAME` | Override configured provider |
| `--model NAME` | Override model (e.g. `gpt-4o`, `llama3`) |
| `--timeout N` | Abort provider call after N seconds |
| `--no-history` | Skip run persistence |
| `--var KEY=VAL` | Inline variable (repeatable) |
| `--vars FILE` | YAML/JSON variable file |
| `--max-context-tokens N` | Context token budget |
| `--context-strategy` | `manual` \| `newest` \| `smallest` \| `git-relevant` |
| `--trust` | Trust this spec's context sources without prompting (records the spec as trusted) |
| `--allow-url` | Permit URL-type context sources (HTTPS-only; SSRF-protected with IP pinning) |
| `--allow-insecure-url` | Also permit plain `http://` URL sources (emits a security warning; default blocked) |
| `--allow-sensitive-env` | Permit credential-like env vars in `env` context sources (emits a warning) |
| `--allow-secrets` | Downgrade secrets gate from hard-block to warning (use only in controlled CI environments) |
| `--tee FILE` | Write response to file while streaming |
| `--format text\|ndjson` | NDJSON emits `start/token/warning/error/done` events |
| `--show-context` | Print context manifest before sending |

Run history is persisted to `~/.local/share/promptgenie/runs/` (files `0600`, directories `0700`).

> **Privacy default:** history stores **run metadata and content hashes only** — prompt and response **bodies are not written to disk**, and per-token text is never persisted. To also store bodies (e.g. for `history show`/`history diff`/`replay`), opt in with `promptgenie config set security.store_history_content true`; even then, the prompt and response are secret-redacted before being written. The same default governs the SQLite store behind `history`/`palette`.

> **Security defaults (v1.2.4+):** The run engine enforces these constraints by default.
> (1) **Spec trust boundary** — a spec with host-touching context sources (`cmd`/`file`/`glob`/`env`/`url`) must be trusted before it runs. Interactive sessions prompt; CI must pass `--trust`/`--yes` or pre-register via `promptgenie trust add`. Trust is keyed by spec path + content hash, so editing a trusted spec re-prompts.
> (2) **Command allowlist** — `cmd` sources are restricted to inert read-only tools; interpreters (`python3`, `node`, `awk`, …) and eval flags (`-c`, `-e`, `-exec`) are blocked, and `git` is limited to read-only subcommands. All subprocess calls use `shell=False`.
> (3) **Env credential guard** — `env` sources refuse credential-like variable names (`*KEY*`, `AWS_*`, `ANTHROPIC_*`, …) unless `--allow-sensitive-env` is passed.
> (4) **Secrets gate** — a detected secret in the assembled prompt aborts the run (exit 6) before any provider call. Pass `--allow-secrets` to override.
> (5) **User-controlled URL egress** — `url` sources are fetched **only** when the user passes `--allow-url`; a spec cannot enable network egress on its own (the former `policy_gated` field is removed). Fetches require `https://` and pin the validated IP for the connection. `http://` requires `--allow-insecure-url`; `file://` and private IP ranges are blocked unconditionally.
> (6) **Provider TLS** — a provider `base_url` may use plain `http://` only for loopback/`local` keyless endpoints; remote providers must use `https://`, so an API key is never sent over cleartext.
> (7) **VS Code trusted binary** — the `promptgenie.executablePath` setting is machine-scoped; custom paths require an absolute path + basename check + one-time trust prompt, and the check fails closed if the extension context is unavailable.
> See [SECURITY.md](SECURITY.md) for the full security model.

---

### `context build`

Assemble context from multiple sources into a single text block (for inspection or piping into other tools).

```bash
# Assemble all Python files under src/
promptgenie context build --glob "src/**/*.py" --max-tokens 8000

# Include git diff + staged changes
promptgenie context build --git-diff --git-staged

# Write to file
promptgenie context build --file README.md --out context.md

# JSON output with source manifest
promptgenie context build --git-diff --format json | jq '.manifest'

# Pipe stdin
git diff | promptgenie context build --stdin

# Manifest only (no text body)
promptgenie context build --glob "**/*.py" --manifest-only
```

**Source types:**

| Type | Flag | Description |
|---|---|---|
| `file` | `--file PATH` | Single file |
| `glob` | `--glob PATTERN` | File glob (e.g. `src/**/*.py`) |
| `stdin` | `--stdin` | Read from stdin |
| `env` | *(via spec only)* | Environment variable value |
| `cmd` | `--cmd "COMMAND"` | Shell command stdout |
| `git_diff` | `--git-diff` | `git diff` output |
| `git_staged` | `--git-staged` | `git diff --staged` output |
| `url` | `--url URL` | HTTP GET (requires `--allow-url`) |

Add `.promptignore` to your repo to exclude files from glob/file sources (same syntax as `.gitignore`).

---

### `provider`

Manage AI provider configurations stored at `~/.config/promptgenie/providers.yaml`.

```bash
# List all configured providers
promptgenie provider list
promptgenie provider list --format json

# Add Ollama (local — no API key)
promptgenie provider add ollama \
  --base-url http://localhost:11434/v1 \
  --model llama3 --local

# Add LM Studio
promptgenie provider add lm-studio \
  --base-url http://localhost:1234/v1 \
  --model local-model --local

# Add a custom OpenAI-compatible endpoint (vLLM, LocalAI, etc.)
promptgenie provider add my-vllm \
  --type openai_compat \
  --base-url http://gpu-server:8000/v1 \
  --model mistral-7b --local

# Show provider details + capabilities
promptgenie provider show anthropic
promptgenie provider show ollama --format json

# Test reachability
promptgenie provider doctor ollama
promptgenie provider doctor anthropic
promptgenie provider doctor my-openai --format json

# Remove a provider
promptgenie provider remove old-provider --yes
```

Built-in defaults (active before `providers.yaml` exists):

| Name | Type | Endpoint |
|---|---|---|
| `anthropic` | Anthropic Messages API | `ANTHROPIC_API_KEY` |
| `openai` | OpenAI-compatible | `OPENAI_API_KEY` + `api.openai.com` |
| `ollama` | OpenAI-compatible (local) | `http://localhost:11434/v1` |
| `hermes` | OpenAI-compatible (NousResearch) | `NOUS_API_KEY` + `inference-api.nousresearch.com/v1` |

Install optional extras for full provider support:

```bash
pip install "promptgenie[providers]"   # httpx + anthropic SDK
```

---

### Hermes (NousResearch)

PromptGenie ships first-class support for the **NousResearch Hermes** model family — both a target profile (for authoring/linting prompts) and a built-in provider (for executing them). No `provider add` step is needed; just supply an API key.

**1. Get an API key.** Create one in the [Nous Portal](https://portal.nousresearch.com) and export it:

```bash
export NOUS_API_KEY=sk-...
```

The built-in `hermes` provider is OpenAI-compatible and points at the Nous Portal (`https://inference-api.nousresearch.com/v1`), with `Hermes-4-405B` as the default model.

**2. Verify connectivity:**

```bash
promptgenie provider doctor hermes
promptgenie provider show hermes
```

**3. Author Hermes-tuned prompts** with the `hermes` target profile — it encodes ChatML / strong-system-role guidance, reliable JSON-mode and tool-calling, a 128k context window, and the external-guardrail security controls Hermes needs (it is highly steerable and lightly moderated):

```bash
# Generate (target auto-inferred from "hermes"/"nous", or pass --target)
promptgenie generate "extract action items from this transcript" --target hermes

# Adapt an existing prompt written for another model
promptgenie adapt prompts/review.md --from claude --to hermes

# Lint / score against the Hermes profile
promptgenie lint prompts/review.md
```

**4. Execute, benchmark, and evaluate** against Hermes:

```bash
# Run a PromptSpec end-to-end through Hermes
promptgenie run spec.yaml --provider hermes --stream

# Pick a specific Hermes variant
promptgenie run spec.yaml --provider hermes --model Hermes-4-70B

# Multi-model evaluation including Hermes (cost is estimated)
promptgenie evaluate prompts/review.md --models hermes,claude,gpt-4o
```

**Custom endpoint or model.** If you serve Hermes elsewhere (OpenRouter, Together, a self-hosted vLLM, etc.), override the defaults — your `providers.yaml` entry wins over the built-in default:

```bash
promptgenie provider add hermes \
  --type openai_compat \
  --base-url https://openrouter.ai/api/v1 \
  --model nousresearch/hermes-4-405b \
  --api-key-env OPENROUTER_API_KEY
```

> **Security note:** Hermes follows the system prompt very literally and performs little vendor-side moderation. Pin your system prompt server-side, keep untrusted input in the user turn, and run an output/moderation pass before surfacing completions to end users. The `hermes` profile's `security_controls` section restates these.

---

### `vars`

Inspect variable resolution for a PromptSpec.

```bash
# List all {{variable}} placeholders in a spec
promptgenie vars list my-prompt.yaml

# Inspect how each variable would resolve (shows source: cli/file/env/default)
promptgenie vars inspect my-prompt.yaml
promptgenie vars inspect my-prompt.yaml --var env=prod --redacted
promptgenie vars inspect my-prompt.yaml --vars prod.yaml --format json
```

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
- [x] GitHub Actions CI (`ci.yml`): pytest 3.10–3.12, coverage ≥85%, ruff, mypy, bandit, pip-audit, VS Code extension CI, build + wheel smoke test
- [x] SARIF output on lint, scan, and policy for GitHub Code Scanning upload
- [x] Policy-as-code: `policy` command with `--max-risk`, `--min-score`, `--format sarif`, expired allowlist reporting
- [x] Registry hardening: SHA-256 checksums required, HTTPS-only, 1 MiB download cap, fail-closed YAML parsing
- [x] VS Code / Cursor extension: inline diagnostics, status bar score, command palette
- [x] SBOM, release provenance, CodeQL, OpenSSF Scorecard, Dependabot
- [x] 1,273 tests · 85%+ coverage · 0 ruff issues · 0 mypy errors

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

### Phase 6 — Governance, SSO, and Cloud Sync *(planned)*

- [ ] Team policy server — central policy fetch on every run; org-wide `disabled_rules`, allowlists, routing rules; policy version pinned in lockfile
- [ ] SSO / OIDC credential binding — `promptgenie auth login --sso`; OIDC device flow; per-user audit attribution; `PROMPTGENIE_TOKEN` env var for CI
- [ ] Prompt registry — `promptgenie registry push|pull`; versioned, signed, searchable; OCI-compatible layout
- [ ] Remote eval runners — offload matrix evaluations to a cloud runner pool; cost and latency budgets enforced server-side
- [ ] `promptgenie fmt` — normalise Markdown prompt files and PromptSpec YAML; heading order, key sort, trailing whitespace; `--check` exits 1 if formatting would change (CI-safe)
- [ ] `promptgenie make` — YAML task graph (`promptgenie.make.yaml`); `--changed` filtering; `--parallel N`; compatible with Make, just, Taskfile

---

## Configuration

Place a `.promptgenie.yaml` file in your project root (or any parent directory). All commands auto-discover and load it. Run `promptgenie config init` to scaffold one with the JSON Schema pointer and editor autocomplete pre-wired.

**Full schema:** `promptgenie/schemas/workspace.schema.json` (Draft 2020-12). All sections enforce `additionalProperties: false` — typos in key names are caught by `config validate`.

```yaml
# yaml-language-server: $schema=https://promptgenie.dev/schemas/workspace.schema.json
$schema: "https://promptgenie.dev/schemas/workspace.schema.json"

# Project-level metadata (optional — used in policy server and audit trail)
workspace:
  name: "my-project"
  version: "1.0"
  team: "platform-eng"
  description: "Prompt engineering workspace for the payments API."
  policy: ".promptgenie-policy.yaml"   # default policy file

# Workspace-wide defaults — overridden by --provider/--model/--target CLI flags
defaults:
  provider: anthropic
  model: claude-opus-4-5
  target: claude-code

scanner:
  # Allowlist entries suppress findings whose *matched text* contains the phrase.
  # Suppression is scoped to the finding's match — not the whole prompt.

  # Simple string: suppresses any finding whose matched text contains this phrase.
  allowlist:
    - "example-token-for-docs"

  # Scoped object: suppress only specific rule codes when the phrase is matched.
  # Safer — won't accidentally suppress unrelated findings on the same line.
  #   - phrase: "known-safe-deploy"
  #     rules:
  #       - PERM_005

  # Expiring suppression — automatically deactivates after the ISO date.
  # Use for time-limited exceptions (CI placeholders, short-lived tokens).
  #   - phrase: "sk-ant-ci-placeholder"
  #     rules:
  #       - SEC_SECRET
  #     expires: "2026-12-31"
  #     reason: "CI placeholder — rotate before expiry, see ticket #456"

  # Disable specific rule codes entirely (no phrase check needed)
  disabled_rules:
    - SEC_007

  # Whitelist mode — ONLY run these rule codes (takes precedence over disabled_rules)
  # Use SEC_SECRET to target all secret sub-rules at once (SEC_SECRET_AWS_KEY, SEC_SECRET_GITHUB, etc.)
  # enabled_rules:
  #   - SEC_SECRET
  #   - OWASP_LLM01_001

  # Override the default risk level for a rule
  severity_overrides:
    PERM_005: CRITICAL

  # Extra directories to load rule packs from (supports ~ expansion)
  # Each *.yaml file is scanned for a scanner_rules key
  # rules_dirs:
  #   - ~/.promptgenie/registry/packs
  #   - ./local-rules

linter:
  # Disable specific lint rules
  disabled_rules:
    - TASK_003

  # Whitelist mode — ONLY run these codes
  # enabled_rules:
  #   - TASK_001
  #   - ENT_001

  # Extra directories to load lint rule packs from
  # rules_dirs:
  #   - ~/.promptgenie/registry/packs

  # Add project-specific vague verbs beyond the built-in list
  custom_vague_verbs:
    - "tidy"
    - "polish"

  # Add custom lint rules (appended after built-in rules)
  custom_rules:
    - id: MY_LINT_001
      category: custom
      pattern: "refactor everything"
      severity: HIGH
      confidence: HIGH
      message: "Overly broad refactor instruction."
      suggestion: "Narrow the refactor to specific modules or files."
```

**Custom scanner rules** can also be added under `scanner.custom_rules`. Each rule requires `id`, `pattern`, `risk`, `confidence`, `message`, and `recommendation`. All patterns are validated at load time — syntax errors and nested quantifiers (ReDoS risk) raise `ValueError` and abort config loading:

```yaml
scanner:
  custom_rules:
    - id: MY_SEC_001
      category: custom
      pattern: "disable (all )?logging"
      risk: HIGH
      confidence: MEDIUM
      message: "Logging suppression detected — may hide audit trail."
      recommendation: "Retain audit logs. Use log-level configuration instead."
      false_positive_note: "May trigger on prompts about log configuration."
```

### Config CLI flags

The `scan`, `lint`, `generate`, `adapt`, and `workflow` commands all accept:

| Flag | Effect |
|---|---|
| `--config PATH` | Load a specific config file instead of auto-discovering `.promptgenie.yaml` |
| `--no-config` | Ignore any `.promptgenie.yaml`; run with default settings |
| `--best-effort` | Fall back to built-in defaults on missing profile, template, or config (fail-open) |

When a config file is loaded in rich output mode, its path is shown as a dim line before results. A missing or malformed `--config` file is a **fatal error** by default — pass `--best-effort` to fall back to defaults instead.

### Config management commands

```bash
# Scaffold a new .promptgenie.yaml with schema pointer
promptgenie config init
promptgenie config init --name "my-project" --force   # overwrite existing

# Validate .promptgenie.yaml against the workspace schema
promptgenie config validate                            # exits 0 = valid, 1 = errors, 2 = not found
promptgenie config validate --format json              # machine-readable for CI
promptgenie config validate --config path/to/file.yaml

# Show current effective config
promptgenie config show
promptgenie config show --format json

# Get / set individual keys
promptgenie config get security.airgap
promptgenie config set security.airgap true
promptgenie config set routing.default ollama
```

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
