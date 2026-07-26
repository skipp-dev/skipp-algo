import assert from "node:assert/strict";
import { test } from "node:test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { resolveProducerRefreshChartUrls } from "../lib/tv_shared.js";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");

// The applied Suite instance lives in EVERY layout that carries consumers —
// the 2026-07-22 live run refreshed only primaryChartUrl (desktop vWgAWyfC)
// while the operator was looking at the Mobile layout (YcGLVHXR), so the
// visible instance stayed frozen despite a "working" producer refresh.
test("producer refresh covers primary plus every distinct target layout", () => {
  const urls = resolveProducerRefreshChartUrls({
    primaryChartUrl: "https://tv.example/chart/AAA/",
    verifyTargets: [
      {},
      { chartUrl: "https://tv.example/chart/BBB/" },
      { chartUrl: "https://tv.example/chart/AAA/" },
      { chartUrl: "https://tv.example/chart/BBB/" },
    ],
  });
  assert.deepEqual(urls, [
    "https://tv.example/chart/AAA/",
    "https://tv.example/chart/BBB/",
  ]);
});

test("primary layout always comes first and empty target urls are ignored", () => {
  const urls = resolveProducerRefreshChartUrls({
    primaryChartUrl: "https://tv.example/chart/MAIN/",
    verifyTargets: [{}],
  });
  assert.deepEqual(urls, ["https://tv.example/chart/MAIN/"]);
});

test("rollout loops the producer refresh over every resolved layout", () => {
  const source = fs.readFileSync(
    path.join(repoRoot, "scripts", "tv_batch_consumer_rollout.ts"),
    "utf-8",
  );
  assert.match(source, /resolveProducerRefreshChartUrls\(config\)/);
  assert.match(source, /for \(const producerChartUrl of /);
  // The loop must NOT call ensurePineEditor itself: the intolerant outer
  // call stranded run 29946386778 on /pine-screener/ before layout 2;
  // refreshChartScriptInstance opens the editor fault-tolerantly.
  const producerBlock = source.split("resolveProducerRefreshChartUrls(config)", 2)[1]?.split("report.producerRefresh.ok = true", 1)[0] ?? "";
  assert.doesNotMatch(producerBlock, /await ensurePineEditor/);
});

// The applied-instance refresh is cosmetic (it re-adds an already-published
// script so the visible chart picks up the new version). Verifying consumer
// SOURCES and BINDINGS is the critical, load-bearing work. Runs 29929470730 and
// 29946386778 both reported `sources.checked 0` / `bindings 0` purely because
// the fragile refresh timed out first and its `ok` flag gated the verification
// block — the important check was blocked by the nice-to-have one.
test("consumer verification gates on save success alone, never on the cosmetic refresh", () => {
  const source = fs.readFileSync(
    path.join(repoRoot, "scripts", "tv_batch_consumer_rollout.ts"),
    "utf-8",
  );
  assert.doesNotMatch(source, /report\.save\.failed\.length === 0 && report\.producerRefresh\.ok/);
  // Saves still gate verification: verifying sources we failed to write is meaningless.
  const saveGatedVerification = source.split("if (report.save.failed.length === 0)", 2)[1] ?? "";
  assert.match(saveGatedVerification, /for \(const target of sourceVerificationTargets\)/);
  assert.match(saveGatedVerification, /result = await verifyConsumerSource\(session, target\)/);
});

test("a failed producer refresh is non-fatal but stays visible as evidence", () => {
  const source = fs.readFileSync(
    path.join(repoRoot, "scripts", "tv_batch_consumer_rollout.ts"),
    "utf-8",
  );
  const okExpression = source.split("report.ok = ", 2)[1]?.split(";", 1)[0] ?? "";
  assert.notEqual(okExpression, "");
  // Best-effort: a cosmetic refresh timeout must not turn a fully verified run red.
  assert.doesNotMatch(okExpression, /producerRefresh/);
  // Non-fatal must never mean silent — the failure keeps a warning and its report field.
  assert.match(source, /report\.producerRefresh\.error/);
  assert.match(source, /console\.warn\([^)]*producer refresh/i);
});

test("refresh-path add-to-chart carries the same 90s floor as its wrapper", () => {
  // The inner addCurrentScriptToChart step timed out at its default 45s while
  // the outer refreshChartScriptInstance timer had already been raised to 90s
  // for exactly this documented 44s-insertion race (live run 29929470730).
  const shared = fs.readFileSync(
    path.join(repoRoot, "automation", "tradingview", "lib", "tv_shared.ts"),
    "utf-8",
  );
  const refreshBlock = shared.split("export async function refreshChartScriptInstance", 2)[1] ?? "";
  assert.match(
    refreshBlock.slice(0, 2000),
    /addCurrentScriptToChart\(page, scriptName, \{[^}]*stepTimeoutMs: Math\.max\(stepTimeoutMs\(\), 90_000\)/s,
  );
});
