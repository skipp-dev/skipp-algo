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


def _invalidated_then_touched_long(family: str) -> FamilyEvent:
    """Long zone [100, 101]: bar 0 closes below the zone (a breach) without
    touching it, then bar 1's low dips into the zone (a late retest touch)."""
    horizon = family_outcome_horizon(family)
    n = horizon + 4
    zone_low, zone_high = 100.0, 101.0
    forward_lows = [98.0, 100.5] + [102.0 + i for i in range(n - 2)]
    forward_highs = [99.0, 101.0] + [103.0 + i for i in range(n - 2)]
    forward_closes = [99.0, 100.8] + [101.5 + 0.5 * i for i in range(n - 2)]
    return {
        "family": family,  # type: ignore[typeddict-item]
        "direction": "BULL",
        "zone_low": zone_low,
        "zone_high": zone_high,
        "anchor_ts": 1.0,
        "forward_highs": forward_highs,
        "forward_lows": forward_lows,
        "forward_closes": forward_closes,
    }


def test_orderblock_touch_after_single_close_invalidation_is_excluded() -> None:
    # OB invalidates on a SINGLE close breach (mirrors smc_core.scoring
    # label_orderblock_mitigation); the retest touch lands after invalidation
    # -> not a tradable mitigation, must be excluded rather than counted.
    assert realized_return(_invalidated_then_touched_long("OB")) is None


def test_fvg_survives_single_close_breach_then_touch() -> None:
    # FVG needs TWO consecutive close breaches to invalidate; a lone breach
    # before the touch does not kill the setup, so a return is produced.
    r = realized_return(_invalidated_then_touched_long("FVG"))
    assert r is not None


def test_fvg_two_consecutive_close_breaches_invalidate_before_touch() -> None:
    horizon = family_outcome_horizon("FVG")
    n = horizon + 4
    # Bars 0 and 1 both close below the zone (two consecutive breaches ->
    # invalidation), bar 2 then retests the zone -> touch is excluded.
    forward_lows = [98.0, 97.0, 100.5] + [102.0 + i for i in range(n - 3)]
    forward_highs = [99.0, 98.0, 101.0] + [103.0 + i for i in range(n - 3)]
    forward_closes = [99.0, 98.5, 100.8] + [101.5 + 0.5 * i for i in range(n - 3)]
    ev: FamilyEvent = {
        "family": "FVG",  # type: ignore[typeddict-item]
        "direction": "BULL",
        "zone_low": 100.0,
        "zone_high": 101.0,
        "anchor_ts": 1.0,
        "forward_highs": forward_highs,
        "forward_lows": forward_lows,
        "forward_closes": forward_closes,
    }
    assert realized_return(ev) is None


# --- EV-24: calibration block flows through to_build_spec -> build_bundle ---

_DAY = 86_400.0


def _scored_immediate_bos(idx: int) -> FamilyEvent:
    """An immediate-entry BOS event carrying a raw score correlated with its
    outcome, spaced far enough apart that the walk-forward purge keeps prior
    training events (guard window << inter-event gap)."""
    horizon = family_outcome_horizon("BOS")
    n = horizon + 1
    anchor = 1_700_000_000.0 + idx * 40.0 * _DAY  # 40d gap >> ~24d guard window
    win = idx % 2 == 0
    entry = 100.0
    close = 101.0 if win else 99.0  # +1% win / -1% loss before cost
    jitter = 0.1 * ((idx % 5) - 2)  # deterministic, score stays family-separable
    event: FamilyEvent = {
        "family": "BOS",  # type: ignore[typeddict-item]
        "direction": "BULL",
        "entry_mode": "immediate",
        "entry_price": entry,
        "zone_low": 0.0,
        "zone_high": 0.0,
        "anchor_ts": anchor,
        "forward_highs": [close + 1.0] * n,
        "forward_lows": [close - 1.0] * n,
        "forward_closes": [close] * n,
        "forward_timestamps": [anchor + (j + 1) * _DAY for j in range(n)],
        "score": (2.0 if win else 0.5) + jitter,
    }
    return event


def test_to_build_spec_emits_calibration_block_and_ev24_provenance() -> None:
    events = [_scored_immediate_bos(i) for i in range(160)]
    spec = to_build_spec(events, as_of=1_700_000_000.0 + 200.0 * 40.0 * _DAY)

    bos = spec["families"]["BOS"]
    block = bos["calibration"]["walkforward"]
    probs, outcomes = block["probabilities"], block["outcomes"]
    assert len(probs) == len(outcomes) >= 40
    assert all(0.0 <= p <= 1.0 for p in probs)
    assert all(o in (0.0, 1.0) for o in outcomes)

    # EV-24 audit-only provenance is attached alongside the block.
    prov = bos["provenance"]
    assert prov["ev24_calibrator"] == "platt_logistic_standardised_v1"
    assert prov["ev24_calibration_target"] == "sign_return_secondary_diagnostic"
    assert "ev24_score_source" in prov and "ev24_fold_scheme" in prov


def test_to_build_spec_emits_live_surrogate_block_and_ev25_provenance() -> None:
    from governance.family_calibration import (
        LIVE_SOURCE_TAG,
        LIVE_TAIL_MIN_SAMPLES,
    )

    events = [_scored_immediate_bos(i) for i in range(160)]
    spec = to_build_spec(events, as_of=1_700_000_000.0 + 200.0 * 40.0 * _DAY)

    bos = spec["families"]["BOS"]
    calibration = bos["calibration"]
    # ADR-0017: the most-recent OOS window is declared the live surrogate.
    assert "live" in calibration
    live = calibration["live"]
    assert len(live["probabilities"]) == LIVE_TAIL_MIN_SAMPLES
    assert len(live["outcomes"]) == LIVE_TAIL_MIN_SAMPLES
    assert all(0.0 <= p <= 1.0 for p in live["probabilities"])
    assert all(o in (0.0, 1.0) for o in live["outcomes"])
    # The walk-forward remainder stays adequately powered.
    assert len(calibration["walkforward"]["probabilities"]) >= 40
    # The EV-25 source tag rides alongside the EV-24 provenance.
    assert bos["provenance"]["ev25_live_source"] == LIVE_SOURCE_TAG


def test_to_build_spec_omits_live_surrogate_when_pool_too_small() -> None:
    # 72 events -> OOS pool below LIVE_TAIL_MIN_SAMPLES + MIN_OOS_SAMPLES, so no
    # split: the full pooled walk-forward is kept and live stays unmeasured.
    events = [_scored_immediate_bos(i) for i in range(72)]
    spec = to_build_spec(events, as_of=1_700_000_000.0 + 200.0 * 40.0 * _DAY)

    bos = spec["families"]["BOS"]
    calibration = bos["calibration"]
    assert "walkforward" in calibration
    assert "live" not in calibration
    assert "ev25_live_source" not in bos.get("provenance", {})


def test_live_surrogate_yields_measured_live_brier_in_bundle() -> None:
    from scripts.build_family_metrics import build_bundle

    events = [_scored_immediate_bos(i) for i in range(160)]
    spec = to_build_spec(events, as_of=1_700_000_000.0 + 200.0 * 40.0 * _DAY)
    bundle = build_bundle(spec)

    bos = next(m for m in bundle if m["family"] == "BOS")
    # The live Brier is now MEASURED (no longer "not yet measured"), enabling
    # the live_vs_wf_ratio gate check to evaluate instead of info-blocking.
    assert bos["live_brier"] is not None


def test_calibration_block_yields_measured_brier_in_bundle() -> None:
    from scripts.build_family_metrics import build_bundle

    events = [_scored_immediate_bos(i) for i in range(160)]
    spec = to_build_spec(events, as_of=1_700_000_000.0 + 200.0 * 40.0 * _DAY)
    bundle = build_bundle(spec)

    bos = next(m for m in bundle if m["family"] == "BOS")
    # The headline gate Brier is now MEASURED (no longer "not yet measured").
    assert bos["brier"] is not None
    assert bos["ece"] is not None
    # Separable score -> out-of-sample Brier beats the 0.25 coin-flip baseline.
    assert bos["brier"] < 0.25


# --- EV#6: C9 psi_trend block flows through to_build_spec -> build_bundle ---


def test_to_build_spec_emits_psi_trend_block_and_source_provenance() -> None:
    events = [_scored_immediate_bos(i) for i in range(160)]
    spec = to_build_spec(events, as_of=1_700_000_000.0 + 200.0 * 40.0 * _DAY)

    bos = spec["families"]["BOS"]
    psi_trend = bos["psi_trend"]
    assert len(psi_trend["reference_probabilities"]) > 0
    assert len(psi_trend["windows"]) >= 2
    for window in psi_trend["windows"]:
        assert all(0.0 <= p <= 1.0 for p in window)

    # The EV#6 source tag rides alongside the EV-24 calibration provenance.
    assert (
        bos["provenance"]["ev24_psi_trend_source"]
        == "ev24_fixed_reference_calibrator_chronological_windows_v1"
    )


def test_psi_trend_block_yields_measured_psi_slope_in_bundle() -> None:
    from scripts.build_family_metrics import build_bundle

    events = [_scored_immediate_bos(i) for i in range(160)]
    spec = to_build_spec(events, as_of=1_700_000_000.0 + 200.0 * 40.0 * _DAY)
    bundle = build_bundle(spec)

    bos = next(m for m in bundle if m["family"] == "BOS")
    # The C9 drift slope is now MEASURED (no longer "not yet measured"), and
    # the producer's slope-fit method is recorded in provenance.
    assert bos["psi_slope"] is not None
    assert bos["provenance"]["psi_trend_method"] == "ols_psi_window_slope"


# --- EV#7: C5.1 regime_degraded flows through to_build_spec -> build_bundle ---


def _regime_bos(idx: int, *, regime: str, win: bool) -> FamilyEvent:
    """An immediate-entry BOS event carrying a regime label and a controlled
    win/loss outcome, spaced like ``_scored_immediate_bos``."""
    horizon = family_outcome_horizon("BOS")
    n = horizon + 1
    anchor = 1_700_000_000.0 + idx * 40.0 * _DAY
    entry = 100.0
    close = 105.0 if win else 99.0  # +5% win / -1% loss before cost
    event: FamilyEvent = {
        "family": "BOS",  # type: ignore[typeddict-item]
        "direction": "BULL",
        "entry_mode": "immediate",
        "entry_price": entry,
        "zone_low": 0.0,
        "zone_high": 0.0,
        "anchor_ts": anchor,
        "forward_highs": [close + 1.0] * n,
        "forward_lows": [close - 1.0] * n,
        "forward_closes": [close] * n,
        "forward_timestamps": [anchor + (j + 1) * _DAY for j in range(n)],
        "regime": regime,
    }
    return event


def test_regime_degradation_unit_rules() -> None:
    from governance.family_returns import regime_degradation

    # No labelled events -> not yet measurable.
    assert regime_degradation([], [], []) is None

    # Pooled mean <= 0 -> a global no-edge problem, not regime-conditional.
    assert (
        regime_degradation([-0.01] * 30, ["RANGING"] * 30, list(range(30))) is False
    )

    # Pooled edge positive, but the CURRENT (latest) regime has >=20 samples
    # and a non-positive mean -> degraded.
    returns = [0.05] * 25 + [-0.01] * 25  # pooled mean > 0
    regimes = ["TRENDING"] * 25 + ["RANGING"] * 25
    anchor = list(range(50))  # RANGING events are the most recent
    assert regime_degradation(returns, regimes, anchor) is True

    # Same pooled edge but the current regime is itself positive -> not degraded.
    returns2 = [-0.01] * 25 + [0.05] * 25
    regimes2 = ["RANGING"] * 25 + ["TRENDING"] * 25
    assert regime_degradation(returns2, regimes2, list(range(50))) is False

    # Current regime under-sampled (<20) -> not yet measurable.
    returns3 = [0.05] * 40 + [-0.01] * 5
    regimes3 = ["TRENDING"] * 40 + ["RANGING"] * 5
    assert regime_degradation(returns3, regimes3, list(range(45))) is None


def test_regime_degradation_length_mismatch_raises() -> None:
    from governance.family_returns import regime_degradation

    with pytest.raises(ValueError, match="length mismatch"):
        regime_degradation([0.01, 0.02], ["TRENDING"], [0.0, 1.0])


def test_extract_family_regime_samples_drops_unlabelled() -> None:
    from governance.family_returns import extract_family_regime_samples

    labelled = _regime_bos(0, regime="TRENDING", win=True)
    unlabelled = _scored_immediate_bos(1)  # carries score but NO regime
    samples = extract_family_regime_samples([labelled, unlabelled])

    bos = samples["BOS"]
    assert len(bos["returns"]) == 1
    assert bos["regimes"] == ["TRENDING"]
    assert len(bos["anchor_ts"]) == 1


def test_to_build_spec_emits_regime_degraded_and_provenance() -> None:
    # Older TRENDING winners (pooled edge), most-recent RANGING losers with
    # >=20 samples -> the family is degraded in the regime it would trade next.
    events = [_regime_bos(i, regime="TRENDING", win=True) for i in range(25)]
    events += [_regime_bos(25 + i, regime="RANGING", win=False) for i in range(25)]
    spec = to_build_spec(events, as_of=1_700_000_000.0 + 200.0 * 40.0 * _DAY)

    bos = spec["families"]["BOS"]
    assert bos["regime_degraded"] is True
    assert (
        bos["provenance"]["ev24_regime_source"]
        == "kaufman_efficiency_ratio_trailing_closes_v1"
    )


def test_regime_degraded_flows_through_bundle_as_blocker() -> None:
    from scripts.build_family_metrics import build_bundle

    events = [_regime_bos(i, regime="TRENDING", win=True) for i in range(25)]
    events += [_regime_bos(25 + i, regime="RANGING", win=False) for i in range(25)]
    spec = to_build_spec(events, as_of=1_700_000_000.0 + 200.0 * 40.0 * _DAY)
    bundle = build_bundle(spec)

    bos = next(m for m in bundle if m["family"] == "BOS")
    # The C5.1 verdict is now MEASURED and rides through to the gate payload.
    assert bos["regime_degraded"] is True


