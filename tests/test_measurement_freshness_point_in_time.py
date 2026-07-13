"""Point-in-time guard for freshness_v2 enrichment (audit 2026-07-13, finding #2).

``_freshness_state_light_for_event`` reads ``mitigated`` / ``invalidated`` flags
(and their timestamps) that were computed on the FULL historical frame. A state
must only colour an event's freshness at its anchor if its timestamp was already
reached — otherwise a later mitigation retroactively changes the event's own
raw_score. These tests pin the anchor_ts gate.
"""
from __future__ import annotations

import pandas as pd

from smc_integration.measurement_evidence import _freshness_state_light_for_event

_ANCHOR_TS = 1_700_000_600.0  # anchor bar timestamp (POSIX)


def _bars() -> pd.DataFrame:
    # 12 one-minute bars around the anchor; DatetimeIndex so the bar-seconds
    # approximation in the function works.
    idx = pd.to_datetime(
        [1_700_000_000 + i * 60 for i in range(12)], unit="s"
    )
    return pd.DataFrame({"close": [100.0 + i for i in range(12)]}, index=idx)


def _event(**over: object) -> dict:
    base = {"bar_index": 8, "mitigated": False, "invalidated": False}
    base.update(over)
    return base


def _state(event: dict) -> dict:
    return _freshness_state_light_for_event(
        event=event, anchor_idx=10, anchor_ts=_ANCHOR_TS, bars=_bars()
    )


def test_future_mitigation_not_applied_at_anchor() -> None:
    # Mitigated 10 minutes AFTER the anchor -> must not read as mitigated now.
    s = _state(_event(mitigated=True, mitigated_ts=_ANCHOR_TS + 600))
    assert s["freshness_bucket"] != "mitigated"
    assert s["mitigated_at"] is None


def test_past_mitigation_is_applied_at_anchor() -> None:
    s = _state(_event(mitigated=True, mitigated_ts=_ANCHOR_TS - 120))
    assert s["freshness_bucket"] == "mitigated"
    assert s["mitigated_at"] == _ANCHOR_TS - 120


def test_mitigated_flag_without_timestamp_is_not_trusted() -> None:
    # Can't prove it happened by the anchor -> treat as not-yet-mitigated.
    s = _state(_event(mitigated=True))
    assert s["freshness_bucket"] != "mitigated"


def test_future_invalidation_not_applied_at_anchor() -> None:
    s = _state(_event(invalidated=True, invalidated_ts=_ANCHOR_TS + 300))
    assert s["freshness_bucket"] != "invalidated"
    assert s["invalidated_at"] is None


def test_past_invalidation_is_applied_at_anchor() -> None:
    s = _state(_event(invalidated=True, invalidated_ts=_ANCHOR_TS - 60))
    assert s["freshness_bucket"] == "invalidated"
    assert s["invalidated_at"] == _ANCHOR_TS - 60


def test_invalidation_at_exactly_anchor_ts_counts() -> None:
    # Boundary: ts == anchor_ts is "already reached" (<=), mirrors
    # _candidate_mitigated_at_anchor.
    s = _state(_event(invalidated=True, invalidated_ts=_ANCHOR_TS))
    assert s["freshness_bucket"] == "invalidated"
