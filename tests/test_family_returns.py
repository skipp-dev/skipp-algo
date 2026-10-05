"""EV-06b — per-family realized-return extractor tests.

Verifies the trade definition ``next_open_then_horizon_close`` (decision
bar -> entry at the next bar's open -> horizon-close exit, signed, minus
cost; ADR-0031, Nachtrag 2026-10-02 II), lookahead refusal,
untriggered-setup exclusion, and that the produced spec flows into
``build_family_metrics`` to yield real PSR/MinTRL — all without
fabricating market data inside the module.
"""
from __future__ import annotations

import pytest

from governance.family_returns import (
    DEFAULT_COST_BPS,
    LEGACY_RETURN_RULE,
    RETURN_RULE,
    RETURN_RULE_EVIDENCE_START,
    FamilyEvent,
    _event_bar_interval,
    _guard_end_ts,
    extract_family_calibration_samples,
    extract_family_returns,
    realized_return,
    to_build_spec,
)
from governance.family_walkforward import family_outcome_horizon, get_family_config


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
    zone_low, zone_high = 100.0, 101.0
    # First forward bar dips into the zone (decision bar = idx 0); later bars
    # leave it. Every bar opens at the previous close, so the entry — the open
    # of idx 1 — is 100.8.
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
        "forward_opens": [100.9, *forward_closes[:-1]],
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
    zone_low, zone_high = 100.0, 101.0
    # First forward bar pokes high into the zone (decision bar); price then
    # falls. Entry is the open of idx 1 = the close of idx 0 = 100.2.
    forward_highs = [100.5] + [98.0 - i for i in range(n - 1)]
    forward_lows = [99.0] + [97.0 - i for i in range(n - 1)]
    forward_closes = [100.2 - step * i for i in range(n)]
    return {
        "family": family,  # type: ignore[typeddict-item]
        "direction": "BEAR",
        "zone_low": zone_low,
        "zone_high": zone_high,
        "anchor_ts": anchor_ts,
        "forward_opens": [100.4, *forward_closes[:-1]],
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


def test_retest_requires_full_horizon_after_touch() -> None:
    horizon = family_outcome_horizon("BOS")
    n = horizon + 1
    ev: FamilyEvent = {
        "family": "BOS",  # type: ignore[typeddict-item]
        "direction": "BULL",
        "zone_low": 100.0,
        "zone_high": 101.0,
        "anchor_ts": 1.0,
        # The zone is reached at idx=1, leaving only horizon-1 bars after it.
        "forward_opens": [103.5] * n,
        "forward_lows": [103.0, 100.5] + [103.0] * (n - 2),
        "forward_highs": [104.0] * n,
        "forward_closes": [102.0] * n,
    }
    assert realized_return(ev) is None
    # Positive control: one more bar and the same setup IS a trade — the None
    # above is the horizon, not a missing field.
    for key, value in (("forward_opens", 103.5), ("forward_lows", 103.0), ("forward_highs", 104.0), ("forward_closes", 102.0)):
        ev[key] = [*ev[key], value]  # type: ignore[literal-required]
    assert realized_return(ev, cost_bps=0.0) == pytest.approx((102.0 - 103.5) / 103.5)


def test_event_bar_interval_even_sample_uses_true_median() -> None:
    # Positive diffs are [1, 3, 7, 9] -> median should be (3 + 7) / 2 = 5.
    fts = [0.0, 1.0, 4.0, 11.0, 20.0]
    assert _event_bar_interval(fts) == pytest.approx(5.0)


def test_unknown_direction_is_none() -> None:
    ev = _long_event()
    ev["direction"] = "SIDEWAYS"
    assert realized_return(ev) is None


def test_lookahead_forward_timestamp_is_refused() -> None:
    ev = _long_event(anchor_ts=100.0, timestamps=True)
    ev["forward_timestamps"][2] = 100.0  # equal to anchor -> leak
    with pytest.raises(ValueError, match="lookahead leak"):
        realized_return(ev)


def test_guard_end_keys_on_label_end_idx_not_buffer_end() -> None:
    fts = [10.0, 11.0, 12.0, 13.0, 14.0]  # interval 1.0; buffer end at idx 4
    # label actually consumed up to idx 2 -> guard keys on fts[2], not fts[-1]
    assert _guard_end_ts(fts, 2, label_end_idx=2) == pytest.approx(12.0 + 2 * 1.0)
    # default (-1) preserves the old buffer-end behavior for callers without an exit
    assert _guard_end_ts(fts, 2) == pytest.approx(14.0 + 2 * 1.0)
    # a tighter label end can only move the guard EARLIER (less over-purging)
    assert _guard_end_ts(fts, 2, label_end_idx=2) < _guard_end_ts(fts, 2)


def test_calibration_guard_end_tightened_to_consumed_exit() -> None:
    # OB retest: horizon 6, touch at forward idx 0 -> exit at idx 6; the adapter
    # buffer runs to idx 8 (n = horizon + 3). The purge guard must key on the EXIT
    # bar (fts[6]), not the buffer end (fts[8]) — tighter but still fully leak-safe.
    ev = _long_event(family="OB", rising=True, timestamps=True)
    ev["score"] = 0.7
    fts = [float(t) for t in ev["forward_timestamps"]]
    horizon = family_outcome_horizon("OB")
    exit_idx = 0 + horizon  # touch idx 0 + horizon
    embargo = get_family_config("OB").embargo_bars
    interval = _event_bar_interval(fts)

    samples = extract_family_calibration_samples([ev], cost_bps=0.0)
    guard = samples["OB"]["guard_end_ts"][0]
    assert guard == pytest.approx(fts[exit_idx] + embargo * interval)
    # tighter than the old buffer-end guard ...
    assert guard < fts[-1] + embargo * interval
    # ... yet never ends BEFORE the consumed label (leak-safety preserved)
    assert guard >= fts[exit_idx]


def test_extract_groups_by_family_and_drops_nontriggers() -> None:
    triggered = _long_event("BOS", anchor_ts=1.0)
    other = _short_event("OB", anchor_ts=2.0)
    dud = _long_event("FVG", anchor_ts=3.0)
    dud["zone_low"], dud["zone_high"] = 1.0, 2.0  # never touched
    grouped = extract_family_returns([triggered, other, dud])
    assert set(grouped) == {"BOS", "OB"}
    assert len(grouped["BOS"]["returns"]) == 1
    assert grouped["BOS"]["timestamps"] == [1.0]


def test_extract_calibration_samples_threads_event_ids() -> None:
    ev = _long_event("BOS", anchor_ts=1.0, timestamps=True)
    ev["score"] = 0.7
    ev["event_id"] = "evt-123"
    samples = extract_family_calibration_samples([ev], cost_bps=0.0)
    bos = samples["BOS"]
    assert bos["event_ids"] == ["evt-123"]
    assert len(bos["event_ids"]) == len(bos["scores"]) == 1  # parallel to the numeric lists


def test_extract_calibration_samples_event_id_defaults_empty_when_absent() -> None:
    ev = _long_event("BOS", anchor_ts=1.0, timestamps=True)
    ev["score"] = 0.7  # no event_id on the event
    samples = extract_family_calibration_samples([ev], cost_bps=0.0)
    assert samples["BOS"]["event_ids"] == [""]


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


def test_to_build_spec_declares_smc_direct_no_ml_pipeline_class() -> None:
    # ADR-0016: this producer builds SMC-direct families, so it declares the
    # no-ML pipeline class on every family and it flows through to the bundle.
    from governance.promotion_gate import PIPELINE_CLASS_KEY, SMC_DIRECT_NO_ML
    from scripts.build_family_metrics import build_bundle

    events: list[FamilyEvent] = []
    for i in range(60):
        # Vary the slope: a constant return series has no variance and no PSR.
        events.append(_long_event("BOS", anchor_ts=float(i + 1), step=0.3 + 0.02 * (i % 7)))

    spec = to_build_spec(events, periods_per_year=252, as_of=10_000.0)
    assert spec["families"]["BOS"]["provenance"][PIPELINE_CLASS_KEY] == SMC_DIRECT_NO_ML
    bundle = build_bundle(spec)
    assert bundle[0]["provenance"][PIPELINE_CLASS_KEY] == SMC_DIRECT_NO_ML


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
        "forward_opens": [98.5, *forward_closes[:-1]],
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
        "forward_opens": [98.5, *forward_closes[:-1]],
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
        # The bar after the signal opens AT the level, so the return under the
        # next-open rule equals the move from 100 to the exit close.
        "forward_opens": [entry] * n,
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


def test_to_build_spec_emits_conformal_block_and_ev26_provenance() -> None:
    from governance.family_calibration import (
        CONFORMAL_MIN_SIDE,
        CONFORMAL_SOURCE_TAG,
    )

    events = [_scored_immediate_bos(i) for i in range(160)]
    spec = to_build_spec(events, as_of=1_700_000_000.0 + 200.0 * 40.0 * _DAY)

    bos = spec["families"]["BOS"]
    conformal = bos["conformal"]
    # ADR-0018: split-conformal block with calibration + held-out test sets.
    assert 0.0 < conformal["alpha"] < 1.0
    cal = conformal["calibration"]
    test = conformal["test"]
    assert len(cal["probabilities"]) >= CONFORMAL_MIN_SIDE
    assert len(test["probabilities"]) >= CONFORMAL_MIN_SIDE
    assert all(0.0 <= p <= 1.0 for p in cal["probabilities"] + test["probabilities"])
    assert all(o in (0.0, 1.0) for o in cal["outcomes"] + test["outcomes"])
    # The EV-26 source tag rides alongside the EV-24/EV-25 provenance.
    assert bos["provenance"]["ev26_conformal_source"] == CONFORMAL_SOURCE_TAG


def test_to_build_spec_omits_conformal_when_pool_too_small() -> None:
    # 90 events -> OOS pool below 2 * CONFORMAL_MIN_SIDE, so no conformal split:
    # conformal_coverage stays "not yet measured".
    events = [_scored_immediate_bos(i) for i in range(90)]
    spec = to_build_spec(events, as_of=1_700_000_000.0 + 200.0 * 40.0 * _DAY)

    bos = spec["families"]["BOS"]
    assert "conformal" not in bos
    assert "ev26_conformal_source" not in bos.get("provenance", {})


def test_conformal_block_yields_measured_coverage_in_bundle() -> None:
    from scripts.build_family_metrics import build_bundle

    events = [_scored_immediate_bos(i) for i in range(160)]
    spec = to_build_spec(events, as_of=1_700_000_000.0 + 200.0 * 40.0 * _DAY)
    bundle = build_bundle(spec)

    bos = next(m for m in bundle if m["family"] == "BOS")
    # Coverage and target are now MEASURED (no longer "not yet measured"),
    # enabling the conformal_coverage gate check to evaluate.
    assert bos["conformal_coverage"] is not None
    assert bos["conformal_target"] is not None
    assert 0.0 <= bos["conformal_coverage"] <= 1.0
    assert bos["provenance"]["conformal_method"] == "split_conformal_vovk"


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
        # The bar after the signal opens AT the level, so the return under the
        # next-open rule equals the move from 100 to the exit close.
        "forward_opens": [entry] * n,
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


# --- Stat-review S3 (#2674): horizon-truncation + embargo-collapse guards ---


def _short_window_immediate_bos() -> FamilyEvent:
    """Immediate-entry BOS whose forward window is one bar SHORT of the
    outcome horizon — pre-S3 the clamp silently exited at the last close."""
    horizon = family_outcome_horizon("BOS")
    n = horizon - 1
    event: FamilyEvent = {
        "family": "BOS",  # type: ignore[typeddict-item]
        "direction": "BULL",
        "entry_mode": "immediate",
        "entry_price": 100.0,
        "zone_low": 0.0,
        "zone_high": 0.0,
        "anchor_ts": 1.0,
        "forward_opens": [100.0] * n,
        "forward_highs": [102.0] * n,
        "forward_lows": [100.0] * n,
        "forward_closes": [101.0] * n,
    }
    return event


def test_immediate_mode_refuses_horizon_truncated_window() -> None:
    # Pre-S3 this returned a (truncated) ~+1% return; now it is not a trade.
    assert realized_return(_short_window_immediate_bos()) is None


def test_immediate_mode_exact_horizon_window_still_measures() -> None:
    ev = _short_window_immediate_bos()
    horizon = family_outcome_horizon("BOS")
    ev["forward_opens"] = [100.0] * horizon
    ev["forward_highs"] = [102.0] * horizon
    ev["forward_lows"] = [100.0] * horizon
    ev["forward_closes"] = [101.0] * horizon
    ret = realized_return(ev)
    assert ret is not None
    assert ret == pytest.approx(0.01 - DEFAULT_COST_BPS / 1e4)


def test_guard_end_ts_refuses_degenerate_interval_with_embargo() -> None:
    # All-equal timestamps -> interval 0; a non-zero embargo cannot be
    # expressed in wall-clock time, so the guard must refuse (None) rather
    # than silently collapse to the label end.
    assert _guard_end_ts([5.0, 5.0, 5.0], embargo_bars=16) is None
    # Zero embargo: the collapse is harmless — label end is returned.
    assert _guard_end_ts([5.0, 5.0, 5.0], embargo_bars=0) == 5.0
    # Healthy spacing: label end + embargo * interval.
    assert _guard_end_ts([0.0, 10.0, 20.0], embargo_bars=2) == 40.0


def test_calibration_samples_exclude_degenerate_embargo_window() -> None:
    good = _scored_immediate_bos(0)
    bad = _scored_immediate_bos(1)
    # Degenerate forward clock: every timestamp identical (interval 0).
    bad["forward_timestamps"] = [bad["forward_timestamps"][0]] * len(
        bad["forward_timestamps"]
    )
    samples = extract_family_calibration_samples([good, bad])
    # BOS embargo_bars > 0, so the degenerate event must be excluded.
    assert len(samples["BOS"]["returns"]) == 1
    assert samples["BOS"]["anchor_ts"] == [good["anchor_ts"]]


# --- ADR-0031, Nachtrag 2026-10-02 II: the entry is a price that traded ---


def _level_event(*, level: float, opens: list[float], closes: list[float], direction: str = "UP") -> FamilyEvent:
    return {
        "family": "SWEEP",  # type: ignore[typeddict-item]  # horizon 3
        "direction": direction,
        "entry_mode": "immediate",
        "entry_price": level,
        "anchor_ts": 1.0,
        "forward_opens": opens,
        "forward_highs": [max(o, c) + 0.1 for o, c in zip(opens, closes, strict=True)],
        "forward_lows": [min(o, c) - 0.1 for o, c in zip(opens, closes, strict=True)],
        "forward_closes": closes,
    }


def test_the_rule_names_itself_and_its_predecessor() -> None:
    assert RETURN_RULE == "next_open_then_horizon_close"
    assert LEGACY_RETURN_RULE == "touch_then_horizon_close"
    assert RETURN_RULE != LEGACY_RETURN_RULE
    assert RETURN_RULE_EVIDENCE_START == "2026-10-05"


def test_level_family_enters_at_the_next_open_not_at_the_level() -> None:
    """Break level 100, the signal bar has already run to ~102: the bar after
    it opens at 102. Variant A booked the 2 % in between; no trade could."""
    assert family_outcome_horizon("SWEEP") == 3
    ev = _level_event(level=100.0, opens=[102.0, 102.5, 103.0], closes=[102.5, 103.0, 103.02])
    ret = realized_return(ev, cost_bps=0.0)
    assert ret == pytest.approx((103.02 - 102.0) / 102.0)
    # The level is not part of the return: move it and nothing changes.
    ev["entry_price"] = 50.0
    assert realized_return(ev, cost_bps=0.0) == ret


def test_short_level_family_is_signed_from_the_next_open() -> None:
    ev = _level_event(level=100.0, opens=[98.0, 97.5, 97.0], closes=[97.5, 97.0, 96.04], direction="DOWN")
    assert realized_return(ev, cost_bps=0.0) == pytest.approx((98.0 - 96.04) / 98.0)


@pytest.mark.parametrize("opens", [None, [], [102.0, 102.5]])
def test_an_event_without_aligned_opens_is_not_a_trade(opens) -> None:
    """Pool events recorded before 2026-10-02 carry no opens. No price is
    substituted — not the level, not a close."""
    ev = _level_event(level=100.0, opens=[102.0, 102.5, 103.0], closes=[102.5, 103.0, 103.02])
    assert realized_return(ev) is not None
    if opens is None:
        del ev["forward_opens"]
    else:
        ev["forward_opens"] = opens
    assert realized_return(ev) is None
    assert extract_family_returns([ev]) == {}


def _zone_event(family: str, *, lows: list[float], highs: list[float], closes: list[float], opens: list[float]) -> FamilyEvent:
    return {
        "family": family,  # type: ignore[typeddict-item]
        "direction": "BULL",
        "zone_low": 100.0,
        "zone_high": 101.0,
        "anchor_ts": 1.0,
        "forward_opens": opens,
        "forward_highs": highs,
        "forward_lows": lows,
        "forward_closes": closes,
    }


def test_zone_family_enters_at_the_open_after_the_bar_that_reached_the_zone() -> None:
    """Zone [100, 101], midpoint 100.5. Bar 1 dips to 100.9 — the midpoint
    never trades. Variant A bought at 100.5 anyway; the rule buys the open of
    bar 2 (101.6) and exits at the close ``horizon`` bars after bar 1."""
    h = family_outcome_horizon("FVG")
    n = h + 3
    lows = [102.0, 100.9] + [101.5] * (n - 2)
    highs = [103.0, 102.0] + [103.0] * (n - 2)
    closes = [102.5, 101.5] + [102.0 + 0.1 * i for i in range(n - 2)]
    opens = [102.8, 102.4, 101.6] + [102.0] * (n - 3)
    ev = _zone_event("FVG", lows=lows, highs=highs, closes=closes, opens=opens)
    assert realized_return(ev, cost_bps=0.0) == pytest.approx((closes[1 + h] - 101.6) / 101.6)


def test_a_bar_that_trades_through_the_zone_is_the_decision_bar() -> None:
    """Bar 0 falls from above the zone to 99.5 — through it — and closes back
    inside at 100.4. Variant A did not count that bar (its low did not come
    to rest in the zone) and waited for a tidier one; whether the low holds
    is not known when the zone is reached."""
    h = family_outcome_horizon("FVG")
    n = h + 2
    lows = [99.5] + [100.6] * (n - 1)
    highs = [102.0] + [101.5] * (n - 1)
    closes = [100.4] + [101.0 + 0.1 * i for i in range(n - 1)]
    opens = [101.8, 100.45] + [101.0] * (n - 2)
    ev = _zone_event("FVG", lows=lows, highs=highs, closes=closes, opens=opens)
    assert realized_return(ev, cost_bps=0.0) == pytest.approx((closes[h] - 100.45) / 100.45)


def test_an_orderblock_invalidated_by_the_decision_bars_own_close_is_no_trade() -> None:
    """Bar 0 reaches the zone and CLOSES below it. At that close the order
    block is void, so there is nothing to enter on at the next open."""
    h = family_outcome_horizon("OB")
    n = h + 2
    lows = [99.0] + [99.0] * (n - 1)
    highs = [101.5] + [100.5] * (n - 1)
    closes = [99.5] + [100.2] * (n - 1)
    opens = [101.4] + [99.6] * (n - 1)
    assert realized_return(_zone_event("OB", lows=lows, highs=highs, closes=closes, opens=opens)) is None
    # Same bars as an FVG: one close below is not yet an invalidation there.
    fvg_n = family_outcome_horizon("FVG") + 2
    fvg = _zone_event("FVG", lows=lows[:fvg_n], highs=highs[:fvg_n], closes=closes[:fvg_n], opens=opens[:fvg_n])
    assert realized_return(fvg) is not None


def test_an_fvg_whose_second_breach_is_the_decision_bars_close_is_no_trade() -> None:
    """Bar 0 closes below the zone without reaching it (gap), bar 1 reaches
    the zone and closes below again: two consecutive breaches stand at bar
    1's close."""
    h = family_outcome_horizon("FVG")
    n = h + 3
    lows = [98.0, 99.0] + [100.5] * (n - 2)
    highs = [99.5, 100.6] + [101.5] * (n - 2)
    closes = [99.0, 99.8] + [101.0] * (n - 2)
    opens = [99.4, 99.1] + [100.0] * (n - 2)
    assert realized_return(_zone_event("FVG", lows=lows, highs=highs, closes=closes, opens=opens)) is None
    # Positive control: let bar 1 close back inside the zone and it is a trade.
    closes[1] = 100.3
    assert realized_return(_zone_event("FVG", lows=lows, highs=highs, closes=closes, opens=opens)) is not None


def test_exit_bar_is_the_one_the_previous_rule_used() -> None:
    """The label window (walk-forward purge) keys on the exit index; it must
    stay ``horizon - 1`` for level families and ``decision + horizon`` for
    zones, so the purge guards are unchanged by the entry fix."""
    from governance.family_returns import _realized_return_and_exit

    level = _level_event(level=100.0, opens=[102.0, 102.5, 103.0], closes=[102.5, 103.0, 103.02])
    assert _realized_return_and_exit(level)[1] == family_outcome_horizon("SWEEP") - 1  # type: ignore[index]
    zone = _long_event("OB")
    assert _realized_return_and_exit(zone)[1] == 0 + family_outcome_horizon("OB")  # type: ignore[index]


# ---------------------------------------------------------------------------
# Structure grain (ADR-0031, Nachtrag 2026-10-03 IV)
# ---------------------------------------------------------------------------


def test_the_structure_grain_is_part_of_the_definition() -> None:
    from governance.family_returns import (
        COARSE_EVENT_ID_SUFFIX,
        COARSE_PIVOT_LOOKUP,
        PIVOT_LOOKUP,
        event_pivot_lookup,
        record_grain_events,
    )

    assert PIVOT_LOOKUP == 1
    assert COARSE_PIVOT_LOOKUP == 50  # the Pine engine's default swing size
    assert COARSE_EVENT_ID_SUFFIX == ":p50"
    # An event (or ledger row) without the stamp predates the second grain.
    assert event_pivot_lookup({}) == PIVOT_LOOKUP
    assert event_pivot_lookup({"pivot_lookup": None}) == PIVOT_LOOKUP
    assert event_pivot_lookup({"pivot_lookup": 50}) == 50
    assert event_pivot_lookup({"pivot_lookup": "50"}) == 50
    pool = [{"pivot_lookup": 50, "n": 0}, {"n": 1}, {"pivot_lookup": 1, "n": 2}]
    assert [e["n"] for e in record_grain_events(pool)] == [1, 2]
