from __future__ import annotations

import smc_integration.repo_sources as repo_sources_module
import pytest

from smc_integration.repo_sources import (
    discover_composite_source_plan,
    discover_repo_source_paths,
    discover_repo_sources,
    load_raw_meta_input,
    select_best_news_source,
    select_best_structure_source,
    select_best_technical_source,
    select_best_volume_source,
    load_raw_structure_input,
)


def test_discover_repo_sources_includes_watchlist_csv_source() -> None:
    sources = discover_repo_sources()
    names = [item.name for item in sources]
    assert "structure_artifact_json" in names
    assert "databento_watchlist_csv" in names
    assert "live_news_snapshot_json" in names
    assert "tradingview_watchlist_json" in names
    assert "fmp_watchlist_json" in names
    assert "benzinga_watchlist_json" in names


def test_discover_repo_sources_names_are_unique() -> None:
    sources = discover_repo_sources()
    names = [item.name for item in sources]
    assert len(names) == len(set(names))


def test_source_auto_selection_is_deterministic() -> None:
    one = discover_repo_source_paths()
    two = discover_repo_source_paths()
    assert one["selected_source"]["name"] == two["selected_source"]["name"]


def test_domain_selectors_return_expected_providers() -> None:
    assert select_best_structure_source().name == "structure_artifact_json"
    assert select_best_volume_source().name == "databento_watchlist_csv"
    assert select_best_technical_source().name in {"fmp_watchlist_json", "tradingview_watchlist_json"}
    assert select_best_news_source().name == "live_news_snapshot_json"


def test_discover_composite_source_plan_auto_and_explicit() -> None:
    auto_plan = discover_composite_source_plan(source="auto")
    assert auto_plan["structure"] == "structure_artifact_json"
    assert auto_plan["volume"] == "databento_watchlist_csv"
    assert auto_plan["news"] == "live_news_snapshot_json"

    single = discover_composite_source_plan(source="fmp_watchlist_json")
    assert single == {
        "structure": "fmp_watchlist_json",
        "volume": "fmp_watchlist_json",
        "technical": "fmp_watchlist_json",
        "news": "fmp_watchlist_json",
        "structure_resolution_mode": "n/a",
    }



def test_explicit_source_selection_works_for_structure_and_meta() -> None:
    structure = load_raw_structure_input("IBG", "15m", source="databento_watchlist_csv")
    meta = load_raw_meta_input("IBG", "15m", source="databento_watchlist_csv")

    assert set(structure.keys()) == {"bos", "orderblocks", "fvg", "liquidity_sweeps"}
    assert meta["symbol"] == "IBG"



def test_unknown_source_raises_clear_error() -> None:
    try:
        _ = load_raw_meta_input("IBG", "15m", source="does_not_exist")
    except ValueError as exc:
        assert "unknown source" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown source")


def test_ibkr_source_name_is_rejected() -> None:
    try:
        _ = load_raw_meta_input("IBG", "15m", source="ibkr_watchlist_preview_json")
    except ValueError as exc:
        assert "unknown source" in str(exc)
    else:
        raise AssertionError("expected ValueError for disabled ibkr source")



def test_source_capabilities_are_set_and_traceable() -> None:
    sources = discover_repo_sources()
    by_name = {item.name: item for item in sources}

    watchlist = by_name["databento_watchlist_csv"]
    assert watchlist.capabilities.has_meta is True
    assert watchlist.capabilities.structure_mode in {"full", "partial", "none"}
    assert isinstance(watchlist.notes, list)


def test_composite_meta_plan_is_symbol_timeframe_aware(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def _fake_plan(*, source: str = "auto", symbol: str = "", timeframe: str = "") -> dict[str, str]:
        captured["source"] = source
        captured["symbol"] = symbol
        captured["timeframe"] = timeframe
        return {
            "structure": "databento_watchlist_csv",
            "volume": "databento_watchlist_csv",
            "technical": "databento_watchlist_csv",
            "news": "databento_watchlist_csv",
        }

    monkeypatch.setattr(repo_sources_module, "discover_composite_source_plan", _fake_plan)

    payload = repo_sources_module.load_raw_meta_input_composite("IBG", "15m", source="auto")

    assert payload["symbol"] == "IBG"
    assert payload["timeframe"] == "15m"
    assert captured["source"] == "auto"
    assert captured["symbol"] == "IBG"
    assert captured["timeframe"] == "15m"


def test_composite_meta_rejects_invalid_asof_ts(monkeypatch) -> None:
    monkeypatch.setattr(
        repo_sources_module,
        "merge_raw_meta_domains",
        lambda **kwargs: {
            "symbol": "IBG",
            "timeframe": "15m",
            "asof_ts": -1.0,
            "volume": {
                "value": {"regime": "NORMAL", "thin_fraction": 0.0},
                "asof_ts": -1.0,
                "stale": False,
            },
            "provenance": [],
        },
    )

    with pytest.raises(ValueError, match="invalid asof_ts"):
        repo_sources_module.load_raw_meta_input_composite("IBG", "15m", source="auto")


def test_composite_meta_marks_stale_asof_ts_in_provenance(monkeypatch) -> None:
    monkeypatch.setattr(
        repo_sources_module,
        "merge_raw_meta_domains",
        lambda **kwargs: {
            "symbol": "IBG",
            "timeframe": "15m",
            "asof_ts": 1.0,
            "volume": {
                "value": {"regime": "NORMAL", "thin_fraction": 0.0},
                "asof_ts": 1.0,
                "stale": False,
            },
            "provenance": [],
        },
    )

    payload = repo_sources_module.load_raw_meta_input_composite("IBG", "15m", source="auto")

    assert any("stale_meta_asof_ts" in str(item) for item in payload.get("provenance", []))


def test_release_reference_meta_can_synthesize_volume_from_structure_artifact(monkeypatch) -> None:
    monkeypatch.setattr(
        repo_sources_module,
        "discover_composite_source_plan",
        lambda **kwargs: {
            "structure": "structure_artifact_json",
            "volume": "databento_watchlist_csv",
            "technical": "fmp_watchlist_json",
            "news": "benzinga_watchlist_json",
            "structure_resolution_mode": "manifest",
        },
    )
    monkeypatch.setattr(
        repo_sources_module.structure_artifact_json,
        "has_artifact_for_symbol_timeframe",
        lambda symbol, timeframe: True,
    )

    def _missing_domain(domain: str, symbol: str, timeframe: str, primary_name: str, *, auto_mode: bool, reference_time: float | None = None):
        return None, "source_validation_error", primary_name

    monkeypatch.setattr(repo_sources_module, "_try_load_meta_domain", _missing_domain)

    payload = repo_sources_module.load_raw_meta_input_composite_for_release_reference(
        "AAPL",
        "5m",
        source="auto",
        reference_time=1000.0,
    )

    assert payload["asof_ts"] == 1000.0
    assert payload["volume"]["value"]["regime"] == "SYNTHETIC_FALLBACK"
    assert payload["volume"]["value"]["thin_fraction"] == 0.0
    assert payload["meta_domains_missing"] == ["technical", "news"]
    assert payload["domain_drop_reasons"] == {
        "technical": "source_validation_error",
        "news": "source_validation_error",
    }
    assert payload["domain_drop_providers"] == {
        "technical": "fmp_watchlist_json",
        "news": "benzinga_watchlist_json",
    }
    diag = payload["meta_domain_diagnostics"]
    assert diag["volume"] == "synthetic_fallback"
    assert diag["volume_planned_source"] == "databento_watchlist_csv"
    assert diag["volume_source"] == "synthetic_structure_artifact_meta"
    assert diag["volume_fallback_used"] is True
    assert diag["technical_planned_source"] == "fmp_watchlist_json"
    assert diag["news_planned_source"] == "benzinga_watchlist_json"
    assert diag["technical_stale"] is False
    assert diag["news_stale"] is False


def test_try_load_meta_domain_logs_warning_when_no_candidates_are_attempted(monkeypatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(repo_sources_module, "_SOURCE_PROVIDERS", {})

    with caplog.at_level("WARNING"):
        payload, status, actual_source = repo_sources_module._try_load_meta_domain(
            "technical",
            "AAPL",
            "15m",
            "fmp_watchlist_json",
            auto_mode=True,
        )

    assert payload is None
    assert status == "not_attempted_no_candidates"
    assert actual_source == "fmp_watchlist_json"
    assert "reason_code=not_attempted_no_candidates" in caplog.text


def test_try_load_meta_domain_surfaces_domain_key_absent_across_all_candidates(monkeypatch, caplog: pytest.LogCaptureFixture) -> None:
    class _Provider:
        def load_meta(self, symbol: str, timeframe: str, **_kwargs) -> dict[str, object]:
            del symbol, timeframe
            return {}

    monkeypatch.setattr(
        repo_sources_module,
        "_SOURCE_PROVIDERS",
        {
            "fmp_watchlist_json": _Provider(),
            "tradingview_watchlist_json": _Provider(),
        },
    )
    monkeypatch.setitem(
        repo_sources_module._DOMAIN_SOURCE_ORDER,
        "technical",
        ["fmp_watchlist_json", "tradingview_watchlist_json"],
    )
    monkeypatch.setattr(repo_sources_module, "_can_supply_domain", lambda *_args, **_kwargs: True)

    with caplog.at_level("WARNING"):
        payload, status, actual_source = repo_sources_module._try_load_meta_domain(
            "technical",
            "AAPL",
            "15m",
            "fmp_watchlist_json",
            auto_mode=True,
        )

    assert payload is None
    assert status == "domain_key_absent_all_candidates"
    assert actual_source == "tradingview_watchlist_json"
    assert "reason_code=domain_key_absent_all_candidates" in caplog.text
