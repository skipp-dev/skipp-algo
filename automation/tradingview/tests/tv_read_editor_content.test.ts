import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";

import {
  buildPineEditorModelPickerSource,
  pineDeclarationTitlePattern,
  visiblePineSourceTransitionVerified,
  waitForVisiblePineDeclarationIdentity,
} from "../lib/tv_shared.js";
import {
  SOURCE_READBACK_IDENTITY_MISMATCH_EVENT,
  judgePersistedConsumerSource,
  pineSourceSha256,
} from "../../../scripts/tv_save_consumer_source.js";

const SUITE_TITLE = "SMC Long-Dip Suite";
const SUITE_PATTERN = pineDeclarationTitlePattern(SUITE_TITLE).source;
const SUITE_SOURCE = `//@version=6\nindicator("${SUITE_TITLE}", overlay = true)\nplot(close)\n`;
const CONSOLE_BUFFER = "console-ish scratch buffer";
const MENTION_ONLY_SOURCE = `//@version=6\nindicator("SMC Decision Board")\ns = input.source(close, "${SUITE_TITLE}: BUS Armed")\n`;

test("saved-document repair requires a non-empty visible source transition", () => {
  const before = 'indicator("My script")';
  const after = 'indicator("SMC Long-Dip Alerts")';
  assert.equal(visiblePineSourceTransitionVerified(before, after), true);
  assert.equal(visiblePineSourceTransitionVerified(before, before), false);
  assert.equal(visiblePineSourceTransitionVerified(null, after), false);
  assert.equal(visiblePineSourceTransitionVerified(before, "   "), false);
});

type PickerResult = { value: string | null; reason: string };

function runPicker(
  patternSource: string,
  windowShim: Record<string, unknown>,
  requireVisibleEditor = false,
): PickerResult {
  const source = buildPineEditorModelPickerSource(patternSource, requireVisibleEditor);
  // Re-wrap the vm-realm object so assertions compare same-realm prototypes.
  const raw = vm.runInNewContext(source, { window: windowShim }) as PickerResult;
  return { value: raw.value, reason: raw.reason };
}

function monacoWithModels(values: string[], editors: unknown[] = []): Record<string, unknown> {
  return {
    editor: {
      getModels: () => values.map((value) => ({ getValue: () => value })),
      getEditors: () => editors,
    },
  };
}

test("picker source is transform-proof: plain JS, no bundler helpers, parses standalone", () => {
  const source = buildPineEditorModelPickerSource(SUITE_PATTERN);
  // tsx/esbuild keep-names injects a `__name` helper into function-form
  // evaluate callbacks that does not exist inside the page — every monaco read
  // threw `ReferenceError: __name is not defined` (run 29888669703). The
  // string form must stay free of any out-of-scope helper.
  assert.ok(!source.includes("__name"));
  assert.doesNotThrow(() => new vm.Script(source));
  const result = runPicker(SUITE_PATTERN, {});
  assert.deepEqual(result, { value: null, reason: "monaco-not-found" });
});

test("picker resolves the declaration-matching model, not an arbitrary buffer", () => {
  const result = runPicker(SUITE_PATTERN, {
    monaco: monacoWithModels([CONSOLE_BUFFER, SUITE_SOURCE]),
  });
  assert.equal(result.value, SUITE_SOURCE);
  assert.equal(result.reason, "model-declaration-match");
});

test("picker ignores title mentions in binding labels of other scripts", () => {
  const result = runPicker(SUITE_PATTERN, {
    monaco: monacoWithModels([MENTION_ONLY_SOURCE, SUITE_SOURCE]),
  });
  assert.equal(result.value, SUITE_SOURCE);
  assert.equal(result.reason, "model-declaration-match");
});

test("picker refuses ambiguous declaration matches instead of guessing", () => {
  const other = SUITE_SOURCE.replace("plot(close)", "plot(open)");
  const result = runPicker(SUITE_PATTERN, {
    monaco: monacoWithModels([SUITE_SOURCE, other]),
  });
  assert.equal(result.value, null);
  assert.match(result.reason, /^declaration-title-unresolved:editors=0:models=2/);
});

test("picker prefers a visible declaration-matching editor instance", () => {
  const visibleEditor = {
    getModel: () => ({ getValue: () => SUITE_SOURCE }),
    getDomNode: () => ({ isConnected: true, getBoundingClientRect: () => ({ width: 800, height: 600 }) }),
    hasTextFocus: () => true,
  };
  const result = runPicker(SUITE_PATTERN, {
    monaco: monacoWithModels([CONSOLE_BUFFER, SUITE_SOURCE], [visibleEditor]),
  });
  assert.equal(result.value, SUITE_SOURCE);
  assert.equal(result.reason, "editor-declaration-match");
});

test("write-authority picker rejects a hidden matching model behind the wrong visible editor", () => {
  const visibleAlerts = {
    getModel: () => ({ getValue: () => MENTION_ONLY_SOURCE }),
    getDomNode: () => ({ isConnected: true, getBoundingClientRect: () => ({ width: 800, height: 600 }) }),
    hasTextFocus: () => true,
  };
  const result = runPicker(
    SUITE_PATTERN,
    { monaco: monacoWithModels([MENTION_ONLY_SOURCE, SUITE_SOURCE], [visibleAlerts]) },
    true,
  );
  assert.equal(result.value, null);
  assert.match(result.reason, /^visible-editor-declaration-unresolved:editors=0:visibleEditors=1/);
});

test("write-authority picker accepts the declaration only in the visible editor", () => {
  const visibleSuite = {
    getModel: () => ({ getValue: () => SUITE_SOURCE }),
    getDomNode: () => ({ isConnected: true, getBoundingClientRect: () => ({ width: 800, height: 600 }) }),
    hasTextFocus: () => true,
  };
  const result = runPicker(
    SUITE_PATTERN,
    { monaco: monacoWithModels([CONSOLE_BUFFER, SUITE_SOURCE], [visibleSuite]) },
    true,
  );
  assert.equal(result.value, SUITE_SOURCE);
  assert.equal(result.reason, "editor-declaration-match");
});

test("webpack scan survives module namespaces with throwing getters", () => {
  // Webpack ESM namespace objects expose TDZ getters that throw on access
  // before module init; Object.values() triggers them. The scan must skip such
  // modules and still find monaco in a later module record.
  const poisoned: Record<string, unknown> = {};
  Object.defineProperty(poisoned, "boom", {
    enumerable: true,
    get() {
      throw new ReferenceError("Cannot access 'boom' before initialization");
    },
  });
  const moduleCache = {
    a: { exports: poisoned },
    b: { exports: { nested: monacoWithModels([SUITE_SOURCE]) } },
  };
  const result = runPicker(SUITE_PATTERN, {
    webpackChunktradingview: {
      push: (tuple: [unknown, unknown, (requireFn: { c: unknown }) => void]) => tuple[2]({ c: moduleCache }),
      pop: () => undefined,
    },
  });
  assert.equal(result.value, SUITE_SOURCE);
  assert.equal(result.reason, "model-declaration-match");
});

test("without a declaration title only an unambiguous single buffer is accepted", () => {
  const single = runPicker("", { monaco: monacoWithModels([SUITE_SOURCE]) });
  assert.equal(single.value, SUITE_SOURCE);
  assert.equal(single.reason, "single-model");
  const ambiguous = runPicker("", { monaco: monacoWithModels([SUITE_SOURCE, CONSOLE_BUFFER]) });
  assert.equal(ambiguous.value, null);
  assert.match(ambiguous.reason, /^ambiguous-models:/);
});

test("visible declaration wait rejects a UI-only switch and accepts the loaded editor model", async () => {
  let evaluations = 0;
  const page = {
    evaluate: async () => {
      evaluations += 1;
      return evaluations === 1
        ? { value: null, reason: "visible-editor-declaration-unresolved" }
        : { value: SUITE_SOURCE, reason: "editor-declaration-match" };
    },
    waitForTimeout: async () => undefined,
  };

  assert.equal(
    await waitForVisiblePineDeclarationIdentity(page as never, [SUITE_TITLE], 1_000),
    true,
  );
  assert.equal(evaluations, 2);
});

// ── Run 33031264859 (2026-08-27), cross-write readback blindness — pinned ───
//
// The rollout saved 12 consumers (10:59Z job, pin /364) and its source
// verification reported "SMC Long-Dip Mobile matches=true" — while the
// PERSISTED saved-script slot held the SMC Long-Dip Strategy source at that
// same pin (operator proof 2026-08-28: Pine-editor open AND a fresh add from
// the Indicators dialog; no other run saved sources in between — every later
// 27.8. run aborted verify-only on the 366/367 publish drift, the next queued
// run never started). The verify pass even ran AFTER a hard page reload
// (11:08:02Z), so the reload does not discard TradingView's per-script
// working buffers. The pair below is the behavioral red-proof: the OLD
// expectation-filtered picker accepts that state as a match, the NEW
// persisted-source judgement rejects it fail-closed.

const MOBILE_TITLE = "SMC Long-Dip Mobile";
const MOBILE_REPO_SOURCE = `//@version=6\nindicator("${MOBILE_TITLE}", overlay = true)\nplot(close)\n`;
const STRATEGY_PERSISTED_SOURCE =
  '//@version=6\nstrategy("SMC Long-Dip Strategy", overlay = true)\nstrategy.entry("L", strategy.long)\n';

test("RED-PROOF: the old expectation-filtered readback verifies the session's own buffer and cannot see the persisted cross-write", () => {
  // The page state of run 33031264859 during its verify pass: the single
  // visible editor serves the session's own staged Mobile buffer; the
  // saved-script store (holding the Strategy source in the Mobile slot) is
  // not reachable through any Monaco model. The old readback selected the
  // buffer BY the expected declaration pattern — "does any visible buffer
  // look like what I expect" — and its hash comparison then reported the
  // false matches=true against the repo file.
  const ownStagedBuffer = {
    getModel: () => ({ getValue: () => MOBILE_REPO_SOURCE }),
    getDomNode: () => ({ isConnected: true, getBoundingClientRect: () => ({ width: 800, height: 600 }) }),
    hasTextFocus: () => true,
  };
  const picked = runPicker(
    pineDeclarationTitlePattern(MOBILE_TITLE).source,
    { monaco: monacoWithModels([MOBILE_REPO_SOURCE], [ownStagedBuffer]) },
    true,
  );
  assert.equal(picked.reason, "editor-declaration-match");
  assert.equal(picked.value, MOBILE_REPO_SOURCE);
  // Exactly the old verify decision on that read: expected == actual.
  assert.equal(pineSourceSha256(picked.value ?? ""), pineSourceSha256(MOBILE_REPO_SOURCE));
});

test("the new persisted-source judgement rejects the same cross-write state fail-closed", () => {
  const target = { source: "SMC_Long_Dip_Mobile.pine", scriptName: MOBILE_TITLE };
  const judged = judgePersistedConsumerSource(
    target,
    STRATEGY_PERSISTED_SOURCE,
    pineSourceSha256(MOBILE_REPO_SOURCE),
  );
  assert.equal(judged.verdict, "identity-mismatch");
  assert.ok(judged.verdict === "identity-mismatch");
  assert.equal(judged.foundTitle, "SMC Long-Dip Strategy");
  // The traceDetail is the exact `<name>:<foundTitle>` payload of the
  // fail-closed trace event the readback emits.
  assert.equal(judged.traceDetail, `${MOBILE_TITLE}:SMC Long-Dip Strategy`);
  assert.equal(SOURCE_READBACK_IDENTITY_MISMATCH_EVENT, "source-readback-identity-mismatch");
});
