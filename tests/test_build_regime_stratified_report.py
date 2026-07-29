"""Tests for ``scripts/build_regime_stratified_report.py`` (C5 producer, ADR-0031)."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.build_regime_stratified_report import build_regime_report, main
from scripts.regime_stratification import MIN_TRADES_PER_REGIME


def _trades(regime: str, n: int, pnl: float) -> list[dict]:
    return [{"pnl": pnl, "regime_at_entry": regime} for _ in range(n)]


def test_empty_trades_yield_insufficient_shell() -> None:
    report = build_regime_report([], date="2026-07-29", measurement={"cost_bps": 5.0})
    assert report["status"] == "insufficient_data"
    assert report["n_trades_with_regime"] == 0
    assert "per_regime" not in report


def test_below_floor_regimes_are_skipped_not_invented() -> None:
    trades = _trades("TRENDING", MIN_TRADES_PER_REGIME - 1, 0.01)
    report = build_regime_report(trades, date="2026-07-29", measurement=None)
    assert report["status"] == "insufficient_data"
    assert report["per_regime"]["TRENDING"]["skipped_reason"] == "insufficient_n"
    boot = report["stratified_bootstrap"]
    assert boot["observed"] is None
    assert boot["skipped_regimes"] == ["TRENDING"]


def test_sufficient_regime_gets_metrics_and_deterministic_ci() -> None:
    trades = _trades("TRENDING", MIN_TRADES_PER_REGIME, 0.01) + _trades(
        "RANGING", MIN_TRADES_PER_REGIME, -0.005
    )
    r1 = build_regime_report(trades, date="2026-07-29", measurement=None)
    r2 = build_regime_report(trades, date="2026-07-29", measurement=None)
    assert r1["status"] == "ok"
    trending = r1["per_regime"]["TRENDING"]
    assert trending["n"] == MIN_TRADES_PER_REGIME
    assert trending["win_rate"] == 1.0
    assert abs(trending["regime_frequency_pct"] - 0.5) < 1e-9
    boot = r1["stratified_bootstrap"]
    assert boot["observed"] is not None
    # fixed seed → byte-identical report on re-run
    assert r1 == r2


def test_unknown_share_warning_when_untagged_majority() -> None:
    """A clean stratification must not hide an untagged majority (C5 deep-review)."""
    trades = _trades("TRENDING", MIN_TRADES_PER_REGIME, 0.01)
    report = build_regime_report(
        trades, date="2026-07-29", measurement=None, n_trades_total=MIN_TRADES_PER_REGIME * 10
    )
    assert report["n_trades_total"] == MIN_TRADES_PER_REGIME * 10
    assert "warning" in report["aggregate"]


def test_cli_roundtrip(tmp_path: Path) -> None:
    series = {
        "n_trades": MIN_TRADES_PER_REGIME + 5,
        "measurement": {"return_rule": "touch_then_horizon_close", "cost_bps": 5.0},
        "trades": _trades("NEUTRAL", MIN_TRADES_PER_REGIME, 0.02),
    }
    series_path = tmp_path / "series.json"
    series_path.write_text(json.dumps(series), encoding="utf-8")
    out = tmp_path / "regime.json"
    rc = main(["--series", str(series_path), "--date", "2026-07-29", "--output", str(out)])
    assert rc == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["status"] == "ok"
    assert report["measurement"]["return_rule"] == "touch_then_horizon_close"
    assert report["per_regime"]["NEUTRAL"]["n"] == MIN_TRADES_PER_REGIME
