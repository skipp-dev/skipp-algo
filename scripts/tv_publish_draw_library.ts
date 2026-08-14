#!/usr/bin/env -S node --enable-source-maps
import path from "node:path";
import { fileURLToPath } from "node:url";

import { runHandLibPublish, type HandLibDescriptor }
  from "../automation/tradingview/lib/tv_publish_hand_lib.js";

export const DRAW_LIBRARY: HandLibDescriptor = {
  scriptName: "smc_draw",
  source: "SMC++/smc_draw.pine",
  alias: "d",
  noun: "Draw",
  reportStem: "publish-draw-library",
  description: "Private drawing and visualization helpers consumed by SMC Core.",
};

export async function runPublishDrawLibraryCli(): Promise<number> {
  return runHandLibPublish(DRAW_LIBRARY, process.argv);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runPublishDrawLibraryCli()
    .then((code) => process.exit(code))
    .catch((error: unknown) => {
      console.error(error instanceof Error ? error.stack || error.message : String(error));
      process.exit(1);
    });
}
