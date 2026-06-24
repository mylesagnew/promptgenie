/**
 * runner.ts — Executes the PromptGenie CLI and returns parsed JSON output.
 *
 * Spawns `promptgenie lint|scan <file> --format json` as a child process,
 * captures stdout, and parses the result. All errors are returned as typed
 * objects — never thrown — so callers can display them cleanly.
 */

import * as cp from "child_process";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";
import type { LintOutput, ScanOutput } from "./types";

// ── Trusted-path state ────────────────────────────────────────────────────────

/**
 * Well-known install prefixes under which a promptgenie binary is considered
 * trusted without a user confirmation prompt.  Paths are checked as
 * case-sensitive prefix matches on POSIX; on Windows the comparison is
 * case-insensitive.
 */
const TRUSTED_PREFIXES: string[] = [
  "/usr/local/bin",
  "/usr/bin",
  "/opt/homebrew/bin",
  path.join(os.homedir(), ".local", "bin"),
  path.join(os.homedir(), ".cargo", "bin"),
];

// Accepted binary base names (platform-aware).
const ACCEPTED_BASENAMES: Set<string> =
  process.platform === "win32"
    ? new Set(["promptgenie.exe", "promptgenie"])
    : new Set(["promptgenie"]);

/**
 * Validate a configured binary path before execution.
 *
 * Rules (CWE-426 / CWE-427 mitigation):
 *   1. Relative paths are rejected outright — require absolute paths only.
 *   2. The base name must be `promptgenie` (or `promptgenie.exe` on Windows).
 *   3. The path must exist and must be a regular file (not a directory or
 *      FIFO etc.).  Symlinks are followed via `fs.statSync` (real stat).
 *   4. Paths under TRUSTED_PREFIXES are silently accepted; all others require
 *      an explicit one-time user trust confirmation stored in globalState.
 *
 * @returns `true` if the path is safe to spawn, `false` otherwise.
 */
export function isTrustedPath(p: string): boolean {
  // Rule 1: must be absolute.
  if (!path.isAbsolute(p)) {
    return false;
  }
  // Rule 2: base name must match.
  const base = path.basename(p);
  const cmp = process.platform === "win32" ? base.toLowerCase() : base;
  const accepted = process.platform === "win32"
    ? new Set([...ACCEPTED_BASENAMES].map((b) => b.toLowerCase()))
    : ACCEPTED_BASENAMES;
  if (!accepted.has(cmp)) {
    return false;
  }
  // Rule 3: path must exist and be a regular file.
  try {
    const stat = fs.statSync(p); // follows symlinks — intentional
    if (!stat.isFile()) {
      return false;
    }
  } catch {
    return false;
  }
  return true;
}

/**
 * Check whether *resolvedPath* falls under one of the well-known trusted
 * install prefixes.
 */
function isUnderTrustedPrefix(resolvedPath: string): boolean {
  const norm = path.normalize(resolvedPath);
  for (const prefix of TRUSTED_PREFIXES) {
    const normPrefix = path.normalize(prefix) + path.sep;
    if (
      process.platform === "win32"
        ? norm.toLowerCase().startsWith(normPrefix.toLowerCase())
        : norm.startsWith(normPrefix)
    ) {
      return true;
    }
  }
  return false;
}

/**
 * Derive a stable key for storing the user's trust decision in globalState.
 * Uses a simple djb2-style hash of the absolute path so we avoid storing raw
 * filesystem paths in extension state.
 */
function pathTrustKey(absPath: string): string {
  let h = 5381;
  for (let i = 0; i < absPath.length; i++) {
    h = ((h << 5) + h) ^ absPath.charCodeAt(i);
    h = h >>> 0; // keep 32-bit unsigned
  }
  return `trustedPath:${h.toString(16)}`;
}

/**
 * Show a one-time trust prompt when a non-default / non-standard
 * `executablePath` is configured in workspace settings.
 *
 * The user's decision is persisted in `globalState` keyed by a hash of the
 * absolute path so it survives session restarts.
 *
 * @returns `true` if the path should be trusted, `false` if dismissed.
 */
async function confirmCustomBinaryTrust(
  absPath: string,
  context: vscode.ExtensionContext
): Promise<boolean> {
  const key = pathTrustKey(absPath);
  const already = context.globalState.get<boolean>(key);
  if (already === true) {
    return true;
  }
  if (already === false) {
    // Previously dismissed — do not spam the user.
    return false;
  }

  const answer = await vscode.window.showWarningMessage(
    `PromptGenie: This workspace has configured a custom executable at:\n"${absPath}"\n` +
      "Executing an untrusted binary from workspace settings is a security risk. " +
      "Only trust this path if you recognise it and intentionally set it.",
    { modal: true },
    "Trust this path",
    "Dismiss"
  );

  const trusted = answer === "Trust this path";
  await context.globalState.update(key, trusted);
  return trusted;
}

// Extension context — set during activation so runner helpers can access it.
let _extensionContext: vscode.ExtensionContext | undefined;

export function setExtensionContext(ctx: vscode.ExtensionContext): void {
  _extensionContext = ctx;
}

// ── Config helpers ───────────────────────────────────────────────────────────

function getConfig(): vscode.WorkspaceConfiguration {
  return vscode.workspace.getConfiguration("promptgenie");
}

/**
 * Resolve the CLI path from configuration, validate it, and (if it is a
 * custom non-default path) prompt the user for one-time trust confirmation.
 *
 * @throws `Error` if the configured path is unsafe or untrusted.
 */
async function resolvedCliPath(): Promise<string> {
  const configured = getConfig().get<string>("executablePath") || getConfig().get<string>("cliPath") || "";

  // Default / empty — use PATH lookup (no trust check required).
  if (!configured || configured === "promptgenie") {
    return "promptgenie";
  }

  // A custom path was configured — validate it before use.
  if (!isTrustedPath(configured)) {
    const reason = !path.isAbsolute(configured)
      ? "relative paths are not permitted — use an absolute path"
      : `path does not resolve to a regular file named "promptgenie"`;
    throw new Error(
      `PromptGenie: configured executablePath "${configured}" is invalid: ${reason}. ` +
        `Update promptgenie.executablePath in your settings to a valid absolute path.`
    );
  }

  // Check if the path is under a well-known trusted prefix.
  if (isUnderTrustedPrefix(configured)) {
    return configured;
  }

  // Non-standard location — require explicit one-time user trust confirmation.
  if (!_extensionContext) {
    // Fail closed (V-003): without the extension context we cannot record or
    // verify one-time trust, so we must NOT execute an arbitrary custom binary.
    throw new Error(
      `PromptGenie: cannot verify trust for custom binary "${configured}" because ` +
        "the extension context is unavailable. Refusing to execute."
    );
  }
  const trusted = await confirmCustomBinaryTrust(configured, _extensionContext);
  if (!trusted) {
    throw new Error(
      `PromptGenie: execution of custom binary "${configured}" was not trusted by the user. ` +
        "Update promptgenie.executablePath in VS Code settings or grant trust when prompted."
    );
  }
  return configured;
}

function extraArgs(): string[] {
  const args: string[] = [];
  const target = getConfig().get<string>("target");
  if (target) {
    args.push("--target", target);
  }
  const config = getConfig().get<string>("config");
  if (config) {
    args.push("--config", config);
  }
  return args;
}

// ── Core spawn helper ────────────────────────────────────────────────────────

async function runCli(
  command: string,
  filePath: string,
  additionalArgs: string[] = []
): Promise<string> {
  // Resolve and validate the CLI path before spawning.
  const cli = await resolvedCliPath();

  return new Promise((resolve, reject) => {
    const args = [command, filePath, "--format", "json", ...additionalArgs];
    const cwd = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || path.dirname(filePath);

    const proc = cp.spawn(cli, args, {
      cwd,
      env: { ...process.env },
      // Increase buffer — large prompts with many findings can produce verbose JSON
      maxBuffer: 1024 * 1024,
    } as cp.SpawnOptionsWithoutStdio);

    let stdout = "";
    let stderr = "";

    proc.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString();
    });

    proc.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString();
    });

    proc.on("error", (err: NodeJS.ErrnoException) => {
      if (err.code === "ENOENT") {
        reject(
          new Error(
            `PromptGenie CLI not found at "${cli}". ` +
              `Install it with: pip install promptgenie\n` +
              `Or set promptgenie.executablePath in your VS Code settings.`
          )
        );
      } else {
        reject(err);
      }
    });

    proc.on("close", (code) => {
      // exit code 1 = findings found (not an error condition for our purposes)
      if (stdout.trim()) {
        resolve(stdout);
      } else if (code !== null && code > 1) {
        reject(new Error(`promptgenie ${command} exited ${code}: ${stderr.trim()}`));
      } else {
        // Clean exit, no output — treat as empty result
        resolve(stdout || "{}");
      }
    });
  });
}

// ── Public API ───────────────────────────────────────────────────────────────

export async function runLint(filePath: string): Promise<LintOutput> {
  const raw = await runCli("lint", filePath, extraArgs());
  return JSON.parse(raw) as LintOutput;
}

export async function runScan(filePath: string): Promise<ScanOutput> {
  const raw = await runCli("scan", filePath, extraArgs());
  return JSON.parse(raw) as ScanOutput;
}

export async function runBoth(
  filePath: string
): Promise<{ lint: LintOutput; scan: ScanOutput }> {
  const [lint, scan] = await Promise.all([runLint(filePath), runScan(filePath)]);
  return { lint, scan };
}
