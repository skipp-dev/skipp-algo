import assert from "node:assert/strict";
import test from "node:test";

import {
  revealEmailLoginField,
  TV_LOGIN_IDENTIFIER_SELECTOR,
} from "../lib/tv_shared.js";

// 2026-07-28: the headless-login fallback in
// `scripts/create_tradingview_storage_state.ts` had never once recovered a dead
// cookie. It waited up to 10 s for the e-mail/username input and only clicked an
// "Email" button afterwards — but TradingView does not render that input until
// the chooser is clicked. Probed live against the real sign-in page:
//
//   matched username/email inputs: 0 | first visible: false
//   visible button labels: ["Show more options", "Email"]
//   after clicking Email -> input visible: true
//
// So the wait always expired, the helper fell through to the interactive branch,
// and on a runner that can only time out after 180 s (run 30338176548). What has
// to hold is the ORDER: reveal, then fill. These pins are browserless on purpose
// so they run in tv-onboarding-packages.yml, which installs no Playwright
// browser — a browser-launching pin there would be exempt and gate nothing,
// which is exactly how this bug survived.

type StubElement = {
  isVisible: () => Promise<boolean>;
  click: (options?: { timeout?: number }) => Promise<void>;
  waitFor: (options?: { state?: string; timeout?: number }) => Promise<void>;
};

/** Minimal Playwright-`Page` shape: visibility per selector + click effects. */
function stubPage(options: {
  visible: Set<string>;
  onClick?: Record<string, () => void>;
  calls: string[];
}) {
  const { visible, onClick = {}, calls } = options;
  const key = (selector: string): string => {
    if (selector === TV_LOGIN_IDENTIFIER_SELECTOR) return "identifier";
    if (selector.includes('has-text("Email")')) return "email-chooser";
    if (selector.includes("more options") || selector.includes("More options")) {
      return "more-options";
    }
    return selector;
  };

  return {
    locator(selector: string) {
      const name = key(selector);
      const element: StubElement = {
        async isVisible() {
          calls.push(`isVisible:${name}`);
          return visible.has(name);
        },
        async click() {
          calls.push(`click:${name}`);
          onClick[name]?.();
        },
        async waitFor() {
          calls.push(`waitFor:${name}`);
          if (!visible.has(name)) {
            throw new Error(`Timeout: ${name} never became visible`);
          }
        },
      };
      return { first: () => element };
    },
  };
}

test("clicks the Email chooser before waiting for the identifier field", async () => {
  const visible = new Set(["email-chooser"]);
  const calls: string[] = [];
  const page = stubPage({
    visible,
    onClick: { "email-chooser": () => visible.add("identifier") },
    calls,
  });

  assert.equal(await revealEmailLoginField(page as never), true);

  const clickIndex = calls.indexOf("click:email-chooser");
  const waitIndex = calls.indexOf("waitFor:identifier");
  assert.ok(clickIndex >= 0, `chooser was never clicked: ${calls.join(" -> ")}`);
  assert.ok(waitIndex > clickIndex, `waited before revealing: ${calls.join(" -> ")}`);
});

test("does not touch the chooser when the identifier field is already visible", async () => {
  const calls: string[] = [];
  const page = stubPage({ visible: new Set(["identifier"]), calls });

  assert.equal(await revealEmailLoginField(page as never), true);
  assert.deepEqual(calls, ["isVisible:identifier"]);
});

test("falls back to Show more options when the chooser is hidden behind it", async () => {
  const visible = new Set(["more-options"]);
  const calls: string[] = [];
  const page = stubPage({
    visible,
    onClick: {
      "more-options": () => visible.add("email-chooser"),
      "email-chooser": () => visible.add("identifier"),
    },
    calls,
  });

  assert.equal(await revealEmailLoginField(page as never), true);
  assert.ok(calls.includes("click:more-options"));
  assert.ok(calls.includes("click:email-chooser"));
});

test("reports failure instead of hanging on a social-only sign-in page", async () => {
  const calls: string[] = [];
  const page = stubPage({ visible: new Set(), calls });

  assert.equal(await revealEmailLoginField(page as never), false);
  assert.ok(
    calls.length > 0,
    "the helper probed nothing at all — the absence pin below would pass vacuously",
  );
  assert.ok(
    !calls.some((call) => call.startsWith("click:")),
    `nothing clickable existed, yet a click was attempted: ${calls.join(" -> ")}`,
  );
});
