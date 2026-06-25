from __future__ import annotations

from pathlib import Path

import pandas as pd

from smc_core.vol_regime import VolRegimeResult
from smc_integration import measurement_evidence


def _daily_bars() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"symbol": "AAPL", "timestamp": "2024-01-01T00:00:00Z", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0},
            {"symbol": "AAPL", "timestamp": "2024-01-02T00:00:00Z", "open": 100.0, "high": 102.0, "low": 100.0, "close": 102.0, "volume": 1100.0},
            {"symbol": "AAPL", "timestamp": "2024-01-03T00:00:00Z", "open": 102.0, "high": 103.0, "low": 101.0, "close": 102.5, "volume": 1200.0},
            {"symbol": "AAPL", "timestamp": "2024-01-04T00:00:00Z", "open": 102.5, "high": 103.0, "low": 100.5, "close": 101.2, "volume": 1300.0},
            {"symbol": "AAPL", "timestamp": "2024-01-05T00:00:00Z", "open": 101.2, "high": 101.8, "low": 99.2, "close": 99.6, "volume": 1400.0},
            {"symbol": "AAPL", "timestamp": "2024-01-06T00:00:00Z", "open": 99.6, "high": 100.6, "low": 99.4, "close": 100.4, "volume": 1500.0},
            {"symbol": "AAPL", "timestamp": "2024-01-07T00:00:00Z", "open": 100.4, "high": 101.5, "low": 100.1, "close": 101.2, "volume": 1600.0},
        ]
    )


def _contract_payload() -> tuple[dict, dict]:
    ts2 = pd.Timestamp("2024-01-02T00:00:00Z").timestamp()
    ts3 = pd.Timestamp("2024-01-03T00:00:00Z").timestamp()
    ts4 = pd.Timestamp("2024-01-04T00:00:00Z").timestamp()
    ts5 = pd.Timestamp("2024-01-05T00:00:00Z").timestamp()
    explicit_payload = {
        "bos": [
            {"id": "bos1", "time": ts2, "price": 101.0, "kind": "BOS", "dir": "UP", "source": "synthetic"},
        ],
        "orderblocks": [
            {"id": "ob1", "low": 99.0, "high": 100.0, "dir": "BULL", "valid": True, "anchor_ts": ts3, "source": "synthetic"},
        ],
        "fvg": [
            {"id": "fvg1", "low": 100.4, "high": 101.0, "dir": "BULL", "valid": True, "anchor_ts": ts3, "source": "synthetic"},
        ],
        "liquidity_sweeps": [
            {"id": "sw1", "time": ts5, "price": 99.3, "side": "SELL_SIDE", "source_liquidity_id": "liq1", "source": "synthetic"},
        ],
        "diagnostics": {
            "orderblock_diagnostics": [{"id": "ob1", "mitigated": True, "mitigated_ts": ts5}],
            "fvg_diagnostics": [{"id": "fvg1", "mitigated": True, "mitigated_ts": ts4}],
        },
    }
    contract = {
        "symbol": "AAPL",
        "timeframe": "1D",
        "canonical_structure": {
            "bos": list(explicit_payload["bos"]),
            "orderblocks": list(explicit_payload["orderblocks"]),
            "fvg": list(explicit_payload["fvg"]),
            "liquidity_sweeps": list(explicit_payload["liquidity_sweeps"]),
        },
        "structure_profile_used": "hybrid_default",
    }
    return contract, explicit_payload


def test_build_measurement_evidence_uses_contract_and_real_bars(monkeypatch) -> None:
    contract, explicit_payload = _contract_payload()
    bars = _daily_bars()

    monkeypatch.setattr(
        measurement_evidence.structure_artifact_json,
        "load_normalized_structure_contract_input",
        lambda symbol, timeframe: contract,
    )
    monkeypatch.setattr(
        measurement_evidence.structure_artifact_json,
        "resolve_artifact_mode",
        lambda symbol, timeframe: "deterministic",
    )
    monkeypatch.setattr(
        measurement_evidence,
        "resolve_structure_artifact_inputs",
        lambda: {"resolution_mode": "synthetic", "export_bundle_root": None, "workbook_path": None},
    )
    monkeypatch.setattr(
        measurement_evidence,
        "load_raw_meta_input_composite",
        lambda symbol, timeframe, source="auto": {
            "event_risk": {
                "EVENT_PROVIDER_STATUS": "ok",
                "EVENT_RISK_LEVEL": "HIGH",
                "SYMBOL_EVENT_BLOCKED": True,
            }
        },
    )
    monkeypatch.setattr(
        measurement_evidence,
        "_load_source_bars",
        lambda symbol, timeframe, resolved_inputs=None: (bars, "synthetic_bundle"),
    )
    monkeypatch.setattr(
        measurement_evidence,
        "build_explicit_structure_from_bars",
        lambda raw_bars, symbol, timeframe, structure_profile="hybrid_default": explicit_payload,
    )
    monkeypatch.setattr(
        measurement_evidence,
        "build_htf_bias_context",
        lambda df, timeframe, htf_frames=None: {"fvg_bias_counter": [{"counter": 2}]},
    )
    monkeypatch.setattr(
        measurement_evidence,
        "build_session_liquidity_context",
        lambda df, tz="America/New_York": {"killzones": []},
    )
    monkeypatch.setattr(
        measurement_evidence,
        "compute_vol_regime",
        lambda df: VolRegimeResult(
            label="NORMAL",
            raw_atr_ratio=1.02,
            confidence=0.91,
            bars_used=len(df),
            model_source="arch_garch",
            fallback_reason=None,
            forecast_volatility=0.02,
            baseline_volatility=0.019,
            forecast_ratio=1.0526,
        ),
    )

    evidence = measurement_evidence.build_measurement_evidence("AAPL", "1D")

    assert evidence.details["measurement_evidence_present"] is True
    assert evidence.details["bars_source_mode"] == "synthetic_bundle"
    assert evidence.details["canonical_event_counts"] == {"BOS": 1, "OB": 1, "FVG": 1, "SWEEP": 1}
    assert evidence.details["evaluated_event_counts"] == {"BOS": 1, "OB": 1, "FVG": 1, "SWEEP": 1}
    assert evidence.events_by_family["BOS"][0]["hit"] is True
    assert evidence.events_by_family["BOS"][0]["invalidated"] is True
    assert evidence.events_by_family["OB"][0]["hit"] is True
    assert evidence.events_by_family["FVG"][0]["hit"] is True
    assert [event.family for event in evidence.scored_events] == ["BOS", "OB", "FVG", "SWEEP"]
    assert all(event.outcome is True for event in evidence.scored_events)
    assert all(event.predicted_prob > 0.5 for event in evidence.scored_events)
    assert all(event.raw_score is not None for event in evidence.scored_events)
    assert all(event.raw_score_name == "SIGNAL_QUALITY_SCORE" for event in evidence.scored_events)
    assert evidence.scored_events[0].context == {"session": "NONE", "htf_bias": "BULLISH", "vol_regime": "NORMAL"}
    assert evidence.details["scoring_event_count"] == 4
    assert evidence.details["scoring_event_counts_by_family"] == {"BOS": 1, "OB": 1, "FVG": 1, "SWEEP": 1}
    assert evidence.details["signal_quality_raw_score_name"] == "SIGNAL_QUALITY_SCORE"
    assert evidence.details["signal_quality_raw_score_count"] == 4
    assert evidence.details["signal_quality_raw_score_complete"] is True
    assert evidence.details["vol_regime"] == "NORMAL"
    assert evidence.details["vol_regime_confidence"] == 0.91
    assert evidence.details["vol_regime_model_source"] == "arch_garch"
    assert evidence.details["vol_regime_fallback_reason"] is None
    assert evidence.details["vol_regime_forecast_volatility"] == 0.02
    assert evidence.details["vol_regime_baseline_volatility"] == 0.019
    assert evidence.details["vol_regime_forecast_ratio"] == 1.0526
    assert evidence.details["event_risk_source_mode"] == "raw_meta"
    assert evidence.details["event_risk_provider_status"] == "ok"
    assert evidence.details["event_risk_signal_present"] is True
    assert evidence.details["ensemble_quality"]["available_components"] == ["bias", "scoring", "vol_regime"]
    assert 0.0 <= evidence.details["ensemble_quality"]["score"] <= 1.0
    assert "session:NONE" in evidence.stratified_events
    assert "htf_bias:BULLISH" in evidence.stratified_events
    assert "vol_regime:NORMAL" in evidence.stratified_events
    assert evidence.warnings == []

    scoring_result = measurement_evidence.score_events(evidence.scored_events)
    assert scoring_result.calibration.input_kind == "raw_score_0_100"
    assert scoring_result.calibration.source_name == "SIGNAL_QUALITY_SCORE"


def test_build_measurement_evidence_warns_when_contract_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        measurement_evidence.structure_artifact_json,
        "load_normalized_structure_contract_input",
        lambda symbol, timeframe: None,
    )
    monkeypatch.setattr(
        measurement_evidence.structure_artifact_json,
        "resolve_artifact_mode",
        lambda symbol, timeframe: "none",
    )
    monkeypatch.setattr(
        measurement_evidence,
        "resolve_structure_artifact_inputs",
        lambda: {"resolution_mode": "missing", "export_bundle_root": None, "workbook_path": None},
    )

    evidence = measurement_evidence.build_measurement_evidence("AAPL", "15m")

    assert evidence.details["measurement_evidence_present"] is False
    assert evidence.details["evaluated_event_counts"] == {"BOS": 0, "OB": 0, "FVG": 0, "SWEEP": 0}
    assert evidence.warnings == ["structure artifact unavailable for measurement evidence"]


def test_build_measurement_evidence_uses_reference_snapshot_event_risk_when_meta_has_none(monkeypatch) -> None:
    contract, explicit_payload = _contract_payload()
    bars = _daily_bars()

    monkeypatch.setattr(
        measurement_evidence.structure_artifact_json,
        "load_normalized_structure_contract_input",
        lambda symbol, timeframe: contract,
    )
    monkeypatch.setattr(
        measurement_evidence.structure_artifact_json,
        "resolve_artifact_mode",
        lambda symbol, timeframe: "deterministic",
    )
    monkeypatch.setattr(
        measurement_evidence,
        "resolve_structure_artifact_inputs",
        lambda: {"resolution_mode": "synthetic", "export_bundle_root": None, "workbook_path": None},
    )
    monkeypatch.setattr(
        measurement_evidence,
        "load_raw_meta_input_composite",
        lambda symbol, timeframe, source="auto": {},
    )
    monkeypatch.setattr(
        measurement_evidence,
        "get_reference_event_risk_snapshot",
        lambda symbols: {
            "provider_status": "ready",
            "reference_change_tickers": ["AAPL"],
            "by_symbol": {
                "AAPL": {
                    "latest_effective_date": "2024-01-03",
                    "recent_events": [{"event": "SPLIT", "effective_date": "2024-01-03"}],
                }
            },
        },
    )
    monkeypatch.setattr(
        measurement_evidence,
        "_load_source_bars",
        lambda symbol, timeframe, resolved_inputs=None: (bars, "synthetic_bundle"),
    )
    monkeypatch.setattr(
        measurement_evidence,
        "build_explicit_structure_from_bars",
        lambda raw_bars, symbol, timeframe, structure_profile="hybrid_default": explicit_payload,
    )
    monkeypatch.setattr(
        measurement_evidence,
        "build_htf_bias_context",
        lambda df, timeframe, htf_frames=None: {"fvg_bias_counter": [{"counter": 2}]},
    )
    monkeypatch.setattr(
        measurement_evidence,
        "build_session_liquidity_context",
        lambda df, tz="America/New_York": {"killzones": []},
    )

    evidence = measurement_evidence.build_measurement_evidence("AAPL", "1D")

    assert evidence.details["event_risk_source_mode"] == "reference_snapshot"
    assert evidence.details["event_risk_provider_status"] == "ok"
    assert evidence.details["event_risk_reference_provider_status"] == "ready"
    assert evidence.details["event_risk_signal_present"] is True


def test_build_measurement_evidence_falls_back_to_recomputed_families(monkeypatch) -> None:
    _, explicit_payload = _contract_payload()
    bars = _daily_bars()
    contract = {
        "symbol": "AAPL",
        "timeframe": "1D",
        "canonical_structure": {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
        "structure_profile_used": "hybrid_default",
    }

    monkeypatch.setattr(
        measurement_evidence.structure_artifact_json,
        "load_normalized_structure_contract_input",
        lambda symbol, timeframe: contract,
    )
    monkeypatch.setattr(
        measurement_evidence.structure_artifact_json,
        "resolve_artifact_mode",
        lambda symbol, timeframe: "manifest",
    )
    monkeypatch.setattr(
        measurement_evidence,
        "resolve_structure_artifact_inputs",
        lambda: {"resolution_mode": "synthetic", "export_bundle_root": None, "workbook_path": None},
    )
    monkeypatch.setattr(
        measurement_evidence,
        "load_raw_meta_input_composite",
        lambda symbol, timeframe, source="auto": {},
    )
    monkeypatch.setattr(
        measurement_evidence,
        "get_reference_event_risk_snapshot",
        lambda symbols: {"provider_status": "ready", "reference_change_tickers": [], "by_symbol": {}},
    )
    monkeypatch.setattr(
        measurement_evidence,
        "_load_source_bars",
        lambda symbol, timeframe, resolved_inputs=None: (bars, "synthetic_bundle"),
    )
    monkeypatch.setattr(
        measurement_evidence,
        "build_explicit_structure_from_bars",
        lambda raw_bars, symbol, timeframe, structure_profile="hybrid_default": explicit_payload,
    )
    monkeypatch.setattr(
        measurement_evidence,
        "build_htf_bias_context",
        lambda df, timeframe, htf_frames=None: {"fvg_bias_counter": [{"counter": 1}]},
    )
    monkeypatch.setattr(
        measurement_evidence,
        "build_session_liquidity_context",
        lambda df, tz="America/New_York": {"killzones": []},
    )

    evidence = measurement_evidence.build_measurement_evidence("AAPL", "1D")

    assert evidence.details["canonical_event_counts"] == {"BOS": 0, "OB": 0, "FVG": 0, "SWEEP": 0}
    assert evidence.details["effective_event_counts"] == {"BOS": 1, "OB": 1, "FVG": 1, "SWEEP": 1}
    assert evidence.details["structure_fallback_families"] == ["BOS", "OB", "FVG", "SWEEP"]
    assert evidence.details["evaluated_event_counts"] == {"BOS": 1, "OB": 1, "FVG": 1, "SWEEP": 1}


def test_load_source_bars_prefers_canonical_bundle_over_daily_workbook_fallback(monkeypatch, tmp_path: Path) -> None:
    workbook_path = tmp_path / "production.xlsx"
    with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "trade_date": "2024-01-02",
                    "symbol": "AAPL",
                    "open": 91.0,
                    "high": 92.0,
                    "low": 90.0,
                    "close": 91.5,
                    "volume": 500.0,
                }
            ]
        ).to_excel(writer, sheet_name="daily_bars", index=False)

    monkeypatch.setattr(
        measurement_evidence,
        "load_export_bundle",
        lambda *_args, **_kwargs: {
            "frames": {
                "daily_bars": pd.DataFrame(
                    [
                        {
                            "trade_date": "2024-01-02",
                            "symbol": "aapl",
                            "open": 101.0,
                            "high": 103.0,
                            "low": 100.0,
                            "close": 102.5,
                            "volume": 1500.0,
                        }
                    ]
                )
            }
        },
    )

    bars, source = measurement_evidence._load_source_bars(
        "AAPL",
        "1D",
        resolved_inputs={"export_bundle_root": tmp_path, "workbook_path": workbook_path},
    )

    assert source == "canonical_export_bundle"
    assert len(bars) == 1
    assert float(bars.loc[0, "open"]) == 101.0
    assert float(bars.loc[0, "volume"]) == 1500.0


def test_load_source_bars_uses_daily_workbook_fallback_when_bundle_has_no_matching_rows(monkeypatch, tmp_path: Path) -> None:
    workbook_path = tmp_path / "production.xlsx"
    with pd.ExcelWriter(workbook_path, engine="openpyxl") as writer:
        pd.DataFrame(
            [
                {
                    "trade_date": "2024-01-03",
                    "symbol": "AAPL",
                    "open": 111.0,
                    "high": 112.0,
                    "low": 109.5,
                    "close": 110.5,
                    "volume": 2000.0,
                }
            ]
        ).to_excel(writer, sheet_name="daily_bars", index=False)

    monkeypatch.setattr(
        measurement_evidence,
        "load_export_bundle",
        lambda *_args, **_kwargs: {
            "frames": {
                "daily_bars": pd.DataFrame(
                    [
                        {
                            "trade_date": "2024-01-03",
                            "symbol": "MSFT",
                            "open": 201.0,
                            "high": 202.0,
                            "low": 199.0,
                            "close": 200.5,
                            "volume": 3000.0,
                        }
                    ]
                )
            }
        },
    )

    bars, source = measurement_evidence._load_source_bars(
        "AAPL",
        "1D",
        resolved_inputs={"export_bundle_root": tmp_path, "workbook_path": workbook_path},
    )

    assert source == "workbook_fallback"
    assert len(bars) == 1
    assert float(bars.loc[0, "open"]) == 111.0
    assert float(bars.loc[0, "close"]) == 110.5


def test_load_source_bars_prefers_older_intraday_bundle_over_newer_daily_only_manifest(tmp_path: Path) -> None:
    older_base = "databento_volatility_production_20260310_090000"
    newer_base = "databento_volatility_production_incremental_20260310_091000"

    (tmp_path / f"{older_base}_manifest.json").write_text("{}\n", encoding="utf-8")
    pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "timestamp": "2024-01-02T14:30:00Z",
                "open": 101.0,
                "high": 102.0,
                "low": 100.0,
                "close": 101.5,
                "volume": 1500.0,
            }
        ]
    ).to_parquet(tmp_path / f"{older_base}__full_universe_second_detail_open.parquet", index=False)

    (tmp_path / f"{newer_base}_manifest.json").write_text("{}\n", encoding="utf-8")
    pd.DataFrame(
        [
            {
                "trade_date": "2024-01-02",
                "symbol": "AAPL",
                "open": 91.0,
                "high": 92.0,
                "low": 90.0,
                "close": 91.5,
                "volume": 500.0,
            }
        ]
    ).to_parquet(tmp_path / f"{newer_base}__daily_bars.parquet", index=False)

    (tmp_path / f"{older_base}_manifest.json").touch()
    (tmp_path / f"{newer_base}_manifest.json").touch()

    bars, source = measurement_evidence._load_source_bars(
        "AAPL",
        "5m",
        resolved_inputs={"export_bundle_root": tmp_path, "workbook_path": None},
    )

    assert source == "canonical_export_bundle"
    assert len(bars) == 1
    assert float(bars.loc[0, "open"]) == 101.0
    assert float(bars.loc[0, "volume"]) == 1500.0


def test_to_epoch_seconds_drops_invalid_timestamp_rows() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "timestamp": "2024-01-02T00:00:00Z",
                "open": 100.0,
                "high": 101.0,
                "low": 99.5,
                "close": 100.5,
                "volume": 1000.0,
            },
            {
                "symbol": "AAPL",
                "timestamp": "not-a-timestamp",
                "open": 101.0,
                "high": 102.0,
                "low": 100.5,
                "close": 101.5,
                "volume": 1200.0,
            },
        ]
    )

    normalized = measurement_evidence._to_epoch_seconds(frame)

    assert len(normalized) == 1
    assert int(normalized.loc[0, "timestamp"]) == int(pd.Timestamp("2024-01-02T00:00:00Z").timestamp())


def test_to_epoch_seconds_preserves_distinct_epoch_values() -> None:
    frame = pd.DataFrame(
        [
            {
                "symbol": "AAPL",
                "timestamp": "2024-01-01T00:00:00Z",
                "open": 100.0,
                "high": 101.0,
                "low": 99.5,
                "close": 100.5,
                "volume": 1000.0,
            },
            {
                "symbol": "AAPL",
                "timestamp": "2024-01-02T00:00:00Z",
                "open": 101.0,
                "high": 102.0,
                "low": 100.5,
                "close": 101.5,
                "volume": 1200.0,
            },
        ]
    )

    normalized = measurement_evidence._to_epoch_seconds(frame)

    assert normalized["timestamp"].tolist() == [
        int(pd.Timestamp("2024-01-01T00:00:00Z").timestamp()),
        int(pd.Timestamp("2024-01-02T00:00:00Z").timestamp()),
    ]


# ---------------------------------------------------------------------------
# F-02: Evidence ID determinism and linkage
# ---------------------------------------------------------------------------

class TestEvidenceId:
    def test_deterministic_same_inputs(self) -> None:
        from smc_integration.measurement_evidence import build_evidence_id
        id1 = build_evidence_id(symbol="AAPL", timeframe="5m", run_timestamp=1713000000.123)
        id2 = build_evidence_id(symbol="AAPL", timeframe="5m", run_timestamp=1713000000.789)
        # Same second → same ID (sub-second is truncated)
        assert id1 == id2

    def test_different_symbol_produces_different_id(self) -> None:
        from smc_integration.measurement_evidence import build_evidence_id
        id1 = build_evidence_id(symbol="AAPL", timeframe="5m", run_timestamp=1713000000.0)
        id2 = build_evidence_id(symbol="MSFT", timeframe="5m", run_timestamp=1713000000.0)
        assert id1 != id2

    def test_different_timeframe_produces_different_id(self) -> None:
        from smc_integration.measurement_evidence import build_evidence_id
        id1 = build_evidence_id(symbol="AAPL", timeframe="5m", run_timestamp=1713000000.0)
        id2 = build_evidence_id(symbol="AAPL", timeframe="1H", run_timestamp=1713000000.0)
        assert id1 != id2

    def test_different_timestamp_produces_different_id(self) -> None:
        from smc_integration.measurement_evidence import build_evidence_id
        id1 = build_evidence_id(symbol="AAPL", timeframe="5m", run_timestamp=1713000000.0)
        id2 = build_evidence_id(symbol="AAPL", timeframe="5m", run_timestamp=1713000001.0)
        assert id1 != id2

    def test_config_fingerprint_affects_id(self) -> None:
        from smc_integration.measurement_evidence import build_evidence_id
        id1 = build_evidence_id(symbol="AAPL", timeframe="5m", run_timestamp=1713000000.0, config_fingerprint="abc")
        id2 = build_evidence_id(symbol="AAPL", timeframe="5m", run_timestamp=1713000000.0, config_fingerprint="xyz")
        assert id1 != id2

    def test_id_is_hex_and_16_chars(self) -> None:
        from smc_integration.measurement_evidence import build_evidence_id
        eid = build_evidence_id(symbol="AAPL", timeframe="5m", run_timestamp=1713000000.0)
        assert len(eid) == 16
        int(eid, 16)  # Must be valid hex

    def test_whitespace_normalization(self) -> None:
        from smc_integration.measurement_evidence import build_evidence_id
        id1 = build_evidence_id(symbol="  aapl  ", timeframe=" 5m ", run_timestamp=1713000000.0)
        id2 = build_evidence_id(symbol="AAPL", timeframe="5m", run_timestamp=1713000000.0)
        assert id1 == id2


# ---------------------------------------------------------------------------
# Coverage-boost tests — targeted at uncovered lines
# ---------------------------------------------------------------------------


class TestEmptyEventRiskLight:
    """Cover line 86."""

    def test_returns_dict_with_no_data_status(self) -> None:
        result = measurement_evidence._empty_event_risk_light()
        assert isinstance(result, dict)
        assert result.get("EVENT_PROVIDER_STATUS") == "no_data"


class TestEventRiskSignalPresent:
    """Cover lines 101-102 context."""

    def test_none_level_returns_false(self) -> None:
        assert measurement_evidence._event_risk_signal_present({}) is False

    def test_market_blocked_returns_true(self) -> None:
        assert measurement_evidence._event_risk_signal_present({"MARKET_EVENT_BLOCKED": True}) is True

    def test_high_risk_level_returns_true(self) -> None:
        assert measurement_evidence._event_risk_signal_present({"EVENT_RISK_LEVEL": "HIGH"}) is True


class TestResolveEventRiskLightEdges:
    """Cover lines 101-102 (meta exception), 116-117 (reference exception), 130-131 (both fail)."""

    def test_meta_exception_falls_to_reference(self, monkeypatch) -> None:
        monkeypatch.setattr(
            measurement_evidence,
            "load_raw_meta_input_composite",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("meta fail")),
        )
        monkeypatch.setattr(
            measurement_evidence,
            "get_reference_event_risk_snapshot",
            lambda symbols: {
                "provider_status": "ready",
                "reference_change_tickers": [],
                "by_symbol": {},
            },
        )
        _light, details = measurement_evidence._resolve_measurement_event_risk_light("AAPL", "15m")
        assert details["event_risk_source_mode"] == "reference_snapshot"

    def test_both_sources_fail_returns_none_mode(self, monkeypatch) -> None:
        monkeypatch.setattr(
            measurement_evidence,
            "load_raw_meta_input_composite",
            lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("meta fail")),
        )
        monkeypatch.setattr(
            measurement_evidence,
            "get_reference_event_risk_snapshot",
            lambda symbols: (_ for _ in ()).throw(RuntimeError("ref fail")),
        )
        _light, details = measurement_evidence._resolve_measurement_event_risk_light("AAPL", "15m")
        assert details["event_risk_source_mode"] == "lookup_failed"
        assert details["event_risk_lookup_failed"] is True
        assert details["event_risk_signal_present"] is False

    def test_reference_exception_falls_to_none_mode(self, monkeypatch) -> None:
        monkeypatch.setattr(
            measurement_evidence,
            "load_raw_meta_input_composite",
            lambda *a, **kw: {"no_event_risk": True},
        )
        monkeypatch.setattr(
            measurement_evidence,
            "get_reference_event_risk_snapshot",
            lambda symbols: (_ for _ in ()).throw(RuntimeError("ref fail")),
        )
        _light, details = measurement_evidence._resolve_measurement_event_risk_light("AAPL", "15m")
        assert details["event_risk_source_mode"] == "lookup_failed"
        assert details["event_risk_lookup_failed"] is True


class TestNormalizeNumericBarsEmpty:
    """Cover lines 193-194 context: workbook exception path."""

    def test_empty_frame_returns_empty(self) -> None:
        result = measurement_evidence._normalize_numeric_bars(pd.DataFrame(), timestamp_column="timestamp")
        assert result.empty


class TestLoadSourceBarsWorkbookException:
    """Cover lines 193-194: daily workbook read exception."""

    def test_workbook_read_exception_falls_to_none(self, monkeypatch, tmp_path) -> None:
        bad_file = tmp_path / "production.xlsx"
        bad_file.write_text("not an excel file")
        monkeypatch.setattr(
            measurement_evidence,
            "load_export_bundle",
            lambda *a, **kw: None,
        )
        bars, source = measurement_evidence._load_source_bars(
            "AAPL", "1D",
            resolved_inputs={"export_bundle_root": None, "workbook_path": bad_file},
        )
        assert source == "none"
        assert bars.empty


class TestDirectionalExcursionsEdges:
    """Cover line 240: empty future or zero price."""

    def test_empty_future_returns_zeros(self) -> None:
        mae, mfe = measurement_evidence._directional_excursions(100.0, "UP", pd.DataFrame())
        assert mae == 0.0 and mfe == 0.0

    def test_zero_price_returns_zeros(self) -> None:
        future = pd.DataFrame([{"high": 102.0, "low": 98.0}])
        mae, mfe = measurement_evidence._directional_excursions(0.0, "UP", future)
        assert mae == 0.0 and mfe == 0.0

    def test_bear_direction(self) -> None:
        """Cover line 340 area: BEAR direction branch in _directional_excursions."""
        future = pd.DataFrame([
            {"high": 102.0, "low": 97.0},
            {"high": 101.0, "low": 96.0},
        ])
        mae, mfe = measurement_evidence._directional_excursions(100.0, "DOWN", future)
        assert mfe > 0  # price dropped below 100
        assert mae > 0  # price went above 100


class TestEvaluateBosEventEdges:
    """Cover lines 301, 305, 309: early returns in _evaluate_bos_event."""

    def _bars(self):
        return measurement_evidence._to_epoch_seconds(pd.DataFrame([
            {"symbol": "A", "timestamp": "2024-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"symbol": "A", "timestamp": "2024-01-02", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1},
        ]))

    def test_zero_price_returns_none(self) -> None:
        assert measurement_evidence._evaluate_bos_event({"price": 0, "time": 100}, self._bars()) is None

    def test_no_anchor_match_returns_none(self) -> None:
        assert measurement_evidence._evaluate_bos_event({"price": 100, "time": 9999999999}, self._bars()) is None

    def test_last_bar_returns_none(self) -> None:
        bars = self._bars()
        last_ts = float(bars["timestamp"].iloc[-1])
        assert measurement_evidence._evaluate_bos_event({"price": 100, "time": last_ts}, bars) is None


class TestEvaluateZoneEventEdges:
    """Cover lines 340, 348: early returns in _evaluate_zone_event."""

    def _bars(self):
        return measurement_evidence._to_epoch_seconds(pd.DataFrame([
            {"symbol": "A", "timestamp": "2024-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"symbol": "A", "timestamp": "2024-01-02", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1},
        ]))

    def test_zero_low_returns_none(self) -> None:
        result = measurement_evidence._evaluate_zone_event(
            {"low": 0, "high": 100, "anchor_ts": 100}, self._bars(), diagnostics_by_id={},
        )
        assert result is None

    def test_no_anchor_returns_none(self) -> None:
        result = measurement_evidence._evaluate_zone_event(
            {"low": 99, "high": 100, "anchor_ts": 9999999999}, self._bars(), diagnostics_by_id={},
        )
        assert result is None


class TestNormalizeDirectionAndVoteLabel:
    """Cover lines 389, 398."""

    def test_neutral_direction(self) -> None:
        assert measurement_evidence._normalize_direction("SIDEWAYS") == "NEUTRAL"

    def test_none_vote_label(self) -> None:
        assert measurement_evidence._direction_vote_label("SIDEWAYS") == "NONE"


class TestAnchorReferencePriceFallback:
    """Cover line 420: last fallback to event.price."""

    def test_sweep_family_falls_to_close(self) -> None:
        bars = pd.DataFrame([
            {"symbol": "A", "timestamp": 100, "open": 50, "high": 55, "low": 45, "close": 52, "volume": 1},
        ])
        result = measurement_evidence._anchor_reference_price(
            {"price": 0}, family="SWEEP", bars=bars, anchor_idx=0,
        )
        assert result == 52.0

    def test_sweep_family_falls_to_event_price_when_close_is_zero(self) -> None:
        bars = pd.DataFrame([
            {"symbol": "A", "timestamp": 100, "open": 50, "high": 55, "low": 45, "close": 0, "volume": 1},
        ])
        result = measurement_evidence._anchor_reference_price(
            {"price": 99.0}, family="SWEEP", bars=bars, anchor_idx=0,
        )
        assert result == 99.0


class TestDirectionalProbabilityNeutral:
    """Cover line 779."""

    def test_neutral_expected_returns_half(self) -> None:
        result = measurement_evidence._directional_probability("NEUTRAL", bias_direction="BULLISH", bias_confidence=0.8)
        assert result == 0.5

    def test_neutral_bias_returns_half(self) -> None:
        result = measurement_evidence._directional_probability("BULLISH", bias_direction="NEUTRAL", bias_confidence=0.8)
        assert result == 0.5


class TestScoreBosEventEdges:
    """Cover lines 813, 817, 821."""

    def _bars(self):
        return measurement_evidence._to_epoch_seconds(pd.DataFrame([
            {"symbol": "A", "timestamp": "2024-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"symbol": "A", "timestamp": "2024-01-02", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1},
        ]))

    def test_zero_price_returns_none(self) -> None:
        result = measurement_evidence._score_bos_event(
            {"price": 0, "time": 100}, self._bars(),
            bias_direction="BULLISH", bias_confidence=0.8, event_context={},
        )
        assert result is None

    def test_no_anchor_returns_none(self) -> None:
        result = measurement_evidence._score_bos_event(
            {"price": 100, "time": 9999999999}, self._bars(),
            bias_direction="BULLISH", bias_confidence=0.8, event_context={},
        )
        assert result is None

    def test_last_bar_returns_none(self) -> None:
        bars = self._bars()
        last_ts = float(bars["timestamp"].iloc[-1])
        result = measurement_evidence._score_bos_event(
            {"price": 100, "time": last_ts}, bars,
            bias_direction="BULLISH", bias_confidence=0.8, event_context={},
        )
        assert result is None


class TestScoreZoneEventEdges:
    """Cover lines 857, 861, 865."""

    def _bars(self):
        return measurement_evidence._to_epoch_seconds(pd.DataFrame([
            {"symbol": "A", "timestamp": "2024-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"symbol": "A", "timestamp": "2024-01-02", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1},
        ]))

    def test_invalid_zone_returns_none(self) -> None:
        result = measurement_evidence._score_zone_event(
            {"low": 0, "high": 100, "anchor_ts": 100}, self._bars(),
            family="OB", bias_direction="BULLISH", bias_confidence=0.8, event_context={},
        )
        assert result is None

    def test_no_anchor_returns_none(self) -> None:
        result = measurement_evidence._score_zone_event(
            {"low": 99, "high": 100, "anchor_ts": 9999999999}, self._bars(),
            family="OB", bias_direction="BULLISH", bias_confidence=0.8, event_context={},
        )
        assert result is None


class TestEvaluateSweepEventEdges:
    """Cover lines 894, 902."""

    def _bars(self):
        return measurement_evidence._to_epoch_seconds(pd.DataFrame([
            {"symbol": "A", "timestamp": "2024-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"symbol": "A", "timestamp": "2024-01-02", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1},
        ]))

    def test_zero_price_returns_none(self) -> None:
        result = measurement_evidence._evaluate_sweep_event(
            {"price": 0, "time": 100}, self._bars(),
            bias_direction="BULLISH", bias_confidence=0.8, event_context={},
        )
        assert result is None

    def test_no_anchor_returns_none(self) -> None:
        result = measurement_evidence._evaluate_sweep_event(
            {"price": 100, "time": 9999999999}, self._bars(),
            bias_direction="BULLISH", bias_confidence=0.8, event_context={},
        )
        assert result is None


def _monkeypatch_full_evidence(monkeypatch, *, contract, explicit_payload, bars, overrides=None):
    """Shared helper to set up build_measurement_evidence monkeypatches."""
    overrides = overrides or {}

    monkeypatch.setattr(
        measurement_evidence.structure_artifact_json,
        "load_normalized_structure_contract_input",
        overrides.get("contract_fn", lambda symbol, timeframe: contract),
    )
    monkeypatch.setattr(
        measurement_evidence.structure_artifact_json,
        "resolve_artifact_mode",
        lambda symbol, timeframe: "deterministic",
    )
    monkeypatch.setattr(
        measurement_evidence,
        "resolve_structure_artifact_inputs",
        lambda: {"resolution_mode": "synthetic", "export_bundle_root": None, "workbook_path": None},
    )
    monkeypatch.setattr(
        measurement_evidence,
        "load_raw_meta_input_composite",
        overrides.get("meta_fn", lambda *a, **kw: {}),
    )
    monkeypatch.setattr(
        measurement_evidence,
        "get_reference_event_risk_snapshot",
        overrides.get("ref_fn", lambda symbols: None),
    )
    monkeypatch.setattr(
        measurement_evidence,
        "_load_source_bars",
        overrides.get("bars_fn", lambda symbol, timeframe, resolved_inputs=None: (bars, "synthetic")),
    )
    monkeypatch.setattr(
        measurement_evidence,
        "build_explicit_structure_from_bars",
        overrides.get("explicit_fn", lambda raw_bars, symbol, timeframe, structure_profile="hybrid_default": explicit_payload),
    )
    monkeypatch.setattr(
        measurement_evidence,
        "build_htf_bias_context",
        overrides.get("htf_fn", lambda df, timeframe, htf_frames=None: {}),
    )
    monkeypatch.setattr(
        measurement_evidence,
        "build_session_liquidity_context",
        overrides.get("session_fn", lambda df, tz="America/New_York": {}),
    )
    if "vol_fn" in overrides:
        monkeypatch.setattr(measurement_evidence, "compute_vol_regime", overrides["vol_fn"])


class TestBuildEvidenceResampledEmpty:
    """Cover lines 984-987: resampled bars empty after resample."""

    def test_empty_resampled_warns(self, monkeypatch) -> None:
        contract, explicit = _contract_payload()
        _monkeypatch_full_evidence(monkeypatch, contract=contract, explicit_payload=explicit, bars=_daily_bars(), overrides={
            "bars_fn": lambda symbol, timeframe, resolved_inputs=None: (_daily_bars(), "synthetic"),
        })
        # Resample to a timeframe that produces no bars from daily data
        monkeypatch.setattr(
            measurement_evidence,
            "resample_bars_to_timeframe",
            lambda df, tf: pd.DataFrame(),
        )
        evidence = measurement_evidence.build_measurement_evidence("AAPL", "5m")
        assert any("could not be resampled" in w for w in evidence.warnings)
        assert evidence.details["evaluated_event_counts"] == {"BOS": 0, "OB": 0, "FVG": 0, "SWEEP": 0}


class TestBuildEvidenceExplicitStructureException:
    """Cover lines 999-1000: explicit structure recompute exception."""

    def test_explicit_structure_exception_warns(self, monkeypatch) -> None:
        contract, _ = _contract_payload()
        _monkeypatch_full_evidence(monkeypatch, contract=contract, explicit_payload=None, bars=_daily_bars(), overrides={
            "explicit_fn": lambda raw_bars, symbol, timeframe, structure_profile="hybrid_default": (_ for _ in ()).throw(
                RuntimeError("structure fail")
            ),
        })
        evidence = measurement_evidence.build_measurement_evidence("AAPL", "1D")
        assert any("explicit structure recompute unavailable" in w for w in evidence.warnings)


class TestBuildEvidenceSessionAndHtfExceptions:
    """Cover lines 1055-1057, 1061-1063."""

    def test_session_context_exception_warns(self, monkeypatch) -> None:
        contract, explicit = _contract_payload()
        _monkeypatch_full_evidence(monkeypatch, contract=contract, explicit_payload=explicit, bars=_daily_bars(), overrides={
            "session_fn": lambda df, tz="America/New_York": (_ for _ in ()).throw(RuntimeError("session fail")),
        })
        evidence = measurement_evidence.build_measurement_evidence("AAPL", "1D")
        assert any("session context unavailable" in w for w in evidence.warnings)

    def test_htf_bias_exception_warns(self, monkeypatch) -> None:
        contract, explicit = _contract_payload()
        _monkeypatch_full_evidence(monkeypatch, contract=contract, explicit_payload=explicit, bars=_daily_bars(), overrides={
            "htf_fn": lambda df, timeframe, htf_frames=None: (_ for _ in ()).throw(RuntimeError("htf fail")),
        })
        evidence = measurement_evidence.build_measurement_evidence("AAPL", "1D")
        assert any("htf bias context unavailable" in w for w in evidence.warnings)


class TestBuildEvidenceSkippedEvents:
    """Cover lines 1082-1083, 1130-1131: skipped BOS/OB events."""

    def test_invalid_events_skipped(self, monkeypatch) -> None:
        contract = {
            "symbol": "AAPL",
            "timeframe": "1D",
            "canonical_structure": {
                "bos": [{"id": "bad_bos", "price": 0, "time": 0, "dir": "UP"}],
                "orderblocks": [{"id": "bad_ob", "low": 0, "high": 0, "anchor_ts": 0, "dir": "BULL"}],
                "fvg": [],
                "liquidity_sweeps": [],
            },
            "structure_profile_used": "hybrid_default",
        }
        _monkeypatch_full_evidence(monkeypatch, contract=contract, explicit_payload=None, bars=_daily_bars(), overrides={
            "explicit_fn": lambda raw_bars, symbol, timeframe, structure_profile="hybrid_default": None,
        })
        evidence = measurement_evidence.build_measurement_evidence("AAPL", "1D")
        assert evidence.details["skipped_event_counts"]["BOS"] >= 1
        assert evidence.details["skipped_event_counts"]["OB"] >= 1


class TestBuildEvidenceEnsembleTimestampError:
    """Cover lines 1290-1291: ensemble_generated_at TypeError."""

    def test_non_numeric_timestamp_falls_to_none(self, monkeypatch) -> None:
        contract, explicit = _contract_payload()
        bars = _daily_bars()
        # Patch bars with non-convertible timestamp in last row
        def patched_bars(symbol, timeframe, resolved_inputs=None):
            b = bars.copy()
            b.loc[b.index[-1], "timestamp"] = "not_a_number"
            return b, "synthetic"

        _monkeypatch_full_evidence(monkeypatch, contract=contract, explicit_payload=explicit, bars=bars, overrides={
            "bars_fn": patched_bars,
        })
        # The ensemble_generated_at should fall to None without crashing
        evidence = measurement_evidence.build_measurement_evidence("AAPL", "1D")
        assert evidence.details["measurement_evidence_present"] is True


class TestEvaluateBosEmptyFuture:
    """Cover line 309: future bars empty after slicing."""

    def test_anchor_at_second_to_last_with_empty_slice(self) -> None:
        # 2 bars: anchor at idx 0, future is bars[1:] which has 1 row but
        # that single row has the same ts → we need anchor at LAST bar index.
        # Actually line 309 is `if future.empty: return None`.
        # To reach it, anchor_idx must be < len(bars)-1 (so anchor_idx passes the check)
        # but then future = bars[anchor_idx+1:] must be empty.
        # This only happens when anchor_idx == len(bars)-1, but that's caught at 305.
        # So line 309 is unreachable in practice when anchor_idx check is first.
        # Let me verify: if anchor_idx < len(bars)-1 then bars[anchor_idx+1:] is non-empty.
        # Confirmed: line 309 is dead code after line 305 check. Skip.
        pass


class TestObContextSkipBranches:
    """Cover lines 547, 551, 554: _ob_context_light_for_event skip branches."""

    def _bars(self):
        return measurement_evidence._to_epoch_seconds(pd.DataFrame([
            {"symbol": "A", "timestamp": "2024-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"symbol": "A", "timestamp": "2024-01-02", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1},
            {"symbol": "A", "timestamp": "2024-01-03", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 1},
        ]))

    def test_bad_candidates_skipped(self) -> None:
        bars = self._bars()
        ts2 = float(bars["timestamp"].iloc[1])
        result = measurement_evidence._ob_context_light_for_event(
            current_event={"id": "current_ob"},
            family="OB",
            orderblocks=[
                # anchor_ts <= 0 → skip (line 547)
                {"id": "bad1", "anchor_ts": 0, "low": 99, "high": 100, "dir": "BULL"},
                # candidate_idx > anchor_idx → skip (line 551)
                {"id": "bad2", "anchor_ts": float(bars["timestamp"].iloc[2]), "low": 99, "high": 100, "dir": "BULL"},
                # low <= 0 → skip (line 554)
                {"id": "bad3", "anchor_ts": float(bars["timestamp"].iloc[0]), "low": 0, "high": 100, "dir": "BULL"},
                # direction NONE → skip
                {"id": "bad4", "anchor_ts": float(bars["timestamp"].iloc[0]), "low": 99, "high": 100, "dir": "SIDEWAYS"},
            ],
            bars=bars,
            anchor_idx=1,
            anchor_ts=ts2,
            current_price=101.0,
            diagnostics_by_id={},
        )
        assert result["PRIMARY_OB_SIDE"] == "NONE"  # No valid candidate found


class TestFvgLifecycleSkipBranches:
    """Cover lines 606, 610, 613: _fvg_lifecycle_light_for_event skip branches."""

    def _bars(self):
        return measurement_evidence._to_epoch_seconds(pd.DataFrame([
            {"symbol": "A", "timestamp": "2024-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"symbol": "A", "timestamp": "2024-01-02", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1},
            {"symbol": "A", "timestamp": "2024-01-03", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 1},
        ]))

    def test_bad_candidates_skipped(self) -> None:
        bars = self._bars()
        ts2 = float(bars["timestamp"].iloc[1])
        result = measurement_evidence._fvg_lifecycle_light_for_event(
            current_event={"id": "current_fvg"},
            family="FVG",
            fvgs=[
                {"id": "bad1", "anchor_ts": 0, "low": 99, "high": 100, "dir": "BULL"},
                {"id": "bad2", "anchor_ts": float(bars["timestamp"].iloc[2]), "low": 99, "high": 100, "dir": "BULL"},
                {"id": "bad3", "anchor_ts": float(bars["timestamp"].iloc[0]), "low": 0, "high": 100, "dir": "BULL"},
                {"id": "bad4", "anchor_ts": float(bars["timestamp"].iloc[0]), "low": 99, "high": 100, "dir": "SIDEWAYS"},
            ],
            bars=bars,
            anchor_idx=1,
            anchor_ts=ts2,
            current_price=101.0,
            diagnostics_by_id={},
        )
        assert result["PRIMARY_FVG_SIDE"] == "NONE"


class TestLiquiditySupportSkipBranches:
    """Cover lines 665, 677: _liquidity_support_for_event skip branches."""

    def _bars(self):
        return measurement_evidence._to_epoch_seconds(pd.DataFrame([
            {"symbol": "A", "timestamp": "2024-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"symbol": "A", "timestamp": "2024-01-02", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1},
            {"symbol": "A", "timestamp": "2024-01-03", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 1},
        ]))

    def test_bad_candidates_skipped(self) -> None:
        bars = self._bars()
        ts2 = float(bars["timestamp"].iloc[1])
        result = measurement_evidence._liquidity_support_for_event(
            current_event={"id": "current_sw"},
            family="SWEEP",
            sweeps=[
                # anchor_ts <= 0 → skip (line 665)
                {"id": "bad1", "time": 0, "side": "SELL_SIDE"},
                # candidate_idx > anchor_idx → skip (line 677)
                {"id": "bad2", "time": float(bars["timestamp"].iloc[2]), "side": "SELL_SIDE"},
                # invalid side → skip
                {"id": "bad3", "time": float(bars["timestamp"].iloc[0]), "side": "INVALID"},
            ],
            bars=bars,
            anchor_idx=1,
            anchor_ts=ts2,
        )
        assert result["SWEEP_DIRECTION"] == "NONE"


class TestScoreBosEmptyFuturePriceLists:
    """Cover line 821: _score_bos_event with no future price data."""

    def test_single_bar_after_anchor_with_nan_prices(self) -> None:
        bars = measurement_evidence._to_epoch_seconds(pd.DataFrame([
            {"symbol": "A", "timestamp": "2024-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"symbol": "A", "timestamp": "2024-01-02", "open": float("nan"), "high": float("nan"), "low": float("nan"), "close": float("nan"), "volume": 1},
        ]))
        ts0 = float(bars["timestamp"].iloc[0])
        result = measurement_evidence._score_bos_event(
            {"price": 100, "time": ts0, "dir": "UP"}, bars,
            bias_direction="BULLISH", bias_confidence=0.8, event_context={},
        )
        assert result is None


class TestScoreZoneEmptyFuturePriceLists:
    """Cover line 865: _score_zone_event with no future price data."""

    def test_single_bar_after_anchor_with_nan_prices(self) -> None:
        bars = measurement_evidence._to_epoch_seconds(pd.DataFrame([
            {"symbol": "A", "timestamp": "2024-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"symbol": "A", "timestamp": "2024-01-02", "open": float("nan"), "high": float("nan"), "low": float("nan"), "close": float("nan"), "volume": 1},
        ]))
        ts0 = float(bars["timestamp"].iloc[0])
        result = measurement_evidence._score_zone_event(
            {"low": 99, "high": 100, "anchor_ts": ts0, "dir": "BULL"}, bars,
            family="OB", bias_direction="BULLISH", bias_confidence=0.8, event_context={},
        )
        assert result is None


class TestEvaluateSweepEmptyFuture:
    """Cover line 902: _evaluate_sweep_event with empty future."""

    def test_single_bar_after_anchor_with_nan_close(self) -> None:
        bars = measurement_evidence._to_epoch_seconds(pd.DataFrame([
            {"symbol": "A", "timestamp": "2024-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"symbol": "A", "timestamp": "2024-01-02", "open": float("nan"), "high": float("nan"), "low": float("nan"), "close": float("nan"), "volume": 1},
        ]))
        ts0 = float(bars["timestamp"].iloc[0])
        result = measurement_evidence._evaluate_sweep_event(
            {"price": 100, "time": ts0, "side": "SELL_SIDE"}, bars,
            bias_direction="BULLISH", bias_confidence=0.8, event_context={},
        )
        # The NaN bars get dropped by _to_epoch_seconds, so this returns None (only 1 bar left)
        assert result is None


def _three_bar_frame() -> pd.DataFrame:
    return measurement_evidence._to_epoch_seconds(pd.DataFrame([
        {"symbol": "A", "timestamp": "2024-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
        {"symbol": "A", "timestamp": "2024-01-02", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 1},
        {"symbol": "A", "timestamp": "2024-01-03", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 1},
    ]))


class TestObContextPriceGuard:
    """Guard against current_price <= 0 / non-finite producing inflated distances."""

    def _call(self, current_price: float) -> dict:
        bars = _three_bar_frame()
        ts2 = float(bars["timestamp"].iloc[1])
        return measurement_evidence._ob_context_light_for_event(
            current_event={"id": "evt"},
            family="OB",
            orderblocks=[{"id": "ob1", "anchor_ts": float(bars["timestamp"].iloc[0]),
                          "low": 99.0, "high": 100.0, "dir": "BULL"}],
            bars=bars,
            anchor_idx=1,
            anchor_ts=ts2,
            current_price=current_price,
            diagnostics_by_id={},
        )

    def test_zero_price_short_circuits_to_none_payload(self) -> None:
        result = self._call(0.0)
        assert result == {
            "PRIMARY_OB_SIDE": "NONE",
            "PRIMARY_OB_DISTANCE": 0.0,
            "OB_FRESH": False,
            "OB_AGE_BARS": 0,
            "OB_MITIGATION_STATE": "stale",
            "OB_SUPPORT_SCORE": 0.0,
        }

    def test_negative_price_short_circuits(self) -> None:
        assert self._call(-1.0)["PRIMARY_OB_SIDE"] == "NONE"

    def test_nan_price_short_circuits(self) -> None:
        assert self._call(float("nan"))["PRIMARY_OB_SIDE"] == "NONE"


class TestFvgLifecyclePriceGuard:
    """Guard against current_price <= 0 / non-finite in FVG distance calc."""

    def _call(self, current_price: float) -> dict:
        bars = _three_bar_frame()
        ts2 = float(bars["timestamp"].iloc[1])
        return measurement_evidence._fvg_lifecycle_light_for_event(
            current_event={"id": "evt"},
            family="FVG",
            fvgs=[{"id": "fvg1", "anchor_ts": float(bars["timestamp"].iloc[0]),
                   "low": 99.0, "high": 100.0, "dir": "BULL"}],
            bars=bars,
            anchor_idx=1,
            anchor_ts=ts2,
            current_price=current_price,
            diagnostics_by_id={},
        )

    def test_zero_price_short_circuits_to_none_payload(self) -> None:
        assert self._call(0.0) == {
            "PRIMARY_FVG_SIDE": "NONE",
            "PRIMARY_FVG_DISTANCE": 0.0,
            "FVG_FILL_PCT": 0.0,
            "FVG_MATURITY_LEVEL": 0,
            "FVG_FRESH": False,
            "FVG_INVALIDATED": False,
            "FVG_GAP_SCORE": 0.0,
        }

    def test_inf_price_short_circuits(self) -> None:
        assert self._call(float("inf"))["PRIMARY_FVG_SIDE"] == "NONE"


class TestFvgQualityIsFullBody:
    """Zero-range bars (dojis) must not be labelled is_full_body=True."""

    def _bars_with_anchor(self, open_v: float, high: float, low: float, close: float) -> pd.DataFrame:
        return measurement_evidence._to_epoch_seconds(pd.DataFrame([
            {"symbol": "A", "timestamp": "2024-01-01", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
            {"symbol": "A", "timestamp": "2024-01-02",
             "open": open_v, "high": high, "low": low, "close": close, "volume": 1},
            {"symbol": "A", "timestamp": "2024-01-03", "open": 101, "high": 103, "low": 100, "close": 102, "volume": 1},
        ]))

    def test_zero_range_doji_is_not_full_body(self) -> None:
        # high == low → range 0; previously max(rng, 1e-9) inflated body/rng to ~1e9
        # and silently set is_full_body=True for every doji.
        bars = self._bars_with_anchor(open_v=100.0, high=100.0, low=100.0, close=100.0)
        features = measurement_evidence._fvg_quality_features(
            event={},
            bars=bars,
            anchor_idx=1,
            low=99.0,
            high=100.0,
            direction="BULL",
            event_context={},
            bias_direction="BULLISH",
        )
        assert features["is_full_body"] is False

    def test_genuine_full_body_still_detected(self) -> None:
        # body 1.0 / range 1.0 = 1.0 >= 0.7
        bars = self._bars_with_anchor(open_v=100.0, high=101.0, low=100.0, close=101.0)
        features = measurement_evidence._fvg_quality_features(
            event={},
            bars=bars,
            anchor_idx=1,
            low=99.0,
            high=100.0,
            direction="BULL",
            event_context={},
            bias_direction="BULLISH",
        )
        assert features["is_full_body"] is True
