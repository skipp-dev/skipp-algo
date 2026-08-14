#!/usr/bin/env -S node --enable-source-maps
import path from "node:path";
import { fileURLToPath } from "node:url";

import { runHandLibPublish, type HandLibDescriptor }
  from "../automation/tradingview/lib/tv_publish_hand_lib.js";

export const UTILS_LIBRARY: HandLibDescriptor = {
  scriptName: "smc_utils",
  source: "SMC++/smc_utils.pine",
  alias: "u",
  noun: "Utils",
  reportStem: "publish-utils-library",
  description: "Private utility functions consumed by SMC Core.",
};

export async function runPublishUtilsLibraryCli(): Promise<number> {
  return runHandLibPublish(UTILS_LIBRARY, process.argv);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runPublishUtilsLibraryCli()
    .then((code) => process.exit(code))
    .catch((error: unknown) => {
      console.error(error instanceof Error ? error.stack || error.message : String(error));
      process.exit(1);
    });
}
