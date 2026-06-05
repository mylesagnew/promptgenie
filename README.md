<p align="center">
  <img src="assets/logo.png" alt="PromptGenie" width="600" />
</p>

# PromptGenie

**Secure prompt engineering for AI agents and engineering teams.**

PromptGenie is a CLI that turns rough task descriptions into optimised, tool-specific, security-checked prompts — with a built-in linter, security scanner, diff engine, quality scoring, and token estimation.

---

## Why

Most prompt engineering is done by hand, rewritten constantly, and never tested. Prompts for agentic tools (Claude Code, Cursor, Devin) are especially risky: a vague scope or missing stop condition can cause scope creep, destructive edits, or unintended deployments.

PromptGenie makes prompts:

- **Structured** — section-by-section output matched to the target tool's requirements
- **Linted** — catches vague verbs, missing scope, broad tasks, and agentic risks before you send
- **Scanned** — detects secrets, prompt injection patterns, and unsafe agent permissions
- **Diffed** — compare two versions with token delta, score delta, section changes, and risk changes
- **Scored** — rates every prompt across 7 quality dimensions
- **Repeatable** — YAML model profiles and templates, versioned alongside your code

---

## Install

```bash
git clone https://github.com/mylesagnew/promptgenie.git
cd promptgenie
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

---

## Commands

| Command | Description |
|---|---|
| `generate` | Build an optimised prompt from a rough task description |
| `lint` | Check a prompt file for quality and structural issues |
| `scan` | Scan a prompt file for security risks |
| `diff` | Compare two prompt versions — token, score, section, and risk delta |
| `list-targets` | Show all available model profiles |
| `list-templates` | Show all available prompt templates |

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
promptgenie lint my-prompt.md
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

---

### `scan`

Scan a prompt file for security risks.

```bash
promptgenie scan my-prompt.md
```

**What it detects:**

| Category | Examples |
|---|---|
| Secrets | API keys, tokens, AWS credentials, private keys embedded in prompt |
| Prompt injection | Instruction overrides, system prompt extraction, output suppression |
| Agent permissions | Unrestricted filesystem access, arbitrary code execution, unsupervised publishing |
| RAG risks | Instructions that follow retrieved content, untrusted input pipelines |
| Chained risks | Web fetch + action (email/deploy/write) without approval gate |

Exits `1` on CRITICAL or HIGH findings — safe to use in CI or pre-commit hooks.

---

### `diff`

Compare two prompt versions side-by-side — tokens, quality scores, section changes, lint changes, and security finding changes.

```bash
promptgenie diff v1.md v2.md --target claude-code
```

```bash
# Include full unified diff
promptgenie diff v1.md v2.md --target claude-code --unified
```

**What it shows:**

| Panel | Content |
|---|---|
| **Summary** | Tokens, quality score, lint count, security findings — A vs B with delta |
| **Quality Score Breakdown** | All 7 dimensions side-by-side with per-dimension delta |
| **Section Changes** | Each `## Section` marked ADDED / REMOVED / CHANGED / UNCHANGED with inline line diffs |
| **Lint Changes** | Issues resolved in v2 vs new issues introduced |
| **Security Changes** | Findings resolved in v2 vs new findings introduced |

**Example output:**

```
Comparing  v1.md  →  v2.md

╭──────────────────────────── Summary ─────────────────────────────╮
│  Metric              Version A    Version B    Delta              │
│  Tokens                    38          171     +133              │
│  Quality score         70/100       88/100      +18              │
│  Lint issues                3            1       -2              │
│  Security findings          0            1       +1              │
╰──────────────────────────────────────────────────────────────────╯

╭──────────────────── Quality Score Breakdown ──────────────────────╮
│  Dimension           A      B      Δ                              │
│  Target Fit         50    100    +50                              │
│  Task Clarity       90     90      0                              │
│  Context Sufficiency 50    75    +25                              │
│  Output Contract    90     90      0                              │
│  Safety Controls    58     82    +24                              │
│  Token Efficiency   95     95      0                              │
│  Testability        60     90    +30                              │
╰──────────────────────────────────────────────────────────────────╯

╭──────────────────────── Section Changes ──────────────────────────╮
│ [CHANGED]    Objective                                            │
│ [CHANGED]    Scope                                               │
│ [CHANGED]    Output Format                                       │
│ [ADDED]      Constraints                                         │
│ [ADDED]      Stop Conditions                                     │
│ [ADDED]      Acceptance Criteria                                 │
╰──────────────────────────────────────────────────────────────────╯

╭───────────────────────── Lint Changes ────────────────────────────╮
│ [RESOLVED]  MEDIUM  [STRUCT_001]  No stop conditions found.      │
│ [RESOLVED]  LOW     [STRUCT_003]  No forbidden actions listed.   │
│ [RESOLVED]  LOW     [STRUCT_005]  No acceptance criteria.        │
│ [NEW]       HIGH    [AGENT_004]   Unrestricted package install.  │
╰──────────────────────────────────────────────────────────────────╯
```

**Options:**

| Flag | Description |
|---|---|
| `--target`, `-t` | Profile to use for quality scoring (default: `claude`) |
| `--unified`, `-u` | Show full colour-coded unified diff |

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

---

## Project structure

```
promptgenie/
├── cli.py                      # Click CLI — all commands
├── core/
│   ├── generator.py            # Prompt builder, scoring, token estimation
│   ├── linter.py               # Lint rules engine
│   ├── scanner.py              # Security scanner
│   └── differ.py              # Diff engine — token, score, section, risk delta
├── profiles/
│   ├── claude.yaml
│   ├── claude-code.yaml
│   ├── chatgpt.yaml
│   ├── cursor.yaml
│   └── gemini.yaml
└── templates/
    └── cyber_templates.yaml    # 7 security and coding templates
```

---

## Roadmap

- [x] `generate` — build structured prompts from rough task descriptions
- [x] `lint` — 15+ rules for quality, scope, and agentic safety
- [x] `scan` — security scanner for secrets, injection, and agent risks
- [x] `diff` — compare two prompt versions with token, score, section, and risk delta
- [ ] `adapt` — translate a prompt from one target to another
- [ ] `test` — prompt unit tests with expected output assertions
- [ ] `benchmark` — run prompt against a model and score the output
- [ ] Context packs — reusable project context blocks
- [ ] Workflow mode — staged prompt chains for complex agentic tasks
- [ ] VS Code / Cursor extension
- [ ] GitHub Actions lint/scan integration
- [ ] Community profile and template packs

---

## License

MIT
