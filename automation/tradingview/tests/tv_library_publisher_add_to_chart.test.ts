import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

// 2026-07-27 production evidence (run 30248563009) proved that
// `tolerateFailure: true` does not cover the outer runTrackedStep timeout:
// the timeout wins the Promise.race before addCurrentScriptToChart reaches its
// internal tolerance branch, so the publisher still exits with
// `publishAttempted: false`.
//
// The pre-publish insertion is unnecessary. publishPrivateScript owns the
// fail-closed "Script is not on the chart" gate and resolves it from the
// publish dialog. This contract therefore forbids the redundant chart probe
// between the compile gate and publish attempt.

const _dir = path.dirname(fileURLToPath(import.meta.url));
const _scriptsDir = path.resolve(_dir, "..", "..", "..", "scripts");

const LIBRARY_PUBLISHERS = [
  "bus",
  "context_engine",
  "context_resolvers",
  "core_types",
  "draw",
  "engine",
  "lifecycle",
  "micro",
  "observability",
  "overlay",
  "profile_engine",
  "utils",
];

for (const name of LIBRARY_PUBLISHERS) {
  test(`tv_publish_${name}_library delegates the chart gate to publishPrivateScript`, () => {
    const source = fs.readFileSync(
      path.join(_scriptsDir, `tv_publish_${name}_library.ts`),
      "utf-8",
    );
    const compileGate = source.indexOf("await assertNoVisibleCompileError(");
    const publishCall = source.indexOf("await publishPrivateScript(", compileGate);

    assert.ok(
      compileGate >= 0 && publishCall > compileGate,
      `tv_publish_${name}_library.ts must retain its compile gate before publishing`,
    );
    assert.doesNotMatch(
      source.slice(compileGate, publishCall),
      /addCurrentScriptToChart\(/,
      `tv_publish_${name}_library.ts must not run the redundant pre-publish `
      + "chart probe; publishPrivateScript owns the hard chart gate",
    );
  });
}
