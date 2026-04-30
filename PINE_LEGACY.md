# Pine Script Status Index — Legacy vs. Active

> **Closes the D-1 backlog item** (Phase 1, index) and the **D-1 v2**
> follow-up (Phase 2, physical move + resolver shim per
> [ADR-0003](docs/adr/0003-pine-legacy-physical-move-resolver.md)) from
> [`docs/TEMPORAL_NUMERICAL_IMPROVEMENT_PLAN_2026-04-24.md`](docs/TEMPORAL_NUMERICAL_IMPROVEMENT_PLAN_2026-04-24.md).
>
> Audit-Befund (`/Users/steffenpreuss/Downloads/TEMPORAL_NUMERICAL_AUDIT_2026-04-24.md`):
> *"Legacy-Pine-Assets `QuickALGO.pine` (4732 LOC), `SkippALGO_Confluence.pine`
> (229 LOC) weiterhin im Root — 7 Dead Code, LOW, Aufräum-Arbeiten."*

## Physical layout (D-1 v2 — ADR-0003 resolver shim)

LEGACY `*.pine` files now live under `pine/legacy/`. Active SMC suite
files stay at the repo root (no TradingView saved-script breakage for
active consumers). `SkippALGO_Confluence.pine` and `test_div.pine` stay
at the root — the former is reclassified as active, the latter is a
test fixture.

Consumers that resolve Pine files **by bare basename** —
[`scripts/smc_bus_manifest.py`](scripts/smc_bus_manifest.py),
[`scripts/smc_file_lifecycle.py`](scripts/smc_file_lifecycle.py),
[`pine_apply_surface_reduction.py`](pine_apply_surface_reduction.py),
[`test_usi_lint.py`](test_usi_lint.py) — either continue to use
basenames as **lookup keys** (lifecycle/manifest classifiers) or open
the file via
[`scripts/pine_path_resolver.resolve_pine_file`](scripts/pine_path_resolver.py)
(file-opening sites). The resolver searches root then `pine/legacy/`
and fails on collision.

Drift-lint enforces the layout in CI: every `*.pine` file in either
root or `pine/legacy/` must be indexed below, and no basename may
appear in both locations — see
[`scripts/check_pine_legacy_drift.py`](scripts/check_pine_legacy_drift.py).

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
| `SMC_Breakout_Overlay.pine`       | overlay       |
| `SMC_VRVP_Overlay.pine`           | overlay       |
| `SMC_Exit_Signal.pine`            | consumer      |
| `SMC_Hold_Manager.pine`           | consumer      |
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
