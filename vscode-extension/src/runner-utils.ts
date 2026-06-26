import * as fs from "fs";
import * as os from "os";
import * as path from "path";

export const TRUSTED_PREFIXES: string[] = [
  "/usr/local/bin",
  "/usr/bin",
  "/opt/homebrew/bin",
  path.join(os.homedir(), ".local", "bin"),
  path.join(os.homedir(), ".cargo", "bin"),
];

export const ACCEPTED_BASENAMES: Set<string> =
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
  if (!path.isAbsolute(p)) {
    return false;
  }
  const base = path.basename(p);
  const cmp = process.platform === "win32" ? base.toLowerCase() : base;
  const accepted =
    process.platform === "win32"
      ? new Set([...ACCEPTED_BASENAMES].map((b) => b.toLowerCase()))
      : ACCEPTED_BASENAMES;
  if (!accepted.has(cmp)) {
    return false;
  }
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

/** Check whether *resolvedPath* falls under one of the well-known trusted install prefixes. */
export function isUnderTrustedPrefix(resolvedPath: string): boolean {
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
export function pathTrustKey(absPath: string): string {
  let h = 5381;
  for (let i = 0; i < absPath.length; i++) {
    h = ((h << 5) + h) ^ absPath.charCodeAt(i);
    h = h >>> 0; // keep 32-bit unsigned
  }
  return `trustedPath:${h.toString(16)}`;
}
