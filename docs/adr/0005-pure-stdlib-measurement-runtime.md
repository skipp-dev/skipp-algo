# ADR-0005: Pure-Stdlib Constraint for the Measurement Runtime

| Field       | Value                                              |
|-------------|----------------------------------------------------|
| Status      | Accepted                                           |
| Date        | 2026-04-24                                         |
| Deciders    | skipp-dev                                          |
| Supersedes  | (none)                                             |
| Related     | [`scripts/run_ab_comparison.py`](../../scripts/run_ab_comparison.py), [`scripts/smc_sprt_stop_rule.py`](../../scripts/smc_sprt_stop_rule.py), [`tests/test_run_ab_comparison_fdr.py`](../../tests/test_run_ab_comparison_fdr.py), [`tests/test_run_ab_comparison_calibration_fdr.py`](../../tests/test_run_ab_comparison_calibration_fdr.py), `BOOTSTRAP_CALIBRATION_FDR_DESIGN_2026-04-24.md` (§7 PR C) |

## Context

The measurement runtime — the set of scripts that compute Promote /
Hold / Rollback evidence from event ledgers — comprises:

- [`scripts/run_ab_comparison.py`](../../scripts/run_ab_comparison.py)
  (A/B digest, hit-rate BH-FDR, calibration BH-FDR, SPRT)
- [`scripts/smc_sprt_stop_rule.py`](../../scripts/smc_sprt_stop_rule.py)
  (Wald SPRT terminal decision)
- The statistical helpers they expose (`benjamini_hochberg`,
  `_two_proportion_z_pvalue`, `_metric_brier`, `_metric_ece`,
  `_permutation_p_delta_metric`).

PR [#102](https://github.com/skippALGO/skipp-algo/pull/102) (S-2
hit-rate BH-FDR) landed under an explicit "pure stdlib" constraint:
no `numpy`, no `scipy`, no `statsmodels`. PR
[#117](https://github.com/skippALGO/skipp-algo/pull/117) (S-2
follow-up calibration BH-FDR) re-affirmed the same constraint and
documented it in the PR body and in the design memo §7 PR C
("NumPy-Vektorisierung — Backlog, konsistent mit #102 'pure stdlib'").

This ADR formalises the rationale so future contributors do not
re-litigate it on a per-PR basis, and so the choice is referenced
from a stable artifact rather than an ephemeral PR discussion.

## Decision

The measurement runtime **must remain importable and executable using
only the Python 3.13 standard library**. Specifically:

1. None of `scripts/run_ab_comparison.py`,
   `scripts/smc_sprt_stop_rule.py`, or the statistical helpers they
   expose may import `numpy`, `scipy`, `pandas`, `statsmodels`,
   `scikit-learn`, or any other third-party numerical library at
   module load or at any code path reachable from `compare()`,
   `decide_recommendation()`, `_sprt_decision()`,
   `_family_fdr_layer()`, `_calibration_fdr_layer()`,
   `_metric_brier()`, `_metric_ece()`, or
   `_permutation_p_delta_metric()`.

2. New statistical layers added to the measurement runtime
   (e.g. block-permutation, Platt-refit-conditional tests) must
   either implement the algorithm in pure Python or be added to a
   separate, opt-in adapter module that is **not imported** by the
   default `compare()` code path.

3. Test suites for the measurement runtime
   (`tests/test_run_ab_comparison_*.py`,
   `tests/test_smc_sprt_stop_rule.py`) likewise stay pure-stdlib so
   the constraint can be verified by `python -m pytest` without
   `pip install`.

## Decision drivers

- **Reproducibility across CI runners and operator workstations.**
  The measurement runtime decides Promote / Hold / Rollback for the
  Q4 gate. Any divergence in numerical output between runners
  (different BLAS, different `numpy` minor version, different
  `scipy` integration backend) would require operator forensics that
  is wholly avoidable with stdlib `math` + `random.Random(seed)`.

- **Determinism is asserted at byte level.** The Calibration-FDR
  schema-pin tests
  ([`tests/test_run_ab_comparison_fdr.py`](../../tests/test_run_ab_comparison_fdr.py)
  `test_fdr_calibration_schema_pin_*`) and the advisory-only
  byte-identity guards
  (`test_compare_advisory_only_does_not_change_recommendation`,
  `test_fdr_layer_advisory_only_byte_identity_recommendation_sprt`)
  rely on exact dict equality across runs. Floating-point drift
  introduced by switching from pure-Python sums to `numpy.sum` (which
  uses pairwise summation on contiguous arrays) is sufficient to
  flake these tests at the round-to-6-decimal granularity used in
  the JSON schema.

- **Audit footprint stays narrow.** The measurement runtime is the
  evidence layer that downstream policy (`f2_run_promotion_gate`,
  release-gate workflow) consumes verbatim. Keeping the dependency
  closure to stdlib lets the entire decision chain be audited by
  reading `scripts/*.py` plus `smc_core/*.py` without traversing a
  third-party dependency tree.

- **Cost is bounded.** The most expensive measurement-runtime path
  is the calibration BH-FDR layer at `B=2000` permutations × 8 cells
  ≈ 3 minutes wall clock when explicitly opted in via
  `--enable-calibration-fdr`. Default-off means the standard CI
  invocation pays zero. The design memo §5 P4 documents that
  vectorisation would buy ~30× on this single path; that is not a
  blocker until the layer is invoked at higher cadence.

## Consequences

### Accepted

- The pure-Python permutation loop in
  `_permutation_p_delta_metric` runs at ~30 ms per cell for the
  expected `n ≈ 100` per arm and `B = 2000`. Aggregate ~3 min for
  the typical 4-family × 2-metric test grid is acceptable as a
  default-off opt-in.

- The BH adjustment, Brier and ECE metric helpers are all O(n)
  pure-Python loops. No vectorisation gain is realised even when the
  layer is enabled.

- New statistical follow-ups (block-permutation, Platt-refit) added
  in pure Python will be slower than a numpy-backed equivalent. This
  is the explicit tradeoff.

### Rejected (deferred to backlog)

- **PR C from `BOOTSTRAP_CALIBRATION_FDR_DESIGN_2026-04-24.md` §7**
  (NumPy-Vectorization of the inner permutation loop) is not
  implemented under this ADR. Trigger condition for revisit:
  calibration-FDR layer is invoked from a default-on CI path AND the
  resulting CI runtime budget is exceeded AND the byte-identity
  guards above are demonstrably tolerant of the numerical
  perturbation introduced (or are migrated to tolerance-based
  comparison).

- Replacement of pure-Python `_two_proportion_z_pvalue` /
  `benjamini_hochberg` with `scipy.stats` equivalents is not
  permitted under this ADR. The pure-Python implementations are
  pinned by the existing test suite (textbook B&H step-up example,
  Phipson-Smyth `(r+1)/(B+1)` clamp, two-proportion z-test against
  closed-form expected values).

### Out of scope

- This ADR does **not** restrict numerical libraries in the
  *non-measurement* runtime: `databento_*`, `terminal_*`, the
  Streamlit screeners, the open-prep boundary, and the SMC analyst
  enrichers may freely depend on `numpy` / `pandas` / `scipy`. The
  boundary is the import graph reachable from `scripts/run_ab_comparison.py`
  and `scripts/smc_sprt_stop_rule.py`.

- This ADR does **not** restrict optional dependencies for *test
  fixtures* or *plotting / visualisation* helpers that are imported
  only by tests or by interactive notebooks.

## Verification

1. The pure-stdlib constraint is verified at runtime by `python -c "import scripts.run_ab_comparison"` succeeding in a venv that has only stdlib + `pytest` installed.
2. The byte-identity guards
   `test_compare_advisory_only_does_not_change_recommendation` and
   `test_fdr_layer_advisory_only_byte_identity_recommendation_sprt`
   would fail under floating-point drift introduced by a numpy
   migration; they act as the regression sentinels for this ADR.
3. The schema-pin tests
   `test_fdr_calibration_schema_pin_{disabled,ledger_missing,active}`
   pin the JSON-output field set, so any restructuring driven by a
   numpy migration would surface as a schema diff.

## References

- `BOOTSTRAP_CALIBRATION_FDR_DESIGN_2026-04-24.md` §5 P4
  (compute-budget pitfall) and §7 PR C (NumPy backlog item).
- PR [#102](https://github.com/skippALGO/skipp-algo/pull/102) — original
  pure-stdlib commitment for the hit-rate BH-FDR layer.
- PR [#117](https://github.com/skippALGO/skipp-algo/pull/117) —
  re-affirmation under the calibration BH-FDR follow-up.
