"""Tests for the C12 trigger-gate check.

Verifies that the script:

1. correctly returns BLOCKED when the public calibration report shows
   ``awaiting_first_run`` (today's state),
2. correctly returns GREEN when at least one family has >= 28 live
   incubation days,
3. correctly returns UNEVALUABLE when the report is missing.

stdlib only — no heavy imports.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_c12_trigger  # noqa: E402


def test_trigger_blocked_when_awaiting_first_run(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"status": "awaiting_first_run"}))
    result = check_c12_trigger.evaluate_trigger(report)
    assert result.status == "BLOCKED"
    assert any("awaiting_first_run" in r for r in result.reasons)


def test_trigger_blocked_when_families_below_threshold(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "status": "incubating",
                "families": [
                    {"name": "BOS", "live_days": 7},
                    {"name": "OB", "live_days": 14},
                ],
            }
        )
    )
    result = check_c12_trigger.evaluate_trigger(report)
    assert result.status == "BLOCKED"
    assert result.families_evaluated == 2
    assert result.families_live_28d_plus == 0


def test_trigger_green_when_one_family_at_or_above_threshold(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "status": "incubating",
                "families": [
                    {"name": "BOS", "live_days": 30},
                    {"name": "OB", "live_days": 14},
                ],
            }
        )
    )
    result = check_c12_trigger.evaluate_trigger(report)
    assert result.status == "GREEN"
    assert result.families_live_28d_plus == 1


def test_trigger_unevaluable_when_report_missing(tmp_path: Path) -> None:
    report = tmp_path / "does_not_exist.json"
    result = check_c12_trigger.evaluate_trigger(report)
    assert result.status == "UNEVALUABLE"
    assert any("not found" in r for r in result.reasons)


def test_trigger_unevaluable_on_malformed_json(tmp_path: Path) -> None:
    report = tmp_path / "malformed.json"
    report.write_text("{not valid json")
    result = check_c12_trigger.evaluate_trigger(report)
    assert result.status == "UNEVALUABLE"
    assert any("not valid JSON" in r for r in result.reasons)


def test_live_calibration_report_blocked_today() -> None:
    """Sanity check against the actual repo state — must be BLOCKED."""
    result = check_c12_trigger.evaluate_trigger()
    assert result.status in {"BLOCKED", "UNEVALUABLE"}, (
        "C12 trigger gate must NOT be GREEN until live incubation runs. "
        f"Got status={result.status}, reasons={result.reasons}"
    )


def test_trigger_handles_unparseable_live_days(tmp_path: Path) -> None:
    """Bad ``live_days`` (None / 'N/A' / nested object) must not crash;
    the family is treated as 0 days and surfaced in the reasons.
    """
    report = tmp_path / "bad.json"
    report.write_text(
        json.dumps(
            {
                "status": "live",
                "families": [
                    {"name": "BOS", "live_days": None},
                    {"name": "OB", "live_days": "N/A"},
                    {"name": "FVG", "live_days": {"unexpected": "shape"}},
                    {"name": "SWEEP", "live_days": 5},
                ],
            }
        )
    )
    result = check_c12_trigger.evaluate_trigger(report)
    assert result.status == "BLOCKED"
    assert result.families_evaluated == 4
    assert result.families_live_28d_plus == 0
    assert any("unparseable" in r for r in result.reasons)
