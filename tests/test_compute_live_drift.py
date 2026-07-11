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


def test_ks_two_sample_empty_returns_not_evaluable() -> None:
    # Stat-review F12: empty input is "not evaluable" (p=None), matching
    # scripts.drift_alert.ks_two_sample — NOT (0.0, 1.0) = "perfectly
    # compatible", which was a latent p=1.0 laundering.
    assert ks_two_sample([], [1.0, 2.0]) == (0.0, None)
    assert ks_two_sample([1.0], []) == (0.0, None)
    assert ks_two_sample([], []) == (0.0, None)


def test_ks_two_sample_empty_semantics_match_drift_alert_twin() -> None:
    # The shared _kolmogorov module exists to keep the twins identical;
    # this pins the empty-input convention on both sides (F12).
    from scripts.drift_alert import ks_two_sample as alert_ks

    assert ks_two_sample([], [1.0]) == alert_ks([], [1.0])
    assert ks_two_sample([1.0], []) == alert_ks([1.0], [])


def test_compute_live_drift_emits_cadence_fields() -> None:
    # Stat-review F7: √252 annualisation of per-trade returns is
    # cadence-blind; the artifact must disclose observed trades/year on
    # both sides so the operator can see the confound.
    returns = _make_returns(0.01, 0.005, 30, seed=7)
    rows = [{"variant": "v1", "return": r} for r in returns]
    out = compute_live_drift(
        live_rows=rows,
        backtest_reference={
            "v1": {"sharpe": 1.0, "n_trades": 504, "window_days": 365.25},
        },
        live_window_days=90,
    )
    v = out["variants"][0]
    assert v["trades_per_year_live"] == pytest.approx(30 * 365.25 / 90, abs=0.01)
    assert v["trades_per_year_backtest"] == pytest.approx(504.0, abs=0.01)


def test_compute_live_drift_cadence_backtest_none_when_unavailable() -> None:
    returns = _make_returns(0.01, 0.005, 30, seed=7)
    rows = [{"variant": "v1", "return": r} for r in returns]
    out = compute_live_drift(
        live_rows=rows,
        backtest_reference={"v1": {"sharpe": 1.0}},
    )
    v = out["variants"][0]
    assert v["trades_per_year_backtest"] is None
    assert v["trades_per_year_live"] is not None


def test_compute_live_drift_cadence_prefers_explicit_trades_per_year() -> None:
    returns = _make_returns(0.01, 0.005, 30, seed=7)
    rows = [{"variant": "v1", "return": r} for r in returns]
    out = compute_live_drift(
        live_rows=rows,
        backtest_reference={
            "v1": {
                "sharpe": 1.0,
                "trades_per_year": 120.0,
                "n_trades": 504,
                "window_days": 365.25,
            },
        },
    )
    assert out["variants"][0]["trades_per_year_backtest"] == pytest.approx(120.0)



# ── compute_live_drift ─────────────────────────────────────────────


def test_compute_live_drift_identical_to_backtest_passes() -> None:
    returns = _make_returns(0.01, 0.005, 30, seed=7)
    # W9-4: compute_live_drift scales trades_per_year dynamically.
    # We must match the same scaling factor in our test reference.
    tpy = len(returns) * 365.25 / 90
    live_sharpe = annualised_sharpe(returns, trades_per_year=tpy)
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
    # Live slippage (signed bps) way above the 50 bps expectation.
    returns = _make_returns(0.005, 0.01, 30, seed=2)
    rows = [{"variant": "v1", "return": r, "slippage": 500.0} for r in returns]
    out = compute_live_drift(
        live_rows=rows,
        backtest_reference={"v1": {"sharpe": 0.5}},
    )
    v = out["variants"][0]
    assert v["slippage_ks_p"] is not None
    assert v["slippage_ks_p"] < 0.001


def test_compute_live_drift_slippage_ks_passes_when_expected() -> None:
    # Live slippage (bps) drawn from the same distribution as the synthetic
    # reference default Normal(50, 30) bps (truth-audit F1: bps, not fraction).
    rng = np.random.default_rng(99)
    returns = _make_returns(0.005, 0.01, 60, seed=3)
    slips = rng.normal(50.0, 30.0, size=60).tolist()
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


def _bos_megacap_rows(seed: int) -> list[dict[str, object]]:
    returns = _make_returns(0.004, 0.01, 30, seed=seed)
    rng = np.random.default_rng(seed + 100)
    slips = rng.normal(2.0, 8.0, size=30).tolist()
    return [
        {"variant": "BOS_megacap", "return": r, "slippage": s}
        for r, s in zip(returns, slips, strict=True)
    ]


def test_compute_live_drift_real_fills_reference_flips_to_backtest_samples(
    tmp_path,
) -> None:
    """Truth-audit F2: only real-fill samples → ``backtest_samples`` type."""
    from scripts.build_backtest_slippage_samples import (
        SCHEMA_VERSION,
        build_payload,
    )
    from scripts.compute_live_drift import _atomic_write_json

    rng = np.random.default_rng(5)
    real_fills = {f: rng.normal(2.0, 8.0, size=120).tolist()
                  for f in ("BOS", "OB", "FVG", "SWEEP")}
    sample_payload = build_payload(
        real_fills_by_family=real_fills, mode="real_fills", min_per_family=120
    )
    assert sample_payload["schema_version"] == SCHEMA_VERSION
    assert sample_payload["families"]["BOS"]["source"] == "real_fills"
    sample_path = tmp_path / "slippage.json"
    _atomic_write_json(sample_path, sample_payload)

    out = compute_live_drift(
        live_rows=_bos_megacap_rows(11),
        backtest_reference={"BOS_megacap": {"sharpe": 0.5}},
        slippage_reference=sample_path,
    )
    assert out["variants"][0]["slippage_ks_reference_type"] == "backtest_samples"

    # Without any slippage reference → synthetic_normal (unchanged).
    out_no_ref = compute_live_drift(
        live_rows=_bos_megacap_rows(11),
        backtest_reference={"BOS_megacap": {"sharpe": 0.5}},
    )
    assert out_no_ref["variants"][0]["slippage_ks_reference_type"] == "synthetic_normal"


def test_compute_live_drift_replay_reference_does_not_launder(tmp_path) -> None:
    """Truth-audit F2: replay samples label as ``replay_samples``, NOT backtest_samples."""
    from scripts.build_backtest_slippage_samples import build_payload
    from scripts.compute_live_drift import _atomic_write_json

    sample_path = tmp_path / "slippage.json"
    _atomic_write_json(
        sample_path,
        build_payload(real_fills_by_family=None, mode="replay", min_per_family=120),
    )
    out = compute_live_drift(
        live_rows=_bos_megacap_rows(12),
        backtest_reference={"BOS_megacap": {"sharpe": 0.5}},
        slippage_reference=sample_path,
    )
    assert out["variants"][0]["slippage_ks_reference_type"] == "replay_samples"


def test_phase_b_gate_blocks_replay_but_passes_real_fills(tmp_path) -> None:
    """Truth-audit F2: the Phase-B readiness gate only passes real-fill references."""
    from scripts import check_phase_b_drift_readiness as gate
    from scripts.build_backtest_slippage_samples import build_payload
    from scripts.compute_live_drift import _atomic_write_json

    # Replay reference → gate NOT ready (was EXIT_OK before the fix).
    replay_path = tmp_path / "slippage_replay.json"
    _atomic_write_json(replay_path, build_payload(mode="replay", min_per_family=100))
    replay_report = compute_live_drift(
        live_rows=_bos_megacap_rows(13),
        backtest_reference={"BOS_megacap": {"sharpe": 0.5}},
        slippage_reference=replay_path,
    )
    replay_drift = tmp_path / "drift_replay.json"
    _atomic_write_json(replay_drift, replay_report)
    assert gate.main([str(replay_drift)]) == gate.EXIT_NOT_READY

    # Real-fill reference → gate ready.
    rng = np.random.default_rng(6)
    real_fills = {f: rng.normal(2.0, 8.0, size=100).tolist()
                  for f in ("BOS", "OB", "FVG", "SWEEP")}
    real_path = tmp_path / "slippage_real.json"
    _atomic_write_json(
        real_path,
        build_payload(real_fills_by_family=real_fills, mode="real_fills", min_per_family=100),
    )
    real_report = compute_live_drift(
        live_rows=_bos_megacap_rows(14),
        backtest_reference={"BOS_megacap": {"sharpe": 0.5}},
        slippage_reference=real_path,
    )
    real_drift = tmp_path / "drift_real.json"
    _atomic_write_json(real_drift, real_report)
    assert gate.main([str(real_drift)]) == gate.EXIT_OK
