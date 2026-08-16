/**
 * Read-only readback of the Hold Manager R2 shadow alerts on TradingView.
 *
 * Why this exists: `smc_hold_manager_shadow_alerts_2026-07-28.json` records
 * that the six alerts exist on the basis of "Operator re-confirmed on
 * 2026-07-29", and states that TradingView alert state is "not machine-
 * verifiable from this repository". No probe was ever run to establish that.
 * It was run on 2026-08-14 and the claim is false: the alert list carries
 * stable `data-name` anchors and reads cleanly.
 *
 * What this proves: that each expected channel has an alert, on which symbol
 * and timeframe, and whether it is Active.
 *
 * What it deliberately does NOT prove: that the alert's webhook action is
 * enabled. That lives inside the per-alert edit dialog, which is a mutation
 * surface on live alerts firing into a production receiver, so this probe
 * refuses to open it. The receiver's own `/tradingview/hold-manager-shadow/
 * state` endpoint closes that gap with delivery counts and needs the operator
 * token, which is not handled here.
 *
 * Secrets: an alert's description field is its full webhook message body,
 * which for these alerts contains `authToken`. It is never read -- only its
 * presence is recorded -- and the evidence is scrubbed before it is written.
 */
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import {
  closeTradingViewSession,
  collectTradingViewPageAuthState,
  gotoChart,
  newTradingViewSession,
  type TradingViewSession,
} from "../automation/tradingview/lib/tv_shared.js";

export type AlertRow = {
  name: string;
  ticker: string | null;
  status: string | null;
  hasDescription: boolean;
  hasStop: boolean;
  hasRestart: boolean;
};

export type ChannelVerdict = {
  channel: string;
  name: string;
  ticker: string | null;
  status: string | null;
  running: boolean;
};

export type ReadbackVerdict = {
  matched: ChannelVerdict[];
  missingChannels: string[];
  notRunningChannels: string[];
  foreignAlertCount: number;
};

export const ALERT_NAME_PREFIX = "R2 SHADOW · ";

/**
 * The panel button is a TOGGLE and TradingView persists the panel state across
 * sessions. Measured 2026-08-14: an unconditional click opened the panel on
 * one run and closed it on the next, yielding zero rows. Read first, click
 * only when empty.
 */
export const READ_ALERT_ROWS = `(() => {
  var names = document.querySelectorAll('[data-name="alert-item-name"]');
  var rows = [];
  for (var i = 0; i < names.length; i++) {
    var row = names[i];
    for (var up = 0; up < 8 && row && row.parentElement; up++) {
      if (row.querySelector('[data-name="alert-item-status"]')) break;
      row = row.parentElement;
    }
    var q = function (sel) {
      var el = row.querySelector(sel);
      return el ? (el.textContent || '').trim().slice(0, 60) : null;
    };
    rows.push({
      name: (names[i].textContent || '').trim(),
      ticker: q('[data-name="alert-item-ticker"]'),
      status: q('[data-name="alert-item-status"]'),
      hasDescription: !!row.querySelector('[data-name="alert-item-description"]'),
      hasStop: !!row.querySelector('[data-name="alert-stop-button"]'),
      hasRestart: !!row.querySelector('[data-name="alert-restart-button"]')
    });
  }
  return rows;
})()`;

/** An alert is running when TradingView offers to stop it, not merely when its
 * status string looks encouraging: the status text is localised, the control
 * is not. Both are recorded; only the control decides. */
export function isRunning(row: AlertRow): boolean {
  return row.hasStop && !row.hasRestart;
}

export function classifyAlerts(rows: AlertRow[], channels: readonly string[]): ReadbackVerdict {
  const matched: ChannelVerdict[] = [];
  const missingChannels: string[] = [];
  const notRunningChannels: string[] = [];

  for (const channel of channels) {
    const row = rows.find((r) => r.name === `${ALERT_NAME_PREFIX}${channel}`);
    if (!row) {
      missingChannels.push(channel);
      continue;
    }
    const running = isRunning(row);
    if (!running) notRunningChannels.push(channel);
    matched.push({
      channel,
      name: row.name,
      ticker: row.ticker,
      status: row.status,
      running,
    });
  }

  const shadowNames = new Set(matched.map((m) => m.name));
  const foreignAlertCount = rows.filter((r) => !shadowNames.has(r.name)).length;

  return { matched, missingChannels, notRunningChannels, foreignAlertCount };
}

/**
 * TradingView defaults a new alert's name to its condition description,
 * "<instance title> (<inputs…>)". The operator created the build-pinned
 * alert with that default (measured 2026-08-16 from the operator's own
 * alerts panel), so the probe accepts it alongside the R2 SHADOW naming
 * convention instead of demanding a manual rename.
 */
export const BUILD_ALERT_DEFAULT_NAME_START = "SMC Hold Manager (";

export type BuildAlertVerdict = {
  buildAlert: ChannelVerdict | null;
  extraPrefixAlerts: string[];
  legacyChannelAlertsRemaining: string[];
  foreignAlertCount: number;
};

/**
 * Post-cutover wire shape: ONE build-pinned alert carries all six channels
 * (the channel travels in the alert() body, not in the alert name), and the
 * six per-channel legacy alerts must be gone. The alert's name is measured,
 * not assumed — the operator chooses it and only the two accepted name
 * shapes are contract.
 */
export function classifyBuildAlert(
  rows: AlertRow[],
  channels: readonly string[],
): BuildAlertVerdict {
  const legacyNames = new Set(channels.map((c) => `${ALERT_NAME_PREFIX}${c}`));
  const prefixRows = rows.filter(
    (r) =>
      r.name.startsWith(ALERT_NAME_PREFIX)
      || r.name.startsWith(BUILD_ALERT_DEFAULT_NAME_START),
  );
  const legacyRemaining = prefixRows
    .filter((r) => legacyNames.has(r.name))
    .map((r) => r.name);
  const candidates = prefixRows.filter((r) => !legacyNames.has(r.name));

  const [first, ...extras] = candidates;
  const buildAlert = first
    ? {
      channel: "ALL_VIA_ALERT_BODY",
      name: first.name,
      ticker: first.ticker,
      status: first.status,
      running: isRunning(first),
    }
    : null;

  return {
    buildAlert,
    extraPrefixAlerts: extras.map((r) => r.name),
    legacyChannelAlertsRemaining: legacyRemaining,
    foreignAlertCount: rows.length - prefixRows.length,
  };
}

const URL_RE = /https?:\/\/\S+/;
const OPAQUE_RE = /[A-Za-z0-9_\-]{32,}/;

function walk(value: unknown, trail: string, check: (s: string, at: string) => void): void {
  if (typeof value === "string") {
    check(value, trail);
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => walk(item, `${trail}[${index}]`, check));
    return;
  }
  if (value && typeof value === "object") {
    for (const [key, item] of Object.entries(value)) {
      walk(item, `${trail}.${key}`, check);
    }
  }
}

/**
 * No webhook URL may reach the evidence, anywhere in it.
 *
 * A whole-tree sweep rather than a field allow-list, because the next person
 * to add a field would not think to update an allow-list.
 */
export function assertNoUrls(value: unknown, trail = "$"): void {
  walk(value, trail, (s, at) => {
    if (URL_RE.test(s)) throw new Error(`readback evidence would leak a URL at ${at}`);
  });
}

/**
 * No long opaque run may reach the evidence from the page.
 *
 * Deliberately narrower in scope than {@link assertNoUrls}: applied only to
 * the subtree the probe read out of TradingView, never to the probe's own
 * prose. The first version swept everything and refused to write at all,
 * because a legitimate artifact FILENAME
 * (`smc_hold_manager_shadow_alerts_2026-07-28.json`) is a 35-character run of
 * `[A-Za-z0-9_]`. A scrubber that cannot distinguish its own words from the
 * page's is not stricter, only useless -- and the pressure to loosen the
 * pattern until the filename passes would have weakened the check that
 * matters.
 */
export function assertNoOpaqueTokens(value: unknown, trail = "$"): void {
  walk(value, trail, (s, at) => {
    if (OPAQUE_RE.test(s)) {
      throw new Error(`readback evidence would leak an opaque token at ${at}`);
    }
  });
}

export async function readAlertRows(session: TradingViewSession): Promise<{
  rows: AlertRow[];
  clickedToOpen: boolean;
}> {
  let rows = (await session.page.evaluate(READ_ALERT_ROWS)) as AlertRow[];
  let clickedToOpen = false;
  if (rows.length === 0) {
    await session.page.locator('button[data-name="alerts"]').first().click();
    await session.page.waitForTimeout(6000);
    rows = (await session.page.evaluate(READ_ALERT_ROWS)) as AlertRow[];
    clickedToOpen = true;
  }
  return { rows, clickedToOpen };
}

function getFlag(name: string, fallback = ""): string {
  const args = process.argv.slice(2);
  const index = args.indexOf(name);
  return index === -1 || !args[index + 1] ? fallback : args[index + 1];
}

export async function runReadbackCli(): Promise<number> {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  const contractPath = path.join(
    root,
    "artifacts/governance/smc_hold_manager_shadow_contract.json",
  );
  const contract = JSON.parse(fs.readFileSync(contractPath, "utf-8"));
  const channels: string[] = contract.activationRequirements.holdAlertChannels;
  const chartUrl = getFlag("--chart-url", "https://www.tradingview.com/chart/twh98JLB/");
  const outPath = getFlag("--out");
  // The wire shape decides what "the alerts are healthy" means. Default from
  // the contract; the explicit flag exists for the cutover sitting itself,
  // where the probe measures the NEW shape before the contract flip merges.
  const shape = getFlag(
    "--shape",
    contract.alertWireShape?.cutOver ? "build" : "channels",
  );
  if (shape !== "build" && shape !== "channels") {
    throw new Error(`unknown --shape: ${shape}`);
  }

  const session = await newTradingViewSession();
  try {
    if (!session.authResolution.authReusedOk) {
      throw new Error("readback requires a reusable authenticated TradingView session");
    }
    await gotoChart(session.page, chartUrl);
    await session.page.waitForTimeout(9000);

    // authReusedOk only proves cookies EXISTED; a revoked TradingView session
    // still loads the chart anonymously ("Ansichtsmodus") with an empty
    // alerts panel. Measured 2026-08-16: two probe runs wrote zero-row
    // "evidence" about an account they never saw. The page's own auth state
    // is the truth, so an anonymous page fails the probe instead of
    // publishing an empty observation.
    const pageAuth = await collectTradingViewPageAuthState(session.page);
    if (!pageAuth.authenticated) {
      throw new Error(
        `readback session is anonymous on the page (${pageAuth.reason}); `
        + "refusing to record an empty alerts panel as evidence",
      );
    }

    const { rows, clickedToOpen } = await readAlertRows(session);

    if (shape === "build") {
      const verdict = classifyBuildAlert(rows, channels);
      const evidence = {
        schemaVersion: 1,
        requirementId: contract.requirementId,
        capturedAt: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
        verificationMode: "automated_readonly_readback",
        wireShape: "build_path_token",
        supersedes: {
          artifact:
            "artifacts/governance/smc_hold_manager_shadow_alert_readback_2026-08-14.json",
          claim: "six per-channel alerts are the live wire shape",
          outcome:
            "superseded by the single build-pinned alert of the R2-SHADOW-CUTOVER sitting",
        },
        tradingView: {
          account: contract.tradingView.account,
          layout: contract.tradingView.validationLayout,
          savedScript: contract.tradingView.savedScript,
          panelOpenedByProbe: clickedToOpen,
        },
        buildAlert: verdict.buildAlert,
        extraPrefixAlerts: verdict.extraPrefixAlerts,
        legacyChannelAlertsRemaining: verdict.legacyChannelAlertsRemaining,
        foreignAlertCount: verdict.foreignAlertCount,
        limitations: [
          "Proves that exactly one build-pinned shadow alert exists, on which symbol and timeframe, whether TradingView offers to stop it, and that the six legacy channel alerts are gone. Does NOT prove the webhook action is enabled: that lives in the per-alert edit dialog, a mutation surface on a live alert, which this probe refuses to open.",
          "The alert description field is the full webhook message body and carries the shadow token. It is never read; only its presence is recorded.",
          "Delivery is proven by the receiver's own state endpoint, not by this probe.",
        ],
      };
      assertNoUrls(evidence);
      if (evidence.buildAlert) assertNoOpaqueTokens(evidence.buildAlert);
      assertNoOpaqueTokens(evidence.tradingView);
      const rendered = `${JSON.stringify(evidence, null, 2)}\n`;
      if (outPath) fs.writeFileSync(path.resolve(outPath), rendered, "utf-8");
      console.log(rendered);

      return evidence.buildAlert?.running === true
        && verdict.extraPrefixAlerts.length === 0
        && verdict.legacyChannelAlertsRemaining.length === 0
        ? 0
        : 1;
    }

    const verdict = classifyAlerts(rows, channels);

    const evidence = {
      schemaVersion: 1,
      requirementId: contract.requirementId,
      capturedAt: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
      verificationMode: "automated_readonly_readback",
      supersedes: {
        artifact: "artifacts/governance/smc_hold_manager_shadow_alerts_2026-07-28.json",
        claim:
          "no automated readback is recorded because TradingView alert state is not machine-verifiable from this repository",
        outcome: "refuted by execution on 2026-08-14",
      },
      tradingView: {
        account: contract.tradingView.account,
        layout: contract.tradingView.validationLayout,
        savedScript: contract.tradingView.savedScript,
        panelOpenedByProbe: clickedToOpen,
      },
      expectedChannels: channels,
      alerts: verdict.matched,
      missingChannels: verdict.missingChannels,
      notRunningChannels: verdict.notRunningChannels,
      foreignAlertCount: verdict.foreignAlertCount,
      limitations: [
        "Proves that an alert exists per channel, on which symbol and timeframe, and whether TradingView offers to stop it. Does NOT prove the webhook action is enabled: that lives in the per-alert edit dialog, a mutation surface on live alerts, which this probe refuses to open.",
        "The alert description field is the full webhook message body and carries the shadow token. It is never read; only its presence is recorded.",
        "Delivery is proven by the receiver's own state endpoint, not by this probe.",
      ],
    };

    // The page-derived subtree gets both checks; the probe's own prose gets
    // only the URL check. See assertNoOpaqueTokens for why that split exists.
    assertNoUrls(evidence);
    assertNoOpaqueTokens(evidence.alerts);
    assertNoOpaqueTokens(evidence.tradingView);
    const rendered = `${JSON.stringify(evidence, null, 2)}\n`;
    if (outPath) fs.writeFileSync(path.resolve(outPath), rendered, "utf-8");
    console.log(rendered);

    return verdict.missingChannels.length === 0 && verdict.notRunningChannels.length === 0
      ? 0
      : 1;
  } finally {
    await closeTradingViewSession(session);
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runReadbackCli()
    .then((rc) => process.exit(rc))
    .catch((error) => {
      console.error(JSON.stringify({ ok: false, error: String(error?.message ?? error) }));
      process.exit(1);
    });
}
