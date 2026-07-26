import assert from "node:assert/strict";
import test from "node:test";
import vm from "node:vm";

import { buildPineEditorModelPickerSource, pineDeclarationTitlePattern } from "../lib/tv_shared.js";

const SUITE_TITLE = "SMC Long-Dip Suite";
const SUITE_PATTERN = pineDeclarationTitlePattern(SUITE_TITLE).source;
const SUITE_SOURCE = `//@version=6\nindicator("${SUITE_TITLE}", overlay = true)\nplot(close)\n`;
const CONSOLE_BUFFER = "console-ish scratch buffer";
const MENTION_ONLY_SOURCE = `//@version=6\nindicator("SMC Long-Dip Dashboard")\ns = input.source(close, "${SUITE_TITLE}: BUS Armed")\n`;

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
