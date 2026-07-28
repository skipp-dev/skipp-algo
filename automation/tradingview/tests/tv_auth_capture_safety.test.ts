import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  acquireExclusiveFileLock,
  writePrivateJsonAtomic,
} from "../lib/tv_shared.js";

test("credential JSON is atomically replaced with owner-only permissions", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "tv-auth-private-json-"));
  const target = path.join(root, "storage-state.json");
  try {
    fs.writeFileSync(target, '{"stale":true}\n', { mode: 0o644 });

    writePrivateJsonAtomic(target, { fresh: true });

    assert.deepEqual(JSON.parse(fs.readFileSync(target, "utf-8")), { fresh: true });
    if (process.platform !== "win32") {
      assert.equal(fs.statSync(target).mode & 0o777, 0o600);
    }
    assert.deepEqual(
      fs.readdirSync(root),
      ["storage-state.json"],
      "atomic writer must not leave credential-bearing temporary files",
    );
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("capture lock rejects a second owner and releases only its own token", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "tv-auth-lock-"));
  const lockPath = path.join(root, "capture.lock");
  try {
    const first = acquireExclusiveFileLock(lockPath, "first-owner");
    if (process.platform !== "win32") {
      assert.equal(fs.statSync(lockPath).mode & 0o777, 0o600);
    }
    assert.throws(
      () => acquireExclusiveFileLock(lockPath, "second-owner"),
      /already held by first-owner/,
    );

    first.release();
    const second = acquireExclusiveFileLock(lockPath, "second-owner");
    second.release();
    assert.equal(fs.existsSync(lockPath), false);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
