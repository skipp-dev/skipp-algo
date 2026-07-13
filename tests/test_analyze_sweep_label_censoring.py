from __future__ import annotations

import json
from pathlib import Path

from scripts.analyze_sweep_label_censoring import (
    SweepObservation,
    bootstrap_intervals,
    join_sweep_observations,
    summarize_observations,
    timeframe_alignment_summary,
)


def _ledger(symbol: str, timeframe: str, timestamp: float, side: str, price: float, outcome: bool) -> dict:
    return {
        "schema_version": "1.0",
        "event_id": f"sweep:{symbol}:{timeframe}:{timestamp - 1}:{side}:{price:.2f}",
        "symbol": symbol,
        "timeframe": timeframe,
        "family": "SWEEP",
        "timestamp": timestamp,
        "predicted_prob": 0.5,
        "outcome": outcome,
        "context": {},
        "features": {},
        "outcome_extras": {},
    }


def _family(timestamp: float, direction: str, price: float, closes: list[float]) -> dict:
    return {
        "family": "SWEEP",
        "anchor_ts": timestamp,
        "direction": direction,
        "entry_mode": "immediate",
        "entry_price": price,
        "forward_closes": closes,
        "forward_highs": closes,
        "forward_lows": closes,
        "forward_timestamps": [timestamp + i + 1 for i in range(len(closes))],
    }


def test_join_and_identified_bounds_pin_right_censoring() -> None:
    ledger = [
        _ledger("AAA", "5m", 10.0, "SELL_SIDE", 100.0, False),
        _ledger("AAA", "5m", 20.0, "SELL_SIDE", 100.0, False),
        _ledger("BBB", "1D", 30.0, "SELL_SIDE", 100.0, True),
    ]
    families = [
        _family(10.0, "LONG", 100.0, [100.1] * 8),
        _family(20.0, "LONG", 100.0, [100.1] * 4),
        _family(30.0, "LONG", 100.0, [101.0, 101.0]),
    ]
    observations, join = join_sweep_observations(ledger, families)
    assert join["joined"] == 3
    assert join["unmatched_family_events"] == 0

    summary = summarize_observations(observations, horizon_bars=8, threshold_pct=0.005)
    canonical = summary["canonical"]
    assert canonical["censored"] == 2
    assert canonical["early_resolved_positive"] == 1
    assert canonical["unresolved_negative"] == 1
    assert canonical["observed_hit_rate"] == 0.333333
    assert canonical["identified_hit_rate_lower"] == 0.333333
    assert canonical["identified_hit_rate_upper"] == 0.666667

    late = summary["late_window_bars_4_to_8"]
    assert late["unresolved_negative"] == 2
    assert late["identified_hit_rate_lower"] == 0.0
    assert late["identified_hit_rate_upper"] == 0.666667


def test_ambiguous_identity_is_not_silently_joined() -> None:
    event = _ledger("AAA", "5m", 10.0, "SELL_SIDE", 100.0, False)
    duplicate = {**event, "event_id": "sweep:BBB:5m:9:SELL_SIDE:100.00", "symbol": "BBB"}
    observations, join = join_sweep_observations([event, duplicate], [_family(10.0, "LONG", 100.0, [100.1] * 8)])
    assert observations == []
    assert join["ambiguous_family_events"] == 1


def test_join_uses_forward_spacing_and_event_id_price_precision() -> None:
    ledger = [
        _ledger("AAA", "5m", 10.0, "BUY_SIDE", 242.41, False),
        _ledger("AAA", "10m", 10.0, "BUY_SIDE", 242.41, False),
    ]
    family = _family(10.0, "SHORT", 242.405, [241.0] * 4)
    family["forward_timestamps"] = [610.0, 1210.0, 1810.0, 2410.0]
    observations, join = join_sweep_observations(ledger, [family])
    assert join["joined"] == 1
    assert observations[0].timeframe == "10m"


def test_identical_multiplicity_is_joined_but_timeframe_mismatch_is_disclosed() -> None:
    ledger = [
        _ledger("AAA", "5m", 10.0, "BUY_SIDE", 100.0, True),
        _ledger("AAA", "10m", 10.0, "BUY_SIDE", 100.0, True),
    ]
    family = _family(10.0, "SHORT", 100.0, [99.0] * 5)
    family["forward_timestamps"] = [86_410.0 + i * 86_400.0 for i in range(5)]
    observations, join = join_sweep_observations(ledger, [family, dict(family)])

    assert join["joined"] == 2
    assert join["multiplicity_allocated_family_events"] == 2
    assert {row.timeframe for row in observations} == {"5m", "10m"}
    alignment = timeframe_alignment_summary(observations)
    assert alignment["analysis_valid"] is False
    assert alignment["mismatches"] == 2

    intervals = bootstrap_intervals(
        observations,
        horizon_bars=8,
        threshold_pct=0.005,
        replicates=20,
        seed=7,
    )
    assert intervals["timeframe_cluster"]["measured"] is False
    assert intervals["symbol_timeframe_two_way"]["measured"] is False


def test_cluster_bootstrap_is_deterministic() -> None:
    observations = [
        SweepObservation(
            symbol=f"S{i % 3}",
            timeframe="5m" if i % 2 else "1D",
            event_id=str(i),
            timestamp=float(i),
            side="SELL_SIDE",
            sweep_price=100.0,
            ledger_outcome=i % 2 == 0,
            forward_closes=tuple([101.0] * (8 if i % 3 else 4)),
            inferred_forward_timeframe="5m" if i % 2 else "1D",
        )
        for i in range(12)
    ]
    first = bootstrap_intervals(
        observations,
        horizon_bars=8,
        threshold_pct=0.005,
        replicates=100,
        seed=7,
    )
    second = bootstrap_intervals(
        observations,
        horizon_bars=8,
        threshold_pct=0.005,
        replicates=100,
        seed=7,
    )
    assert first == second
    assert first["symbol_cluster"]["measured"] is True
    interval = first["symbol_timeframe_two_way"]["intervals"]["canonical.censoring_rate"]
    assert 0.0 <= interval["low"] <= interval["high"] <= 1.0


def test_fixture_shapes_are_json_serializable(tmp_path: Path) -> None:
    payload = _ledger("AAA", "5m", 10.0, "SELL_SIDE", 100.0, False)
    path = tmp_path / "event.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert json.loads(path.read_text(encoding="utf-8"))["family"] == "SWEEP"
