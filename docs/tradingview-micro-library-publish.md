# TradingView Micro Library Publish

This runbook closes the gap between local microstructure generation and the hard import in SMC Core.

## Contract

The generated library contract has three authoritative artifacts:

- Manifest: pine/generated/smc_micro_profiles_generated.json
- Import snippet: pine/generated/smc_micro_profiles_core_import_snippet.pine
- Core consumer: SMC_Core_Engine.pine

The TradingView release tracking artifact is:

- artifacts/tradingview/library_release_manifest.json

The import path must stay identical in all three places.

## Local Refresh

Regenerate the base and library artifacts from the checked-in snapshot or a fresh Databento bundle.

Snapshot path:

```bash
./.venv/bin/python scripts/generate_smc_micro_profiles.py \
  --schema schema/schema.json \
  --input data/input/microstructure_base_snapshot_2026-03-23.csv \
  --overrides data/input/microstructure_overrides.csv \
  --output-root .
```

Bundle or workbook path:

```bash
./.venv/bin/python scripts/generate_smc_micro_base_from_databento.py <bundle-or-workbook>
```

## Contract Check

Run the contract verifier before any TradingView publish step:

```bash
npm run smc:verify-micro-publish
```

This verifies:

- the manifest recommended import path
- the first import line in the generated snippet
- the actual import used by SMC_Core_Engine.pine
- the generated alias block copied into the core file in the same order

## TradingView Publish

Preferred path:

1. Generate the base and Pine library artifacts from the Streamlit base-generator UI.
2. Use the UI button `Publish To TradingView` to run the contract check, publish the generated library, and run the post-publish core validation.
3. Review `artifacts/tradingview/library_release_manifest.json` and the emitted publish report for the final release status.

The automated publish report now distinguishes two separate facts:

- `publishedScriptVerified`: the TradingView library script could be reopened after publish
- `publishVerificationMode`: publish proof is only release-green when the reopened script identity matches exactly in canonical editor context and that same context proves the expected version; `body_fallback` is diagnostic only and fails closed
- `repoCoreValidationReport`: the local repo core consumer was revalidated in mutating preflight mode after publish

Legacy note:

- `scripts/99_full_release.ts` is intentionally reduced to a hard-fail stub and is not a supported release path.

Fallback manual path:

1. Open pine/generated/smc_micro_profiles_generated.pine in TradingView as a library script.
2. Publish it under the owner and version declared in pine/generated/smc_micro_profiles_generated.json.
3. Keep the import path unchanged unless you intentionally bump owner or version.
4. If owner or version changes, regenerate the library artifacts first, then rerun the contract verifier.

Version handling stays explicit. The core import path does not auto-resolve the newest library version in TradingView. If you change owner or version, regenerate the artifacts first and treat that version selection as an operator decision.

## Runtime Validation

After the library is published:

1. Capture or refresh TradingView auth state with npm run tv:storage-state.
2. Run npm run tv:preflight for the mutating repo-source compile/save/input validation path.
3. Run npm run tv:smoke-readonly when you want a non-writing smoke pass against the already-saved TradingView scripts.
4. Use npm run tv:publish-micro-library for the only supported automated TradingView publish path.

The auth capture step should only be considered valid if it finishes without the anonymous-session guard. A storage-state file containing only generic cookies can still open TradingView pages, but it will usually cause chart/login oscillation and false runtime failures.

The repo-side guardrail is the contract verifier plus the generated manifest.

The release manifest under `artifacts/tradingview/library_release_manifest.json` records the expected import path, expected version, published version, last referenced preflight report, and whether the current status is still manual, not yet verified, or fully published.
