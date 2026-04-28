"""Tests for ``scripts/render_ci_gate_summary.py``."""
from __future__ import annotations

import importlib
import json
import sys
import types
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "render_ci_gate_summary.py"


@pytest.fixture()
def mod() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("render_ci_gate_summary", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["render_ci_gate_summary"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Gate row extraction
# ---------------------------------------------------------------------------


class TestExtractGateRows:
    def test_release_gates_report(self, mod: types.ModuleType) -> None:
        report = {
            "report_kind": "release_gates",
            "gates": [
                {"name": "provider_health", "status": "ok"},
                {"name": "reference_bundle", "status": "ok"},
            ],
        }
        rows = mod.extract_gate_rows(report)
        assert len(rows) == 2
        assert rows[0]["name"] == "provider_health"

    def test_evidence_summary_report(self, mod: types.ModuleType) -> None:
        report = {
            "report_kind": "gate_evidence_summary",
            "green_ready": True,
            "deeper_ok_runs_in_window": 5,
            "release_ok_runs_in_window": 3,
            "criteria": {"min_deeper_ok_runs": 3, "min_release_ok_runs": 2},
        }
        rows = mod.extract_gate_rows(report)
        assert len(rows) == 3
        assert rows[0]["name"] == "evidence_readiness"
        assert rows[0]["status"] == "ok"

    def test_empty_report(self, mod: types.ModuleType) -> None:
        rows = mod.extract_gate_rows({})
        assert rows == []


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


class TestRenderGateSummary:
    def test_basic_rendering(self, mod: types.ModuleType) -> None:
        gates = [
            {"name": "provider_health", "status": "ok", "blocking": True, "details": {}},
            {"name": "measurement_lane", "status": "warn", "blocking": False, "details": {"pairs_checked": 48}},
        ]
        md = mod.render_gate_summary_markdown(
            gates,
            enforcement="hard",
            overall_status="ok",
        )
        assert "Gate Summary" in md
        assert "HARD" in md
        assert "provider_health" in md
        assert "measurement_lane" in md
        assert "48 pairs" in md

    def test_ci_mode_downgraded_detail(self, mod: types.ModuleType) -> None:
        gates = [
            {
                "name": "post_release_validation",
                "status": "fail",
                "blocking": False,
                "ci_mode_downgraded": True,
                "ci_mode_downgrade_reason": "external_tv_drift",
                "tv_failure_class": "external_tv_drift",
                "details": {"failures": [{"code": "AUTH_FAILED"}]},
            },
        ]
        md = mod.render_gate_summary_markdown(gates, enforcement="hard", overall_status="ok")
        assert "external_tv_drift" in md
        assert "downgraded" in md

    def test_enforcement_labels(self, mod: types.ModuleType) -> None:
        gates = [{"name": "test", "status": "ok", "details": {}}]
        for enforcement in ("hard", "advisory", "not-enforced"):
            md = mod.render_gate_summary_markdown(gates, enforcement=enforcement, overall_status="ok")
            assert enforcement.upper().replace("-", " ") in md


# ---------------------------------------------------------------------------
# write_to_step_summary
# ---------------------------------------------------------------------------


class TestWriteToStepSummary:
    def test_writes_when_env_set(self, mod: types.ModuleType, tmp_path: Path) -> None:
        summary_file = tmp_path / "summary.md"
        with patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": str(summary_file)}):
            result = mod.write_to_step_summary("# Test")
        assert result is True
        assert "# Test" in summary_file.read_text()

    def test_returns_false_when_no_env(self, mod: types.ModuleType) -> None:
        with patch.dict("os.environ", {}, clear=True):
            import os
            os.environ.pop("GITHUB_STEP_SUMMARY", None)
            result = mod.write_to_step_summary("# Test")
        assert result is False


# ---------------------------------------------------------------------------
# CLI main
# ---------------------------------------------------------------------------


class TestMain:
    def test_missing_report_returns_1(self, mod: types.ModuleType) -> None:
        with patch.object(
            mod,
            "build_parser",
            return_value=type("P", (), {
                "parse_args": lambda self: type("A", (), {
                    "report": "/nonexistent/report.json",
                    "enforcement": "hard",
                })()
            })(),
        ):
            result = mod.main()
        assert result == 1

    def test_valid_report_returns_0(self, mod: types.ModuleType, tmp_path: Path) -> None:
        report_path = tmp_path / "report.json"
        report_path.write_text(json.dumps({
            "report_kind": "release_gates",
            "overall_status": "ok",
            "gates": [{"name": "test", "status": "ok", "details": {}}],
        }))

        with patch.object(
            mod,
            "build_parser",
            return_value=type("P", (), {
                "parse_args": lambda self: type("A", (), {
                    "report": str(report_path),
                    "enforcement": "advisory",
                })()
            })(),
        ), patch.dict("os.environ", {}, clear=True):
            import os
            os.environ.pop("GITHUB_STEP_SUMMARY", None)
            result = mod.main()
        assert result == 0
