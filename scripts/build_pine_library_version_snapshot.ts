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
 *   1. discovers every `import preuss_steffen/<lib>/<N>` pin in the repo's
 *      `.pine` files (root consumers + inter-library imports),
 *   2. probes each distinct library's REAL published version via the
 *      pine-facade `filter=published` listing
 *      (`fetchPublishedLibraryVersionViaFacade` — the #3603-corrected source;
 *      `filter=saved` counts editor save revisions, not the importable
 *      version), and
 *   3. writes a compact snapshot the live-overlay daemon's
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
  consumers: ConsumerEntry[];
  anyConsumerDrift: boolean;
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
 * Discover all consumer pins in the repo, grouped by library name. Paths are
 * repo-relative so the snapshot is host-independent.
 */
export function discoverConsumerPins(root: string): Map<string, ConsumerPin[]> {
  const byLibrary = new Map<string, ConsumerPin[]>();
  for (const absFile of collectPineFiles(root)) {
    const rel = path.relative(root, absFile);
    const text = fs.readFileSync(absFile, "utf-8");
    for (const pin of parseImportPins(text, rel)) {
      const list = byLibrary.get(pin.library) ?? [];
      list.push(pin);
      byLibrary.set(pin.library, list);
    }
  }
  return byLibrary;
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
): PineLibraryVersionSnapshot {
  const libraries: LibrarySnapshot[] = [];
  for (const name of [...pinsByLibrary.keys()].sort()) {
    const tvVersion = tvVersions.get(name) ?? null;
    const tvVersionKnown = typeof tvVersion === "number";
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
    libraries.push({
      name,
      tvVersion,
      tvVersionKnown,
      consumers,
      anyConsumerDrift,
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

  const snapshot = buildSnapshot(pinsByLibrary, tvVersions, nowUnix, facadeError);
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
