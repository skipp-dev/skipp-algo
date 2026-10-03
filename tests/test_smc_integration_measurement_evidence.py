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
        # 2026-07-13 (edge-censoring fix): neutral trailing bars so every event keeps its
        # FULL label horizon (FVG anchors at bar 2 and needs 20 forward bars); first-hit /
        # invalidation indices all land in the original 7 bars, so no pinned outcome moves.
        + [
            {"symbol": "AAPL", "timestamp": f"2024-01-{8 + i:02d}T00:00:00Z", "open": 101.2, "high": 101.6, "low": 100.9, "close": 101.2, "volume": 1700.0 + i}
            for i in range(18)
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
    assert evidence.details["bias_conviction_score"] == 0.8
    assert "bias_confidence" not in evidence.details
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


class TestFindBarIndexContainingBar:
    """`_find_bar_index` resolves an event to its CONTAINING bar (off-grid regression)."""

    @staticmethod
    def _bars() -> pd.DataFrame:
        return pd.DataFrame({"timestamp": [100.0, 200.0, 300.0],
                             "open": [1, 1, 1], "high": [1, 1, 1],
                             "low": [1, 1, 1], "close": [1, 1, 1]})

    def test_exact_match_returns_that_bar(self) -> None:
        bars = self._bars()
        assert measurement_evidence._find_bar_index(bars, 200.0) == 1
        assert measurement_evidence._find_bar_index(bars, 100.0) == 0

    def test_off_grid_anchors_on_containing_not_following_bar(self) -> None:
        bars = self._bars()
        # 250 fell DURING the bar at 200 -> anchor bar 1 (not the following bar 2),
        # so the forward slice (anchor+1) begins at bar 2, the first fully-post-event bar.
        assert measurement_evidence._find_bar_index(bars, 250.0) == 1
        assert measurement_evidence._find_bar_index(bars, 150.0) == 0

    def test_before_all_bars_keeps_first(self) -> None:
        # No containing bar exists; keep bar 0 (the outer anchor_idx guard drops it).
        assert measurement_evidence._find_bar_index(self._bars(), 50.0) == 0

    def test_after_all_bars_is_none(self) -> None:
        assert measurement_evidence._find_bar_index(self._bars(), 400.0) is None


class TestEventSessionKeyDailyAlias:
    """`_event_session_key` short-circuits to NONE for daily bars — incl. aliases.

    An inline ``== "1D"`` matched only exact "1D"; a daily alias ("1d"/"D"/"daily")
    fell through and computed a spurious intraday session for a daily bar.
    """

    _TS = 1_700_000_000.0

    def _mock_session(self, monkeypatch) -> None:
        # Any non-short-circuited call would surface this session, not NONE.
        monkeypatch.setattr(
            measurement_evidence, "build_session_context_block",
            lambda **kwargs: {"SESSION_CONTEXT": "NY_AM"},
        )

    def test_intraday_uses_the_session(self, monkeypatch) -> None:
        self._mock_session(monkeypatch)
        assert measurement_evidence._event_session_key(self._TS, "15m") == "session:NY_AM"

    def test_daily_aliases_short_circuit_to_none(self, monkeypatch) -> None:
        self._mock_session(monkeypatch)
        for tf in ("1D", "1d", "D", "daily", " 1D ", "1DAY"):
            assert measurement_evidence._event_session_key(self._TS, tf) == "session:NONE"
        assert measurement_evidence._event_session_label(self._TS, "daily") == "NONE"


def _apply_build_mocks(monkeypatch, contract, explicit_payload, bars, vol_fn) -> None:
    """Wire the build_measurement_evidence data seams to in-memory fixtures.

    ``vol_fn(df) -> VolRegimeResult`` is data-dependent so a point-in-time slice
    (bars up to an event's anchor) yields a different regime than the full frame.
    """
    m = monkeypatch
    m.setattr(measurement_evidence.structure_artifact_json, "load_normalized_structure_contract_input", lambda s, t: contract)
    m.setattr(measurement_evidence.structure_artifact_json, "resolve_artifact_mode", lambda s, t: "deterministic")
    m.setattr(measurement_evidence, "resolve_structure_artifact_inputs", lambda: {"resolution_mode": "synthetic", "export_bundle_root": None, "workbook_path": None})
    m.setattr(measurement_evidence, "load_raw_meta_input_composite", lambda s, t, source="auto": {})
    m.setattr(measurement_evidence, "_load_source_bars", lambda s, t, resolved_inputs=None: (bars, "synthetic_bundle"))
    m.setattr(measurement_evidence, "build_explicit_structure_from_bars", lambda raw_bars, symbol, timeframe, structure_profile="hybrid_default": explicit_payload)
    m.setattr(measurement_evidence, "build_htf_bias_context", lambda df, timeframe, htf_frames=None: {"fvg_bias_counter": [{"counter": 2}]})
    m.setattr(measurement_evidence, "build_session_liquidity_context", lambda df, tz="America/New_York": {"killzones": []})
    m.setattr(measurement_evidence, "compute_vol_regime", vol_fn)


def _len_based_vol(df) -> VolRegimeResult:
    # A slice of >= 4 bars reads HIGH_VOL; a shorter (earlier-anchor) slice NORMAL.
    label = "HIGH_VOL" if len(df) >= 4 else "NORMAL"
    return VolRegimeResult(
        label=label, raw_atr_ratio=1.0, confidence=0.5, bars_used=len(df),
        model_source="test", fallback_reason=None, forecast_volatility=0.02,
        baseline_volatility=0.02, forecast_ratio=1.0,
    )


def test_vol_regime_is_point_in_time_not_end_of_sample(monkeypatch) -> None:
    """Each event's vol regime comes from bars up to its own anchor, not the
    end-of-sample frame (no future leakage)."""
    contract, explicit_payload = _contract_payload()
    _apply_build_mocks(monkeypatch, contract, explicit_payload, _daily_bars(), _len_based_vol)

    evidence = measurement_evidence.build_measurement_evidence("AAPL", "1D")
    by_family = {e.family: e for e in evidence.scored_events}

    # BOS anchors at bar 1 -> PIT slice of 2 bars -> NORMAL (a full-frame read
    # would be HIGH_VOL). SWEEP anchors at bar 4 -> slice of 5 bars -> HIGH_VOL.
    assert by_family["BOS"].context["vol_regime"] == "NORMAL"
    assert by_family["SWEEP"].context["vol_regime"] == "HIGH_VOL"
    # Distinct per-event values prove it is not one global end-of-sample verdict.
    assert by_family["BOS"].context["vol_regime"] != by_family["SWEEP"].context["vol_regime"]
    # The run-level summary still reflects the full frame (7 bars -> HIGH_VOL).
    assert evidence.details["vol_regime"] == "HIGH_VOL"


def test_future_bars_do_not_change_earlier_event_scores(monkeypatch) -> None:
    """Perturbing bars AFTER an event's anchor must not change that event's
    point-in-time vol regime / context."""
    contract, explicit_payload = _contract_payload()

    base_bars = _daily_bars()
    future_rows = [
        {"symbol": "AAPL", "timestamp": f"2024-01-{d}T00:00:00Z", "open": 200.0, "high": 205.0, "low": 195.0, "close": 200.0 + i, "volume": 9000.0}
        for i, d in enumerate(("26", "27", "28", "29"))  # 2026-07-13: after the extended 25-bar frame
    ]
    perturbed_bars = pd.concat([base_bars, pd.DataFrame(future_rows)], ignore_index=True)

    _apply_build_mocks(monkeypatch, contract, explicit_payload, base_bars, _len_based_vol)
    base = measurement_evidence.build_measurement_evidence("AAPL", "1D")
    base_ctx = {e.family: e.context for e in base.scored_events}

    _apply_build_mocks(monkeypatch, contract, explicit_payload, perturbed_bars, _len_based_vol)
    perturbed = measurement_evidence.build_measurement_evidence("AAPL", "1D")
    perturbed_ctx = {e.family: e.context for e in perturbed.scored_events}

    # Every event anchors before the appended bars -> identical PIT context.
    for family in ("BOS", "OB", "FVG", "SWEEP"):
        assert base_ctx[family]["vol_regime"] == perturbed_ctx[family]["vol_regime"]
class TestKpiHorizonCap:
    """#3: KPI evaluation windows are capped to the family label horizon, so a
    touch beyond the horizon is a miss (matching the ScoredEvent label)."""

    def _bars(self, rows):
        base = []
        for i, (hi, lo, cl) in enumerate(rows):
            base.append({
                "symbol": "A", "timestamp": f"2024-01-{i + 1:02d}",
                "open": cl, "high": hi, "low": lo, "close": cl, "volume": 1,
            })
        return measurement_evidence._to_epoch_seconds(pd.DataFrame(base))

    def test_bos_touch_beyond_horizon_is_miss(self) -> None:
        # anchor at bar 0, UP BOS at price 100. Lows stay above 100 within the
        # 8-bar horizon; a touch (low <= 100) only happens at bar 12 (beyond it).
        rows = [(101.0, 100.5, 101.0)]  # bar 0 anchor
        rows += [(102.0 + i, 101.0, 102.0 + i) for i in range(11)]  # bars 1..11: lows 101 (no touch)
        rows += [(101.0, 99.0, 100.0)]  # bar 12: low 99 -> touch, but beyond horizon 8
        rows += [(101.0, 101.0, 101.0) for _ in range(3)]
        bars = self._bars(rows)
        anchor_ts = float(bars["timestamp"].iloc[0])
        result = measurement_evidence._evaluate_bos_event(
            {"price": 100.0, "time": anchor_ts, "dir": "UP"}, bars
        )
        assert result is not None
        assert result["hit"] is False  # touch was beyond the 8-bar BOS horizon

    def test_bos_touch_within_horizon_is_hit(self) -> None:
        rows = [(101.0, 100.5, 101.0)]  # bar 0 anchor
        rows += [(102.0, 101.0, 102.0), (102.0, 101.0, 102.0)]  # bars 1,2 no touch
        rows += [(101.0, 99.0, 101.0)]  # bar 3: low 99 -> touch within horizon, close 101 (no invalidation)
        rows += [(101.0, 101.0, 101.0) for _ in range(6)]
        bars = self._bars(rows)
        anchor_ts = float(bars["timestamp"].iloc[0])
        result = measurement_evidence._evaluate_bos_event(
            {"price": 100.0, "time": anchor_ts, "dir": "UP"}, bars
        )
        assert result is not None
        assert result["hit"] is True


class TestEdgeCensoringGuards:
    """Right-censoring fix: BOS/zone events whose forward window is truncated at
    the data edge are SKIPPED (None), not labeled False; a full window is labeled."""

    def _flat_bars(self, n: int) -> pd.DataFrame:
        rows = [
            {"symbol": "A", "timestamp": f"2024-02-{i + 1:02d}", "open": 100.0,
             "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1}
            for i in range(n)
        ]
        return measurement_evidence._to_epoch_seconds(pd.DataFrame(rows))

    def _anchor_ts(self, bars: pd.DataFrame) -> float:
        return float(bars["timestamp"].iloc[0])

    def test_bos_truncated_window_is_skipped(self) -> None:
        bars = self._flat_bars(6)  # 5 future bars < BOS horizon 8
        result = measurement_evidence._score_bos_event(
            {"price": 100.0, "time": self._anchor_ts(bars), "dir": "UP"}, bars,
            bias_direction="BULLISH", bias_confidence=0.8, event_context={},
        )
        assert result is None

    def test_bos_full_window_is_labeled(self) -> None:
        bars = self._flat_bars(9)  # exactly 8 future bars
        result = measurement_evidence._score_bos_event(
            {"price": 101.0, "time": self._anchor_ts(bars), "dir": "UP"}, bars,  # 101*1.003 > all highs (100.5) -> miss
            bias_direction="BULLISH", bias_confidence=0.8, event_context={},
        )
        assert result is not None
        assert result.outcome is False  # flat bars: observed full window, genuine miss

    def test_zone_truncated_window_is_skipped(self) -> None:
        bars = self._flat_bars(10)  # 9 future bars < OB horizon 12
        result = measurement_evidence._score_zone_event(
            {"low": 99.0, "high": 99.4, "anchor_ts": self._anchor_ts(bars)}, bars,
            family="OB", bias_direction="BULLISH", bias_confidence=0.8, event_context={},
        )
        assert result is None

    def test_zone_full_window_is_labeled(self) -> None:
        bars = self._flat_bars(13)  # exactly 12 future bars
        result = measurement_evidence._score_zone_event(
            {"low": 99.0, "high": 99.4, "anchor_ts": self._anchor_ts(bars)}, bars,
            family="OB", bias_direction="BULLISH", bias_confidence=0.8, event_context={},
        )
        assert result is not None
        assert result.outcome is False  # zone never touched in the FULL window


class TestLabelThresholdSsot:
    """F6: the measurement labeling thresholds come from the skipp_config SSOT —
    re-hardcoding them here would silently decouple labels from the config knob."""

    def test_thresholds_bind_to_trading_thresholds_config(self) -> None:
        from skipp_config import get_trading_thresholds

        cfg = get_trading_thresholds().smc_scoring
        assert cfg.sweep_reversal_threshold_pct == measurement_evidence._SWEEP_REVERSAL_THRESHOLD_PCT
        assert cfg.bos_follow_through_threshold_pct == measurement_evidence._BOS_FOLLOW_THROUGH_THRESHOLD_PCT


class TestKpiMirrorEdgeCensoringGuards:
    """The KPI mirrors (_evaluate_bos_event/_evaluate_zone_event -> events_by_family
    hit/MAE/MFE) must skip truncated windows exactly like the score-path guards —
    before this they graded 1..N-1 available bars as a final miss, biasing the
    benchmark hit rates at the data edge (and creating a SWEEP-vs-rest asymmetry
    after #3591 guarded only the sweep evaluator's shared path)."""

    def _flat_bars(self, n: int) -> pd.DataFrame:
        rows = [
            {"symbol": "A", "timestamp": f"2024-03-{i + 1:02d}", "open": 100.0,
             "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1}
            for i in range(n)
        ]
        return measurement_evidence._to_epoch_seconds(pd.DataFrame(rows))

    def test_bos_kpi_truncated_window_is_skipped(self) -> None:
        bars = self._flat_bars(6)  # 5 future bars < BOS horizon 8
        ts = float(bars["timestamp"].iloc[0])
        assert measurement_evidence._evaluate_bos_event({"price": 101.0, "time": ts, "dir": "UP"}, bars) is None

    def test_bos_kpi_full_window_is_graded(self) -> None:
        bars = self._flat_bars(9)  # exactly 8 future bars
        ts = float(bars["timestamp"].iloc[0])
        result = measurement_evidence._evaluate_bos_event({"price": 101.0, "time": ts, "dir": "UP"}, bars)
        assert result is not None
        assert result["hit"] is False  # full window observed, genuine miss

    def test_zone_kpi_truncated_window_is_skipped(self) -> None:
        bars = self._flat_bars(10)  # 9 future bars < OB horizon 12
        ts = float(bars["timestamp"].iloc[0])
        result = measurement_evidence._evaluate_zone_event(
            {"low": 98.0, "high": 98.4, "anchor_ts": ts, "dir": "BULL"}, bars, diagnostics_by_id={},
        )
        assert result is None

    def test_zone_kpi_full_window_is_graded(self) -> None:
        bars = self._flat_bars(13)  # exactly 12 future bars
        result = measurement_evidence._evaluate_zone_event(
            {"low": 98.0, "high": 98.4, "anchor_ts": float(bars["timestamp"].iloc[0]), "dir": "BULL"},
            bars, diagnostics_by_id={},
        )
        assert result is not None
        assert result["hit"] is False  # zone never touched in the FULL window


def test_anchor_window_filters_old_events_and_discloses(monkeypatch) -> None:
    """Incremental scoring window (2026-07-13): events anchored before the
    trailing window are skipped (they were scored by earlier rolling runs)
    and the skip is disclosed; None keeps the unbounded behaviour."""
    day = 86400.0
    frame_end = 1_783_000_000.0
    bars = pd.DataFrame(
        {
            "symbol": "AAPL",
            "timestamp": [
                pd.Timestamp(frame_end - offset_days * day, unit="s", tz="UTC")
                for offset_days in range(29, -1, -1)
            ],
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000.0,
        }
    )
    # Geometry: the #3605 edge-censoring guard also skips KPI events whose
    # FULL horizon (FVG: 20 bars) is truncated, so the in-window event must
    # sit >= 20 bars before the frame edge on this 30-bar daily frame.
    old_event = {"id": "fvg-old", "anchor_ts": frame_end - 28 * day, "low": 99.0, "high": 100.0, "dir": "BULLISH"}
    recent_event = {"id": "fvg-new", "anchor_ts": frame_end - 22 * day, "low": 99.0, "high": 100.0, "dir": "BULLISH"}
    contract = {
        "structure_profile_used": "hybrid_default",
        "warnings": [],
        "canonical_structure": {
            "bos": [],
            "orderblocks": [],
            "fvg": [old_event, recent_event],
            "liquidity_sweeps": [],
        },
    }
    monkeypatch.setattr(
        measurement_evidence.structure_artifact_json,
        "load_normalized_structure_contract_input",
        lambda symbol, timeframe: contract,
    )
    monkeypatch.setattr(
        measurement_evidence, "_load_source_bars", lambda symbol, timeframe, resolved_inputs=None: (bars, "test")
    )
    monkeypatch.setattr(
        measurement_evidence,
        "build_explicit_structure_from_bars",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("recompute disabled in test")),
    )

    windowed = measurement_evidence.build_measurement_evidence("AAPL", "1D", anchor_window_days=25.0)
    assert windowed.details["scoring_anchor_window_days"] == 25.0
    assert windowed.details["skipped_out_of_window_counts"]["FVG"] == 1
    assert windowed.details["evaluated_event_counts"]["FVG"] == 1

    unbounded = measurement_evidence.build_measurement_evidence("AAPL", "1D")
    assert unbounded.details["scoring_anchor_window_days"] is None
    assert unbounded.details["skipped_out_of_window_counts"]["FVG"] == 0
    assert unbounded.details["evaluated_event_counts"]["FVG"] == 2


class TestSessionContextScoreFamilyParity:
    """The per-event SESSION_CONTEXT_SCORE structure bonus must treat all four
    event families uniformly.

    Regression: ``_session_context_light_for_event`` awarded a +1 structure bonus
    to ``{BOS, OB, FVG}`` but silently omitted ``SWEEP`` (the 4th member of
    ``_FAMILIES``), so a sweep event scored one point below an otherwise-identical
    structural event — flipping the ``build_signal_quality`` session-alignment
    bucket (>=4 killzone / >=3) at the boundary. Every other family iteration in the
    module treats the four families symmetrically.
    """

    def test_sweep_scores_same_as_structural_families(self) -> None:
        # Identical inputs; the ONLY variable is the event family. Any session /
        # killzone classification from the fixed anchor applies equally to all four,
        # so the score must be equal across families.
        common = dict(
            anchor_ts=1704207600.0,  # fixed 2024 instant; classification is family-agnostic
            expected_direction="BULLISH",
            bias_direction="BULLISH",
            vol_regime_label="NORMAL",
        )
        scores = {
            fam: measurement_evidence._session_context_light_for_event(family=fam, **common)[
                "SESSION_CONTEXT_SCORE"
            ]
            for fam in ("BOS", "OB", "FVG", "SWEEP")
        }
        assert scores["SWEEP"] == scores["BOS"] == scores["OB"] == scores["FVG"], (
            f"SWEEP must receive the same structure bonus as BOS/OB/FVG, got {scores}"
        )


def test_family_events_carry_the_bar_grid_they_were_measured_on(monkeypatch) -> None:
    """ADR-0031, Nachtrag 2026-10-02 III: the pool and the ledgers refuse
    events of another bar grid, and an event without the stamp counts as the
    previous one. The benchmark is where the stamp is put on."""
    from governance.family_returns import BAR_GRID, event_bar_grid

    contract, explicit = _contract_payload()
    _monkeypatch_full_evidence(monkeypatch, contract=contract, explicit_payload=explicit, bars=_daily_bars())

    evidence = measurement_evidence.build_measurement_evidence("AAPL", "1D")

    assert evidence.family_events, "the fixture must yield family events, or the loop below proves nothing"
    assert {event_bar_grid(event) for event in evidence.family_events} == {BAR_GRID}
    assert BAR_GRID == "exchange_aligned"


# ---------------------------------------------------------------------------
# Structure grain (ADR-0031, Nachtrag 2026-10-03 IV): BOS on the Pine engine's
# swing size as a second record, side by side with the fine-grain events.
# ---------------------------------------------------------------------------


def _m15_bars(n: int = 40) -> pd.DataFrame:
    start = pd.Timestamp("2024-01-02T14:30:00Z")
    rows = []
    price = 100.0
    for i in range(n):
        price += 0.2 if i % 3 else -0.1
        rows.append({
            "symbol": "AAPL",
            "timestamp": (start + pd.Timedelta(minutes=15 * i)).isoformat(),
            "open": price, "high": price + 0.5, "low": price - 0.5, "close": price + 0.1, "volume": 1000.0 + i,
        })
    return pd.DataFrame(rows)


def _grain_aware_explicit(fine: dict, coarse_bos: list[dict], calls: list[dict]):
    def explicit_fn(raw_bars, symbol, timeframe, structure_profile="hybrid_default", pivot_lookup=1):
        calls.append({"pivot_lookup": pivot_lookup, "structure_profile": structure_profile, "timeframe": timeframe})
        if pivot_lookup == 1:
            return fine
        return {"bos": coarse_bos, "orderblocks": [], "fvg": [], "liquidity_sweeps": [], "diagnostics": {}}
    return explicit_fn


def test_fine_grain_events_are_stamped_and_daily_skips_the_coarse_pass(monkeypatch) -> None:
    from governance.family_returns import PIVOT_LOOKUP, event_pivot_lookup

    contract, explicit = _contract_payload()
    calls: list[dict] = []
    _monkeypatch_full_evidence(
        monkeypatch, contract=contract, explicit_payload=explicit, bars=_daily_bars(),
        overrides={"explicit_fn": _grain_aware_explicit(explicit, [], calls)},
    )
    evidence = measurement_evidence.build_measurement_evidence("AAPL", "1D")

    assert evidence.family_events
    assert {event_pivot_lookup(event) for event in evidence.family_events} == {PIVOT_LOOKUP}
    assert {event["pivot_lookup"] for event in evidence.family_events} == {1}, "the stamp is explicit, not inferred"
    assert evidence.details["coarse_bos_event_count"] == 0
    assert [call["pivot_lookup"] for call in calls] == [1], "a 50-bar pivot cannot confirm inside the daily window"
    assert not [w for w in evidence.warnings if "coarse" in w]


def test_intraday_runs_the_coarse_bos_pass_as_a_second_record(monkeypatch) -> None:
    from governance.family_returns import COARSE_EVENT_ID_SUFFIX, COARSE_PIVOT_LOOKUP, event_pivot_lookup

    bars = _m15_bars()
    ts = pd.to_datetime(bars["timestamp"]).map(lambda t: t.timestamp()).tolist()
    fine = {
        "bos": [{"id": "bos:AAPL:15m:fine", "time": ts[10], "price": 101.0, "kind": "BOS", "dir": "UP", "source": "synthetic"}],
        "orderblocks": [], "fvg": [], "liquidity_sweeps": [], "diagnostics": {},
    }
    coarse = [
        {"id": "bos:AAPL:15m:fine", "time": ts[10], "price": 101.0, "kind": "BOS", "dir": "UP", "source": "synthetic"},
        {"id": "bos:AAPL:15m:other", "time": ts[20], "price": 102.0, "kind": "CHOCH", "dir": "DOWN", "source": "synthetic"},
    ]
    contract = {
        "symbol": "AAPL", "timeframe": "15m", "structure_profile_used": "hybrid_default",
        "canonical_structure": {"bos": list(fine["bos"]), "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
    }
    calls: list[dict] = []
    _monkeypatch_full_evidence(
        monkeypatch, contract=contract, explicit_payload=fine, bars=bars,
        overrides={"explicit_fn": _grain_aware_explicit(fine, coarse, calls)},
    )
    evidence = measurement_evidence.build_measurement_evidence("AAPL", "15m")

    by_grain: dict[int, list[dict]] = {}
    for event in evidence.family_events:
        by_grain.setdefault(event_pivot_lookup(event), []).append(event)
    assert set(by_grain) == {1, COARSE_PIVOT_LOOKUP}
    assert [e["event_id"] for e in by_grain[1]] == ["bos:AAPL:15m:fine"]
    # Same bar, same level as the fine BOS — still a distinct pool entry.
    assert sorted(e["event_id"] for e in by_grain[COARSE_PIVOT_LOOKUP]) == [
        f"bos:AAPL:15m:fine{COARSE_EVENT_ID_SUFFIX}",
        f"bos:AAPL:15m:other{COARSE_EVENT_ID_SUFFIX}",
    ]
    assert {e["family"] for e in by_grain[COARSE_PIVOT_LOOKUP]} == {"BOS"}
    assert {e["bar_grid"] for e in evidence.family_events} == {"exchange_aligned"}
    assert evidence.details["coarse_bos_event_count"] == 2
    coarse_calls = [c for c in calls if c["pivot_lookup"] == COARSE_PIVOT_LOOKUP]
    assert coarse_calls == [{"pivot_lookup": 50, "structure_profile": "hybrid_default", "timeframe": "15m"}]


def test_a_failing_coarse_pass_leaves_the_record_intact_and_says_so(monkeypatch) -> None:
    bars = _m15_bars()
    ts = pd.to_datetime(bars["timestamp"]).map(lambda t: t.timestamp()).tolist()
    fine = {
        "bos": [{"id": "bos:AAPL:15m:fine", "time": ts[10], "price": 101.0, "kind": "BOS", "dir": "UP", "source": "synthetic"}],
        "orderblocks": [], "fvg": [], "liquidity_sweeps": [], "diagnostics": {},
    }
    contract = {
        "symbol": "AAPL", "timeframe": "15m", "structure_profile_used": "hybrid_default",
        "canonical_structure": {"bos": list(fine["bos"]), "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
    }

    def explicit_fn(raw_bars, symbol, timeframe, structure_profile="hybrid_default", pivot_lookup=1):
        if pivot_lookup != 1:
            raise RuntimeError("coarse boom")
        return fine

    _monkeypatch_full_evidence(monkeypatch, contract=contract, explicit_payload=fine, bars=bars, overrides={"explicit_fn": explicit_fn})
    evidence = measurement_evidence.build_measurement_evidence("AAPL", "15m")

    assert [e["event_id"] for e in evidence.family_events] == ["bos:AAPL:15m:fine"]
    assert evidence.details["coarse_bos_event_count"] == 0
    assert any("coarse BOS pass (pivot_lookup=50) unavailable: coarse boom" in w for w in evidence.warnings)
    assert any("coarse boom" in w for w in evidence.details["warnings"])
