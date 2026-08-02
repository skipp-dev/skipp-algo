/**
 * Decide whether someone other than this run wrote to the managed layouts.
 *
 * Read BEFORE the first mutation, any difference from the last CI observation
 * is by construction not this run's doing -- that is the proof the pipeline
 * currently cannot produce. The baseline is the snapshot every run force-pushes
 * to `bot/live-tradingview-bindings`.
 *
 * The comparison key is the actual bound parent study id per label. Source
 * hashes stay out of it: `sources.drifted` already covers them on every run.
 *
 * Three verdicts, and the third is load-bearing. "unknown" means the comparison
 * could not be made -- a missing, unreadable or PARTIAL baseline, or a run that
 * did not read every target. It never rounds to "clean", and it never rounds to
 * "drifted" either: reporting drift that did not happen would train the
 * operator to ignore the signal.
 */

export type ObservedBinding = { label: string; actual: string | null };
export type ObservedConsumer = { scriptName: string; selections: ObservedBinding[] };

export type OutOfBandChange = {
  scriptName: string;
  label: string;
  baseline: string | null;
  observed: string | null;
};

export type OutOfBandVerdict = {
  status: "clean" | "drifted" | "unknown";
  reason: string;
  changed: OutOfBandChange[];
};

function selectionsByLabel(consumer: ObservedConsumer): Map<string, string | null> {
  return new Map(consumer.selections.map((selection) => [selection.label, selection.actual]));
}

function coverage(consumers: ObservedConsumer[], expected: string[]): string[] {
  const present = new Set(consumers.map((consumer) => consumer.scriptName));
  return expected.filter((name) => !present.has(name));
}

export function compareAgainstBaseline(args: {
  observed: ObservedConsumer[];
  baseline: ObservedConsumer[] | null;
  expectedScriptNames: string[];
}): OutOfBandVerdict {
  const { observed, baseline, expectedScriptNames } = args;

  if (baseline === null) {
    return {
      status: "unknown",
      reason: "no published baseline snapshot was available to compare against",
      changed: [],
    };
  }

  const missingFromBaseline = coverage(baseline, expectedScriptNames);
  if (missingFromBaseline.length > 0) {
    return {
      status: "unknown",
      reason: `the baseline does not cover every verify target (missing: ${missingFromBaseline.join(", ")})`,
      changed: [],
    };
  }

  const missingFromObserved = coverage(observed, expectedScriptNames);
  if (missingFromObserved.length > 0) {
    return {
      status: "unknown",
      reason: `this run did not read every verify target (missing: ${missingFromObserved.join(", ")})`,
      changed: [],
    };
  }

  const baselineByName = new Map(baseline.map((consumer) => [consumer.scriptName, selectionsByLabel(consumer)]));
  const observedByName = new Map(observed.map((consumer) => [consumer.scriptName, selectionsByLabel(consumer)]));
  const changed: OutOfBandChange[] = [];

  for (const scriptName of expectedScriptNames) {
    const before = baselineByName.get(scriptName)!;
    const after = observedByName.get(scriptName)!;
    for (const label of new Set([...before.keys(), ...after.keys()])) {
      // A label absent on one side reads as null: a binding that disappeared is
      // as much a foreign write as one that moved.
      const was = before.get(label) ?? null;
      const is = after.get(label) ?? null;
      if (was !== is) changed.push({ scriptName, label, baseline: was, observed: is });
    }
  }

  if (changed.length > 0) {
    return {
      status: "drifted",
      reason: `${changed.length} binding(s) changed since the last CI observation`,
      changed,
    };
  }

  return { status: "clean", reason: "every binding matches the last CI observation", changed: [] };
}
