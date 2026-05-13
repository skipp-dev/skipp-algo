# C7 — Track-Record-Dashboard User Guide

**Status:** scaffolded — awaits production deployment decision (T8 follow-up).
**Audience:** Steffen + future external reviewers of the track record.

This guide explains how to read every panel of the C7 dashboard and
which sprint produced each block.  It does **not** explain how to
operate the calibration pipeline — see the per-sprint plans in
`docs/SPRINT_PLAN_C2…C9_*.md`.

---

## How to launch (locally)

```bash
streamlit run streamlit_terminal.py
```

The dashboard reads from `cache/calibration/*.json` (built by the C2-C6
nightly jobs) and from `cache/live/*.json` (built by the C8 cron once
live incubation starts).  If a file is missing, the corresponding panel
shows a placeholder rather than crashing.

For a containerised run see `docs/c7_deploy.md` (T8).

---

## Tab: Track Record (`tab_track_record.py`)

Top-level summary of every variant.

* **Gate counts** — `🟢 / 🟡 / 🔴 / ⚪` totals.  Source: per-variant
  `gate_status` field from `track_record_gate_<date>.json` (C6).
* **Variants table** — one row per variant.  Columns: `variant`, `n`,
  `hit_rate`, `sharpe`, bootstrap CI low / high (C3),
  `permutation_p_value` (C4), `psr` (C6), walk-forward efficiency (C2),
  `max_dd`, `gate_status`.
* **Gate failures (red)** — for each red variant the dashboard lists
  the reason codes from `gate_failures` so the failure mode is
  immediately readable.

**How to read it:** A green row is a variant that passes all C2-C6
checks.  Amber means the variant is eligible for paper-incubation but
not for live size.  Red means the variant must not be promoted.

---

## Tab: Calibration Detail (`tab_calibration_detail.py`)

Per-variant drill-down with five sub-tabs:

1. **Walk-Forward** — fold-by-fold Sharpe and the C2 walk-forward
   efficiency.
2. **Bootstrap** — the C3 stationary-block bootstrap distribution and
   the 95 % Sharpe CI.
3. **Permutation** — the C4 empirical null distribution with the
   observed statistic marked, plus the empirical p-value.
4. **Regime** — the C5 regime-stratified per-cell metrics, the
   freq-weighted aggregate Sharpe, and the regime-concentration
   warning flag.
5. **PSR / MinTRL** — the C6 Probabilistic Sharpe Ratio and the
   minimum track record length needed to claim the observed Sharpe at
   the configured confidence.

Empty sub-tabs are expected when the upstream artifact has not been
generated yet (e.g. a variant is too new to have a permutation null).

---

## Tab: Live Incubation (`tab_live_incubation.py`)

Surfaces the C8 drift detector output (`compute_live_drift.py` →
`cache/live/drift_<date>.json`).

* **Verdict counts** — `🟢 pass / 🟡 acceptable / 🟠 concerning / 🔴 fail / ⚪ insufficient_sample`. * **Per-variant table** — backtest Sharpe, live Sharpe, drift
  (live − backtest), live trade count, verdict.

While Phase-A has not started this tab shows the
*"Live-Inkubation startet in Sprint C8."* placeholder.

---

## Sidebar: Methodology Drawer (`methodology_drawer.py`)

* Links to every sprint plan (C2-C9) so readers can audit the math
  behind each metric.
* Canonical sources: Bailey & López de Prado (2012, 2014), Politis &
  Romano stationary bootstrap.
* Current gate threshold table (`min_trades`, `min_sharpe`,
  `min_psr`, `perm_p_max`, `drift_score_min_acceptable`).
* Data-freshness indicator (`fresh` / `stale` / `unknown`) — `stale`
  fires if the most recent payload is older than 24 hours.

---

## Where the data comes from

| Panel block | Cache file | Producer |
| --- | --- | --- |
| Track-Record gates | `cache/calibration/track_record_gate_<date>.json` | `scripts/track_record_gate.py` (C6/T6) |
| Walk-forward folds | `cache/calibration/walk_forward_<date>.json` | C2 nightly job |
| Bootstrap CIs | `cache/calibration/bootstrap_ci_<date>.json` | C3 nightly job |
| Permutation nulls | `cache/calibration/permutation_<date>.json` | C4 nightly job |
| Regime stratification | `cache/calibration/regime_stratified_<date>.json` | `scripts/regime_stratification.py` (C5) |
| PSR / MinTRL | `cache/calibration/psr_mintrl_<date>.json` | C6 nightly job |
| Drift verdicts | `cache/live/drift_<date>.json` | `scripts/compute_live_drift.py` (C8/T4) |

The aggregator `scripts/build_dashboard_payload.py` (C7/T2) merges
these inputs into a single payload the tabs render.

---

## Troubleshooting

* **Empty tab** — verify the corresponding cache file exists for
  *today's* date.  The aggregator picks the newest available
  `walk_forward_*.json` and uses its date suffix for every other
  lookup.
* **Sidebar shows `freshness: stale`** — the `computed_at` timestamp
  on the payload is more than 24 h old; re-run the C2-C6 nightly
  jobs.
* **Dashboard crashes on launch** — make sure `streamlit`, `numpy`,
  and `plotly` are installed (`pip install -r requirements.txt`).

---

## Sprint C7 acceptance — done in this guide

* [x] Per-tab reading guide (T3, T4, T6)
* [x] Source/methodology pointer (T5)
* [x] Cache-file inventory (T2)
* [x] Local-launch instructions
* [x] Troubleshooting block

Production deploy + multi-user auth remain out of scope for C7 by
design — see `docs/SPRINT_PLAN_C7_DASHBOARD_2026-04-26.md` §T8.
