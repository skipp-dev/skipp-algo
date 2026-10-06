// Session-only overrides of SMC Long-Dip Suite inputs for the readout scripts.
//
// The readouts measure variants of the Suite (e.g. "Require Internal Break For
// Confirm" off) without saving anything: the override is applied through the
// chart API after the chart loaded and read back; the stored layout keeps its
// values (a later navigation reloads them).
//
// Inputs are addressed by their LABEL in the repository source. TradingView
// numbers a script's inputs in_0, in_1, ... in the order of the input() calls in
// the source; measured 2026-10-06 on vWgAWyfC (Suite v436): in_68 "Setup Expiry
// Bars" = 6, in_72 "Max Bars Armed -> Confirm" = 2, in_105 "Require Internal
// Break For Confirm" = true, in_109 "Structure Mode" = "Internal CHoCH only".
// The settings dialog is NOT used: its reader pairs two checkboxes on one line
// wrongly (same measurement).

import type { Page } from "playwright";

export type SuiteInputOverride = { label: string; raw: string };
export type AppliedOverride = { label: string; id: string; before: unknown; after: unknown };

/** "Label=value" -> override; the label may itself contain "=" only if escaped as "\=". */
export function parseSuiteInputOverride(spec: string): SuiteInputOverride {
  const m = spec.match(/^((?:[^=\\]|\\.)+)=(.*)$/);
  if (!m || !m[1].trim()) throw new Error(`--suite-input expects "Label=value", got: ${spec}`);
  return { label: m[1].replace(/\\=/g, "=").trim(), raw: m[2].trim() };
}

/** Every value of a repeated flag, e.g. --suite-input A=1 --suite-input B=2. */
export function getAllFlagValues(argv: string[], flag: string): string[] {
  const out: string[] = [];
  argv.forEach((a, i) => {
    if (a === flag) {
      if (i + 1 >= argv.length) throw new Error(`${flag} needs a value`);
      out.push(argv[i + 1]);
    }
  });
  return out;
}

/**
 * Map each input label of a Pine source to its TradingView input id (in_N, by
 * order of the input() calls; comments ignored). A label that occurs more than
 * once maps to several ids and is refused by resolveSuiteInputId.
 */
export function suiteInputIdsByLabel(source: string): Map<string, string[]> {
  const ids = new Map<string, string[]>();
  let n = 0;
  for (const line of source.split("\n")) {
    const code = line.split("//")[0];
    const calls = code.matchAll(/\binput(?:\.\w+)?\(/g);
    for (const call of calls) {
      const rest = code.slice(call.index ?? 0);
      const label = rest.match(/^input(?:\.\w+)?\([^,]*,\s*'([^']*)'/)?.[1] ?? rest.match(/^input(?:\.\w+)?\([^,]*,\s*"([^"]*)"/)?.[1];
      if (label !== undefined) ids.set(label, [...(ids.get(label) ?? []), `in_${n}`]);
      n += 1;
    }
  }
  return ids;
}

/** Number of input() calls in a Pine source (comments ignored). */
export function countSourceInputs(source: string): number {
  let n = 0;
  for (const line of source.split("\n")) n += [...line.split("//")[0].matchAll(/\binput(?:\.\w+)?\(/g)].length;
  return n;
}

export function resolveSuiteInputId(source: string, label: string): string {
  const ids = suiteInputIdsByLabel(source).get(label);
  if (!ids) throw new Error(`no Suite input labelled "${label}"`);
  if (ids.length !== 1) throw new Error(`Suite input label "${label}" is ambiguous (${ids.join(", ")})`);
  return ids[0];
}

/** Coerce the CLI text to the type of the value currently on the chart. */
export function coerceInputValue(raw: string, current: unknown): unknown {
  if (typeof current === "boolean") {
    if (raw !== "true" && raw !== "false") throw new Error(`expected true/false, got ${raw}`);
    return raw === "true";
  }
  if (typeof current === "number") {
    const v = Number(raw);
    if (!Number.isFinite(v)) throw new Error(`expected a number, got ${raw}`);
    return v;
  }
  return raw;
}

const READ_SOURCE = `
  const [name, ids] = arguments[0];
  const c = window.TradingViewApi.chart(0);
  const st = c.getAllStudies().filter((x) => x.name === name);
  if (st.length !== 1) return { error: name + " instances on chart 0: " + st.length };
  const values = c.getStudyById(st[0].id).getInputValues();
  const inCount = values.filter((x) => /^in_[0-9]+$/.test(x.id)).length;
  const out = {};
  for (const id of ids) { const hit = values.find((x) => x.id === id); out[id] = hit ? hit.value : undefined; }
  return { values: out, inCount };
`;

const WRITE_SOURCE = `
  const [name, writes] = arguments[0];
  const c = window.TradingViewApi.chart(0);
  const st = c.getAllStudies().filter((x) => x.name === name)[0];
  c.getStudyById(st.id).setInputValues(writes);
  return true;
`;

const SUITE_STATUS_SOURCE = `
  const name = arguments[0];
  const rows = Array.from(document.querySelectorAll('[data-qa-id="chart-container"]'))[0]?.querySelectorAll('[data-qa-id="legend-source-item"]') ?? [];
  for (const row of rows) if (row.innerText.startsWith(name)) return row.getAttribute("data-status");
  return "missing";
`;

const run = (page: Page, source: string, arg: unknown): Promise<unknown> =>
  page.evaluate(([src, a]) => new Function(src as string).call(null, a), [source, arg] as const);

/**
 * Apply overrides to the Suite on chart 0, read them back, then wait for the
 * Suite to finish recalculating. Throws if a value does not read back as set.
 */
export async function applySuiteInputOverrides(
  page: Page, suiteName: string, source: string, overrides: SuiteInputOverride[],
): Promise<AppliedOverride[]> {
  if (overrides.length === 0) return [];
  const ids = overrides.map((o) => resolveSuiteInputId(source, o.label));
  const before = (await run(page, READ_SOURCE, [suiteName, ids])) as { values?: Record<string, unknown>; inCount?: number; error?: string };
  if (before.error || !before.values) throw new Error(before.error ?? "could not read Suite inputs");
  // label -> in_N holds only for the version the repository holds
  if (before.inCount !== countSourceInputs(source)) {
    throw new Error(`Suite on chart has ${before.inCount} in_N inputs, repository source ${countSourceInputs(source)}: different version, refusing to map labels`);
  }
  const writes = overrides.map((o, i) => {
    const current = before.values![ids[i]];
    if (current === undefined) throw new Error(`Suite on chart has no ${ids[i]} ("${o.label}")`);
    return { id: ids[i], value: coerceInputValue(o.raw, current) };
  });
  await run(page, WRITE_SOURCE, [suiteName, writes]);
  // the loading edge may be too short to observe; settle on a stable non-loading state
  const deadline = Date.now() + 180_000;
  let stable = 0;
  await page.waitForTimeout(1_500);
  while (stable < 3) {
    const status = await run(page, SUITE_STATUS_SOURCE, suiteName);
    stable = status === "loading" ? 0 : stable + 1;
    if (Date.now() >= deadline) throw new Error("Suite still recalculating 180 s after the input override");
    await page.waitForTimeout(1_000);
  }
  const after = (await run(page, READ_SOURCE, [suiteName, ids])) as { values?: Record<string, unknown>; error?: string };
  if (after.error || !after.values) throw new Error(after.error ?? "could not read Suite inputs back");
  return overrides.map((o, i) => {
    const got = after.values![ids[i]];
    if (got !== writes[i].value) throw new Error(`"${o.label}" (${ids[i]}) reads ${String(got)} after setting ${String(writes[i].value)}`);
    return { label: o.label, id: ids[i], before: before.values![ids[i]], after: got };
  });
}
