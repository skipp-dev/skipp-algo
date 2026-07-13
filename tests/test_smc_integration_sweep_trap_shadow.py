"""WS1 + WS4a: sweep-trap shadow wiring in measurement_evidence.

WS1 derives ``swept_level`` / ``sweep_extreme`` / ``origin_level`` at the single
choke point (sweep event + bars both available) so ``classify_sweep_trap``
executes on real sweeps when ``ENABLE_SWEEP_TRAP=1``.

WS4a logs the trap quality into the SWEEP ScoredEvent ``features`` observe-only.
These MUST NOT change the event outcome / raw_score (confluence reads the coarse
SWEEP_QUALITY_SCORE, not SWEEP_TRAP_QUALITY_SCORE) — they exist so WS4b can
measure a Brier/hit-rate delta before any budget weight.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pandas as pd

from smc_integration.measurement_evidence import (
    _derive_sweep_trap_geometry,
    _evaluate_sweep_event,
)


def _bull_sweep_bars() -> pd.DataFrame:
    """A bullish (SELL_SIDE) sweep of the 100 low: leg up to 105, dip to 98 at
    bar 10, then reclaim back above 100."""
    rows = []
    ts0 = 1_700_000_000
    for i in range(20):
        if i <= 9:
            # pre-sweep leg: drifts around 102-105 (origin high = 105 at bar 5)
            c = 105.0 if i == 5 else 102.0
            hi, lo = c + 0.5, c - 0.5
        elif i == 10:
            # the sweep bar: low pierces 98 (below swept_level 100), closes 99
            c, hi, lo = 99.0, 100.2, 98.0
        else:
            # reclaim: closes back above 100
            c, hi, lo = 101.0, 101.5, 100.2
        rows.append({"timestamp": ts0 + i * 900, "open": c, "high": hi, "low": lo, "close": c})
    return pd.DataFrame(rows)


_SWEEP_TS = 1_700_000_000 + 10 * 900  # timestamp of the sweep bar (index 10)


def _event() -> dict:
    return {"id": "sweep-x", "price": 100.0, "side": "SELL_SIDE", "time": float(_SWEEP_TS)}


class TestDeriveGeometry:
    def test_bullish_geometry(self) -> None:
        bars = _bull_sweep_bars()
        swept, extreme, origin = _derive_sweep_trap_geometry(
            _event(), bars, 10, is_bullish_sweep=True
        )
        assert swept == 100.0
        assert extreme == 98.0          # sweep bar low
        assert origin == 105.5          # max high (wick) in the pre-sweep leg
        assert origin > swept > extreme  # bullish: origin above, extreme below

    def test_producer_value_overrides_derivation(self) -> None:
        bars = _bull_sweep_bars()
        cand = {**_event(), "origin_level": 110.0}
        _, _, origin = _derive_sweep_trap_geometry(cand, bars, 10, is_bullish_sweep=True)
        assert origin == 110.0

    def test_missing_bar_index_falls_back(self) -> None:
        bars = _bull_sweep_bars()
        swept, extreme, origin = _derive_sweep_trap_geometry(_event(), bars, None, is_bullish_sweep=True)
        assert swept == 100.0
        assert extreme == 0.0   # no bar → candidate fallback
        assert origin == 100.0  # falls back to swept_level


def _evaluate(bars: pd.DataFrame, *, flag: str) -> tuple:
    with patch.dict(os.environ, {"ENABLE_SWEEP_TRAP": flag}):
        return _evaluate_sweep_event(
            _event(), bars,
            bias_direction="BULLISH", bias_confidence=0.6,
            event_context={"session": "NY_AM"},
        )


class TestShadowObserve:
    def test_features_populated_when_flag_on(self) -> None:
        result = _evaluate(_bull_sweep_bars(), flag="1")
        assert result is not None
        _, scored = result
        f = scored.features
        assert f["sweep_trap_type"] != "failed"          # corrected classifier → valid trap
        assert f["sweep_trap_reclaim_strength"] > 0.0
        assert f["sweep_trap_fib_retrace"] > 0.0
        assert f["sweep_trap_quality_score"] > 0.0
        # Leakage-free emission: the disjoint late outcome + schema version are logged.
        assert "sweep_trap_outcome_late" in f
        assert isinstance(f["sweep_trap_outcome_late"], bool)
        assert f["sweep_trap_schema_version"] == 1

    def test_trap_confirmation_window_disjoint_from_late_outcome(self) -> None:
        """A reclaim only in the LATE window (bars 4..8) must NOT confirm the trap
        (confirmation is bars 1..3) yet the disjoint late outcome still fires —
        proving the two windows never overlap (no target leakage)."""
        rows = []
        ts0 = 1_700_000_000
        for i in range(20):
            if i <= 9:
                c = 105.0 if i == 5 else 102.0
                hi, lo = c + 0.5, c - 0.5
            elif i == 10:  # the sweep bar
                c, hi, lo = 99.0, 100.2, 98.0
            elif i <= 13:  # confirmation window (bars 1..3 post-sweep): stays BELOW 100
                c, hi, lo = 99.2, 99.8, 98.8
            else:          # late window (bars 4..8 post-sweep): reclaims above 100
                c, hi, lo = 101.0, 101.5, 100.2
            rows.append({"timestamp": ts0 + i * 900, "open": c, "high": hi, "low": lo, "close": c})
        _, scored = _evaluate(pd.DataFrame(rows), flag="1")
        f = scored.features
        assert f["sweep_trap_type"] == "failed"           # no reclaim within bars 1..3
        assert f["sweep_trap_outcome_late"] is True        # but the late window did reverse

    def test_features_empty_when_flag_off(self) -> None:
        result = _evaluate(_bull_sweep_bars(), flag="0")
        assert result is not None
        _, scored = result
        assert scored.features == {}

    def test_outcome_and_score_unchanged_by_flag(self) -> None:
        bars = _bull_sweep_bars()
        _, on = _evaluate(bars, flag="1")
        _, off = _evaluate(bars, flag="0")
        # The observe fields must not perturb the label or the probability.
        assert on.outcome == off.outcome
        assert on.predicted_prob == off.predicted_prob
        assert on.raw_score == off.raw_score


class TestWS1LiquiditySupportWiring:
    def test_liquidity_support_runs_classifier_when_flag_on(self) -> None:
        from smc_integration.measurement_evidence import _liquidity_support_for_event

        bars = _bull_sweep_bars()
        candidate = {**_event(), "id": "cand-1"}  # SELL_SIDE sweep at bar 10
        anchor_ts = float(bars.iloc[15]["timestamp"])
        with patch.dict(os.environ, {"ENABLE_SWEEP_TRAP": "1", "ENABLE_REACTION_ZONE_STUDY": "1"}):
            payload = _liquidity_support_for_event(
                current_event=candidate,
                family="SWEEP",
                sweeps=[candidate],
                bars=bars,
                anchor_idx=15,
                anchor_ts=anchor_ts,
            )
        assert payload["SWEEP_DIRECTION"] == "BULL"
        # WS1: the derived geometry let the corrected classifier produce a real trap.
        assert payload["SWEEP_TRAP_QUALITY_SCORE"] > 0.0
        assert payload["SWEEP_TRAP_TYPE"] != "failed"
        assert "REACTION_BAND_LOW" in payload  # reaction-zone path also runs
        assert "REACTION_LEVEL_RECLAIMED" in payload  # authoritative reclaim signal recorded

    def test_reclaim_on_the_anchor_bar_is_detected(self) -> None:
        # Off-by-one regression: the anchor bar is a COMPLETED bar (its close is the
        # current reference price), so a reclaim landing ON it must be seen now — not
        # one anchor step later. Pre-fix the window ended AT anchor_idx (exclusive),
        # so this sweep classified as "failed" with REACTION_LEVEL_RECLAIMED False.
        from smc_integration.measurement_evidence import _liquidity_support_for_event

        ts0 = 1_700_000_000
        rows = []
        for i in range(14):
            if i == 5:            # pre-sweep leg high (origin)
                c, hi, lo = 105.0, 105.5, 104.5
            elif i <= 9:          # pre-sweep leg above the 100 level
                c, hi, lo = 102.0, 102.5, 101.5
            elif i == 10:         # sweep bar: pierces 98, closes 99 (below swept 100)
                c, hi, lo = 99.0, 100.2, 98.0
            elif i < 13:          # bars 11,12: recover but STAY below 100 (no reclaim, not in band)
                c, hi, lo = 99.0, 99.4, 98.6
            else:                 # bar 13 = the anchor: closes back above 100 (reclaim ON the anchor)
                c, hi, lo = 101.0, 101.5, 100.2
            rows.append({"timestamp": ts0 + i * 900, "open": c, "high": hi, "low": lo, "close": c})
        bars = pd.DataFrame(rows)
        candidate = {"id": "cand-anchor", "price": 100.0, "side": "SELL_SIDE",
                     "time": float(ts0 + 10 * 900)}
        with patch.dict(os.environ, {"ENABLE_SWEEP_TRAP": "1", "ENABLE_REACTION_ZONE_STUDY": "1"}):
            payload = _liquidity_support_for_event(
                current_event=candidate, family="SWEEP", sweeps=[candidate],
                bars=bars, anchor_idx=13, anchor_ts=float(bars.iloc[13]["timestamp"]),
            )
        assert payload["REACTION_LEVEL_RECLAIMED"] is True
        assert payload["REACTION_BARS_TO_RECLAIM"] == 3   # bars 11,12,13 -> reclaim on the 3rd
        assert payload["SWEEP_TRAP_TYPE"] != "failed"
        assert payload["SWEEP_RECLAIM_BARS"] == 3

    def test_liquidity_support_no_trap_fields_when_flag_off(self) -> None:
        from smc_integration.measurement_evidence import _liquidity_support_for_event

        bars = _bull_sweep_bars()
        candidate = {**_event(), "id": "cand-1"}
        with patch.dict(os.environ, {"ENABLE_SWEEP_TRAP": "0"}):
            payload = _liquidity_support_for_event(
                current_event=candidate, family="SWEEP", sweeps=[candidate],
                bars=bars, anchor_idx=15, anchor_ts=float(bars.iloc[15]["timestamp"]),
            )
        assert "SWEEP_TRAP_QUALITY_SCORE" not in payload
        # Flag off → no status field at all (distinguishable from ok/error).
        assert "SWEEP_TRAP_STATUS" not in payload

    def test_reaction_study_runs_without_sweep_trap(self) -> None:
        # F9 fix: the reaction-zone study is independently gated — with ONLY
        # ENABLE_REACTION_ZONE_STUDY on (sweep-trap OFF), the enrichment path must
        # still emit the REACTION_* geometry (it used to be nested inside the
        # sweep-trap block, so the study flag alone was a silent no-op here).
        from smc_integration.measurement_evidence import _liquidity_support_for_event

        bars = _bull_sweep_bars()
        candidate = {**_event(), "id": "cand-1"}
        with patch.dict(os.environ, {"ENABLE_SWEEP_TRAP": "0", "ENABLE_REACTION_ZONE_STUDY": "1"}):
            payload = _liquidity_support_for_event(
                current_event=candidate, family="SWEEP", sweeps=[candidate],
                bars=bars, anchor_idx=15, anchor_ts=float(bars.iloc[15]["timestamp"]),
            )
        # Reaction geometry present on the study flag alone …
        assert "REACTION_BAND_LOW" in payload
        assert "REACTION_LEVEL_RECLAIMED" in payload
        assert payload["REACTION_STATUS"] == "ok"
        # … while the sweep-trap fields stay absent (its flag was off).
        assert "SWEEP_TRAP_TYPE" not in payload
        assert "SWEEP_TRAP_QUALITY_SCORE" not in payload
        assert "SWEEP_TRAP_STATUS" not in payload

    def test_liquidity_support_emits_ok_status_on_success(self) -> None:
        from smc_integration.measurement_evidence import _liquidity_support_for_event

        bars = _bull_sweep_bars()
        candidate = {**_event(), "id": "cand-1"}
        with patch.dict(os.environ, {"ENABLE_SWEEP_TRAP": "1", "ENABLE_REACTION_ZONE_STUDY": "1"}):
            payload = _liquidity_support_for_event(
                current_event=candidate, family="SWEEP", sweeps=[candidate],
                bars=bars, anchor_idx=15, anchor_ts=float(bars.iloc[15]["timestamp"]),
            )
        assert payload["SWEEP_TRAP_STATUS"] == "ok"
        assert payload["REACTION_STATUS"] == "ok"

    def test_liquidity_support_emits_error_status_on_failure(self, caplog) -> None:
        # A failed Phase B/C enrichment must be DISTINGUISHABLE from "flag off" /
        # "no geometry": it emits SWEEP_TRAP_STATUS=="error" + an error code and a
        # WARNING (was a DEBUG-only silent skip that shrank the shadow sample).
        import logging

        from smc_integration import measurement_evidence as me
        from smc_integration.measurement_evidence import _liquidity_support_for_event

        bars = _bull_sweep_bars()
        candidate = {**_event(), "id": "cand-1"}

        def _boom(**_kw):
            raise ValueError("classifier blew up")

        with patch.object(me, "classify_sweep_trap", _boom), \
                patch.dict(os.environ, {"ENABLE_SWEEP_TRAP": "1", "ENABLE_REACTION_ZONE_STUDY": "1"}), \
                caplog.at_level(logging.WARNING):
            payload = _liquidity_support_for_event(
                current_event=candidate, family="SWEEP", sweeps=[candidate],
                bars=bars, anchor_idx=15, anchor_ts=float(bars.iloc[15]["timestamp"]),
            )
        assert payload["SWEEP_TRAP_STATUS"] == "error"
        assert payload["SWEEP_TRAP_ERROR"] == "ValueError"
        assert payload["REACTION_STATUS"] == "error"
        assert "SWEEP_TRAP_QUALITY_SCORE" not in payload
        assert any(r.levelno == logging.WARNING for r in caplog.records)


class TestDeriveGeometryBearishAndFallback:
    def test_bearish_geometry_uses_high_and_min_low_origin(self) -> None:
        bars = _bull_sweep_bars()
        swept, extreme, origin = _derive_sweep_trap_geometry(
            {"price": 100.0, "side": "BUY_SIDE"}, bars, 10, is_bullish_sweep=False
        )
        assert swept == 100.0
        assert extreme == float(bars.iloc[10]["high"])                  # sweep bar high
        assert origin == float(bars.iloc[0:11]["low"].min())            # min low in leg
        assert extreme > swept > origin  # bearish mirror: origin below, extreme above

    def test_nan_leg_origin_falls_back_to_swept_level(self) -> None:
        bars = _bull_sweep_bars().copy()
        bars["high"] = float("nan")  # degenerate: no finite leg extreme
        swept, _extreme, origin = _derive_sweep_trap_geometry(
            {"price": 100.0, "side": "SELL_SIDE"}, bars, 10, is_bullish_sweep=True
        )
        assert origin == swept == 100.0
