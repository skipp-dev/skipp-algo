"""EV-06 (scaffold) — per-family PSR/MinTRL metrics producer tests.

Verifies the producer computes real statistics, enforces the EV-04
lookahead tripwire, refuses too-small samples, and emits a bundle that
``run_promotion_gate.py`` can load — without fabricating any data.
"""
from __future__ import annotations

import json
import random
import tempfile
from pathlib import Path

import pytest

from governance.point_in_time import LookaheadError
from scripts.build_family_metrics import (
    _brier_block_bootstrap_ci_upper,
    build_bundle,
    build_family_metrics_from_returns,
)
from scripts.run_promotion_gate import _load_bundle


def _positive_edge_returns(n: int = 80, seed: int = 7) -> list[float]:
    rng = random.Random(seed)
    # Small positive drift with noise → a detectable (if modest) edge.
    return [0.001 + rng.gauss(0.0, 0.01) for _ in range(n)]


def test_produces_psr_and_mintrl_fields() -> None:
    metrics = build_family_metrics_from_returns("BOS", _positive_edge_returns())
    assert metrics["family"] == "BOS"
    assert 0.0 <= metrics["psr"] <= 1.0
    # provenance the producer genuinely owns
    assert metrics["provenance"]["psr_method"] == "bailey_lopez_de_prado_2012"
    assert metrics["provenance"]["wf_scheme"] == "expanding"
    assert metrics["provenance"]["wf_embargo_bars"] == 16  # 2 * 8 for BOS
    # honestly-unmeasured fields stay None
    assert metrics["brier"] is None
    assert metrics["fdr_pvalue"] is None
    # C4: the RAW per-family p-value is computed and carried in extras; the
    # FDR-adjusted fdr_pvalue is filled only at the bundle level.
    assert 0.0 < metrics["extras"]["raw_pvalue"] <= 1.0
    assert metrics["provenance"]["fdr_method"] == "benjamini_hochberg"


def test_too_few_returns_raises() -> None:
    with pytest.raises(ValueError, match="at least"):
        build_family_metrics_from_returns("BOS", [0.001] * 10)


def test_lookahead_timestamp_is_rejected() -> None:
    returns = _positive_edge_returns(n=40)
    # Last timestamp is after as_of → must raise (EV-04 negative control).
    timestamps = [f"2026-01-{(i % 28) + 1:02d}T10:00:00" for i in range(40)]
    timestamps[-1] = "2026-12-31T10:00:00"
    with pytest.raises(LookaheadError, match="lookahead leak"):
        build_family_metrics_from_returns(
            "BOS", returns, timestamps=timestamps, as_of="2026-06-30T23:59:59"
        )


def test_timestamp_length_mismatch_raises() -> None:
    returns = _positive_edge_returns(n=40)
    with pytest.raises(ValueError, match="length"):
        build_family_metrics_from_returns(
            "BOS", returns, timestamps=["2026-01-01T00:00:00"], as_of="2026-06-30"
        )


def test_observed_periods_per_year_derived_from_timestamp_span() -> None:
    # 40 events spaced exactly one day apart → span = 39 days. The realized
    # events-per-year cadence is n / (span_years) and must be surfaced as an
    # EV-20 time-basis diagnostic WITHOUT touching the declared annualization.
    import datetime as _dt

    returns = _positive_edge_returns(n=40)
    base = _dt.datetime(2026, 1, 1, 10, 0, 0)
    timestamps = [(base + _dt.timedelta(days=i)).isoformat() for i in range(40)]
    metrics = build_family_metrics_from_returns(
        "BOS", returns, timestamps=timestamps, as_of="2026-06-30T23:59:59"
    )
    span_years = 39.0 / 365.25
    expected = 40.0 / span_years
    observed = metrics["extras"]["observed_periods_per_year"]
    assert observed == pytest.approx(expected, rel=1e-9)
    # The declared annualization basis is untouched (gate semantics stable).
    assert metrics["extras"]["periods_per_year"] == 252.0


def test_observed_periods_per_year_absent_without_timestamps() -> None:
    # No timestamps → no cadence can be observed → diagnostic key is omitted
    # (the key only ever appears when it was genuinely measured).
    metrics = build_family_metrics_from_returns("BOS", _positive_edge_returns())
    assert "observed_periods_per_year" not in metrics["extras"]


def test_no_detectable_edge_leaves_mintrl_none() -> None:
    # Zero-mean noise → sr_hat <= sr_star → MinTRL undefined → None.
    rng = random.Random(3)
    flat = [rng.gauss(0.0, 0.01) for _ in range(60)]
    metrics = build_family_metrics_from_returns("FVG", flat)
    # psr always present; mintrl may be None when no edge is detectable.
    assert metrics["psr"] is not None
    if metrics["extras"]["sharpe_hat"] <= 0.0:
        assert metrics["mintrl_years"] is None


def test_build_bundle_round_trip_and_gate_loadable() -> None:
    spec = {
        "periods_per_year": 252,
        "families": {
            "BOS": {"returns": _positive_edge_returns(seed=1)},
            "OB": {"returns": _positive_edge_returns(seed=2)},
        },
    }
    bundle = build_bundle(spec)
    assert {m["family"] for m in bundle} == {"BOS", "OB"}

    # The bundle must be loadable by the production gate CLI loader.
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "bundle.json"
        p.write_text(json.dumps(bundle), encoding="utf-8")
        loaded = _load_bundle(p)
    assert {fm.family for fm in loaded} == {"BOS", "OB"}


def test_build_bundle_requires_returns() -> None:
    with pytest.raises(ValueError, match="returns"):
        build_bundle({"families": {"BOS": {}}})


def test_bundle_fills_bh_adjusted_fdr_pvalue() -> None:
    spec = {
        "periods_per_year": 252,
        "families": {
            "BOS": {"returns": _positive_edge_returns(seed=1)},
            "OB": {"returns": _positive_edge_returns(seed=2)},
            "FVG": {"returns": _positive_edge_returns(seed=3)},
        },
    }
    bundle = build_bundle(spec)
    by_family = {m["family"]: m for m in bundle}
    for fam, metric in by_family.items():
        q = metric["fdr_pvalue"]
        raw = metric["extras"]["raw_pvalue"]
        # fdr_pvalue is now populated (no longer None) and is a valid q-value.
        assert q is not None
        assert 0.0 <= q <= 1.0
        # BH adjustment never makes a p-value MORE significant than its raw.
        assert q >= raw - 1e-12, f"{fam}: q {q} < raw {raw}"


def test_non_positive_periods_per_year_raises() -> None:
    with pytest.raises(ValueError, match="periods_per_year must be positive"):
        build_family_metrics_from_returns(
            "BOS", _positive_edge_returns(), periods_per_year=0
        )


def test_alpha_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="alpha must be in"):
        build_family_metrics_from_returns("BOS", _positive_edge_returns(), alpha=1.5)


def test_one_sided_timestamp_guard_raises() -> None:
    returns = _positive_edge_returns(n=40)
    # timestamps without as_of must not silently skip the EV-04 guard.
    with pytest.raises(ValueError, match="provided together"):
        build_family_metrics_from_returns(
            "BOS", returns, timestamps=["2026-01-01T00:00:00"] * 40
        )
    # as_of without timestamps is equally rejected.
    with pytest.raises(ValueError, match="provided together"):
        build_family_metrics_from_returns("BOS", returns, as_of="2026-06-30")


# ---- EV-15 calibration slice -------------------------------------------


def _calibrated_pairs(n: int = 60, seed: int = 11) -> dict[str, list[float]]:
    """A well-calibrated synthetic (probabilities, outcomes) pair."""
    rng = random.Random(seed)
    probs: list[float] = []
    outcomes: list[float] = []
    for _ in range(n):
        p = rng.uniform(0.05, 0.95)
        probs.append(p)
        outcomes.append(1.0 if rng.random() < p else 0.0)
    return {"probabilities": probs, "outcomes": outcomes}


def test_calibration_fills_brier_ece_when_supplied() -> None:
    wf = _calibrated_pairs(seed=21)
    metrics = build_family_metrics_from_returns(
        "BOS",
        _positive_edge_returns(),
        calibration={"walkforward": wf},
    )
    # brier and walkforward_brier are the SAME measurement (WF out-of-sample).
    assert metrics["brier"] is not None
    assert 0.0 <= metrics["brier"] <= 1.0
    assert metrics["walkforward_brier"] == metrics["brier"]
    assert metrics["ece"] is not None
    assert 0.0 <= metrics["ece"] <= 1.0
    assert metrics["provenance"]["calibration_method"] == "empirical_brier_ece_psi"
    # not supplied → still honestly None
    assert metrics["live_brier"] is None
    assert metrics["psi"] is None


def test_brier_ci_upper_computed_and_brackets_point_estimate() -> None:
    # 60 samples (> BRIER_CI_MIN_SAMPLES) → CI is measured. The block-bootstrap
    # upper bound must be a valid probability and sit at or above the point
    # Brier (an upper confidence bound is never below the central estimate).
    wf = _calibrated_pairs(n=60, seed=21)
    metrics = build_family_metrics_from_returns(
        "BOS", _positive_edge_returns(), calibration={"walkforward": wf}
    )
    assert metrics["brier_ci_upper"] is not None
    assert 0.0 <= metrics["brier_ci_upper"] <= 1.0
    assert metrics["brier_ci_upper"] >= metrics["brier"] - 1e-9
    assert (
        metrics["provenance"]["brier_ci_method"]
        == "stationary_block_bootstrap_brier_p95"
    )


def test_brier_ci_upper_is_deterministic() -> None:
    # Pinned seed → identical CI across runs (audit reproducibility).
    pairs = _calibrated_pairs(n=80, seed=5)
    p, y = pairs["probabilities"], pairs["outcomes"]
    assert _brier_block_bootstrap_ci_upper(p, y) == _brier_block_bootstrap_ci_upper(
        p, y
    )


def test_brier_ci_upper_none_below_min_samples() -> None:
    # Too few OOS events → the interval is too noisy to trust, so it stays
    # "not yet measured" (None) rather than shipping a misleading bound.
    wf = _calibrated_pairs(n=20, seed=21)
    metrics = build_family_metrics_from_returns(
        "BOS", _positive_edge_returns(), calibration={"walkforward": wf}
    )
    assert metrics["brier"] is not None  # point estimate still measured
    assert metrics["brier_ci_upper"] is None
    assert "brier_ci_method" not in metrics["provenance"]


def test_calibration_live_and_psi() -> None:
    wf = _calibrated_pairs(seed=22)
    live = _calibrated_pairs(seed=23)
    metrics = build_family_metrics_from_returns(
        "OB",
        _positive_edge_returns(seed=4),
        calibration={
            "walkforward": wf,
            "live": live,
            "reference_probabilities": wf["probabilities"],
        },
    )
    assert metrics["live_brier"] is not None
    assert 0.0 <= metrics["live_brier"] <= 1.0
    assert metrics["psi"] is not None
    assert metrics["psi"] >= 0.0


def test_no_calibration_leaves_calibration_fields_none() -> None:
    metrics = build_family_metrics_from_returns("FVG", _positive_edge_returns())
    for field in (
        "brier",
        "brier_ci_upper",
        "ece",
        "psi",
        "live_brier",
        "walkforward_brier",
    ):
        assert metrics[field] is None
    assert "calibration_method" not in metrics["provenance"]


def test_calibration_rejects_out_of_range_probability() -> None:
    bad = {"probabilities": [0.2, 1.5, 0.4], "outcomes": [0.0, 1.0, 1.0]}
    with pytest.raises(ValueError, match=r"probabilities must lie in \[0, 1\]"):
        build_family_metrics_from_returns(
            "BOS", _positive_edge_returns(), calibration={"walkforward": bad}
        )


def test_calibration_rejects_non_binary_outcome() -> None:
    bad = {"probabilities": [0.2, 0.6, 0.4], "outcomes": [0.0, 0.5, 1.0]}
    with pytest.raises(ValueError, match="outcomes must be binary"):
        build_family_metrics_from_returns(
            "BOS", _positive_edge_returns(), calibration={"live": bad}
        )


def test_calibration_length_mismatch_raises() -> None:
    bad = {"probabilities": [0.2, 0.6], "outcomes": [0.0]}
    with pytest.raises(ValueError, match="length"):
        build_family_metrics_from_returns(
            "BOS", _positive_edge_returns(), calibration={"walkforward": bad}
        )


def test_psi_without_live_distribution_raises() -> None:
    with pytest.raises(ValueError, match=r"PSI needs calibration\.live"):
        build_family_metrics_from_returns(
            "BOS",
            _positive_edge_returns(),
            calibration={"reference_probabilities": [0.2, 0.4, 0.6]},
        )


def test_bundle_threads_calibration_per_family() -> None:
    spec = {
        "periods_per_year": 252,
        "families": {
            "BOS": {
                "returns": _positive_edge_returns(seed=1),
                "calibration": {"walkforward": _calibrated_pairs(seed=31)},
            },
            "OB": {"returns": _positive_edge_returns(seed=2)},
        },
    }
    bundle = build_bundle(spec)
    by_family = {m["family"]: m for m in bundle}
    # BOS got calibration → brier measured; OB did not → stays None.
    assert by_family["BOS"]["brier"] is not None
    assert by_family["OB"]["brier"] is None


# ---- EV-16 conformal slice ---------------------------------------------


def _conformal_block(alpha: float = 0.1, seed: int = 41) -> dict[str, object]:
    cal = _calibrated_pairs(n=120, seed=seed)
    test = _calibrated_pairs(n=120, seed=seed + 1)
    return {
        "alpha": alpha,
        "calibration": cal,
        "test": test,
    }


def test_conformal_fills_coverage_and_target() -> None:
    metrics = build_family_metrics_from_returns(
        "BOS",
        _positive_edge_returns(),
        conformal=_conformal_block(alpha=0.1),
    )
    assert metrics["conformal_coverage"] is not None
    assert 0.0 <= metrics["conformal_coverage"] <= 1.0
    assert metrics["conformal_target"] == pytest.approx(0.9)
    assert metrics["provenance"]["conformal_method"] == "split_conformal_vovk"


def test_no_conformal_leaves_fields_none() -> None:
    metrics = build_family_metrics_from_returns("FVG", _positive_edge_returns())
    assert metrics["conformal_coverage"] is None
    assert metrics["conformal_target"] is None
    assert "conformal_method" not in metrics["provenance"]


def test_conformal_rejects_bad_alpha() -> None:
    block = _conformal_block()
    block["alpha"] = 1.5
    with pytest.raises(ValueError, match="conformal alpha must be in"):
        build_family_metrics_from_returns(
            "BOS", _positive_edge_returns(), conformal=block
        )


def test_conformal_requires_both_sets() -> None:
    with pytest.raises(ValueError, match="both 'calibration' and 'test'"):
        build_family_metrics_from_returns(
            "BOS",
            _positive_edge_returns(),
            conformal={"calibration": _calibrated_pairs(seed=51)},
        )


def test_conformal_marginal_coverage_holds() -> None:
    # Split-conformal guarantees marginal coverage >= 1 - alpha (finite-sample,
    # with the (n+1) correction). On well-calibrated data with large sets it
    # should comfortably meet the target.
    metrics = build_family_metrics_from_returns(
        "BOS",
        _positive_edge_returns(),
        conformal=_conformal_block(alpha=0.2, seed=61),
    )
    assert metrics["conformal_coverage"] >= metrics["conformal_target"] - 0.15


def test_bundle_threads_conformal_per_family() -> None:
    spec = {
        "periods_per_year": 252,
        "families": {
            "BOS": {
                "returns": _positive_edge_returns(seed=1),
                "conformal": _conformal_block(seed=71),
            },
            "OB": {"returns": _positive_edge_returns(seed=2)},
        },
    }
    bundle = build_bundle(spec)
    by_family = {m["family"]: m for m in bundle}
    assert by_family["BOS"]["conformal_coverage"] is not None
    assert by_family["OB"]["conformal_coverage"] is None


# EV-17 — caller-declared upstream provenance pass-through.

_STRICT_PROVENANCE = {
    "bootstrap_method": "bca",
    "block_size": 64,
    "stacked_used": True,
}


def test_caller_provenance_is_passed_through() -> None:
    metrics = build_family_metrics_from_returns(
        "BOS",
        _positive_edge_returns(),
        provenance=dict(_STRICT_PROVENANCE),
    )
    prov = metrics["provenance"]
    # Caller-declared upstream keys appear verbatim...
    assert prov["bootstrap_method"] == "bca"
    assert prov["block_size"] == 64
    assert prov["stacked_used"] is True
    # ...alongside the keys the producer computes itself.
    assert prov["psr_method"] == "bailey_lopez_de_prado_2012"
    assert prov["wf_scheme"] is not None


def test_no_caller_provenance_leaves_strict_keys_undeclared() -> None:
    metrics = build_family_metrics_from_returns("FVG", _positive_edge_returns())
    prov = metrics["provenance"]
    # Absent → undeclared → the strict gate blocks honestly.
    assert "bootstrap_method" not in prov
    assert "block_size" not in prov
    assert "stacked_used" not in prov


def test_caller_provenance_cannot_override_producer_owned_keys() -> None:
    with pytest.raises(ValueError, match="may not override producer-owned keys"):
        build_family_metrics_from_returns(
            "BOS",
            _positive_edge_returns(),
            provenance={"wf_scheme": "forged", "bootstrap_method": "bca"},
        )


def test_caller_provenance_rejects_non_mapping() -> None:
    with pytest.raises(ValueError, match="provenance must be a mapping"):
        build_family_metrics_from_returns(
            "BOS",
            _positive_edge_returns(),
            provenance=["bca"],  # type: ignore[arg-type]
        )


def test_bundle_threads_provenance_per_family() -> None:
    spec = {
        "periods_per_year": 252,
        "families": {
            "BOS": {
                "returns": _positive_edge_returns(seed=1),
                "provenance": dict(_STRICT_PROVENANCE),
            },
            "OB": {"returns": _positive_edge_returns(seed=2)},
        },
    }
    bundle = build_bundle(spec)
    by_family = {m["family"]: m for m in bundle}
    assert by_family["BOS"]["provenance"]["stacked_used"] is True
    assert "stacked_used" not in by_family["OB"]["provenance"]


# EV-18 (C9) — PSI-trend slope producer.


def _drifting_windows(
    base: float = 0.3, step: float = 0.05, k: int = 5, n: int = 40, seed: int = 3
) -> dict[str, object]:
    """Reference + k windows whose mean probability drifts upward each step.

    Increasing drift over windows yields a positive PSI slope (worsening
    stability), which is what the gate alarms on.
    """
    rng = random.Random(seed)
    reference = [rng.uniform(0.2, 0.4) for _ in range(n)]
    windows: list[list[float]] = []
    for w in range(k):
        centre = base + step * w
        windows.append(
            [min(0.99, max(0.01, rng.gauss(centre, 0.03))) for _ in range(n)]
        )
    return {"reference_probabilities": reference, "windows": windows}


def test_psi_trend_fills_psi_slope_when_supplied() -> None:
    metrics = build_family_metrics_from_returns(
        "BOS",
        _positive_edge_returns(),
        psi_trend=_drifting_windows(),
    )
    assert metrics["psi_slope"] is not None
    # Upward drift → positive slope.
    assert metrics["psi_slope"] > 0.0
    assert metrics["provenance"]["psi_trend_method"] == "ols_psi_window_slope"


def test_no_psi_trend_leaves_slope_none() -> None:
    metrics = build_family_metrics_from_returns("FVG", _positive_edge_returns())
    assert metrics["psi_slope"] is None
    assert "psi_trend_method" not in metrics["provenance"]


def test_psi_trend_stable_windows_give_near_zero_slope() -> None:
    # No drift between windows → slope should sit near zero.
    metrics = build_family_metrics_from_returns(
        "BOS",
        _positive_edge_returns(),
        psi_trend=_drifting_windows(step=0.0, seed=9),
    )
    assert metrics["psi_slope"] == pytest.approx(0.0, abs=0.05)


def test_psi_trend_requires_two_windows() -> None:
    with pytest.raises(ValueError, match="at least 2 windows"):
        build_family_metrics_from_returns(
            "BOS",
            _positive_edge_returns(),
            psi_trend={
                "reference_probabilities": [0.3, 0.4, 0.5],
                "windows": [[0.3, 0.4, 0.5]],
            },
        )


def test_psi_trend_requires_reference_and_windows() -> None:
    with pytest.raises(ValueError, match="needs both 'reference_probabilities'"):
        build_family_metrics_from_returns(
            "BOS",
            _positive_edge_returns(),
            psi_trend={"windows": [[0.3], [0.4]]},
        )


def test_psi_trend_rejects_out_of_range_window() -> None:
    with pytest.raises(ValueError, match=r"windows\[1\] must lie in \[0, 1\]"):
        build_family_metrics_from_returns(
            "BOS",
            _positive_edge_returns(),
            psi_trend={
                "reference_probabilities": [0.3, 0.4, 0.5],
                "windows": [[0.3, 0.4], [0.4, 1.5]],
            },
        )


def test_bundle_threads_psi_trend_per_family() -> None:
    spec = {
        "periods_per_year": 252,
        "families": {
            "BOS": {
                "returns": _positive_edge_returns(seed=1),
                "psi_trend": _drifting_windows(seed=4),
            },
            "OB": {"returns": _positive_edge_returns(seed=2)},
        },
    }
    bundle = build_bundle(spec)
    by_family = {m["family"]: m for m in bundle}
    assert by_family["BOS"]["psi_slope"] is not None
    assert by_family["OB"]["psi_slope"] is None

