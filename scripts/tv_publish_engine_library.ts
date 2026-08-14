#!/usr/bin/env -S node --enable-source-maps
import path from "node:path";
import { fileURLToPath } from "node:url";

import { runHandLibPublish, type HandLibDescriptor }
  from "../automation/tradingview/lib/tv_publish_hand_lib.js";

export const ENGINE_LIBRARY: HandLibDescriptor = {
  scriptName: "smc_engine_private",
  source: "SMC++/smc_engine_private.pine",
  alias: "eng",
  noun: "Engine",
  reportStem: "publish-engine-private-library",
  description: "SMC OB/FVG/structure engine (OrderBlock, FVG types + tracking/detection/drawing) consumed by SMC Core. Extracted to relieve the main-script token budget (CE10117).",
};

export async function runPublishEnginePrivateLibraryCli(): Promise<number> {
  return runHandLibPublish(ENGINE_LIBRARY, process.argv);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runPublishEnginePrivateLibraryCli()
    .then((code) => process.exit(code))
    .catch((error: unknown) => {
      console.error(error instanceof Error ? error.stack || error.message : String(error));
      process.exit(1);
    });
}
