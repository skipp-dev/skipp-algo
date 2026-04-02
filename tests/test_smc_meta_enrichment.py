"""Tests for calendar risk, enriched news, and regime bridge integration.

Covers:
  Slice A — EventRisk type + event-risk layering overlay
  Slice B — EnrichedNews type + enriched news heat in normalization
  Slice C — MarketRegimeContext + regime bridge adapter + regime reason codes
"""
from __future__ import annotations

import pytest

from smc_core.types import (
    DirectionalStrength,
    EnrichedNews,
    EventRisk,
    MarketRegimeContext,
    SmcMeta,
    SmcStructure,
    TimedDirectionalStrength,
    TimedEnrichedNews,
    TimedVolumeInfo,
    VolumeInfo,
)
from smc_core.layering import (
    apply_layering,
    derive_base_signals,
    normalize_meta,
)
from smc_adapters.ingest import build_meta_from_raw
from smc_adapters.regime_bridge import regime_snapshot_to_context


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vol(regime: str = "NORMAL", thin: float = 0.1) -> TimedVolumeInfo:
    return TimedVolumeInfo(
        value=VolumeInfo(regime=regime, thin_fraction=thin),  # type: ignore[arg-type]
        asof_ts=1_700_000_000.0,
        stale=False,
    )


def _tech(strength: float = 0.7, bias: str = "BULLISH") -> TimedDirectionalStrength:
    return TimedDirectionalStrength(
        value=DirectionalStrength(strength=strength, bias=bias),  # type: ignore[arg-type]
        asof_ts=1_700_000_000.0,
        stale=False,
    )


def _base_meta(**overrides) -> SmcMeta:
    defaults = dict(
        symbol="AAPL",
        timeframe="15m",
        asof_ts=1_700_000_050.0,
        volume=_vol(),
        technical=_tech(),
    )
    defaults.update(overrides)
    return SmcMeta(**defaults)  # type: ignore[arg-type]


def _minimal_structure() -> SmcStructure:
    from smc_core.types import Orderblock
    return SmcStructure(
        orderblocks=[Orderblock(id="ob:1", low=100.0, high=101.0, dir="BULL", valid=True)],
    )


# ===================================================================
#  SLICE A — Calendar / Event Risk
# ===================================================================

class TestEventRiskType:
    def test_event_risk_fields(self) -> None:
        er = EventRisk(event_type="EARNINGS", severity="HIGH", window_start=100.0, window_end=200.0)
        assert er.event_type == "EARNINGS"
        assert er.severity == "HIGH"
        assert er.window_start == 100.0
        assert er.window_end == 200.0

    def test_event_risk_frozen(self) -> None:
        er = EventRisk(event_type="FOMC", severity="MODERATE", window_start=0.0, window_end=1.0)
        with pytest.raises(AttributeError):
            er.severity = "LOW"  # type: ignore[misc]


class TestEventRiskNormalization:
    def test_no_event_risk_defaults(self) -> None:
        nm = normalize_meta(_base_meta())
        assert nm["event_severity"] is None
        assert nm["event_in_window"] is False

    def test_event_in_window_detected(self) -> None:
        meta = _base_meta(
            event_risk=EventRisk(
                event_type="EARNINGS",
                severity="HIGH",
                window_start=1_700_000_000.0,
                window_end=1_700_000_100.0,
            ),
        )
        nm = normalize_meta(meta)
        assert nm["event_in_window"] is True
        assert nm["event_severity"] == "HIGH"

    def test_event_outside_window(self) -> None:
        meta = _base_meta(
            event_risk=EventRisk(
                event_type="NFP",
                severity="HIGH",
                window_start=1_600_000_000.0,
                window_end=1_600_001_000.0,
            ),
        )
        nm = normalize_meta(meta)
        assert nm["event_in_window"] is False

    def test_high_event_adds_reason_code(self) -> None:
        meta = _base_meta(
            event_risk=EventRisk(
                event_type="FOMC",
                severity="HIGH",
                window_start=1_700_000_000.0,
                window_end=1_700_000_100.0,
            ),
        )
        signals = derive_base_signals(normalize_meta(meta))
        assert "EVENT_RISK_HIGH" in signals["base_reasons"]

    def test_moderate_event_adds_reason_code(self) -> None:
        meta = _base_meta(
            event_risk=EventRisk(
                event_type="OPEX",
                severity="MODERATE",
                window_start=1_700_000_000.0,
                window_end=1_700_000_100.0,
            ),
        )
        signals = derive_base_signals(normalize_meta(meta))
        assert "EVENT_RISK_MODERATE" in signals["base_reasons"]
        assert "EVENT_RISK_HIGH" not in signals["base_reasons"]

    def test_low_event_no_reason_code(self) -> None:
        meta = _base_meta(
            event_risk=EventRisk(
                event_type="OTHER",
                severity="LOW",
                window_start=1_700_000_000.0,
                window_end=1_700_000_100.0,
            ),
        )
        signals = derive_base_signals(normalize_meta(meta))
        assert "EVENT_RISK_HIGH" not in signals["base_reasons"]
        assert "EVENT_RISK_MODERATE" not in signals["base_reasons"]


class TestEventRiskLayeringOverlay:
    def test_high_event_blocks_trades(self) -> None:
        meta = _base_meta(
            event_risk=EventRisk(
                event_type="EARNINGS",
                severity="HIGH",
                window_start=1_700_000_000.0,
                window_end=1_700_000_100.0,
            ),
        )
        snap = apply_layering(_minimal_structure(), meta, generated_at=1_700_000_050.0)
        style = snap.layered.zone_styles["ob:1"]
        assert style.trade_state == "DISCOURAGED"
        assert style.render_state == "DIMMED"
        assert "EVENT_RISK_HIGH" in style.reason_codes

    def test_moderate_event_discourages_trades(self) -> None:
        meta = _base_meta(
            event_risk=EventRisk(
                event_type="CPI",
                severity="MODERATE",
                window_start=1_700_000_000.0,
                window_end=1_700_000_100.0,
            ),
        )
        snap = apply_layering(_minimal_structure(), meta, generated_at=1_700_000_050.0)
        style = snap.layered.zone_styles["ob:1"]
        assert style.trade_state in ("DISCOURAGED", "BLOCKED")
        assert "EVENT_RISK_MODERATE" in style.reason_codes

    def test_no_event_risk_trade_allowed(self) -> None:
        meta = _base_meta()
        snap = apply_layering(_minimal_structure(), meta, generated_at=1_700_000_050.0)
        style = snap.layered.zone_styles["ob:1"]
        assert style.trade_state == "ALLOWED"


# ===================================================================
#  SLICE B — Enriched News
# ===================================================================

class TestEnrichedNewsType:
    def test_enriched_news_fields(self) -> None:
        en = EnrichedNews(strength=0.8, bias="BEARISH", category="MACRO", freshness_minutes=15.0, source="reuters")
        assert en.category == "MACRO"
        assert en.freshness_minutes == 15.0

    def test_enriched_news_frozen(self) -> None:
        en = EnrichedNews(strength=0.5, bias="NEUTRAL", category="OTHER", freshness_minutes=5.0, source="x")
        with pytest.raises(AttributeError):
            en.strength = 0.9  # type: ignore[misc]


class TestEnrichedNewsNormalization:
    def test_no_enriched_news_heat_zero(self) -> None:
        nm = normalize_meta(_base_meta())
        assert nm["enriched_news_heat"] == 0.0

    def test_bearish_enriched_news_negative_heat(self) -> None:
        meta = _base_meta(
            enriched_news=[
                TimedEnrichedNews(
                    value=EnrichedNews(strength=0.9, bias="BEARISH", category="MACRO", freshness_minutes=5.0, source="fmp"),
                    asof_ts=1_700_000_040.0,
                    stale=False,
                ),
            ],
        )
        nm = normalize_meta(meta)
        assert nm["enriched_news_heat"] < 0

    def test_stale_enriched_news_ignored(self) -> None:
        meta = _base_meta(
            enriched_news=[
                TimedEnrichedNews(
                    value=EnrichedNews(strength=0.9, bias="BEARISH", category="SECTOR", freshness_minutes=999.0, source="old"),
                    asof_ts=1_700_000_040.0,
                    stale=True,
                ),
            ],
        )
        nm = normalize_meta(meta)
        assert nm["enriched_news_heat"] == 0.0

    def test_mixed_enriched_news_averages(self) -> None:
        meta = _base_meta(
            enriched_news=[
                TimedEnrichedNews(
                    value=EnrichedNews(strength=0.8, bias="BULLISH", category="COMPANY", freshness_minutes=5.0, source="a"),
                    asof_ts=1_700_000_040.0,
                    stale=False,
                ),
                TimedEnrichedNews(
                    value=EnrichedNews(strength=0.8, bias="BEARISH", category="MACRO", freshness_minutes=5.0, source="b"),
                    asof_ts=1_700_000_040.0,
                    stale=False,
                ),
            ],
        )
        nm = normalize_meta(meta)
        assert abs(nm["enriched_news_heat"]) < 0.05  # opposing cancel out


# ===================================================================
#  SLICE C — Market Regime Context + Bridge Adapter
# ===================================================================

class TestMarketRegimeContextType:
    def test_defaults(self) -> None:
        ctx = MarketRegimeContext(regime="RISK_ON")
        assert ctx.vix_level is None
        assert ctx.sector_breadth == 0.5

    def test_full_init(self) -> None:
        ctx = MarketRegimeContext(regime="RISK_OFF", vix_level=30.5, sector_breadth=0.2)
        assert ctx.regime == "RISK_OFF"
        assert ctx.vix_level == 30.5


class TestRegimeBridgeAdapter:
    def test_none_returns_none(self) -> None:
        assert regime_snapshot_to_context(None) is None

    def test_dict_risk_on(self) -> None:
        ctx = regime_snapshot_to_context({"regime": "RISK_ON", "vix_level": 14.0, "sector_breadth": 0.8})
        assert ctx is not None
        assert ctx.regime == "RISK_ON"
        assert ctx.vix_level == 14.0

    def test_dict_invalid_regime(self) -> None:
        assert regime_snapshot_to_context({"regime": "UNKNOWN_THING"}) is None

    def test_object_form(self) -> None:
        class _Snap:
            regime = "RISK_OFF"
            vix_level = 28.0
            sector_breadth = 0.3
        ctx = regime_snapshot_to_context(_Snap())
        assert ctx is not None
        assert ctx.regime == "RISK_OFF"
        assert ctx.sector_breadth == 0.3

    def test_object_missing_regime(self) -> None:
        class _Snap:
            pass
        assert regime_snapshot_to_context(_Snap()) is None


class TestRegimeReasonCodes:
    def test_risk_on_reason_code(self) -> None:
        meta = _base_meta(market_regime=MarketRegimeContext(regime="RISK_ON"))
        signals = derive_base_signals(normalize_meta(meta))
        assert "REGIME_RISK_ON" in signals["base_reasons"]

    def test_risk_off_reason_code(self) -> None:
        meta = _base_meta(market_regime=MarketRegimeContext(regime="RISK_OFF"))
        signals = derive_base_signals(normalize_meta(meta))
        assert "REGIME_RISK_OFF" in signals["base_reasons"]

    def test_rotation_reason_code(self) -> None:
        meta = _base_meta(market_regime=MarketRegimeContext(regime="ROTATION"))
        signals = derive_base_signals(normalize_meta(meta))
        assert "REGIME_ROTATION" in signals["base_reasons"]

    def test_neutral_regime_no_extra_reason(self) -> None:
        meta = _base_meta(market_regime=MarketRegimeContext(regime="NEUTRAL"))
        signals = derive_base_signals(normalize_meta(meta))
        for r in signals["base_reasons"]:
            assert r not in ("REGIME_RISK_ON", "REGIME_RISK_OFF", "REGIME_ROTATION")

    def test_no_regime_no_extra_reason(self) -> None:
        meta = _base_meta()
        signals = derive_base_signals(normalize_meta(meta))
        for r in signals["base_reasons"]:
            assert r not in ("REGIME_RISK_ON", "REGIME_RISK_OFF", "REGIME_ROTATION")


# ===================================================================
#  Ingest round-trip for new fields
# ===================================================================

class TestIngestNewFields:
    def _raw_meta_base(self) -> dict:
        return {
            "symbol": "AAPL",
            "timeframe": "15m",
            "asof_ts": 1_700_000_050.0,
            "volume": {
                "value": {"regime": "NORMAL", "thin_fraction": 0.1},
                "asof_ts": 1_700_000_050.0,
                "stale": False,
            },
            "provenance": ["test"],
        }

    def test_event_risk_round_trip(self) -> None:
        raw = self._raw_meta_base()
        raw["event_risk"] = {
            "event_type": "EARNINGS",
            "severity": "HIGH",
            "window_start": 1_700_000_000.0,
            "window_end": 1_700_000_100.0,
        }
        meta = build_meta_from_raw(raw)
        assert meta.event_risk is not None
        assert meta.event_risk.event_type == "EARNINGS"
        assert meta.event_risk.severity == "HIGH"

    def test_enriched_news_round_trip(self) -> None:
        raw = self._raw_meta_base()
        raw["enriched_news"] = [
            {
                "value": {
                    "strength": 0.7,
                    "bias": "BEARISH",
                    "category": "MACRO",
                    "freshness_minutes": 10.0,
                    "source": "reuters",
                },
                "asof_ts": 1_700_000_040.0,
                "stale": False,
            },
        ]
        meta = build_meta_from_raw(raw)
        assert len(meta.enriched_news) == 1
        assert meta.enriched_news[0].value.category == "MACRO"

    def test_market_regime_round_trip(self) -> None:
        raw = self._raw_meta_base()
        raw["market_regime"] = {"regime": "RISK_OFF", "vix_level": 30.0, "sector_breadth": 0.25}
        meta = build_meta_from_raw(raw)
        assert meta.market_regime is not None
        assert meta.market_regime.regime == "RISK_OFF"

    def test_missing_new_fields_default_safely(self) -> None:
        raw = self._raw_meta_base()
        meta = build_meta_from_raw(raw)
        assert meta.event_risk is None
        assert meta.enriched_news == []
        assert meta.market_regime is None

    def test_invalid_event_risk_ignored(self) -> None:
        raw = self._raw_meta_base()
        raw["event_risk"] = {"event_type": "INVALID", "severity": "ULTRA"}
        meta = build_meta_from_raw(raw)
        assert meta.event_risk is None

    def test_invalid_enriched_news_ignored(self) -> None:
        raw = self._raw_meta_base()
        raw["enriched_news"] = [{"garbage": True}, "not_a_dict"]
        meta = build_meta_from_raw(raw)
        assert meta.enriched_news == []
