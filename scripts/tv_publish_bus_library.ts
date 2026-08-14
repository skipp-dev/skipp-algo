#!/usr/bin/env -S node --enable-source-maps
import path from "node:path";
import { fileURLToPath } from "node:url";

import { runHandLibPublish, type HandLibDescriptor }
  from "../automation/tradingview/lib/tv_publish_hand_lib.js";

export const BUS_LIBRARY: HandLibDescriptor = {
  scriptName: "smc_bus_private",
  source: "SMC++/smc_bus_private.pine",
  alias: "bp",
  noun: "Bus",
  reportStem: "publish-bus-library",
  description: "Private message-bus helpers consumed by SMC Core.",
};

export async function runPublishBusLibraryCli(): Promise<number> {
  return runHandLibPublish(BUS_LIBRARY, process.argv);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runPublishBusLibraryCli()
    .then((code) => process.exit(code))
    .catch((error: unknown) => {
      console.error(error instanceof Error ? error.stack || error.message : String(error));
      process.exit(1);
    });
}
