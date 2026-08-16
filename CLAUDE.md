# Claude Code Guidelines for skipp-algo

## Core Working Rules (apply to every agent/session)

**No unverified assumptions.** Every assumption, caveat, or "maybe / probably / could / should"
claim about anything *checkable* must be verified **before** you state it, and resolved into
exactly one of three outcomes:

1. **TRUE** — with concrete evidence (command output, grep/rg hit, live probe, test, log, endpoint response).
2. **FALSE** — with concrete evidence disproving it.
3. **→ follow-up PR** — when the check surfaces a problem that must be fixed.

Checkable means checkable with the tools/access at hand (repo, `railway` CLI, `.env` keys,
endpoints, live probes, tests). Only *genuinely uncheckable* things may remain as residual
risk — and then say so explicitly ("not verifiable because …"), never as a casual "maybe".
This applies especially to post-merge ops dependencies (env vars, deploy pickup, secrets) and
to regression/behavior claims.

**Forward promises need a mechanism.** The rule above covers claims about the present;
this extends it to the future tense, where the same failure hid (added 2026-08-16 after
operator escalation). A sentence of the form "when X happens, Y must be done" — in an
issue, a PR body, a memory note, a report, or a doc — is a **forward promise**. Prose does
not fire at X: nothing in any flow re-reads it at the right moment, and this repo's
history shows such promises rot silently (#4756 before #4762 mechanised it; the vacuity
sweeps dug out a row of dead ones; every stale "verified YYYY-MM-DD"). Before writing a
forward promise, resolve it into exactly one of:

1. **Mechanism in the same change** — a tripwire on the required path that goes red at X
   (template: `tests/test_pine_const_getter_migration_tripwire.py`, one test file), a
   scheduled check, or a gate. The prose then *summarises* the mechanism.
2. **Live ownership** — Y is happening now: a PR in flight, a cron that does Y itself.
3. **Explicitly unsecured** — write "UNGESICHERT — verlässt sich auf menschliches
   Gedächtnis" next to the promise. Allowed, but the label is mandatory, so no reader
   mistakes prose for protection.

A follow-up **issue alone is not a resolution** — an issue is prose with a number. This
binds every agent session working in this repo, parallel sessions included.

## Pine Library Maintenance

**Ownership:** @preuss_steffen  
**Direction of truth:** the repo is the **single source of truth** for ALL Pine libraries. Publishing is **repo → TradingView only** — `scripts/tv_publish_*_library.ts` push the hand-authored `SMC++/` libraries, and the two `pine/generated/` libraries are regenerated in-repo and published by `smc-library-refresh.yml` / `smc-overlay-library-publish.yml`.

### No TV→repo sync (removed 2026-07-11)

There is **no** TradingView→repo sync, by design. The old `sync-tradingview-pine-libraries.yml` workflow (a weekly Playwright scrape of the TV Pine Editor into `SMC++/` + `pine/generated/`) was removed because it was architecturally backwards and never worked:

- **Wrong direction.** With the repo as SSOT it would fetch back exactly what the repo→TV publishers just pushed, and any TV-side edit would clobber the repo's authored/generated source. It fought the publishers over the same files.
- **Never ran green.** The Playwright fetch scraped source from the Pine Editor DOM and exited 1 on `smc_overlay_generated` (null `script_url`).
- **Its freshness gate was a structural false-red.** The removed `pine-library-freshness` **job** in `smc-fast-pr-gates.yml` failed any PR whose `pine/LIBRARY_VERSIONS.toml` `local_synced` date exceeded a 7-day SLA — but nothing ever stamped `local_synced` (the sync never wrote it), so from 2026-07-11 it breached on **every** PR. It was non-required (only `fast-gates` gates merges).

Removed 2026-07-11: `.github/workflows/sync-tradingview-pine-libraries.yml`, `scripts/tv_fetch_smc_libraries.ts`, `scripts/check_pine_library_age.py`, and the `pine-library-freshness` job in `smc-fast-pr-gates.yml`. The unread `pine/LIBRARY_VERSIONS.toml` metadata artifact was removed separately on 2026-07-15.

**Still present (unaffected):**
- `scripts/tv_publish_*_library.ts` — repo→TV publishers (the real, working direction).
- `smc-library-refresh.yml` / `smc-overlay-library-publish.yml` — regenerate + publish the two generated libraries.
- `scripts/sync_tradingview_libraries.py` — standalone **local** validator (Pine syntax + import existence; fetches/writes nothing); no longer invoked by any workflow.
- `.github/workflows/pine-library-freshness.yml` — SEPARATE and unaffected: guards the five hand-authored `pine/skipp_*.pine` libraries on a 120-day/monthly cadence (not the code-generated `SMC++/` set).

### Libraries

| Library | Type | Location | Published by |
|---------|------|----------|--------------|
| smc_profile_engine | Core | SMC++/ | `tv_publish_*` (repo→TV) |
| smc_context_resolvers | Core | SMC++/ | `tv_publish_*` (repo→TV) |
| smc_observability_private | Core | SMC++/ | `tv_publish_*` (repo→TV) |
| smc_bus_private | Core | SMC++/ | `tv_publish_*` (repo→TV) |
| smc_lifecycle_private | Core | SMC++/ | `tv_publish_*` (repo→TV) |
| smc_engine_private | Core | SMC++/ | `tv_publish_engine_library.ts` (repo→TV) |
| smc_overlay_generated | Generated | pine/generated/ | `smc-overlay-library-publish.yml` |
| smc_micro_profiles_generated | Generated | pine/generated/ | `smc-library-refresh.yml` |

### References

- **Audit report:** `pine/PINE_LIBRARIES_AUDIT.md`
- **Publishers:** `scripts/tv_publish_*_library.ts`; `smc-library-refresh.yml` / `smc-overlay-library-publish.yml`
- **Hand-authored-lib freshness (separate):** `.github/workflows/pine-library-freshness.yml`

---

## Other Guidelines

(Add other CLAUDE.md sections as needed for the project)
