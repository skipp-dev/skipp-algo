"""Tests for the 'qualify, don't block' layering policy.

Hard blocks (trade_state=BLOCKED) must be reserved for fatal data/health failures.
Volume regimes and event risk should only downgrade + warn, never hard-block.
"""

from __future__ import annotations

import pytest

from smc_core.layering import apply_layering
from smc_core.types import (
    EventRisk,
    SmcMeta,
    SmcStructure,
    Orderblock,
    TimedVolumeInfo,
    VolumeInfo,
)


def _meta(regime: str, *, event_risk: EventRisk | None = None) -> SmcMeta:
    return SmcMeta(
        symbol="TEST",
        timeframe="15m",
        asof_ts=100.0,
        volume=TimedVolumeInfo(
            value=VolumeInfo(regime=regime, thin_fraction=0.5),
            asof_ts=100.0,
            stale=False,
        ),
        event_risk=event_risk,
    )


def _structure_with_ob() -> SmcStructure:
    return SmcStructure(
        orderblocks=[
            Orderblock(id="ob:TEST:15m:100:BULL:99.00:100.00", low=99.0, high=100.0, dir="BULL", valid=True)
        ]
    )


class TestQualifyDontBlock:
    """Volume regimes and event risk must not produce BLOCKED — only DISCOURAGED + warnings."""

    def test_holiday_suspect_not_blocked(self) -> None:
        snapshot = apply_layering(_structure_with_ob(), _meta("HOLIDAY_SUSPECT"), generated_at=1.0)
        for style in snapshot.layered.zone_styles.values():
            assert style.trade_state != "BLOCKED", (
                f"HOLIDAY_SUSPECT must not hard-block; got trade_state=BLOCKED for {style.reason_codes}"
            )
            assert "WARNING" == style.tone or style.trade_state == "DISCOURAGED"

    def test_low_volume_not_blocked(self) -> None:
        snapshot = apply_layering(_structure_with_ob(), _meta("LOW_VOLUME"), generated_at=1.0)
        for style in snapshot.layered.zone_styles.values():
            assert style.trade_state != "BLOCKED"

    def test_event_risk_high_not_blocked(self) -> None:
        er = EventRisk(event_type="FOMC", severity="HIGH", window_start=50.0, window_end=150.0)
        snapshot = apply_layering(_structure_with_ob(), _meta("NORMAL", event_risk=er), generated_at=1.0)
        for style in snapshot.layered.zone_styles.values():
            assert style.trade_state != "BLOCKED", (
                f"EVENT_RISK_HIGH must not hard-block; got BLOCKED for {style.reason_codes}"
            )
            assert style.trade_state == "DISCOURAGED"

    def test_event_risk_high_reduces_strength(self) -> None:
        er = EventRisk(event_type="FOMC", severity="HIGH", window_start=50.0, window_end=150.0)
        snapshot_normal = apply_layering(_structure_with_ob(), _meta("NORMAL"), generated_at=1.0)
        snapshot_event = apply_layering(_structure_with_ob(), _meta("NORMAL", event_risk=er), generated_at=1.0)
        for key in snapshot_normal.layered.zone_styles:
            s_normal = snapshot_normal.layered.zone_styles[key].strength
            s_event = snapshot_event.layered.zone_styles[key].strength
            assert s_event <= s_normal, "Event risk should reduce strength"

    def test_normal_regime_allows_allowed(self) -> None:
        snapshot = apply_layering(_structure_with_ob(), _meta("NORMAL"), generated_at=1.0)
        states = {s.trade_state for s in snapshot.layered.zone_styles.values()}
        # NORMAL regime should not force BLOCKED
        assert "BLOCKED" not in states

    def test_reason_codes_are_bounded(self) -> None:
        """Each zone should have at most a bounded number of reason codes (machine-readable)."""
        er = EventRisk(event_type="CPI", severity="HIGH", window_start=50.0, window_end=150.0)
        snapshot = apply_layering(_structure_with_ob(), _meta("HOLIDAY_SUSPECT", event_risk=er), generated_at=1.0)
        for style in snapshot.layered.zone_styles.values():
            assert len(style.reason_codes) <= 10, f"Too many reason codes: {style.reason_codes}"
