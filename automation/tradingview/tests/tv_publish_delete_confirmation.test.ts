import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const _dir = path.dirname(fileURLToPath(import.meta.url));
const SHARED = path.join(_dir, "..", "lib", "tv_shared.ts");

// 2026-08-17: TradingView replaced the publish-dismissal confirmation.
// The old dialog matched /cancel publication/i and confirmed with "Yes";
// the new one is titled "Delete this publication?" with buttons
// Cancel / Delete (screenshot evidence in run 32040147080 artifacts).
// Seven consecutive smc-library-publish runs hung on the unanswered
// modal: every surface-close click timed out behind it, the identity
// evidence collapsed on the covered page, and the refresh treadmill
// re-published the library 255 -> 262 with nothing verified.
//
// These are source-structure pins. The DOM behavior itself is
// Playwright-against-TradingView and is proven by the next CI publish
// run -- that limit is stated here so nobody reads these tests as more.

const source = () => fs.readFileSync(SHARED, "utf-8");

test("the publish-dismissal confirmation knows both dialog variants", () => {
  const confirmation = source().match(
    /async function dismissPublishCancelConfirmation[\s\S]*?\n\}/,
  )?.[0] ?? "";
  // Pinned on the findVisibleDialogByText CALL, not on the phrase: the
  // function's own comment tells the incident story and contains both
  // phrases, so a phrase-wide pin stayed green with the lookup deleted
  // (caught by this fix's own mutation probe).
  assert.match(
    confirmation,
    /findVisibleDialogByText\(page, \/cancel publication\/i/,
    "the legacy Cancel-publication lookup must stay handled (TV A/B)",
  );
  assert.match(
    confirmation,
    /findVisibleDialogByText\(page, \/delete this publication\/i/,
    "the 2026-08-17 Delete-this-publication lookup must exist -- an " +
      "unmatched confirmation is exactly the seven-run outage this pins",
  );
});

test("the delete variant confirms strictly inside the matched dialog", () => {
  const confirmation = source().match(
    /async function dismissPublishCancelConfirmation[\s\S]*?\n\}/,
  )?.[0] ?? "";
  // The affirmative locator must hang off the found dialog handle, never
  // page-wide: a page-wide /delete/i click is a loaded gun on a platform
  // that also renders "Delete" in script-management menus.
  assert.match(
    confirmation,
    /dialog\.getByRole\("button", \{ name: \/\^delete\$\/i \}\)/,
    "the Delete click must be scoped to the matched confirmation dialog",
  );
  assert.doesNotMatch(
    confirmation,
    /page\.getByRole\("button", \{ name: \/\^delete\$\/i \}\)/,
    "a page-wide Delete locator must never appear here",
  );
});

test("the close loop answers the confirmation the close click just spawned", () => {
  const loop = source().match(
    /async function dismissPublishSurfaceAfterNoChange[\s\S]*?\n\}/,
  )?.[0] ?? "";
  const closeClick = loop.indexOf("publish-no-change-surface-close-");
  const confirmBeforeEscape = loop.indexOf("dismissPublishCancelConfirmation");
  const escape = loop.indexOf('press("Escape")');
  assert.ok(closeClick > 0 && confirmBeforeEscape > 0 && escape > 0, "loop anatomy changed -- re-anchor this pin");
  assert.ok(
    closeClick < confirmBeforeEscape && confirmBeforeEscape < escape,
    "the confirmation must be answered right after the close click and " +
      "BEFORE Escape -- Escape can cancel the confirm modal and hand the " +
      "stuck surface straight back (the 2026-08-17 loop shape)",
  );
});
