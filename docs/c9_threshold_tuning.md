# C9/T7 — Threshold Tuning

**Status:** synthetic-tuned — detectors 3 + 4 are p-value tests
(structural part of issue #298, done 2026-06-11); the alpha ladder
will be re-tuned and locked once the C8 live-incubation backfill
provides ≥ 90 days of real outcome data
(`scripts/c9_threshold_replay.py::CALIBRATION_SOURCE` flips
`"synthetic"` → `"live"` in that PR).

## What this is

`scripts/c9_threshold_replay.py` replays a labelled episode bank
(synthetic for now, historical C1 outcome stream once available)
against a grid of threshold settings for the C9 4-detector consensus:

* **Detector 1 — KS p-value** (per `scripts/drift_alert.py:ks_two_sample`)
* **Detector 2 — PSI** (per `scripts/drift_alert.py:population_stability_index`)
* **Detector 3 — Welch t-test p-value** (two-sided, unequal-variance;
  per `scripts/drift_alert.py:welch_t_two_sample`) — first-moment shift
* **Detector 4 — Brown-Forsythe p-value** (median-centered Levene; per
  `scripts/drift_alert.py:brown_forsythe_two_sample`) — second-moment
  shift

Detectors 1, 3 and 4 share a single alpha ladder
(`p_red` / `p_yellow`) so one grid axis tunes the whole consensus. A
consensus of `≥ N` detectors firing yellow-or-red counts as an
episode-level fire.  The default grid is `consensus ∈ {2, 3}` per the
C9 sprint plan.

### History: bauchgefühl literals → p-value tests (issue #298)

Until 2026-06-11 detectors 3 + 4 were interim effect-size rules
(mean shift ≥ 0.3 σ of baseline; live σ / baseline σ outside
`[0.5, 2.0]`) sourced from drift-monitoring rules of thumb. They were
replaced by significance tests so the firing rate is controlled by an
alpha level rather than an arbitrary effect-size cutoff:

* Detector 3 → **Welch t** (robust to variance imbalance between
  baseline and live windows). P-value via the regularized incomplete
  beta function — pure stdlib, no scipy (verified to 1e-9 against
  `scipy.stats.ttest_ind(equal_var=False)`).
* Detector 4 → **Brown-Forsythe** rather than the plain F-ratio test:
  the F-test is catastrophically non-robust to heavy tails, and the
  episode bank deliberately includes t(df=4) and lognormal families.
  (Verified to 1e-9 against `scipy.stats.levene(center='median')`.)

Zero-variance guards are pinned by
`tests/test_c9_episode_fires_invariants_property.py`: a degenerate
baseline disables detectors 3 + 4; a degenerate live sample disables
detector 4.

### Grid results (2026-06-11, synthetic bank)

`build_synthetic_episodes(n_normal=40, n_drift=20, sample_size=80, seed=11)`,
acceptance bar TPR ≥ 0.80 ∧ FPR < 0.10:

| alpha ladder (red/yellow) | consensus | Gaussian bank | mixed bank (t(4)+lognormal) |
|---|---|---|---|
| 0.005 / 0.025 | 2 | TPR 0.80, FPR 0.03 ✅ | TPR 0.90, FPR 0.07 ✅ |
| 0.01 / 0.05 | 2 | TPR 0.80, FPR 0.05 ✅ | TPR 0.90, **FPR 0.12 ❌** |
| 0.01 / 0.05 | 3 | TPR 0.75 ❌ | TPR 0.80, FPR 0.05 ✅ |
| 0.001 / 0.01 | 2 | TPR 0.80, FPR 0.00 ✅ | TPR 0.70 ❌ |

**Current production default** (in
`drift_alert.compute_drift_report`; synthetic-tuned, see header — NOT
yet locked against live outcomes): `p_red=0.005`, `p_yellow=0.025`,
`consensus_min=2` — the only setting passing both banks while
dominating on FPR. The previous `0.01/0.05` default failed the mixed
bank once detectors 3 + 4 became p-value tests (they fire more often
near the boundary, raising 2-of-4 consensus sensitivity).

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

## Next steps (deferred until C8 live data exists — issue #298 stays open)

1. Replace `build_synthetic_episodes` with a loader for historical
   C1 outcome chunks tagged with known regime breaks.
2. Re-run the alpha-ladder grid against the live windows; tighten the
   grid around `0.005/0.025`.
3. Lock the chosen setting into `drift_alert.compute_drift_report`,
   flip `CALIBRATION_SOURCE` to `"live"`, change **Status** above to
   `locked`, and retire
   `tests/test_c9_threshold_finalisation_anchor.py`.
4. Add a sensitivity plot (`docs/c9_threshold_tuning_plot.png`).

The CI anchor `tests/test_c9_threshold_finalisation_anchor.py` fails
the moment the C12 trigger flips GREEN (≥ 1 family with ≥ 28
live-incubation days) while `CALIBRATION_SOURCE` still reads
`"synthetic"`.
