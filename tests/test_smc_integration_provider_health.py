from __future__ import annotations

import json
import os

from smc_integration import provider_health


def _stub_structure_status(**_: object) -> dict[str, object]:
    return {
        "source": "auto",
        "selected": "structure_artifact_json",
        "selected_health_issue_count": 0,
        "selected_health_issues": [],
    }


def _stub_contract_summary() -> dict[str, object]:
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
        "warnings",
        "failures",
        "degradations_detected",
    }
    assert required_keys.issubset(report_a.keys())
    assert json.dumps(report_a, sort_keys=True) == json.dumps(report_b, sort_keys=True)


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
