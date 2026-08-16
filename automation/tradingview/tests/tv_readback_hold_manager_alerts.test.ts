import assert from "node:assert/strict";
import test from "node:test";

import {
  ALERT_NAME_PREFIX,
  BUILD_ALERT_DEFAULT_NAME_START,
  READ_ALERT_ROWS,
  assertNoOpaqueTokens,
  assertNoUrls,
  classifyAlerts,
  classifyBuildAlert,
  isRunning,
  type AlertRow,
} from "../../../scripts/tv_readback_hold_manager_alerts.js";

const CHANNELS = ["HM_ENTRY", "HM_T1", "HM_T2", "HM_STOP", "HM_TIMESTOP", "HM_EXIT_ANY"];

/** The shape measured live on 2026-08-14, one row per shadow channel. */
function shadowRow(channel: string, over: Partial<AlertRow> = {}): AlertRow {
  return {
    name: `${ALERT_NAME_PREFIX}${channel}`,
    ticker: "BKNG, 5m",
    status: "Active",
    hasDescription: true,
    hasStop: true,
    hasRestart: false,
    ...over,
  };
}

const FOREIGN: AlertRow = {
  name: "5 bearish reversal confirmed with footprint support 15",
  ticker: "stock, 5m",
  status: "Stopped manually",
  hasDescription: true,
  hasStop: false,
  hasRestart: true,
};

test("the live shape read on 2026-08-14 is accepted in full", () => {
  const rows = [...CHANNELS.map((c) => shadowRow(c)), FOREIGN];

  const verdict = classifyAlerts(rows, CHANNELS);

  assert.deepEqual(verdict.missingChannels, []);
  assert.deepEqual(verdict.notRunningChannels, []);
  assert.equal(verdict.matched.length, 6);
  assert.equal(verdict.foreignAlertCount, 1);
  assert.equal(verdict.matched[0].ticker, "BKNG, 5m");
});

test("a missing channel is reported rather than silently dropped", () => {
  const rows = CHANNELS.filter((c) => c !== "HM_STOP").map((c) => shadowRow(c));

  const verdict = classifyAlerts(rows, CHANNELS);

  assert.deepEqual(verdict.missingChannels, ["HM_STOP"]);
  assert.equal(verdict.matched.length, 5);
});

test("running is decided by the control, not by the status text", () => {
  // TradingView localises the status string; it does not localise data-name.
  // A stopped alert whose status text still reads Active must not pass.
  const lying = shadowRow("HM_T1", { hasStop: false, hasRestart: true, status: "Active" });

  assert.equal(isRunning(lying), false);
  assert.deepEqual(classifyAlerts([lying], ["HM_T1"]).notRunningChannels, ["HM_T1"]);
});

test("an alert whose name merely contains a channel does not match", () => {
  const decoy = shadowRow("HM_ENTRY", { name: "copy of R2 SHADOW · HM_ENTRY" });

  assert.deepEqual(classifyAlerts([decoy], ["HM_ENTRY"]).missingChannels, ["HM_ENTRY"]);
});

test("the post-cutover shape is one build alert, zero legacy, name measured", () => {
  const rows = [
    shadowRow("BUILD", { name: `${ALERT_NAME_PREFIX}BUILD`, hasDescription: true }),
    FOREIGN,
  ];

  const verdict = classifyBuildAlert(rows, CHANNELS);

  assert.equal(verdict.buildAlert?.name, "R2 SHADOW · BUILD");
  assert.equal(verdict.buildAlert?.running, true);
  assert.deepEqual(verdict.extraPrefixAlerts, []);
  assert.deepEqual(verdict.legacyChannelAlertsRemaining, []);
  assert.equal(verdict.foreignAlertCount, 1);
});

test("a surviving legacy channel alert is reported, not counted as the build alert", () => {
  const rows = [
    shadowRow("BUILD", { name: `${ALERT_NAME_PREFIX}BUILD` }),
    shadowRow("HM_STOP"),
  ];

  const verdict = classifyBuildAlert(rows, CHANNELS);

  assert.equal(verdict.buildAlert?.name, "R2 SHADOW · BUILD");
  assert.deepEqual(verdict.legacyChannelAlertsRemaining, ["R2 SHADOW · HM_STOP"]);
});

test("two prefix alerts are ambiguous and surface as extras", () => {
  const rows = [
    shadowRow("BUILD", { name: `${ALERT_NAME_PREFIX}BUILD` }),
    shadowRow("BUILD2", { name: `${ALERT_NAME_PREFIX}BUILD OLD` }),
  ];

  const verdict = classifyBuildAlert(rows, CHANNELS);

  assert.deepEqual(verdict.extraPrefixAlerts, ["R2 SHADOW · BUILD OLD"]);
});

test("no prefix alert at all yields a null build alert, not a crash", () => {
  const verdict = classifyBuildAlert([FOREIGN], CHANNELS);

  assert.equal(verdict.buildAlert, null);
  assert.equal(verdict.foreignAlertCount, 1);
});

test("the TradingView default-named build alert is accepted as measured live", () => {
  // 2026-08-16, operator's alerts panel: the build alert kept TradingView's
  // default name (condition description), not the R2 SHADOW convention.
  const rows = [
    shadowRow("BUILD", {
      name: `${BUILD_ALERT_DEFAULT_NAME_START}Engine BUS v2, 0,00, 14, 21)`,
    }),
    FOREIGN,
  ];

  const verdict = classifyBuildAlert(rows, CHANNELS);

  assert.ok(verdict.buildAlert?.name.startsWith(BUILD_ALERT_DEFAULT_NAME_START));
  assert.equal(verdict.buildAlert?.running, true);
  assert.deepEqual(verdict.legacyChannelAlertsRemaining, []);
  assert.equal(verdict.foreignAlertCount, 1);
});

test("assertNoUrls rejects a webhook URL anywhere in the tree", () => {
  assert.throws(
    () => assertNoUrls({ a: [{ b: "https://example.invalid/x/y" }] }),
    /leak a URL at \$\.a\[0\]\.b/,
  );
});

test("assertNoOpaqueTokens rejects a long opaque run", () => {
  assert.throws(
    () => assertNoOpaqueTokens({ nested: { token: "x".repeat(40) } }),
    /leak an opaque token at \$\.nested\.token/,
  );
});

test("the token check is not applied to the probe's own prose", () => {
  // Measured on the first live run: sweeping the whole tree refused to write
  // at all, because this legitimate artifact filename is a 35-character run
  // of [A-Za-z0-9_]. The narrower scope is the fix; loosening the pattern
  // until the filename passed would have weakened the check that matters.
  const filename = "smc_hold_manager_shadow_alerts_2026-07-28.json";
  assert.ok(/[A-Za-z0-9_\-]{32,}/.test(filename), "the filename must still look opaque");
  assert.doesNotThrow(() => assertNoUrls({ supersedes: { artifact: filename } }));
});

test("both checks accept the evidence the probe actually writes", () => {
  // The positive cases are only meaningful next to the negatives above: a
  // scrubber that accepted everything would pass these alone.
  const alerts = [
    { channel: "HM_ENTRY", name: `${ALERT_NAME_PREFIX}HM_ENTRY`, ticker: "BKNG, 5m", status: "Active", running: true },
  ];
  assert.doesNotThrow(() => assertNoOpaqueTokens(alerts));
  assert.doesNotThrow(() => assertNoUrls({ requirementId: "R2-SHADOW-CUTOVER", alerts }));
});

test("the page-side reader never touches the description text", () => {
  // The description field is the full webhook body and carries the token.
  // Presence may be recorded; content may not be.
  assert.ok(READ_ALERT_ROWS.includes('hasDescription'));
  assert.ok(
    !/q\(\s*'\[data-name="alert-item-description"\]'\s*\)/.test(READ_ALERT_ROWS),
    "the reader must not extract description text",
  );
});
