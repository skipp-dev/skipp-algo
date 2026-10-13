# Pine Script Libraries Audit & Update Strategy

**Date:** 2026-07-03 (original) · **Updated:** 2026-07-11  
**Status:** ✅ RESOLVED by decision — repo is SSOT; the TV→repo sync was removed.

> **⚠️ SUPERSEDED (2026-07-11).** This report assumed TradingView is *upstream* and the
> repo must "sync down" — that premise is wrong for this codebase. The repo is the
> **single source of truth**; publishing is **repo→TV only** (`scripts/tv_publish_*_library.ts`
> plus `smc-library-refresh.yml` / `smc-overlay-library-publish.yml`). "Days behind
> TradingView" is therefore **not a meaningful metric** — TV is downstream. The TV→repo
> sync workflow, its Playwright fetcher (`scripts/tv_fetch_smc_libraries.ts`), and the
> 7-day `pine-library-freshness` CI job (`check_pine_library_age.py`) were **removed**.
> The staleness table below is kept for history only — ignore its STALE/CRITICAL
> verdicts. See CLAUDE.md → "Pine Library Maintenance". The *separate* 120-day
> `pine-library-freshness.yml` (hand-authored `pine/skipp_*.pine`) is unaffected.

---

## Executive Summary

| Library | TradingView Last Update | Local Last Sync | Days Behind | Status |
|---------|------------------------|-----------------|-------------|--------|
| smc_overlay_generated | Jun 9 | Jun 10 | ✅ 1 day (OK) | Current |
| smc_profile_engine | Apr 16 | Jun 10 | ⚠️ 55 days | **STALE** |
| smc_context_resolvers | Apr 16 | Jun 10 | ⚠️ 55 days | **STALE** |
| smc_observability_private | Apr 5 | Jun 10 | ⚠️ 59 days | **CRITICAL** |
| smc_bus_private | Apr 16 | Jun 10 | ⚠️ 55 days | **STALE** |
| smc_lifecycle_private | Unknown | Jun 10 | ❌ Unknown | **STALE** |
| smc_micro_profiles_generated | Jun 15 | Jun 15 | ✅ 0 days (OK) | Current |

---

## Library Usage in skipp-algo

### Critical Path (Production)

**SMC_Long_Dip_Suite.pine** (master strategy)
```pine
import preuss_steffen/smc_lifecycle_private/1 as ll  // ⚠️ STALE
import preuss_steffen/smc_bus_private/1 as bp         // ⚠️ STALE
import preuss_steffen/smc_observability_private/1 as obv  // ⚠️ CRITICAL
import preuss_steffen/smc_context_resolvers/1 as cr   // ⚠️ STALE
import preuss_steffen/smc_profile_engine/1 as pe      // ⚠️ STALE
```

**Risk:** Core engine may be operating on outdated signal resolvers, context logic, and profile calculations.

### Secondary Path (Dashboards/Overlays)

- `SMC_Hold_Manager.pine` → references smc_lifecycle (comments only, no import)
- `SMC_Long_Dip_Dashboard.pine` → may depend on smc_profile_engine
- `SMC_Liquidity_Structure.pine` → depends on smc_context_resolvers

### Generated (Auto-Maintained)

- ✅ `smc_overlay_generated.pine` — 1 day behind (acceptable)
- ✅ `smc_micro_profiles_generated.pine` — current

---

## Root Cause Analysis

### Why Did Sync Fail 3-4 Weeks Ago?

**Expected:** PR should have updated SMC++ libraries as part of the "regular refresh"  
**Actual:** Pin-registry entries show last library update was 2026-06-10  
**Evidence:**
```
File                                  Modified
─────────────────────────────────────────────
SMC++/smc_bus_private.pine           Jun 10 15:55
SMC++/smc_context_resolvers.pine     Jun 10 15:55
SMC++/smc_lifecycle_private.pine     Jun 10 15:55
SMC++/smc_observability_private.pine Jun 10 15:55
SMC++/smc_profile_engine.pine        Jun 10 15:55
```

**Hypothesis:** A scheduled PR or manual update was planned for ~2026-06-24 but never executed. The TradingView libraries were updated (Apr 5 → Jun 9 progression visible), but sync broke.

---

## Impact Assessment

### Potential Issues from Stale Libraries

1. **smc_lifecycle_private** (armed/confirm/ready state machine)
   - 55+ days behind
   - If TradingView updated signal freshness gates, early-exit logic, or invalidation thresholds → Core_Engine still uses old gating
   - **Risk:** Missed entries, false triggers, stale signal handling

2. **smc_observability_private** (debug/event logging)
   - 59 days behind (CRITICAL)
   - Debug mode might be logging incorrect state or missing new event types
   - **Risk:** Silent failures, undetectable bugs in signal routing

3. **smc_bus_private** (packed row state, meta-encoding)
   - 55+ days behind
   - If row state schema changed, bus messages misaligned with dashboard parsing
   - **Risk:** Dashboard displays wrong colors, signal quality scores corrupt

4. **smc_context_resolvers** (composed text, blocker codes)
   - 55+ days behind
   - If resolver logic for "ready_blocker_code" or "strict_blocker_code" changed, misleading alerts
   - **Risk:** Trader sees "ready" but system disagrees internally

5. **smc_profile_engine** (volume profile rendering)
   - 55+ days behind
   - Profile lines might not draw or POC/VAH calculations drift
   - **Risk:** Visual analysis incomplete, volume data unreliable

---

## Solution: Automated Library Sync Pipeline

### 1. **Establish TradingView Sync Mechanism**

Currently **manual** → **should be automated**

**Option A: Web Scraper (TradingView public library pages)**
```python
# scripts/sync_tradingview_libraries.py
import requests
from bs4 import BeautifulSoup

LIBRARIES = {
    "smc_overlay_generated": "preuss_steffen/smc_overlay_generated/1",
    "smc_profile_engine": "preuss_steffen/smc_profile_engine/1",
    "smc_context_resolvers": "preuss_steffen/smc_context_resolvers/1",
    "smc_observability_private": "preuss_steffen/smc_observability_private/1",
    "smc_bus_private": "preuss_steffen/smc_bus_private/1",
    "smc_lifecycle_private": "preuss_steffen/smc_lifecycle_private/1",
}

def fetch_library_metadata(user, lib_name, version):
    """Scrape TradingView library page for last-update date."""
    url = f"https://www.tradingview.com/script/{user.lower()}{lib_name.lower()}{version}/"
    # Parse last-update timestamp
    ...

def check_library_updates():
    """Check which libraries have been updated since last sync."""
    ...
```

**Option B: Manual Check + Git Hook**
```bash
# .githooks/pre-push
# Warn if SMC++ files unchanged for >30 days
find SMC++/ -name "*.pine" -mtime +30 -exec echo "WARNING: {} not updated in 30+ days" \;
```

### 2. **Scheduled Sync (CI Job)**

**File: `.github/workflows/sync-tradingview-libraries.yml`**

```yaml
name: Sync TradingView SMC Libraries

on:
  schedule:
    # Every 2 weeks on Monday 09:00 UTC
    - cron: '0 9 * * 1'
  workflow_dispatch:  # Manual trigger

jobs:
  sync:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Fetch library updates from TradingView
        run: |
          python scripts/sync_tradingview_libraries.py \
            --output-dir SMC++ \
            --libraries smc_profile_engine,smc_context_resolvers,smc_lifecycle_private,smc_bus_private,smc_observability_private
      
      - name: Check for changes
        id: diff
        run: |
          git diff --quiet SMC++ || echo "changes=true" >> $GITHUB_OUTPUT
      
      - name: Create PR if updated
        if: steps.diff.outputs.changes == 'true'
        run: |
          git config user.name "Skipp-Algo Library Sync"
          git config user.email "automation@skipp-algo.local"
          git checkout -b chore/sync-tradingview-libraries-$(date +%s)
          git add SMC++/*.pine
          git commit -m "chore(pine): sync TradingView SMC libraries — \$(date +%F)"
          git push origin HEAD
          gh pr create \
            --title "chore(pine): sync TradingView SMC libraries" \
            --body "Auto-sync from TradingView library sources. Review for breaking changes in signal resolvers, state machines, or bus encoding." \
            --label "pine-libraries" \
            --auto-merge
```

### 3. **Validation: Syntax + Import Check**

**File: `scripts/validate_pine_libraries.py`**

```python
import re

def validate_pine_imports(pine_file):
    """Ensure all @imports reference existing libraries."""
    with open(pine_file, 'r') as f:
        content = f.read()
    
    # Find all imports
    imports = re.findall(r'import\s+(\S+)\s+as\s+(\w+)', content)
    
    for lib_path, alias in imports:
        user, lib_name, version = lib_path.split('/')
        expected_file = f"SMC++/{lib_name}.pine"
        
        if not os.path.exists(expected_file):
            raise ImportError(f"{pine_file} imports {lib_path}, but {expected_file} not found")
        
        # Validate library header
        with open(expected_file, 'r') as lib:
            if f'library("{lib_name}"' not in lib.read():
                raise ValueError(f"{expected_file} does not export library '{lib_name}'")

def main():
    pine_files = glob.glob("*.pine") + glob.glob("SMC_Long_Dip_Suite.pine")
    for pf in pine_files:
        validate_pine_imports(pf)
    print("✅ All Pine imports valid")
```

**Add to CI:**
```yaml
- name: Validate Pine library imports
  run: python scripts/validate_pine_libraries.py
```

### 4. **Library Version Tracking**

**File: `pine/LIBRARY_VERSIONS.toml`**

```toml
[libraries]
smc_overlay_generated = { version = "1", tradingview_updated = "2026-06-09", local_synced = "2026-06-10" }
smc_profile_engine = { version = "1", tradingview_updated = "2026-04-16", local_synced = "2026-06-10", days_behind = 55 }
smc_context_resolvers = { version = "1", tradingview_updated = "2026-04-16", local_synced = "2026-06-10", days_behind = 55 }
smc_observability_private = { version = "1", tradingview_updated = "2026-04-05", local_synced = "2026-06-10", days_behind = 59 }
smc_bus_private = { version = "1", tradingview_updated = "2026-04-16", local_synced = "2026-06-10", days_behind = 55 }
smc_lifecycle_private = { version = "1", tradingview_updated = "unknown", local_synced = "2026-06-10", days_behind = "?" }
smc_micro_profiles_generated = { version = "1", tradingview_updated = "2026-06-15", local_synced = "2026-06-15", days_behind = 0 }

[changelog]
# 2026-07-03: Audit found 55-59 day stale libraries; scheduled bi-weekly sync + automated validation
# 2026-06-10: Last manual sync (missed updates from Apr 5-16)
```

### 5. **Maintenance SLA**

| Metric | Target | Current | Status |
|--------|--------|---------|--------|
| Max library age | 7 days | 55-59 days | ❌ BREACH |
| Sync frequency | Bi-weekly | Manual (broken) | ❌ BROKEN |
| Import validation | Per-commit | Not automated | ❌ MISSING |
| Changelog tracking | Per-update | Ad-hoc | ⚠️ PARTIAL |

---

## Immediate Actions (Today)

### 1. **Emergency: Manual Sync**

```bash
# Download current versions from TradingView
# (Requires manual copy-paste from TradingView UI or API token)

# For each library:
# 1. Open https://www.tradingview.com/script/preuss_steffen{lib_name}/1/
# 2. Copy full source code
# 3. Save to SMC++/{lib_name}.pine
# 4. Commit with message: "chore(pine): manual sync {lib_name} from TradingView"
```

### 2. **Deploy Sync Automation** (1 day)

- Create `.github/workflows/sync-tradingview-libraries.yml`
- Add `scripts/sync_tradingview_libraries.py`
- Add validation checks to `scripts/validate_pine_libraries.py`
- Update `pine/LIBRARY_VERSIONS.toml` with current metadata

### 3. **Update CI Pipeline** (2 hours)

```yaml
# In .github/workflows/smc-fast-pr-gates.yml
- name: Check Pine library freshness
  run: |
    python scripts/check_library_age.py --max-days=7 --fail-on-breach
```

### 4. **Document in CLAUDE.md** (30 min)

```markdown
## Pine Library Maintenance

**Responsible:** @preuss_steffen
**Cadence:** Bi-weekly (every Monday 09:00 UTC)
**SLA:** Max 7 days behind TradingView source
**Status:** 🔴 CRITICAL — currently 55-59 days behind

To sync libraries manually:
1. Open each TradingView library link
2. Copy source → SMC++/{name}.pine
3. Create PR with label `pine-libraries`

Automated sync runs every 2 weeks via GitHub Actions.
```

---

## References

- **Pin Registry:** `pin_registry.toml` (tracks library import line numbers)
- **Import Validation:** `tests/test_pine_input_surface.py` (verifies library contracts)
- **TradingView Library Links:**
  - https://www.tradingview.com/script/preuss_steffensmc_overlay_generated/1/
  - https://www.tradingview.com/script/preuss_steffensmc_profile_engine/1/
  - https://www.tradingview.com/script/preuss_steffensmc_context_resolvers/1/
  - https://www.tradingview.com/script/preuss_steffensmc_observability_private/1/
  - https://www.tradingview.com/script/preuss_steffensmc_bus_private/1/
  - https://www.tradingview.com/script/preuss_steffensmc_lifecycle_private/1/
