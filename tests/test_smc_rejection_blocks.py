"""Rejection-Block (RJB) detector tests.

Covers both directions and both wick variants (``trapped_wick`` and
``signal_wick``), the zone geometry ported from the SMC rejection-block study,
mitigation/invalidation bookkeeping, the mutual exclusivity of the two variants,
degenerate (zero-height) wick skipping, the honest empty-input paths, and the
stable ``classic_rjb`` / ``REJECTIONBLOCK`` tags.

RECORDED-ONLY: the detector produces structure records and is not wired into any
score or gate; these tests assert the records, not any trading decision.
"""

from __future__ import annotations

import pandas as pd

from scripts.explicit_structure_detectors import detect_rejection_blocks_classic

_T0 = 1_700_000_000
_STEP = 900  # 15-minute bars
_BAR_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


def _df(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """Build an OHLCV frame from ``(open, high, low, close)`` tuples."""
    return pd.DataFrame(
        {
            "timestamp": [_T0 + i * _STEP for i in range(len(rows))],
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "volume": [1000.0] * len(rows),
        }
    )


def _detect(rows: list[tuple[float, float, float, float]]):
    return detect_rejection_blocks_classic(_df(rows), symbol="BTCUSDT", timeframe="15m")


def _diag_for(diag: list[dict], row: dict) -> dict:
    return next(d for d in diag if d["id"] == row["id"])


def test_bullish_trapped_wick_zone() -> None:
    # Down (trapped) then up (signal) closing above; signal only grazes the wick.
    out, diag = _detect(
        [
            (110.0, 111.0, 95.0, 100.0),  # trapped DOWN, lower wick 95..100
            (101.0, 116.0, 100.0, 115.0),  # signal UP, low 100 > threshold 99
        ]
    )
    assert len(out) == 1
    row = out[0]
    assert row["dir"] == "BULL"
    assert row["low"] == 95.0
    assert row["high"] == 100.0
    assert row["source"] == "classic_rjb"
    assert row["valid"] is True
    assert row["anchor_ts"] == _T0 + _STEP
    d = _diag_for(diag, row)
    assert d["kind"] == "REJECTIONBLOCK"
    assert d["variant"] == "trapped_wick"
    assert d["invalidation_rule"] == "close_below_low"
    assert d["left_anchor_ts"] == _T0


def test_bullish_signal_wick_zone() -> None:
    # Signal runs past the trapped low: the zone is the signal candle's own wick.
    out, diag = _detect(
        [
            (110.0, 111.0, 100.0, 101.0),  # trapped DOWN, low 100
            (102.0, 116.0, 95.0, 115.0),  # signal UP, low 95 < trapped low 100
        ]
    )
    assert len(out) == 1
    row = out[0]
    assert row["dir"] == "BULL"
    assert row["low"] == 95.0  # cur_low
    assert row["high"] == 102.0  # cur_open
    assert _diag_for(diag, row)["variant"] == "signal_wick"


def test_bearish_trapped_wick_zone() -> None:
    out, diag = _detect(
        [
            (100.0, 111.0, 99.0, 105.0),  # trapped UP, upper wick 105..111
            (104.0, 106.0, 90.0, 95.0),  # signal DOWN, high 106 < threshold 106.2
        ]
    )
    assert len(out) == 1
    row = out[0]
    assert row["dir"] == "BEAR"
    assert row["low"] == 105.0  # prev_close
    assert row["high"] == 111.0  # prev_high
    d = _diag_for(diag, row)
    assert d["variant"] == "trapped_wick"
    assert d["invalidation_rule"] == "close_above_high"


def test_bearish_signal_wick_zone() -> None:
    out, diag = _detect(
        [
            (100.0, 106.0, 99.0, 105.0),  # trapped UP, high 106
            (107.0, 112.0, 90.0, 95.0),  # signal DOWN, high 112 > trapped high 106
        ]
    )
    assert len(out) == 1
    row = out[0]
    assert row["dir"] == "BEAR"
    assert row["low"] == 107.0  # cur_open
    assert row["high"] == 112.0  # cur_high
    assert _diag_for(diag, row)["variant"] == "signal_wick"


def test_mitigation_marks_touch_without_invalidation() -> None:
    out, diag = _detect(
        [
            (110.0, 111.0, 95.0, 100.0),  # bull trapped, zone [95, 100]
            (101.0, 116.0, 100.0, 115.0),
            (104.0, 106.0, 98.0, 103.0),  # probe low 98 enters zone; close 103 holds
        ]
    )
    bull = [r for r in out if r["dir"] == "BULL"]
    assert len(bull) == 1
    assert bull[0]["valid"] is True
    d = _diag_for(diag, bull[0])
    assert d["mitigated"] is True
    assert d["mitigated_ts"] == _T0 + 2 * _STEP


def test_invalidation_sets_valid_false() -> None:
    out, _diag = _detect(
        [
            (110.0, 111.0, 95.0, 100.0),  # bull trapped, zone [95, 100]
            (101.0, 116.0, 100.0, 115.0),
            (96.0, 99.0, 80.0, 85.0),  # close 85 < zone low 95 -> invalidated
        ]
    )
    bull = [r for r in out if r["dir"] == "BULL"]
    assert len(bull) == 1
    assert bull[0]["valid"] is False


def test_degenerate_wick_is_skipped() -> None:
    # Trapped candle with no lower wick -> zero-height zone -> nothing emitted.
    out, diag = _detect(
        [
            (110.0, 111.0, 100.0, 100.0),  # prev down, low == close (no lower wick)
            (101.0, 116.0, 105.0, 115.0),
        ]
    )
    assert out == []
    assert diag == []


def test_no_pattern_returns_empty() -> None:
    out, diag = _detect(
        [
            (100.0, 101.0, 99.0, 100.5),
            (100.5, 101.5, 99.5, 101.0),
            (101.0, 102.0, 100.0, 101.5),
        ]
    )
    assert out == []
    assert diag == []


def test_empty_and_single_bar_frames() -> None:
    empty = pd.DataFrame({c: [] for c in _BAR_COLUMNS})
    out, diag = detect_rejection_blocks_classic(empty, symbol="BTCUSDT", timeframe="15m")
    assert out == []
    assert diag == []
    out1, diag1 = _detect([(100.0, 101.0, 99.0, 100.5)])
    assert out1 == []
    assert diag1 == []


def test_tags_and_unique_ids_across_multiple_blocks() -> None:
    out, diag = _detect(
        [
            (110.0, 111.0, 95.0, 100.0),  # bull RJB
            (101.0, 116.0, 100.0, 115.0),
            (100.0, 106.0, 99.0, 105.0),  # filler up bar
            (104.0, 108.0, 90.0, 95.0),  # bear RJB (signal wick)
        ]
    )
    dirs = {r["dir"] for r in out}
    assert "BULL" in dirs
    assert "BEAR" in dirs
    assert all(r["source"] == "classic_rjb" for r in out)
    assert all(d["kind"] == "REJECTIONBLOCK" for d in diag)
    ids = [r["id"] for r in out]
    assert len(ids) == len(set(ids))
