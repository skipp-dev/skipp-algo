"""Tests for ADR-0019 step 2: recording the relative-volume feature on events
and extracting it (with outcomes) for the pre-registered A/B harness."""

from __future__ import annotations

from governance.family_event_adapter import family_events_from_structure
from governance.family_event_score import ATR_PERIOD
from governance.family_returns import (
    FamilyEvent,
    extract_family_feature_samples,
)

_T0 = 1_700_000_000.0
_STEP = 86_400.0  # daily bars


def _bars_with_volume(
    closes: list[float], volumes: list[float | None]
) -> list[dict]:
    rows: list[dict] = []
    for i, close in enumerate(closes):
        row: dict = {
            "timestamp": _T0 + i * _STEP,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
        }
        vol = volumes[i]
        if vol is not None:
            row["volume"] = vol
        rows.append(row)
    return rows


def test_adapter_records_relative_volume_when_volume_present() -> None:
    # Enough trailing history (anchor at bar ATR_PERIOD+2) and a heavy
    # formation bar -> relative_volume recorded and > 1.
    n = ATR_PERIOD + 12
    closes = [100.0 + i for i in range(n)]
    volumes: list[float | None] = [100.0] * n
    anchor_bar = ATR_PERIOD + 2
    volumes[anchor_bar] = 300.0
    bars = _bars_with_volume(closes, volumes)
    anchor_ts = _T0 + anchor_bar * _STEP
    structure = {"bos": [{"id": "b1", "time": anchor_ts, "price": closes[anchor_bar], "dir": "UP"}]}

    events = family_events_from_structure(structure, bars)

    assert len(events) == 1
    assert "relative_volume" in events[0]
    assert events[0]["relative_volume"] > 1.0


def test_adapter_omits_relative_volume_when_volume_absent() -> None:
    # No bar carries volume -> feature honestly absent (never invented).
    n = ATR_PERIOD + 12
    closes = [100.0 + i for i in range(n)]
    volumes: list[float | None] = [None] * n
    anchor_bar = ATR_PERIOD + 2
    bars = _bars_with_volume(closes, volumes)
    anchor_ts = _T0 + anchor_bar * _STEP
    structure = {"bos": [{"id": "b1", "time": anchor_ts, "price": closes[anchor_bar], "dir": "UP"}]}

    events = family_events_from_structure(structure, bars)

    assert len(events) == 1
    assert "relative_volume" not in events[0]


def _triggered_event(family: str, *, rel_volume: float | None, up: bool) -> FamilyEvent:
    """A minimal level event that triggers immediately with a known sign."""
    base = 100.0
    if up:
        forward = [base + 1.0, base + 2.0, base + 3.0]
    else:
        forward = [base - 1.0, base - 2.0, base - 3.0]
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
    if rel_volume is not None:
        event["relative_volume"] = rel_volume
    return event


def test_extract_feature_samples_pairs_feature_with_binary_outcome() -> None:
    events = [
        _triggered_event("BOS", rel_volume=2.0, up=True),
        _triggered_event("BOS", rel_volume=0.5, up=False),
    ]

    samples = extract_family_feature_samples(events)

    assert "BOS" in samples
    assert samples["BOS"]["feature"] == [2.0, 0.5]
    assert samples["BOS"]["outcomes"] == [1.0, 0.0]
    assert len(samples["BOS"]["anchor_ts"]) == 2


def test_extract_feature_samples_excludes_events_without_feature() -> None:
    events = [
        _triggered_event("BOS", rel_volume=None, up=True),
        _triggered_event("BOS", rel_volume=1.5, up=True),
    ]

    samples = extract_family_feature_samples(events)

    # Only the event carrying the feature is included.
    assert samples["BOS"]["feature"] == [1.5]


def test_extract_feature_samples_empty_when_no_feature_anywhere() -> None:
    events = [_triggered_event("BOS", rel_volume=None, up=True)]
    assert extract_family_feature_samples(events) == {}
