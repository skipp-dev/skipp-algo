import assert from "node:assert/strict";
import test from "node:test";

import { clipboardReadbackProvesWrite } from "../lib/tv_validation_model.js";

// The clipboard write strategy verified itself against the value it had just
// put on the clipboard: write `code` -> paste -> select-all -> copy -> read,
// then compare the read against `code`. A copy that never lands leaves the
// original write on the clipboard, so the comparison succeeds while the editor
// is untouched — and the publisher then saves and publishes the OLD source,
// with the compile check blind because the old source compiles.
//
// The read path in the same module already seeds a marker for exactly this
// reason ("so a copy that never lands cannot masquerade as source"). These pin
// that guard for the write path.
//
// Unit-level by necessity: setEditorContent drives a real TradingView editor
// (ensurePineEditor), so the end-to-end path cannot be faked honestly. The
// evidence that the bug is real is the code reading back its own write plus the
// reader-side comment, not a synthetic browser fixture.

const norm = (value: string): string => value.replace(/\r\n/g, "\n");
const MARKER = "tv-editor-write-probe-4711";
const CODE = "//@version=6\nindicator('X')\nplot(close)\n";

test("a readback still holding the seeded marker is not proof", () => {
  // The copy was a no-op. Before the fix this case could not even arise,
  // because nothing was seeded and the clipboard simply still held CODE.
  assert.equal(
    clipboardReadbackProvesWrite({ expected: CODE, seededMarker: MARKER, readback: MARKER, normalize: norm }),
    false,
  );
});

test("a readback of the expected text is proof", () => {
  assert.equal(
    clipboardReadbackProvesWrite({ expected: CODE, seededMarker: MARKER, readback: CODE, normalize: norm }),
    true,
  );
});

test("CRLF normalisation still matches", () => {
  assert.equal(
    clipboardReadbackProvesWrite({
      expected: CODE,
      seededMarker: MARKER,
      readback: CODE.replace(/\n/g, "\r\n"),
      normalize: norm,
    }),
    true,
  );
});

test("an empty readback is not proof", () => {
  // clipboard.readText() rejecting is mapped to "" by the caller; that is a
  // failed look, not an empty editor.
  assert.equal(
    clipboardReadbackProvesWrite({ expected: CODE, seededMarker: MARKER, readback: "", normalize: norm }),
    false,
  );
});

test("a truncated grab is not proof", () => {
  assert.equal(
    clipboardReadbackProvesWrite({
      expected: CODE,
      seededMarker: MARKER,
      readback: CODE.slice(0, 12),
      normalize: norm,
    }),
    false,
  );
});

test("the head/tail tolerance needs equal length, and accepts a large document", () => {
  const big = `${"a".repeat(500)}MIDDLE${"b".repeat(500)}`;
  const sameEndsSameLength = `${"a".repeat(500)}middle${"b".repeat(500)}`;
  const sameEndsShorter = `${"a".repeat(500)}${"b".repeat(500)}`;

  assert.equal(
    clipboardReadbackProvesWrite({ expected: big, seededMarker: MARKER, readback: sameEndsSameLength, normalize: norm }),
    true,
    "equal length plus identical 200-char head and tail is the documented tolerance",
  );
  assert.equal(
    clipboardReadbackProvesWrite({ expected: big, seededMarker: MARKER, readback: sameEndsShorter, normalize: norm }),
    false,
    "a different length must not pass on matching ends alone",
  );
});

test("an unseeded marker fails closed", () => {
  // If seeding the clipboard failed, there is no way to tell a stale readback
  // from a real one — so nothing is proof.
  assert.equal(
    clipboardReadbackProvesWrite({ expected: CODE, seededMarker: "", readback: CODE, normalize: norm }),
    false,
  );
});
