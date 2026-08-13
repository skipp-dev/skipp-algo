import fs from "node:fs";
import path from "node:path";

export type ConsumerPin = { file: string; version: number };

/** Every repo .pine that may import a hand-authored library. */
export function consumerPineFiles(repoRoot: string): string[] {
  const out: string[] = [];
  for (const dir of [repoRoot, path.join(repoRoot, "SMC++")]) {
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const e of entries) {
      if (e.isFile() && e.name.endsWith(".pine")) {
        out.push(path.join(dir, e.name));
      }
    }
  }
  return out;
}

/** Every consumer pin of `scriptName`, with the version each one names. */
export function consumerPins(repoRoot: string, scriptName: string): ConsumerPin[] {
  const re = new RegExp(`import\\s+[A-Za-z0-9_]+\\/${scriptName}\\/(\\d+)`, "g");
  const pins: ConsumerPin[] = [];
  for (const file of consumerPineFiles(repoRoot)) {
    // The library declares itself; it is not its own consumer.
    if (path.basename(file) === `${scriptName}.pine`) {
      continue;
    }
    const text = fs.readFileSync(file, "utf-8");
    for (const m of text.matchAll(re)) {
      pins.push({ file, version: Number(m[1]) });
    }
  }
  return pins;
}

/**
 * The version the repo declares for `scriptName`.
 *
 * Zero pins is a legal bootstrap (a newly introduced private library version
 * that nothing imports yet) and yields `null`. Disagreement is a repo
 * inconsistency and aborts before any TradingView write, because publishing
 * against a guess would pick a winner silently.
 */
export function deriveExpectedVersion(
  repoRoot: string,
  scriptName: string,
): { version: number | null; pins: ConsumerPin[] } {
  const pins = consumerPins(repoRoot, scriptName);
  const distinct = [...new Set(pins.map((p) => p.version))];
  if (distinct.length > 1) {
    const detail = pins
      .map((p) => `${path.relative(repoRoot, p.file)} pins /${p.version}`)
      .join(", ");
    throw new Error(
      `Consumer pins disagree for ${scriptName}: ${detail}. `
        + `Reconcile the repo before publishing.`,
    );
  }
  return { version: distinct.length === 1 ? distinct[0] : null, pins };
}

/**
 * Whether a publish counts as verified.
 *
 * The pre-existing facade override (#3603/#3606) set acceptance to true
 * whenever the facade answered, without looking at the direction of the
 * difference. That kept bumped libraries from exiting rc=1, but it also
 * accepted a version BELOW every consumer pin — which means the wrong script
 * was addressed, not that content changed. This states both halves explicitly.
 */
export function resolveVersionAcceptance(input: {
  expected: number | null;
  published: number | null;
  facadeAnswered: boolean;
}): { accepted: boolean; reason: string } {
  const { expected, published } = input;
  if (published === null) {
    return { accepted: false, reason: "published version not verified" };
  }
  if (expected === null) {
    return { accepted: true, reason: `bootstrap: no consumer pin, published /${published}` };
  }
  if (published < expected) {
    return {
      accepted: false,
      reason: `published /${published} is below the expected /${expected}`,
    };
  }
  if (published > expected) {
    return { accepted: true, reason: `publish advanced /${expected} to /${published}` };
  }
  return { accepted: true, reason: `published /${published} matches the consumer pin` };
}
