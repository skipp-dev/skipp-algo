# Claude Code Guidelines for skipp-algo

## Pine Library Maintenance

**Ownership:** @preuss_steffen  
**Cadence:** Weekly (every Monday 09:00 UTC via GitHub Actions — cron `0 9 * * 1`)  
**SLA:** Maximum 7 days behind TradingView source (currently unenforceable — see Status)  
**Status:** 🔴 BROKEN — the sync workflow has never completed a successful run (missing Node/Playwright setup steps; the fetch script exits 1 on `smc_overlay_generated`'s null `script_url`). Wire-or-remove decision pending (truth-audit 2026-07-10).  
**Workflow:** `.github/workflows/sync-tradingview-pine-libraries.yml`

### Architecture

The sync pipeline was designed to be fully automated using the same authentication mechanism as the TradingView publishing process, but has never worked (see Status):

```
skipp-algo ←→ TradingView
  ↓
  Playwright + TV_STORAGE_STATE (same as publishing)
  ↓
  scripts/tv_fetch_smc_libraries.ts
  ↓
  SMC++/ + pine/generated/
```

**Direction of truth:** the repo is the source of truth for ALL libraries — `scripts/tv_publish_*_library.ts` publish repo→TV for the five core SMC++ libraries, and the two `pine/generated/` libraries are regenerated in-repo and published repo→TV by `smc-library-refresh.yml` / `smc-overlay-library-publish.yml`. A working TV→repo fetch would fight those publishers over the same files.

**Key scripts:**
- `scripts/tv_fetch_smc_libraries.ts` — Playwright-based fetcher (handles auth + extraction; currently always exits 1, see Status)
- `scripts/check_pine_library_age.py` — SLA validation (runs in smc-fast-pr-gates.yml)
- `scripts/sync_tradingview_libraries.py` — local validation only (Pine syntax + import existence; fetches and writes nothing)

### Libraries Under Management

| Library | Type | Location | Status |
|---------|------|----------|--------|
| smc_profile_engine | Core | SMC++/ | ⛔ Sync never ran |
| smc_context_resolvers | Core | SMC++/ | ⛔ Sync never ran |
| smc_observability_private | Core | SMC++/ | ⛔ Sync never ran |
| smc_bus_private | Core | SMC++/ | ⛔ Sync never ran |
| smc_lifecycle_private | Core | SMC++/ | ⛔ Sync never ran |
| smc_overlay_generated | Generated | pine/generated/ | 🔁 Repo→TV (generated in-repo) |
| smc_micro_profiles_generated | Generated | pine/generated/ | 🔁 Repo→TV (generated in-repo) |

### Manual Trigger

To manually trigger the sync workflow outside the weekly schedule (note: currently fails, see Status):

```bash
# Via GitHub Actions (preferred)
gh workflow run sync-tradingview-pine-libraries.yml

# Optional: force update even if unchanged (workflow_dispatch input)
gh workflow run sync-tradingview-pine-libraries.yml -f force_update=true
```

### Freshness Monitoring

The `smc-fast-pr-gates.yml` workflow includes a **pine-library-freshness** job (not in the required-checks set — only `fast-gates` is required) that fails when any `pine/LIBRARY_VERSIONS.toml` entry's `local_synced` date exceeds the 7-day SLA. No automation updates those dates (all frozen at 2026-07-03), so the job breaches from 2026-07-11 onward until the wire-or-remove decision lands. Not to be confused with the standalone `pine-library-freshness.yml` workflow, which guards the five hand-authored `pine/skipp_*.pine` libraries on a 120-day/monthly cadence.

### References

- **Audit report:** `pine/PINE_LIBRARIES_AUDIT.md`
- **Sync workflow:** `.github/workflows/sync-tradingview-pine-libraries.yml`
- **CI gate:** `.github/workflows/smc-fast-pr-gates.yml` (pine-library-freshness job)
- **Version tracking:** `pine/LIBRARY_VERSIONS.toml`

---

## Other Guidelines

(Add other CLAUDE.md sections as needed for the project)
