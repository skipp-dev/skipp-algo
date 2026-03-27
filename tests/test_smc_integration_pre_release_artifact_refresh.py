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
