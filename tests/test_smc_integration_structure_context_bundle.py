from __future__ import annotations

import pandas as pd

from smc_integration import service
from smc_core.scoring import ScoredEvent
from smc_integration.measurement_evidence import MeasurementEvidence


class _FakeSourceDescriptor:
    def to_dict(self) -> dict:
        return {"name": "structure_artifact_json", "kind": "repo_source"}


def test_delivery_bundle_adds_optional_structure_context_without_snapshot_pollution(monkeypatch) -> None:
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
        ]
    )

    monkeypatch.setattr(service, "select_best_structure_source", lambda: _FakeSourceDescriptor())
    monkeypatch.setattr(service, "discover_composite_source_plan", lambda **_: {"structure": "structure_artifact_json", "volume": "watchlist", "technical": "watchlist", "news": "watchlist"})
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
            events_by_family={"BOS": [], "OB": [], "FVG": [], "SWEEP": []},
            stratified_events={},
            scored_events=[ScoredEvent("bos-1", "BOS", 0.75, True, 1.0)],
            details={
                "measurement_evidence_present": True,
                "bars_source_mode": "synthetic_bundle",
                "evaluated_event_counts": {"BOS": 0, "OB": 0, "FVG": 0, "SWEEP": 0},
                "ensemble_quality": {"available_components": ["bias", "scoring", "vol_regime"], "score": 0.81},
            },
            warnings=[],
        ),
    )
    monkeypatch.setattr(
        service.structure_artifact_json,
        "load_structure_context_input",
        lambda *args, **kwargs: {
            "structure_profile_used": "hybrid_default",
            "event_logic_version": "v2",
            "coverage": {
                "has_bos": True,
                "has_orderblocks": False,
                "has_fvg": False,
                "has_liquidity_sweeps": False,
            },
            "counts": {
                "bos": 1,
                "orderblocks": 0,
                "fvg": 0,
                "liquidity_sweeps": 0,
            },
        },
    )

    bundle = service.build_snapshot_bundle_for_symbol_timeframe("AAPL", "15m", source="auto", generated_at=1709253600.0)

    assert "structure_context" in bundle
    assert bundle["structure_context"]["structure_profile_used"] == "hybrid_default"
    assert bundle["structure_context"]["event_logic_version"] == "v2"
    assert bundle["structure_context"]["coverage"]["has_bos"] is True

    snapshot = bundle["snapshot"]
    assert set(snapshot["structure"].keys()) == {"bos", "orderblocks", "fvg", "liquidity_sweeps"}
    assert "liquidity_lines" not in snapshot["structure"]
    assert "session_ranges" not in snapshot["structure"]
    assert "session_pivots" not in snapshot["structure"]
    assert "ipda_range" not in snapshot["structure"]
    assert "htf_fvg_bias" not in snapshot["structure"]
    assert "broken_fractal_signals" not in snapshot["structure"]
