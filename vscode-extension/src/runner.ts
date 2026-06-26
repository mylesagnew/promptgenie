/**
 * runner.ts — Executes the PromptGenie CLI and returns parsed JSON output.
 *
 * Spawns `promptgenie lint|scan <file> --format json` as a child process,
 * captures stdout, and parses the result. All errors are returned as typed
 * objects — never thrown — so callers can display them cleanly.
 */

import * as cp from "child_process";
import * as path from "path";
import * as vscode from "vscode";
import type { LintOutput, ScanOutput } from "./types";
import { isTrustedPath, isUnderTrustedPrefix, pathTrustKey } from "./runner-utils";

export { isTrustedPath } from "./runner-utils";

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
    } as cp.SpawnOptionsWithoutStdio);

    // cp.spawn does NOT honour maxBuffer (that option only applies to exec/
    // execFile), so without an explicit cap a hostile or runaway CLI could grow
    // these buffers until the extension host runs out of memory. Bound each
    // stream and abort if exceeded; also kill the process if it hangs.
    const MAX_OUTPUT_BYTES = 8 * 1024 * 1024; // 8 MB
    const TIMEOUT_MS = 30_000;

    const stdoutChunks: Buffer[] = [];
    const stderrChunks: Buffer[] = [];
    let stdoutBytes = 0;
    let stderrBytes = 0;
    let settled = false;

    let timer: ReturnType<typeof setTimeout>;
    const finishResolve = (value: string): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(value);
    };
    const finishReject = (err: Error): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      reject(err);
    };

    timer = setTimeout(() => {
      proc.kill();
      finishReject(
        new Error(
          `promptgenie ${command} timed out after ${TIMEOUT_MS / 1000}s and was terminated.`
        )
      );
    }, TIMEOUT_MS);

    proc.stdout.on("data", (chunk: Buffer) => {
      stdoutBytes += chunk.length;
      if (stdoutBytes > MAX_OUTPUT_BYTES) {
        proc.kill();
        finishReject(
          new Error(
            `promptgenie ${command} produced more than ${MAX_OUTPUT_BYTES} bytes of output; aborted.`
          )
        );
        return;
      }
      stdoutChunks.push(chunk);
    });

    proc.stderr.on("data", (chunk: Buffer) => {
      stderrBytes += chunk.length;
      // Keep stderr bounded too, but don't abort on it — just stop accumulating
      // so the error message below still has the earliest output.
      if (stderrBytes <= MAX_OUTPUT_BYTES) {
        stderrChunks.push(chunk);
      }
    });

    proc.on("error", (err: NodeJS.ErrnoException) => {
      if (err.code === "ENOENT") {
        finishReject(
          new Error(
            `PromptGenie CLI not found at "${cli}". ` +
              `Install it with: pip install promptgenie\n` +
              `Or set promptgenie.executablePath in your VS Code settings.`
          )
        );
      } else {
        finishReject(err);
      }
    });

    proc.on("close", (code) => {
      const stdout = Buffer.concat(stdoutChunks).toString();
      const stderr = Buffer.concat(stderrChunks).toString();
      // exit code 1 = findings found (not an error condition for our purposes)
      if (stdout.trim()) {
        finishResolve(stdout);
      } else if (code !== null && code > 1) {
        finishReject(new Error(`promptgenie ${command} exited ${code}: ${stderr.trim()}`));
      } else {
        // Clean exit, no output — treat as empty result
        finishResolve(stdout || "{}");
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
