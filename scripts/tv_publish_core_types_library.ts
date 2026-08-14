#!/usr/bin/env -S node --enable-source-maps
import path from "node:path";
import { fileURLToPath } from "node:url";

import { runHandLibPublish, type HandLibDescriptor }
  from "../automation/tradingview/lib/tv_publish_hand_lib.js";

export const CORE_TYPES_LIBRARY: HandLibDescriptor = {
  scriptName: "smc_core_types",
  source: "SMC++/smc_core_types.pine",
  alias: "ct",
  noun: "Core types",
  reportStem: "publish-core-types-library",
  description: "Private core types, enums, and UDT definitions consumed by SMC Core.",
};

export async function runPublishCoreTypesLibraryCli(): Promise<number> {
  return runHandLibPublish(CORE_TYPES_LIBRARY, process.argv);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runPublishCoreTypesLibraryCli()
    .then((code) => process.exit(code))
    .catch((error: unknown) => {
      console.error(error instanceof Error ? error.stack || error.message : String(error));
      process.exit(1);
    });
}
