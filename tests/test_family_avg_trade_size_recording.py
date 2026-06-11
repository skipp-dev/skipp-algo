"""ADR-0016 / ADR-0019 — recording the average trade size feature on events and
extracting it (with outcomes) for the pre-registered ADR-0019 A/B harness."""

from __future__ import annotations

from governance.family_event_adapter import family_events_from_structure
from governance.family_event_score import ATR_PERIOD
from governance.family_walkforward import family_outcome_horizon
from governance.family_returns import (
    FamilyEvent,
    extract_family_feature_samples,
)

_T0 = 1_700_000_000.0
_STEP = 86_400.0  # daily bars


def _bars_with_trades(
    closes: list[float],
    volume: list[float | None],
    trade_count: list[float | None],
) -> list[dict]:
    rows: list[dict] = []
    for i, close in enumerate(closes):
        row: dict = {
            "timestamp": _T0 + i * _STEP,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
        }
        vol = volume[i]
        if vol is not None:
            row["volume"] = vol
        tc = trade_count[i]
        if tc is not None:
            row["trade_count"] = tc
        rows.append(row)
    return rows


def test_adapter_records_avg_trade_size_when_trades_present() -> None:
    n = ATR_PERIOD + 12
    closes = [100.0 + i for i in range(n)]
    volume: list[float | None] = [100.0 + 10.0 * i for i in range(n)]
    trade_count: list[float | None] = [4.0 + (i % 3) for i in range(n)]
    anchor_bar = ATR_PERIOD + 2
    bars = _bars_with_trades(closes, volume, trade_count)
    anchor_ts = _T0 + anchor_bar * _STEP
    structure = {
        "bos": [{"id": "b1", "time": anchor_ts, "price": closes[anchor_bar], "dir": "UP"}]
    }

    events = family_events_from_structure(structure, bars)

    assert len(events) == 1
    assert "average_trade_size" in events[0]
    assert isinstance(events[0]["average_trade_size"], float)


def test_adapter_omits_avg_trade_size_when_trade_count_absent() -> None:
    # OHLCV-only run: no bar carries trade_count -> feature honestly absent.
    n = ATR_PERIOD + 12
    closes = [100.0 + i for i in range(n)]
    volume: list[float | None] = [100.0 + 10.0 * i for i in range(n)]
    trade_count: list[float | None] = [None] * n
    anchor_bar = ATR_PERIOD + 2
    bars = _bars_with_trades(closes, volume, trade_count)
    anchor_ts = _T0 + anchor_bar * _STEP
    structure = {
        "bos": [{"id": "b1", "time": anchor_ts, "price": closes[anchor_bar], "dir": "UP"}]
    }

    events = family_events_from_structure(structure, bars)

    assert len(events) == 1
    assert "average_trade_size" not in events[0]


def _triggered_event(
    family: str, *, avg_size: float | None, up: bool
) -> FamilyEvent:
    base = 100.0
    # Stat-review S3 (#2674): immediate-mode windows shorter than the family
    # horizon are now refused (no clamp-to-last-bar), so the fixture must
    # supply a full horizon-length forward series.
    n = family_outcome_horizon(family)
    forward = (
        [base + (1.0 + i) for i in range(n)]
        if up
        else [base - (1.0 + i) for i in range(n)]
    )
    event = FamilyEvent(
        family=family,  # type: ignore[typeddict-item]
        direction="LONG",
        entry_mode="immediate",
        entry_price=base,
        anchor_ts=_T0,
        forward_highs=[f + 1.0 for f in forward],
        forward_lows=[f - 1.0 for f in forward],
        forward_closes=forward,
        forward_timestamps=[_T0 + (i + 1) * _STEP for i in range(len(forward))],
    )
    if avg_size is not None:
        event["average_trade_size"] = avg_size
    return event


def test_extract_feature_samples_pairs_avg_size_with_binary_outcome() -> None:
    events = [
        _triggered_event("BOS", avg_size=42.0, up=True),
        _triggered_event("BOS", avg_size=11.0, up=False),
    ]

    samples = extract_family_feature_samples(
        events, feature_key="average_trade_size"
    )

    assert samples["BOS"]["feature"] == [42.0, 11.0]
    assert samples["BOS"]["outcomes"] == [1.0, 0.0]


def test_extract_feature_samples_excludes_events_without_avg_size() -> None:
    events = [
        _triggered_event("BOS", avg_size=None, up=True),
        _triggered_event("BOS", avg_size=25.0, up=True),
    ]

    samples = extract_family_feature_samples(
        events, feature_key="average_trade_size"
    )

    assert samples["BOS"]["feature"] == [25.0]
