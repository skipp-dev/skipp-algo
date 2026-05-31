"""EV-06b — per-family realized-return extractor tests.

Verifies the variant-A trade definition (touch -> horizon-close exit,
signed, minus cost), lookahead refusal, untriggered-setup exclusion, and
that the produced spec flows into ``build_family_metrics`` to yield real
PSR/MinTRL — all without fabricating market data inside the module.
"""
from __future__ import annotations

import pytest

from governance.family_returns import (
    DEFAULT_COST_BPS,
    FamilyEvent,
    extract_family_returns,
    realized_return,
    to_build_spec,
)
from governance.family_walkforward import family_outcome_horizon


def _long_event(
    family: str = "BOS",
    *,
    anchor_ts: float = 1.0,
    rising: bool = True,
    timestamps: bool = False,
    step: float | None = None,
) -> FamilyEvent:
    horizon = family_outcome_horizon(family)
    n = horizon + 3
    zone_low, zone_high = 100.0, 101.0  # mid = 100.5 = entry
    # First forward bar dips into the zone (touch at idx 0); later bars leave it.
    forward_lows = [100.5] + [102.0 + i for i in range(n - 1)]
    forward_highs = [101.0] + [103.0 + i for i in range(n - 1)]
    if step is None:
        step = 0.5 if rising else -0.5
    forward_closes = [100.8 + step * i for i in range(n)]
    event: FamilyEvent = {
        "family": family,  # type: ignore[typeddict-item]
        "direction": "BULL",
        "zone_low": zone_low,
        "zone_high": zone_high,
        "anchor_ts": anchor_ts,
        "forward_highs": forward_highs,
        "forward_lows": forward_lows,
        "forward_closes": forward_closes,
    }
    if timestamps:
        event["forward_timestamps"] = [anchor_ts + 1.0 + i for i in range(n)]
    return event


def _short_event(
    family: str = "OB", *, anchor_ts: float = 1.0, step: float = 0.5
) -> FamilyEvent:
    horizon = family_outcome_horizon(family)
    n = horizon + 3
    zone_low, zone_high = 100.0, 101.0  # mid = 100.5 = entry
    # First forward bar pokes high into the zone (touch); price then falls.
    forward_highs = [100.5] + [98.0 - i for i in range(n - 1)]
    forward_lows = [99.0] + [97.0 - i for i in range(n - 1)]
    forward_closes = [100.2 - step * i for i in range(n)]
    return {
        "family": family,  # type: ignore[typeddict-item]
        "direction": "BEAR",
        "zone_low": zone_low,
        "zone_high": zone_high,
        "anchor_ts": anchor_ts,
        "forward_highs": forward_highs,
        "forward_lows": forward_lows,
        "forward_closes": forward_closes,
    }


def test_long_event_yields_positive_return() -> None:
    r = realized_return(_long_event(rising=True), cost_bps=0.0)
    assert r is not None and r > 0.0


def test_short_event_yields_positive_return() -> None:
    r = realized_return(_short_event(), cost_bps=0.0)
    assert r is not None and r > 0.0


def test_cost_strictly_reduces_return() -> None:
    ev = _long_event(rising=True)
    cheap = realized_return(ev, cost_bps=2.0)
    dear = realized_return(ev, cost_bps=50.0)
    assert cheap is not None and dear is not None
    assert dear < cheap
    # cost is a flat bps subtraction
    assert cheap - dear == pytest.approx((50.0 - 2.0) / 1e4)


def test_untriggered_setup_is_excluded() -> None:
    ev = _long_event()
    # Move the zone far below all forward lows -> never touched.
    ev["zone_low"] = 1.0
    ev["zone_high"] = 2.0
    assert realized_return(ev) is None


def test_unknown_direction_is_none() -> None:
    ev = _long_event()
    ev["direction"] = "SIDEWAYS"
    assert realized_return(ev) is None


def test_lookahead_forward_timestamp_is_refused() -> None:
    ev = _long_event(anchor_ts=100.0, timestamps=True)
    ev["forward_timestamps"][2] = 100.0  # equal to anchor -> leak
    with pytest.raises(ValueError, match="lookahead leak"):
        realized_return(ev)


def test_extract_groups_by_family_and_drops_nontriggers() -> None:
    triggered = _long_event("BOS", anchor_ts=1.0)
    other = _short_event("OB", anchor_ts=2.0)
    dud = _long_event("FVG", anchor_ts=3.0)
    dud["zone_low"], dud["zone_high"] = 1.0, 2.0  # never touched
    grouped = extract_family_returns([triggered, other, dud])
    assert set(grouped) == {"BOS", "OB"}
    assert len(grouped["BOS"]["returns"]) == 1
    assert grouped["BOS"]["timestamps"] == [1.0]


def test_to_build_spec_feeds_real_psr() -> None:
    from scripts.build_family_metrics import build_bundle

    # >= MIN_OBSERVATIONS_FOR_PSR triggered events per family so the PSR
    # producer (and its walk-forward fold check) accepts the series.
    # Vary the per-event close slope so the return series has variance.
    events: list[FamilyEvent] = []
    for i in range(60):
        slope = 0.3 + 0.02 * (i % 7)
        events.append(_long_event("BOS", anchor_ts=float(i + 1), step=slope))
        events.append(_short_event("OB", anchor_ts=float(i + 1), step=slope))

    spec = to_build_spec(events, periods_per_year=252, as_of=10_000.0)
    bundle = build_bundle(spec)
    by_family = {m["family"]: m for m in bundle}
    assert set(by_family) == {"BOS", "OB"}
    for m in by_family.values():
        assert 0.0 <= m["psr"] <= 1.0
        assert m["provenance"]["psr_method"] == "bailey_lopez_de_prado_2012"
        # honestly-unmeasured fields stay None
        assert m["brier"] is None


def test_default_cost_is_applied() -> None:
    ev = _long_event(rising=True)
    with_default = realized_return(ev)
    explicit = realized_return(ev, cost_bps=DEFAULT_COST_BPS)
    assert with_default == explicit
