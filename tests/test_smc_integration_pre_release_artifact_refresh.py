from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from scripts import run_smc_pre_release_artifact_refresh as refresh_script


class _Parser:
    def __init__(self, args: Namespace):
        self._args = args

    def parse_args(self) -> Namespace:
        return self._args


def test_pre_release_refresh_generates_reference_artifacts_for_each_timeframe(monkeypatch, tmp_path: Path) -> None:
    captured_reports: list[dict] = []
    calls: list[dict] = []

    monkeypatch.setattr(
        refresh_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                symbols="IBG,AAPL",
                timeframes="5m,15m",
                structure_artifacts_dir=str(tmp_path / "reports" / "smc_structure_artifacts"),
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
        lambda **kwargs: {
            "workbook_path": Path("/tmp/workbook.xlsx"),
            "export_bundle_root": Path("/tmp/exports"),
            "structure_artifacts_dir": tmp_path / "reports" / "smc_structure_artifacts",
            "resolution_mode": "explicit",
            "warnings": [],
            "errors": [],
        },
    )

    def _refresh_stub(**kwargs):
        calls.append(kwargs)
        symbols = list(kwargs["symbols"])
        return {
            "artifacts": [
                {
                    "symbol": symbol,
                    "timeframe": kwargs["timeframe"],
                    "coverage_mode": "bundle",
                    "bos_count": 1,
                    "orderblocks_count": 0,
                    "fvg_count": 0,
                    "liquidity_sweeps_count": 0,
                    "has_bos": True,
                    "has_orderblocks": False,
                    "has_fvg": False,
                    "has_liquidity_sweeps": False,
                }
                for symbol in symbols
            ],
            "counts": {
                "symbols_requested": len(symbols),
                "artifacts_written": len(symbols),
                "errors": 0,
            },
            "errors": [],
            "warnings": [],
            "timeframe": kwargs["timeframe"],
        }

    monkeypatch.setattr(refresh_script, "write_structure_artifacts_from_workbook", _refresh_stub)
    monkeypatch.setattr(refresh_script, "_render", lambda report, output: captured_reports.append(report))

    rc = refresh_script.main()

    assert rc == 0
    assert len(calls) == 2
    assert {call["timeframe"] for call in calls} == {"5m", "15m"}
    assert captured_reports[-1]["overall_status"] == "ok"


def test_pre_release_refresh_fails_when_reference_set_is_incomplete(monkeypatch, tmp_path: Path) -> None:
    captured_reports: list[dict] = []

    monkeypatch.setattr(
        refresh_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                symbols="IBG,AAPL",
                timeframes="15m",
                structure_artifacts_dir=str(tmp_path / "reports" / "smc_structure_artifacts"),
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
        lambda **kwargs: {
            "workbook_path": None,
            "export_bundle_root": None,
            "structure_artifacts_dir": tmp_path / "reports" / "smc_structure_artifacts",
            "resolution_mode": "missing",
            "warnings": [],
            "errors": [{"code": "WORKBOOK_NOT_FOUND"}],
        },
    )
    monkeypatch.setattr(
        refresh_script,
        "write_structure_artifacts_from_workbook",
        lambda **kwargs: {
            "counts": {
                "symbols_requested": 2,
                "artifacts_written": 1,
                "errors": 1,
            },
            "errors": [{"code": "MISSING_STRUCTURE_INPUTS"}],
            "warnings": [],
            "timeframe": kwargs["timeframe"],
        },
    )
    monkeypatch.setattr(refresh_script, "_render", lambda report, output: captured_reports.append(report))

    rc = refresh_script.main()

    assert rc == 1
    assert captured_reports[-1]["overall_status"] == "fail"
    assert any(item.get("code") in {"REFRESH_MANIFEST_ERRORS", "REFRESH_INCOMPLETE_REFERENCE_SET"} for item in captured_reports[-1]["failures"])


def test_pre_release_refresh_soft_skips_on_manifest_errors_when_inputs_missing(
    monkeypatch, tmp_path: Path
) -> None:
    """F-V8-followup (2026-05-02): widen soft-skip predicate.

    When `--soft-skip-on-missing-inputs` is set and every failure is a
    missing-input failure (REFRESH_MANIFEST_ERRORS /
    REFRESH_INCOMPLETE_REFERENCE_SET in this scenario), the script must
    return exit code 78 so the smc-deeper-integration-gates workflow can
    promote the failure into a `::warning::` instead of a hard failure.

    Regression for run 25248713567 where the predicate previously only
    matched `REFRESH_EXECUTION_FAILED + "manifest"` and therefore exited
    1 even with `--soft-skip-on-missing-inputs`.
    """
    captured_reports: list[dict] = []

    monkeypatch.setattr(
        refresh_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                symbols="IBG,AAPL",
                timeframes="15m",
                structure_artifacts_dir=str(tmp_path / "reports" / "smc_structure_artifacts"),
                workbook_path="",
                export_bundle_root="",
                structure_profile="hybrid_default",
                allow_missing_inputs=False,
                warn_on_empty_artifacts=False,
                soft_skip_on_missing_inputs=True,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(
        refresh_script,
        "resolve_structure_artifact_inputs",
        lambda **kwargs: {
            "workbook_path": None,
            "export_bundle_root": None,
            "structure_artifacts_dir": tmp_path / "reports" / "smc_structure_artifacts",
            "resolution_mode": "missing",
            "warnings": [],
            "errors": [{"code": "WORKBOOK_NOT_FOUND"}],
        },
    )
    monkeypatch.setattr(
        refresh_script,
        "write_structure_artifacts_from_workbook",
        lambda **kwargs: {
            "counts": {
                "symbols_requested": 2,
                "artifacts_written": 1,
                "errors": 1,
            },
            "errors": [{"code": "MISSING_STRUCTURE_INPUTS"}],
            "warnings": [],
            "timeframe": kwargs["timeframe"],
        },
    )
    monkeypatch.setattr(
        refresh_script, "_render", lambda report, output: captured_reports.append(report)
    )

    rc = refresh_script.main()

    assert rc == 78, "soft-skip should yield exit 78 (skipped) when only missing-input failures present"
    assert captured_reports[-1]["overall_status"] == "skipped"


def test_pre_release_refresh_fails_when_artifacts_are_structurally_empty(monkeypatch, tmp_path: Path) -> None:
    captured_reports: list[dict] = []

    monkeypatch.setattr(
        refresh_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                symbols="IBG,AAPL",
                timeframes="15m",
                structure_artifacts_dir=str(tmp_path / "reports" / "smc_structure_artifacts"),
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
        lambda **kwargs: {
            "workbook_path": Path("/tmp/workbook.xlsx"),
            "export_bundle_root": Path("/tmp/exports"),
            "structure_artifacts_dir": tmp_path / "reports" / "smc_structure_artifacts",
            "resolution_mode": "explicit",
            "warnings": [],
            "errors": [],
        },
    )
    monkeypatch.setattr(
        refresh_script,
        "write_structure_artifacts_from_workbook",
        lambda **kwargs: {
            "artifacts": [
                {
                    "symbol": "IBG",
                    "timeframe": kwargs["timeframe"],
                    "coverage_mode": "none",
                    "bos_count": 0,
                    "orderblocks_count": 0,
                    "fvg_count": 0,
                    "liquidity_sweeps_count": 0,
                    "has_bos": False,
                    "has_orderblocks": False,
                    "has_fvg": False,
                    "has_liquidity_sweeps": False,
                },
                {
                    "symbol": "AAPL",
                    "timeframe": kwargs["timeframe"],
                    "coverage_mode": "none",
                    "bos_count": 0,
                    "orderblocks_count": 0,
                    "fvg_count": 0,
                    "liquidity_sweeps_count": 0,
                    "has_bos": False,
                    "has_orderblocks": False,
                    "has_fvg": False,
                    "has_liquidity_sweeps": False,
                },
            ],
            "counts": {
                "symbols_requested": 2,
                "artifacts_written": 2,
                "errors": 0,
            },
            "errors": [],
            "warnings": [],
            "timeframe": kwargs["timeframe"],
        },
    )
    monkeypatch.setattr(refresh_script, "_render", lambda report, output: captured_reports.append(report))

    rc = refresh_script.main()

    assert rc == 1
    assert captured_reports[-1]["overall_status"] == "fail"
    assert {
        "code": "REFRESH_EMPTY_REFERENCE_ARTIFACTS",
        "timeframe": "15m",
        "artifacts_evaluated": 2,
        "coverage_modes": ["none"],
    } in captured_reports[-1]["failures"]


def test_pre_release_refresh_warns_when_empty_artifacts_are_allowed(monkeypatch, tmp_path: Path) -> None:
    captured_reports: list[dict] = []

    monkeypatch.setattr(
        refresh_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                symbols="IBG,AAPL",
                timeframes="15m",
                structure_artifacts_dir=str(tmp_path / "reports" / "smc_structure_artifacts"),
                workbook_path="",
                export_bundle_root="",
                structure_profile="hybrid_default",
                allow_missing_inputs=False,
                warn_on_empty_artifacts=True,
                output="-",
            )
        ),
    )
    monkeypatch.setattr(
        refresh_script,
        "resolve_structure_artifact_inputs",
        lambda **kwargs: {
            "workbook_path": Path("/tmp/workbook.xlsx"),
            "export_bundle_root": Path("/tmp/exports"),
            "structure_artifacts_dir": tmp_path / "reports" / "smc_structure_artifacts",
            "resolution_mode": "explicit",
            "warnings": [],
            "errors": [],
        },
    )
    monkeypatch.setattr(
        refresh_script,
        "write_structure_artifacts_from_workbook",
        lambda **kwargs: {
            "artifacts": [
                {
                    "symbol": "IBG",
                    "timeframe": kwargs["timeframe"],
                    "coverage_mode": "none",
                    "bos_count": 0,
                    "orderblocks_count": 0,
                    "fvg_count": 0,
                    "liquidity_sweeps_count": 0,
                    "has_bos": False,
                    "has_orderblocks": False,
                    "has_fvg": False,
                    "has_liquidity_sweeps": False,
                },
                {
                    "symbol": "AAPL",
                    "timeframe": kwargs["timeframe"],
                    "coverage_mode": "none",
                    "bos_count": 0,
                    "orderblocks_count": 0,
                    "fvg_count": 0,
                    "liquidity_sweeps_count": 0,
                    "has_bos": False,
                    "has_orderblocks": False,
                    "has_fvg": False,
                    "has_liquidity_sweeps": False,
                },
            ],
            "counts": {
                "symbols_requested": 2,
                "artifacts_written": 2,
                "errors": 0,
            },
            "errors": [],
            "warnings": [],
            "timeframe": kwargs["timeframe"],
        },
    )
    monkeypatch.setattr(refresh_script, "_render", lambda report, output: captured_reports.append(report))

    rc = refresh_script.main()

    assert rc == 0
    assert captured_reports[-1]["overall_status"] == "warn"
    assert captured_reports[-1]["failures"] == []
    assert {
        "code": "REFRESH_EMPTY_REFERENCE_ARTIFACTS",
        "timeframe": "15m",
        "artifacts_evaluated": 2,
        "coverage_modes": ["none"],
        "message": "Refreshed reference artifacts are structurally empty for this timeframe.",
        "promoted_to_warning_by": "warn_on_empty_artifacts",
    } in captured_reports[-1]["warnings"]


def test_pre_release_refresh_warns_and_filters_unavailable_reference_symbols(monkeypatch, tmp_path: Path) -> None:
    captured_reports: list[dict] = []
    captured_symbols: list[list[str]] = []

    monkeypatch.setattr(
        refresh_script,
        "build_parser",
        lambda: _Parser(
            Namespace(
                symbols="AAPL,LIN",
                timeframes="15m",
                structure_artifacts_dir=str(tmp_path / "reports" / "smc_structure_artifacts"),
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
        lambda **kwargs: {
            "workbook_path": Path("/tmp/workbook.xlsx"),
            "export_bundle_root": None,
            "structure_artifacts_dir": tmp_path / "reports" / "smc_structure_artifacts",
            "resolution_mode": "canonical",
            "warnings": [],
            "errors": [],
        },
    )
    monkeypatch.setattr(refresh_script, "_discover_available_reference_symbols", lambda **kwargs: ["AAPL"])

    def _refresh_stub(**kwargs):
        symbols = list(kwargs["symbols"])
        captured_symbols.append(symbols)
        return {
            "artifacts": [
                {
                    "symbol": symbol,
                    "timeframe": kwargs["timeframe"],
                    "coverage_mode": "bundle",
                    "bos_count": 1,
                    "orderblocks_count": 0,
                    "fvg_count": 0,
                    "liquidity_sweeps_count": 0,
                    "has_bos": True,
                    "has_orderblocks": False,
                    "has_fvg": False,
                    "has_liquidity_sweeps": False,
                }
                for symbol in symbols
            ],
            "counts": {
                "symbols_requested": len(symbols),
                "artifacts_written": len(symbols),
                "errors": 0,
            },
            "errors": [],
            "warnings": [],
            "timeframe": kwargs["timeframe"],
        }

    monkeypatch.setattr(refresh_script, "write_structure_artifacts_from_workbook", _refresh_stub)
    monkeypatch.setattr(refresh_script, "_render", lambda report, output: captured_reports.append(report))

    rc = refresh_script.main()

    assert rc == 0
    assert captured_symbols == [["AAPL"]]
    assert captured_reports[-1]["overall_status"] == "warn"
    assert {
        "code": "REFERENCE_SYMBOLS_UNAVAILABLE_IN_SOURCE",
        "timeframe": "15m",
        "symbols_missing": ["LIN"],
        "symbols_available": ["AAPL"],
        "message": "Resolved refresh inputs do not cover every requested reference symbol; continuing with the available subset.",
    } in captured_reports[-1]["warnings"]
