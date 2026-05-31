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

