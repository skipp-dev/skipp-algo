from __future__ import annotations

import json
import os
from pathlib import Path

from smc_integration import provider_health


def _stub_structure_status(**_: object) -> dict[str, object]:
    return {
        "source": "auto",
        "selected": "structure_artifact_json",
        "selected_health_issue_count": 0,
        "selected_health_issues": [],
    }


def _stub_contract_summary(**_: object) -> dict[str, object]:
    return {
        "mapped_structure_categories": {
            "bos": "bos",
            "orderblocks": "orderblocks",
            "fvg": "fvg",
            "liquidity_sweeps": "liquidity_sweeps",
        },
        "structure_profile_supported": True,
        "diagnostics_available": True,
        "health": {"issues": [], "sources": []},
    }


def _stub_smoke_ok(**_: object) -> dict[str, object]:
    return {
        "results": [],
        "warnings": [],
        "failures": [],
        "degradations": [],
    }


def _write_real_manifest_artifact_fixture(tmp_path: Path, *, observed_workbook: Path, generated_at: float = 95.0) -> Path:
    artifact_dir = tmp_path / "reports" / "smc_structure_artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    artifact_path = artifact_dir / "AAPL_15m.structure.json"
    artifact_path.write_text(
        json.dumps(
            {
                "symbol": "AAPL",
                "timeframe": "15m",
                "structure": {
                    "bos": [
                        {
                            "id": "bos:AAPL:15m:1",
                            "time": 1.0,
                            "price": 100.0,
                            "kind": "BOS",
                            "dir": "UP",
                        }
                    ],
                    "orderblocks": [],
                    "fvg": [],
                    "liquidity_sweeps": [],
                },
                "auxiliary": {},
                "diagnostics": {
                    "structure_profile_used": "hybrid_default",
                    "event_logic_version": "v2",
                },
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    manifest_path = artifact_dir / "manifest_15m.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": "3.0.0",
                "generated_at": generated_at,
                "timeframe": "15m",
                "producer": {
                    "name": "smc_price_action_engine_v2",
                    "upstream": observed_workbook.as_posix(),
                },
                "resolved_inputs": {
                    "workbook_path": observed_workbook.as_posix(),
                    "export_bundle_root": (tmp_path / "artifacts" / "smc_microstructure_exports").as_posix(),
                },
                "artifacts": [
                    {
                        "symbol": "AAPL",
                        "timeframe": "15m",
                        "artifact_path": "reports/smc_structure_artifacts/AAPL_15m.structure.json",
                    }
                ],
                "errors": [],
                "warnings": [],
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    os.utime(manifest_path, (generated_at, generated_at))
    return artifact_dir


def _patch_real_artifact_environment(monkeypatch, tmp_path: Path, artifact_dir: Path, canonical_workbook: Path) -> None:
    from smc_integration import artifact_resolution

    monkeypatch.setattr(provider_health, "discover_provider_matrix", lambda: [])
    monkeypatch.setattr(provider_health, "discover_structure_source_status", _stub_structure_status)
    monkeypatch.setattr(provider_health, "_run_smoke_checks", _stub_smoke_ok)
    monkeypatch.setattr(provider_health.structure_artifact_json, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(provider_health.structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", artifact_dir)
    monkeypatch.setattr(
        provider_health.structure_artifact_json,
        "STRUCTURE_ARTIFACT_JSON",
        tmp_path / "reports" / "smc_structure_artifact.json",
    )
    monkeypatch.setattr(artifact_resolution, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(artifact_resolution, "resolve_production_workbook_path", lambda explicit_path=None: canonical_workbook)


def test_run_provider_health_real_canonical_manifest_is_ok(monkeypatch, tmp_path):
    canonical_workbook = tmp_path / "artifacts" / "smc_microstructure_exports" / "canonical.xlsx"
    canonical_workbook.parent.mkdir(parents=True, exist_ok=True)
    canonical_workbook.write_text("workbook\n", encoding="utf-8")

    artifact_dir = _write_real_manifest_artifact_fixture(tmp_path, observed_workbook=canonical_workbook)
    _patch_real_artifact_environment(monkeypatch, tmp_path, artifact_dir, canonical_workbook)

    report = provider_health.run_provider_health_check(
        symbols=["AAPL"],
        timeframes=["15m"],
        checked_at=100.0,
        stale_after_seconds=30,
    )

    assert report["overall_status"] == "ok"
    assert report["warnings"] == []
    assert report["failures"] == []
    assert report["artifact_health"]["health_issue_count"] == 0
    assert report["artifact_health"]["contract_summary"]["mapped_structure_categories"]["bos"] is True


def test_run_provider_health_real_manifest_surfaces_noncanonical_provenance(monkeypatch, tmp_path):
    canonical_workbook = tmp_path / "artifacts" / "smc_microstructure_exports" / "canonical.xlsx"
    canonical_workbook.parent.mkdir(parents=True, exist_ok=True)
    canonical_workbook.write_text("workbook\n", encoding="utf-8")

    observed_workbook = tmp_path / "pytest-temp" / "noncanonical.xlsx"
    observed_workbook.parent.mkdir(parents=True, exist_ok=True)
    observed_workbook.write_text("noncanonical\n", encoding="utf-8")

    artifact_dir = _write_real_manifest_artifact_fixture(tmp_path, observed_workbook=observed_workbook)
    _patch_real_artifact_environment(monkeypatch, tmp_path, artifact_dir, canonical_workbook)

    report = provider_health.run_provider_health_check(
        symbols=["AAPL"],
        timeframes=["15m"],
        checked_at=100.0,
        stale_after_seconds=30,
    )

    assert report["overall_status"] == "warn"
    codes = {str(item.get("code", "")) for item in report["warnings"]}
    assert "NONCANONICAL_MANIFEST_WORKBOOK_PATH" in codes
    assert report["artifact_health"]["contract_summary"]["mapped_structure_categories"]["bos"] is False


def test_run_provider_health_missing_artifact_visible(monkeypatch, tmp_path):
    monkeypatch.setattr(provider_health, "discover_provider_matrix", lambda: [])
    monkeypatch.setattr(provider_health, "discover_structure_source_status", _stub_structure_status)
    monkeypatch.setattr(provider_health.structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(provider_health.structure_artifact_json, "discover_normalized_contract_summary", _stub_contract_summary)
    monkeypatch.setattr(provider_health.structure_artifact_json, "has_artifact_for_symbol_timeframe", lambda symbol, timeframe: False)
    monkeypatch.setattr(provider_health, "_run_smoke_checks", _stub_smoke_ok)

    report = provider_health.run_provider_health_check(
        symbols=["AAPL"],
        timeframes=["15m"],
        checked_at=1_700_000_000.0,
    )

    assert report["overall_status"] == "warn"
    assert report["missing_artifacts"] == [
        {
            "symbol": "AAPL",
            "timeframe": "15m",
            "code": "MISSING_ARTIFACT",
        }
    ]
    assert any(item.get("code") == "MISSING_ARTIFACT" for item in report["warnings"])


def test_run_provider_health_broken_manifest_is_failure(monkeypatch, tmp_path):
    (tmp_path / "manifest_15m.json").write_text("{invalid-json", encoding="utf-8")

    monkeypatch.setattr(provider_health, "discover_provider_matrix", lambda: [])
    monkeypatch.setattr(provider_health, "discover_structure_source_status", _stub_structure_status)
    monkeypatch.setattr(provider_health.structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(provider_health.structure_artifact_json, "discover_normalized_contract_summary", _stub_contract_summary)
    monkeypatch.setattr(provider_health.structure_artifact_json, "has_artifact_for_symbol_timeframe", lambda symbol, timeframe: True)
    monkeypatch.setattr(provider_health, "_run_smoke_checks", _stub_smoke_ok)

    report = provider_health.run_provider_health_check(
        symbols=["AAPL"],
        timeframes=["15m"],
        checked_at=1_700_000_000.0,
    )

    assert report["overall_status"] == "fail"
    assert any(item.get("code") == "INVALID_MANIFEST_JSON" for item in report["failures"])


def test_smoke_detects_empty_structure_input_as_degradation(monkeypatch):
    monkeypatch.setattr(
        provider_health,
        "discover_composite_source_plan",
        lambda **kwargs: {
            "snapshot_structure": "artifact_json",
            "snapshot_meta": "symbol_timeframe",
            "snapshot_technical": "none",
            "snapshot_news": "none",
        },
    )
    monkeypatch.setattr(
        provider_health,
        "load_raw_structure_input",
        lambda symbol, timeframe, source: {
            "bos": [],
            "orderblocks": [],
            "fvg": [],
            "liquidity_sweeps": [],
        },
    )
    monkeypatch.setattr(
        provider_health,
        "load_raw_meta_input_composite",
        lambda symbol, timeframe, source: {"asof_ts": 995.0},
    )
    monkeypatch.setattr(
        provider_health,
        "build_snapshot_bundle_for_symbol_timeframe",
        lambda symbol, timeframe, source, generated_at: {
            "snapshot": {
                "symbol": symbol,
                "timeframe": timeframe,
                "generated_at": generated_at,
                "structure": {
                    "bos": [],
                    "orderblocks": [],
                    "fvg": [],
                    "liquidity_sweeps": [],
                },
            },
            "source_plan": {
                "snapshot_structure": "artifact_json",
                "snapshot_meta": "symbol_timeframe",
                "snapshot_technical": "none",
                "snapshot_news": "none",
            },
            "dashboard_payload": {},
            "pine_payload": {},
            "structure_context": {"meta": {"service": "stub"}},
        },
    )

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"],
        timeframes=["15m"],
        checked_at=1_000.0,
        stale_after_seconds=None,
    )

    assert smoke["results"][0]["status"] == "warn"
    assert any(item.get("code") == "EMPTY_STRUCTURE_INPUT" for item in smoke["degradations"])


def test_smoke_detects_bundle_without_context_bars_as_degradation(monkeypatch):
    monkeypatch.setattr(
        provider_health,
        "discover_composite_source_plan",
        lambda **kwargs: {
            "snapshot_structure": "artifact_json",
            "snapshot_meta": "symbol_timeframe",
            "snapshot_technical": "none",
            "snapshot_news": "none",
        },
    )
    monkeypatch.setattr(
        provider_health,
        "load_raw_structure_input",
        lambda symbol, timeframe, source: {
            "bos": [{"id": "bos:1", "time": 1.0, "price": 100.0, "kind": "BOS", "dir": "UP"}],
            "orderblocks": [],
            "fvg": [],
            "liquidity_sweeps": [],
        },
    )
    monkeypatch.setattr(
        provider_health,
        "load_raw_meta_input_composite",
        lambda symbol, timeframe, source: {
            "asof_ts": 995.0,
            "volume": {"value": {"regime": "NORMAL", "thin_fraction": 0.1}},
        },
    )
    monkeypatch.setattr(
        provider_health,
        "build_snapshot_bundle_for_symbol_timeframe",
        lambda symbol, timeframe, source, generated_at: {
            "snapshot": {
                "symbol": symbol,
                "timeframe": timeframe,
                "generated_at": generated_at,
                "structure": {
                    "bos": [{"id": "bos:1"}],
                    "orderblocks": [],
                    "fvg": [],
                    "liquidity_sweeps": [],
                },
            },
            "source_plan": {
                "snapshot_structure": "artifact_json",
                "snapshot_meta": "symbol_timeframe",
                "snapshot_technical": "none",
                "snapshot_news": "none",
            },
            "dashboard_payload": {},
            "pine_payload": {},
            "context_diagnostics": {
                "bars_available": False,
                "bar_count": 0,
                "reason": "empty_bars",
            },
        },
    )

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"],
        timeframes=["15m"],
        checked_at=1_000.0,
        stale_after_seconds=None,
    )

    assert smoke["results"][0]["status"] == "warn"
    assert any(item.get("code") == "EMPTY_CONTEXT_BARS" for item in smoke["degradations"])


def test_smoke_release_reference_ignores_empty_structure_from_structure_artifact(monkeypatch):
    import smc_integration.repo_sources as repo_sources_module

    monkeypatch.setattr(
        provider_health,
        "discover_composite_source_plan",
        lambda **kwargs: {
            "structure": "structure_artifact_json",
            "volume": "databento_watchlist_csv",
            "technical": "fmp_watchlist_json",
            "news": "live_news_snapshot_json",
        },
    )
    monkeypatch.setattr(
        provider_health,
        "load_raw_structure_input",
        lambda symbol, timeframe, source: {
            "bos": [],
            "orderblocks": [],
            "fvg": [],
            "liquidity_sweeps": [],
        },
    )
    monkeypatch.setattr(
        repo_sources_module,
        "load_raw_meta_input_composite_for_release_reference",
        lambda symbol, timeframe, source="auto", reference_time=None: {
            "asof_ts": 995.0,
            "meta_domain_diagnostics": {
                "volume": "synthetic_fallback",
                "volume_source": "synthetic_structure_artifact_meta",
                "volume_fallback_used": True,
                "volume_stale": False,
                "technical": "source_file_not_found",
                "technical_source": "fmp_watchlist_json",
                "technical_fallback_used": False,
                "technical_stale": False,
                "news": "present",
                "news_source": "live_news_snapshot_json",
                "news_fallback_used": False,
                "news_stale": False,
            },
        },
    )
    monkeypatch.setattr(
        provider_health,
        "build_snapshot_bundle_for_symbol_timeframe",
        lambda symbol, timeframe, source, generated_at, **kwargs: {
            "snapshot": {
                "symbol": symbol,
                "timeframe": timeframe,
                "generated_at": generated_at,
                "structure": {
                    "bos": [],
                    "orderblocks": [],
                    "fvg": [],
                    "liquidity_sweeps": [],
                },
            },
            "source_plan": {
                "structure": "structure_artifact_json",
                "volume": "databento_watchlist_csv",
                "technical": "fmp_watchlist_json",
                "news": "live_news_snapshot_json",
            },
            "dashboard_payload": {},
            "pine_payload": {},
            "structure_context": {"meta": {"service": "stub"}},
        },
    )

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"],
        timeframes=["15m"],
        checked_at=1_000.0,
        stale_after_seconds=None,
        allow_release_reference_meta_fallback=True,
    )

    assert smoke["results"][0]["status"] == "ok"
    assert smoke["results"][0]["structure_empty"] is True
    assert not any(item.get("code") == "EMPTY_STRUCTURE_INPUT" for item in smoke["warnings"])
    assert not any(item.get("code") == "EMPTY_STRUCTURE_INPUT" for item in smoke["degradations"])


def test_smoke_happy_path_is_ok(monkeypatch):
    monkeypatch.setattr(
        provider_health,
        "discover_composite_source_plan",
        lambda **kwargs: {
            "snapshot_structure": "artifact_json",
            "snapshot_meta": "symbol_timeframe",
            "snapshot_technical": "none",
            "snapshot_news": "none",
        },
    )
    monkeypatch.setattr(
        provider_health,
        "load_raw_structure_input",
        lambda symbol, timeframe, source: {
            "bos": [{"id": 1}],
            "orderblocks": [],
            "fvg": [],
            "liquidity_sweeps": [],
        },
    )
    monkeypatch.setattr(
        provider_health,
        "load_raw_meta_input_composite",
        lambda symbol, timeframe, source: {"asof_ts": 995.0},
    )
    monkeypatch.setattr(
        provider_health,
        "build_snapshot_bundle_for_symbol_timeframe",
        lambda symbol, timeframe, source, generated_at: {
            "snapshot": {
                "symbol": symbol,
                "timeframe": timeframe,
                "generated_at": generated_at,
                "structure": {
                    "bos": [{"id": 1}],
                    "orderblocks": [],
                    "fvg": [],
                    "liquidity_sweeps": [],
                },
            },
            "source_plan": {
                "snapshot_structure": "artifact_json",
                "snapshot_meta": "symbol_timeframe",
                "snapshot_technical": "none",
                "snapshot_news": "none",
            },
            "dashboard_payload": {},
            "pine_payload": {},
            "structure_context": {"meta": {"service": "stub"}},
        },
    )

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"],
        timeframes=["15m"],
        checked_at=1_000.0,
        stale_after_seconds=None,
    )

    assert smoke["results"][0]["status"] == "ok"
    assert smoke["warnings"] == []
    assert smoke["failures"] == []


def test_smoke_release_reference_fallback_skips_missing_optional_meta_domains(monkeypatch):
    import smc_integration.repo_sources as repo_sources_module

    monkeypatch.setattr(
        provider_health,
        "discover_composite_source_plan",
        lambda **kwargs: {
            "snapshot_structure": "artifact_json",
            "snapshot_meta": "symbol_timeframe",
            "snapshot_technical": "none",
            "snapshot_news": "none",
        },
    )
    monkeypatch.setattr(
        provider_health,
        "load_raw_structure_input",
        lambda symbol, timeframe, source: {
            "bos": [{"id": 1}],
            "orderblocks": [],
            "fvg": [],
            "liquidity_sweeps": [],
        },
    )
    monkeypatch.setattr(
        repo_sources_module,
        "load_raw_meta_input_composite_for_release_reference",
        lambda symbol, timeframe, source="auto", reference_time=None: {
            "asof_ts": 995.0,
            "meta_domain_diagnostics": {
                "volume": "synthetic_fallback",
                "volume_source": "synthetic_structure_artifact_meta",
                "volume_fallback_used": True,
                "volume_stale": False,
                "technical": "source_validation_error",
                "technical_source": "fmp_watchlist_json",
                "technical_fallback_used": False,
                "technical_stale": True,
                "news": "source_validation_error",
                "news_source": "benzinga_watchlist_json",
                "news_fallback_used": False,
                "news_stale": True,
            },
        },
    )
    monkeypatch.setattr(
        provider_health,
        "build_snapshot_bundle_for_symbol_timeframe",
        lambda symbol, timeframe, source, generated_at, **kwargs: {
            "snapshot": {
                "symbol": symbol,
                "timeframe": timeframe,
                "generated_at": generated_at,
                "structure": {
                    "bos": [{"id": 1}],
                    "orderblocks": [],
                    "fvg": [],
                    "liquidity_sweeps": [],
                },
            },
            "source_plan": {
                "snapshot_structure": "artifact_json",
                "snapshot_meta": "symbol_timeframe",
                "snapshot_technical": "none",
                "snapshot_news": "none",
            },
            "dashboard_payload": {},
            "pine_payload": {},
            "structure_context": {"meta": {"service": "stub"}},
        },
    )

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"],
        timeframes=["15m"],
        checked_at=1_000.0,
        stale_after_seconds=None,
        allow_release_reference_meta_fallback=True,
    )

    assert smoke["results"][0]["status"] == "ok"
    alerts = smoke["results"][0]["domain_alerts"]
    assert any(item.get("code") == "FALLBACK_META_VOLUME_DOMAIN" for item in alerts)
    assert any(item.get("code") == "META_TECHNICAL_DOMAIN_STATUS" and item.get("severity") == "info" for item in alerts)
    assert any(item.get("code") == "META_NEWS_DOMAIN_STATUS" and item.get("severity") == "info" for item in alerts)
    codes = {row["code"] for row in smoke["degradations"]}
    assert "STALE_META_TECHNICAL_DOMAIN" not in codes
    assert "STALE_META_NEWS_DOMAIN" not in codes
    assert smoke["failures"] == []


def test_smoke_surfaces_domain_alert_for_fallback_usage(monkeypatch):
    def _loader(symbol, timeframe, source):
        return {
            "asof_ts": 995.0,
            "meta_domain_diagnostics": {
                "volume": "present",
                "volume_source": "databento_watchlist_csv",
                "volume_fallback_used": False,
                "volume_stale": False,
                "technical": "present",
                "technical_source": "tradingview_watchlist_json",
                "technical_fallback_used": True,
                "technical_stale": False,
                "news": "present",
                "news_source": "benzinga_watchlist_json",
                "news_fallback_used": False,
                "news_stale": False,
            },
        }

    _patch_smoke_env(monkeypatch, _loader)

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"], timeframes=["15m"], checked_at=1_000.0, stale_after_seconds=None,
    )

    assert smoke["results"][0]["status"] == "ok"
    alerts = smoke["results"][0]["domain_alerts"]
    assert any(
        item.get("code") == "FALLBACK_META_TECHNICAL_DOMAIN" and item.get("severity") == "info"
        for item in alerts
    )
    assert not any(item.get("code") == "FALLBACK_META_TECHNICAL_DOMAIN" for item in smoke["warnings"])


def test_smoke_surfaces_domain_alert_for_benzinga_news_fallback(monkeypatch):
    def _loader(symbol, timeframe, source):
        return {
            "asof_ts": 995.0,
            "meta_domain_diagnostics": {
                "volume": "present",
                "volume_source": "databento_watchlist_csv",
                "volume_fallback_used": False,
                "volume_stale": False,
                "technical": "present",
                "technical_source": "fmp_watchlist_json",
                "technical_fallback_used": False,
                "technical_stale": False,
                "news": "present",
                "news_source": "benzinga_watchlist_json",
                "news_fallback_used": True,
                "news_stale": False,
            },
        }

    _patch_smoke_env(monkeypatch, _loader)

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"], timeframes=["15m"], checked_at=1_000.0, stale_after_seconds=None,
    )

    assert smoke["results"][0]["status"] == "ok"
    alerts = smoke["results"][0]["domain_alerts"]
    assert any(
        item.get("code") == "FALLBACK_META_NEWS_DOMAIN"
        and item.get("severity") == "info"
        and item.get("actual_source") == "benzinga_watchlist_json"
        for item in alerts
    )
    assert not any(item.get("code") == "FALLBACK_META_NEWS_DOMAIN" for item in smoke["warnings"])


def test_smoke_surfaces_domain_status_warning(monkeypatch):
    def _loader(symbol, timeframe, source):
        return {
            "asof_ts": 995.0,
            "meta_domain_diagnostics": {
                "volume": "present",
                "volume_source": "databento_watchlist_csv",
                "volume_fallback_used": False,
                "volume_stale": False,
                "technical": "source_file_not_found",
                "technical_source": "fmp_watchlist_json",
                "technical_fallback_used": False,
                "technical_stale": True,
                "news": "present",
                "news_source": "benzinga_watchlist_json",
                "news_fallback_used": False,
                "news_stale": False,
            },
        }

    _patch_smoke_env(monkeypatch, _loader)

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"], timeframes=["15m"], checked_at=1_000.0, stale_after_seconds=None,
    )

    assert smoke["results"][0]["status"] == "warn"
    alerts = smoke["results"][0]["domain_alerts"]
    assert any(
        item.get("code") == "META_TECHNICAL_DOMAIN_STATUS"
        and item.get("severity") == "warn"
        and item.get("status") == "source_file_not_found"
        for item in alerts
    )
    warning_codes = {item.get("code") for item in smoke["warnings"]}
    assert "META_TECHNICAL_DOMAIN_STATUS" in warning_codes


def test_smoke_emits_silent_domain_drop_alert(monkeypatch):
    def _loader(symbol, timeframe, source):
        return {
            "asof_ts": 995.0,
            "meta_domains_missing": ["technical"],
            "domain_drop_reasons": {"technical": "domain_fields_incomplete"},
            "domain_drop_providers": {"technical": "fmp_watchlist_json"},
            "meta_domain_diagnostics": {
                "volume": "present",
                "volume_source": "databento_watchlist_csv",
                "volume_fallback_used": False,
                "volume_stale": False,
                "technical": "domain_fields_incomplete",
                "technical_source": "fmp_watchlist_json",
                "technical_fallback_used": False,
                "technical_stale": False,
                "news": "present",
                "news_source": "benzinga_watchlist_json",
                "news_fallback_used": False,
                "news_stale": False,
            },
        }

    _patch_smoke_env(monkeypatch, _loader)

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"], timeframes=["15m"], checked_at=1_000.0, stale_after_seconds=None,
    )

    alerts = smoke["results"][0]["domain_alerts"]
    assert any(
        item.get("code") == "DOMAIN_DROP_DURING_BUILD"
        and item.get("severity") == "warn"
        and item.get("domain") == "technical"
        and item.get("drop_provider") == "fmp_watchlist_json"
        for item in alerts
    )
    assert any(
        item.get("code") == "SILENT_DOMAIN_DROP_TECHNICAL"
        and item.get("severity") == "warn"
        and item.get("status") == "domain_fields_incomplete"
        for item in alerts
    )
    assert any(
        item.get("code") == "DOMAIN_DROPPED_TECHNICAL"
        and item.get("severity") == "info"
        and item.get("status") == "domain_fields_incomplete"
        for item in alerts
    )
    assert not any(item.get("code") == "META_TECHNICAL_DOMAIN_STATUS" for item in alerts)
    warning_codes = {item.get("code") for item in smoke["warnings"]}
    assert "DOMAIN_DROP_DURING_BUILD" in warning_codes
    assert "SILENT_DOMAIN_DROP_TECHNICAL" in warning_codes
    assert "DOMAIN_DROPPED_TECHNICAL" not in warning_codes


def test_smoke_avoids_duplicate_drop_alert_when_domain_is_also_stale(monkeypatch):
    def _loader(symbol, timeframe, source):
        return {
            "asof_ts": 995.0,
            "meta_domains_missing": ["technical"],
            "domain_drop_reasons": {"technical": "source_file_not_found"},
            "meta_domain_diagnostics": {
                "volume": "present",
                "volume_source": "databento_watchlist_csv",
                "volume_fallback_used": False,
                "volume_stale": False,
                "technical": "source_file_not_found",
                "technical_source": "fmp_watchlist_json",
                "technical_fallback_used": False,
                "technical_stale": True,
                "news": "present",
                "news_source": "benzinga_watchlist_json",
                "news_fallback_used": False,
                "news_stale": False,
            },
        }

    _patch_smoke_env(monkeypatch, _loader)

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"], timeframes=["15m"], checked_at=1_000.0, stale_after_seconds=None,
    )

    alerts = smoke["results"][0].get("domain_alerts", [])
    assert not any(item.get("code") == "SILENT_DOMAIN_DROP_TECHNICAL" for item in alerts)
    assert not any(item.get("code") == "META_TECHNICAL_DOMAIN_STATUS" for item in alerts)
    degradation_codes = {item.get("code") for item in smoke["degradations"]}
    assert "STALE_META_TECHNICAL_DOMAIN" in degradation_codes


def test_smoke_records_domain_visibility_score_for_full_coverage(monkeypatch):
    def _loader(symbol, timeframe, source):
        return {
            "asof_ts": 995.0,
            "meta_domains_present": ["volume", "technical", "news"],
            "meta_domain_diagnostics": {
                "volume": "present",
                "volume_source": "databento_watchlist_csv",
                "volume_fallback_used": False,
                "volume_stale": False,
                "technical": "present",
                "technical_source": "fmp_watchlist_json",
                "technical_fallback_used": False,
                "technical_stale": False,
                "news": "present",
                "news_source": "benzinga_watchlist_json",
                "news_fallback_used": False,
                "news_stale": False,
            },
        }

    _patch_smoke_env(monkeypatch, _loader)

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"], timeframes=["15m"], checked_at=1_000.0, stale_after_seconds=None,
    )

    row = smoke["results"][0]
    assert row["domain_visibility_score"] == 1.0
    assert row["domain_visibility_complete"] is True
    assert row["domain_visibility_domains_present"] == ["news", "structure", "technical", "volume"]
    assert row["domain_visibility_domains_missing"] == []


def test_smoke_records_domain_visibility_score_for_partial_coverage(monkeypatch):
    def _loader(symbol, timeframe, source):
        return {
            "asof_ts": 995.0,
            "meta_domains_present": ["volume"],
            "meta_domains_missing": ["technical", "news"],
            "meta_domain_diagnostics": {
                "volume": "present",
                "volume_source": "databento_watchlist_csv",
                "volume_fallback_used": False,
                "volume_stale": False,
                "technical": "domain_fields_incomplete",
                "technical_source": "fmp_watchlist_json",
                "technical_fallback_used": False,
                "technical_stale": False,
                "news": "source_file_not_found",
                "news_source": "benzinga_watchlist_json",
                "news_fallback_used": False,
                "news_stale": False,
            },
        }

    _patch_smoke_env(monkeypatch, _loader)

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"], timeframes=["15m"], checked_at=1_000.0, stale_after_seconds=None,
    )

    row = smoke["results"][0]
    assert row["domain_visibility_score"] == 0.5
    assert row["domain_visibility_complete"] is False
    assert row["domain_visibility_domains_present"] == ["structure", "volume"]
    assert row["domain_visibility_domains_missing"] == ["technical", "news"]


def test_smoke_unknown_volume_regime_is_degradation(monkeypatch):
    def _loader(symbol, timeframe, source):
        return {
            "asof_ts": 995.0,
            "volume": {
                "value": {"regime": "UNKNOWN", "thin_fraction": None},
                "asof_ts": 995.0,
                "stale": False,
            },
            "meta_domain_diagnostics": {
                "volume": "present",
                "volume_source": "databento_watchlist_csv",
                "volume_fallback_used": False,
                "volume_stale": False,
                "technical": "present",
                "technical_source": "fmp_watchlist_json",
                "technical_fallback_used": False,
                "technical_stale": False,
                "news": "present",
                "news_source": "benzinga_watchlist_json",
                "news_fallback_used": False,
                "news_stale": False,
            },
        }

    _patch_smoke_env(monkeypatch, _loader)

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"], timeframes=["15m"], checked_at=1_000.0, stale_after_seconds=None,
    )

    degradation_codes = {item.get("code") for item in smoke["degradations"]}
    failure_codes = {item.get("code") for item in smoke["failures"]}
    assert "UNKNOWN_VOLUME_REGIME" in degradation_codes
    assert "UNKNOWN_VOLUME_REGIME" not in failure_codes


def test_smoke_bundle_build_error_is_failure(monkeypatch):
    monkeypatch.setattr(
        provider_health,
        "discover_composite_source_plan",
        lambda **kwargs: {
            "snapshot_structure": "artifact_json",
            "snapshot_meta": "symbol_timeframe",
            "snapshot_technical": "none",
            "snapshot_news": "none",
        },
    )
    monkeypatch.setattr(
        provider_health,
        "load_raw_structure_input",
        lambda symbol, timeframe, source: {
            "bos": [{"id": 1}],
            "orderblocks": [],
            "fvg": [],
            "liquidity_sweeps": [],
        },
    )
    monkeypatch.setattr(
        provider_health,
        "load_raw_meta_input_composite",
        lambda symbol, timeframe, source: {"asof_ts": 995.0},
    )

    def _raise_bundle(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(provider_health, "build_snapshot_bundle_for_symbol_timeframe", _raise_bundle)

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"],
        timeframes=["15m"],
        checked_at=1_000.0,
        stale_after_seconds=None,
    )

    assert smoke["results"][0]["status"] == "fail"
    assert any(item.get("code") == "BUNDLE_BUILD_FAILED" for item in smoke["failures"])


def test_smoke_marks_stale_meta_with_threshold(monkeypatch):
    monkeypatch.setattr(
        provider_health,
        "discover_composite_source_plan",
        lambda **kwargs: {
            "snapshot_structure": "artifact_json",
            "snapshot_meta": "symbol_timeframe",
            "snapshot_technical": "none",
            "snapshot_news": "none",
        },
    )
    monkeypatch.setattr(
        provider_health,
        "load_raw_structure_input",
        lambda symbol, timeframe, source: {
            "bos": [{"id": 1}],
            "orderblocks": [],
            "fvg": [],
            "liquidity_sweeps": [],
        },
    )
    monkeypatch.setattr(
        provider_health,
        "load_raw_meta_input_composite",
        lambda symbol, timeframe, source: {"asof_ts": 10.0},
    )
    monkeypatch.setattr(
        provider_health,
        "build_snapshot_bundle_for_symbol_timeframe",
        lambda symbol, timeframe, source, generated_at: {
            "snapshot": {
                "symbol": symbol,
                "timeframe": timeframe,
                "generated_at": generated_at,
                "structure": {
                    "bos": [{"id": 1}],
                    "orderblocks": [],
                    "fvg": [],
                    "liquidity_sweeps": [],
                },
            },
            "source_plan": {
                "snapshot_structure": "artifact_json",
                "snapshot_meta": "symbol_timeframe",
                "snapshot_technical": "none",
                "snapshot_news": "none",
            },
            "dashboard_payload": {},
            "pine_payload": {},
        },
    )

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"],
        timeframes=["15m"],
        checked_at=100.0,
        stale_after_seconds=30,
    )

    assert smoke["results"][0]["status"] == "warn"
    assert any(item.get("code") == "STALE_META_ASOF_TS" for item in smoke["degradations"])


def test_provider_health_report_is_machine_readable_and_deterministic(monkeypatch, tmp_path):
    (tmp_path / "manifest_15m.json").write_text(
        json.dumps({"generated_at": 50.0, "timeframe": "15m", "symbols": ["AAPL"]}),
        encoding="utf-8",
    )

    monkeypatch.setattr(provider_health, "discover_provider_matrix", lambda: [])
    monkeypatch.setattr(provider_health, "discover_structure_source_status", _stub_structure_status)
    monkeypatch.setattr(provider_health.structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(provider_health.structure_artifact_json, "discover_normalized_contract_summary", _stub_contract_summary)
    monkeypatch.setattr(provider_health.structure_artifact_json, "has_artifact_for_symbol_timeframe", lambda symbol, timeframe: True)
    monkeypatch.setattr(provider_health, "_run_smoke_checks", _stub_smoke_ok)

    report_a = provider_health.run_provider_health_check(
        symbols=["AAPL"],
        timeframes=["15m"],
        checked_at=100.0,
        stale_after_seconds=1000,
    )
    report_b = provider_health.run_provider_health_check(
        symbols=["AAPL"],
        timeframes=["15m"],
        checked_at=100.0,
        stale_after_seconds=1000,
    )

    required_keys = {
        "provider_domain_results",
        "structure_source_status",
        "artifact_health",
        "missing_artifacts",
        "stale_artifacts",
        "smoke_test_results",
        "domain_visibility_score",
        "domain_visibility_full_coverage_ratio",
        "domain_visibility",
        "warnings",
        "failures",
        "degradations_detected",
    }
    assert required_keys.issubset(report_a.keys())
    assert json.dumps(report_a, sort_keys=True) == json.dumps(report_b, sort_keys=True)

    # WP-R13: smoke_bundles must NOT appear in the default report to
    # prevent accidental serialisation of large bundle payloads (and
    # tuple-key JSON crashes) in callers that don't opt in.
    assert "smoke_bundles" not in report_a, (
        "smoke_bundles leaked into default report — "
        "only include_smoke_bundles=True should add it"
    )


def test_strict_release_policy_promotes_missing_artifact_to_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(provider_health, "discover_provider_matrix", lambda: [])
    monkeypatch.setattr(provider_health, "discover_structure_source_status", _stub_structure_status)
    monkeypatch.setattr(provider_health.structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(provider_health.structure_artifact_json, "discover_normalized_contract_summary", _stub_contract_summary)
    monkeypatch.setattr(provider_health.structure_artifact_json, "has_artifact_for_symbol_timeframe", lambda symbol, timeframe: False)
    monkeypatch.setattr(provider_health, "_run_smoke_checks", _stub_smoke_ok)

    report = provider_health.run_provider_health_check(
        symbols=["AAPL"],
        timeframes=["15m"],
        checked_at=1_700_000_000.0,
        stale_after_seconds=60,
        strict_release_policy=True,
    )

    assert report["overall_status"] == "fail"
    assert any(item.get("code") == "MISSING_ARTIFACT" for item in report["failures"])
    assert any(item.get("promoted_by") == "release_strict_policy" for item in report["failures"])


def test_strict_release_policy_promotes_stale_manifest_to_failure(monkeypatch, tmp_path):
    manifest_path = tmp_path / "manifest_15m.json"
    manifest_path.write_text(
        json.dumps({"generated_at": 0.0, "timeframe": "15m", "symbols": ["AAPL"]}),
        encoding="utf-8",
    )
    os.utime(manifest_path, (0.0, 0.0))

    monkeypatch.setattr(provider_health, "discover_provider_matrix", lambda: [])
    monkeypatch.setattr(provider_health, "discover_structure_source_status", _stub_structure_status)
    monkeypatch.setattr(provider_health.structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(provider_health.structure_artifact_json, "discover_normalized_contract_summary", _stub_contract_summary)
    monkeypatch.setattr(provider_health.structure_artifact_json, "has_artifact_for_symbol_timeframe", lambda symbol, timeframe: True)
    monkeypatch.setattr(provider_health, "_run_smoke_checks", _stub_smoke_ok)

    report = provider_health.run_provider_health_check(
        symbols=["AAPL"],
        timeframes=["15m"],
        checked_at=100.0,
        stale_after_seconds=10,
        strict_release_policy=True,
    )

    assert report["overall_status"] == "fail"
    assert any(item.get("code") in {"STALE_MANIFEST_GENERATED_AT", "STALE_MANIFEST_FILE_MTIME"} for item in report["failures"])


def test_strict_release_policy_fails_when_manifest_timestamp_missing(monkeypatch, tmp_path):
    manifest_path = tmp_path / "manifest_15m.json"
    manifest_path.write_text(
        json.dumps({"timeframe": "15m", "symbols": ["AAPL"]}),
        encoding="utf-8",
    )

    monkeypatch.setattr(provider_health, "discover_provider_matrix", lambda: [])
    monkeypatch.setattr(provider_health, "discover_structure_source_status", _stub_structure_status)
    monkeypatch.setattr(provider_health.structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(provider_health.structure_artifact_json, "discover_normalized_contract_summary", _stub_contract_summary)
    monkeypatch.setattr(provider_health.structure_artifact_json, "has_artifact_for_symbol_timeframe", lambda symbol, timeframe: True)
    monkeypatch.setattr(provider_health, "_run_smoke_checks", _stub_smoke_ok)

    report = provider_health.run_provider_health_check(
        symbols=["AAPL"],
        timeframes=["15m"],
        checked_at=100.0,
        stale_after_seconds=3600,
        strict_release_policy=True,
    )

    assert report["overall_status"] == "fail"
    assert any(item.get("code") == "MISSING_MANIFEST_GENERATED_AT" for item in report["failures"])


def test_strict_release_policy_does_not_promote_empty_context_bars_to_failure(monkeypatch, tmp_path):
    manifest_path = tmp_path / "manifest_15m.json"
    manifest_path.write_text(
        json.dumps({"generated_at": 95.0, "timeframe": "15m", "symbols": ["AAPL"]}),
        encoding="utf-8",
    )
    os.utime(manifest_path, (95.0, 95.0))

    monkeypatch.setattr(provider_health, "discover_provider_matrix", lambda: [])
    monkeypatch.setattr(provider_health, "discover_structure_source_status", _stub_structure_status)
    monkeypatch.setattr(provider_health.structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(provider_health.structure_artifact_json, "discover_normalized_contract_summary", _stub_contract_summary)
    monkeypatch.setattr(provider_health.structure_artifact_json, "has_artifact_for_symbol_timeframe", lambda symbol, timeframe: True)
    monkeypatch.setattr(
        provider_health,
        "_run_smoke_checks",
        lambda **kwargs: {
            "results": [],
            "warnings": [],
            "failures": [],
            "degradations": [{"code": "EMPTY_CONTEXT_BARS", "symbol": "AAPL", "timeframe": "15m"}],
            "domain_alerts": [],
        },
    )

    report = provider_health.run_provider_health_check(
        symbols=["AAPL"],
        timeframes=["15m"],
        checked_at=100.0,
        stale_after_seconds=3600,
        strict_release_policy=True,
    )

    # EMPTY_CONTEXT_BARS no longer promoted to failure — stays as degradation
    assert report["overall_status"] == "warn"
    assert not any(item.get("code") == "EMPTY_CONTEXT_BARS" for item in report.get("failures", []))
    assert any(item.get("code") == "EMPTY_CONTEXT_BARS" for item in report["degradations_detected"])


def test_strict_release_policy_passes_on_fresh_reference_artifact(monkeypatch, tmp_path):
    checked_at = 100.0
    manifest_path = tmp_path / "manifest_15m.json"
    manifest_path.write_text(
        json.dumps({"generated_at": 95.0, "timeframe": "15m", "symbols": ["AAPL"]}),
        encoding="utf-8",
    )
    os.utime(manifest_path, (checked_at, checked_at))

    monkeypatch.setattr(provider_health, "discover_provider_matrix", lambda: [])
    monkeypatch.setattr(provider_health, "discover_structure_source_status", _stub_structure_status)
    monkeypatch.setattr(provider_health.structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(provider_health.structure_artifact_json, "discover_normalized_contract_summary", _stub_contract_summary)
    monkeypatch.setattr(provider_health.structure_artifact_json, "has_artifact_for_symbol_timeframe", lambda symbol, timeframe: True)
    monkeypatch.setattr(provider_health, "_run_smoke_checks", _stub_smoke_ok)

    report = provider_health.run_provider_health_check(
        symbols=["AAPL"],
        timeframes=["15m"],
        checked_at=checked_at,
        stale_after_seconds=30,
        strict_release_policy=True,
    )

    assert report["overall_status"] == "ok"
    assert report["failures"] == []


# ---------------------------------------------------------------------------
# Per-domain staleness (technical / news) via meta_domain_diagnostics
# ---------------------------------------------------------------------------

def _stub_meta_with_domain_diagnostics(*, technical_stale: bool, news_stale: bool):
    """Return a load_raw_meta_input_composite stub with controllable domain staleness."""
    def _loader(symbol, timeframe, source):
        return {
            "asof_ts": 995.0,
            "meta_domain_diagnostics": {
                "technical_stale": technical_stale,
                "technical_age_hours": 72.0 if technical_stale else 1.0,
                "technical_asof_ts": 100.0 if technical_stale else 990.0,
                "news_stale": news_stale,
                "news_age_hours": 96.0 if news_stale else 2.0,
                "news_asof_ts": 50.0 if news_stale else 988.0,
            },
        }
    return _loader


def _stub_smoke_source_plan(**kwargs):
    return {
        "snapshot_structure": "artifact_json",
        "snapshot_meta": "symbol_timeframe",
        "snapshot_technical": "none",
        "snapshot_news": "none",
    }


def _stub_smoke_structure(symbol, timeframe, source):
    return {"bos": [{"id": 1}], "orderblocks": [], "fvg": [], "liquidity_sweeps": []}


def _stub_smoke_bundle(symbol, timeframe, source, generated_at):
    return {
        "snapshot": {
            "symbol": symbol,
            "timeframe": timeframe,
            "generated_at": generated_at,
            "structure": {"bos": [{"id": 1}], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
        },
        "source_plan": _stub_smoke_source_plan(),
        "dashboard_payload": {},
        "pine_payload": {},
    }


def _patch_smoke_env(monkeypatch, meta_loader):
    monkeypatch.setattr(provider_health, "discover_composite_source_plan", _stub_smoke_source_plan)
    monkeypatch.setattr(provider_health, "load_raw_structure_input", _stub_smoke_structure)
    monkeypatch.setattr(provider_health, "load_raw_meta_input_composite", meta_loader)
    monkeypatch.setattr(provider_health, "build_snapshot_bundle_for_symbol_timeframe", _stub_smoke_bundle)


def test_smoke_detects_stale_technical_domain(monkeypatch):
    _patch_smoke_env(monkeypatch, _stub_meta_with_domain_diagnostics(technical_stale=True, news_stale=False))

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"], timeframes=["15m"], checked_at=1_000.0, stale_after_seconds=None,
    )

    codes = [r["code"] for r in smoke["degradations"]]
    assert "STALE_META_TECHNICAL_DOMAIN" in codes
    assert "STALE_META_NEWS_DOMAIN" not in codes

    # meta_domain_diagnostics should be surfaced in the smoke result row
    assert "meta_domain_diagnostics" in smoke["results"][0]
    assert smoke["results"][0]["meta_domain_diagnostics"]["technical_stale"] is True


def test_smoke_detects_stale_news_domain(monkeypatch):
    _patch_smoke_env(monkeypatch, _stub_meta_with_domain_diagnostics(technical_stale=False, news_stale=True))

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"], timeframes=["15m"], checked_at=1_000.0, stale_after_seconds=None,
    )

    codes = [r["code"] for r in smoke["degradations"]]
    assert "STALE_META_NEWS_DOMAIN" in codes
    assert "STALE_META_TECHNICAL_DOMAIN" not in codes


def test_smoke_fresh_domains_produce_no_stale_signal(monkeypatch):
    _patch_smoke_env(monkeypatch, _stub_meta_with_domain_diagnostics(technical_stale=False, news_stale=False))

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"], timeframes=["15m"], checked_at=1_000.0, stale_after_seconds=None,
    )

    domain_codes = {"STALE_META_TECHNICAL_DOMAIN", "STALE_META_NEWS_DOMAIN"}
    assert not domain_codes.intersection(r["code"] for r in smoke["degradations"])
    assert smoke["results"][0]["status"] == "ok"


def test_smoke_missing_domain_meta_treated_as_stale(monkeypatch):
    """When meta_domain_diagnostics marks a domain stale because meta was None."""
    def _loader(symbol, timeframe, source):
        return {
            "asof_ts": 995.0,
            "meta_domain_diagnostics": {
                "technical_stale": True,
                "technical_age_hours": None,
                "technical_asof_ts": None,
                "news_stale": True,
                "news_age_hours": None,
                "news_asof_ts": None,
            },
        }

    _patch_smoke_env(monkeypatch, _loader)

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"], timeframes=["15m"], checked_at=1_000.0, stale_after_seconds=None,
    )

    codes = [r["code"] for r in smoke["degradations"]]
    assert "STALE_META_TECHNICAL_DOMAIN" in codes
    assert "STALE_META_NEWS_DOMAIN" in codes
    # age_hours should NOT be in the record when it was None
    for row in smoke["degradations"]:
        if row["code"] in ("STALE_META_TECHNICAL_DOMAIN", "STALE_META_NEWS_DOMAIN"):
            assert "age_hours" not in row


def test_strict_release_promotes_stale_domain_to_failure(monkeypatch, tmp_path):
    checked_at = 100.0
    manifest_path = tmp_path / "manifest_15m.json"
    manifest_path.write_text(
        json.dumps({"generated_at": 95.0, "timeframe": "15m", "symbols": ["AAPL"]}),
        encoding="utf-8",
    )
    import os
    os.utime(manifest_path, (checked_at, checked_at))

    monkeypatch.setattr(provider_health, "discover_provider_matrix", lambda: [])
    monkeypatch.setattr(provider_health, "discover_structure_source_status", _stub_structure_status)
    monkeypatch.setattr(provider_health.structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(provider_health.structure_artifact_json, "discover_normalized_contract_summary", _stub_contract_summary)
    monkeypatch.setattr(provider_health.structure_artifact_json, "has_artifact_for_symbol_timeframe", lambda symbol, timeframe: True)

    # Smoke returns stale technical domain as degradation
    def _stale_smoke(**_):
        return {
            "results": [{"symbol": "AAPL", "timeframe": "15m", "status": "warn"}],
            "warnings": [{"code": "STALE_META_TECHNICAL_DOMAIN", "symbol": "AAPL", "timeframe": "15m"}],
            "failures": [],
            "degradations": [{"code": "STALE_META_TECHNICAL_DOMAIN", "symbol": "AAPL", "timeframe": "15m"}],
        }

    monkeypatch.setattr(provider_health, "_run_smoke_checks", _stale_smoke)

    report = provider_health.run_provider_health_check(
        symbols=["AAPL"],
        timeframes=["15m"],
        checked_at=checked_at,
        stale_after_seconds=3600,
        strict_release_policy=True,
    )

    assert report["overall_status"] == "fail"
    promoted = [f for f in report["failures"] if f.get("code") == "STALE_META_TECHNICAL_DOMAIN"]
    assert len(promoted) == 1
    assert promoted[0].get("promoted_by") == "release_strict_policy"


# ---------------------------------------------------------------------------
# Volume domain stale in health / gate path
# ---------------------------------------------------------------------------

def test_smoke_detects_stale_volume_domain(monkeypatch):
    def _loader(symbol, timeframe, source):
        return {
            "asof_ts": 995.0,
            "meta_domain_diagnostics": {
                "volume_stale": True, "volume_age_hours": 96.0, "volume_asof_ts": 50.0,
                "technical_stale": False, "technical_age_hours": 1.0, "technical_asof_ts": 990.0,
                "news_stale": False, "news_age_hours": 2.0, "news_asof_ts": 988.0,
            },
        }
    _patch_smoke_env(monkeypatch, _loader)

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"], timeframes=["15m"], checked_at=1_000.0, stale_after_seconds=None,
    )

    codes = [r["code"] for r in smoke["degradations"]]
    assert "STALE_META_VOLUME_DOMAIN" in codes
    assert "STALE_META_TECHNICAL_DOMAIN" not in codes
    assert "STALE_META_NEWS_DOMAIN" not in codes


def test_smoke_fresh_volume_produces_no_stale_signal(monkeypatch):
    def _loader(symbol, timeframe, source):
        return {
            "asof_ts": 995.0,
            "meta_domain_diagnostics": {
                "volume_stale": False, "volume_age_hours": 1.0, "volume_asof_ts": 990.0,
                "technical_stale": False, "technical_age_hours": 1.0, "technical_asof_ts": 990.0,
                "news_stale": False, "news_age_hours": 2.0, "news_asof_ts": 988.0,
            },
        }
    _patch_smoke_env(monkeypatch, _loader)

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"], timeframes=["15m"], checked_at=1_000.0, stale_after_seconds=None,
    )

    domain_codes = {"STALE_META_VOLUME_DOMAIN", "STALE_META_TECHNICAL_DOMAIN", "STALE_META_NEWS_DOMAIN"}
    assert not domain_codes.intersection(r["code"] for r in smoke["degradations"])


def test_strict_release_promotes_stale_volume_to_failure(monkeypatch, tmp_path):
    checked_at = 100.0
    manifest_path = tmp_path / "manifest_15m.json"
    manifest_path.write_text(
        json.dumps({"generated_at": 95.0, "timeframe": "15m", "symbols": ["AAPL"]}),
        encoding="utf-8",
    )
    import os
    os.utime(manifest_path, (checked_at, checked_at))

    monkeypatch.setattr(provider_health, "discover_provider_matrix", lambda: [])
    monkeypatch.setattr(provider_health, "discover_structure_source_status", _stub_structure_status)
    monkeypatch.setattr(provider_health.structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", tmp_path)
    monkeypatch.setattr(provider_health.structure_artifact_json, "discover_normalized_contract_summary", _stub_contract_summary)
    monkeypatch.setattr(provider_health.structure_artifact_json, "has_artifact_for_symbol_timeframe", lambda symbol, timeframe: True)

    def _stale_smoke(**_):
        return {
            "results": [{"symbol": "AAPL", "timeframe": "15m", "status": "warn"}],
            "warnings": [{"code": "STALE_META_VOLUME_DOMAIN", "symbol": "AAPL", "timeframe": "15m"}],
            "failures": [],
            "degradations": [{"code": "STALE_META_VOLUME_DOMAIN", "symbol": "AAPL", "timeframe": "15m"}],
        }

    monkeypatch.setattr(provider_health, "_run_smoke_checks", _stale_smoke)

    report = provider_health.run_provider_health_check(
        symbols=["AAPL"],
        timeframes=["15m"],
        checked_at=checked_at,
        stale_after_seconds=3600,
        strict_release_policy=True,
    )

    assert report["overall_status"] == "fail"
    promoted = [f for f in report["failures"] if f.get("code") == "STALE_META_VOLUME_DOMAIN"]
    assert len(promoted) == 1
    assert promoted[0].get("promoted_by") == "release_strict_policy"


def test_smoke_volume_staleness_skipped_with_release_fallback(monkeypatch):
    """When allow_release_reference_meta_fallback is True and volume domain is
    not present, STALE_META_VOLUME_DOMAIN must NOT be emitted (F1)."""
    def _loader(symbol, timeframe, source):
        return {
            "asof_ts": 995.0,
            "meta_domain_diagnostics": {
                # volume is missing (not "present") AND marked stale.
                # With fallback enabled this should be silently skipped.
                "volume": "missing",
                "volume_stale": True, "volume_age_hours": 96.0, "volume_asof_ts": None,
                "technical": "missing",
                "technical_stale": True, "technical_age_hours": 72.0, "technical_asof_ts": None,
                "news": "missing",
                "news_stale": True, "news_age_hours": 120.0, "news_asof_ts": None,
            },
        }
    _patch_smoke_env(monkeypatch, _loader)

    smoke = provider_health._run_smoke_checks(
        symbols=["AAPL"], timeframes=["15m"], checked_at=1_000.0,
        stale_after_seconds=None,
        allow_release_reference_meta_fallback=True,
    )

    emitted_codes = {r["code"] for r in smoke["degradations"]}
    assert "STALE_META_VOLUME_DOMAIN" not in emitted_codes
    assert "STALE_META_TECHNICAL_DOMAIN" not in emitted_codes
    assert "STALE_META_NEWS_DOMAIN" not in emitted_codes


# ---------------------------------------------------------------------------
# F-04 — Provider Failure Semantics
# ---------------------------------------------------------------------------


class TestFailureSemantics:
    def test_resolve_known_structure_missing(self) -> None:
        sem = provider_health.resolve_failure_action("structure", "missing")
        assert sem.action == provider_health.FailureAction.HARD_DEGRADE
        assert sem.affects_entry is True

    def test_resolve_known_volume_stale(self) -> None:
        sem = provider_health.resolve_failure_action("volume", "stale")
        assert sem.action == provider_health.FailureAction.ADVISORY
        assert sem.max_tolerable_hours == 48

    def test_resolve_known_news_fallback(self) -> None:
        sem = provider_health.resolve_failure_action("news", "fallback")
        assert sem.action == provider_health.FailureAction.FALLBACK
        assert sem.affects_entry is False

    def test_resolve_unknown_defaults_to_advisory(self) -> None:
        sem = provider_health.resolve_failure_action("unknown_domain", "cosmic_ray")
        assert sem.action == provider_health.FailureAction.ADVISORY
        assert sem.affects_entry is False

    def test_classify_domain_alerts_enriches_records(self) -> None:
        alerts = [
            {"domain": "volume", "code": "STALE_META_VOLUME_DOMAIN", "severity": "warn"},
            {"domain": "news", "code": "FALLBACK_META_NEWS_DOMAIN", "severity": "info"},
        ]
        enriched = provider_health.classify_domain_alerts_to_failure_actions(alerts)
        assert len(enriched) == 2
        assert enriched[0]["failure_action"] == "advisory"
        assert enriched[1]["failure_action"] == "fallback"

    def test_classify_domain_alerts_dropped_code(self) -> None:
        alerts = [{"domain": "news", "code": "DROPPED_NEWS_DOMAIN", "severity": "warn"}]
        enriched = provider_health.classify_domain_alerts_to_failure_actions(alerts)
        assert enriched[0]["failure_action"] == "fallback"  # news/missing -> FALLBACK

    def test_classify_domain_alerts_invalid_code(self) -> None:
        alerts = [{"domain": "structure", "code": "INVALID_STRUCTURE_ARTIFACT", "severity": "error"}]
        enriched = provider_health.classify_domain_alerts_to_failure_actions(alerts)
        assert enriched[0]["failure_action"] == "hard_degrade"  # structure/invalid -> HARD_DEGRADE

    def test_classify_domain_alerts_unknown_code(self) -> None:
        alerts = [{"domain": "volume", "code": "COSMIC_RAY_HIT", "severity": "info"}]
        enriched = provider_health.classify_domain_alerts_to_failure_actions(alerts)
        assert enriched[0]["failure_action"] == "advisory"  # unknown -> ADVISORY

    def test_classify_domain_alerts_silent_domain_drop(self) -> None:
        alerts = [{"domain": "technical", "code": "SILENT_DOMAIN_DROP_TECH", "severity": "warn"}]
        enriched = provider_health.classify_domain_alerts_to_failure_actions(alerts)
        assert enriched[0]["failure_action"] == "fallback"  # technical/missing -> FALLBACK

    def test_worst_failure_action_picks_most_severe(self) -> None:
        enriched = [
            {"failure_action": "fallback"},
            {"failure_action": "advisory"},
            {"failure_action": "hard_degrade"},
        ]
        assert provider_health.worst_failure_action(enriched) == provider_health.FailureAction.HARD_DEGRADE

    def test_worst_failure_action_fallback_only(self) -> None:
        enriched = [{"failure_action": "fallback"}]
        assert provider_health.worst_failure_action(enriched) == provider_health.FailureAction.FALLBACK

    def test_worst_failure_action_ignores_invalid_values(self) -> None:
        enriched = [
            {"failure_action": "fallback"},
            {"failure_action": "not_a_real_action"},
        ]
        assert provider_health.worst_failure_action(enriched) == provider_health.FailureAction.FALLBACK

    def test_worst_failure_action_empty_string_ignored(self) -> None:
        enriched = [{"failure_action": ""}]
        assert provider_health.worst_failure_action(enriched) == provider_health.FailureAction.FALLBACK

    def test_failure_semantics_matrix_covers_all_domains(self) -> None:
        domains = {fs.domain for fs in provider_health._FAILURE_SEMANTICS_MATRIX}
        assert domains == {"structure", "volume", "technical", "news"}

    def test_failure_action_enum_has_four_values(self) -> None:
        assert len(provider_health.FailureAction) == 4


class TestSmokeCheckBundleSkipFastPath:
    """Verify the fast-path: when all meta domains are absent the bundle
    build is skipped and ``bundle_skipped`` is set on the result row."""

    def test_all_domains_absent_skips_bundle(self, monkeypatch) -> None:
        """When meta_domain_diagnostics shows all domains absent, the
        expensive bundle build must be skipped."""
        bundle_calls: list[tuple] = []

        monkeypatch.setattr(
            provider_health, "discover_composite_source_plan",
            lambda **kwargs: {"structure": "s", "volume": "v", "technical": "t", "news": "n"},
        )
        monkeypatch.setattr(
            provider_health, "load_raw_structure_input",
            lambda symbol, timeframe, source: {
                "bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": [],
            },
        )
        monkeypatch.setattr(
            provider_health, "load_raw_meta_input_composite",
            lambda symbol, timeframe, source: {
                "asof_ts": 995.0,
                "meta_domain_diagnostics": {
                    "volume": "source_file_not_found",
                    "volume_source": "databento_watchlist_csv",
                    "volume_fallback_used": False,
                    "volume_stale": False,
                    "technical": "source_file_not_found",
                    "technical_source": "fmp_watchlist_json",
                    "technical_fallback_used": False,
                    "technical_stale": False,
                    "news": "source_file_not_found",
                    "news_source": "benzinga_watchlist_json",
                    "news_fallback_used": False,
                    "news_stale": False,
                },
            },
        )

        def _spy_bundle(**kwargs):
            bundle_calls.append(kwargs)
            return {"snapshot": {}, "dashboard_payload": {}, "pine_payload": {}}

        monkeypatch.setattr(
            provider_health, "build_snapshot_bundle_for_symbol_timeframe", _spy_bundle,
        )

        smoke = provider_health._run_smoke_checks(
            symbols=["AAPL"],
            timeframes=["15m"],
            checked_at=1_000.0,
            stale_after_seconds=None,
        )

        assert len(bundle_calls) == 0, "bundle build should be skipped"
        row = smoke["results"][0]
        assert row.get("bundle_skipped") is True
        assert row.get("bundle_skip_reason") == "all_meta_domains_absent"

    def test_one_domain_present_runs_bundle(self, monkeypatch) -> None:
        """When at least one domain is present, the bundle build runs."""
        bundle_calls: list[tuple] = []

        monkeypatch.setattr(
            provider_health, "discover_composite_source_plan",
            lambda **kwargs: {"structure": "s", "volume": "v", "technical": "t", "news": "n"},
        )
        monkeypatch.setattr(
            provider_health, "load_raw_structure_input",
            lambda symbol, timeframe, source: {
                "bos": [{"id": "b1", "time": 1.0, "price": 100.0, "kind": "BOS", "dir": "UP"}],
                "orderblocks": [], "fvg": [], "liquidity_sweeps": [],
            },
        )
        monkeypatch.setattr(
            provider_health, "load_raw_meta_input_composite",
            lambda symbol, timeframe, source: {
                "asof_ts": 995.0,
                "volume": {"value": {"regime": "NORMAL", "thin_fraction": 0.1}},
                "meta_domain_diagnostics": {
                    "volume": "present",
                    "volume_source": "databento_watchlist_csv",
                    "volume_fallback_used": False,
                    "volume_stale": False,
                    "technical": "source_file_not_found",
                    "technical_source": "fmp_watchlist_json",
                    "technical_fallback_used": False,
                    "technical_stale": False,
                    "news": "source_file_not_found",
                    "news_source": "benzinga_watchlist_json",
                    "news_fallback_used": False,
                    "news_stale": False,
                },
            },
        )

        def _spy_bundle(**kwargs):
            bundle_calls.append(kwargs)
            return {
                "snapshot": {
                    "structure": {
                        "bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": [],
                    },
                },
                "source_plan": {"structure": "s", "volume": "v", "technical": "t", "news": "n"},
                "dashboard_payload": {},
                "pine_payload": {},
                "context_diagnostics": {"bars_available": True, "bar_count": 100},
            }

        monkeypatch.setattr(
            provider_health, "build_snapshot_bundle_for_symbol_timeframe", _spy_bundle,
        )

        smoke = provider_health._run_smoke_checks(
            symbols=["AAPL"],
            timeframes=["15m"],
            checked_at=1_000.0,
            stale_after_seconds=None,
        )

        assert len(bundle_calls) == 1, "bundle build should run"
        assert smoke["results"][0].get("bundle_skipped") is not True

    def test_synthetic_fallback_volume_runs_bundle(self, monkeypatch) -> None:
        """synthetic_fallback counts as present — bundle should still run."""
        bundle_calls: list[tuple] = []

        monkeypatch.setattr(
            provider_health, "discover_composite_source_plan",
            lambda **kwargs: {"structure": "s", "volume": "v", "technical": "t", "news": "n"},
        )
        monkeypatch.setattr(
            provider_health, "load_raw_structure_input",
            lambda symbol, timeframe, source: {
                "bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": [],
            },
        )
        monkeypatch.setattr(
            provider_health, "load_raw_meta_input_composite",
            lambda symbol, timeframe, source: {
                "asof_ts": 995.0,
                "meta_domain_diagnostics": {
                    "volume": "synthetic_fallback",
                    "volume_source": "synthetic",
                    "volume_fallback_used": True,
                    "volume_stale": False,
                    "technical": "source_file_not_found",
                    "technical_source": "fmp_watchlist_json",
                    "technical_fallback_used": False,
                    "technical_stale": False,
                    "news": "source_file_not_found",
                    "news_source": "benzinga_watchlist_json",
                    "news_fallback_used": False,
                    "news_stale": False,
                },
            },
        )

        def _spy_bundle(**kwargs):
            bundle_calls.append(kwargs)
            return {
                "snapshot": {
                    "structure": {
                        "bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": [],
                    },
                },
                "source_plan": {"structure": "s", "volume": "v", "technical": "t", "news": "n"},
                "dashboard_payload": {},
                "pine_payload": {},
                "context_diagnostics": {"bars_available": True, "bar_count": 0},
            }

        monkeypatch.setattr(
            provider_health, "build_snapshot_bundle_for_symbol_timeframe", _spy_bundle,
        )

        smoke = provider_health._run_smoke_checks(
            symbols=["AAPL"],
            timeframes=["15m"],
            checked_at=1_000.0,
            stale_after_seconds=None,
        )

        assert len(bundle_calls) == 1, "synthetic_fallback counts as present — bundle must run"
        assert smoke["results"][0].get("bundle_skipped") is not True


# ── pure helper coverage ─────────────────────────────────────────

from smc_integration.provider_health import (
    _domain_drop_provider_map,
    _domain_drop_reason_map,
    _domain_visibility_snapshot,
    _iso_utc,
    _missing_meta_domains,
    _normalize_symbols,
    _normalize_timeframes,
    _present_meta_domains,
    _promote_release_strict_failures,
    _raw_volume_regime,
    _shape_ok,
    _sorted_records,
    _source_plan_value,
    _status_from_lists,
    _structure_is_empty,
    _summarize_domain_visibility,
    provider_health_exit_code,
    write_provider_health_report,
)


class TestNormalizeSymbols:
    def test_dedup_and_upper(self) -> None:
        assert _normalize_symbols(["aapl", "AAPL", "msft"]) == ["AAPL", "MSFT"]

    def test_none_defaults_to_ibg(self) -> None:
        assert _normalize_symbols(None) == ["IBG"]

    def test_empty_list_defaults_to_ibg(self) -> None:
        assert _normalize_symbols([]) == ["IBG"]

    def test_whitespace_only_filtered(self) -> None:
        assert _normalize_symbols(["  ", "AAPL"]) == ["AAPL"]


class TestNormalizeTimeframes:
    def test_dedup(self) -> None:
        assert _normalize_timeframes(["15m", "15m", "1D"]) == ["15m", "1D"]

    def test_none_defaults_to_15m(self) -> None:
        assert _normalize_timeframes(None) == ["15m"]

    def test_empty_defaults_to_15m(self) -> None:
        assert _normalize_timeframes([]) == ["15m"]

    def test_whitespace_filtered(self) -> None:
        assert _normalize_timeframes(["  ", "5m"]) == ["5m"]


class TestShapeOk:
    def test_valid(self) -> None:
        assert _shape_ok({"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []}) is True

    def test_non_dict(self) -> None:
        assert _shape_ok("not a dict") is False

    def test_missing_keys(self) -> None:
        assert _shape_ok({"bos": []}) is False

    def test_extra_keys(self) -> None:
        assert _shape_ok({"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": [], "extra": []}) is False


class TestStructureIsEmpty:
    def test_all_empty(self) -> None:
        assert _structure_is_empty({"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []}) is True

    def test_one_populated(self) -> None:
        assert _structure_is_empty({"bos": [1], "orderblocks": [], "fvg": [], "liquidity_sweeps": []}) is False

    def test_non_list_value(self) -> None:
        assert _structure_is_empty({"bos": "not_a_list", "orderblocks": [], "fvg": [], "liquidity_sweeps": []}) is True


class TestStatusFromLists:
    def test_fail(self) -> None:
        assert _status_from_lists(failures=[{"x": 1}], warnings=[], degradations=[]) == "fail"

    def test_warn(self) -> None:
        assert _status_from_lists(failures=[], warnings=[{"x": 1}], degradations=[]) == "warn"

    def test_warn_from_degradation(self) -> None:
        assert _status_from_lists(failures=[], warnings=[], degradations=[{"x": 1}]) == "warn"

    def test_ok(self) -> None:
        assert _status_from_lists(failures=[], warnings=[], degradations=[]) == "ok"


class TestSourcePlanValue:
    def test_direct_key(self) -> None:
        assert _source_plan_value({"volume": "databento"}, "volume") == "databento"

    def test_snapshot_prefix(self) -> None:
        assert _source_plan_value({"snapshot_volume": "fmp"}, "volume") == "fmp"

    def test_none_source_plan(self) -> None:
        assert _source_plan_value(None, "volume") == ""

    def test_empty_value(self) -> None:
        assert _source_plan_value({"volume": ""}, "volume") == ""


class TestMissingMetaDomains:
    def test_valid(self) -> None:
        assert _missing_meta_domains({"meta_domains_missing": ["news", "technical"]}) == {"news", "technical"}

    def test_non_dict(self) -> None:
        assert _missing_meta_domains(None) == set()

    def test_non_list(self) -> None:
        assert _missing_meta_domains({"meta_domains_missing": "not_a_list"}) == set()

    def test_filters_non_strings(self) -> None:
        assert _missing_meta_domains({"meta_domains_missing": ["news", 42, "", "  "]}) == {"news"}


class TestDomainDropReasonMap:
    def test_valid(self) -> None:
        assert _domain_drop_reason_map({"domain_drop_reasons": {"news": "stale"}}) == {"news": "stale"}

    def test_non_dict_input(self) -> None:
        assert _domain_drop_reason_map(None) == {}

    def test_non_dict_reasons(self) -> None:
        assert _domain_drop_reason_map({"domain_drop_reasons": "bad"}) == {}

    def test_filters_empty_keys(self) -> None:
        assert _domain_drop_reason_map({"domain_drop_reasons": {"": "x", "news": ""}}) == {}


class TestDomainDropProviderMap:
    def test_valid(self) -> None:
        assert _domain_drop_provider_map({"domain_drop_providers": {"news": "benzinga"}}) == {"news": "benzinga"}

    def test_non_dict(self) -> None:
        assert _domain_drop_provider_map(None) == {}


class TestPresentMetaDomains:
    def test_from_list(self) -> None:
        result = _present_meta_domains({"meta_domains_present": ["volume", "news"]})
        assert result == {"volume", "news"}

    def test_from_dict_keys(self) -> None:
        result = _present_meta_domains({"volume": {"value": {}}, "technical": {"value": {}}})
        assert "volume" in result
        assert "technical" in result

    def test_non_dict(self) -> None:
        assert _present_meta_domains(None) == set()

    def test_non_list_present(self) -> None:
        result = _present_meta_domains({"meta_domains_present": "bad", "volume": {"value": {}}})
        assert "volume" in result


class TestRawVolumeRegime:
    def test_valid(self) -> None:
        assert _raw_volume_regime({"volume": {"value": {"regime": "UNKNOWN"}}}) == "UNKNOWN"

    def test_non_dict(self) -> None:
        assert _raw_volume_regime(None) == ""

    def test_no_volume(self) -> None:
        assert _raw_volume_regime({}) == ""

    def test_no_value(self) -> None:
        assert _raw_volume_regime({"volume": {}}) == ""

    def test_normal(self) -> None:
        assert _raw_volume_regime({"volume": {"value": {"regime": "normal"}}}) == "NORMAL"


class TestDomainVisibilitySnapshot:
    def test_full_coverage(self) -> None:
        result = _domain_visibility_snapshot(
            structure_present=True,
            raw_meta={"meta_domains_present": ["volume", "technical", "news"]},
            domain_diag=None,
        )
        assert result["domain_visibility_complete"] is True
        assert result["domain_visibility_score"] == 1.0

    def test_partial_from_diag(self) -> None:
        result = _domain_visibility_snapshot(
            structure_present=True,
            raw_meta=None,
            domain_diag={"volume": "present", "technical": "missing", "news": "synthetic_fallback"},
        )
        assert "volume" in result["domain_visibility_domains_present"]
        assert "news" in result["domain_visibility_domains_present"]
        assert "technical" in result["domain_visibility_domains_missing"]

    def test_stale_excluded_from_diag(self) -> None:
        result = _domain_visibility_snapshot(
            structure_present=False,
            raw_meta=None,
            domain_diag={"volume": "present", "volume_stale": True},
        )
        assert "volume" not in result["domain_visibility_domains_present"]


class TestSummarizeDomainVisibility:
    def test_empty(self) -> None:
        result = _summarize_domain_visibility([])
        assert result["average_score"] is None
        assert result["evaluated_rows"] == 0

    def test_with_rows(self) -> None:
        rows = [
            {"domain_visibility_score": 1.0, "domain_visibility_complete": True,
             "domain_visibility_domains_present": ["structure"], "domain_visibility_domains_missing": [],
             "symbol": "AAPL", "timeframe": "15m"},
            {"domain_visibility_score": 0.5, "domain_visibility_complete": False,
             "domain_visibility_domains_present": ["structure"], "domain_visibility_domains_missing": ["volume"],
             "symbol": "MSFT", "timeframe": "15m"},
        ]
        result = _summarize_domain_visibility(rows)
        assert result["evaluated_rows"] == 2
        assert result["fully_visible_rows"] == 1
        assert result["average_score"] == 0.75

    def test_non_numeric_score_skipped(self) -> None:
        rows = [{"domain_visibility_score": "bad"}]
        result = _summarize_domain_visibility(rows)
        assert result["evaluated_rows"] == 0


class TestIsoUtc:
    def test_formats(self) -> None:
        result = _iso_utc(0.0)
        assert "1970" in result


class TestSortedRecords:
    def test_sorts_deterministically(self) -> None:
        records = [{"b": 2}, {"a": 1}]
        result = _sorted_records(records)
        assert result[0] == {"a": 1}
        assert result[1] == {"b": 2}


class TestPromoteReleaseStrictFailures:
    def test_promotes_matching_warning(self) -> None:
        warnings = [{"code": "MISSING_ARTIFACT", "symbol": "X"}]
        w, f, _d = _promote_release_strict_failures(warnings=warnings, failures=[], degradations=[])
        assert len(w) == 0
        assert len(f) == 1
        assert f[0]["promoted_by"] == "release_strict_policy"

    def test_promotes_matching_degradation(self) -> None:
        degradations = [{"code": "STALE_MANIFEST_GENERATED_AT"}]
        _w, f, d = _promote_release_strict_failures(warnings=[], failures=[], degradations=degradations)
        assert len(d) == 0
        assert len(f) == 1

    def test_keeps_non_matching(self) -> None:
        warnings = [{"code": "SOME_OTHER_CODE"}]
        degradations = [{"code": "ANOTHER_CODE"}]
        w, f, d = _promote_release_strict_failures(warnings=warnings, failures=[], degradations=degradations)
        assert len(w) == 1
        assert len(d) == 1
        assert len(f) == 0


class TestProviderHealthExitCode:
    def test_fail_returns_1(self) -> None:
        assert provider_health_exit_code({"overall_status": "fail"}) == 1

    def test_ok_returns_0(self) -> None:
        assert provider_health_exit_code({"overall_status": "ok"}) == 0

    def test_warn_returns_0_by_default(self) -> None:
        assert provider_health_exit_code({"overall_status": "warn"}) == 0

    def test_warn_returns_2_with_fail_on_warn(self) -> None:
        assert provider_health_exit_code({"overall_status": "warn"}, fail_on_warn=True) == 2


class TestWriteProviderHealthReport:
    def test_writes_to_file(self, tmp_path: Path) -> None:
        out = tmp_path / "sub" / "report.json"
        write_provider_health_report({"status": "ok"}, out)
        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["status"] == "ok"

    def test_writes_to_stdout(self, capsys) -> None:
        write_provider_health_report({"status": "ok"}, None)
        captured = capsys.readouterr()
        assert '"status": "ok"' in captured.out


# ── Smoke-check failure-path coverage ────────────────────────────


def _stub_meta_ok(symbol, timeframe, source):
    return {"asof_ts": 995.0}


def _stub_structure_ok(symbol, timeframe, source):
    return {
        "bos": [{"id": 1}],
        "orderblocks": [],
        "fvg": [],
        "liquidity_sweeps": [],
    }


def _stub_source_plan(**_kw):
    return {
        "snapshot_structure": "artifact_json",
        "snapshot_meta": "symbol_timeframe",
        "snapshot_technical": "none",
        "snapshot_news": "none",
    }


def _stub_bundle_ok(*, symbol="X", timeframe="15m", **_kw):
    return {
        "snapshot": {
            "symbol": symbol,
            "timeframe": timeframe,
            "generated_at": 1_000.0,
            "structure": {
                "bos": [{"id": 1}],
                "orderblocks": [],
                "fvg": [],
                "liquidity_sweeps": [],
            },
        },
        "source_plan": _stub_source_plan(),
        "dashboard_payload": {},
        "pine_payload": {},
        "structure_context": {"meta": {"service": "stub"}},
    }


class TestSmokeSourcePlanFails:
    def test_source_plan_resolution_failed(self, monkeypatch) -> None:
        def _raise(**_kw):
            raise RuntimeError("source plan boom")

        monkeypatch.setattr(provider_health, "discover_composite_source_plan", _raise)

        smoke = provider_health._run_smoke_checks(
            symbols=["AAPL"],
            timeframes=["15m"],
            checked_at=1_000.0,
            stale_after_seconds=None,
        )
        assert smoke["results"][0]["status"] == "fail"
        assert any(f.get("code") == "SOURCE_PLAN_RESOLUTION_FAILED" for f in smoke["failures"])


class TestSmokeStructureInputFails:
    def test_structure_input_load_failed(self, monkeypatch) -> None:
        monkeypatch.setattr(provider_health, "discover_composite_source_plan", _stub_source_plan)

        def _raise(symbol, timeframe, source):
            raise RuntimeError("structure load boom")

        monkeypatch.setattr(provider_health, "load_raw_structure_input", _raise)

        smoke = provider_health._run_smoke_checks(
            symbols=["AAPL"],
            timeframes=["15m"],
            checked_at=1_000.0,
            stale_after_seconds=None,
        )
        assert smoke["results"][0]["status"] == "fail"
        assert any(f.get("code") == "STRUCTURE_INPUT_LOAD_FAILED" for f in smoke["failures"])


class TestSmokeInvalidStructureShape:
    def test_invalid_shape_is_failure(self, monkeypatch) -> None:
        monkeypatch.setattr(provider_health, "discover_composite_source_plan", _stub_source_plan)
        monkeypatch.setattr(
            provider_health, "load_raw_structure_input",
            lambda symbol, timeframe, source: {"wrong_key": []},
        )
        monkeypatch.setattr(provider_health, "load_raw_meta_input_composite", _stub_meta_ok)

        smoke = provider_health._run_smoke_checks(
            symbols=["AAPL"],
            timeframes=["15m"],
            checked_at=1_000.0,
            stale_after_seconds=None,
        )
        assert smoke["results"][0]["status"] == "fail"
        assert any(f.get("code") == "INVALID_STRUCTURE_SHAPE" for f in smoke["failures"])


class TestSmokeMetaInputFails:
    def test_meta_input_load_failed(self, monkeypatch) -> None:
        monkeypatch.setattr(provider_health, "discover_composite_source_plan", _stub_source_plan)
        monkeypatch.setattr(provider_health, "load_raw_structure_input", _stub_structure_ok)

        def _raise(symbol, timeframe, source):
            raise RuntimeError("meta boom")

        monkeypatch.setattr(provider_health, "load_raw_meta_input_composite", _raise)

        smoke = provider_health._run_smoke_checks(
            symbols=["AAPL"],
            timeframes=["15m"],
            checked_at=1_000.0,
            stale_after_seconds=None,
        )
        # meta load failure is captured but does NOT produce a hard fail
        # because raw_meta becomes None and the code continues.
        # However the failure IS added to the failures list.
        assert any(f.get("code") == "META_INPUT_LOAD_FAILED" for f in smoke["failures"])

    def test_meta_missing_asof_ts(self, monkeypatch) -> None:
        monkeypatch.setattr(provider_health, "discover_composite_source_plan", _stub_source_plan)
        monkeypatch.setattr(provider_health, "load_raw_structure_input", _stub_structure_ok)
        monkeypatch.setattr(
            provider_health, "load_raw_meta_input_composite",
            lambda symbol, timeframe, source: {"no_asof": True},
        )
        monkeypatch.setattr(provider_health, "build_snapshot_bundle_for_symbol_timeframe", lambda **kw: _stub_bundle_ok(**kw))

        smoke = provider_health._run_smoke_checks(
            symbols=["AAPL"],
            timeframes=["15m"],
            checked_at=1_000.0,
            stale_after_seconds=None,
        )
        assert any(w.get("code") == "MISSING_META_ASOF_TS" for w in smoke["warnings"])


class TestSmokeBundleValidation:
    """Cover bundle snapshot/payload/plan validation paths."""

    def _patch_pre_bundle(self, monkeypatch) -> None:
        monkeypatch.setattr(provider_health, "discover_composite_source_plan", _stub_source_plan)
        monkeypatch.setattr(provider_health, "load_raw_structure_input", _stub_structure_ok)
        monkeypatch.setattr(provider_health, "load_raw_meta_input_composite", _stub_meta_ok)

    def test_no_snapshot_dict_is_failure(self, monkeypatch) -> None:
        self._patch_pre_bundle(monkeypatch)
        monkeypatch.setattr(
            provider_health, "build_snapshot_bundle_for_symbol_timeframe",
            lambda **kw: {
                "snapshot": "not_a_dict",
                "source_plan": None,
                "dashboard_payload": None,
                "pine_payload": None,
            },
        )

        smoke = provider_health._run_smoke_checks(
            symbols=["AAPL"], timeframes=["15m"], checked_at=1_000.0, stale_after_seconds=None,
        )
        codes = [f.get("code") for f in smoke["failures"]]
        assert "INVALID_BUNDLE_SNAPSHOT" in codes
        assert "MISSING_DASHBOARD_PAYLOAD" in codes
        assert "MISSING_PINE_PAYLOAD" in codes

    def test_invalid_snapshot_structure_shape(self, monkeypatch) -> None:
        self._patch_pre_bundle(monkeypatch)
        monkeypatch.setattr(
            provider_health, "build_snapshot_bundle_for_symbol_timeframe",
            lambda **kw: {
                "snapshot": {
                    "structure": {"wrong": []},
                    "structure_context": {"leak": True},
                },
                "source_plan": _stub_source_plan(),
                "dashboard_payload": {},
                "pine_payload": {},
            },
        )

        smoke = provider_health._run_smoke_checks(
            symbols=["AAPL"], timeframes=["15m"], checked_at=1_000.0, stale_after_seconds=None,
        )
        codes = [f.get("code") for f in smoke["failures"]]
        assert "INVALID_SNAPSHOT_STRUCTURE_SHAPE" in codes
        assert "STRUCTURE_CONTEXT_POLLUTES_SNAPSHOT" in codes

    def test_source_plan_mismatch(self, monkeypatch) -> None:
        self._patch_pre_bundle(monkeypatch)
        monkeypatch.setattr(
            provider_health, "build_snapshot_bundle_for_symbol_timeframe",
            lambda **kw: {
                "snapshot": {
                    "structure": {
                        "bos": [{"id": 1}],
                        "orderblocks": [],
                        "fvg": [],
                        "liquidity_sweeps": [],
                    },
                },
                "source_plan": {"snapshot_structure": "DIFFERENT"},
                "dashboard_payload": {},
                "pine_payload": {},
            },
        )

        smoke = provider_health._run_smoke_checks(
            symbols=["AAPL"], timeframes=["15m"], checked_at=1_000.0, stale_after_seconds=None,
        )
        assert any(w.get("code") == "SOURCE_PLAN_MISMATCH" for w in smoke["warnings"])
        assert any(d.get("code") == "SOURCE_PLAN_MISMATCH" for d in smoke["degradations"])

    def test_missing_bundle_source_plan(self, monkeypatch) -> None:
        self._patch_pre_bundle(monkeypatch)
        monkeypatch.setattr(
            provider_health, "build_snapshot_bundle_for_symbol_timeframe",
            lambda **kw: {
                "snapshot": {
                    "structure": {
                        "bos": [{"id": 1}],
                        "orderblocks": [],
                        "fvg": [],
                        "liquidity_sweeps": [],
                    },
                },
                "dashboard_payload": {},
                "pine_payload": {},
            },
        )

        smoke = provider_health._run_smoke_checks(
            symbols=["AAPL"], timeframes=["15m"], checked_at=1_000.0, stale_after_seconds=None,
        )
        assert any(w.get("code") == "MISSING_BUNDLE_SOURCE_PLAN" for w in smoke["warnings"])


class TestCollectArtifactHealthEdges:
    def test_artifact_lookup_exception(self, monkeypatch) -> None:
        monkeypatch.setattr(
            provider_health.structure_artifact_json,
            "discover_normalized_contract_summary",
            _stub_contract_summary,
        )
        monkeypatch.setattr(
            provider_health.structure_artifact_json,
            "STRUCTURE_ARTIFACTS_DIR",
            Path("/nonexistent"),
        )

        def _raise(symbol, timeframe):
            raise RuntimeError("lookup boom")

        monkeypatch.setattr(
            provider_health.structure_artifact_json,
            "has_artifact_for_symbol_timeframe",
            _raise,
        )

        result = provider_health._collect_artifact_health(
            symbols=["AAPL"],
            timeframes=["15m"],
            checked_at=1_000.0,
            stale_after_seconds=None,
        )
        assert any(f.get("code") == "ARTIFACT_LOOKUP_FAILED" for f in result["failures"])


class TestProviderDomainResultsWithEntries:
    def test_warn_when_cannot_supply_symbols(self, monkeypatch) -> None:
        from smc_integration.provider_matrix import (
            ProviderCurrentMapping,
            ProviderMatrixEntry,
            ProviderPotential,
        )

        entry = ProviderMatrixEntry(
            name="test_provider",
            source_module="smc_integration.sources.test_provider",
            path_hint="test.json",
            source_format="json",
            potential=ProviderPotential(
                can_supply_symbols=False,
                can_supply_volume_meta=False,
                can_supply_technical_meta=False,
                can_supply_news_meta=False,
                can_supply_raw_bars=False,
                can_supply_microstructure=False,
                can_supply_precomputed_structure=False,
            ),
            current=ProviderCurrentMapping(
                currently_maps_structure=False,
                currently_maps_meta=False,
                currently_maps_volume=False,
                currently_maps_technical=False,
                currently_maps_news=False,
                snapshot_structure_mode="none",
                snapshot_meta_mode="none",
            ),
            known_gaps=["no_symbols"],
        )
        monkeypatch.setattr(provider_health, "discover_provider_matrix", lambda: [entry])
        rows = provider_health._provider_domain_results()
        assert len(rows) == 1
        assert rows[0]["status"] == "warn"
        assert rows[0]["provider"] == "test_provider"
        assert rows[0]["known_gaps"] == ["no_symbols"]


class TestRunProviderHealthIncludeSmokeBundles:
    def test_smoke_bundles_included_in_report(self, monkeypatch) -> None:
        monkeypatch.setattr(provider_health, "discover_provider_matrix", lambda: [])
        monkeypatch.setattr(provider_health, "discover_structure_source_status", _stub_structure_status)
        monkeypatch.setattr(
            provider_health.structure_artifact_json,
            "discover_normalized_contract_summary",
            _stub_contract_summary,
        )
        monkeypatch.setattr(
            provider_health.structure_artifact_json,
            "STRUCTURE_ARTIFACTS_DIR",
            Path("/nonexistent"),
        )
        monkeypatch.setattr(
            provider_health.structure_artifact_json,
            "has_artifact_for_symbol_timeframe",
            lambda symbol, timeframe: True,
        )
        monkeypatch.setattr(
            provider_health,
            "_run_smoke_checks",
            lambda **_kw: {
                "results": [],
                "warnings": [],
                "failures": [],
                "degradations": [],
                "domain_alerts": [],
                "bundles": {("AAPL", "15m"): {"stub": True}},
            },
        )

        report = provider_health.run_provider_health_check(
            symbols=["AAPL"],
            timeframes=["15m"],
            checked_at=1_000.0,
            include_smoke_bundles=True,
        )
        assert "smoke_bundles" in report
        assert report["smoke_bundles"] == {("AAPL", "15m"): {"stub": True}}

    def test_smoke_bundles_excluded_by_default(self, monkeypatch) -> None:
        monkeypatch.setattr(provider_health, "discover_provider_matrix", lambda: [])
        monkeypatch.setattr(provider_health, "discover_structure_source_status", _stub_structure_status)
        monkeypatch.setattr(
            provider_health.structure_artifact_json,
            "discover_normalized_contract_summary",
            _stub_contract_summary,
        )
        monkeypatch.setattr(
            provider_health.structure_artifact_json,
            "STRUCTURE_ARTIFACTS_DIR",
            Path("/nonexistent"),
        )
        monkeypatch.setattr(
            provider_health.structure_artifact_json,
            "has_artifact_for_symbol_timeframe",
            lambda symbol, timeframe: True,
        )
        monkeypatch.setattr(provider_health, "_run_smoke_checks", _stub_smoke_ok)

        report = provider_health.run_provider_health_check(
            symbols=["AAPL"],
            timeframes=["15m"],
            checked_at=1_000.0,
        )
        assert "smoke_bundles" not in report


class TestCollectArtifactHealthFatalIssue:
    """Cover line 600: health issue with a fatal code → failures.append."""

    def test_fatal_health_issue_promotes_to_failure(self, monkeypatch) -> None:
        monkeypatch.setattr(
            provider_health.structure_artifact_json,
            "discover_normalized_contract_summary",
            lambda **_kw: {
                "health": {
                    "issues": [
                        {"code": "INVALID_MANIFEST_JSON", "message": "corrupt json"},
                    ],
                },
                "mapped_structure_categories": {},
                "structure_profile_supported": False,
                "diagnostics_available": False,
            },
        )
        monkeypatch.setattr(
            provider_health.structure_artifact_json,
            "STRUCTURE_ARTIFACTS_DIR",
            Path("/nonexistent"),
        )
        monkeypatch.setattr(
            provider_health.structure_artifact_json,
            "has_artifact_for_symbol_timeframe",
            lambda symbol, timeframe: True,
        )

        result = provider_health._collect_artifact_health(
            symbols=["AAPL"],
            timeframes=["15m"],
            checked_at=1_000.0,
            stale_after_seconds=None,
        )
        assert result["status"] == "fail"
        assert any(f.get("code") == "INVALID_MANIFEST_JSON" for f in result["failures"])


class TestSmokeBundleInvalidStructureContextShape:
    """Cover line 1081: bundle.structure_context exists but is not a dict."""

    def test_non_dict_structure_context_is_warning(self, monkeypatch) -> None:
        monkeypatch.setattr(provider_health, "discover_composite_source_plan", _stub_source_plan)
        monkeypatch.setattr(provider_health, "load_raw_structure_input", _stub_structure_ok)
        monkeypatch.setattr(provider_health, "load_raw_meta_input_composite", _stub_meta_ok)
        monkeypatch.setattr(
            provider_health, "build_snapshot_bundle_for_symbol_timeframe",
            lambda **kw: {
                "snapshot": {
                    "structure": {
                        "bos": [{"id": 1}],
                        "orderblocks": [],
                        "fvg": [],
                        "liquidity_sweeps": [],
                    },
                },
                "source_plan": _stub_source_plan(),
                "dashboard_payload": {},
                "pine_payload": {},
                "structure_context": "not_a_dict",
            },
        )

        smoke = provider_health._run_smoke_checks(
            symbols=["AAPL"], timeframes=["15m"], checked_at=1_000.0, stale_after_seconds=None,
        )
        assert any(w.get("code") == "INVALID_STRUCTURE_CONTEXT_SHAPE" for w in smoke["warnings"])


class TestRunProviderHealthStructureSourceHealthIssues:
    """Cover line 1219: selected_health_issue_count > 0 → degradation."""

    def test_health_issues_produce_degradation(self, monkeypatch) -> None:
        monkeypatch.setattr(provider_health, "discover_provider_matrix", lambda: [])
        monkeypatch.setattr(
            provider_health,
            "discover_structure_source_status",
            lambda **_kw: {
                "source": "auto",
                "selected": "structure_artifact_json",
                "selected_health_issue_count": 2,
                "selected_health_issues": [{"code": "X"}, {"code": "Y"}],
            },
        )
        monkeypatch.setattr(
            provider_health.structure_artifact_json,
            "discover_normalized_contract_summary",
            _stub_contract_summary,
        )
        monkeypatch.setattr(
            provider_health.structure_artifact_json,
            "STRUCTURE_ARTIFACTS_DIR",
            Path("/nonexistent"),
        )
        monkeypatch.setattr(
            provider_health.structure_artifact_json,
            "has_artifact_for_symbol_timeframe",
            lambda symbol, timeframe: True,
        )
        monkeypatch.setattr(provider_health, "_run_smoke_checks", _stub_smoke_ok)

        report = provider_health.run_provider_health_check(
            symbols=["AAPL"],
            timeframes=["15m"],
            checked_at=1_000.0,
        )
        assert any(
            d.get("code") == "STRUCTURE_SOURCE_HEALTH_ISSUES" for d in report["degradations_detected"]
        )
