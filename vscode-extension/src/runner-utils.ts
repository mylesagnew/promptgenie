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

/**
 * Resolve the default `promptgenie` command to an absolute path by walking
 * *pathEnv* ourselves, instead of handing a bare name to `child_process.spawn`.
 *
 * On Windows a bare command name can be resolved from the child's `cwd` before
 * PATH, and the extension spawns with the workspace (or the opened file's
 * directory) as `cwd` — so a `promptgenie.exe` planted in an opened repository
 * would run. Empty and relative PATH entries, and every directory in
 * *excludeDirs*, are skipped; the result must also pass `isTrustedPath`.
 *
 * @returns the absolute path, or `undefined` if no acceptable binary is found.
 */
export function resolveOnPath(
  pathEnv: string,
  excludeDirs: string[],
  platform: NodeJS.Platform = process.platform
): string | undefined {
  const win = platform === "win32";
  const norm = (d: string) => {
    const n = path.resolve(d);
    return win ? n.toLowerCase() : n;
  };
  const excluded = new Set(excludeDirs.filter(Boolean).map(norm));
  const names = win ? ["promptgenie.exe"] : ["promptgenie"];
  for (const dir of pathEnv.split(win ? ";" : ":")) {
    if (!dir || !path.isAbsolute(dir) || excluded.has(norm(dir))) {
      continue;
    }
    for (const name of names) {
      const candidate = path.join(dir, name);
      if (isTrustedPath(candidate)) {
        return candidate;
      }
    }
  }
  return undefined;
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
