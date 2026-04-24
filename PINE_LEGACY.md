# Pine Script Status Index — Legacy vs. Active

> **Closes the D-1 backlog item** from
> [`docs/TEMPORAL_NUMERICAL_IMPROVEMENT_PLAN_2026-04-24.md`](docs/TEMPORAL_NUMERICAL_IMPROVEMENT_PLAN_2026-04-24.md)
> (Phase 1 — index-only; physical move stays open as D-1 v2).
>
> Audit-Befund (`/Users/steffenpreuss/Downloads/TEMPORAL_NUMERICAL_AUDIT_2026-04-24.md`):
> *"Legacy-Pine-Assets `QuickALGO.pine` (4732 LOC), `SkippALGO_Confluence.pine`
> (229 LOC) weiterhin im Root — 7 Dead Code, LOW, Aufräum-Arbeiten."*

## Why an index instead of a `git mv` to `pine/legacy/`?

A physical move was the audit's recommendation, but it has real blast
radius. The blockers fall into two tiers:

**Tier-1 — bare-filename lookup keys (architectural).** Several modules
resolve Pine files by **bare basename**, not by relative path:

- [`scripts/smc_bus_manifest.py`](scripts/smc_bus_manifest.py) —
  `SURFACE_DEFINITIONS[*].file` and the `NON_SMC_PINE_FILES` frozenset
  both store bare names (`'QuickALGO.pine'`, `'USI.pine'`, …).
- [`scripts/smc_file_lifecycle.py`](scripts/smc_file_lifecycle.py) —
  `EXPLICIT_OVERRIDES` and `SURFACE_MATRIX[*].name` use bare names;
  `classify_file(filename)` does dict lookup by basename.
- [`pine_apply_surface_reduction.py`](pine_apply_surface_reduction.py#L569)
  hard-codes `["QuickALGO.pine", "SkippALGO.pine", "SkippALGO_Strategy.pine"]`.

A physical move to `pine/legacy/` either (a) requires a sweeping
refactor of every consumer to use relative paths, or (b) needs a
path-resolution shim layer that recovers a file from its bare name.
Neither is a single-PR change — it deserves a mini-RFC.

**Tier-2 — verbatim references (mechanical sed scope).**

- [`test_usi_lint.py`](test_usi_lint.py#L78) defaults `sys.argv[1]` to
  `"USI.pine"`.
- [`README.md`](README.md), [`CHANGELOG.md`](CHANGELOG.md),
  [`docs/smc_product_map_2026-04-16.md`](docs/smc_product_map_2026-04-16.md)
  and several `docs/*.md` files reference the root paths verbatim.
- Operators may have **TradingView "saved scripts" with the root paths**
  recorded in their script-source URLs.

Tier-2 alone is mechanical; Tier-1 is the real blocker. The audit's
intent — *"klar als legacy markieren, separates Backlog"* — is
delivered by this index plus the drift-lint described below.

A future physical move stays an option (D-1 v2). When it happens, all
the consumers above must be updated atomically with the moves and the
bare-name lookup convention has to be either replaced or wrapped.

## Active SMC suite (DO NOT touch in legacy sweeps)

These are the canonical TradingView library + consumer files, pinned by
[`artifacts/tradingview/library_release_manifest.json`](artifacts/tradingview/library_release_manifest.json):

| File                              | Role          |
|-----------------------------------|---------------|
| `SMC_Core_Engine.pine`            | core engine   |
| `SMC_Dashboard.pine`              | consumer      |
| `SMC_Mobile_Dashboard.pine`       | consumer      |
| `SMC_Long_Strategy.pine`          | strategy      |
| `SkippALGO_Confluence.pine`       | consumer (active — see note below) |
| `SMC_Structure_Context.pine`      | overlay       |
| `SMC_Session_Context.pine`        | overlay       |
| `SMC_Profile_Context.pine`        | overlay       |
| `SMC_Orderflow_Overlay.pine`      | overlay       |
| `SMC_Liquidity_Structure.pine`    | overlay       |
| `SMC_Liquidity_Context.pine`      | overlay       |
| `SMC_Imbalance_Context.pine`      | overlay       |
| `SMC_HTF_Confluence.pine`         | overlay       |
| `SMC_Event_Overlay.pine`          | overlay       |
| `SMC_TV_Bridge.pine`              | bridge        |
| `SMC_Setup_Check.pine`            | diagnostic    |
| `pine/skipp_calibration.pine`     | library       |
| `pine/skipp_indicators.pine`      | library       |
| `pine/skipp_labels.pine`          | library       |
| `pine/skipp_math.pine`            | library       |
| `pine/skipp_scoring.pine`         | library       |
| `pine/generated/*`                | code-generated |

> **Note on `SkippALGO_Confluence.pine`**: the audit listed it as legacy,
> but it appears in the active consumer set in
> [`docs/freeze_exit_checklist_wp_f.md`](docs/freeze_exit_checklist_wp_f.md)
> and is referenced by `scripts/audit_library_consumers.py`. Status
> reclassified to **active**. If the audit was correct that it's
> dead, that needs a separate D-1 v2 verification PR before any move.

## Legacy / standalone (not in active SMC manifest)

Generated 2026-04-24 by enumerating root-level `*.pine` files that are
**not** in the SMC suite above. LOC measured at HEAD.

| File                                                        |  LOC | Status      | Notes                                          |
|-------------------------------------------------------------|-----:|-------------|------------------------------------------------|
| `QuickALGO.pine`                                            | 4732 | LEGACY      | v6.3.5 original signal engine; superseded by SMC suite |
| `BFI-Reversal.pine`                                         |  870 | LEGACY      | Breakout-Finder reversal variant               |
| `USI-CHOCH.pine`                                            |  796 | LEGACY      | USI + CHoCH hybrid                             |
| `CHOCH-Base_Strategy.pine`                                  |  760 | LEGACY      |                                                |
| `REV-Ladder.pine`                                           |  544 | LEGACY      |                                                |
| `VWAP_Reclaim_Strategy.pine`                                |  466 | LEGACY      |                                                |
| `REV-BUY.pine`                                              |  464 | LEGACY      |                                                |
| `VWAP_Reclaim_Indicator.pine`                               |  403 | LEGACY      |                                                |
| `USI_Strategy.pine`                                         |  355 | LEGACY      |                                                |
| `VWAP_Long_Reclaim_Strategy.pine`                           |  344 | LEGACY      |                                                |
| `CHOCH-Base_Indikator.pine`                                 |  344 | LEGACY      |                                                |
| `Breakout_Finder_Intelligent.pine`                          |  342 | LEGACY      |                                                |
| `VWAP_Long_Reclaim_Indicator.pine`                          |  330 | LEGACY      |                                                |
| `CHOCH-Strategy.pine`                                       |  324 | LEGACY      |                                                |
| `CHoCH.pine`                                                |  282 | LEGACY      | (note: `CHOCH.pine` case variant existed historically; not present at HEAD) |
| `BTC 3m EV Scalper BALANCED (Harmonized).pine`              |  242 | LEGACY      | space + parens in filename — handle with quoting |
| `USI_Lines.pine`                                            |  227 | LEGACY      |                                                |
| `CHOCH-Indicator.pine`                                      |  224 | LEGACY      |                                                |
| `USI.pine`                                                  |  209 | LEGACY      | also default of `test_usi_lint.py`             |
| `USI-REV-BUY.pine`                                          |  209 | LEGACY      |                                                |
| `USI-Flip.pine`                                             |  209 | LEGACY      |                                                |
| `REV-Ladder-CHoCH.pine`                                     |  157 | LEGACY      |                                                |
| `Volume_Weighted_Trend_SkippAlgo.pine`                      |   81 | LEGACY      |                                                |
| `test_div.pine`                                             |   ~ | TEST FIXTURE | not legacy — used by lint tests               |

**Total legacy LOC**: ~12 000 lines across 24 files.

## Policy

- **No new feature development** on files marked `LEGACY` above.
- **Bug-fix-only** for legacy files until a physical move (D-1 v2) is
  scheduled.
- **TradingView users** keep using existing saved scripts pointing at
  these paths — no breakage.
- **A future D-1 v2 PR** can do the physical move once
  `pine_apply_surface_reduction.py`, `test_usi_lint.py`, README,
  CHANGELOG, and docs/*.md are updated atomically.

## How this index is kept fresh

When adding a new `.pine` file at the repo root:

1. If it belongs to the SMC suite → add to the **Active SMC suite**
   table here AND to
   [`artifacts/tradingview/library_release_manifest.json`](artifacts/tradingview/library_release_manifest.json).
2. If it is a one-off / experiment → add to **Legacy / standalone**
   here with the LOC and a one-line note.

**Drift detection is enforced in CI.**
[`scripts/check_pine_legacy_drift.py`](scripts/check_pine_legacy_drift.py)
runs as part of [`smc-fast-pr-gates`](.github/workflows/smc-fast-pr-gates.yml)
and fails the build whenever:

- A root-level `*.pine` file is missing from this index, **or**
- A file mentioned in this index is missing from the repo root.
