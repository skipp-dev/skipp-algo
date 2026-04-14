from __future__ import annotations

import logging

from smc_integration import provider_health
from smc_integration.meta_merge import merge_raw_meta_domains
from smc_integration.repo_sources import _finalize_composite_meta


def _volume_meta() -> dict:
    return {
        "symbol": "AAPL",
        "timeframe": "15m",
        "asof_ts": 1709253600.0,
        "volume": {
            "value": {"regime": "NORMAL", "thin_fraction": 0.1},
            "asof_ts": 1709253600.0,
            "stale": False,
        },
        "provenance": ["volume:a"],
    }


def _news_meta() -> dict:
    return {
        "symbol": "AAPL",
        "timeframe": "15m",
        "asof_ts": 1709253602.0,
        "news": {
            "value": {"strength": 0.3, "bias": "BEARISH"},
            "asof_ts": 1709253602.0,
            "stale": False,
        },
        "provenance": ["news:a"],
    }


def test_domain_drop_emits_structured_log(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        _finalize_composite_meta(
            symbol="AAPL",
            timeframe="15m",
            reference_time=1709253610.0,
            structure_source="structure_artifact_json",
            planned_volume_source="databento_watchlist_csv",
            volume_meta=_volume_meta(),
            volume_domain_status="present",
            actual_volume_source="databento_watchlist_csv",
            volume_fallback_used=False,
            planned_technical_source="fmp_watchlist_json",
            technical_meta=None,
            technical_domain_status="domain_fields_incomplete",
            actual_technical_source="fmp_watchlist_json",
            technical_fallback_used=False,
            planned_news_source="benzinga_watchlist_json",
            news_meta=_news_meta(),
            news_domain_status="present",
            actual_news_source="benzinga_watchlist_json",
            news_fallback_used=False,
            relax_missing_optional_domains=False,
        )

    assert any(
        "domain_drop: domain=technical" in record.message
        and "reason=domain_fields_incomplete" in record.message
        and "provider=fmp_watchlist_json" in record.message
        for record in caplog.records
    )


def test_meta_merge_logs_missing_domains(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        merge_raw_meta_domains(
            volume_meta=_volume_meta(),
            technical_meta=None,
            news_meta=None,
            domain_sources={
                "structure": "structure_artifact_json",
                "volume": "databento_watchlist_csv",
                "technical": "fmp_watchlist_json",
                "news": "benzinga_watchlist_json",
            },
            domain_drop_reasons={
                "technical": "domain_fields_incomplete",
                "news": "source_file_not_found",
            },
            domain_drop_providers={
                "technical": "fmp_watchlist_json",
                "news": "benzinga_watchlist_json",
            },
        )

    assert any(
        "meta domains missing for AAPL/15m" in record.message
        and "technical,news" in record.message
        for record in caplog.records
    )


def test_provider_health_report_summarizes_domain_visibility(monkeypatch) -> None:
    monkeypatch.setattr(provider_health, "discover_provider_matrix", lambda: [])
    monkeypatch.setattr(
        provider_health,
        "discover_structure_source_status",
        lambda **_: {
            "source": "auto",
            "selected": "structure_artifact_json",
            "selected_health_issue_count": 0,
            "selected_health_issues": [],
        },
    )
    monkeypatch.setattr(
        provider_health,
        "_collect_artifact_health",
        lambda **_: {
            "status": "ok",
            "warnings": [],
            "failures": [],
            "degradations": [],
            "missing_artifacts": [],
            "stale_artifacts": [],
        },
    )
    monkeypatch.setattr(
        provider_health,
        "_run_smoke_checks",
        lambda **_: {
            "results": [
                {
                    "symbol": "AAPL",
                    "timeframe": "15m",
                    "status": "ok",
                    "domain_visibility_score": 1.0,
                    "domain_visibility_complete": True,
                    "domain_visibility_domains_present": ["news", "structure", "technical", "volume"],
                    "domain_visibility_domains_missing": [],
                },
                {
                    "symbol": "MSFT",
                    "timeframe": "15m",
                    "status": "warn",
                    "domain_visibility_score": 0.5,
                    "domain_visibility_complete": False,
                    "domain_visibility_domains_present": ["structure", "volume"],
                    "domain_visibility_domains_missing": ["technical", "news"],
                },
            ],
            "warnings": [],
            "failures": [],
            "degradations": [],
            "domain_alerts": [],
        },
    )

    report = provider_health.run_provider_health_check(
        symbols=["AAPL", "MSFT"],
        timeframes=["15m"],
        checked_at=1_700_000_000.0,
        stale_after_seconds=3600,
    )

    assert report["domain_visibility_score"] == 0.75
    assert report["domain_visibility_full_coverage_ratio"] == 0.5
    assert report["domain_visibility"]["fully_visible_rows"] == 1
    assert report["domain_visibility"]["evaluated_rows"] == 2