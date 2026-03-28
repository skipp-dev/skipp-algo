# v4 → v5 Enrichment Migration

> **This document has been superseded by [v5-enrichment-architecture.md](v5-enrichment-architecture.md).**
> Kept for reference — the v4 field set is a strict subset of v5.

---

## v4 Summary (historical)

The v4 library introduced **37 `export const` fields** across 7 sections (regime, news, calendar, layering, providers, volume, core+meta). The v5 architecture adds 14 event-risk fields for a total of **51 fields**.

## Migration Notes

- All v4 fields remain at their original positions — no renames.
- The `library_field_version` in the manifest is now `"v5"`.
- Secret names are unchanged: `FMP_API_KEY`, `BENZINGA_API_KEY`, `DATABENTO_API_KEY`, `TV_STORAGE_STATE`, `GH_PAT`.
- The `--enrich-all` CLI flag now includes `--enrich-event-risk` automatically.
- `SMCFMPClient` (in `scripts/smc_fmp_client.py`) is the runtime FMP adapter — `open_prep.macro.FMPClient` is no longer used in the generation path.
