import * as assert from "assert";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import { isTrustedPath, isUnderTrustedPrefix, pathTrustKey } from "../runner-utils";

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
