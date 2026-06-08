/**
 * types.ts — TypeScript interfaces matching the PromptGenie CLI JSON output.
 *
 * Kept in sync with promptgenie/core/formatters.py (lint_to_json / scan_to_json).
 */

// ── Lint output ──────────────────────────────────────────────────────────────

export interface LintIssue {
  code: string;
  severity: "HIGH" | "MEDIUM" | "LOW" | "INFO";
  confidence: "HIGH" | "MEDIUM" | "LOW";
  line: number;
  col: number;
  message: string;
  suggestion: string;
}

export interface LintOutput {
  tool: string;
  command: "lint";
  file: string;
  score: number;
  issue_count: number;
  issues: LintIssue[];
}

// ── Scan output ──────────────────────────────────────────────────────────────

export interface ScanFinding {
  code: string;
  risk: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW";
  confidence: "HIGH" | "MEDIUM" | "LOW";
  line: number;
  col: number;
  message: string;
  detail: string;
  recommendation: string;
}

export interface ScanOutput {
  tool: string;
  command: "scan";
  file: string;
  risk_level: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "NONE";
  finding_count: number;
  findings: ScanFinding[];
}

// ── Shared ───────────────────────────────────────────────────────────────────

export type SeverityLevel = "error" | "warning" | "information" | "hint";

export interface RunResult {
  lintOutput?: LintOutput;
  scanOutput?: ScanOutput;
  error?: string;
}
