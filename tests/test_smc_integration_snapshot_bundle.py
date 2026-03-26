from __future__ import annotations

import pandas as pd

from smc_integration import service


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

    bundle = service.build_snapshot_bundle_for_symbol_timeframe("AAPL", "15m", source="auto", generated_at=1709253600.0)

    assert set(["source_plan", "structure_status", "snapshot", "dashboard_payload", "pine_payload"]).issubset(set(bundle.keys()))
    assert set(["structure_qualifiers", "session_context", "htf_context"]).issubset(set(bundle.keys()))

    snapshot = bundle["snapshot"]
    assert set(snapshot["structure"].keys()) == {"bos", "orderblocks", "fvg", "liquidity_sweeps"}
    assert "structure_qualifiers" not in snapshot["structure"]
    assert "session_context" not in snapshot["structure"]
    assert "htf_context" not in snapshot["structure"]

    dashboard_coverage = bundle["dashboard_payload"]["structure_coverage"]
    pine_coverage = bundle["pine_payload"]["structure_coverage"]
    assert dashboard_coverage["has_bos"] is True
    assert dashboard_coverage["has_orderblocks"] is False
    assert dashboard_coverage["has_fvg"] is False
    assert dashboard_coverage["has_liquidity_sweeps"] is False
    assert pine_coverage == dashboard_coverage
