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

The manifest carries `library_field_version: "v5.5b"` and lists all active `enrichment_blocks`.
When broad v5/v5.1-v5.3 enrichment is present, the generator normalizes the
six v5.5b lean blocks before export so the Pine artifact and manifest stay in sync.

## v5.5b Library Field Contract

The generated Pine library exports the full compatibility surface used by
SMC_Core_Engine.pine: legacy v5-v5.3 fields remain available, and the
preferred v5.5b lean surface is exported alongside them.

Preferred lean families:

- Event Risk Light: 7 fields
- Session Context Light: 5 fields
- Order Block Context Light: 5 fields
- FVG / Imbalance Lifecycle Light: 6 fields
- Structure State Light: 4 fields
- Signal Quality: 5 fields

The executable contract is defined by the generator output under
`pine/generated/` plus the consumer-contract tests in
`tests/test_pine_consumer_contract.py`, not by a fixed field-count number in this runbook.

## Local Refresh

### Manual Streamlit Path

The Streamlit base-generator UI is the preferred manual path. It orchestrates enrichment collection, base scan, library generation, and publish in a single session:

```bash
streamlit run streamlit_smc_micro_base_generator.py
```

1. Configure Databento + FMP API keys in the sidebar.
2. Click `Run SMC Base Scan` to generate the base snapshot.
3. Click `Generate Pine Library` — this produces the v5.5b library surface with normalized lean blocks and any selected enrichment data from FMP/Benzinga.
4. Review the manifest contract in the UI.
5. Click `Publish To TradingView` when the publish guard is green.

### Automated Refresh Path

The GitHub Actions workflow `.github/workflows/smc-library-refresh.yml` runs 4x per trading day (12:30/14:30/16:30/18:30 UTC). Each run:

1. Generates the base + v5.5b enrichment library via `scripts/generate_smc_micro_base_from_databento.py --run-scan --enrich-all`
2. Runs evidence gate tests
3. Detects whether the library content changed
4. Publishes to TradingView only when changed
5. Commits the updated artifacts and bumps the core import version
6. Evaluates signal alerts (regime changes, macro events, provider degradation)

### CLI Snapshot Path (base-only, no enrichment)

Regenerate from a checked-in snapshot without enrichment data:

```bash
./.venv/bin/python scripts/generate_smc_micro_profiles.py \
  --schema schema/schema.json \
  --input data/input/microstructure_base_snapshot_2026-03-28.csv \
  --overrides data/input/microstructure_overrides.csv \
  --output-root .
```

This produces a valid 37-field library with safe neutral defaults for all enrichment fields.

### Bundle or Workbook Path

```bash
./.venv/bin/python scripts/generate_smc_micro_base_from_databento.py <bundle-or-workbook>
```

### Checked-in Artifact Refresh

The three artifacts under `pine/generated/` are version-controlled reference
outputs generated from a deterministic seed fixture.  After any change to
the generator code, refresh them:

```bash
python -m scripts.refresh_generated_artifacts
```

This runs `run_generation()` against `tests/fixtures/seed_base_snapshot.csv`
with `enrichment=None` and overwrites:

- `pine/generated/smc_micro_profiles_generated.pine`
- `pine/generated/smc_micro_profiles_generated.json`
- `pine/generated/smc_micro_profiles_core_import_snippet.pine`

Commit the updated artifacts.  The anti-drift test
`tests/test_generated_artifact_drift.py` fails if checked-in artifacts
diverge from the generator output.

## Contract Check

Run the contract verifier before any TradingView publish step:

```bash
npm run smc:verify-micro-publish
```

This verifies:

- the manifest recommended import path
- the first import line in the generated snippet
- the actual import used by SMC_Core_Engine.pine
- the generated alias block copied into the core file in the same order and exactly once as real contiguous code

## TradingView Publish

Preferred path:

1. Generate the base and Pine library artifacts from the Streamlit base-generator UI.
2. Use the UI button `Publish To TradingView` to run the contract check, publish the generated library, and run the post-publish core validation.
3. Review `artifacts/tradingview/library_release_manifest.json` and the emitted publish report for the final release status.

`tv:publish-micro-library` now applies the same hard open-existing requirement as preflight before any editor mutation. If the exact target script cannot be reopened first, the publish run aborts before writing to the editor and records the attempt as an automation failure rather than a manual-publish state.

The automated publish report now distinguishes two separate facts:

- `publishedScriptVerified`: the TradingView library script could be reopened after publish
- `identityVerificationMode`: exact reopened script identity from canonical editor context
- `versionVerificationMode`: version proof from dedicated exact script-bound version UI context; `body_fallback` is diagnostic only and fails closed
- `repoCoreValidationReport`: the local repo core consumer was revalidated in mutating preflight mode after publish

Settings-opening automation is also fail-closed: if the visible settings dialog cannot prove the exact target script from its title, the run aborts instead of accepting an unidentified dialog.

`--no-open-existing` remains a deliberate Sonderpfad for a fresh untitled draft and is not treated as the default hardened release path.

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

## Alert Secrets

The automated refresh workflow fires alerts when enrichment state changes (e.g. MARKET_REGIME → RISK_OFF, TRADE_STATE → BLOCKED, provider degradation). Two channels are supported:

| Secret | Purpose |
|--------|---------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token for alert delivery |
| `TELEGRAM_CHAT_ID` | Telegram chat/channel ID |
| `SMTP_HOST` | SMTP server hostname for email alerts |
| `SMTP_USER` | SMTP login username |
| `SMTP_PASS` | SMTP login password |
| `ALERT_EMAIL_FROM` | Sender address |
| `ALERT_EMAIL_TO` | Recipient address |

Both channels are optional. Alerts can also be run locally:

```bash
./.venv/bin/python scripts/smc_alert_notifier.py \
  --library pine/generated/smc_micro_profiles_generated.pine \
  --state-file artifacts/ci/alert_last_state.json \
  --provider-alerts \
  --dry-run
```

## TradingView Publish Expectations

After a successful publish:

1. The TradingView library must contain exactly 37 `export const` fields.
2. The manifest `library_field_version` must be `"v4"`.
3. SMC_Core_Engine.pine reads 15 of the 37 fields via `mp.FIELD`.
4. Dashboard and Strategy consume data only via BUS channels (26 and 8 respectively) — they never import the library directly.
5. If any enrichment provider fails, the library still contains all 37 fields with safe neutral defaults.
