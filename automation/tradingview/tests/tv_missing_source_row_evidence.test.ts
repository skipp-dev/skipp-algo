import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { formatMissingSourceRowEvidence } from "../../../scripts/tv_verify_consumer_bindings.js";

const _dir = path.dirname(fileURLToPath(import.meta.url));
const VERIFY = path.join(_dir, "..", "..", "..", "scripts", "tv_verify_consumer_bindings.ts");

// A bare "Source combobox not found for CTX SessionMssBull" cost three CI runs
// and two wrong diagnoses, because it is true under two opposite causes. The
// message has to name which one it observed.

const BASE = {
  label: "CTX SessionMssBull",
  renderedBefore: ["CTX SessionRangeBottom", "CTX OpeningRangeActive", "CTX SessionDirection"],
  renderedAfter: ["CTX SessionDirection", "CTX SessionMssBull", "CTX SessionMssBear"],
  appearedAfterScroll: true,
  dialogScrolled: true,
};

test("a row that appears after scrolling is reported as virtualized, not missing", () => {
  const message = formatMissingSourceRowEvidence(BASE);

  assert.match(message, /Source combobox not found for CTX SessionMssBull/);
  assert.match(message, /EXISTS and was only virtualized/);
  assert.doesNotMatch(message, /ABSENT/);
});

test("a row still missing at the end of the dialog is reported as absent", () => {
  const message = formatMissingSourceRowEvidence({
    ...BASE,
    renderedAfter: BASE.renderedBefore,
    appearedAfterScroll: false,
  });

  assert.match(message, /ABSENT from the applied instance/);
  assert.doesNotMatch(message, /virtualized out of the DOM/);
});

test("an unscrollable dialog claims neither cause", () => {
  // Without a scroll the probe has not tested anything, and saying "absent"
  // there would be the same unearned confidence that started this.
  const message = formatMissingSourceRowEvidence({
    ...BASE,
    appearedAfterScroll: false,
    dialogScrolled: false,
  });

  assert.match(message, /virtualization stays untested/);
  assert.doesNotMatch(message, /ABSENT/);
  assert.doesNotMatch(message, /EXISTS/);
});

test("the message carries the row counts and the last rows on both sides", () => {
  const message = formatMissingSourceRowEvidence(BASE);

  assert.match(message, /rendered rows 3 -> 3/);
  assert.match(message, /CTX SessionDirection/);
  assert.match(message, /CTX SessionMssBear/);
});

test("an empty dialog says so instead of printing nothing", () => {
  const message = formatMissingSourceRowEvidence({
    ...BASE,
    renderedBefore: [],
    renderedAfter: [],
    appearedAfterScroll: false,
  });

  assert.match(message, /rendered rows 0 -> 0/);
  assert.match(message, /last before none, last after none/);
});

test("the throw path actually uses it", () => {
  // Pinned after #4307, where deleting the call site left every helper test
  // green. A diagnostic nothing invokes reports nothing.
  const source = fs.readFileSync(VERIFY, "utf-8");

  assert.match(
    source,
    /throw new Error\(\s*await describeMissingSourceRow\(page, label\)/,
    "the 'combobox not found' throw must carry the probe's evidence",
  );
  assert.match(
    source,
    /describeMissingSourceRow\(page, label\)\.catch\(/,
    "a failing probe must not replace the failure with its own error",
  );
});
