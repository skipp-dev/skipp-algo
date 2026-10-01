"""Tests for ``scripts/accumulate_returns_ledger.py`` (ADR-0031, Nachtrag 2026-10-01).

The ledger is the memory the 30-day pool lacks. What must hold:

* it records exactly the returns the daily series would report for the same
  pool (one trade definition, no second scale);
* it only ever appends — a trade recorded once survives the pool forgetting it;
* it never pools two trade definitions;
* a pre-registration date keeps earlier trades out of the verdict, not out of
  the record.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from governance.family_returns import DEFAULT_COST_BPS, RETURN_RULE, realized_return
from scripts.accumulate_returns_ledger import (
    RC_OK,
    RC_RULE_MISMATCH,
    build_cumulative_series,
    load_ledger,
    main,
    merge,
    pool_trades,
)
from scripts.build_returns_series import build_series_payload
from scripts.build_track_record_gate import build_track_record_gate_payload

_M15 = 900.0
_DAY = 86_400.0
# 2026-10-01 14:30:00 UTC — a 15m bar boundary after the 15m evidence start.
_ANCHOR = 1_790_865_000.0


def _sweep(
    symbol: str,
    anchor_ts: float,
    *,
    step: float = _M15,
    timeframe: str = "15m",
    direction: str = "LONG",
    closes: tuple[float, ...] = (101.0, 102.0, 103.0),
    regime: str | None = "TRENDING",
    with_id: bool = True,
) -> dict:
    """A triggered SWEEP event (immediate entry, horizon 3 bars) on one plane."""
    event = {
        "family": "SWEEP",
        "direction": direction,
        "entry_mode": "immediate",
        "entry_price": 100.0,
        "anchor_ts": anchor_ts,
        "forward_closes": list(closes),
        "forward_highs": [c + 0.5 for c in closes],
        "forward_lows": [c - 0.5 for c in closes],
        "forward_timestamps": [anchor_ts + step * (i + 1) for i in range(len(closes))],
    }
    if regime is not None:
        event["regime"] = regime
    if with_id:
        event["event_id"] = f"sweep:{symbol}:{timeframe}:{int(anchor_ts)}:SELL_SIDE:100.00"
    return event


def _write_pool(path: Path, events: list[dict]) -> Path:
    path.write_text(json.dumps(events), encoding="utf-8")
    return path


def _run(tmp_path: Path, pool: Path, *, plane: str = "15m", day: str = "2026-10-01", extra=()) -> int:
    return main([
        "--events", str(pool),
        "--plane", plane,
        "--date", day,
        "--ledger", str(tmp_path / f"ledger_{plane}.jsonl"),
        "--series-output", str(tmp_path / f"cumulative_{plane}.json"),
        *extra,
    ])


def _ledger_rows(tmp_path: Path, plane: str = "15m") -> list[dict]:
    text = (tmp_path / f"ledger_{plane}.jsonl").read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# One trade definition: the ledger says what the series says.
# ---------------------------------------------------------------------------


def test_the_ledger_records_exactly_the_series_returns(tmp_path: Path) -> None:
    events = [
        _sweep("AAPL", _ANCHOR),
        _sweep("MSFT", _ANCHOR, closes=(99.0, 98.0, 97.0)),
        _sweep("NVDA", _ANCHOR + _M15, direction="SHORT", closes=(99.0, 98.5, 98.0)),
    ]
    pool = _write_pool(tmp_path / "pool.json", events)
    assert _run(tmp_path, pool) == RC_OK

    series = build_series_payload(events, date="2026-10-01", plane="15m")
    cumulative = json.loads((tmp_path / "cumulative_15m.json").read_text(encoding="utf-8"))
    assert sorted(cumulative["returns_by_variant"]["SWEEP"]) == sorted(
        series["returns_by_variant"]["SWEEP"]
    )
    assert cumulative["n_trades"] == series["n_trades"] == 3
    for row in _ledger_rows(tmp_path):
        assert row["return_rule"] == RETURN_RULE
        assert row["cost_bps"] == DEFAULT_COST_BPS
        assert row["plane"] == "15m"
        assert row["first_recorded"] == "2026-10-01"


def test_same_bar_trades_of_different_symbols_are_separate_rows(tmp_path: Path) -> None:
    """Identity is the event, not the bar — the pool's old defect must not recur."""
    pool = _write_pool(
        tmp_path / "pool.json",
        [_sweep(symbol, _ANCHOR) for symbol in ("AAPL", "MSFT", "NVDA")],
    )
    _run(tmp_path, pool)
    assert len({row["key"] for row in _ledger_rows(tmp_path)}) == 3


def test_untriggered_events_are_not_recorded(tmp_path: Path) -> None:
    too_short = _sweep("AAPL", _ANCHOR, closes=(101.0,))  # horizon 3 not reached
    assert realized_return(too_short) is None
    pool = _write_pool(tmp_path / "pool.json", [too_short])
    _run(tmp_path, pool)
    assert _ledger_rows(tmp_path) == []


def test_only_events_of_the_ledgers_own_plane_are_recorded(tmp_path: Path) -> None:
    pool = _write_pool(
        tmp_path / "pool.json",
        [
            _sweep("AAPL", _ANCHOR),
            _sweep("AAPL", _ANCHOR, step=_DAY, timeframe="1D"),
        ],
    )
    _run(tmp_path, pool, plane="15m")
    _run(tmp_path, pool, plane="1D")
    assert [row["key"].split(":")[2] for row in _ledger_rows(tmp_path, "15m")] == ["15m"]
    assert [row["key"].split(":")[2] for row in _ledger_rows(tmp_path, "1D")] == ["1D"]


# ---------------------------------------------------------------------------
# Append-only: the ledger remembers what the pool forgets.
# ---------------------------------------------------------------------------


def test_a_second_run_over_the_same_pool_adds_nothing(tmp_path: Path) -> None:
    pool = _write_pool(tmp_path / "pool.json", [_sweep("AAPL", _ANCHOR)])
    _run(tmp_path, pool, day="2026-10-01")
    before = (tmp_path / "ledger_15m.jsonl").read_text(encoding="utf-8")
    _run(tmp_path, pool, day="2026-10-02")
    assert (tmp_path / "ledger_15m.jsonl").read_text(encoding="utf-8") == before


def test_a_trade_survives_ageing_out_of_the_pool(tmp_path: Path) -> None:
    """The reason the ledger exists.

    Day 1 the pool holds AAPL. Day 2 the window has moved on: AAPL is gone,
    MSFT is new. The window series would now show one trade; the ledger two.
    """
    _run(tmp_path, _write_pool(tmp_path / "day1.json", [_sweep("AAPL", _ANCHOR)]), day="2026-10-01")
    _run(
        tmp_path,
        _write_pool(tmp_path / "day2.json", [_sweep("MSFT", _ANCHOR + _DAY)]),
        day="2026-10-02",
    )
    rows = _ledger_rows(tmp_path)
    assert [row["key"].split(":")[1] for row in rows] == ["AAPL", "MSFT"]
    assert [row["first_recorded"] for row in rows] == ["2026-10-01", "2026-10-02"]
    cumulative = json.loads((tmp_path / "cumulative_15m.json").read_text(encoding="utf-8"))
    assert cumulative["n_trades"] == 2
    assert cumulative["ledger"]["n_trades_ledger"] == 2


def test_existing_lines_are_kept_verbatim_and_new_ones_appended(tmp_path: Path) -> None:
    _run(tmp_path, _write_pool(tmp_path / "day1.json", [_sweep("MSFT", _ANCHOR + _DAY)]))
    first_line = (tmp_path / "ledger_15m.jsonl").read_text(encoding="utf-8")
    # Day 2 brings an EARLIER anchor: it is appended, not sorted in front.
    _run(tmp_path, _write_pool(tmp_path / "day2.json", [_sweep("AAPL", _ANCHOR)]), day="2026-10-02")
    text = (tmp_path / "ledger_15m.jsonl").read_text(encoding="utf-8")
    assert text.startswith(first_line)
    assert len(text.splitlines()) == 2


def test_a_contradicted_return_is_reported_and_not_overwritten(tmp_path: Path, capsys) -> None:
    _run(tmp_path, _write_pool(tmp_path / "day1.json", [_sweep("AAPL", _ANCHOR)]))
    recorded = _ledger_rows(tmp_path)[0]["pnl"]
    revised = _sweep("AAPL", _ANCHOR, closes=(101.0, 102.0, 90.0))  # same id, other outcome
    capsys.readouterr()
    assert _run(tmp_path, _write_pool(tmp_path / "day2.json", [revised]), day="2026-10-02") == RC_OK
    captured = capsys.readouterr()
    assert _ledger_rows(tmp_path)[0]["pnl"] == recorded
    assert "re-observed sweep:AAPL:15m" in captured.err
    assert "1 contradicted" in captured.out


def test_merge_is_pure_and_orders_new_rows_by_anchor_then_key() -> None:
    observed, _ = pool_trades(
        [_sweep("MSFT", _ANCHOR + _M15), _sweep("NVDA", _ANCHOR), _sweep("AAPL", _ANCHOR)],
        plane="15m",
        cost_bps=DEFAULT_COST_BPS,
    )
    new_rows, conflicts = merge({}, observed, run_date="2026-10-01")
    assert conflicts == []
    assert [row["key"].split(":")[1] for row in new_rows] == ["AAPL", "NVDA", "MSFT"]


# ---------------------------------------------------------------------------
# Identity and integrity.
# ---------------------------------------------------------------------------


def test_trades_without_event_id_are_counted_not_recorded(tmp_path: Path, capsys) -> None:
    pool = _write_pool(
        tmp_path / "pool.json",
        [_sweep("AAPL", _ANCHOR), _sweep("MSFT", _ANCHOR, with_id=False)],
    )
    _run(tmp_path, pool)
    assert len(_ledger_rows(tmp_path)) == 1
    assert "1 closed trade(s) without event_id" in capsys.readouterr().err


def test_a_ledger_never_pools_two_trade_definitions(tmp_path: Path, capsys) -> None:
    pool = _write_pool(tmp_path / "pool.json", [_sweep("AAPL", _ANCHOR)])
    _run(tmp_path, pool)
    before = (tmp_path / "ledger_15m.jsonl").read_text(encoding="utf-8")
    more = _write_pool(tmp_path / "pool2.json", [_sweep("MSFT", _ANCHOR)])
    assert _run(tmp_path, more, extra=("--cost-bps", "7")) == RC_RULE_MISMATCH
    assert "ONE trade definition" in capsys.readouterr().err
    assert (tmp_path / "ledger_15m.jsonl").read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    "content",
    [
        "not json\n",
        '{"family": "SWEEP"}\n',  # row without key
        '{"key": "a", "pnl": 0.1}\n{"key": "a", "pnl": 0.2}\n',  # duplicate key
    ],
)
def test_an_unreadable_ledger_is_an_error_not_an_empty_one(tmp_path: Path, content: str) -> None:
    """Treating a corrupt ledger as empty would re-append every trade in it."""
    ledger = tmp_path / "ledger_15m.jsonl"
    ledger.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError):
        load_ledger(ledger)
    pool = _write_pool(tmp_path / "pool.json", [_sweep("AAPL", _ANCHOR)])
    with pytest.raises(ValueError):
        _run(tmp_path, pool)
    assert ledger.read_text(encoding="utf-8") == content


def test_a_missing_pool_creates_an_empty_ledger_and_an_honest_empty_series(tmp_path: Path) -> None:
    assert _run(tmp_path, tmp_path / "absent.json") == RC_OK
    assert (tmp_path / "ledger_15m.jsonl").read_text(encoding="utf-8") == ""
    cumulative = json.loads((tmp_path / "cumulative_15m.json").read_text(encoding="utf-8"))
    assert cumulative["n_trades"] == 0
    assert cumulative["returns_by_variant"] == {}


def test_a_malformed_run_date_never_reaches_the_ledger(tmp_path: Path) -> None:
    pool = _write_pool(tmp_path / "pool.json", [_sweep("AAPL", _ANCHOR)])
    with pytest.raises(ValueError):
        _run(tmp_path, pool, day="01.10.2026")
    assert not (tmp_path / "ledger_15m.jsonl").exists()


# ---------------------------------------------------------------------------
# Evidence start: in the record, not in the verdict.
# ---------------------------------------------------------------------------


def test_trades_before_the_evidence_start_stay_in_the_ledger_but_out_of_the_series(
    tmp_path: Path,
) -> None:
    before = _sweep("AAPL", _ANCHOR - 5 * _DAY)  # 2026-09-26, seen before the plane was fixed
    after = _sweep("MSFT", _ANCHOR)  # 2026-10-01
    pool = _write_pool(tmp_path / "pool.json", [before, after])
    _run(tmp_path, pool, extra=("--evidence-start", "2026-10-01"))
    assert len(_ledger_rows(tmp_path)) == 2
    cumulative = json.loads((tmp_path / "cumulative_15m.json").read_text(encoding="utf-8"))
    assert cumulative["n_trades"] == 1
    assert cumulative["ledger"] == {
        "window": "cumulative",
        "evidence_start": "2026-10-01",
        "n_trades_ledger": 2,
        "n_trades_before_evidence_start": 1,
        "first_anchor": "2026-10-01T14:30:00+00:00",
        "last_anchor": "2026-10-01T14:30:00+00:00",
    }


def test_the_evidence_start_boundary_is_utc_midnight_inclusive() -> None:
    midnight = 1_790_812_800.0  # 2026-10-01T00:00:00Z
    rows = [
        {"key": "a", "family": "SWEEP", "anchor_ts": midnight - 1, "pnl": 0.01, "regime_at_entry": None},
        {"key": "b", "family": "SWEEP", "anchor_ts": midnight, "pnl": 0.02, "regime_at_entry": None},
    ]
    series = build_cumulative_series(
        rows, run_date="2026-10-02", plane="15m", cost_bps=5.0, evidence_start="2026-10-01"
    )
    assert series["returns_by_variant"] == {"SWEEP": [0.02]}


# ---------------------------------------------------------------------------
# The consumer: the cumulative series is something the gate can read.
# ---------------------------------------------------------------------------


def test_the_cumulative_series_feeds_the_track_record_gate(tmp_path: Path) -> None:
    """Shape-B contract, exercised through the real gate builder.

    Returns are time-ordered (the gate's bootstrap resamples in sequence), and
    only regime-tagged trades enter ``trades``.
    """
    events = [
        _sweep("AAPL", _ANCHOR + i * _M15, closes=(100.5, 101.0, 101.0 + (i % 3)), regime=None if i % 4 == 0 else "RANGING")
        for i in range(12)
    ]
    pool = _write_pool(tmp_path / "pool.json", list(reversed(events)))
    _run(tmp_path, pool)
    cumulative = json.loads((tmp_path / "cumulative_15m.json").read_text(encoding="utf-8"))
    expected = [realized_return(event) for event in events]  # anchor order
    assert cumulative["returns_by_variant"]["SWEEP"] == expected
    assert cumulative["n_trades_with_regime"] == 9
    assert cumulative["trades_per_year"] is not None
    verdict = build_track_record_gate_payload(cumulative)
    assert verdict["n_trades"] == 12
    assert "SWEEP" in verdict["per_variant"]
