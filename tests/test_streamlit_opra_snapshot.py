from __future__ import annotations

import json
from datetime import UTC, datetime

from open_prep import streamlit_monitor


def test_missing_snapshot_is_explicitly_unavailable(tmp_path) -> None:
    result = streamlit_monitor.load_opra_shadow_snapshot(tmp_path / "missing.json")
    assert result["status"] == "unavailable"
    assert result["reason"] == "snapshot_not_found"


def test_local_snapshot_load_never_uses_historical_wrapper(tmp_path, monkeypatch) -> None:
    path = tmp_path / "opra.json"
    path.write_text(
        json.dumps(
            {
                "version": "opra-shadow/v1",
                "status": "shadow",
                "shadow_only": True,
                "asof": datetime.now(UTC).isoformat(),
                "candidates": [{"ticker": "AAPL"}],
            }
        ),
        encoding="utf-8",
    )
    import newsstack_fmp.ingest_opra_options_flow as historical

    monkeypatch.setattr(
        historical,
        "fetch_opra_options_flow",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("provider called")),
    )
    streamlit_monitor._cached_opra_shadow_snapshot.clear()
    result = streamlit_monitor.load_opra_shadow_snapshot(path)
    assert result["status"] == "shadow"
    assert result["candidates"] == [{"ticker": "AAPL"}]


def test_stale_snapshot_is_not_reported_as_fresh(tmp_path) -> None:
    path = tmp_path / "opra.json"
    path.write_text(
        json.dumps(
            {
                "version": "opra-shadow/v1",
                "status": "shadow",
                "shadow_only": True,
                "asof": "2026-01-01T00:00:00+00:00",
                "candidates": [],
            }
        ),
        encoding="utf-8",
    )
    streamlit_monitor._cached_opra_shadow_snapshot.clear()
    assert streamlit_monitor.load_opra_shadow_snapshot(path)["status"] == "stale"
