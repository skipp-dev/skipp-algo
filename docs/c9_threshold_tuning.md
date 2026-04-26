# C9/T7 — Threshold Tuning

**Status:** scaffolded — production thresholds will be locked once the
C8 live-incubation backfill provides ≥ 90 days of real outcome data.

## What this is

`scripts/c9_threshold_replay.py` replays a labelled episode bank
(synthetic for now, historical C1 outcome stream once available)
against a grid of threshold settings for the C9 4-detector consensus:

* **Detector 1 — KS p-value** (per `scripts/drift_alert.py:ks_two_sample`)
* **Detector 2 — PSI** (per `scripts/drift_alert.py:population_stability_index`)
* **Detector 3 — mean-shift** (live mean − baseline mean, normalized by baseline σ; fires at ≥ 0.3σ)
* **Detector 4 — variance ratio** (live σ / baseline σ outside `[0.5, 2.0]`)

A consensus of `≥ N` detectors firing yellow-or-red counts as an
episode-level fire.  The default grid is `consensus ∈ {2, 3}` per the
C9 sprint plan.

## Usage

```bash
python -m scripts.c9_threshold_replay \
  --out cache/c9/threshold_replay.json \
  --print-table
```

Output JSON schema (1.0.0):

```json
{
  "schema_version": "1.0.0",
  "n_settings": 24,
  "results": [
    {
      "setting": {"ks_p_red": 0.01, "ks_p_yellow": 0.05, "psi_n_buckets": 10, "consensus_min": 2},
      "setting_key": "ks_red=0.0100_ks_yellow=0.0500_psi_bins=10_consensus=2",
      "n_drift": 10,
      "n_normal": 20,
      "true_positive": 9,
      "false_positive": 1,
      "tpr": 0.9,
      "fpr": 0.05,
      "passes_acceptance": true,
      "fired_episodes": ["drift_00", "drift_01", "..."]
    }
  ],
  "passing_settings": ["ks_red=0.0100_..."]
}
```

## Acceptance bar (sprint plan §T7)

A grid point passes if **TPR ≥ 0.80** and **FPR < 0.10**.  At least
one default-grid point must clear the bar on the synthetic bank — this
is enforced by `tests/test_c9_threshold_replay.py::test_default_grid_has_at_least_one_passing_setting`.

## Next steps (deferred until C8 live data exists)

1. Replace `build_synthetic_episodes` with a loader for historical
   C1 outcome chunks tagged with known regime breaks.
2. Tighten the grid around the highest-scoring synthetic point.
3. Lock the chosen setting into `scripts/run_drift_watchdog.py`.
4. Add a sensitivity plot (`docs/c9_threshold_tuning_plot.png`).
