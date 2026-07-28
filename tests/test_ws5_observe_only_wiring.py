"""Observe-only wiring of the ENG-WS5 modules into their named consumers.

Covers two shadow-first adoptions:

* E1 (ENG-WS5-01) — ``smc_integration.provider_health`` emits a
  manifest-preference verdict (:mod:`smc_integration.manifest_preference`)
  for the reference structure artifact WITHOUT changing source selection.
* E2 (ENG-WS5-02) — ``scripts.run_smc_pre_release_artifact_refresh`` emits a
  stale-batch verdict (:mod:`smc_integration.stale_batch_guard`) for the
  reference manifests WITHOUT fail-fast.

For each: one test that the emitted field is present + correct, and one that
the host's existing decision output is unchanged (observe-only).
"""
from __future__ import annotations

import json
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

from scripts import run_smc_pre_release_artifact_refresh as refresh_script
from smc_integration import provider_health, stale_batch_guard
from smc_integration.sources import structure_artifact_json


# --------------------------------------------------------------------------- #
# E1 — provider_health manifest-preference verdict                            #
# --------------------------------------------------------------------------- #
def _stub_structure_status(**_: object) -> dict[str, object]:
    return {
        "selected_structure_source": "structure_artifact_json",
        "selected_health_issue_count": 0,
        "selected_health_issues": [],
    }


def _stub_contract_summary(**_: object) -> dict[str, object]:
    return {
        "mapped_structure_categories": {"bos": "bos"},
        "structure_profile_supported": True,
        "diagnostics_available": True,
        "health": {"issues": [], "sources": []},
    }


def _stub_smoke_ok(**_: object) -> dict[str, object]:
    return {"results": [], "warnings": [], "failures": [], "degradations": []}


def _install_manifest_fixture(monkeypatch, tmp_path: Path, *, generated_at: float = 95.0) -> None:
    """Write a real manifest + deterministic scratch artifact for AAPL/15m."""
    artifact_dir = tmp_path / "reports" / "smc_structure_artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "AAPL_15m.structure.json").write_text(
        json.dumps({"symbol": "AAPL", "timeframe": "15m", "structure": {}}) + "\n",
        encoding="utf-8",
    )
    (artifact_dir / "manifest_15m.json").write_text(
        json.dumps(
            {
                "schema_version": "3.0.0",
                "generated_at": generated_at,
                "timeframe": "15m",
                "artifacts": [
                    {
                        "symbol": "AAPL",
                        "timeframe": "15m",
                        "artifact_path": "reports/smc_structure_artifacts/AAPL_15m.structure.json",
                    }
                ],
                "errors": [],
                "warnings": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(structure_artifact_json, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", artifact_dir)
    monkeypatch.setattr(
        structure_artifact_json, "STRUCTURE_ARTIFACT_JSON", tmp_path / "reports" / "smc_structure_artifact.json"
    )
    monkeypatch.setattr(provider_health, "discover_provider_matrix", lambda: [])
    monkeypatch.setattr(provider_health, "discover_structure_source_status", _stub_structure_status)
    monkeypatch.setattr(provider_health, "_run_smoke_checks", _stub_smoke_ok)
    monkeypatch.setattr(
        provider_health.structure_artifact_json, "discover_normalized_contract_summary", _stub_contract_summary
    )


def _run_health(**overrides):
    kwargs = {"symbols": ["AAPL"], "timeframes": ["15m"], "checked_at": 100.0, "stale_after_seconds": 30}
    kwargs.update(overrides)
    return provider_health.run_provider_health_check(**kwargs)


def test_e1_manifest_preference_field_present_and_correct(monkeypatch, tmp_path):
    _install_manifest_fixture(monkeypatch, tmp_path)

    report = _run_health()

    pref = report["structure_artifact_preference"]
    assert pref is not None
    assert pref["observe_only"] is True
    assert pref["chosen_source"] == "manifest"
    assert pref["reference_symbol"] == "AAPL"
    assert pref["reference_timeframe"] == "15m"
    # The deterministic local file is enumerated as a scratch candidate and
    # must be rejected in favour of the manifest-backed artifact.
    rejected_sources = {row["source"] for row in pref["rejected"]}
    assert "scratch" in rejected_sources
    # The manifest-preference winner agrees with what the loader resolves today.
    assert pref["loader_actual_mode"] == "manifest"
    assert pref["agrees_with_loader"] is True


def _decision(report: dict) -> dict:
    return {
        "overall_status": report["overall_status"],
        "warnings": report["warnings"],
        "failures": report["failures"],
        "degradations_detected": report["degradations_detected"],
        "exit_code": provider_health.provider_health_exit_code(report),
    }


def test_e1_observe_only_verdict_never_changes_health_decision(monkeypatch, tmp_path):
    _install_manifest_fixture(monkeypatch, tmp_path)

    baseline = _run_health()
    baseline_decision = _decision(baseline)

    # Inject an alarming verdict: the decision must be byte-identical, only the
    # observe-only field changes.
    sentinel = {"chosen_source": None, "blocked": True, "reason": "INJECTED", "observe_only": True}
    monkeypatch.setattr(provider_health, "_resolve_structure_artifact_preference", lambda *a, **k: sentinel)
    injected = _run_health()

    assert _decision(injected) == baseline_decision
    assert injected["structure_artifact_preference"] == sentinel
    assert injected["structure_artifact_preference"] != baseline["structure_artifact_preference"]


def test_e1_preference_is_fail_soft_and_still_observe_only(monkeypatch, tmp_path):
    _install_manifest_fixture(monkeypatch, tmp_path)
    baseline_decision = _decision(_run_health())

    def _boom(*_a, **_k):
        raise RuntimeError("candidate discovery blew up")

    monkeypatch.setattr(structure_artifact_json, "discover_artifact_candidates", _boom)
    report = _run_health()

    # Fail-soft: the field is None, and the host decision is unchanged.
    assert report["structure_artifact_preference"] is None
    assert _decision(report) == baseline_decision


# --------------------------------------------------------------------------- #
# E2 — pre-release refresh stale-batch verdict                                #
# --------------------------------------------------------------------------- #
_NOW = datetime(2026, 4, 20, 12, 0, tzinfo=UTC)


def _write_manifest(dir_: Path, timeframe: str, generated_at: float) -> None:
    (dir_ / f"manifest_{timeframe}.json").write_text(
        json.dumps({"generated_at": generated_at, "timeframe": timeframe}) + "\n", encoding="utf-8"
    )


def test_e2_stale_batch_verdict_present_and_correct(tmp_path):
    _write_manifest(tmp_path, "1D", _NOW.timestamp())  # fresh
    _write_manifest(tmp_path, "5m", 0.0)  # 1970 -> stale
    # "1H" manifest intentionally absent -> unknown freshness.

    verdict = refresh_script._evaluate_reference_batch_freshness(
        tmp_path, ["1D", "5m", "1H"], now=_NOW
    )

    assert verdict is not None
    assert verdict["overall_status"] == "stale"
    assert verdict["blocked"] is True
    statuses = {row["name"]: row["status"] for row in verdict["batches"]}
    assert statuses["structure_manifest_1D"] == "fresh"
    assert statuses["structure_manifest_5m"] == "stale"
    assert statuses["structure_manifest_1H"] == "unknown"


def test_e2_batch_freshness_is_fail_soft(monkeypatch, tmp_path):
    _write_manifest(tmp_path, "1D", _NOW.timestamp())

    def _boom(*_a, **_k):
        raise RuntimeError("evaluate blew up")

    monkeypatch.setattr(stale_batch_guard, "evaluate", _boom)
    assert refresh_script._evaluate_reference_batch_freshness(tmp_path, ["1D"], now=_NOW) is None


class _Parser:
    def __init__(self, args: Namespace):
        self._args = args

    def parse_args(self) -> Namespace:
        return self._args


def test_e2_observe_only_stale_verdict_does_not_block_refresh(monkeypatch, tmp_path):
    artifacts_dir = tmp_path / "reports" / "smc_structure_artifacts"
    artifacts_dir.mkdir(parents=True)
    _write_manifest(artifacts_dir, "1D", 0.0)  # STALE reference manifest on disk

    captured: list[dict] = []
    monkeypatch.setattr(
        refresh_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                symbols="AAPL",
                timeframes="1D",
                structure_artifacts_dir=str(artifacts_dir),
                workbook_path="",
                export_bundle_root="",
                structure_profile="hybrid_default",
                allow_missing_inputs=False,
                warn_on_empty_artifacts=False,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(
        refresh_script,
        "resolve_structure_artifact_inputs",
        lambda **_k: {
            "workbook_path": None,
            "export_bundle_root": None,
            "structure_artifacts_dir": artifacts_dir,
            "resolution_mode": "explicit",
            "warnings": [],
            "errors": [],
        },
    )

    def _ok_stub(**kwargs):
        syms = list(kwargs["symbols"])
        return {
            "artifacts": [
                {"symbol": s, "timeframe": kwargs["timeframe"], "coverage_mode": "bundle", "bos_count": 1}
                for s in syms
            ],
            "counts": {"symbols_requested": len(syms), "artifacts_written": len(syms), "errors": 0},
            "errors": [],
            "warnings": [],
            "timeframe": kwargs["timeframe"],
        }

    monkeypatch.setattr(refresh_script, "write_structure_artifacts_from_workbook", _ok_stub)
    monkeypatch.setattr(refresh_script, "runtime_metadata", lambda: {})
    monkeypatch.setattr(refresh_script, "_render", lambda report, output: captured.append(report))

    rc = refresh_script.main()

    # Observe-only: the on-disk reference manifest is STALE and the verdict says
    # so, yet the refresh neither fails nor blocks.
    assert rc == 0
    report = captured[-1]
    assert report["overall_status"] == "ok"
    assert report["stale_batch_verdict"] is not None
    assert report["stale_batch_verdict"]["blocked"] is True
    assert report["stale_batch_verdict"]["overall_status"] == "stale"
