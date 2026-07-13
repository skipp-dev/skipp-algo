#!/usr/bin/env -S node --enable-source-maps
/**
 * Ordered publish + repin for the hand-authored SMC++ libraries.
 *
 * Why this exists: the 8 hand-authored `SMC++/` libraries form a DEPENDENCY
 * GRAPH (smc_utils imports smc_core_types; profile_engine/observability/
 * context_resolvers import smc_utils; context_resolvers also imports
 * smc_bus_private). #3606 had to republish them BY HAND in topological order —
 * core_types before utils before its dependents — repinning each lib's own
 * dep-imports to the freshly published version between publishes, or the
 * downstream lib compiles against a stale dependency (CE10271 on missing
 * exports). This helper encodes that ordering so the operator runs ONE command
 * instead of hand-sequencing publishes.
 *
 * It is OPERATOR-TRIGGERED (no schedule): the live-overlay daemon's
 * `pine_library_version_bridge` + Grafana drift alert (PR #3607) tell the
 * operator WHEN a republish is due; this tells the operator HOW, safely.
 *
 * Each publish is facade-verified (PR #3609 wired
 * `fetchPublishedLibraryVersionViaFacade` into every hand-lib publisher, so a
 * successful publish reports the real published version instead of exiting rc=1
 * not_verified). TradingView no-ops an unchanged publish, so running the whole
 * set is idempotent — unchanged libs don't bump; the run still repins consumers
 * to the real published versions, reconciling any lingering drift.
 *
 * `--dry-run` prints the publish order + repin plan and performs NO live
 * publish and NO file edits.
 */
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

/** One hand-authored library: its TV script name, source, publisher, consumers. */
export type HandLib = {
  name: string;
  source: string;
  /** Publisher CLI relative to repo root, or null when none exists (smc_bus_private). */
  publisher: string | null;
};

/**
 * The hand-authored library set. `deps` are DERIVED from each source's imports
 * at runtime (see {@link parseHandLibDeps}); this table only pins the identity
 * + publisher mapping (which is irregular: smc_lifecycle_private →
 * tv_publish_lifecycle_library.ts, etc.).
 */
export const HAND_LIBS: HandLib[] = [
  { name: "smc_core_types", source: "SMC++/smc_core_types.pine", publisher: "scripts/tv_publish_core_types_library.ts" },
  { name: "smc_utils", source: "SMC++/smc_utils.pine", publisher: "scripts/tv_publish_utils_library.ts" },
  { name: "smc_draw", source: "SMC++/smc_draw.pine", publisher: "scripts/tv_publish_draw_library.ts" },
  { name: "smc_lifecycle_private", source: "SMC++/smc_lifecycle_private.pine", publisher: "scripts/tv_publish_lifecycle_library.ts" },
  { name: "smc_observability_private", source: "SMC++/smc_observability_private.pine", publisher: "scripts/tv_publish_observability_library.ts" },
  { name: "smc_context_resolvers", source: "SMC++/smc_context_resolvers.pine", publisher: "scripts/tv_publish_context_resolvers_library.ts" },
  { name: "smc_profile_engine", source: "SMC++/smc_profile_engine.pine", publisher: "scripts/tv_publish_profile_engine_library.ts" },
  // smc_bus_private has NO publisher script (repo→TV gap). It is included so the
  // topo sort + consumer repin still account for it, but it cannot be published
  // by this helper — surfaced as a warning at the next line that would need it.
  { name: "smc_bus_private", source: "SMC++/smc_bus_private.pine", publisher: null },
];

const OWNER = "preuss_steffen";

/** Parse the hand-lib dependency names a library source imports (owner-scoped). */
export function parseHandLibDeps(sourceText: string, known: ReadonlySet<string>): string[] {
  const deps = new Set<string>();
  const re = new RegExp(`import\\s+${OWNER}\\/([A-Za-z0-9_]+)\\/`, "g");
  for (const m of sourceText.matchAll(re)) {
    if (known.has(m[1])) {
      deps.add(m[1]);
    }
  }
  return [...deps];
}

/**
 * Kahn topological sort: dependencies before dependents. Deterministic — ties
 * break by the input order of {@link HAND_LIBS}. Throws on a cycle.
 */
export function topoSort(libs: readonly HandLib[], depsByLib: ReadonlyMap<string, readonly string[]>): HandLib[] {
  const byName = new Map(libs.map((l) => [l.name, l]));
  const indegree = new Map<string, number>(libs.map((l) => [l.name, 0]));
  const dependents = new Map<string, string[]>(libs.map((l) => [l.name, []]));
  for (const lib of libs) {
    for (const dep of depsByLib.get(lib.name) ?? []) {
      if (!byName.has(dep)) {
        continue;
      }
      indegree.set(lib.name, (indegree.get(lib.name) ?? 0) + 1);
      dependents.get(dep)!.push(lib.name);
    }
  }
  // Seed the queue in input order so the result is stable.
  const queue = libs.filter((l) => (indegree.get(l.name) ?? 0) === 0).map((l) => l.name);
  const ordered: HandLib[] = [];
  while (queue.length > 0) {
    const name = queue.shift()!;
    ordered.push(byName.get(name)!);
    for (const dependent of dependents.get(name) ?? []) {
      const next = (indegree.get(dependent) ?? 0) - 1;
      indegree.set(dependent, next);
      if (next === 0) {
        queue.push(dependent);
      }
    }
  }
  if (ordered.length !== libs.length) {
    const cyclic = libs.filter((l) => !ordered.includes(l)).map((l) => l.name);
    throw new Error(`Cyclic hand-library dependency detected among: ${cyclic.join(", ")}`);
  }
  return ordered;
}

/**
 * Repin one library's import in a Pine source: rewrite
 * `import preuss_steffen/<lib>/<any>` → `.../<version>`. Returns the new text
 * and whether anything changed. Pure.
 */
export function repinImport(text: string, lib: string, version: number): { text: string; changed: boolean } {
  const re = new RegExp(`(import\\s+${OWNER}\\/${lib}\\/)\\d+`, "g");
  let changed = false;
  const out = text.replace(re, (_m, prefix: string) => {
    changed = true;
    return `${prefix}${version}`;
  });
  return { text: out, changed };
}

/** Resolve the derived dependency map for the whole hand-lib set. */
export function resolveDeps(libs: readonly HandLib[], repoRoot: string): Map<string, string[]> {
  const known = new Set(libs.map((l) => l.name));
  const depsByLib = new Map<string, string[]>();
  for (const lib of libs) {
    const src = fs.readFileSync(path.join(repoRoot, lib.source), "utf-8");
    depsByLib.set(lib.name, parseHandLibDeps(src, known).filter((d) => d !== lib.name));
  }
  return depsByLib;
}

/** Every repo `.pine` file that may pin a hand-lib (root consumers + SMC++ sources). */
function consumerPineFiles(repoRoot: string): string[] {
  const out: string[] = [];
  const roots = [repoRoot, path.join(repoRoot, "SMC++")];
  for (const dir of roots) {
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

/** Repin `lib` to `version` across all consumer files; returns the changed files. */
export function repinAllConsumers(repoRoot: string, lib: string, version: number, write: boolean): string[] {
  const changedFiles: string[] = [];
  for (const file of consumerPineFiles(repoRoot)) {
    const before = fs.readFileSync(file, "utf-8");
    const { text, changed } = repinImport(before, lib, version);
    if (changed && text !== before) {
      changedFiles.push(path.relative(repoRoot, file));
      if (write) {
        fs.writeFileSync(file, text, "utf-8");
      }
    }
  }
  return changedFiles;
}

type PublishResult = { name: string; ok: boolean; version: number | null; noPublisher?: boolean };

/** Run one publisher CLI (live) and return the facade-verified published version. */
function runPublisher(lib: HandLib, repoRoot: string, tsxBin: string): PublishResult {
  if (!lib.publisher) {
    return { name: lib.name, ok: false, version: null, noPublisher: true };
  }
  const out = path.join(os.tmpdir(), `publish-${lib.name}-${process.pid}.json`);
  const res = spawnSync(tsxBin, [path.join(repoRoot, lib.publisher), "--out", out], {
    cwd: repoRoot,
    stdio: ["ignore", "inherit", "inherit"],
    encoding: "utf-8",
  });
  let version: number | null = null;
  try {
    const report = JSON.parse(fs.readFileSync(out, "utf-8")) as { publishedVersion?: number | null };
    version = typeof report.publishedVersion === "number" ? report.publishedVersion : null;
  } catch {
    version = null;
  }
  return { name: lib.name, ok: res.status === 0 && version !== null, version };
}

type CliArgs = { repoRoot: string; dryRun: boolean };

function parseArgs(argv: string[]): CliArgs {
  const args = argv.slice(2);
  const getFlag = (name: string, fallback: string): string => {
    const i = args.indexOf(name);
    return i === -1 || !args[i + 1] ? fallback : args[i + 1];
  };
  return {
    repoRoot: path.resolve(getFlag("--repo-root", process.cwd())),
    dryRun: args.includes("--dry-run"),
  };
}

export async function runPublishHandAuthoredLibrariesCli(argv: string[] = process.argv): Promise<number> {
  const cli = parseArgs(argv);
  const depsByLib = resolveDeps(HAND_LIBS, cli.repoRoot);
  const order = topoSort(HAND_LIBS, depsByLib);

  process.stdout.write("Hand-authored library publish order (dependencies first):\n");
  order.forEach((lib, i) => {
    const deps = depsByLib.get(lib.name) ?? [];
    const pub = lib.publisher ? "" : "  [NO PUBLISHER — cannot republish, will only repin]";
    process.stdout.write(`  ${i + 1}. ${lib.name}${deps.length ? ` (deps: ${deps.join(", ")})` : ""}${pub}\n`);
  });

  if (cli.dryRun) {
    process.stdout.write("\n--dry-run: no publish, no file edits. Consumer repins would target each library's\n");
    process.stdout.write("facade-verified published version after the ordered publish above.\n");
    const gap = HAND_LIBS.filter((l) => !l.publisher).map((l) => l.name);
    if (gap.length) {
      process.stdout.write(`\n⚠️  No-publisher gap: ${gap.join(", ")} — a required republish here needs a new tv_publish_* script first.\n`);
    }
    return 0;
  }

  const tsxBin = path.join(cli.repoRoot, "node_modules", ".bin", "tsx");
  const published = new Map<string, number>();
  const failures: string[] = [];

  for (const lib of order) {
    // 1. Repin this lib's OWN dep-imports to versions published earlier this run,
    //    so the published lib compiles against the fresh dependency.
    for (const dep of depsByLib.get(lib.name) ?? []) {
      const v = published.get(dep);
      if (v !== undefined) {
        const src = path.join(cli.repoRoot, lib.source);
        const { text, changed } = repinImport(fs.readFileSync(src, "utf-8"), dep, v);
        if (changed) {
          fs.writeFileSync(src, text, "utf-8");
          process.stdout.write(`  repin ${lib.source}: ${dep} → /${v}\n`);
        }
      }
    }
    // 2. Publish (facade-verified) unless there is no publisher.
    process.stdout.write(`\n▶ publishing ${lib.name} …\n`);
    const result = runPublisher(lib, cli.repoRoot, tsxBin);
    if (result.noPublisher) {
      process.stdout.write(`  ⚠️  ${lib.name} has no publisher — skipping publish (consumers keep their current pin).\n`);
      continue;
    }
    if (!result.ok || result.version === null) {
      failures.push(lib.name);
      process.stdout.write(`  ❌ ${lib.name} publish/verify failed — stopping before dependents publish against a stale version.\n`);
      break;
    }
    published.set(lib.name, result.version);
    process.stdout.write(`  ✅ ${lib.name} published/verified at /${result.version}\n`);
  }

  // 3. Repin ALL consumers (root + SMC++) to the freshly published versions.
  for (const [lib, version] of published) {
    const files = repinAllConsumers(cli.repoRoot, lib, version, true);
    if (files.length) {
      process.stdout.write(`\nrepin consumers → ${lib}/${version}:\n`);
      files.forEach((f) => process.stdout.write(`  ${f}\n`));
    }
  }

  if (failures.length) {
    process.stdout.write(`\n❌ Failed: ${failures.join(", ")}. Review the publisher output, then re-run.\n`);
    return 1;
  }
  process.stdout.write("\n✅ Done. Review the repinned .pine files and commit them.\n");
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runPublishHandAuthoredLibrariesCli()
    .then((code) => process.exit(code))
    .catch((error: unknown) => {
      console.error(error instanceof Error ? error.stack || error.message : String(error));
      process.exit(1);
    });
}
