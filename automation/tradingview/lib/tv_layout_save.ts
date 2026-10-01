import type { Locator, Page } from "playwright";

/**
 * Persist the current chart layout — and count it as saved only when
 * TradingView ANSWERED the save, not when a header control changed its text.
 *
 * Why this file exists (measured, 2026-10-01). The previous implementation
 * looked for `button[data-qa-id="header-toolbar-save-load"]` and waited for
 * its aria-label to read "All changes saved". TradingView rebuilt the header
 * between 2026-08-23 (last confirmed save) and 2026-09-01: the id
 * `header-toolbar-save-load` moved to a wrapper <div>, the button became
 * `button[data-qa-id="save-load-button"]`, its label is constant and its
 * state lives in `aria-disabled`. From then on every repair rebound its
 * inputs, threw "save control not found" and lost the rebinds on the next
 * load — 467 run artefacts between 2026-09-01 and 2026-10-01 carry zero
 * `layoutSaved: true`, and the operator's chart sat on 108 `Close` bindings.
 *
 * Two copies of that code existed (lib/tv_shared.ts and
 * scripts/tv_onboard_consumers.ts, the customer onboarding package) and both
 * carried the same dead selector. This module is the single place now; both
 * callers wrap it.
 *
 * What is measured, and where (operator's chart vWgAWyfC on
 * de.tradingview.com, device emulation OFF, 2026-10-01):
 *   - the button selector and its `aria-disabled="true"` idle state;
 *   - Cmd/Ctrl+S on the chart -> `POST /api/v1/charts/save/` -> 200.
 * What is NOT measured: the button's state with unsaved changes, and whether
 * an account with autosave keeps it disabled for good. That is why
 * "disabled" is never read as "already saved, nothing to do" — see below.
 */

/** Newest first. The second entry is the header that carried until 2026-08-23. */
export const CHART_LAYOUT_SAVE_BUTTON_SELECTORS = [
  'button[data-qa-id="save-load-button"]',
  'button[data-qa-id="header-toolbar-save-load"]',
] as const;

export const CHART_LAYOUT_SAVE_REQUEST_PATH = "/api/v1/charts/save/";

/** Playwright resolves this to Meta on macOS and Control elsewhere. */
export const CHART_LAYOUT_SAVE_SHORTCUT = "ControlOrMeta+s";

export type ChartLayoutSaveFailure = "unconfirmed" | "rejected" | "unsafe-focus";

export class ChartLayoutSaveError extends Error {
  constructor(
    readonly failure: ChartLayoutSaveFailure,
    message: string,
  ) {
    super(message);
    this.name = "ChartLayoutSaveError";
  }
}

export interface ChartLayoutSaveOutcome {
  /** How the save was triggered. */
  trigger: "click" | "shortcut";
  /** Selector of the button that was found, or "none". */
  control: string;
  /** HTTP status TradingView answered the save request with. */
  status: number;
}

export function isChartLayoutSaveRequest(method: string, url: string): boolean {
  if (method.toUpperCase() !== "POST") return false;
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  const host = parsed.hostname.toLowerCase();
  if (host !== "tradingview.com" && !host.endsWith(".tradingview.com")) return false;
  return parsed.pathname === CHART_LAYOUT_SAVE_REQUEST_PATH;
}

interface SaveControl {
  selector: string;
  button: Locator;
  ariaDisabled: string | null;
  ariaLabel: string | null;
}

async function findSaveControl(page: Page): Promise<SaveControl | null> {
  for (const selector of CHART_LAYOUT_SAVE_BUTTON_SELECTORS) {
    const buttons = page.locator(selector);
    const count = await buttons.count().catch(() => 0);
    for (let index = 0; index < count; index += 1) {
      const button = buttons.nth(index);
      if (!(await button.isVisible().catch(() => false))) continue;
      return {
        selector,
        button,
        ariaDisabled: await button.getAttribute("aria-disabled").catch(() => null),
        ariaLabel: await button.getAttribute("aria-label").catch(() => null),
      };
    }
  }
  return null;
}

/** New header: `aria-disabled`. Header until 2026-08-23: the label itself. */
function controlReportsNothingToSave(control: SaveControl): boolean {
  return control.ariaDisabled === "true" || /all changes saved/i.test(control.ariaLabel ?? "");
}

function describeControl(control: SaveControl | null): string {
  if (!control) {
    return `no visible save button (tried ${CHART_LAYOUT_SAVE_BUTTON_SELECTORS.join(", ")})`;
  }
  return `${control.selector} aria-disabled=${control.ariaDisabled ?? "null"} aria-label=${JSON.stringify(control.ariaLabel)}`;
}

// Passed as a STRING: tsx/esbuild injects a `__name` helper into function
// arguments of page.evaluate that the page does not have.
const MOVE_FOCUS_OFF_EDITABLES = `(() => {
  var active = document.activeElement;
  if (active && active !== document.body && typeof active.blur === "function") active.blur();
  var now = document.activeElement;
  if (!now) return { tag: "BODY", editable: false, monaco: false };
  return {
    tag: now.tagName,
    editable: !!now.isContentEditable,
    monaco: !!(now.closest && now.closest(".monaco-editor")),
  };
})()`;

/**
 * Ctrl+S inside the Pine editor saves the SCRIPT, not the chart — a live
 * mutation of a saved source on the account. The shortcut is therefore only
 * pressed once focus is provably off every editable element; otherwise the
 * run stops.
 */
async function pressSaveShortcut(page: Page): Promise<void> {
  const focus = (await page.evaluate(MOVE_FOCUS_OFF_EDITABLES)) as {
    tag: string;
    editable: boolean;
    monaco: boolean;
  };
  const tag = String(focus?.tag ?? "").toUpperCase();
  if (focus?.monaco || focus?.editable || tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") {
    throw new ChartLayoutSaveError(
      "unsafe-focus",
      `refusing to press ${CHART_LAYOUT_SAVE_SHORTCUT}: focus stayed on an editable element `
        + `(${tag}${focus?.monaco ? ", Pine editor" : ""}) — there the shortcut saves the script, not the chart layout`,
    );
  }
  await page.keyboard.press(CHART_LAYOUT_SAVE_SHORTCUT);
}

// Passed as a STRING for the same reason as MOVE_FOCUS_OFF_EDITABLES.
const VISIBLE_DIALOG_HEADLINES = `(() => {
  var out = [];
  var nodes = document.querySelectorAll('[role="dialog"], #overlap-manager-root [data-id]');
  for (var i = 0; i < nodes.length && out.length < 4; i++) {
    var box = nodes[i].getBoundingClientRect();
    if (box.width === 0 || box.height === 0) continue;
    var text = (nodes[i].innerText || "").replace(/\\s+/g, " ").trim().slice(0, 60);
    if (text && out.indexOf(text) === -1) out.push(text);
  }
  return out;
})()`;

/**
 * What stood on the page when the save went unanswered. Run 36859274386
 * (2026-10-01) pressed the shortcut under a promotion overlay and with the
 * Pine editor docked; the message then named neither, and the question "who
 * took the key press?" needed a screenshot from a different step to answer.
 */
async function describeOpenDialogs(page: Page): Promise<string> {
  const found = await page.evaluate(VISIBLE_DIALOG_HEADLINES).catch(() => null);
  const headlines = Array.isArray(found) ? found.map((entry) => String(entry)) : [];
  return headlines.length > 0 ? `open dialogs: ${JSON.stringify(headlines)}` : "open dialogs: none seen";
}

export async function saveChartLayout(
  page: Page,
  options: { timeoutMs?: number } = {},
): Promise<ChartLayoutSaveOutcome> {
  const timeoutMs = options.timeoutMs ?? 20_000;
  const control = await findSaveControl(page);

  // Armed BEFORE the trigger and matched on the REQUEST, so only a save that
  // was issued after this point counts — an autosave already in flight was
  // serialised before the last rebind and proves nothing about it.
  const pending = page
    .waitForRequest((request) => isChartLayoutSaveRequest(request.method(), request.url()), { timeout: timeoutMs })
    .then(
      (request) => request,
      () => null,
    );

  let trigger: ChartLayoutSaveOutcome["trigger"];
  if (control && !controlReportsNothingToSave(control)) {
    await control.button.click();
    trigger = "click";
  } else {
    // No button, or a button that says there is nothing to save. Neither is
    // taken as "saved": the caller mutated the layout and asked for a save,
    // and a disabled button was exactly what the idle header showed while the
    // chart's bindings were unpersisted. Force the save and require the answer.
    await pressSaveShortcut(page);
    trigger = "shortcut";
  }

  const request = await pending;
  if (!request) {
    throw new ChartLayoutSaveError(
      "unconfirmed",
      `TradingView sent no POST ${CHART_LAYOUT_SAVE_REQUEST_PATH} within ${timeoutMs}ms after the ${trigger}; `
        + `save control: ${describeControl(control)}; ${await describeOpenDialogs(page)}`,
    );
  }
  const response = await request.response().catch(() => null);
  if (!response) {
    throw new ChartLayoutSaveError(
      "unconfirmed",
      `POST ${CHART_LAYOUT_SAVE_REQUEST_PATH} was sent after the ${trigger} but never answered; `
        + `save control: ${describeControl(control)}`,
    );
  }
  if (!response.ok()) {
    throw new ChartLayoutSaveError(
      "rejected",
      `TradingView answered POST ${CHART_LAYOUT_SAVE_REQUEST_PATH} with HTTP ${response.status()}; `
        + `save control: ${describeControl(control)}`,
    );
  }
  return { trigger, control: control?.selector ?? "none", status: response.status() };
}
