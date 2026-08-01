import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

export type RolloutExecutionMode = "write" | "verify-only";

export type RolloutExecutionPlan = Readonly<{
  mode: RolloutExecutionMode;
  saveSources: boolean;
  refreshProducer: boolean;
  repairBindings: boolean;
  saveLayout: boolean;
}>;

export type RolloutTarget = {
  source: string;
  scriptName: string;
};

export type ExpectedSource = {
  repoRelativePath: string;
  scriptName: string;
  sha256: string;
  bytes: number;
};

export type RolloutProvenance = {
  repoCommitSha: string;
  rolloutConfigSha256: string;
  productManifestVersion: number;
  libraryReleaseVersion: number;
  inputsMatchCommit: boolean;
  repositoryExpected: {
    rolloutConfigPath: string;
    productManifestPath: string;
    libraryReleaseManifestPath: string;
    sources: ExpectedSource[];
    bindings: Array<{
      repoRelativePath: string;
      scriptName: string;
      expectedProducerName: string;
      labels: string[];
    }>;
    libraryRelease: {
      expectedVersion: number;
      publishedVersion: number;
      publishStatus: string;
      matches: boolean;
    };
  };
};

function isTrue(value: string | undefined): boolean {
  return value?.trim().toLowerCase() === "true";
}

function normalizedMappingOverride(raw: string | undefined): string {
  return raw?.trim() ?? "";
}

export function resolveExecutionPlan(
  args: readonly string[],
  env: NodeJS.ProcessEnv,
): RolloutExecutionPlan {
  const verifyOnly = args.includes("--verify-only");
  const forceRebind = isTrue(env.TV_FORCE_REBIND);
  const refreshProducer = isTrue(env.TV_REFRESH_PRODUCER);
  const mappingOverride = normalizedMappingOverride(env.TV_CONSUMER_MAPPING_JSON);

  if (verifyOnly) {
    if (forceRebind) {
      throw new Error("--verify-only conflicts with TV_FORCE_REBIND=true");
    }
    if (refreshProducer) {
      throw new Error("--verify-only conflicts with TV_REFRESH_PRODUCER=true");
    }
    if (mappingOverride && mappingOverride !== "[]") {
      throw new Error("--verify-only conflicts with non-empty TV_CONSUMER_MAPPING_JSON");
    }
    return Object.freeze({
      mode: "verify-only",
      saveSources: false,
      refreshProducer: false,
      repairBindings: false,
      saveLayout: false,
    });
  }

  if (refreshProducer && !forceRebind) {
    throw new Error(
      "TV_REFRESH_PRODUCER=true requires TV_FORCE_REBIND=true so child BUS sources follow the new parent instance",
    );
  }
  return Object.freeze({
    mode: "write",
    saveSources: true,
    refreshProducer,
    repairBindings: forceRebind,
    saveLayout: forceRebind,
  });
}

export function sha256Bytes(contents: string | Buffer): string {
  return createHash("sha256").update(contents).digest("hex");
}

export function normalizedPineSha256(source: string): string {
  return sha256Bytes(Buffer.from(source.replace(/\r\n/g, "\n"), "utf-8"));
}

function repoRelative(repoRoot: string, filePath: string): string {
  const relative = path.relative(repoRoot, path.resolve(repoRoot, filePath));
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error(`Evidence input escapes repository root: ${filePath}`);
  }
  return relative.split(path.sep).join("/");
}

function readJson(filePath: string): Record<string, unknown> {
  return JSON.parse(fs.readFileSync(filePath, "utf-8")) as Record<string, unknown>;
}

function integerField(value: unknown, label: string): number {
  if (!Number.isInteger(value) || Number(value) < 1) {
    throw new Error(`${label} must be a positive integer`);
  }
  return Number(value);
}

export function gitHeadSha(repoRoot: string): string {
  return execFileSync("git", ["rev-parse", "HEAD"], {
    cwd: repoRoot,
    encoding: "utf-8",
  }).trim();
}

export function inputsMatchHead(repoRoot: string, repoRelativePaths: readonly string[]): boolean {
  const paths = [...new Set(repoRelativePaths)].sort();
  if (paths.length === 0) return false;
  const options = { cwd: repoRoot, stdio: "ignore" as const };
  try {
    execFileSync("git", ["diff", "--quiet", "HEAD", "--", ...paths], options);
    execFileSync("git", ["diff", "--cached", "--quiet", "HEAD", "--", ...paths], options);
    for (const input of paths) {
      execFileSync("git", ["ls-files", "--error-unmatch", "--", input], options);
    }
    return true;
  } catch {
    return false;
  }
}

export function buildRolloutProvenance(options: {
  repoRoot: string;
  configPath: string;
  productManifestPath: string;
  libraryReleaseManifestPath: string;
  sourceTargets: readonly RolloutTarget[];
  bindingTargets: ReadonlyArray<{
    source: string;
    scriptName: string;
    labels: readonly string[];
  }>;
  producerName: string;
}): RolloutProvenance {
  const repoRoot = path.resolve(options.repoRoot);
  const configPath = path.resolve(options.configPath);
  const productManifestPath = path.resolve(options.productManifestPath);
  const libraryReleaseManifestPath = path.resolve(options.libraryReleaseManifestPath);
  const productManifest = readJson(productManifestPath);
  const releaseManifest = readJson(libraryReleaseManifestPath);
  const library = releaseManifest.library as Record<string, unknown> | undefined;
  if (!library) throw new Error("library release manifest has no library object");

  const expectedVersion = integerField(library.expectedVersion, "library.expectedVersion");
  const publishedVersion = integerField(library.publishedVersion, "library.publishedVersion");
  const publishStatus = typeof library.publishStatus === "string" ? library.publishStatus : "";
  const releaseMatches = expectedVersion === publishedVersion && publishStatus === "published";

  const sourceInputs = options.sourceTargets.map((target) => {
    const sourcePath = path.resolve(repoRoot, target.source);
    const source = fs.readFileSync(sourcePath, "utf-8");
    return {
      repoRelativePath: repoRelative(repoRoot, sourcePath),
      scriptName: target.scriptName,
      sha256: normalizedPineSha256(source),
      bytes: Buffer.byteLength(source, "utf-8"),
    };
  });
  const bindingInputs = options.bindingTargets.map((target) => ({
    repoRelativePath: repoRelative(repoRoot, target.source),
    scriptName: target.scriptName,
    expectedProducerName: options.producerName,
    labels: [...target.labels],
  }));
  const rolloutConfigPath = repoRelative(repoRoot, configPath);
  const productPath = repoRelative(repoRoot, productManifestPath);
  const releasePath = repoRelative(repoRoot, libraryReleaseManifestPath);
  const trackedInputs = [
    rolloutConfigPath,
    productPath,
    releasePath,
    ...sourceInputs.map((item) => item.repoRelativePath),
    ...bindingInputs.map((item) => item.repoRelativePath),
  ];

  return {
    repoCommitSha: gitHeadSha(repoRoot),
    rolloutConfigSha256: sha256Bytes(fs.readFileSync(configPath)),
    productManifestVersion: integerField(productManifest.manifestVersion, "product manifestVersion"),
    libraryReleaseVersion: publishedVersion,
    inputsMatchCommit: inputsMatchHead(repoRoot, trackedInputs),
    repositoryExpected: {
      rolloutConfigPath,
      productManifestPath: productPath,
      libraryReleaseManifestPath: releasePath,
      sources: sourceInputs,
      bindings: bindingInputs,
      libraryRelease: {
        expectedVersion,
        publishedVersion,
        publishStatus,
        matches: releaseMatches,
      },
    },
  };
}

export type RolloutLayoutGroup<T> = Readonly<{ chartUrl: string; targets: readonly T[] }>;

/**
 * The rollout's targets split into the chart layouts it visits, in visit order.
 *
 * The rollout walks `verifyTargets` and calls `gotoChart` whenever the next
 * target lives on a different chart. `gotoChart` is a hard `page.goto`, so the
 * reload discards every unsaved rebind made on the layout being left. That is
 * why a single save after the loop persisted only the LAST layout, and why
 * saving afterwards by navigating back would persist the reverted state rather
 * than the repair.
 *
 * The layout is therefore the unit the rollout can act on atomically: every
 * rebind on it is persisted together by one save, or discarded together by the
 * next reload. Grouping the targets makes that unit explicit, so the caller can
 * decide per layout — save it, or abandon it — instead of per target.
 *
 * Consecutive duplicates are collapsed; a layout the run returns to later
 * legitimately appears twice, because it has to be saved again.
 */
export function groupTargetsByLayout<T extends { chartUrl?: string }>(
  targets: ReadonlyArray<T>,
  primaryChartUrl: string,
): Array<RolloutLayoutGroup<T>> {
  const groups: Array<{ chartUrl: string; targets: T[] }> = [];
  for (const target of targets) {
    const chartUrl = target.chartUrl ?? primaryChartUrl;
    const current = groups[groups.length - 1];
    if (current && current.chartUrl === chartUrl) current.targets.push(target);
    else groups.push({ chartUrl, targets: [target] });
  }
  return groups;
}

/** The chart layouts a repairing rollout must SAVE, in the order it visits them. */
export function resolveLayoutSavePoints(
  targets: ReadonlyArray<{ chartUrl?: string }>,
  primaryChartUrl: string,
): string[] {
  return groupTargetsByLayout(targets, primaryChartUrl).map((group) => group.chartUrl);
}
