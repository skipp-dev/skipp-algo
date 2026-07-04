#!/usr/bin/env -S node --enable-source-maps

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  closeTradingViewSession,
  newTradingViewSession,
} from "../automation/tradingview/lib/tv_shared.js";

type LibraryConfig = {
  name: string;
  owner: string;
  version: string;
  local_path: string;
};

const LIBRARIES: LibraryConfig[] = [
  {
    name: "smc_overlay_generated",
    owner: "preuss_steffen",
    version: "1",
    local_path: "pine/generated/smc_overlay_generated.pine",
  },
  {
    name: "smc_profile_engine",
    owner: "preuss_steffen",
    version: "1",
    local_path: "SMC++/smc_profile_engine.pine",
  },
  {
    name: "smc_context_resolvers",
    owner: "preuss_steffen",
    version: "1",
    local_path: "SMC++/smc_context_resolvers.pine",
  },
  {
    name: "smc_observability_private",
    owner: "preuss_steffen",
    version: "1",
    local_path: "SMC++/smc_observability_private.pine",
  },
  {
    name: "smc_bus_private",
    owner: "preuss_steffen",
    version: "1",
    local_path: "SMC++/smc_bus_private.pine",
  },
  {
    name: "smc_lifecycle_private",
    owner: "preuss_steffen",
    version: "1",
    local_path: "SMC++/smc_lifecycle_private.pine",
  },
];

async function fetchLibrarySource(
  session: any,
  lib: LibraryConfig,
): Promise<string | null> {
  const tvUrl = `https://www.tradingview.com/script/${lib.owner.toLowerCase()}${lib.name.toLowerCase()}${lib.version}/`;

  console.log(`[${lib.name}] Fetching from ${tvUrl}`);

  try {
    await session.page.goto(tvUrl, { waitUntil: "networkidle" });

    // Wait for the editor to load
    await session.page.waitForSelector('[data-testid="editor-container"], .editor-wrapper', {
      timeout: 10000,
    }).catch(() => {
      console.warn(`[${lib.name}] Editor container not found, trying alternative selector`);
    });

    // Try to extract source from the editor
    // TradingView renders Pine code in a code editor, we need to get the textarea or contenteditable
    let source = null;

    // Method 1: Try textarea or input
    const editorTextarea = await session.page.locator('textarea[data-testid="editor-input"], textarea.CodeMirror-code').first();
    if (editorTextarea) {
      source = await editorTextarea.inputValue().catch(() => null);
    }

    // Method 2: Try contenteditable
    if (!source) {
      const editableEditor = await session.page.locator('[contenteditable="true"]').first();
      if (editableEditor) {
        source = await editableEditor.innerText().catch(() => null);
      }
    }

    // Method 3: Try pre or code block (fallback)
    if (!source) {
      const codeBlock = await session.page.locator('pre code, code.hljs').first();
      if (codeBlock) {
        source = await codeBlock.innerText().catch(() => null);
      }
    }

    if (!source || source.trim().length === 0) {
      console.error(`[${lib.name}] Could not extract source code from TradingView`);
      return null;
    }

    console.log(`[${lib.name}] ✓ Fetched ${source.length} bytes`);
    return source;
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.message : String(error);
    console.error(`[${lib.name}] Fetch failed: ${msg}`);
    return null;
  }
}

function validatePineSource(source: string, libName: string): boolean {
  // Check for required library declaration
  if (!new RegExp(`library\\s*\\(\\s*["\']?${libName}["\']?`).test(source)) {
    console.error(`[${libName}] Missing library declaration`);
    return false;
  }

  // Check for unbalanced braces
  const openBraces = source.match(/{/g)?.length ?? 0;
  const closeBraces = source.match(/}/g)?.length ?? 0;
  if (openBraces !== closeBraces) {
    console.error(`[${libName}] Unbalanced braces (${openBraces} open, ${closeBraces} close)`);
    return false;
  }

  // Check for unclosed block comments
  const openComments = source.match(/\/\*/g)?.length ?? 0;
  const closeComments = source.match(/\*\//g)?.length ?? 0;
  if (openComments !== closeComments) {
    console.error(`[${libName}] Unclosed block comments (${openComments} open, ${closeComments} close)`);
    return false;
  }

  return true;
}

async function main(): Promise<number> {
  console.log("TradingView SMC Library Synchronizer (Playwright-based)\n");

  // Parse command-line args
  const args = process.argv.slice(2);
  const dryRun = args.includes("--dry-run");
  const force = args.includes("--force");

  if (dryRun) {
    console.log("[DRY-RUN MODE] No files will be written.\n");
  }

  let session: any = null;
  let successCount = 0;
  let failureCount = 0;

  try {
    console.log("Opening TradingView session with TV_STORAGE_STATE...\n");
    session = await newTradingViewSession();

    if (!session.authResolution.authReusedOk) {
      throw new Error("TradingView auth failed. Ensure TV_STORAGE_STATE is valid.");
    }

    console.log("✓ Authenticated with TradingView\n");

    for (const lib of LIBRARIES) {
      console.log(`\n${"=".repeat(60)}`);
      console.log(`Syncing: ${lib.name}`);
      console.log(`${"=".repeat(60)}`);

      const source = await fetchLibrarySource(session, lib);
      if (!source) {
        failureCount++;
        continue;
      }

      if (!validatePineSource(source, lib.name)) {
        failureCount++;
        continue;
      }

      const localPath = path.resolve(lib.local_path);
      const localDir = path.dirname(localPath);

      // Check if content changed
      let contentChanged = true;
      if (fs.existsSync(localPath)) {
        const existing = fs.readFileSync(localPath, "utf-8");
        contentChanged = existing !== source;
      }

      if (!contentChanged && !force) {
        console.log(`[${lib.name}] ✓ Already up-to-date, skipping.`);
        successCount++;
        continue;
      }

      if (!dryRun) {
        // Ensure directory exists
        fs.mkdirSync(localDir, { recursive: true });

        // Write file
        fs.writeFileSync(localPath, source, "utf-8");
        console.log(`[${lib.name}] ✓ Written to ${lib.local_path}`);
      } else {
        console.log(`[${lib.name}] [DRY-RUN] Would write ${source.length} bytes to ${lib.local_path}`);
      }

      successCount++;
    }

    console.log(`\n${"=".repeat(60)}`);
    console.log(`Sync Complete: ${successCount}/${LIBRARIES.length} succeeded`);
    if (failureCount > 0) {
      console.log(`⚠️  ${failureCount} libraries failed to sync`);
    }
    console.log(`${"=".repeat(60)}\n`);

    return failureCount === 0 ? 0 : 1;
  } catch (error: unknown) {
    const msg = error instanceof Error ? error.stack || error.message : String(error);
    console.error(`\n❌ Fatal error: ${msg}\n`);
    return 1;
  } finally {
    if (session) {
      await closeTradingViewSession(session);
    }
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main()
    .then((code) => process.exit(code))
    .catch((error: unknown) => {
      console.error(error instanceof Error ? error.stack || error.message : String(error));
      process.exit(1);
    });
}
