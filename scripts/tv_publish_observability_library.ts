#!/usr/bin/env -S node --enable-source-maps
import path from "node:path";
import { fileURLToPath } from "node:url";

import { runHandLibPublish, type HandLibDescriptor }
  from "../automation/tradingview/lib/tv_publish_hand_lib.js";

export const OBSERVABILITY_LIBRARY: HandLibDescriptor = {
  scriptName: "smc_observability_private",
  source: "SMC++/smc_observability_private.pine",
  alias: "obv",
  noun: "Observability",
  reportStem: "publish-observability-library",
  description: "Private ready-edge and observability helpers consumed by SMC Core.",
};

export async function runPublishObservabilityLibraryCli(): Promise<number> {
  return runHandLibPublish(OBSERVABILITY_LIBRARY, process.argv);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runPublishObservabilityLibraryCli()
    .then((code) => process.exit(code))
    .catch((error: unknown) => {
      console.error(error instanceof Error ? error.stack || error.message : String(error));
      process.exit(1);
    });
}
