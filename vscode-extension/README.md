# PromptGenie — VS Code / Cursor Extension

Inline lint and security scan for AI prompt files, powered by the [PromptGenie CLI](https://github.com/mylesagnew/promptgenie).

---

## Features

- **Inline lint diagnostics** — squiggly underlines for vague verbs, missing scope, broad tasks, and agentic safety issues while you type (debounced)
- **Security scan on save** — flags secrets, prompt injection patterns, and unsafe agent permissions when you save
- **Status bar score** — shows the prompt quality score (`PG: 85/100`) and issue count in the bottom-right corner
- **High-risk alerts** — pops a warning notification when a `HIGH` or `CRITICAL` security finding is detected
- **Command palette** — `PromptGenie: Lint File`, `PromptGenie: Scan File`, `PromptGenie: Lint & Scan`
- **Context menu** — right-click any `.md`, `.txt`, or `.prompt` file for quick lint/scan

---

## Requirements

The extension shells out to the `promptgenie` CLI. Install it first:

```bash
pip install promptgenie
```

Verify the CLI is on your PATH:

```bash
promptgenie --version
```

If you use a virtualenv, set `promptgenie.cliPath` in your settings to the absolute path:

```json
{
  "promptgenie.cliPath": "/home/user/.venv/bin/promptgenie"
}
```

---

## Extension Settings

| Setting | Default | Description |
|---|---|---|
| `promptgenie.cliPath` | `"promptgenie"` | Path to the CLI executable |
| `promptgenie.target` | `""` | Default `--target` profile (e.g. `claude-code`, `gpt-4o`) |
| `promptgenie.config` | `""` | Path to `.promptgenie.yaml` config file |
| `promptgenie.runOnSave` | `true` | Run lint + scan automatically on file save |
| `promptgenie.runOnChange` | `true` | Run lint automatically while typing (debounced) |
| `promptgenie.debounceMs` | `800` | Debounce delay in milliseconds for on-change lint |
| `promptgenie.enabledFileExtensions` | `[".md",".txt",".prompt",".promptgenie"]` | File extensions that activate diagnostics |
| `promptgenie.showScoreInStatusBar` | `true` | Show quality score in the status bar |
| `promptgenie.severityMapping` | See below | Map risk levels to VS Code diagnostic severity |

**Default severity mapping:**

```json
{
  "promptgenie.severityMapping": {
    "HIGH": "error",
    "MEDIUM": "warning",
    "LOW": "information",
    "CRITICAL": "error"
  }
}
```

---

## Commands

| Command | Description |
|---|---|
| `PromptGenie: Lint File` | Lint the active file and show issues |
| `PromptGenie: Scan File` | Security-scan the active file and show findings |
| `PromptGenie: Lint & Scan` | Run both lint and scan |
| `PromptGenie: Clear Diagnostics` | Remove all PromptGenie diagnostics from the active file |

---

## Supported File Types

By default the extension activates on:

- `.md` — Markdown (most prompts are written in markdown)
- `.txt` — Plain text
- `.prompt` — PromptGenie prompt files
- `.promptgenie` — PromptGenie workflow / config files

Add more extensions via `promptgenie.enabledFileExtensions`.

---

## Building from Source

```bash
cd vscode-extension
npm install
npm run compile
# Launch extension host: F5 in VS Code with the extension folder open
```

To package as a `.vsix`:

```bash
npm run package
```

---

## Troubleshooting

**"PromptGenie CLI not found"** — Set `promptgenie.cliPath` to the full path of the CLI executable.

**Diagnostics not appearing** — Check that the file extension is in `promptgenie.enabledFileExtensions` and that `runOnChange` / `runOnSave` is enabled.

**High CPU usage** — Increase `promptgenie.debounceMs` (e.g. to `2000`) or disable `runOnChange` and rely on save-only analysis.

---

## License

MIT — same as the PromptGenie CLI.
