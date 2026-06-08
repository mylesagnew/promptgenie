/**
 * statusBar.ts — PromptGenie score + issue summary in the VS Code status bar.
 *
 * Shows:  $(inspect) PG: 85/100  2 issues  [HIGH]
 *
 * Only visible when the active editor is a prompt file.
 */

import * as vscode from "vscode";
import type { LintOutput, ScanOutput } from "./types";

let statusBarItem: vscode.StatusBarItem | undefined;

export function createStatusBarItem(): vscode.StatusBarItem {
  statusBarItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100
  );
  statusBarItem.command = "promptgenie.lintAndScan";
  statusBarItem.tooltip = "PromptGenie — Click to lint & scan";
  return statusBarItem;
}

export function updateStatusBar(lint?: LintOutput, scan?: ScanOutput): void {
  if (!statusBarItem) return;

  const show = vscode.workspace
    .getConfiguration("promptgenie")
    .get<boolean>("showScoreInStatusBar", true);

  if (!show) {
    statusBarItem.hide();
    return;
  }

  const score = lint?.score ?? null;
  const issueCount = lint?.issue_count ?? 0;
  const findingCount = scan?.finding_count ?? 0;
  const riskLevel = scan?.risk_level ?? "NONE";

  // Score colour
  let scoreIcon = "$(pass)";
  if (score !== null) {
    if (score < 50) scoreIcon = "$(error)";
    else if (score < 75) scoreIcon = "$(warning)";
    else scoreIcon = "$(pass)";
  }

  // Risk badge
  let riskBadge = "";
  if (riskLevel === "CRITICAL" || riskLevel === "HIGH") {
    riskBadge = " $(shield) HIGH";
  } else if (riskLevel === "MEDIUM") {
    riskBadge = " $(shield) MED";
  }

  const scorePart = score !== null ? ` ${score}/100` : "";
  const issuePart =
    issueCount + findingCount > 0
      ? ` · ${issueCount + findingCount} issue${issueCount + findingCount !== 1 ? "s" : ""}`
      : "";

  statusBarItem.text = `${scoreIcon} PG${scorePart}${issuePart}${riskBadge}`;

  if (score !== null && score < 50) {
    statusBarItem.backgroundColor = new vscode.ThemeColor(
      "statusBarItem.errorBackground"
    );
  } else if (score !== null && score < 75) {
    statusBarItem.backgroundColor = new vscode.ThemeColor(
      "statusBarItem.warningBackground"
    );
  } else {
    statusBarItem.backgroundColor = undefined;
  }

  statusBarItem.show();
}

export function setStatusBarRunning(): void {
  if (!statusBarItem) return;
  statusBarItem.text = "$(sync~spin) PG: analysing…";
  statusBarItem.backgroundColor = undefined;
  statusBarItem.show();
}

export function setStatusBarError(msg: string): void {
  if (!statusBarItem) return;
  statusBarItem.text = "$(error) PG: error";
  statusBarItem.tooltip = `PromptGenie error: ${msg}`;
  statusBarItem.backgroundColor = new vscode.ThemeColor(
    "statusBarItem.errorBackground"
  );
  statusBarItem.show();
}

export function hideStatusBar(): void {
  statusBarItem?.hide();
}

export function disposeStatusBar(): void {
  statusBarItem?.dispose();
}
