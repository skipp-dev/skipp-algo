import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const _dir = path.dirname(fileURLToPath(import.meta.url));
const ROLLOUT = path.join(_dir, "..", "..", "..", "scripts", "tv_batch_consumer_rollout.ts");

// Root cause of six red R4 runs (30694013096, 30696257671, 30698519321,
// 30700161400, 30702240413, 30718040533), proven 2026-08-02: a freshly
// inserted chart instance is an UNSAVED layout mutation, and the source
// verification's hard reload — which sits between the instance refreshes and
// the binding verification — discards it. The probes were never blind; they
// truthfully reported a chart that the reload had just reverted to its saved
// state. Four detection-side fixes (#4304, #4307, #4313, #4320) attacked the
// wrong layer for exactly that reason.
//
// The reload itself is load-bearing (it makes source verification read
// TradingView's persisted saved-script state instead of the Monaco buffers
// this run just edited), so it cannot be dropped — it has to run BEFORE the
// refreshes, while there is nothing unsaved to destroy. These pins hold that
// order. The DOM behavior itself is Playwright-against-TradingView and only a
// live run proves it; run 30733442671 (62/62, layout saved) is the green
// reference this ordering must not regress.

const source = () => fs.readFileSync(ROLLOUT, "utf-8");

// The window below has to bound the REAL verification loop inside main(), not
// the read-only pre-mutation helper `observeBindingsOnly` that now sits ABOVE
// main() (added for the out-of-band drift check). That helper's body calls
// `groupTargetsByLayout(config.verifyTargets, config.primaryChartUrl)` with
// the exact same argument text as the real loop -- so neither `indexOf` (finds
// the helper's earlier occurrence) nor `lastIndexOf` (would silently break the
// same way again the day a THIRD call site is ever added below the real loop)
// can tell them apart by that string alone. Six red R4 runs and four wrong
// fixes came from an ordering bug in this exact region, so the anchor here
// has to be one that cannot be produced by any read-only helper: only the
// real loop's mutation path declares `repairBindings` as a mutable local
// immediately before grouping its targets -- a read-only pass has nothing to
// narrow, since it always calls verifyConsumerBindings with repair=false.
const TO_MARKER = "let repairBindings = executionPlan.repairBindings;";

/**
 * Locate a `[from, to)` window by two markers and refuse to hand back a
 * window nobody can vouch for.
 *
 * Both `indexOf` calls fail closed: a marker that has moved, been renamed, or
 * been duplicated above main() must fail this assertion LOUDLY, never pass
 * silently by producing an inverted or empty slice that the caller then
 * inspects as if it were real content (Finding 1, 2026-08-03: exactly that
 * happened here -- `s.slice(481-idx, 166-idx)` returned "" and a test still
 * asserted over it and reported green).
 */
function locateWindow(s: string, fromMarker: string, toMarker: string): { from: number; to: number; between: string } {
  const from = s.indexOf(fromMarker);
  const to = s.indexOf(toMarker);
  assert.ok(from >= 0, `start marker not found: ${JSON.stringify(fromMarker)}`);
  assert.ok(to >= 0, `end marker not found: ${JSON.stringify(toMarker)}`);
  assert.ok(
    from < to,
    `window is empty or inverted (from=${from}, to=${to}) -- both markers were found but not in the `
      + "expected order, which is exactly how the six-red-run bug passed silently before",
  );
  return { from, to, between: s.slice(from, to) };
}

test("source verification runs before the producer refresh", () => {
  const s = source();
  const verifyAt = s.indexOf("await verifyConsumerSource(session, target)");
  const producerRefreshAt = s.indexOf("resolveProducerRefreshChartUrls(config)");

  assert.ok(verifyAt > 0, "expected the source-verification call site");
  assert.ok(producerRefreshAt > 0, "expected the producer-refresh call site");
  assert.ok(
    verifyAt < producerRefreshAt,
    "source verification must precede the instance refreshes — its hard "
      + "reload discards unsaved inserts, which is the root cause of the six "
      + "red R4 runs",
  );
});

test("no primary-chart reload sits between the refreshes and the binding loop", () => {
  const { between } = locateWindow(source(), "resolveProducerRefreshChartUrls(config)", TO_MARKER);
  assert.doesNotMatch(
    between,
    /gotoChart\(session\.page, config\.primaryChartUrl\)/,
    "an unconditional primary reload here reverts the layout to its saved "
      + "state and silently deletes every instance the refreshes just added",
  );
});

test("the refresh-phase navigations stay conditional on a URL mismatch", () => {
  // A goto to the URL the page is already on is still a hard reload. The
  // producer and consumer refresh gotos must remain guarded, or refreshing
  // the second target destroys what the first one inserted.
  const { between } = locateWindow(source(), "resolveProducerRefreshChartUrls(config)", TO_MARKER);

  const gotos = [...between.matchAll(/await gotoChart\(/g)];
  assert.ok(
    gotos.length > 0,
    "no gotoChart call in the refresh window — the guard pin below would pass vacuously",
  );

  for (const match of gotos) {
    // 500 chars: the guard and the goto are separated by explanatory comments
    // (e.g. the "No ensurePineEditor here" block), which is fine — the pin
    // cares that a guard exists, not that it is adjacent.
    const before = between.slice(Math.max(0, match.index - 500), match.index);
    assert.match(
      before,
      /if \(!session\.page\.url\(\)\.startsWith\(/,
      "every refresh-phase gotoChart must be guarded by a URL check",
    );
  }
});

test("the ordering rationale is written where the reload lives", () => {
  // The reload's comment used to explain only WHY it exists, not what it
  // destroys — which is how the destructive ordering survived six runs and
  // four fixes. The lesson stays at the code.
  assert.match(
    source(),
    /BEFORE the (producer|instance)[\s\S]{0,600}(discard|unsaved)/i,
    "the reload must document that it has to run before the instance refreshes",
  );
});

// ---------------------------------------------------------------------------
// Task 3 (2026-08-22/23): repair-only must touch ONLY the layouts the
// pre-mutation snapshot named as needing repair. Unlike the pure selector
// (selectLayoutsNeedingRepair, unit-tested directly in
// tv_layouts_needing_repair.test.ts), the SKIP ITSELF lives inline in this
// file's layout loop and had no source-anchor regression pin — a future
// refactor could silently drop the `continue` and no test would notice.
// ---------------------------------------------------------------------------

test("a clean layout is skipped right after mutatingLayout is captured, before any target is read", () => {
  const s = source();
  const markerAt = s.indexOf("const mutatingLayout = repairBindings;");
  assert.ok(markerAt > 0, "mutatingLayout capture not found");
  const targetLoopAt = s.indexOf("for (const target of layout.targets) {", markerAt);
  assert.ok(targetLoopAt > markerAt, "per-target verification loop not found after mutatingLayout");
  const between = s.slice(markerAt, targetLoopAt);
  assert.match(
    between,
    /if \(executionPlan\.mode === "repair-only" && !layoutsNeedingRepair\.includes\(layout\.chartUrl\)\) \{/,
    "the repair-only skip must sit between mutatingLayout and the per-target loop, " +
      "or a clean layout's targets get read/repaired anyway",
  );
  assert.match(
    between,
    /continue;/,
    "the skip must actually leave the loop iteration — without `continue` the guard is a no-op",
  );
});

test("a skipped clean layout leaves a trace line in tracePageEvent's exact log format", () => {
  // tracePageEvent itself is module-private in tv_shared.ts and not imported
  // here (verified 2026-08-22) — the skip logs directly with console.error,
  // byte-identical to what tracePageEvent writes, so the line greps the same
  // for any reader or CI rule.
  assert.match(
    source(),
    /console\.error\(`\[tv-trace\] repair-skip-clean-layout \$\{layout\.chartUrl\}`\)/,
    "the skip must emit the [tv-trace] repair-skip-clean-layout line",
  );
});
