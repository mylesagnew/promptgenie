import * as assert from "assert";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { isTrustedPath, isUnderTrustedPrefix, pathTrustKey, resolveOnPath } from "../runner-utils";

describe("isTrustedPath", () => {
  it("rejects relative paths", () => {
    assert.strictEqual(isTrustedPath("promptgenie"), false);
    assert.strictEqual(isTrustedPath("./bin/promptgenie"), false);
  });

  it("rejects absolute paths with wrong basename", () => {
    assert.strictEqual(isTrustedPath("/usr/local/bin/evil"), false);
    assert.strictEqual(isTrustedPath("/usr/bin/pg"), false);
    assert.strictEqual(isTrustedPath("/usr/bin/promptgenie-cli"), false);
  });

  it("rejects absolute path with correct basename that does not exist", () => {
    assert.strictEqual(isTrustedPath("/nonexistent/path/to/promptgenie"), false);
  });

  it("accepts a real file named promptgenie", () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "pg-test-"));
    const p = path.join(tmp, "promptgenie");
    try {
      fs.writeFileSync(p, "#!/bin/sh\necho ok\n");
      assert.strictEqual(isTrustedPath(p), true);
    } finally {
      fs.rmSync(tmp, { recursive: true, force: true });
    }
  });

  it("rejects a directory named promptgenie", () => {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "pg-test-"));
    const dir = path.join(tmp, "promptgenie");
    try {
      fs.mkdirSync(dir);
      assert.strictEqual(isTrustedPath(dir), false);
    } finally {
      fs.rmSync(tmp, { recursive: true, force: true });
    }
  });
});

describe("isUnderTrustedPrefix", () => {
  it("accepts paths under standard system prefixes", () => {
    assert.strictEqual(isUnderTrustedPrefix("/usr/local/bin/promptgenie"), true);
    assert.strictEqual(isUnderTrustedPrefix("/usr/bin/promptgenie"), true);
    assert.strictEqual(isUnderTrustedPrefix("/opt/homebrew/bin/promptgenie"), true);
  });

  it("accepts paths under user home prefixes", () => {
    const home = os.homedir();
    assert.strictEqual(
      isUnderTrustedPrefix(path.join(home, ".local", "bin", "promptgenie")),
      true
    );
    assert.strictEqual(
      isUnderTrustedPrefix(path.join(home, ".cargo", "bin", "promptgenie")),
      true
    );
  });

  it("rejects paths outside trusted prefixes", () => {
    assert.strictEqual(isUnderTrustedPrefix("/tmp/promptgenie"), false);
    assert.strictEqual(isUnderTrustedPrefix("/home/user/Downloads/promptgenie"), false);
  });

  it("does not match on prefix substring without path separator", () => {
    assert.strictEqual(isUnderTrustedPrefix("/usr/local/binary"), false);
  });
});

describe("pathTrustKey", () => {
  it("returns a string prefixed with trustedPath:", () => {
    assert.ok(pathTrustKey("/usr/local/bin/promptgenie").startsWith("trustedPath:"));
  });

  it("is stable for the same input", () => {
    const p = "/usr/local/bin/promptgenie";
    assert.strictEqual(pathTrustKey(p), pathTrustKey(p));
  });

  it("produces different keys for different paths", () => {
    assert.notStrictEqual(
      pathTrustKey("/usr/local/bin/promptgenie"),
      pathTrustKey("/usr/bin/promptgenie")
    );
  });
});

describe("resolveOnPath", () => {
  const exe = process.platform === "win32" ? "promptgenie.exe" : "promptgenie";
  const sep = process.platform === "win32" ? ";" : ":";

  function mkBin(): string {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pg-path-"));
    fs.writeFileSync(path.join(dir, exe), "#!/bin/sh\necho ok\n");
    return dir;
  }

  it("returns an absolute path from PATH, never a bare name", () => {
    const dir = mkBin();
    try {
      const got = resolveOnPath(dir, []);
      assert.strictEqual(got, path.join(dir, exe));
      assert.ok(got && path.isAbsolute(got));
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });

  it("skips workspace / opened-file directories even when they are on PATH", () => {
    const workspace = mkBin();
    const real = mkBin();
    try {
      const got = resolveOnPath([workspace, real].join(sep), [workspace]);
      assert.strictEqual(got, path.join(real, exe));
    } finally {
      fs.rmSync(workspace, { recursive: true, force: true });
      fs.rmSync(real, { recursive: true, force: true });
    }
  });

  it("skips empty and relative PATH entries", () => {
    assert.strictEqual(resolveOnPath(["", ".", "bin"].join(sep), []), undefined);
  });

  it("returns undefined when nothing acceptable is found", () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), "pg-path-"));
    try {
      assert.strictEqual(resolveOnPath(dir, []), undefined);
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
    }
  });
});
