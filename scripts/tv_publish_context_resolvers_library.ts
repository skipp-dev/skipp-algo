#!/usr/bin/env -S node --enable-source-maps
import path from "node:path";
import { fileURLToPath } from "node:url";

import { runHandLibPublish, type HandLibDescriptor }
  from "../automation/tradingview/lib/tv_publish_hand_lib.js";

export const CONTEXT_RESOLVERS_LIBRARY: HandLibDescriptor = {
  scriptName: "smc_context_resolvers",
  source: "SMC++/smc_context_resolvers.pine",
  alias: "cr",
  noun: "Context resolvers",
  reportStem: "publish-context-resolvers-library",
  description: "Private context resolvers consumed by SMC Core.",
};

export async function runPublishContextResolversLibraryCli(): Promise<number> {
  return runHandLibPublish(CONTEXT_RESOLVERS_LIBRARY, process.argv);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runPublishContextResolversLibraryCli()
    .then((code) => process.exit(code))
    .catch((error: unknown) => {
      console.error(error instanceof Error ? error.stack || error.message : String(error));
      process.exit(1);
    });
}
