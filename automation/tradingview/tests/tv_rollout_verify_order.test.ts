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
  const s = source();
  const from = s.indexOf("resolveProducerRefreshChartUrls(config)");
  const to = s.indexOf("groupTargetsByLayout(");
  assert.ok(0 < from && from < to, "expected refresh phase before binding loop");

  const between = s.slice(from, to);
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
  const s = source();
  const from = s.indexOf("resolveProducerRefreshChartUrls(config)");
  const to = s.indexOf("groupTargetsByLayout(");
  const between = s.slice(from, to);

  for (const match of between.matchAll(/await gotoChart\(/g)) {
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
