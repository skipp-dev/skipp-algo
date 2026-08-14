#!/usr/bin/env -S node --enable-source-maps
import path from "node:path";
import { fileURLToPath } from "node:url";

import { runHandLibPublish, type HandLibDescriptor }
  from "../automation/tradingview/lib/tv_publish_hand_lib.js";

export const PROFILE_ENGINE_LIBRARY: HandLibDescriptor = {
  scriptName: "smc_profile_engine",
  source: "SMC++/smc_profile_engine.pine",
  alias: "pe",
  noun: "Profile engine",
  reportStem: "publish-profile-engine-library",
  description: "Private profile engine consumed by SMC Core.",
};

export async function runPublishProfileEngineLibraryCli(): Promise<number> {
  return runHandLibPublish(PROFILE_ENGINE_LIBRARY, process.argv);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runPublishProfileEngineLibraryCli()
    .then((code) => process.exit(code))
    .catch((error: unknown) => {
      console.error(error instanceof Error ? error.stack || error.message : String(error));
      process.exit(1);
    });
}
