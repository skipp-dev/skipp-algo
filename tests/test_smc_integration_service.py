from __future__ import annotations

import pandas as pd

from smc_integration import service


def test_load_symbol_bars_for_context_normalizes_daily_trade_dates_to_epoch_seconds(monkeypatch) -> None:
    bundle = {
        "frames": {
            "daily_bars": pd.DataFrame(
                [
                    {
                        "symbol": "aapl",
                        "trade_date": "2026-04-10",
                        "open": 100.0,
                        "high": 101.0,
                        "low": 99.5,
                        "close": 100.5,
                        "volume": 1000,
                    },
                    {
                        "symbol": "AAPL",
                        "trade_date": "2026-04-11",
                        "open": 100.5,
                        "high": 102.0,
                        "low": 100.0,
                        "close": 101.0,
                        "volume": 1200,
                    },
                ]
            )
        }
    }

    monkeypatch.setattr(service, "load_export_bundle", lambda *args, **kwargs: bundle)

    bars = service._load_symbol_bars_for_context("AAPL", "1D")

    assert bars["timestamp"].tolist() == [1775779200, 1775865600]
    assert bars["symbol"].tolist() == ["AAPL", "AAPL"]


def test_load_symbol_bars_for_context_normalizes_intraday_timestamps_to_epoch_seconds(monkeypatch) -> None:
    bundle = {
        "frames": {
            "full_universe_second_detail_open": pd.DataFrame(
                [
                    {
                        "symbol": "aapl",
                        "timestamp": "2026-04-10T13:30:05Z",
                        "open": 100.0,
                        "high": 100.2,
                        "low": 99.9,
                        "close": 100.1,
                        "volume": 500,
                    },
                    {
                        "symbol": "AAPL",
                        "timestamp": "2026-04-10T13:30:06Z",
                        "open": 100.1,
                        "high": 100.3,
                        "low": 100.0,
                        "close": 100.2,
                        "volume": 550,
                    },
                ]
            )
        }
    }

    monkeypatch.setattr(service, "load_export_bundle", lambda *args, **kwargs: bundle)

    bars = service._load_symbol_bars_for_context("AAPL", "15m")

    assert bars["timestamp"].tolist() == [1775827805, 1775827806]
    assert bars["symbol"].tolist() == ["AAPL", "AAPL"]


# ── pure helper coverage ─────────────────────────────────────────


class TestSafeFloat:
    def test_valid(self) -> None:
        assert service._safe_float(3.14) == 3.14

    def test_string(self) -> None:
        assert service._safe_float("2.5") == 2.5

    def test_none(self) -> None:
        assert service._safe_float(None) is None

    def test_nan(self) -> None:
        assert service._safe_float(float("nan")) is None

    def test_inf(self) -> None:
        assert service._safe_float(float("inf")) is None

    def test_non_numeric(self) -> None:
        assert service._safe_float("bad") is None


class TestSerializeBiasVerdict:
    def test_serializes(self) -> None:
        from types import SimpleNamespace

        verdict = SimpleNamespace(
            direction="BULLISH",
            confidence=0.8,
            htf_direction="UP",
            session_direction="UP",
            conflict=False,
            source="merged",
        )
        result = service._serialize_bias_verdict(verdict)
        assert result["direction"] == "BULLISH"
        assert result["confidence"] == 0.8
        assert result["conflict"] is False


class TestSerializeVolRegime:
    def test_normal(self) -> None:
        from types import SimpleNamespace

        regime = SimpleNamespace(
            label="NORMAL",
            raw_atr_ratio=1.0,
            confidence=0.9,
            bars_used=100,
            model_source="atr",
            fallback_reason=None,
            forecast_volatility=0.02,
            baseline_volatility=0.02,
            forecast_ratio=1.0,
        )
        result = service._serialize_vol_regime(regime, bars_available=True)
        assert result["label"] == "NORMAL"
        assert result["confidence"] == 0.9

    def test_empty_bars_override(self) -> None:
        from types import SimpleNamespace

        regime = SimpleNamespace(
            label="LOW",
            raw_atr_ratio=0.5,
            confidence=0.3,
            bars_used=0,
            model_source="fallback",
            fallback_reason="empty_bars",
            forecast_volatility=0.0,
            baseline_volatility=0.0,
            forecast_ratio=0.0,
        )
        result = service._serialize_vol_regime(regime, bars_available=False)
        assert result["label"] == "UNKNOWN"
        assert result["confidence"] == 0.0
        assert result["service_override_reason"] == "empty_bars"


class TestContextDiagnosticsForBars:
    def test_empty_bars(self) -> None:
        result = service._context_diagnostics_for_bars(pd.DataFrame())
        assert result["bars_available"] is False
        assert result["reason"] == "empty_bars"

    def test_non_empty_bars(self) -> None:
        df = pd.DataFrame({"a": [1, 2, 3]})
        result = service._context_diagnostics_for_bars(df)
        assert result["bars_available"] is True
        assert result["bar_count"] == 3
        assert "reason" not in result


class TestSerializeScoringFamilyMetrics:
    def test_non_dict_returns_empty(self) -> None:
        from types import SimpleNamespace

        scoring = SimpleNamespace(family_metrics=None)
        assert service._serialize_scoring_family_metrics(scoring) == {}

    def test_dict_serializes(self) -> None:
        from types import SimpleNamespace

        item = SimpleNamespace(n_events=10, brier_score=0.25, log_score=0.5, hit_rate=0.7)
        scoring = SimpleNamespace(family_metrics={"bos": item})
        result = service._serialize_scoring_family_metrics(scoring)
        assert result["bos"]["n_events"] == 10
        assert result["bos"]["brier_score"] == 0.25


class TestStringList:
    def test_valid_list(self) -> None:
        assert service._string_list(["a", "b", ""]) == ["a", "b"]

    def test_non_list(self) -> None:
        assert service._string_list(None) == []

    def test_strips_whitespace(self) -> None:
        assert service._string_list(["  x  ", "  "]) == ["x"]


class TestResolveStructureState:
    def test_none_returns_unknown(self) -> None:
        assert service._resolve_structure_state(None) == "unknown"

    def test_full(self) -> None:
        assert service._resolve_structure_state({"selected_structure_mode": "full"}) == "full"

    def test_partial(self) -> None:
        assert service._resolve_structure_state({"coverage": "partial"}) == "partial"

    def test_ok_maps_to_full(self) -> None:
        assert service._resolve_structure_state({"selected": "ok"}) == "full"

    def test_missing_maps_to_none(self) -> None:
        assert service._resolve_structure_state({"selected_structure_mode": "missing"}) == "none"

    def test_selected_category_coverage_all_true(self) -> None:
        status = {"selected_category_coverage": {"bos": True, "fvg": True}}
        assert service._resolve_structure_state(status) == "full"

    def test_selected_category_coverage_mixed(self) -> None:
        status = {"selected_category_coverage": {"bos": True, "fvg": False}}
        assert service._resolve_structure_state(status) == "partial"

    def test_selected_category_coverage_all_false(self) -> None:
        status = {"selected_category_coverage": {"bos": False, "fvg": False}}
        assert service._resolve_structure_state(status) == "none"

    def test_unrecognized_returns_unknown(self) -> None:
        assert service._resolve_structure_state({"selected_structure_mode": "weird_value"}) == "unknown"


class TestMissingMetaDomains:
    def test_from_diagnostics(self) -> None:
        meta = {"meta_domain_diagnostics": {"volume": "dropped", "technical": "present", "news": "missing"}}
        result = service._missing_meta_domains(meta)
        assert "volume" in result
        assert "news" in result
        assert "technical" not in result


class TestStaleMetaDomains:
    def test_from_diagnostics_stale_flag(self) -> None:
        meta = {"meta_domain_diagnostics": {"volume_stale": True, "technical": "present"}}
        result = service._stale_meta_domains(meta)
        assert "volume" in result

    def test_from_diagnostics_stale_status(self) -> None:
        meta = {"meta_domain_diagnostics": {"news": "stale"}}
        result = service._stale_meta_domains(meta)
        assert "news" in result

    def test_from_volume_dict_stale(self) -> None:
        meta = {"volume": {"stale": True}}
        result = service._stale_meta_domains(meta)
        assert "volume" in result


class TestMeasurementQualityTier:
    def test_from_tier_field(self) -> None:
        assert service._measurement_quality_tier({"ensemble_quality": {"tier": "good"}}) == "good"

    def test_from_score_high(self) -> None:
        assert service._measurement_quality_tier({"ensemble_quality": {"score": 0.8}}) == "high"

    def test_from_score_good(self) -> None:
        assert service._measurement_quality_tier({"ensemble_quality": {"score": 0.6}}) == "good"

    def test_from_score_ok(self) -> None:
        assert service._measurement_quality_tier({"ensemble_quality": {"score": 0.3}}) == "ok"

    def test_from_score_low(self) -> None:
        assert service._measurement_quality_tier({"ensemble_quality": {"score": 0.1}}) == "low"

    def test_no_ensemble_returns_unknown(self) -> None:
        assert service._measurement_quality_tier({}) == "unknown"

    def test_none_score_returns_unknown(self) -> None:
        assert service._measurement_quality_tier({"ensemble_quality": {}}) == "unknown"


class TestMeasurementQualityScore:
    def test_returns_score(self) -> None:
        assert service._measurement_quality_score({"ensemble_quality": {"score": 0.75}}) == 0.75

    def test_no_ensemble_returns_none(self) -> None:
        assert service._measurement_quality_score({}) is None


class TestMeasurementWarningMessages:
    def test_extracts_warnings(self) -> None:
        assert service._measurement_warning_messages({"warnings": ["a", "b"]}) == ["a", "b"]

    def test_no_warnings(self) -> None:
        assert service._measurement_warning_messages({}) == []


class TestLoadSymbolBarsForContextEdgeCases:
    def test_bundle_load_failure_returns_empty(self, monkeypatch) -> None:
        monkeypatch.setattr(service, "load_export_bundle", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
        bars = service._load_symbol_bars_for_context("AAPL", "15m")
        assert bars.empty

    def test_daily_bars_empty_symbol_returns_empty(self, monkeypatch) -> None:
        bundle = {"frames": {"daily_bars": pd.DataFrame({
            "symbol": ["MSFT"],
            "trade_date": ["2026-01-01"],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1000],
        })}}
        monkeypatch.setattr(service, "load_export_bundle", lambda *a, **kw: bundle)
        bars = service._load_symbol_bars_for_context("AAPL", "1D")
        assert bars.empty

    def test_intraday_empty_symbol_returns_empty(self, monkeypatch) -> None:
        bundle = {"frames": {"full_universe_second_detail_open": pd.DataFrame({
            "symbol": ["MSFT"],
            "timestamp": ["2026-01-01T14:30:00Z"],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1000],
        })}}
        monkeypatch.setattr(service, "load_export_bundle", lambda *a, **kw: bundle)
        bars = service._load_symbol_bars_for_context("AAPL", "15m")
        assert bars.empty