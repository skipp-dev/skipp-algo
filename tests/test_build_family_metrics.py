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

from scripts.build_family_metrics import (
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
    with pytest.raises(Exception):  # noqa: B017 - LookaheadError subclasses ValueError
        build_family_metrics_from_returns(
            "BOS", returns, timestamps=timestamps, as_of="2026-06-30T23:59:59"
        )


def test_timestamp_length_mismatch_raises() -> None:
    returns = _positive_edge_returns(n=40)
    with pytest.raises(ValueError, match="length"):
        build_family_metrics_from_returns(
            "BOS", returns, timestamps=["2026-01-01T00:00:00"], as_of="2026-06-30"
        )


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
    for field in ("brier", "ece", "psi", "live_brier", "walkforward_brier"):
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


