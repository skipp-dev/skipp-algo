from __future__ import annotations

from smc_adapters.dashboard import snapshot_to_dashboard_payload
from smc_adapters.ingest import build_snapshot_from_raw


def _snapshot():
    raw_structure = {
        "bos": [
            {"id": "bos:2", "time": 2, "price": 102.0, "kind": "BOS", "dir": "UP"},
            {"id": "bos:1", "time": 1, "price": 101.0, "kind": "CHOCH", "dir": "DOWN"},
        ],
        "orderblocks": [
            {"id": "ob:2", "low": 99.0, "high": 100.0, "dir": "BULL", "valid": True},
            {"id": "ob:1", "low": 98.0, "high": 99.0, "dir": "BEAR", "valid": True},
        ],
        "fvg": [
            {"id": "fvg:1", "low": 100.2, "high": 100.8, "dir": "BULL", "valid": True}
        ],
        "liquidity_sweeps": [
            {"id": "sw:1", "time": 3, "price": 100.5, "side": "SELL_SIDE"}
        ],
    }
    raw_meta = {
        "symbol": "AAPL",
        "timeframe": "15m",
        "asof_ts": 1709253580,
        "volume": {
            "value": {"regime": "NORMAL", "thin_fraction": 0.1},
            "asof_ts": 1709253580,
            "stale": False,
        },
        "provenance": ["TEST"],
    }
    return build_snapshot_from_raw(raw_structure, raw_meta, generated_at=1709254000.0)


def test_dashboard_payload_contains_summary_zones_markers() -> None:
    payload = snapshot_to_dashboard_payload(_snapshot())
    assert "structure_coverage" in payload
    assert "summary" in payload
    assert "zones" in payload
    assert "markers" in payload


def test_dashboard_zones_and_markers_kind_partition() -> None:
    payload = snapshot_to_dashboard_payload(_snapshot())
    zone_kinds = {z["kind"] for z in payload["zones"]}
    marker_kinds = {m["kind"] for m in payload["markers"]}
    assert zone_kinds.issubset({"ORDERBLOCK", "FVG"})
    assert marker_kinds.issubset({"BOS", "CHOCH", "LIQUIDITY_SWEEP"})


def test_dashboard_summary_zone_count_matches_zones() -> None:
    payload = snapshot_to_dashboard_payload(_snapshot())
    assert payload["summary"]["zone_count"] == len(payload["zones"])
    assert payload["summary"]["marker_count"] == len(payload["markers"])


def test_dashboard_structure_coverage_matches_snapshot_content() -> None:
    payload = snapshot_to_dashboard_payload(_snapshot())
    coverage = payload["structure_coverage"]

    assert coverage["has_bos"] is True
    assert coverage["has_orderblocks"] is True
    assert coverage["has_fvg"] is True
    assert coverage["has_liquidity_sweeps"] is True
    assert "bos" in coverage["available_categories"]
    assert "choch" in coverage["available_categories"]


def test_dashboard_style_fields_are_projected() -> None:
    payload = snapshot_to_dashboard_payload(_snapshot())
    first_zone_style = payload["zones"][0]["style"]
    for key in ["render_state", "trade_state", "bias", "strength", "heat", "tone", "emphasis", "reason_codes"]:
        assert key in first_zone_style


def test_dashboard_sorting_is_deterministic() -> None:
    payload = snapshot_to_dashboard_payload(_snapshot())
    zone_order = [(z["kind"], z["id"]) for z in payload["zones"]]
    marker_order = [(m["kind"], m["id"]) for m in payload["markers"]]
    assert zone_order == sorted(zone_order)
    assert marker_order == sorted(marker_order)
