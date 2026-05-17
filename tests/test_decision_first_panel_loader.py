"""Sprint W1.c — decision-first panel ↔ promotion-gate report loader."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from dashboard.decision_first_panel import (
    load_decisions_from_report,
    render_panel,
)


def _sample_report() -> dict:
    return {
        "schema_version": 1,
        "gate_schema_version": 2,
        "generated_at": "2026-05-17T18:00:00+00:00",
        "strict_provenance": True,
        "decisions": [
            {
                "schema_version": 2,
                "family": "BOS",
                "promoted": True,
                "posture": "green",
                "blockers": [],
                "metrics": {"brier": 0.18},
                "provenance": {"wf_scheme": "purged_kfold"},
            },
            {
                "schema_version": 2,
                "family": "OB",
                "promoted": False,
                "posture": "orange",
                "blockers": [
                    {
                        "check": "psi_slope_threshold",
                        "severity": "blocker",
                        "observed": 0.20,
                        "threshold": 0.05,
                        "message": "psi_slope=0.2000 fails <= 0.0500",
                    }
                ],
                "metrics": {"psi_slope": 0.20},
                "provenance": {},
            },
        ],
    }


def test_load_decisions_round_trips_report(tmp_path: Path) -> None:
    p = tmp_path / "report.json"
    p.write_text(json.dumps(_sample_report()), encoding="utf-8")
    decisions = load_decisions_from_report(p)
    assert [d["family"] for d in decisions] == ["BOS", "OB"]
    assert decisions[0]["promoted"] is True
    assert decisions[1]["posture"] == "orange"


def test_load_decisions_rejects_non_dict_top_level(tmp_path: Path) -> None:
    p = tmp_path / "report.json"
    p.write_text(json.dumps([{"family": "BOS"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="must be a dict with a 'decisions' key"):
        load_decisions_from_report(p)


def test_load_decisions_rejects_non_list_decisions(tmp_path: Path) -> None:
    p = tmp_path / "report.json"
    p.write_text(json.dumps({"decisions": {"family": "BOS"}}), encoding="utf-8")
    with pytest.raises(ValueError, match="'decisions' must be a list"):
        load_decisions_from_report(p)


def test_panel_renders_loaded_decisions(tmp_path: Path) -> None:
    p = tmp_path / "report.json"
    p.write_text(json.dumps(_sample_report()), encoding="utf-8")
    decisions = load_decisions_from_report(p)
    out = render_panel(decisions)
    assert "[GREEN]" in out
    assert "[ORANGE]" in out
    assert "BOS" in out
    assert "OB" in out
    assert "psi_slope_threshold" in out
