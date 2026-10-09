"""Tests for the C12 trigger-gate check.

Verifies that the script:

1. correctly returns BLOCKED when the public calibration report shows
   ``awaiting_first_run`` (today's state),
2. correctly returns GREEN when at least one family meets all gate
   criteria (Phase-B-aligned: >=90 live days, >=30 trades,
   kill_switch=0, drift verdict in pass/acceptable),
3. correctly returns UNEVALUABLE when the report is missing or has a
   schema violation,
4. correctly returns BLOCKED with a fine-grained failure breakdown
   when individual gate criteria are unmet.

stdlib only — no heavy imports.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_c12_trigger


def _qualified_family(**overrides: object) -> dict:
    """Build a minimal family payload that satisfies all gate criteria."""
    base: dict = {
        "name": "BOS",
        "live_days": 120,
        "n_trades": 45,
        "kill_switch_fires": 0,
        "drift_verdict": "pass",
    }
    base.update(overrides)
    return base


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
                    _qualified_family(name="BOS", live_days=7),
                    _qualified_family(name="OB", live_days=14),
                ],
            }
        )
    )
    result = check_c12_trigger.evaluate_trigger(report)
    assert result.status == "BLOCKED"
    assert result.families_evaluated == 2
    assert result.families_live_qualified == 0
    assert result.failure_breakdown["live_days_below_threshold"] == 2


def test_trigger_green_when_one_family_meets_all_criteria(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "status": "incubating",
                "families": [
                    _qualified_family(name="BOS"),
                    _qualified_family(name="OB", live_days=14),
                ],
            }
        )
    )
    result = check_c12_trigger.evaluate_trigger(report)
    assert result.status == "GREEN"
    assert result.families_live_qualified == 1


def test_trigger_blocked_when_only_live_days_meet_threshold(tmp_path: Path) -> None:
    """Phase-A semantics (live-days only) must NOT trip the gate."""
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "status": "incubating",
                "families": [{"name": "BOS", "live_days": 120}],
            }
        )
    )
    result = check_c12_trigger.evaluate_trigger(report)
    assert result.status == "BLOCKED"
    assert "n_trades_missing" in result.failure_breakdown
    assert "kill_switch_fires_missing" in result.failure_breakdown
    assert "drift_verdict_missing" in result.failure_breakdown


def test_trigger_blocked_when_kill_switch_has_fired(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "status": "incubating",
                "families": [_qualified_family(kill_switch_fires=1)],
            }
        )
    )
    result = check_c12_trigger.evaluate_trigger(report)
    assert result.status == "BLOCKED"
    assert result.failure_breakdown.get("kill_switch_has_fired") == 1


def test_trigger_blocked_when_drift_verdict_unacceptable(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "status": "incubating",
                "families": [_qualified_family(drift_verdict="warn")],
            }
        )
    )
    result = check_c12_trigger.evaluate_trigger(report)
    assert result.status == "BLOCKED"
    assert result.failure_breakdown.get("drift_verdict_unacceptable") == 1


def test_trigger_blocked_when_n_trades_too_low(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_text(
        json.dumps(
            {
                "status": "incubating",
                "families": [_qualified_family(n_trades=10)],
            }
        )
    )
    result = check_c12_trigger.evaluate_trigger(report)
    assert result.status == "BLOCKED"
    assert result.failure_breakdown.get("n_trades_below_threshold") == 1


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


def test_trigger_unevaluable_when_root_is_not_object(tmp_path: Path) -> None:
    report = tmp_path / "list_root.json"
    report.write_text(json.dumps([1, 2, 3]))
    result = check_c12_trigger.evaluate_trigger(report)
    assert result.status == "UNEVALUABLE"
    assert any("root" in r for r in result.reasons)


def test_trigger_unevaluable_when_families_is_not_a_list(tmp_path: Path) -> None:
    """Schema violation must surface as UNEVALUABLE, never BLOCKED."""
    report = tmp_path / "bad_families.json"
    report.write_text(
        json.dumps({"status": "incubating", "families": "BOS,OB"})
    )
    result = check_c12_trigger.evaluate_trigger(report)
    assert result.status == "UNEVALUABLE"
    assert any("'families'" in r for r in result.reasons)


def test_trigger_skips_non_dict_family_entries(tmp_path: Path) -> None:
    report = tmp_path / "mixed.json"
    report.write_text(
        json.dumps(
            {
                "status": "incubating",
                "families": [
                    "garbage",
                    42,
                    _qualified_family(name="BOS"),
                ],
            }
        )
    )
    result = check_c12_trigger.evaluate_trigger(report)
    assert result.status == "GREEN"
    assert result.invalid_families == 2


def test_trigger_blocked_when_metrics_are_non_finite(tmp_path: Path) -> None:
    """Copilot #301: NaN/Inf in numeric metrics must NOT slip past the gate.

    Python's ``json`` accepts ``NaN``/``Infinity`` literals by default;
    if those land in ``live_days`` / ``n_trades``, naive float
    coercion would let ``NaN < MIN_LIVE_DAYS`` evaluate to False
    (every NaN comparison is False) — silently letting a poisoned
    family qualify. The gate must instead treat non-finite values
    as unparseable and BLOCK deterministically.
    """
    report = tmp_path / "nan_inf.json"
    # ``allow_nan=True`` is the json module default; we make it explicit
    # so a future tightening on the producer side doesn't mask the test.
    report.write_text(
        json.dumps(
            {
                "status": "incubating",
                "families": [
                    {
                        "name": "BOS",
                        "live_days": float("nan"),
                        "n_trades": float("inf"),
                        "kill_switch_fires": 0,
                        "drift_verdict": "pass",
                    }
                ],
            },
            allow_nan=True,
        )
    )
    result = check_c12_trigger.evaluate_trigger(report)
    assert result.status == "BLOCKED"
    assert result.failure_breakdown.get("live_days_unparseable", 0) >= 1
    assert result.failure_breakdown.get("n_trades_missing", 0) >= 1


def test_trigger_blocked_when_n_trades_is_fractional(tmp_path: Path) -> None:
    """Copilot #301: counts must be whole numbers; ``30.5`` is upstream defect."""
    report = tmp_path / "fractional.json"
    report.write_text(
        json.dumps(
            {
                "status": "incubating",
                "families": [_qualified_family(name="BOS", n_trades=30.5)],
            }
        )
    )
    result = check_c12_trigger.evaluate_trigger(report)
    assert result.status == "BLOCKED"
    assert result.failure_breakdown.get("n_trades_missing", 0) >= 1


def test_resolve_report_path_cli_overrides_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("CALIBRATION_REPORT_PATH", str(tmp_path / "env.json"))
    cli_target = tmp_path / "cli.json"
    resolved = check_c12_trigger._resolve_report_path(str(cli_target))
    assert resolved == cli_target.resolve()


def test_resolve_report_path_env_used_when_no_cli(tmp_path: Path, monkeypatch) -> None:
    env_target = tmp_path / "env.json"
    monkeypatch.setenv("CALIBRATION_REPORT_PATH", str(env_target))
    resolved = check_c12_trigger._resolve_report_path(None)
    assert resolved == env_target.resolve()


def test_resolve_report_path_default_when_neither(monkeypatch) -> None:
    monkeypatch.delenv("CALIBRATION_REPORT_PATH", raising=False)
    resolved = check_c12_trigger._resolve_report_path(None)
    assert resolved == check_c12_trigger.DEFAULT_DASHBOARD_REPORT


def test_live_calibration_report_blocked_today() -> None:
    """Sanity check against the actual repo state — must be BLOCKED."""
    result = check_c12_trigger.evaluate_trigger()
    assert result.status in {"BLOCKED", "UNEVALUABLE"}, (
        "C12 trigger gate must NOT be GREEN until live incubation runs. "
        f"Got status={result.status}, reasons={result.reasons}"
    )


def test_trigger_unevaluable_on_invalid_utf8(tmp_path: Path) -> None:
    """Non-UTF-8 bytes must surface as UNEVALUABLE, not crash."""
    report = tmp_path / "latin1.json"
    report.write_bytes(b'{"status": "f\xfcr"}')  # latin-1 'ü', invalid utf-8
    result = check_c12_trigger.evaluate_trigger(report)
    assert result.status == "UNEVALUABLE"
    assert any("UTF-8" in r for r in result.reasons)
