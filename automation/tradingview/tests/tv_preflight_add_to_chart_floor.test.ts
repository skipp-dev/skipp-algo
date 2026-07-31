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

// 2026-07-31: the mutating preflight saved a fixed SMC HTF Confluence source,
// then hit addCurrentScriptToChart's "already present" fast path and measured
// the STALE chart instance — re-reporting the pre-fix CE10156 for a source
// pine-facade had already accepted. A mutating run must clear existing
// instances and force a fresh insert so every downstream axis (runtime smoke
// included) measures the just-saved source.
test("the mutating preflight clears stale instances and force-inserts after save", () => {
  const source = preflightSource();

  const mutatingBranch = source.match(
    /if \(cli\.executionMode === "mutating" && target\.scriptName\) \{[\s\S]*?removeVisibleChartScriptInstances[\s\S]*?addCurrentScriptToChart\([^;]*?forceInsert: true[\s\S]*?\}/,
  );
  assert.ok(
    mutatingBranch,
    "tv_preflight's add-to-chart block must, in mutating mode, call "
    + "removeVisibleChartScriptInstances and then addCurrentScriptToChart with "
    + "forceInsert: true — otherwise the 'already present' fast path re-measures "
    + "the stale instance after a source change (the 2026-07-31 CE10156 re-run).",
  );

  const staleReuse = source.match(
    /usedFreshDraftPath/,
  );
  assert.equal(
    staleReuse,
    null,
    "the fresh-draft-only guard must stay retired: forceInsert now applies to "
    + "every mutating run, not only the fresh-draft path",
  );
});
