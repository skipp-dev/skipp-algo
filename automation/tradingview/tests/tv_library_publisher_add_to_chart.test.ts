import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

// 2026-07-22 publish stall: every library publisher called
// `addCurrentScriptToChart(...)` as a HARD step before `publishPrivateScript`.
// A Pine `library()` never gets a chart legend row, so once the bogus
// strategy-report clause was removed from `isScriptVisibleOnChart`, that call
// can no longer short-circuit — it walks the full click/indicators/hotkey
// insertion path and burns its whole step budget before throwing, killing the
// publish with `publishAttempted: false`.
//
// It does not need to succeed: `publishPrivateScript` already handles the
// "Script is not on the chart" gate itself, including the in-dialog "Add to
// chart" button that TradingView offers for libraries. So the pre-emptive call
// is an optimisation, and an optimisation must never be able to fail the run.
// This contract pins `tolerateFailure` into every library publisher.

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

/** Every `addCurrentScriptToChart(` call in a publisher, with its argument list. */
function addToChartCalls(source: string): string[] {
  const calls: string[] = [];
  const needle = "addCurrentScriptToChart(";
  let from = 0;
  for (;;) {
    const start = source.indexOf(needle, from);
    if (start === -1) {
      break;
    }
    const open = start + needle.length - 1;
    let depth = 0;
    let end = open;
    for (let i = open; i < source.length; i += 1) {
      const ch = source[i];
      if (ch === "(") {
        depth += 1;
      } else if (ch === ")") {
        depth -= 1;
        if (depth === 0) {
          end = i;
          break;
        }
      }
    }
    calls.push(source.slice(open + 1, end));
    from = end + 1;
  }
  return calls;
}

test("addToChartCalls extracts each call's argument list", () => {
  const calls = addToChartCalls(
    'await addCurrentScriptToChart(p, name(x), { tolerateFailure: true });\n'
    + "await addCurrentScriptToChart(p, other);\n",
  );
  assert.deepEqual(calls, ["p, name(x), { tolerateFailure: true }", "p, other"]);
});

for (const name of LIBRARY_PUBLISHERS) {
  test(`tv_publish_${name}_library tolerates a failed pre-publish add-to-chart`, () => {
    const source = fs.readFileSync(
      path.join(_scriptsDir, `tv_publish_${name}_library.ts`),
      "utf-8",
    );
    const calls = addToChartCalls(source);
    assert.ok(
      calls.length > 0,
      `tv_publish_${name}_library.ts no longer calls addCurrentScriptToChart — `
      + "drop it from LIBRARY_PUBLISHERS if that is intended",
    );
    for (const args of calls) {
      assert.match(
        args,
        /tolerateFailure:\s*true/,
        `tv_publish_${name}_library.ts calls addCurrentScriptToChart without `
        + `tolerateFailure: a library has no legend row, so this call cannot `
        + `succeed and must not be able to fail the publish. Args were: ${args}`,
      );
    }
  });
}
