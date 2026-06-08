/**
 * diagnostics.ts — Converts PromptGenie lint/scan output to VS Code Diagnostics.
 *
 * Each LintIssue → Diagnostic in the "PromptGenie Lint" collection.
 * Each ScanFinding → Diagnostic in the "PromptGenie Scan" collection.
 * Both collections are managed here; callers just call update*().
 */

import * as vscode from "vscode";
import type { LintIssue, LintOutput, ScanFinding, ScanOutput, SeverityLevel } from "./types";

// ── Diagnostic collections ───────────────────────────────────────────────────

export const lintCollection = vscode.languages.createDiagnosticCollection("PromptGenie Lint");
export const scanCollection = vscode.languages.createDiagnosticCollection("PromptGenie Scan");

// ── Severity mapping ─────────────────────────────────────────────────────────

function vscodeSeverity(level: string): vscode.DiagnosticSeverity {
  const cfg = vscode.workspace
    .getConfiguration("promptgenie")
    .get<Record<string, SeverityLevel>>("severityMapping") ?? {};

  const mapped: SeverityLevel = cfg[level] ?? (
    level === "CRITICAL" || level === "HIGH" ? "error" :
    level === "MEDIUM" ? "warning" : "information"
  );

  switch (mapped) {
    case "error":       return vscode.DiagnosticSeverity.Error;
    case "warning":     return vscode.DiagnosticSeverity.Warning;
    case "information": return vscode.DiagnosticSeverity.Information;
    case "hint":        return vscode.DiagnosticSeverity.Hint;
    default:            return vscode.DiagnosticSeverity.Warning;
  }
}

// ── Range helper — PromptGenie uses 1-based line/col ─────────────────────────

function toRange(doc: vscode.TextDocument, line: number, col: number): vscode.Range {
  // Clamp to valid document bounds; line 0 means "whole document" (summary-level)
  const l = Math.max(0, (line || 1) - 1);
  const c = Math.max(0, (col || 1) - 1);
  const safeLine = Math.min(l, doc.lineCount - 1);
  const lineText = doc.lineAt(safeLine).text;
  const safeCol = Math.min(c, lineText.length);
  // Highlight to end of word or end of line
  const endCol = lineText.length > safeCol ? lineText.length : safeCol + 1;
  return new vscode.Range(safeLine, safeCol, safeLine, endCol);
}

// ── Lint diagnostics ─────────────────────────────────────────────────────────

function lintIssueToDiagnostic(doc: vscode.TextDocument, issue: LintIssue): vscode.Diagnostic {
  const range = toRange(doc, issue.line, issue.col);
  const severity = vscodeSeverity(issue.severity);
  const message = issue.suggestion
    ? `${issue.message} — ${issue.suggestion}`
    : issue.message;

  const diag = new vscode.Diagnostic(range, message, severity);
  diag.source = "PromptGenie";
  diag.code = issue.code;

  // Tags: LINT_UNNECESSARY → Unnecessary, anything with "deprecated" → Deprecated
  if (issue.code.includes("DEPR")) {
    diag.tags = [vscode.DiagnosticTag.Deprecated];
  }

  return diag;
}

export function updateLintDiagnostics(doc: vscode.TextDocument, output: LintOutput): void {
  const diags = output.issues.map((issue) => lintIssueToDiagnostic(doc, issue));
  lintCollection.set(doc.uri, diags);
}

export function clearLintDiagnostics(uri: vscode.Uri): void {
  lintCollection.delete(uri);
}

// ── Scan diagnostics ─────────────────────────────────────────────────────────

function scanFindingToDiagnostic(doc: vscode.TextDocument, finding: ScanFinding): vscode.Diagnostic {
  const range = toRange(doc, finding.line, finding.col);
  const severity = vscodeSeverity(finding.risk);
  const message = finding.recommendation
    ? `[${finding.risk}] ${finding.message} — ${finding.recommendation}`
    : `[${finding.risk}] ${finding.message}`;

  const diag = new vscode.Diagnostic(range, message, severity);
  diag.source = "PromptGenie Security";
  diag.code = finding.code;

  return diag;
}

export function updateScanDiagnostics(doc: vscode.TextDocument, output: ScanOutput): void {
  const diags = output.findings.map((f) => scanFindingToDiagnostic(doc, f));
  scanCollection.set(doc.uri, diags);
}

export function clearScanDiagnostics(uri: vscode.Uri): void {
  scanCollection.delete(uri);
}

// ── Clear both ───────────────────────────────────────────────────────────────

export function clearAll(uri: vscode.Uri): void {
  lintCollection.delete(uri);
  scanCollection.delete(uri);
}

export function disposeCollections(): void {
  lintCollection.dispose();
  scanCollection.dispose();
}
