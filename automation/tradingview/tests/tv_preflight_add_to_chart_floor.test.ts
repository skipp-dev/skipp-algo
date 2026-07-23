import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

// 2026-07-23: refresh run 30023429034 published a populated v162, then the
// POST-release validation timed out at the default 45s inside
// addCurrentScriptToChart (report: compile_ok=not_run,
// "Step timed out after 45000ms: addCurrentScriptToChart"). That failed the
// strict release gate and SKIPPED the consumer repin, so the good library was
// published but never adopted.
//
// #3899 raised exactly this inner step to a 90s floor for the publish and
// producer-refresh paths (the documented 44s insertion race). tv_preflight's
// two add-to-chart calls were not covered and still ran at 45s. This pins the
// same floor onto both so the validation path cannot time out where the publish
// path already succeeds.

const _dir = path.dirname(fileURLToPath(import.meta.url));
const _repoRoot = path.resolve(_dir, "..", "..", "..");

function preflightSource(): string {
  return fs.readFileSync(path.join(_repoRoot, "scripts", "tv_preflight.ts"), "utf-8");
}

/** Every addCurrentScriptToChart(...) call's argument list, brace-balanced. */
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
      if (source[i] === "(") {
        depth += 1;
      } else if (source[i] === ")") {
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
  assert.deepEqual(
    addToChartCalls("await addCurrentScriptToChart(p, n, { a: f(1) });\nx(addCurrentScriptToChart(q, m));\n"),
    ["p, n, { a: f(1) }", "q, m"],
  );
});

test("every preflight add-to-chart carries the same 90s floor as the publish path", () => {
  const calls = addToChartCalls(preflightSource());
  assert.ok(calls.length >= 2, `expected preflight to call addCurrentScriptToChart; found ${calls.length}`);
  for (const args of calls) {
    assert.match(
      args,
      /stepTimeoutMs:\s*Math\.max\(stepTimeoutMs\(\),\s*90_000\)/,
      "tv_preflight add-to-chart must carry stepTimeoutMs: Math.max(stepTimeoutMs(), 90_000) — "
      + "the post-release validation timed out at the default 45s where the 90s "
      + `publish path succeeds. Args were: ${args}`,
    );
  }
});
