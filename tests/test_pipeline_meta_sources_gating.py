"""Truth-audit: meta["sources"] must list the FMP political/filings extras
whenever they actually poll.

The extras (senate/house/8-K/13F) fetch on ``enable_fmp_<x> and fmp_api_key``,
independent of ``ENABLE_FMP`` (mirroring Config.active_sources). Their telemetry
labels were nested under ``if cfg.enable_fmp:``, so with ENABLE_FMP=0 and a
sub-flag on the source was polled and exported yet missing from meta["sources"].
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch


def test_meta_sources_lists_political_extra_when_enable_fmp_off() -> None:
    from newsstack_fmp import pipeline
    from newsstack_fmp.config import Config

    env = {
        "FMP_API_KEY": "test",
        "ENABLE_FMP": "0",
        "ENABLE_FMP_SENATE_TRADES": "1",
        "FILTER_TO_UNIVERSE": "0",
    }
    with patch("newsstack_fmp.pipeline._get_store") as mock_store, patch(
        "newsstack_fmp.pipeline._get_enricher"
    ) as mock_enr, patch("newsstack_fmp.pipeline.export_open_prep"), patch(
        "newsstack_fmp.pipeline.fetch_fmp_senate_trades", return_value=[]
    ), patch.dict(os.environ, env, clear=False):
        store = MagicMock()
        store.get_kv.return_value = "0"
        mock_store.return_value = store
        mock_enr.return_value = MagicMock()
        cfg = Config()
        assert cfg.enable_fmp is False
        assert cfg.enable_fmp_senate_trades is True
        pipeline.poll_once(cfg, universe=set())

    sources = pipeline.get_last_meta().get("sources", [])
    # Polled + exported ⇒ must be visible in telemetry.
    assert "fmp_senate_trade" in sources, sources
    # ENABLE_FMP=0 ⇒ the core FMP labels must NOT appear (guards against a
    # regression that simply un-gates everything).
    assert "fmp_stock_latest" not in sources, sources
