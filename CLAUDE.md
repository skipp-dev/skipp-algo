# Claude Code Guidelines for skipp-algo

## Pine Library Maintenance

**Ownership:** @preuss_steffen  
**Cadence:** Bi-weekly (every Monday 09:00 UTC via GitHub Actions)  
**SLA:** Maximum 7 days behind TradingView source  
**Status:** 🟢 AUTOMATED (as of 2026-07-03)  
**Workflow:** `.github/workflows/sync-tradingview-pine-libraries.yml`

### Architecture

The sync pipeline is **fully automated** using the same authentication mechanism as the TradingView publishing process:

```
skipp-algo ←→ TradingView
  ↓
  Playwright + TV_STORAGE_STATE (same as publishing)
  ↓
  scripts/tv_fetch_smc_libraries.ts
  ↓
  SMC++/ + pine/generated/
```

**Key scripts:**
- `scripts/tv_fetch_smc_libraries.ts` — Playwright-based fetcher (handles auth + extraction)
- `scripts/check_pine_library_age.py` — SLA validation (runs in smc-fast-pr-gates.yml)
- `scripts/sync_tradingview_libraries.py` — Import validation (runs after fetch)

### Libraries Under Management

| Library | Type | Location | Status |
|---------|------|----------|--------|
| smc_profile_engine | Core | SMC++/ | 🔄 Auto-synced |
| smc_context_resolvers | Core | SMC++/ | 🔄 Auto-synced |
| smc_observability_private | Core | SMC++/ | 🔄 Auto-synced |
| smc_bus_private | Core | SMC++/ | 🔄 Auto-synced |
| smc_lifecycle_private | Core | SMC++/ | 🔄 Auto-synced |
| smc_overlay_generated | Generated | pine/generated/ | 🔄 Auto-synced |
| smc_micro_profiles_generated | Generated | pine/generated/ | 🔄 Auto-synced |

### Manual Trigger

To manually sync libraries outside the 2-week schedule:

```bash
# Via GitHub Actions (preferred)
gh workflow run sync-tradingview-pine-libraries.yml

# Command-line args
--force-update=true  # Update even if unchanged
```

### Freshness Monitoring

The `smc-fast-pr-gates.yml` workflow includes a **pine-library-freshness** job that fails CI if any library exceeds the 7-day SLA. Check `pine/LIBRARY_VERSIONS.toml` for current state.

### References

- **Audit report:** `pine/PINE_LIBRARIES_AUDIT.md`
- **Sync workflow:** `.github/workflows/sync-tradingview-pine-libraries.yml`
- **CI gate:** `.github/workflows/smc-fast-pr-gates.yml` (pine-library-freshness job)
- **Version tracking:** `pine/LIBRARY_VERSIONS.toml`

---

## Other Guidelines

(Add other CLAUDE.md sections as needed for the project)
