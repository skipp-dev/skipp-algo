#!/usr/bin/env -S node --enable-source-maps
import path from "node:path";
import { fileURLToPath } from "node:url";

import { runHandLibPublish, type HandLibDescriptor }
  from "../automation/tradingview/lib/tv_publish_hand_lib.js";

export const LIFECYCLE_LIBRARY: HandLibDescriptor = {
  scriptName: "smc_lifecycle_private",
  source: "SMC++/smc_lifecycle_private.pine",
  alias: "ll",
  noun: "Lifecycle",
  reportStem: "publish-lifecycle-library",
  description: "Private lifecycle, readiness, blocker, and risk-plan helpers consumed by SMC Core.",
};

export async function runPublishLifecycleLibraryCli(): Promise<number> {
  return runHandLibPublish(LIFECYCLE_LIBRARY, process.argv);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runPublishLifecycleLibraryCli()
    .then((code) => process.exit(code))
    .catch((error: unknown) => {
      console.error(error instanceof Error ? error.stack || error.message : String(error));
      process.exit(1);
    });
}
