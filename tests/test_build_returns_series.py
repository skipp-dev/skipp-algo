"""Tests for ``scripts/build_returns_series.py`` (ADR-0031 producer).

The series file is the persisted returns source the C6/C7 track-record
gate and the C5 regime stratification consume; these tests pin the two
contracts (gate Shape-B ``returns_by_variant``, C5 ``trades``) and the
honest empty-pool behavior.
"""
from __future__ import annotations

import json
from pathlib import Path

from governance.family_returns import DEFAULT_COST_BPS, RETURN_RULE, realized_return
from scripts.build_returns_series import (
    _trades_per_year,
    build_series_payload,
    main,
)

_DAY = 86_400.0
_ANCHOR = 1_750_000_000.0


def _sweep_event(
    *,
    direction: str = "UP",
    regime: str | None = "TRENDING",
    anchor_ts: float = _ANCHOR,
    closes: tuple[float, ...] = (101.0, 102.0, 103.0),
) -> dict:
    """Minimal triggered SWEEP event (immediate entry, horizon 3 bars)."""
    ev = {
        "family": "SWEEP",
        "direction": direction,
        "entry_mode": "immediate",
        "entry_price": 100.0,
        "anchor_ts": anchor_ts,
        "forward_closes": list(closes),
        "forward_highs": [c + 0.5 for c in closes],
        "forward_lows": [c - 0.5 for c in closes],
        "forward_timestamps": [anchor_ts + _DAY * (i + 1) for i in range(len(closes))],
    }
    if regime is not None:
        ev["regime"] = regime
    return ev


def test_payload_returns_match_variant_a_rule() -> None:
    """The series must carry exactly realized_return's Variant-A numbers."""
    ev = _sweep_event()
    payload = build_series_payload([ev], date="2026-07-29", plane="1D")
    expected = realized_return(ev, cost_bps=DEFAULT_COST_BPS)
    assert expected is not None
    assert payload["returns_by_variant"] == {"SWEEP": [expected]}
    assert payload["n_trades"] == 1
    assert payload["measurement"]["return_rule"] == RETURN_RULE
    assert payload["measurement"]["cost_bps"] == DEFAULT_COST_BPS
    assert payload["rr_target"] == 1.0


def test_trades_carry_regime_and_exclude_untagged() -> None:
    """C5 trades: only triggered events WITH a regime tag; never invented."""
    tagged = _sweep_event(regime="RANGING")
    untagged = _sweep_event(regime=None, anchor_ts=_ANCHOR + _DAY)
    payload = build_series_payload([tagged, untagged], date="2026-07-29", plane=None)
    assert payload["n_trades"] == 2
    assert payload["n_trades_with_regime"] == 1
    (trade,) = payload["trades"]
    assert trade["regime_at_entry"] == "RANGING"
    assert trade["family"] == "SWEEP"
    assert trade["pnl"] == realized_return(tagged, cost_bps=DEFAULT_COST_BPS)


def test_untriggered_events_are_not_trades() -> None:
    """direction-less events yield no return and must not appear as zeros."""
    dead = _sweep_event(direction="")
    payload = build_series_payload([dead], date="2026-07-29", plane=None)
    assert payload["n_trades"] == 0
    assert payload["returns_by_variant"] == {}
    assert payload["trades"] == []
    assert payload["trades_per_year"] is None


def test_trades_per_year_uses_anchor_span() -> None:
    # 3 trades over exactly 2 days → 3 / (2/365.25) = 548.25 715... per year
    ts = [0.0, _DAY, 2 * _DAY]
    tpy = _trades_per_year(ts)
    assert tpy is not None
    assert abs(tpy - 3 / (2 * _DAY / (365.25 * _DAY))) < 1e-6


def test_cli_missing_pool_writes_honest_empty_series(tmp_path: Path, capsys) -> None:
    out = tmp_path / "series.json"
    rc = main(
        [
            "--events", str(tmp_path / "nope.json"),
            "--date", "2026-07-29",
            "--output", str(out),
        ]
    )
    assert rc == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["n_trades"] == 0
    assert payload["returns_by_variant"] == {}
    assert "WARNING" in capsys.readouterr().err


def test_cli_roundtrip_gate_shape(tmp_path: Path) -> None:
    """The written file must load through the gate producer unchanged."""
    from scripts.build_track_record_gate import build_track_record_gate_payload

    pool = tmp_path / "pool.json"
    pool.write_text(
        json.dumps(
            [
                _sweep_event(),
                # different exit close → non-identical returns (the gate
                # refuses zero-variance series as a broken-feed signal)
                _sweep_event(anchor_ts=_ANCHOR + _DAY, closes=(101.0, 102.0, 99.0)),
            ]
        ),
        encoding="utf-8",
    )
    out = tmp_path / "series.json"
    assert main(["--events", str(pool), "--date", "2026-07-29", "--output", str(out)]) == 0
    series = json.loads(out.read_text(encoding="utf-8"))
    verdict = build_track_record_gate_payload(series)
    # 2 trades << MIN_OOS_TRADES → honest red, never a crash.
    assert verdict["status"] == "red"
    assert verdict["n_trades"] == 2


def test_every_return_carries_its_anchor_for_the_gates_day_checks() -> None:
    """``anchor_ts_by_variant`` is parallel to ``returns_by_variant`` — the
    gate counts trading days from it (ADR-0031, Nachtrag 2026-10-02). An
    untriggered event contributes to neither list."""
    from scripts.build_track_record_gate import build_track_record_gate_payload

    events = [
        _sweep_event(anchor_ts=_ANCHOR + day * _DAY, closes=(101.0, 102.0, 100.0 + day))
        for day in (0, 0, 1, 3)
    ]
    events.append(_sweep_event(direction="", anchor_ts=_ANCHOR + 2 * _DAY))  # no trade

    payload = build_series_payload(events, date="2026-10-02", plane="1D")

    assert payload["anchor_ts_by_variant"] == {
        "SWEEP": [_ANCHOR, _ANCHOR, _ANCHOR + _DAY, _ANCHOR + 3 * _DAY]
    }
    assert len(payload["returns_by_variant"]["SWEEP"]) == 4
    verdict = build_track_record_gate_payload(payload)
    days = {c["name"]: c for c in verdict["per_variant"]["SWEEP"]["checks"]}["trading_days"]
    assert (days["status"], days["value"]) == ("red", 3.0)
