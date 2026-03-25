#!/usr/bin/env -S node --enable-source-maps

throw new Error(
  "scripts/99_full_release.ts is deprecated and blocked. Use scripts/tv_publish_micro_library.ts for the fail-closed TradingView publish path.",
);

import fs from "node:fs";
import path from "node:path";

import {
  addCurrentScriptToChart,
  assertInputLabelsVisible,
  assertNoVisibleCompileError,
  closeModal,
  closeTradingViewSession,
  detectPublishedVersionFromBody,
  ensurePineEditor,
  gotoChart,
  newTradingViewSession,
  openExistingScript,
  openInputsTab,
  openSettingsForScript,
  parseInputSourceLabels,
  publishPrivateScript,
  saveScript,
  setEditorContent,
  takeScreenshot,
  utcNow,
  writeJson,
} from "../automation/tradingview/lib/tv_shared.js";

type ReleaseTarget = {
  file: string;
  scriptName: string;
  publishTitle?: string;
  publishDescription?: string;
  checkInputs?: boolean;
  addToChart?: boolean;
  minInputs?: number;
};

type CliArgs = {
  config?: string;
  out: string;
  openExisting: boolean;
};

type TargetResult = {
  file: string;
  scriptName: string;
  ok: boolean;
  publishedVersion: number | null;
  screenshots: string[];
  error?: string;
};

function parseArgs(): CliArgs {
  const args = process.argv.slice(2);

  function getFlag(name: string): string | undefined {
    const index = args.indexOf(name);
    if (index === -1 || !args[index + 1]) {
      return undefined;
    }
    return args[index + 1];
  }

  function hasFlag(name: string): boolean {
    return args.includes(name);
  }

  return {
    config: getFlag("--config")
      ? path.resolve(getFlag("--config") as string)
      : process.env.TV_RELEASE_CONFIG
        ? path.resolve(process.env.TV_RELEASE_CONFIG)
        : undefined,
    out: path.resolve(
      getFlag("--out") ||
        process.env.TV_RELEASE_REPORT ||
        `automation/tradingview/reports/full-release-${utcNow().replace(/[:.]/g, "-")}.json`,
    ),
    openExisting: hasFlag("--no-open-existing") ? false : true,
  };
}

function defaultTargets(): ReleaseTarget[] {
  return [
    {
      file: "SMC_Core_Engine.pine",
      scriptName: "SMC Core Engine",
      publishTitle: "SMC Core Engine",
      publishDescription: "Automated private release of the SMC Core Engine.",
      checkInputs: false,
      addToChart: false,
    },
    {
      file: "SMC_Dashboard.pine",
      scriptName: "SMC Dashboard",
      publishTitle: "SMC Dashboard",
      publishDescription: "Automated private release of the SMC Dashboard consumer.",
      checkInputs: true,
      addToChart: true,
      minInputs: 26,
    },
    {
      file: "SMC_Long_Strategy.pine",
      scriptName: "SMC Long Strategy",
      publishTitle: "SMC Long Strategy",
      publishDescription: "Automated private release of the SMC strategy consumer.",
      checkInputs: true,
      addToChart: true,
      minInputs: 8,
    },
  ];
}

function loadTargets(configPath?: string): ReleaseTarget[] {
  if (!configPath) {
    return defaultTargets();
  }

  const payload = JSON.parse(fs.readFileSync(configPath, "utf-8")) as {
    targets?: ReleaseTarget[];
  };

  if (!payload.targets || payload.targets.length === 0) {
    throw new Error(`No targets defined in config: ${configPath}`);
  }

  return payload.targets;
}

async function main(): Promise<number> {
  const cli = parseArgs();
  const targets = loadTargets(cli.config);
  const runId = utcNow().replace(/[:.]/g, "-");
  const results: TargetResult[] = [];
  const session = await newTradingViewSession();

  try {
    await gotoChart(session.page);
    await ensurePineEditor(session.page);

    for (const target of targets) {
      const screenshots: string[] = [];
      const filePath = path.resolve(target.file);
      const code = fs.readFileSync(filePath, "utf-8");
      const inputLabels = [...new Set(parseInputSourceLabels(code))];

      try {
        if (cli.openExisting) {
          const openedExisting = await openExistingScript(session.page, target.scriptName);
          if (!openedExisting) {
            throw new Error(
              `Could not open existing TradingView script: ${target.scriptName}. Rerun with --no-open-existing only if a fresh untitled draft is intended.`,
            );
          }
        }

        await ensurePineEditor(session.page);
        await setEditorContent(session.page, code);
        await saveScript(session.page, target.scriptName);
        await assertNoVisibleCompileError(session.page);
        await takeScreenshot(session.page, runId, `${target.scriptName}-compiled`, screenshots);

        if (target.addToChart || target.checkInputs) {
          await addCurrentScriptToChart(session.page);
        }

        if (target.checkInputs && inputLabels.length > 0) {
          await openSettingsForScript(session.page, target.scriptName);
          await openInputsTab(session.page);
          await assertInputLabelsVisible(
            session.page,
            inputLabels,
            Math.min(target.minInputs ?? inputLabels.length, inputLabels.length),
          );
          await takeScreenshot(session.page, runId, `${target.scriptName}-inputs`, screenshots);
          await closeModal(session.page);
        }

        await publishPrivateScript(session.page, {
          title: target.publishTitle ?? target.scriptName,
          description:
            target.publishDescription ?? `Automated private release for ${target.scriptName} at ${utcNow()}.`,
        });
        await takeScreenshot(session.page, runId, `${target.scriptName}-published`, screenshots);

        const bodyText = await session.page.locator("body").innerText().catch(() => "");
        results.push({
          file: filePath,
          scriptName: target.scriptName,
          ok: true,
          publishedVersion: detectPublishedVersionFromBody(bodyText, target.scriptName),
          screenshots,
        });
      } catch (error: unknown) {
        await takeScreenshot(session.page, runId, `${target.scriptName}-error`, screenshots).catch(() => undefined);
        await closeModal(session.page).catch(() => undefined);
        results.push({
          file: filePath,
          scriptName: target.scriptName,
          ok: false,
          publishedVersion: null,
          screenshots,
          error: error instanceof Error ? error.stack || error.message : String(error),
        });
      }
    }
  } finally {
    await closeTradingViewSession(session);
  }

  writeJson(cli.out, {
    generatedAt: utcNow(),
    ok: results.every((result) => result.ok),
    targets: results,
  });

  const failed = results.filter((result) => !result.ok);
  if (failed.length > 0) {
    for (const result of failed) {
      console.error(`[release] ${result.scriptName}: ${result.error}`);
    }
    console.error(`Release report written to ${cli.out}`);
    return 1;
  }

  console.log(`Release report written to ${cli.out}`);
  return 0;
}

main()
  .then((code) => process.exit(code))
  .catch((error: unknown) => {
    console.error(error instanceof Error ? error.stack || error.message : String(error));
    process.exit(1);
  });