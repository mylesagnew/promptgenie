/**
 * extension.ts — PromptGenie VS Code / Cursor extension entry point.
 *
 * Features:
 *   - Inline lint diagnostics while typing (debounced)
 *   - Full lint + scan diagnostics on save
 *   - Status bar score + issue count for active prompt files
 *   - Commands: lintFile, scanFile, lintAndScan, clearDiagnostics
 *
 * The extension shells out to the `promptgenie` CLI with `--format json`
 * and maps the structured output to VS Code Diagnostic objects.
 */

import * as vscode from "vscode";
import { runLint, runScan, runBoth } from "./runner";
import {
  lintCollection,
  scanCollection,
  updateLintDiagnostics,
  updateScanDiagnostics,
  clearAll,
  disposeCollections,
} from "./diagnostics";
import {
  createStatusBarItem,
  updateStatusBar,
  setStatusBarRunning,
  setStatusBarError,
  hideStatusBar,
  disposeStatusBar,
} from "./statusBar";

// ── File extension gate ──────────────────────────────────────────────────────

function isPromptFile(doc: vscode.TextDocument): boolean {
  const exts = vscode.workspace
    .getConfiguration("promptgenie")
    .get<string[]>("enabledFileExtensions") ?? [".md", ".txt", ".prompt", ".promptgenie"];

  const fileName = doc.fileName;
  return exts.some((ext) => fileName.endsWith(ext));
}

// ── Debounce ─────────────────────────────────────────────────────────────────

let debounceTimer: ReturnType<typeof setTimeout> | undefined;

function debounce(fn: () => void, ms: number): void {
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(fn, ms);
}

// ── Core analysis runners ────────────────────────────────────────────────────

async function lintDocument(doc: vscode.TextDocument, quiet = false): Promise<void> {
  if (!isPromptFile(doc)) return;

  if (!quiet) setStatusBarRunning();

  try {
    const output = await runLint(doc.fileName);
    updateLintDiagnostics(doc, output);
    if (!quiet) updateStatusBar(output, undefined);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    if (!quiet) {
      setStatusBarError(msg);
      vscode.window.showErrorMessage(`PromptGenie lint failed: ${msg}`);
    }
  }
}

async function scanDocument(doc: vscode.TextDocument): Promise<void> {
  if (!isPromptFile(doc)) return;

  setStatusBarRunning();

  try {
    const output = await runScan(doc.fileName);
    updateScanDiagnostics(doc, output);
    updateStatusBar(undefined, output);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    setStatusBarError(msg);
    vscode.window.showErrorMessage(`PromptGenie scan failed: ${msg}`);
  }
}

async function lintAndScanDocument(doc: vscode.TextDocument): Promise<void> {
  if (!isPromptFile(doc)) return;

  setStatusBarRunning();

  try {
    const { lint, scan } = await runBoth(doc.fileName);
    updateLintDiagnostics(doc, lint);
    updateScanDiagnostics(doc, scan);
    updateStatusBar(lint, scan);

    // Surface a summary notification for high-risk findings
    const highRisk = scan.findings.filter(
      (f) => f.risk === "CRITICAL" || f.risk === "HIGH"
    );
    if (highRisk.length > 0) {
      vscode.window.showWarningMessage(
        `PromptGenie: ${highRisk.length} high-risk finding${highRisk.length !== 1 ? "s" : ""} — ` +
          `${highRisk[0].message}`,
        "Show Problems"
      ).then((action) => {
        if (action === "Show Problems") {
          vscode.commands.executeCommand("workbench.action.problems.focus");
        }
      });
    }
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    setStatusBarError(msg);
    vscode.window.showErrorMessage(`PromptGenie failed: ${msg}`);
  }
}

// ── Extension lifecycle ──────────────────────────────────────────────────────

export function activate(context: vscode.ExtensionContext): void {
  // Status bar
  const statusBar = createStatusBarItem();
  context.subscriptions.push(statusBar);

  // Diagnostic collections
  context.subscriptions.push(lintCollection, scanCollection);

  // ── Commands ──────────────────────────────────────────────────────────────

  context.subscriptions.push(
    vscode.commands.registerCommand("promptgenie.lintFile", () => {
      const doc = vscode.window.activeTextEditor?.document;
      if (doc) lintDocument(doc);
      else vscode.window.showInformationMessage("PromptGenie: no active file.");
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("promptgenie.scanFile", () => {
      const doc = vscode.window.activeTextEditor?.document;
      if (doc) scanDocument(doc);
      else vscode.window.showInformationMessage("PromptGenie: no active file.");
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("promptgenie.lintAndScan", () => {
      const doc = vscode.window.activeTextEditor?.document;
      if (doc) lintAndScanDocument(doc);
      else vscode.window.showInformationMessage("PromptGenie: no active file.");
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("promptgenie.clearDiagnostics", () => {
      const doc = vscode.window.activeTextEditor?.document;
      if (doc) {
        clearAll(doc.uri);
        hideStatusBar();
      }
    })
  );

  // ── On-change lint (debounced) ────────────────────────────────────────────

  context.subscriptions.push(
    vscode.workspace.onDidChangeTextDocument((event) => {
      const doc = event.document;
      if (!isPromptFile(doc)) return;

      const cfg = vscode.workspace.getConfiguration("promptgenie");
      if (!cfg.get<boolean>("runOnChange", true)) return;

      const ms = cfg.get<number>("debounceMs", 800);
      debounce(() => lintDocument(doc, true), ms);
    })
  );

  // ── On-save lint + scan ───────────────────────────────────────────────────

  context.subscriptions.push(
    vscode.workspace.onDidSaveTextDocument((doc) => {
      if (!isPromptFile(doc)) return;
      const cfg = vscode.workspace.getConfiguration("promptgenie");
      if (!cfg.get<boolean>("runOnSave", true)) return;
      lintAndScanDocument(doc);
    })
  );

  // ── Active editor change — update status bar ──────────────────────────────

  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      if (!editor || !isPromptFile(editor.document)) {
        hideStatusBar();
        return;
      }
      // Re-run on focus so status bar always reflects the current file
      lintDocument(editor.document, true);
    })
  );

  // ── On close — clean up diagnostics ──────────────────────────────────────

  context.subscriptions.push(
    vscode.workspace.onDidCloseTextDocument((doc) => {
      clearAll(doc.uri);
    })
  );

  // ── Initial scan of the active editor on activation ───────────────────────

  const activeDoc = vscode.window.activeTextEditor?.document;
  if (activeDoc && isPromptFile(activeDoc)) {
    lintDocument(activeDoc, true);
  }
}

export function deactivate(): void {
  if (debounceTimer) clearTimeout(debounceTimer);
  disposeCollections();
  disposeStatusBar();
}
