import {
  closeTradingViewSession,
  ensurePineEditor,
  gotoChart,
  newTradingViewSession,
  openExistingScript,
} from "../automation/tradingview/lib/tv_shared.js";
import fs from "node:fs";
import path from "node:path";

const session = await newTradingViewSession();

try {
  const { page } = session;
  await gotoChart(page);
  await ensurePineEditor(page);
  await openExistingScript(page, "SMC Dashboard");
  await ensurePineEditor(page);

  const dashboardCode = fs.readFileSync(path.resolve("SMC_Dashboard.pine"), "utf-8");
  const textarea = page.locator("textarea.inputarea").first();
  await textarea.click({ force: true });

  const result = await page.evaluate(() => {
    const editorNodes = Array.from(
      document.querySelectorAll(".monaco-editor, [class*=\"monaco-editor\"], textarea"),
    );
    const globals = Object.keys(window)
      .filter((key) => /monaco|editor|pine/i.test(key))
      .slice(0, 100);

    const webpackRequire = (() => {
      const chunk = (window as Window & { webpackChunktradingview?: unknown[] }).webpackChunktradingview;
      if (!Array.isArray(chunk)) {
        return null;
      }

      let captured: unknown = null;
      chunk.push([[Symbol("tv-probe")], {}, (requireFn: unknown) => {
        captured = requireFn;
      }]);
      return captured as
        | {
            c?: Record<string, { exports?: unknown }>;
          }
        | null;
    })();

    const monacoModuleHits = Object.entries(webpackRequire?.c ?? {})
      .map(([id, mod]) => {
        const exports = (mod as { exports?: Record<string, unknown> }).exports;
        const directEditor = exports as { editor?: { getModels?: unknown } } | undefined;
        const defaultEditor = exports?.default as { editor?: { getModels?: unknown } } | undefined;
        const exportKeys = exports ? Object.keys(exports).slice(0, 20) : [];
        const nestedKeys = exports
          ? Object.entries(exports)
              .filter(([, value]) => !!value && typeof value === "object")
              .flatMap(([key, value]) =>
                Object.keys(value as Record<string, unknown>)
                  .filter((nestedKey) => /editor|model|monaco/i.test(nestedKey))
                  .map((nestedKey) => `${key}.${nestedKey}`),
              )
              .slice(0, 20)
          : [];

        const hasDirectMonaco = typeof directEditor?.editor?.getModels === "function";
        const hasDefaultMonaco = typeof defaultEditor?.editor?.getModels === "function";
        if (!hasDirectMonaco && !hasDefaultMonaco && nestedKeys.length === 0) {
          return null;
        }

        return {
          id,
          hasDirectMonaco,
          hasDefaultMonaco,
          exportKeys,
          nestedKeys,
        };
      })
      .filter(Boolean)
      .slice(0, 30);

    const details = editorNodes.slice(0, 8).map((node, index) => {
      const element = node as HTMLElement & Record<string, unknown>;
      return {
        index,
        tag: element.tagName,
        className: typeof element.className === "string" ? element.className : String(element.className ?? ""),
        role: element.getAttribute("role"),
        dataName: element.getAttribute("data-name"),
        ariaLabel: element.getAttribute("aria-label"),
        title: element.getAttribute("title"),
        ownKeys: Object.keys(element).filter((key) => /monaco|editor|model|view|react/i.test(key)).slice(0, 40),
        ownProps: Object.getOwnPropertyNames(element)
          .filter((key) => /monaco|editor|model|view|react/i.test(key))
          .slice(0, 40),
      };
    });

    return {
      url: location.href,
      monacoType: typeof (window as Window & { monaco?: unknown }).monaco,
      requireType: typeof (window as Window & { require?: unknown }).require,
      requirejsType: typeof (window as Window & { requirejs?: unknown }).requirejs,
      webpackKeys: Object.keys(window)
        .filter((key) => /webpack|chunk|require/i.test(key))
        .slice(0, 100),
      webpackModuleCount: Object.keys(webpackRequire?.c ?? {}).length,
      monacoModuleHits,
      monacoEnvironmentKeys: Object.keys(
        ((window as Window & { MonacoEnvironment?: Record<string, unknown> }).MonacoEnvironment ?? {}) as Record<
          string,
          unknown
        >,
      ),
      editorCount: editorNodes.length,
      globals,
      details,
    };
  });

  const directSmall = await textarea
    .evaluate((node) => {
      if (!(node instanceof HTMLTextAreaElement)) {
        return { wrote: false, reason: "not-textarea" };
      }

      node.value = "abc123";
      node.dispatchEvent(new Event("input", { bubbles: true }));
      node.dispatchEvent(new Event("change", { bubbles: true }));
      return { wrote: true, valueLength: node.value.length };
    })
    .catch((error: unknown) => ({ wrote: false, reason: String(error) }));

  const readbackSmall = await textarea.inputValue().catch((error: unknown) => `ERR:${String(error)}`);

  const directLarge = await textarea
    .evaluate((node, nextCode) => {
      if (!(node instanceof HTMLTextAreaElement)) {
        return { wrote: false, reason: "not-textarea" };
      }

      node.value = nextCode;
      node.dispatchEvent(new Event("input", { bubbles: true }));
      node.dispatchEvent(new Event("change", { bubbles: true }));
      return { wrote: true, valueLength: node.value.length };
    }, dashboardCode)
    .catch((error: unknown) => ({ wrote: false, reason: String(error) }));

  const readbackLarge = await textarea.inputValue().catch((error: unknown) => `ERR:${String(error)}`);

  const webpackMonacoWrite = await page
    .evaluate((nextCode) => {
      const chunk = (window as Window & { webpackChunktradingview?: unknown[] }).webpackChunktradingview;
      if (!Array.isArray(chunk)) {
        return { wrote: false, reason: "no-webpack-chunk" };
      }

      let captured: unknown = null;
      chunk.push([[Symbol("tv-probe-write")], {}, (requireFn: unknown) => {
        captured = requireFn;
      }]);

      const requireFn = captured as { c?: Record<string, { exports?: unknown }> } | null;
      const monacoExport = Object.values(requireFn?.c ?? {})
        .map((mod) => (mod.exports ?? null) as { editor?: { getModels?: () => Array<{ setValue: (value: string) => void; getValue: () => string }> } } | null)
        .find((exports) => typeof exports?.editor?.getModels === "function");

      const models = monacoExport?.editor?.getModels?.() ?? [];
      if (models.length === 0) {
        return { wrote: false, reason: "no-models" };
      }

      models[0].setValue(nextCode);
      return {
        wrote: true,
        modelCount: models.length,
        modelLength: models[0].getValue().length,
        preview: models[0].getValue().slice(0, 80),
      };
    }, dashboardCode)
    .catch((error: unknown) => ({ wrote: false, reason: String(error) }));

  console.log(
    JSON.stringify(
      {
        runtime: result,
        directSmall,
        readbackSmall,
        directLarge,
        readbackLargeLength: typeof readbackLarge === "string" ? readbackLarge.length : null,
        readbackLargePreview:
          typeof readbackLarge === "string" ? readbackLarge.slice(0, 120) : String(readbackLarge),
        webpackMonacoWrite,
      },
      null,
      2,
    ),
  );
} finally {
  await closeTradingViewSession(session);
}
