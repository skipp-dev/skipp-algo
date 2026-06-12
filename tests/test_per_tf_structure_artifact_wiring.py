"""#2667 — per-TF structure artifact wiring (un-void Plan 2.8 Phase-E2).

Pins the three layers that turn the cross-TF aliasing guard from a silent
clone-factory into an operable contract:

1. CLI: ``scripts/export_smc_structure_artifacts_from_workbook.py`` exposes
   ``--export-bundle-root`` and forwards it — an explicitly passed
   ``--workbook`` suppresses bundle auto-discovery, so intraday timeframes
   could never be exported from CI. ``--workbook`` defaults to ``None`` so
   the library applies the SAME canonical workbook resolution that the
   downstream manifest provenance check expects
   (``NONCANONICAL_MANIFEST_WORKBOOK_PATH`` regression, #2678 fallout).
2. Evidence: ``build_measurement_evidence`` propagates contract-level
   warnings (``legacy_tf_fallback``) into the evidence warning stream.
3. Runner: ``run_smc_measurement_benchmark.py --strict-structure-tf``
   fails the run when any pair was served aliased structure; default is
   warn-only + manifest disclosure (``structure_tf_integrity``).
4. Workflow: the rolling lane exports per-TF artifacts BEFORE the benchmark
   and feeds both steps from one SYMBOLS/TIMEFRAMES resolution.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

import scripts.export_smc_structure_artifacts_from_workbook as exporter_cli
import scripts.run_smc_measurement_benchmark as bench
from smc_integration import measurement_evidence

REPO = Path(__file__).resolve().parents[1]
ROLLING_WF = REPO / ".github" / "workflows" / "smc-measurement-benchmark-rolling.yml"


# ---------------------------------------------------------------------------
# 1. Exporter CLI: --export-bundle-root passthrough
# ---------------------------------------------------------------------------


def test_exporter_cli_exposes_export_bundle_root() -> None:
    parser = exporter_cli._build_parser()
    ns = parser.parse_args(["--timeframe", "5m", "--export-bundle-root", "some/bundle"])
    assert ns.export_bundle_root == "some/bundle"


def test_exporter_cli_bundle_root_defaults_to_none() -> None:
    parser = exporter_cli._build_parser()
    ns = parser.parse_args(["--timeframe", "5m"])
    assert ns.export_bundle_root is None


def test_exporter_cli_forwards_bundle_root(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_write(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"counts": {"artifacts_written": 0, "errors": 0}}

    monkeypatch.setattr(exporter_cli, "write_structure_artifacts_from_workbook", _fake_write)
    rc = exporter_cli.main(
        [
            "--timeframe",
            "15m",
            "--symbols",
            "AAPL",
            "--export-bundle-root",
            "artifacts/smc_microstructure_exports",
        ]
    )
    assert rc == 0
    assert captured["export_bundle_root"] == Path("artifacts/smc_microstructure_exports")
    assert captured["timeframe"] == "15m"


def test_exporter_cli_forwards_none_when_bundle_root_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_write(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"counts": {"artifacts_written": 0, "errors": 0}}

    monkeypatch.setattr(exporter_cli, "write_structure_artifacts_from_workbook", _fake_write)
    rc = exporter_cli.main(["--timeframe", "1D"])
    assert rc == 0
    assert captured["export_bundle_root"] is None


def test_exporter_cli_workbook_defaults_to_none() -> None:
    """#2678 fallout: a hardcoded DEFAULT_WORKBOOK default stamped a
    non-existent path into the manifest in CI, tripping the consumer's
    NONCANONICAL_MANIFEST_WORKBOOK_PATH provenance check. The CLI must
    default to None so the library's canonical resolution (the same one the
    consumer check uses) is applied."""
    parser = exporter_cli._build_parser()
    ns = parser.parse_args(["--timeframe", "5m"])
    assert ns.workbook is None


def test_exporter_cli_forwards_none_workbook_when_omitted(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_write(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"counts": {"artifacts_written": 0, "errors": 0}}

    monkeypatch.setattr(exporter_cli, "write_structure_artifacts_from_workbook", _fake_write)
    rc = exporter_cli.main(["--timeframe", "5m", "--symbols", "AAPL"])
    assert rc == 0
    assert captured["workbook"] is None


def test_exporter_cli_forwards_explicit_workbook(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_write(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"counts": {"artifacts_written": 0, "errors": 0}}

    monkeypatch.setattr(exporter_cli, "write_structure_artifacts_from_workbook", _fake_write)
    rc = exporter_cli.main(["--timeframe", "1D", "--workbook", "some/workbook.xlsx"])
    assert rc == 0
    assert captured["workbook"] == Path("some/workbook.xlsx")


# ---------------------------------------------------------------------------
# 2. Evidence: contract warnings propagate into evidence warnings
# ---------------------------------------------------------------------------


def _minimal_contract(warnings: list[str]) -> dict[str, Any]:
    return {
        "symbol": "AAPL",
        "timeframe": "5m",
        "structure_profile_used": "hybrid_default",
        "canonical_structure": {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
        "warnings": list(warnings),
    }


def test_contract_legacy_tf_fallback_warning_reaches_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    fallback_warning = "legacy_tf_fallback: requested 5m, served 1D"
    monkeypatch.setattr(
        measurement_evidence.structure_artifact_json,
        "load_normalized_structure_contract_input",
        lambda symbol, timeframe: _minimal_contract([fallback_warning]),
    )
    monkeypatch.setattr(
        measurement_evidence,
        "_resolve_measurement_event_risk_light",
        lambda symbol, timeframe: ({}, {}),
    )
    monkeypatch.setattr(
        measurement_evidence,
        "_load_source_bars",
        lambda symbol, timeframe, resolved_inputs=None: (pd.DataFrame(), "none"),
    )

    evidence = measurement_evidence.build_measurement_evidence("AAPL", "5m")
    assert fallback_warning in evidence.warnings


def test_contract_without_warnings_adds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        measurement_evidence.structure_artifact_json,
        "load_normalized_structure_contract_input",
        lambda symbol, timeframe: _minimal_contract([]),
    )
    monkeypatch.setattr(
        measurement_evidence,
        "_resolve_measurement_event_risk_light",
        lambda symbol, timeframe: ({}, {}),
    )
    monkeypatch.setattr(
        measurement_evidence,
        "_load_source_bars",
        lambda symbol, timeframe, resolved_inputs=None: (pd.DataFrame(), "none"),
    )

    evidence = measurement_evidence.build_measurement_evidence("AAPL", "5m")
    assert not any("legacy_tf_fallback" in w for w in evidence.warnings)


# ---------------------------------------------------------------------------
# 3. Runner: --strict-structure-tf gate + manifest disclosure
# ---------------------------------------------------------------------------


def _pair_summary(symbol: str, timeframe: str, warnings: list[str]) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "measurement_evidence_present": True,
        "bars_source_mode": "canonical_export_bundle",
        "scoring": {
            "n_events": 3,
            "brier_score": 0.2,
            "log_score": 0.5,
            "hit_rate": 0.5,
            "families_present": ["BOS"],
            "calibration": {
                "method": "isotonic",
                "calibrated_brier_score": 0.2,
                "calibrated_log_score": 0.5,
                "raw_ece": 0.1,
                "calibrated_ece": 0.1,
            },
            "stratified_calibration_summary": {"dimensions_present": []},
            "contextual_calibration_summary": {
                "dimensions_present": [],
                "best_dimension_by_adjusted_brier": None,
                "best_dimension_by_adjusted_ece": None,
            },
        },
        "stratification_coverage": {"populated_bucket_count": 1},
        "warnings": list(warnings),
    }


def _run_main(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    warnings_by_tf: dict[str, list[str]],
    strict: bool,
) -> tuple[int, dict[str, Any]]:
    def _fake_run_pair(symbol: str, timeframe: str, *, output_root: Path) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "artifact_dir": (output_root / f"{symbol}_{timeframe}").as_posix(),
            "summary": _pair_summary(symbol, timeframe, warnings_by_tf.get(timeframe, [])),
            "family_events": [],
        }

    monkeypatch.setattr(bench, "run_pair", _fake_run_pair)
    argv = [
        "run_smc_measurement_benchmark.py",
        "--symbols",
        "AAPL",
        "--timeframes",
        ",".join(warnings_by_tf),
        "--output-dir",
        str(tmp_path),
    ]
    if strict:
        argv.append("--strict-structure-tf")
    monkeypatch.setattr(sys, "argv", argv)

    rc = bench.main()
    manifest = json.loads((tmp_path / "benchmark_run_manifest.json").read_text(encoding="utf-8"))
    return rc, manifest


def test_strict_structure_tf_fails_on_fallback_pair(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, manifest = _run_main(
        monkeypatch,
        tmp_path,
        warnings_by_tf={"5m": ["legacy_tf_fallback: requested 5m, served 1D"], "1H": []},
        strict=True,
    )
    assert rc == 1
    assert "legacy_tf_fallback" in capsys.readouterr().err
    integrity = manifest["structure_tf_integrity"]
    assert integrity["strict_structure_tf"] is True
    assert integrity["legacy_tf_fallback_pair_count"] == 1
    assert integrity["legacy_tf_fallback_pairs"] == ["AAPL/5m"]


def test_default_mode_warns_but_passes_on_fallback_pair(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc, manifest = _run_main(
        monkeypatch,
        tmp_path,
        warnings_by_tf={"5m": ["legacy_tf_fallback: requested 5m, served 1D"]},
        strict=False,
    )
    assert rc == 0
    assert "legacy_tf_fallback" in capsys.readouterr().err
    integrity = manifest["structure_tf_integrity"]
    assert integrity["strict_structure_tf"] is False
    assert integrity["legacy_tf_fallback_pairs"] == ["AAPL/5m"]


def test_strict_structure_tf_passes_when_no_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rc, manifest = _run_main(
        monkeypatch,
        tmp_path,
        warnings_by_tf={"5m": [], "1H": []},
        strict=True,
    )
    assert rc == 0
    integrity = manifest["structure_tf_integrity"]
    assert integrity["legacy_tf_fallback_pair_count"] == 0
    assert integrity["legacy_tf_fallback_pairs"] == []


def test_strict_flag_defaults_off() -> None:
    ns = bench.build_parser().parse_args([])
    assert ns.strict_structure_tf is False


# ---------------------------------------------------------------------------
# 4. Workflow: per-TF export step wired before the benchmark
# ---------------------------------------------------------------------------


def test_rolling_workflow_exports_per_tf_artifacts_before_benchmark() -> None:
    text = ROLLING_WF.read_text(encoding="utf-8")
    export_idx = text.index("Export per-TF structure artifacts")
    bench_idx = text.index("Run daily rolling benchmark")
    verify_idx = text.index("Verify Databento production export bundle is present")
    assert verify_idx < export_idx < bench_idx
    assert "--export-bundle-root artifacts/smc_microstructure_exports" in text


def test_rolling_workflow_benchmark_consumes_shared_symbol_resolution() -> None:
    text = ROLLING_WF.read_text(encoding="utf-8")
    # Single source of truth: the export step publishes the validated
    # SYMBOLS/TIMEFRAMES via GITHUB_ENV; the benchmark step must consume
    # them instead of re-deriving its own copy (stale-duplicate trap).
    assert 'echo "SMC_BENCH_SYMBOLS=${SYMBOLS}" >> "$GITHUB_ENV"' in text
    assert 'echo "SMC_BENCH_TIMEFRAMES=${TIMEFRAMES}" >> "$GITHUB_ENV"' in text
    assert '--symbols "${SMC_BENCH_SYMBOLS}"' in text
    assert '--timeframes "${SMC_BENCH_TIMEFRAMES}"' in text
