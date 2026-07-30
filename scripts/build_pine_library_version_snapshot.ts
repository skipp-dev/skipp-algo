#!/usr/bin/env -S node --enable-source-maps
/**
 * Repo↔TradingView Pine-library version snapshot builder.
 *
 * Why this exists: until the 2026-07-13 incident chain (#3599/#3603) there was
 * NO periodic check that the `import preuss_steffen/<lib>/<N>` pins in the repo
 * still matched the real published version on TradingView. The generated
 * micro_profiles lib drifted `/1` (2026-03) vs a live `/152` for ~4 months and
 * nothing alerted — CE10272 on every modern `mp.*` symbol. The 8 hand-authored
 * `SMC++/` libraries (imported by SMC_Core_Engine at `/1`) still have zero
 * drift detection.
 *
 * This builder is the PRODUCER half of the monitoring layer (mirrors
 * `scripts/build_evidence_freshness_snapshot.py`). It:
 *   1. discovers every repo-owned `library("<name>")` declaration and every
 *      `import preuss_steffen/<lib>/<N>` pin in the repo's `.pine` files
 *      (root consumers + inter-library imports),
 *   2. probes each distinct library's REAL published version via the
 *      pine-facade `filter=published` listing
 *      (`fetchPublishedLibraryVersionViaFacade` — the #3603-corrected source;
 *      `filter=saved` counts editor save revisions, not the importable
 *      version), and
 *   3. reads ASOF_DATE from repo-owned generated library sources, and
 *   4. writes a compact snapshot the live-overlay daemon's
 *      `pine_library_version_bridge` turns into Prometheus gauges +
 *      repo↔TV drift alerts in Grafana.
 *
 * `--dry-run` skips the TradingView session entirely (tvVersion=null for every
 * library) so the snapshot shape can be produced and schema-checked offline.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// NOTE: `tv_shared` (Playwright, the TradingView session) is imported
// DYNAMICALLY inside the live-probe branch only — so the pure parse/build
// functions, `--dry-run`, and the unit tests load without Playwright installed.

/** Minimal JSON writer (avoids a static tv_shared import for the pure path). */
function writeJsonFile(filePath: string, payload: unknown): void {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(payload, null, 2)}\n`, "utf-8");
}

/** One `import preuss_steffen/<library>/<pinnedVersion>` site in a `.pine` file. */
export type ConsumerPin = {
  file: string;
  library: string;
  pinnedVersion: number;
};

export type ConsumerEntry = {
  file: string;
  pinnedVersion: number;
  drift: boolean;
};

export type LibrarySnapshot = {
  name: string;
  tvVersion: number | null;
  tvVersionKnown: boolean;
  dataAsOf: string;
  dataAsOfUnix: number | null;
  dataAsOfKnown: boolean;
  consumers: ConsumerEntry[];
  anyConsumerDrift: boolean;
  payloadKnown: boolean;
  payloadUniverseSize: number | null;
  payloadUniverseSymbols: number;
  payloadListSymbols: number;
};

export type PineLibraryVersionSnapshot = {
  generatedAt: string;
  generated_at_unix: number;
  libraries: LibrarySnapshot[];
  anyDrift: boolean;
  librariesProbed: number;
  librariesDrifted: number;
  facadeError: string;
};

const OWNER_PREFIX = "preuss_steffen";
const PIN_RE = new RegExp(`import\\s+${OWNER_PREFIX}\\/([A-Za-z0-9_]+)\\/(\\d+)`, "g");
const LIBRARY_DECL_RE = /^\s*library\(\s*"([A-Za-z0-9_]+)"/m;
const ASOF_DATE_RE = /export\s+const\s+string\s+ASOF_DATE\s*=\s*"(\d{4}-\d{2}-\d{2})"/;

/** Directories that hold fixtures / generated snapshots / vendored code — never live consumer pins. */
const EXCLUDED_DIR_NAMES = new Set(["tests", "pine", "node_modules", ".git", ".claude"]);

/**
 * Extract every `import preuss_steffen/<lib>/<N>` pin from one `.pine` source.
 * Pure — no filesystem access — so the parse is unit-testable in isolation.
 */
export function parseImportPins(pineText: string, file: string): ConsumerPin[] {
  const pins: ConsumerPin[] = [];
  for (const match of pineText.matchAll(PIN_RE)) {
    const library = match[1];
    const pinnedVersion = Number.parseInt(match[2], 10);
    if (Number.isFinite(pinnedVersion)) {
      pins.push({ file, library, pinnedVersion });
    }
  }
  return pins;
}

/** Extract a repo-owned Pine library declaration, if this source has one. */
export function parseLibraryDeclaration(pineText: string): string | null {
  return LIBRARY_DECL_RE.exec(pineText)?.[1] ?? null;
}

/** Recursively collect `.pine` files under `root`, skipping excluded directories. */
function collectPineFiles(root: string): string[] {
  const out: string[] = [];
  const walk = (dir: string): void => {
    let entries: fs.Dirent[];
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (!EXCLUDED_DIR_NAMES.has(entry.name)) {
          walk(full);
        }
      } else if (entry.isFile() && entry.name.endsWith(".pine")) {
        out.push(full);
      }
    }
  };
  walk(root);
  return out;
}

/**
 * Discover all repo-owned libraries and consumer pins, grouped by library
 * name. Declared libraries are seeded even when they have zero consumers so a
 * bootstrap library cannot disappear from version monitoring. Paths are
 * repo-relative so the snapshot is host-independent.
 */
export function discoverConsumerPins(root: string): Map<string, ConsumerPin[]> {
  const byLibrary = new Map<string, ConsumerPin[]>();
  for (const absFile of collectPineFiles(root)) {
    const rel = path.relative(root, absFile);
    const text = fs.readFileSync(absFile, "utf-8");
    const declaredLibrary = parseLibraryDeclaration(text);
    if (declaredLibrary && !byLibrary.has(declaredLibrary)) {
      byLibrary.set(declaredLibrary, []);
    }
    for (const pin of parseImportPins(text, rel)) {
      const list = byLibrary.get(pin.library) ?? [];
      list.push(pin);
      byLibrary.set(pin.library, list);
    }
  }
  return byLibrary;
}

/**
 * How much payload a generated library actually carries (ADR-0029).
 *
 * `known=false` means the exports were not found at all — distinct from a
 * measured zero. Hand-authored libraries have no payload exports, and an
 * unreadable file must read neither as empty nor as green.
 */
export type LibraryPayloadVolume = {
  known: boolean;
  universeSize: number | null;
  universeSymbols: number;
  listSymbols: number;
};

/** Mirrors ``smc_payload_volume.MEMBERSHIP_LIST_EXPORTS`` (pinned by a Python test). */
const MEMBERSHIP_LIST_EXPORTS = [
  "CLEAN_RECLAIM_TICKERS",
  "STOP_HUNT_PRONE_TICKERS",
  "MIDDAY_DEAD_TICKERS",
  "RTH_ONLY_TICKERS",
  "WEAK_PREMARKET_TICKERS",
  "WEAK_AFTERHOURS_TICKERS",
  "FAST_DECAY_TICKERS",
] as const;

const UNIVERSE_SIZE_RE = /export\s+const\s+int\s+UNIVERSE_SIZE\s*=\s*(\d+)/;

function countCsvExportSymbols(pineText: string, exportName: string): number | null {
  const literal = new RegExp(
    `export\\s+const\\s+string\\s+(?<![A-Za-z0-9_])${exportName}(?![A-Za-z0-9_])\\s*=\\s*"([^"]*)"`,
  ).exec(pineText);
  if (literal) {
    return literal[1].split(",").filter((part) => part.length > 0).length;
  }

  // Sharded form. `render_csv_export` splits at max_chars (3900 for
  // UNIVERSE_TICKERS), so a healthy 6929-symbol payload is a concatenation
  // expression and carries NO literal on the export line. Scoring that as 0
  // would invert every rule built on this metric.
  const shardRe = new RegExp(`const\\s+string\\s+${exportName}_PART_\\d+\\s*=\\s*"([^"]*)"`, "g");
  let total = 0;
  let sawShard = false;
  for (const match of pineText.matchAll(shardRe)) {
    sawShard = true;
    total += match[1].split(",").filter((part) => part.length > 0).length;
  }
  return sawShard ? total : null;
}

/** Measure a generated Pine library's payload volume. */
export function parseLibraryPayloadVolume(pineText: string): LibraryPayloadVolume {
  const sizeMatch = UNIVERSE_SIZE_RE.exec(pineText);
  const universeSize = sizeMatch ? Number.parseInt(sizeMatch[1], 10) : null;
  const universeSymbols = countCsvExportSymbols(pineText, "UNIVERSE_TICKERS");

  let listSymbols = 0;
  for (const exportName of MEMBERSHIP_LIST_EXPORTS) {
    listSymbols += countCsvExportSymbols(pineText, exportName) ?? 0;
  }

  return {
    known: universeSize !== null && universeSymbols !== null,
    universeSize,
    universeSymbols: universeSymbols ?? 0,
    listSymbols,
  };
}

/** Resolve payload volume for generated libraries whose source is part of this repo. */
export function discoverLibraryPayloadVolume(
  root: string,
  libraryNames: string[],
): Map<string, LibraryPayloadVolume> {
  const result = new Map<string, LibraryPayloadVolume>();
  for (const name of libraryNames) {
    const source = path.join(root, "pine", "generated", `${name}.pine`);
    try {
      result.set(name, parseLibraryPayloadVolume(fs.readFileSync(source, "utf-8")));
    } catch {
      result.set(name, { known: false, universeSize: null, universeSymbols: 0, listSymbols: 0 });
    }
  }
  return result;
}

/** Parse a generated Pine library's exported data watermark. */
export function parseLibraryDataAsOf(pineText: string): string | null {
  const value = ASOF_DATE_RE.exec(pineText)?.[1] ?? "";
  if (!value) return null;
  const parsed = Date.parse(`${value}T00:00:00Z`);
  if (!Number.isFinite(parsed) || new Date(parsed).toISOString().slice(0, 10) !== value) return null;
  return value;
}

/** Resolve ASOF_DATE for generated libraries whose source is part of this repo. */
export function discoverLibraryDataAsOf(root: string, libraryNames: string[]): Map<string, string | null> {
  const result = new Map<string, string | null>();
  for (const name of libraryNames) {
    const source = path.join(root, "pine", "generated", `${name}.pine`);
    try {
      result.set(name, parseLibraryDataAsOf(fs.readFileSync(source, "utf-8")));
    } catch {
      result.set(name, null);
    }
  }
  return result;
}

/**
 * Assemble the snapshot from discovered pins + probed TV versions. Pure so the
 * drift logic is unit-testable without a TradingView session. `tvVersions`
 * maps library → published version (or `null` when the probe failed / the
 * library is unpublished).
 */
export function buildSnapshot(
  pinsByLibrary: Map<string, ConsumerPin[]>,
  tvVersions: Map<string, number | null>,
  nowUnix: number,
  facadeError = "",
  dataAsOfByLibrary: Map<string, string | null> = new Map(),
  payloadByLibrary: Map<string, LibraryPayloadVolume> = new Map(),
): PineLibraryVersionSnapshot {
  const libraries: LibrarySnapshot[] = [];
  for (const name of [...pinsByLibrary.keys()].sort()) {
    const tvVersion = tvVersions.get(name) ?? null;
    const tvVersionKnown = typeof tvVersion === "number";
    const dataAsOf = dataAsOfByLibrary.get(name) ?? "";
    const parsedDataAsOf = dataAsOf ? Date.parse(`${dataAsOf}T00:00:00Z`) : Number.NaN;
    const dataAsOfUnix = Number.isFinite(parsedDataAsOf) ? Math.floor(parsedDataAsOf / 1000) : null;
    const pins = pinsByLibrary.get(name) ?? [];
    const consumers: ConsumerEntry[] = pins
      .slice()
      .sort((a, b) => a.file.localeCompare(b.file))
      .map((pin) => ({
        file: pin.file,
        pinnedVersion: pin.pinnedVersion,
        // Drift is only asserted when the real version is KNOWN — an
        // unreachable facade must not masquerade as "in sync" OR as drift.
        drift: tvVersionKnown && pin.pinnedVersion !== tvVersion,
      }));
    const anyConsumerDrift = consumers.some((c) => c.drift);
    const payload = payloadByLibrary.get(name) ?? {
      known: false,
      universeSize: null,
      universeSymbols: 0,
      listSymbols: 0,
    };
    libraries.push({
      name,
      tvVersion,
      tvVersionKnown,
      dataAsOf,
      dataAsOfUnix,
      dataAsOfKnown: dataAsOfUnix !== null,
      consumers,
      anyConsumerDrift,
      payloadKnown: payload.known,
      payloadUniverseSize: payload.universeSize,
      payloadUniverseSymbols: payload.universeSymbols,
      payloadListSymbols: payload.listSymbols,
    });
  }

  const librariesDrifted = libraries.filter((l) => l.anyConsumerDrift).length;
  return {
    generatedAt: new Date(nowUnix * 1000).toISOString(),
    generated_at_unix: nowUnix,
    libraries,
    anyDrift: librariesDrifted > 0,
    librariesProbed: libraries.filter((l) => l.tvVersionKnown).length,
    librariesDrifted,
    facadeError,
  };
}

type CliArgs = {
  root: string;
  out: string;
  dryRun: boolean;
};

function parseArgs(argv: string[]): CliArgs {
  const args = argv.slice(2);
  const getFlag = (name: string, fallback: string): string => {
    const i = args.indexOf(name);
    return i === -1 || !args[i + 1] ? fallback : args[i + 1];
  };
  const root = path.resolve(getFlag("--root", process.cwd()));
  return {
    root,
    out: path.resolve(getFlag("--out", path.join(root, "artifacts", "monitoring", "pine_library_versions.json"))),
    dryRun: args.includes("--dry-run"),
  };
}

export async function runBuildPineLibraryVersionSnapshotCli(argv: string[] = process.argv): Promise<number> {
  const cli = parseArgs(argv);
  const nowUnix = Math.floor(Date.now() / 1000);

  const pinsByLibrary = discoverConsumerPins(cli.root);
  const libraryNames = [...pinsByLibrary.keys()].sort();
  const dataAsOfByLibrary = discoverLibraryDataAsOf(cli.root, libraryNames);
  const payloadByLibrary = discoverLibraryPayloadVolume(cli.root, libraryNames);

  const tvVersions = new Map<string, number | null>();
  let facadeError = "";

  if (cli.dryRun) {
    for (const name of libraryNames) {
      tvVersions.set(name, null);
    }
  } else {
    const {
      newTradingViewSession,
      closeTradingViewSession,
      gotoChart,
      fetchPublishedLibraryVersionViaFacade,
    } = await import("../automation/tradingview/lib/tv_shared.js");
    let session: Awaited<ReturnType<typeof newTradingViewSession>> | null = null;
    try {
      session = await newTradingViewSession();
      if (!session.authResolution.authReusedOk) {
        throw new Error(
          "Pine-library version snapshot requires a reusable authenticated session. Refresh TV_STORAGE_STATE or TV_PERSISTENT_PROFILE_DIR first.",
        );
      }
      await gotoChart(session.page);
      for (const name of libraryNames) {
        const version = await fetchPublishedLibraryVersionViaFacade(session.page, name).catch(() => null);
        tvVersions.set(name, version);
      }
    } catch (error: unknown) {
      // Never abort with a half-built snapshot: record the error and emit
      // tvVersion=null for every library so the daemon's snapshot-age gauge
      // still advances and the stale/loaded alerts fire instead of a silent gap.
      facadeError = error instanceof Error ? error.message : String(error);
      for (const name of libraryNames) {
        if (!tvVersions.has(name)) {
          tvVersions.set(name, null);
        }
      }
    } finally {
      if (session) {
        await closeTradingViewSession(session);
      }
    }
  }

  const snapshot = buildSnapshot(
    pinsByLibrary,
    tvVersions,
    nowUnix,
    facadeError,
    dataAsOfByLibrary,
    payloadByLibrary,
  );
  writeJsonFile(cli.out, snapshot);
  process.stdout.write(JSON.stringify(snapshot, null, 2));
  process.stdout.write("\n");
  // Exit 0 even on drift — the snapshot is the signal; alerting lives in Grafana.
  // Only a total facade failure in a non-dry run is worth a non-zero code.
  return facadeError && !cli.dryRun ? 1 : 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runBuildPineLibraryVersionSnapshotCli()
    .then((code) => process.exit(code))
    .catch((error: unknown) => {
      console.error(error instanceof Error ? error.stack || error.message : String(error));
      process.exit(1);
    });
}
