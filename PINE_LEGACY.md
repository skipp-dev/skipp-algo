# Pine Script Status Index — Legacy vs. Active

> **Closes the D-1 backlog item** (Phase 1, index) and the **D-1 v2**
> follow-up (Phase 2, physical move + resolver shim per
> [ADR-0003](docs/adr/0003-pine-legacy-physical-move-resolver.md)) from
> [`docs/TEMPORAL_NUMERICAL_IMPROVEMENT_PLAN_2026-04-24.md`](docs/TEMPORAL_NUMERICAL_IMPROVEMENT_PLAN_2026-04-24.md).
>
> Audit-Befund (`/Users/steffenpreuss/Downloads/TEMPORAL_NUMERICAL_AUDIT_2026-04-24.md`):
> *"Legacy-Pine-Assets `QuickALGO.pine` (4732 LOC), `SMC_Confluence_Hub.pine`
> (229 LOC) weiterhin im Root — 7 Dead Code, LOW, Aufräum-Arbeiten."*

## Physical layout (D-1 v2 — ADR-0003 resolver shim)

LEGACY `*.pine` files now live under `pine/legacy/`. Active SMC suite
files stay at the repo root (no TradingView saved-script breakage for
active consumers). `SMC_Confluence_Hub.pine` and `test_div.pine` stay
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

## SMC product surfaces

The canonical machine-readable lifecycle is
[`scripts/smc_bus_manifest.py`](scripts/smc_bus_manifest.py). This index is a
human-readable compatibility view and must not introduce a second
classification.

### Deployed standard rollout

These eight files are the current managed TradingView save targets:

| File | Role |
|---|---|
| `SMC_Long_Dip_Suite.pine` | Engine BUS v2 producer |
| `SMC_Breakout_Overlay.pine` | deployed overlay consumer |
| `SMC_Confluence_Hub.pine` | deployed confluence consumer |
| `SMC_Long_Dip_Alerts.pine` | deployed alert consumer |
| `SMC_Long_Dip_Dashboard.pine` | deployed dashboard consumer |
| `SMC_Long_Dip_Mobile.pine` | deployed mobile consumer |
| `SMC_Long_Dip_Strategy.pine` | deployed execution consumer |
| `SMC_Setup_Check.pine` | deployed setup and binding diagnostic |

### Planned rollout

These sources exist, but are not part of the current managed rollout:

| File | Target state |
|---|---|
| `SMC_Event_Overlay.pine` | planned standard companion |
| `SMC_Exit_Signal.pine` | planned standard companion |
| `SMC_Hold_Manager.pine` | planned standard companion after its readiness gates |
| `SMC_Volume_Profile_Overlay.pine` | planned optional companion |
| `SMC_Context_Bus.pine` | R4 shadow producer; source exists but is not deployed until private runtime gates pass |
| `SMC_Context_Overlay.pine` | R4 non-gating shadow consumer; source exists but is not deployed until binding and parity gates pass |

### Replacement or retirement pending

The seven snapshot-era context files below are known-broken against the
current generated micro-profile contract. They remain at the root only until
their documented replacement or archive gate is complete. They are not active
rollout targets.

| File | State |
|---|---|
| `SMC_HTF_Confluence.pine` | replacement pending |
| `SMC_Imbalance_Context.pine` | replacement pending |
| `SMC_Liquidity_Context.pine` | replacement pending |
| `SMC_Liquidity_Structure.pine` | replacement pending |
| `SMC_Profile_Context.pine` | replacement pending |
| `SMC_Session_Context.pine` | replacement pending |
| `SMC_Structure_Context.pine` | replacement pending |
| `SMC_Orderflow_Overlay.pine` | retirement pending; live orderflow belongs in the Databento backend |
| `SMC_Regime_and_News.pine` | retired, network-inert compatibility tombstone |

### Published Pine libraries and generated sources

| File | Role |
|---|---|
| `pine/skipp_calibration.pine` | library |
| `pine/skipp_indicators.pine` | library |
| `pine/skipp_labels.pine` | library |
| `pine/skipp_math.pine` | library |
| `pine/skipp_scoring.pine` | library |
| `pine/generated/*` | code-generated |

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
| `SMC_HTF_Confluence_v1_snapshot.pine`                       |  101 | LEGACY      | R5 snapshot-era HTF consumer; rollback reference for the confirmed rebuild |
| `SMC_Session_Context_v1_snapshot.pine`                      |   56 | LEGACY      | R5 snapshot-era Session consumer; rollback reference for the IANA rebuild |
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

1. If it belongs to the SMC product → classify it once in
   [`scripts/smc_bus_manifest.py`](scripts/smc_bus_manifest.py). Generated
   manifests, rollout gates, lifecycle views, and this human index must agree
   with that registry.
2. If it is a one-off or historical tool → move or add it under
   `pine/legacy/` and record it in **Legacy / standalone** with the LOC and a
   one-line note.

**Drift detection is enforced in CI.**
[`scripts/check_pine_legacy_drift.py`](scripts/check_pine_legacy_drift.py)
runs together with the Pine surface-registry gate in
[`smc-fast-pr-gates`](.github/workflows/smc-fast-pr-gates.yml) and fails the
build whenever:

- A root-level `*.pine` file is missing from this index, **or**
- A physical file mentioned in this index is missing from the root or
  `pine/legacy/`, **or**
- Registry lifecycle, rollout configuration, BUS dependencies, or known
  micro-profile debt drift from their canonical contracts.
