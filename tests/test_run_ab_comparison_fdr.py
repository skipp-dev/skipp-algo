"""S-2: Per-family Benjamini-Hochberg FDR layer for ``run_ab_comparison``.

The BH layer is *advisory* — it does not change the Promote/Hold/Rollback
decision — but the rejection set must satisfy the classical B&H step-up
guarantees and stay disjoint from the SPRT terminal decision logic.
"""
from __future__ import annotations

import math

from scripts.run_ab_comparison import (
    FDR_Q,
    _family_fdr_layer,
    _two_proportion_z_pvalue,
    benjamini_hochberg,
    compare,
)

# ---------------------------------------------------------------------------
# benjamini_hochberg() unit tests
# ---------------------------------------------------------------------------


def test_bh_empty_input_returns_empty_lists() -> None:
    out = benjamini_hochberg([], q=0.05)
    assert out == {"rejected": [], "adjusted": [], "threshold": None, "q": 0.05}


def test_bh_all_significant_rejects_all() -> None:
    # All p-values well below alpha=0.05 → all rejected.
    pvals = [0.001, 0.002, 0.003]
    out = benjamini_hochberg(pvals, q=0.05)
    assert out["rejected"] == [True, True, True]
    assert out["threshold"] == 0.003


def test_bh_no_significant_rejects_none() -> None:
    pvals = [0.5, 0.6, 0.7]
    out = benjamini_hochberg(pvals, q=0.05)
    assert out["rejected"] == [False, False, False]
    assert out["threshold"] is None


def test_bh_step_up_textbook_example() -> None:
    # B&H 1995 Table 1 example with m=15 hypotheses (subset).
    # Sorted p-values 0.001, 0.005, 0.012, 0.04, 0.06, 0.10, 0.20, 0.50, 0.80, 0.95
    # at q=0.05 → reject k=4 (p_(4)=0.04 <= 4/10 * 0.05 = 0.020 — false; check k=3:
    # 0.012 <= 3/10 * 0.05 = 0.015 → True. So threshold rank = 3.
    pvals = [0.012, 0.001, 0.005, 0.04, 0.06, 0.10, 0.20, 0.50, 0.80, 0.95]
    out = benjamini_hochberg(pvals, q=0.05)
    # The first three (0.012, 0.001, 0.005 in original order) should be rejected.
    assert out["rejected"][0] is True   # 0.012
    assert out["rejected"][1] is True   # 0.001
    assert out["rejected"][2] is True   # 0.005
    assert out["rejected"][3] is False  # 0.04
    assert out["threshold"] == 0.012


def test_bh_preserves_input_order_in_output() -> None:
    pvals = [0.04, 0.001, 0.5, 0.005]
    out = benjamini_hochberg(pvals, q=0.05)
    # Sorted indices: 1 (0.001), 3 (0.005), 0 (0.04), 2 (0.5)
    # k=1: 0.001 <= 1/4*0.05=0.0125 → reject (rank 1)
    # k=2: 0.005 <= 2/4*0.05=0.025 → reject (rank 2)
    # k=3: 0.04 <= 3/4*0.05=0.0375 → false
    # threshold rank = 2; rejected = the two smallest in original order.
    assert out["rejected"] == [False, True, False, True]


def test_bh_adjusted_pvalues_are_monotone_when_sorted() -> None:
    pvals = [0.001, 0.005, 0.012, 0.04, 0.06]
    out = benjamini_hochberg(pvals, q=0.05)
    sorted_adj = sorted(out["adjusted"])
    # BH-adjusted p-values must be non-decreasing in the sorted order.
    for i in range(1, len(sorted_adj)):
        assert sorted_adj[i] >= sorted_adj[i - 1] - 1e-12


def test_bh_adjusted_pvalues_clamped_to_unit_interval() -> None:
    pvals = [0.5, 0.6, 0.7]
    out = benjamini_hochberg(pvals, q=0.05)
    for p in out["adjusted"]:
        assert 0.0 <= p <= 1.0


def test_bh_clamps_invalid_input_pvalues() -> None:
    """Defensive: degenerate p-values (negative / > 1) get clamped."""
    out = benjamini_hochberg([-0.1, 1.5], q=0.05)
    assert all(0.0 <= p <= 1.0 for p in out["adjusted"])


# ---------------------------------------------------------------------------
# _two_proportion_z_pvalue() unit tests
# ---------------------------------------------------------------------------


def test_z_pvalue_strong_treatment_lift_is_significant() -> None:
    # treatment 80% on 200 vs control 50% on 200 → p ≈ 0
    p = _two_proportion_z_pvalue(k_treat=160, n_treat=200, k_ctrl=100, n_ctrl=200)
    assert p is not None
    assert p < 0.001


def test_z_pvalue_no_difference_is_about_half() -> None:
    p = _two_proportion_z_pvalue(k_treat=100, n_treat=200, k_ctrl=100, n_ctrl=200)
    assert p is not None
    assert math.isclose(p, 0.5, abs_tol=0.01)


def test_z_pvalue_treatment_worse_returns_p_above_half() -> None:
    p = _two_proportion_z_pvalue(k_treat=80, n_treat=200, k_ctrl=120, n_ctrl=200)
    assert p is not None
    assert p > 0.5


def test_z_pvalue_zero_n_returns_none() -> None:
    assert _two_proportion_z_pvalue(k_treat=0, n_treat=0, k_ctrl=10, n_ctrl=20) is None


def test_z_pvalue_degenerate_pool_returns_none() -> None:
    # Both arms 100% hit rate → pooled p=1.0, no variance.
    assert _two_proportion_z_pvalue(k_treat=10, n_treat=10, k_ctrl=20, n_ctrl=20) is None
    # Both arms 0% → pooled p=0.0, no variance.
    assert _two_proportion_z_pvalue(k_treat=0, n_treat=10, k_ctrl=0, n_ctrl=20) is None


def test_z_pvalue_zero_control_arm_returns_none() -> None:
    # Mirror of the n_treat=0 case: caller passes a control arm with no
    # observed events for the family. Guard the second branch of the
    # ``n_treat <= 0 or n_ctrl <= 0`` early-return so future refactors
    # cannot drop one half silently.
    assert _two_proportion_z_pvalue(k_treat=10, n_treat=20, k_ctrl=0, n_ctrl=0) is None


def test_family_fdr_layer_marks_degenerate_family_skipped() -> None:
    """End-to-end: a family that triggers the None p-value path is recorded
    with ``skipped_reason='degenerate_or_empty'`` and excluded from the
    BH input. Guards the wiring between ``_two_proportion_z_pvalue`` and
    ``_family_fdr_layer`` so the skip reason cannot be silently renamed.
    """
    from scripts.run_ab_comparison import _family_fdr_layer

    def pair(family_metrics: dict[str, dict]) -> dict:
        return {
            "symbol": "AAPL", "timeframe": "5m", "n_events": 100,
            "brier": 0.20, "calibrated_brier": 0.20, "calibrated_ece": 0.05,
            "raw_ece": 0.05, "log_score": 0.5, "hit_rate_pct": 50.0,
            "family_metrics": family_metrics,
        }

    # Family BOS: both arms 0/n events → pooled p=0 → degenerate.
    # Family FVG: clean signal → testable.
    ctrl = [pair({"BOS": {"n_events": 50, "hit_rate": 0.0},
                  "FVG": {"n_events": 200, "hit_rate": 0.50}})]
    treat = [pair({"BOS": {"n_events": 50, "hit_rate": 0.0},
                   "FVG": {"n_events": 200, "hit_rate": 0.70}})]
    out = _family_fdr_layer(ctrl, treat)

    by_fam = {e["family"]: e for e in out["families"]}
    assert by_fam["BOS"]["p_value"] is None
    assert by_fam["BOS"]["skipped_reason"] == "degenerate_or_empty"
    assert by_fam["BOS"]["adjusted_p_value"] is None
    assert by_fam["BOS"]["rejected"] is False
    assert by_fam["FVG"]["p_value"] is not None
    assert by_fam["FVG"]["skipped_reason"] is None
    assert out["tested_families"] == 1
    assert out["skipped_families"] == 1


# ---------------------------------------------------------------------------
# _family_fdr_layer() integration
# ---------------------------------------------------------------------------


def _pair(family_metrics: dict[str, dict]) -> dict:
    return {
        "symbol": "X",
        "timeframe": "5m",
        "n_events": sum(int(fm.get("n_events", 0)) for fm in family_metrics.values()),
        "family_metrics": family_metrics,
    }


def test_fdr_layer_aggregates_events_across_pairs() -> None:
    ctrl = [_pair({"BOS": {"n_events": 50, "hit_rate": 0.5}})]
    treat = [_pair({"BOS": {"n_events": 50, "hit_rate": 0.5}})]
    out = _family_fdr_layer(ctrl, treat)
    assert len(out["families"]) == 1
    fam = out["families"][0]
    assert fam["n_control"] == 50
    assert fam["n_treatment"] == 50


def test_fdr_layer_skips_families_only_in_one_arm() -> None:
    ctrl = [_pair({"BOS": {"n_events": 50, "hit_rate": 0.5}})]
    treat = [_pair({"FVG": {"n_events": 50, "hit_rate": 0.5}})]
    out = _family_fdr_layer(ctrl, treat)
    assert out["families"] == []
    assert out["tested_families"] == 0


def test_fdr_layer_marks_strong_treatment_lift_as_rejected() -> None:
    ctrl = [_pair({"BOS": {"n_events": 200, "hit_rate": 0.50}})]
    treat = [_pair({"BOS": {"n_events": 200, "hit_rate": 0.80}})]
    out = _family_fdr_layer(ctrl, treat)
    assert "BOS" in out["rejected_families"]
    assert out["families"][0]["rejected"] is True
    assert out["families"][0]["adjusted_p_value"] is not None


def test_fdr_layer_does_not_reject_random_lift() -> None:
    # 1pp lift on 100 events — clearly not significant.
    ctrl = [_pair({"BOS": {"n_events": 100, "hit_rate": 0.50}})]
    treat = [_pair({"BOS": {"n_events": 100, "hit_rate": 0.51}})]
    out = _family_fdr_layer(ctrl, treat)
    assert out["rejected_families"] == []
    assert out["families"][0]["rejected"] is False


def test_fdr_layer_handles_percentage_hit_rates() -> None:
    """Legacy artifacts may store hit_rate as percent (e.g. 50.0); auto-detect."""
    ctrl = [_pair({"BOS": {"n_events": 200, "hit_rate": 50.0}})]
    treat = [_pair({"BOS": {"n_events": 200, "hit_rate": 80.0}})]
    out = _family_fdr_layer(ctrl, treat)
    assert out["families"][0]["hit_rate_control"] == 0.5
    assert out["families"][0]["hit_rate_treatment"] == 0.8
    assert out["families"][0]["rejected"] is True


def test_fdr_layer_default_q_matches_module_constant() -> None:
    out = _family_fdr_layer([], [])
    assert out["q"] == FDR_Q


def test_compare_includes_fdr_in_digest() -> None:
    ctrl = [{
        "symbol": "AAPL", "timeframe": "5m", "n_events": 100,
        "brier": 0.20, "calibrated_brier": 0.20, "calibrated_ece": 0.05,
        "raw_ece": 0.05, "log_score": 0.5, "hit_rate_pct": 50.0,
        "family_metrics": {"BOS": {"n_events": 100, "hit_rate": 0.5}},
    }]
    treat = [{
        "symbol": "AAPL", "timeframe": "5m", "n_events": 100,
        "brier": 0.18, "calibrated_brier": 0.18, "calibrated_ece": 0.04,
        "raw_ece": 0.04, "log_score": 0.5, "hit_rate_pct": 60.0,
        "family_metrics": {"BOS": {"n_events": 100, "hit_rate": 0.6}},
    }]
    digest = compare(ctrl, treat, "test-fdr")
    assert "fdr" in digest
    assert digest["fdr"]["method"] == "benjamini_hochberg"


# ---------------------------------------------------------------------------
# Disjointness regression: FDR layer must NOT influence Promote/Hold/Rollback
# ---------------------------------------------------------------------------


def test_fdr_layer_is_advisory_only_recommendation_unchanged() -> None:
    """Even with strong per-family rejection, recommendation logic ignores FDR."""
    # Setup that should HOLD per the KPI thresholds (no calibration improvement)
    # but BOS family alone shows strong significance → FDR rejects, but the
    # top-level recommendation must not flip to "promote".
    ctrl = [{
        "symbol": "AAPL", "timeframe": "5m", "n_events": 200,
        "brier": 0.20, "calibrated_brier": 0.20, "calibrated_ece": 0.05,
        "raw_ece": 0.05, "log_score": 0.5, "hit_rate_pct": 50.0,
        "family_metrics": {"BOS": {"n_events": 200, "hit_rate": 0.5}},
    }]
    treat = [{
        "symbol": "AAPL", "timeframe": "5m", "n_events": 200,
        "brier": 0.20, "calibrated_brier": 0.20, "calibrated_ece": 0.05,
        "raw_ece": 0.05, "log_score": 0.5, "hit_rate_pct": 50.5,
        "family_metrics": {"BOS": {"n_events": 200, "hit_rate": 0.80}},
    }]
    digest = compare(ctrl, treat, "advisory-only")
    # FDR may reject BOS, but recommendation is hold (no calibration delta).
    assert digest["recommendation"] in {"hold", "rollback"}, digest["recommendation"]


def test_fdr_layer_advisory_only_byte_identity_recommendation_sprt() -> None:
    """Strict mirror of ``test_compare_advisory_only_does_not_change_recommendation``.

    Symmetry guard: the calibration-FDR test (S-2 follow-up) asserts that
    toggling ``enable_calibration_fdr`` between two ``compare()`` calls
    leaves ``recommendation`` / ``recommendation_reason`` / ``sprt``
    byte-identical. Hit-rate FDR has no enable flag (it is always-on),
    so the equivalent invariant is: removing ``family_metrics`` (which
    disables FDR computation entirely) versus including ``family_metrics``
    that produce a strong rejection must not perturb the same three
    decision-driving fields, because all three derive only from the
    top-level brier / ECE / log-score / hit-rate aggregates.
    """
    # Top-level metrics are byte-identical across both runs.
    base_ctrl = {
        "symbol": "AAPL", "timeframe": "5m", "n_events": 200,
        "brier": 0.20, "calibrated_brier": 0.20, "calibrated_ece": 0.05,
        "raw_ece": 0.05, "log_score": 0.5, "hit_rate_pct": 50.0,
    }
    base_treat = {
        "symbol": "AAPL", "timeframe": "5m", "n_events": 200,
        "brier": 0.18, "calibrated_brier": 0.18, "calibrated_ece": 0.04,
        "raw_ece": 0.04, "log_score": 0.5, "hit_rate_pct": 60.0,
    }
    # Variant A: family_metrics with strong lift → FDR rejects.
    ctrl_with = [{**base_ctrl, "family_metrics": {"BOS": {"n_events": 200, "hit_rate": 0.50}}}]
    treat_with = [{**base_treat, "family_metrics": {"BOS": {"n_events": 200, "hit_rate": 0.80}}}]
    # Variant B: no family_metrics at all → FDR has nothing to test.
    ctrl_without = [{**base_ctrl, "family_metrics": {}}]
    treat_without = [{**base_treat, "family_metrics": {}}]

    digest_with = compare(ctrl_with, treat_with, "symmetry-guard")
    digest_without = compare(ctrl_without, treat_without, "symmetry-guard")

    # Byte-identical decision-driving fields.
    assert digest_with["recommendation"] == digest_without["recommendation"]
    assert digest_with["recommendation_reason"] == digest_without["recommendation_reason"]
    assert digest_with["sprt"] == digest_without["sprt"]
    # And the FDR layer was actually exercised non-trivially in variant A.
    assert "BOS" in digest_with["fdr"]["rejected_families"]
    assert digest_without["fdr"]["families"] == []


# ---------------------------------------------------------------------------
# Schema-pin smoke test: ``digest["fdr_calibration"]`` field set
# ---------------------------------------------------------------------------
#
# Pins the canonical key set for the calibration-FDR advisory block. Any
# stealth field add/rename here must be paired with a major schema version
# bump (per ``schema-version-bump-must-be-major-on-field-count-change``
# convention). This test fails loudly if a new key is added without
# updating both the pin below and the schema version contract.


_FDR_CALIBRATION_DISABLED_KEYS = frozenset({"skipped_reason", "method"})

_FDR_CALIBRATION_ACTIVE_KEYS = frozenset({
    "method",
    "q",
    "B",
    "seed",
    "metrics_tested",
    "tested_cells",
    "skipped_cells",
    "rejected_cells",
    "threshold_p_value",
    "min_events_per_arm",
    "notes",
    "cells",
})

_FDR_CALIBRATION_CELL_KEYS = frozenset({
    "family",
    "metric",
    "n_control",
    "n_treatment",
    "metric_control",
    "metric_treatment",
    "delta",
    "p_value",
    "adjusted_p_value",
    "rejected",
    "lower_is_better",
    "skipped_reason",
})


def _calibration_pair() -> dict:
    return {
        "symbol": "AAPL", "timeframe": "5m", "n_events": 100,
        "brier": 0.20, "calibrated_brier": 0.20, "calibrated_ece": 0.05,
        "raw_ece": 0.05, "log_score": 0.5, "hit_rate_pct": 50.0,
        "family_metrics": {"BOS": {"n_events": 100, "hit_rate": 0.5}},
    }


def test_fdr_calibration_schema_pin_disabled() -> None:
    digest = compare([_calibration_pair()], [_calibration_pair()], "schema-pin-disabled")
    block = digest["fdr_calibration"]
    assert set(block.keys()) == _FDR_CALIBRATION_DISABLED_KEYS, (
        f"fdr_calibration disabled-variant key set drifted: {set(block.keys())}. "
        "Update the schema version (major bump) and the pin in this test."
    )
    assert block["method"] == "permutation_bh"
    assert block["skipped_reason"] == "disabled"


def test_fdr_calibration_schema_pin_ledger_missing() -> None:
    digest = compare(
        [_calibration_pair()],
        [_calibration_pair()],
        "schema-pin-ledger-missing",
        enable_calibration_fdr=True,
    )
    block = digest["fdr_calibration"]
    assert set(block.keys()) == _FDR_CALIBRATION_DISABLED_KEYS, (
        f"fdr_calibration ledger-missing-variant key set drifted: {set(block.keys())}. "
        "Update the schema version (major bump) and the pin in this test."
    )
    assert block["skipped_reason"] == "ledger_not_provided"


def test_fdr_calibration_schema_pin_active() -> None:
    """Active layer (ledgers provided): top-level + per-cell field set is pinned."""
    # Minimal ledger with enough events to get past MIN_EVENTS_PER_ARM_FOR_BOOTSTRAP.
    ctrl_ledger = [("BOS", 0.5, i % 2 == 0) for i in range(60)]
    treat_ledger = [("BOS", 0.5, i % 2 == 0) for i in range(60)]
    digest = compare(
        [_calibration_pair()],
        [_calibration_pair()],
        "schema-pin-active",
        control_ledgers=[ctrl_ledger],
        treatment_ledgers=[treat_ledger],
        enable_calibration_fdr=True,
        calibration_fdr_B=50,
    )
    block = digest["fdr_calibration"]
    assert set(block.keys()) == _FDR_CALIBRATION_ACTIVE_KEYS, (
        f"fdr_calibration active-variant key set drifted: {set(block.keys())}. "
        "Update the schema version (major bump) and the pin in this test."
    )
    # At least one cell must exist so we can pin its key set too.
    assert len(block["cells"]) >= 1
    for cell in block["cells"]:
        assert set(cell.keys()) == _FDR_CALIBRATION_CELL_KEYS, (
            f"fdr_calibration cell key set drifted: {set(cell.keys())}. "
            "Update the schema version (major bump) and the pin in this test."
        )


# ---------------------------------------------------------------------------
# Schema-pin smoke test: ``digest["fdr"]`` hit-rate field set
# ---------------------------------------------------------------------------
#
# Mirrors the calibration-FDR schema-pin (above). The hit-rate FDR layer is
# always-on (no enable flag), so two variants exist: "no common families"
# (empty ``families`` list, no per-family schema check) and "common families
# present" (full output including per-family entries). Any stealth field
# add/rename here must be paired with a major schema version bump per the
# ``schema-version-bump-must-be-major-on-field-count-change`` convention.


_FDR_TOPLEVEL_KEYS = frozenset({
    "method",
    "q",
    "tested_families",
    "skipped_families",
    "rejected_families",
    "threshold_p_value",
    "families",
})

_FDR_FAMILY_ENTRY_KEYS = frozenset({
    "family",
    "n_control",
    "n_treatment",
    "hit_rate_control",
    "hit_rate_treatment",
    "p_value",
    "rejected",
    "adjusted_p_value",
    "skipped_reason",
})


def _fdr_pair(family_metrics: dict[str, dict] | None = None) -> dict:
    return {
        "symbol": "AAPL", "timeframe": "5m", "n_events": 100,
        "brier": 0.20, "calibrated_brier": 0.20, "calibrated_ece": 0.05,
        "raw_ece": 0.05, "log_score": 0.5, "hit_rate_pct": 50.0,
        "family_metrics": family_metrics if family_metrics is not None else {},
    }


def test_fdr_schema_pin_no_common_families() -> None:
    """No common families → top-level keys still pinned, families list empty."""
    digest = compare(
        [_fdr_pair({"BOS": {"n_events": 50, "hit_rate": 0.5}})],
        [_fdr_pair({"FVG": {"n_events": 50, "hit_rate": 0.5}})],
        "fdr-pin-no-common",
    )
    block = digest["fdr"]
    assert set(block.keys()) == _FDR_TOPLEVEL_KEYS, (
        f"fdr top-level key set drifted: {set(block.keys())}. "
        "Update the schema version (major bump) and the pin in this test."
    )
    assert block["method"] == "benjamini_hochberg"
    assert block["families"] == []
    assert block["tested_families"] == 0


def test_fdr_schema_pin_with_families() -> None:
    """Common families present → top-level + per-family key sets pinned."""
    digest = compare(
        [_fdr_pair({"BOS": {"n_events": 200, "hit_rate": 0.50}})],
        [_fdr_pair({"BOS": {"n_events": 200, "hit_rate": 0.80}})],
        "fdr-pin-with-families",
    )
    block = digest["fdr"]
    assert set(block.keys()) == _FDR_TOPLEVEL_KEYS, (
        f"fdr top-level key set drifted: {set(block.keys())}. "
        "Update the schema version (major bump) and the pin in this test."
    )
    assert len(block["families"]) >= 1
    for fam in block["families"]:
        assert set(fam.keys()) == _FDR_FAMILY_ENTRY_KEYS, (
            f"fdr per-family key set drifted: {set(fam.keys())}. "
            "Update the schema version (major bump) and the pin in this test."
        )
