"""Tests for scripts/compute_live_drift.py (C8/T4)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from scripts.compute_live_drift import (
    DriftVerdict,
    annualised_sharpe,
    compute_live_drift,
    drift_score,
    ks_two_sample,
    main,
)


def _make_returns(mean: float, std: float, n: int, seed: int) -> list[float]:
    rng = np.random.default_rng(seed)
    return rng.normal(loc=mean, scale=std, size=n).tolist()


# ── unit ────────────────────────────────────────────────────────────


def test_annualised_sharpe_zero_when_too_few_samples() -> None:
    assert annualised_sharpe([]) == 0.0
    assert annualised_sharpe([0.01]) == 0.0


def test_annualised_sharpe_zero_when_zero_std() -> None:
    assert annualised_sharpe([0.01, 0.01, 0.01, 0.01]) == 0.0


def test_annualised_sharpe_positive_for_positive_returns() -> None:
    sh = annualised_sharpe(_make_returns(0.01, 0.005, 100, seed=1))
    assert sh > 0.0


def test_drift_score_identical_returns_one() -> None:
    assert drift_score(0.93, 0.93) == pytest.approx(1.0, rel=1e-6)


def test_drift_score_zero_live_returns_zero() -> None:
    assert drift_score(0.0, 1.0) == 0.0


def test_drift_score_capped_at_1_5() -> None:
    assert drift_score(10.0, 1.0) == 1.5


def test_drift_score_handles_zero_backtest() -> None:
    # 1.0 / 0.001 = 1000, capped to 1.5
    assert drift_score(1.0, 0.0) == 1.5


def test_ks_two_sample_identical_distributions_high_p() -> None:
    rng = np.random.default_rng(42)
    a = rng.normal(0, 1, size=300).tolist()
    b = rng.normal(0, 1, size=300).tolist()
    _, p = ks_two_sample(a, b)
    assert p > 0.05


def test_ks_two_sample_different_distributions_low_p() -> None:
    rng = np.random.default_rng(42)
    a = rng.normal(0, 1, size=300).tolist()
    b = rng.normal(2.0, 1, size=300).tolist()
    d, p = ks_two_sample(a, b)
    assert d > 0.5
    assert p < 0.001


def test_ks_two_sample_empty_returns_neutral() -> None:
    assert ks_two_sample([], [1.0, 2.0]) == (0.0, 1.0)
    assert ks_two_sample([1.0], []) == (0.0, 1.0)


# ── compute_live_drift ─────────────────────────────────────────────


def test_compute_live_drift_identical_to_backtest_passes() -> None:
    returns = _make_returns(0.01, 0.005, 30, seed=7)
    live_sharpe = annualised_sharpe(returns)
    rows = [{"variant": "v1", "return": r} for r in returns]
    out = compute_live_drift(
        live_rows=rows,
        backtest_reference={"v1": {"sharpe": live_sharpe}},
    )
    assert len(out["variants"]) == 1
    v = out["variants"][0]
    assert v["variant"] == "v1"
    assert v["drift_score"] == pytest.approx(1.0, rel=1e-3)
    assert v["verdict"] == "pass"


def test_compute_live_drift_zero_live_fails() -> None:
    # Symmetric returns → mean ≈ 0 → live_sharpe ≈ 0 → drift_score ≈ 0.
    rows = [{"variant": "v1", "return": r} for r in [0.01, -0.01] * 15]
    out = compute_live_drift(
        live_rows=rows,
        backtest_reference={"v1": {"sharpe": 1.0}},
    )
    v = out["variants"][0]
    assert v["drift_score"] < 0.4
    assert v["verdict"] == "fail"


def test_compute_live_drift_below_min_trades_marked_insufficient() -> None:
    rows = [{"variant": "v1", "return": 0.01} for _ in range(5)]
    out = compute_live_drift(
        live_rows=rows,
        backtest_reference={"v1": {"sharpe": 1.0}},
        min_trades=15,
    )
    v = out["variants"][0]
    assert v["verdict"] == "insufficient_sample"
    assert v["n_live_trades"] == 5


def test_compute_live_drift_slippage_ks_fires_on_mismatch() -> None:
    # Live slippage way above the 0.5% expectation.
    returns = _make_returns(0.005, 0.01, 30, seed=2)
    rows = [{"variant": "v1", "return": r, "slippage": 0.05} for r in returns]
    out = compute_live_drift(
        live_rows=rows,
        backtest_reference={"v1": {"sharpe": 0.5}},
    )
    v = out["variants"][0]
    assert v["slippage_ks_p"] is not None
    assert v["slippage_ks_p"] < 0.001


def test_compute_live_drift_slippage_ks_passes_when_expected() -> None:
    # Live slippage drawn from the same distribution as the reference.
    rng = np.random.default_rng(99)
    returns = _make_returns(0.005, 0.01, 60, seed=3)
    slips = rng.normal(0.005, 0.003, size=60).tolist()
    rows = [
        {"variant": "v1", "return": r, "slippage": s}
        for r, s in zip(returns, slips, strict=True)
    ]
    out = compute_live_drift(
        live_rows=rows,
        backtest_reference={"v1": {"sharpe": 0.5}},
    )
    v = out["variants"][0]
    assert v["slippage_ks_p"] is not None
    assert v["slippage_ks_p"] > 0.05


def test_compute_live_drift_hit_rate_in_ci_true_when_inside() -> None:
    returns = _make_returns(0.005, 0.01, 30, seed=4)
    rows = [
        {"variant": "v1", "return": r, "hit": (i % 2 == 0)}
        for i, r in enumerate(returns)
    ]
    out = compute_live_drift(
        live_rows=rows,
        backtest_reference={
            "v1": {"sharpe": 0.5, "hit_rate_ci_low": 0.40, "hit_rate_ci_high": 0.60},
        },
    )
    assert out["variants"][0]["hr_in_bootstrap_ci"] is True


def test_compute_live_drift_hit_rate_in_ci_false_when_outside() -> None:
    returns = _make_returns(0.005, 0.01, 30, seed=5)
    rows = [{"variant": "v1", "return": r, "hit": True} for r in returns]
    out = compute_live_drift(
        live_rows=rows,
        backtest_reference={
            "v1": {"sharpe": 0.5, "hit_rate_ci_low": 0.40, "hit_rate_ci_high": 0.60},
        },
    )
    assert out["variants"][0]["hr_in_bootstrap_ci"] is False


def test_compute_live_drift_deterministic_with_fixed_now() -> None:
    rows = [{"variant": "v1", "return": 0.01} for _ in range(20)]
    fixed = datetime(2026, 4, 26, 13, 30, tzinfo=UTC)
    a = compute_live_drift(
        live_rows=rows, backtest_reference={"v1": {"sharpe": 1.0}}, now=fixed,
    )
    b = compute_live_drift(
        live_rows=rows, backtest_reference={"v1": {"sharpe": 1.0}}, now=fixed,
    )
    assert a == b
    assert a["computed_at"] == "2026-04-26T13:30:00+00:00"


def test_compute_live_drift_sorts_variants_alphabetically() -> None:
    rows = (
        [{"variant": "z_var", "return": 0.01} for _ in range(20)]
        + [{"variant": "a_var", "return": 0.01} for _ in range(20)]
    )
    out = compute_live_drift(
        live_rows=rows,
        backtest_reference={"a_var": {"sharpe": 1.0}, "z_var": {"sharpe": 1.0}},
    )
    assert [v["variant"] for v in out["variants"]] == ["a_var", "z_var"]


def test_compute_live_drift_requires_either_rows_or_path() -> None:
    with pytest.raises(ValueError, match="live_rows or live_jsonl"):
        compute_live_drift(backtest_reference={})


def test_compute_live_drift_requires_either_reference_or_path() -> None:
    with pytest.raises(ValueError, match="backtest_reference or backtest_calibration"):
        compute_live_drift(live_rows=[])


# ── reference-integrity verdicts (silent-fallback audit 2026-06-10) ─


def test_missing_backtest_reference_does_not_pass() -> None:
    """A variant absent from the reference must NOT score 1.5/pass via
    the 0.001 denominator clamp."""
    rows = [{"variant": "v1", "return": r} for r in _make_returns(0.01, 0.005, 30, seed=3)]
    out = compute_live_drift(
        live_rows=rows,
        backtest_reference={"other_variant": {"sharpe": 1.0}},
    )
    by_variant = {v["variant"]: v for v in out["variants"]}
    v1 = by_variant["v1"]
    assert v1["verdict"] == "missing_backtest_reference"
    assert v1["drift_score"] == 0.0


def test_non_numeric_backtest_sharpe_marked_missing() -> None:
    rows = [{"variant": "v1", "return": r} for r in _make_returns(0.01, 0.005, 30, seed=4)]
    out = compute_live_drift(
        live_rows=rows,
        backtest_reference={"v1": {"sharpe": "not-a-number"}},
    )
    v = next(item for item in out["variants"] if item["variant"] == "v1")
    assert v["verdict"] == "missing_backtest_reference"


def test_non_positive_backtest_sharpe_marked_explicitly() -> None:
    rows = [{"variant": "v1", "return": r} for r in _make_returns(0.01, 0.005, 30, seed=5)]
    out = compute_live_drift(
        live_rows=rows,
        backtest_reference={"v1": {"sharpe": 0.0}},
    )
    v = next(item for item in out["variants"] if item["variant"] == "v1")
    assert v["verdict"] == "non_positive_backtest_sharpe"
    assert v["drift_score"] == 0.0


def test_reference_only_variant_emitted_as_no_live_data() -> None:
    """A reference variant with zero live rows ("stopped trading") must
    not vanish from the artifact."""
    rows = [{"variant": "v1", "return": r} for r in _make_returns(0.01, 0.005, 30, seed=6)]
    out = compute_live_drift(
        live_rows=rows,
        backtest_reference={"v1": {"sharpe": 1.0}, "dormant": {"sharpe": 0.8}},
    )
    by_variant = {v["variant"]: v for v in out["variants"]}
    assert by_variant["dormant"]["verdict"] == "no_live_data"
    assert by_variant["dormant"]["n_live_trades"] == 0


def test_overperformance_capped_flag_set_when_ratio_exceeds_cap() -> None:
    returns = _make_returns(0.01, 0.005, 30, seed=7)
    live_sharpe = annualised_sharpe(returns)
    rows = [{"variant": "v1", "return": r} for r in returns]
    out = compute_live_drift(
        live_rows=rows,
        # backtest reference far below live → raw ratio > 1.5 cap
        backtest_reference={"v1": {"sharpe": live_sharpe / 10.0}},
    )
    v = out["variants"][0]
    assert v["drift_score"] == pytest.approx(1.5)
    assert v["overperformance_capped"] is True


def test_overperformance_capped_flag_false_for_healthy_pass() -> None:
    returns = _make_returns(0.01, 0.005, 30, seed=7)
    live_sharpe = annualised_sharpe(returns)
    rows = [{"variant": "v1", "return": r} for r in returns]
    out = compute_live_drift(
        live_rows=rows,
        backtest_reference={"v1": {"sharpe": live_sharpe}},
    )
    assert out["variants"][0]["overperformance_capped"] is False


# ── CLI / atomic write ─────────────────────────────────────────────


def test_main_end_to_end(tmp_path: Path) -> None:
    live = tmp_path / "live.jsonl"
    live.write_text(
        "\n".join(json.dumps({"variant": "v1", "return": 0.01}) for _ in range(20))
        + "\n",
        encoding="utf-8",
    )
    cal = tmp_path / "cal.json"
    cal.write_text(
        json.dumps({"backtest_reference": {"v1": {"sharpe": 1.0}}}),
        encoding="utf-8",
    )
    out = tmp_path / "drift.json"

    rc = main(
        [
            "--live-jsonl", str(live),
            "--backtest-calibration", str(cal),
            "--output", str(out),
            "--min-trades", "10",
        ],
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["live_window_days"] == 90
    assert payload["variants"][0]["variant"] == "v1"


def test_main_atomic_write_no_tmp_left_behind(tmp_path: Path) -> None:
    live = tmp_path / "live.jsonl"
    live.write_text(
        "\n".join(json.dumps({"variant": "v1", "return": 0.01}) for _ in range(20)),
        encoding="utf-8",
    )
    cal = tmp_path / "cal.json"
    cal.write_text(
        json.dumps({"backtest_reference": {"v1": {"sharpe": 1.0}}}),
        encoding="utf-8",
    )
    out = tmp_path / "drift.json"
    main(
        [
            "--live-jsonl", str(live),
            "--backtest-calibration", str(cal),
            "--output", str(out),
            "--min-trades", "10",
        ],
    )
    leftover = list(tmp_path.glob(".drift_*.tmp"))
    assert leftover == []


def test_drift_verdict_to_json_round_trip() -> None:
    v = DriftVerdict(
        variant="v",
        n_live_trades=20,
        live_sharpe=0.5,
        backtest_sharpe=1.0,
        drift_score=0.5,
        slippage_ks_p=0.1,
        hr_in_bootstrap_ci=True,
        verdict="acceptable",
        slippage_ks_reference_type="synthetic_normal",
    )
    payload = v.to_json()
    assert payload["variant"] == "v"
    assert payload["verdict"] == "acceptable"
    assert payload["hr_in_bootstrap_ci"] is True
    # C8 deep-review fix: KS reference is a synthetic normal, not a
    # real backtest-slippage sample — the marker must surface in the
    # JSON so downstream consumers do not over-trust the p-value.
    assert payload["slippage_ks_reference"] == "synthetic_normal"
    assert payload["slippage_ks_reference_type"] == "synthetic_normal"
    # C8 phase promotion is manual-signoff-only; this drift module
    # never auto-promotes between phase-A/B/C.
    assert payload["phase_promotion"] == "manual_signoff_only"


def test_drift_verdict_default_reference_type_is_unavailable() -> None:
    """No slippage data → reference_type must be ``unavailable``."""
    v = DriftVerdict(
        variant="v",
        n_live_trades=5,
        live_sharpe=0.0,
        backtest_sharpe=1.0,
        drift_score=0.0,
        slippage_ks_p=None,
        hr_in_bootstrap_ci=None,
        verdict="insufficient_sample",
    )
    payload = v.to_json()
    assert payload["slippage_ks_reference_type"] == "unavailable"
    assert payload["slippage_ks_reference"] == "unavailable"
    assert payload["slippage_ks_p"] is None


def test_drift_verdict_backtest_samples_reference_type() -> None:
    """When backtest_samples is supplied → reference_type must reflect it."""
    v = DriftVerdict(
        variant="v",
        n_live_trades=20,
        live_sharpe=0.7,
        backtest_sharpe=1.0,
        drift_score=0.7,
        slippage_ks_p=0.4,
        hr_in_bootstrap_ci=True,
        verdict="acceptable",
        slippage_ks_reference_type="backtest_samples",
    )
    payload = v.to_json()
    assert payload["slippage_ks_reference_type"] == "backtest_samples"
    # Legacy field reflects the new structured marker too.
    assert payload["slippage_ks_reference"] == "backtest_samples"


# ── C13/T4: --slippage-reference round-trip ─────────────────────────


def test_compute_live_drift_slippage_reference_flips_to_backtest_samples(
    tmp_path,
) -> None:
    """End-to-end: per-family slippage file → backtest_samples ref type."""
    from scripts.build_backtest_slippage_samples import (
        SCHEMA_VERSION,
        build_payload,
    )
    from scripts.compute_live_drift import _atomic_write_json

    # 1. Produce per-family slippage samples (replay-only for determinism).
    sample_payload = build_payload(
        real_fills_by_family=None, mode="replay", min_per_family=120
    )
    assert sample_payload["schema_version"] == SCHEMA_VERSION
    sample_path = tmp_path / "slippage.json"
    _atomic_write_json(sample_path, sample_payload)

    # 2. Live rows for a BOS_megacap variant with realistic slippage.
    returns = _make_returns(0.004, 0.01, 30, seed=11)
    rng = np.random.default_rng(7)
    slips = rng.normal(2.0, 8.0, size=30).tolist()
    rows = [
        {"variant": "BOS_megacap", "return": r, "slippage": s}
        for r, s in zip(returns, slips, strict=True)
    ]

    # 3. Compute drift WITH slippage reference.
    out = compute_live_drift(
        live_rows=rows,
        backtest_reference={"BOS_megacap": {"sharpe": 0.5}},
        slippage_reference=sample_path,
    )
    v = out["variants"][0]
    assert v["slippage_ks_reference_type"] == "backtest_samples"

    # 4. Without the slippage reference → falls back to synthetic_normal.
    out_no_ref = compute_live_drift(
        live_rows=rows,
        backtest_reference={"BOS_megacap": {"sharpe": 0.5}},
    )
    assert out_no_ref["variants"][0]["slippage_ks_reference_type"] == "synthetic_normal"


def test_compute_live_drift_slippage_reference_unblocks_phase_b_gate(
    tmp_path,
) -> None:
    """Drift-report + phase-B gate produced via --slippage-reference passes."""
    from scripts import check_phase_b_drift_readiness as gate
    from scripts.build_backtest_slippage_samples import build_payload
    from scripts.compute_live_drift import _atomic_write_json

    sample_path = tmp_path / "slippage.json"
    _atomic_write_json(
        sample_path,
        build_payload(mode="replay", min_per_family=100),
    )

    returns = _make_returns(0.004, 0.01, 30, seed=13)
    rng = np.random.default_rng(8)
    slips = rng.normal(2.0, 8.0, size=30).tolist()
    rows = [
        {"variant": "BOS_megacap", "return": r, "slippage": s}
        for r, s in zip(returns, slips, strict=True)
    ]

    drift_report = compute_live_drift(
        live_rows=rows,
        backtest_reference={"BOS_megacap": {"sharpe": 0.5}},
        slippage_reference=sample_path,
    )
    drift_path = tmp_path / "drift.json"
    _atomic_write_json(drift_path, drift_report)

    assert gate.main([str(drift_path)]) == gate.EXIT_OK
