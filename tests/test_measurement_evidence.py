from __future__ import annotations

from pathlib import Path

import pandas as pd

from smc_integration import measurement_evidence
from smc_core.vol_regime import VolRegimeResult


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