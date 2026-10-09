"""ADR-0016 / ADR-0019 — recording the order-flow imbalance feature on events and
extracting it (with outcomes) for the pre-registered ADR-0019 A/B harness."""

from __future__ import annotations

from governance.family_event_adapter import family_events_from_structure
from governance.family_event_score import ATR_PERIOD
from governance.family_returns import (
    FamilyEvent,
    extract_family_feature_samples,
)
from governance.family_walkforward import family_outcome_horizon

_T0 = 1_700_000_000.0
_STEP = 86_400.0  # daily bars


def _bars_with_flow(
    closes: list[float],
    signed: list[float | None],
    abs_vol: list[float | None],
) -> list[dict]:
    rows: list[dict] = []
    for i, close in enumerate(closes):
        row: dict = {
            "timestamp": _T0 + i * _STEP,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 100.0,
        }
        sv = signed[i]
        if sv is not None:
            row["signed_volume"] = sv
        av = abs_vol[i]
        if av is not None:
            row["abs_volume"] = av
        rows.append(row)
    return rows


def test_adapter_records_ofi_when_flow_present() -> None:
    n = ATR_PERIOD + 12
    closes = [100.0 + i for i in range(n)]
    signed: list[float | None] = [float((i % 5) - 2) * 10.0 for i in range(n)]
    abs_vol: list[float | None] = [100.0 + 5.0 * i for i in range(n)]
    anchor_bar = ATR_PERIOD + 2
    bars = _bars_with_flow(closes, signed, abs_vol)
    anchor_ts = _T0 + anchor_bar * _STEP
    structure = {
        "bos": [{"id": "b1", "time": anchor_ts, "price": closes[anchor_bar], "dir": "UP"}]
    }

    events = family_events_from_structure(structure, bars)

    assert len(events) == 1
    assert "ofi_imbalance" in events[0]
    value = events[0]["ofi_imbalance"]
    assert isinstance(value, float)
    assert 0.0 <= value <= 1.0


def test_adapter_omits_ofi_when_abs_volume_absent() -> None:
    # OHLCV-only run: no bar carries abs_volume -> feature honestly absent.
    n = ATR_PERIOD + 12
    closes = [100.0 + i for i in range(n)]
    signed: list[float | None] = [10.0] * n
    abs_vol: list[float | None] = [None] * n
    anchor_bar = ATR_PERIOD + 2
    bars = _bars_with_flow(closes, signed, abs_vol)
    anchor_ts = _T0 + anchor_bar * _STEP
    structure = {
        "bos": [{"id": "b1", "time": anchor_ts, "price": closes[anchor_bar], "dir": "UP"}]
    }

    events = family_events_from_structure(structure, bars)

    assert len(events) == 1
    assert "ofi_imbalance" not in events[0]


def _triggered_event(family: str, *, ofi: float | None, up: bool) -> FamilyEvent:
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
    if ofi is not None:
        event["ofi_imbalance"] = ofi
    return event


def test_extract_feature_samples_pairs_ofi_with_binary_outcome() -> None:
    events = [
        _triggered_event("BOS", ofi=0.7, up=True),
        _triggered_event("BOS", ofi=0.1, up=False),
    ]

    samples = extract_family_feature_samples(events, feature_key="ofi_imbalance")

    assert samples["BOS"]["feature"] == [0.7, 0.1]
    assert samples["BOS"]["outcomes"] == [1.0, 0.0]


def test_extract_feature_samples_excludes_events_without_ofi() -> None:
    events = [
        _triggered_event("BOS", ofi=None, up=True),
        _triggered_event("BOS", ofi=0.5, up=True),
    ]

    samples = extract_family_feature_samples(events, feature_key="ofi_imbalance")

    assert samples["BOS"]["feature"] == [0.5]
