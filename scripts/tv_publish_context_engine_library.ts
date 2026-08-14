#!/usr/bin/env -S node --enable-source-maps
import path from "node:path";
import { fileURLToPath } from "node:url";

import { runHandLibPublish, type HandLibDescriptor }
  from "../automation/tradingview/lib/tv_publish_hand_lib.js";

export const CONTEXT_ENGINE_LIBRARY: HandLibDescriptor = {
  scriptName: "smc_context_engine_private",
  source: "SMC++/smc_context_engine_private.pine",
  alias: "cx",
  noun: "Context engine",
  reportStem: "publish-context-engine-library",
  description: "Private confirmed-bar context frames for structure, imbalance, zones, sweeps, liquidity pools, sessions, and aggregate context.",
  // The only hand-lib with the advance-exactly-one contract -- see
  // HandLibDescriptor.requiresExplicitVersionAdvance's docstring for what
  // this opts into (advance contract + live page-auth probe + preflight
  // version check).
  requiresExplicitVersionAdvance: true,
};

export async function runPublishContextEngineLibraryCli(): Promise<number> {
  return runHandLibPublish(CONTEXT_ENGINE_LIBRARY, process.argv);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runPublishContextEngineLibraryCli()
    .then((code) => process.exit(code))
    .catch((error: unknown) => {
      console.error(error instanceof Error ? error.stack || error.message : String(error));
      process.exit(1);
    });
}
