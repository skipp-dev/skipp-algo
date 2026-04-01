from __future__ import annotations

import pandas as pd

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

    assert evidence.details["measurement_evidence_present"] is True
    assert evidence.details["bars_source_mode"] == "synthetic_bundle"
    assert evidence.details["canonical_event_counts"] == {"BOS": 1, "OB": 1, "FVG": 1, "SWEEP": 1}
    assert evidence.details["evaluated_event_counts"] == {"BOS": 1, "OB": 1, "FVG": 1, "SWEEP": 1}
    assert evidence.events_by_family["BOS"][0]["hit"] is True
    assert evidence.events_by_family["BOS"][0]["invalidated"] is True
    assert evidence.events_by_family["OB"][0]["hit"] is True
    assert evidence.events_by_family["FVG"][0]["hit"] is True
    assert evidence.scored_events[0].family == "SWEEP"
    assert evidence.scored_events[0].outcome is True
    assert evidence.scored_events[0].predicted_prob > 0.5
    assert "session:NONE" in evidence.stratified_events
    assert "htf_bias:BULLISH" in evidence.stratified_events
    assert "vol_regime:NORMAL" in evidence.stratified_events
    assert evidence.warnings == []


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