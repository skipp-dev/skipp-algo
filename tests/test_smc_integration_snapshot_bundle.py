from __future__ import annotations

import pandas as pd

from smc_integration import service
from smc_core.scoring import ScoredEvent
from smc_core.vol_regime import VolRegimeResult
from smc_integration.measurement_evidence import MeasurementEvidence


class _FakeSourceDescriptor:
    def to_dict(self) -> dict:
        return {"name": "structure_artifact_json", "kind": "repo_source"}


def test_bundle_contains_snapshot_projections_and_additive_contexts(monkeypatch) -> None:
    raw_structure = {
        "bos": [{"id": "bos:1", "time": 1.0, "price": 101.0, "kind": "BOS", "dir": "UP"}],
        "orderblocks": [],
        "fvg": [],
        "liquidity_sweeps": [],
    }
    raw_meta = {
        "symbol": "AAPL",
        "timeframe": "15m",
        "asof_ts": 10.0,
        "volume": {
            "value": {"regime": "NORMAL", "thin_fraction": 0.1},
            "asof_ts": 10.0,
            "stale": False,
        },
    }

    bars = pd.DataFrame(
        [
            {"timestamp": 1, "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0, "symbol": "AAPL"},
            {"timestamp": 2, "open": 100.5, "high": 102.0, "low": 100.0, "close": 101.5, "volume": 900.0, "symbol": "AAPL"},
            {"timestamp": 3, "open": 101.5, "high": 102.5, "low": 100.5, "close": 101.0, "volume": 950.0, "symbol": "AAPL"},
        ]
    )

    monkeypatch.setattr(service, "select_best_structure_source", lambda: _FakeSourceDescriptor())
    monkeypatch.setattr(service, "discover_composite_source_plan", lambda **_: {"structure": "structure_artifact_json", "volume": "watchlist"})
    monkeypatch.setattr(service, "discover_structure_source_status", lambda **_: {"source": "structure_artifact_json", "coverage": "partial"})
    monkeypatch.setattr(service, "load_raw_structure_input", lambda *args, **kwargs: raw_structure)
    monkeypatch.setattr(service, "load_raw_meta_input_composite", lambda *args, **kwargs: raw_meta)
    monkeypatch.setattr(service, "_load_symbol_bars_for_context", lambda *args, **kwargs: bars)
    monkeypatch.setattr(service, "build_structure_qualifiers", lambda *args, **kwargs: {"ppdd": []})
    monkeypatch.setattr(service, "build_session_liquidity_context", lambda *args, **kwargs: {"killzones": []})
    monkeypatch.setattr(service, "build_htf_bias_context", lambda *args, **kwargs: {"selected_ipda_htf": "D"})
    monkeypatch.setattr(
        service,
        "build_measurement_evidence",
        lambda *_args, **_kwargs: MeasurementEvidence(
            events_by_family={
                "BOS": [{"hit": True, "time_to_mitigation": 1.0, "invalidated": False, "mae": 0.01, "mfe": 0.03}],
                "OB": [],
                "FVG": [],
                "SWEEP": [],
            },
            stratified_events={
                "htf_bias:NEUTRAL": {
                    "BOS": [{"hit": True, "time_to_mitigation": 1.0, "invalidated": False, "mae": 0.01, "mfe": 0.03}],
                    "OB": [],
                    "FVG": [],
                    "SWEEP": [],
                }
            },
            scored_events=[ScoredEvent("bos-1", "BOS", 0.75, True, 1.0)],
            details={
                "measurement_evidence_present": True,
                "bars_source_mode": "synthetic_bundle",
                "evaluated_event_counts": {"BOS": 1, "OB": 0, "FVG": 0, "SWEEP": 0},
                "ensemble_quality": {"available_components": ["bias", "scoring", "vol_regime"], "score": 0.81},
            },
            warnings=[],
        ),
    )
    monkeypatch.setattr(
        service,
        "compute_vol_regime",
        lambda _bars: VolRegimeResult(
            label="HIGH_VOL",
            raw_atr_ratio=1.7,
            confidence=0.88,
            bars_used=len(_bars),
            model_source="arch_garch",
            fallback_reason=None,
            forecast_volatility=0.03,
            baseline_volatility=0.017,
            forecast_ratio=1.7647,
        ),
    )

    bundle = service.build_snapshot_bundle_for_symbol_timeframe("AAPL", "15m", source="auto", generated_at=1709253600.0)

    assert set(["source_plan", "structure_status", "snapshot", "dashboard_payload", "pine_payload"]).issubset(set(bundle.keys()))
    assert set(["structure_qualifiers", "session_context", "htf_context"]).issubset(set(bundle.keys()))

    snapshot = bundle["snapshot"]
    assert set(snapshot["structure"].keys()) == {"bos", "orderblocks", "fvg", "liquidity_sweeps"}
    assert "structure_qualifiers" not in snapshot["structure"]
    assert "session_context" not in snapshot["structure"]
    assert "htf_context" not in snapshot["structure"]

    assert bundle["vol_regime"] == {
        "label": "HIGH_VOL",
        "raw_atr_ratio": 1.7,
        "confidence": 0.88,
        "bars_used": 3,
        "model_source": "arch_garch",
        "fallback_reason": None,
        "forecast_volatility": 0.03,
        "baseline_volatility": 0.017,
        "forecast_ratio": 1.7647,
    }
    assert bundle["ensemble_quality"]["available_components"] == ["bias", "heuristic", "vol_regime"]
    assert 0.0 <= bundle["ensemble_quality"]["score"] <= 1.0
    assert bundle["measurement_refs"]["status"] == "available"
    assert bundle["measurement_refs"]["summary_artifact"] == "measurement_summary_AAPL_15m.json"
    assert bundle["measurement_summary"]["measurement_evidence_present"] is True
    assert bundle["measurement_summary"]["benchmark_event_counts"] == {"BOS": 1, "OB": 0, "FVG": 0, "SWEEP": 0}
    assert bundle["measurement_summary"]["scoring"]["n_events"] == 1
    assert bundle["measurement_summary"]["scoring"]["families_present"] == ["BOS"]
    assert bundle["market_context"]["bias_direction"] == bundle["bias_verdict"]["direction"]
    assert bundle["market_context"]["vol_regime_label"] == "HIGH_VOL"
    assert bundle["market_context"]["measurement_status"] == "available"

    dashboard_coverage = bundle["dashboard_payload"]["structure_coverage"]
    pine_coverage = bundle["pine_payload"]["structure_coverage"]
    assert dashboard_coverage["has_bos"] is True
    assert dashboard_coverage["has_orderblocks"] is False
    assert dashboard_coverage["has_fvg"] is False
    assert dashboard_coverage["has_liquidity_sweeps"] is False
    assert pine_coverage == dashboard_coverage
