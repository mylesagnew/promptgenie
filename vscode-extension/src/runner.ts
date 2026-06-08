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

// ── Config helpers ───────────────────────────────────────────────────────────

function getConfig(): vscode.WorkspaceConfiguration {
  return vscode.workspace.getConfiguration("promptgenie");
}

function cliPath(): string {
  return getConfig().get<string>("cliPath") || "promptgenie";
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

function runCli(
  command: string,
  filePath: string,
  additionalArgs: string[] = []
): Promise<string> {
  return new Promise((resolve, reject) => {
    const cli = cliPath();
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
              `Or set promptgenie.cliPath in your VS Code settings.`
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
