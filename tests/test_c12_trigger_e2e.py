"""End-to-end producer/consumer test for the C12 trigger gate.

Closes the producer/consumer gap surfaced by the 2026-04-27 deep
review: ``scripts/check_c12_trigger.py`` reads ``families[]`` from the
public calibration report, but no producer in the repo was actually
emitting that block. Schema 1.3.0 of
:func:`scripts.emit_public_calibration_report.build_public_report`
adds a ``families`` kwarg; this test exercises the GREEN and BLOCKED
paths through the *real* producer + consumer stack so future
refactors that drift one side can't silently re-open the gap.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.check_c12_trigger import (
    ACCEPTABLE_DRIFT_VERDICTS,
    MIN_LIVE_DAYS,
    MIN_LIVE_TRADES,
    evaluate_trigger,
)
from scripts.emit_public_calibration_report import (
    build_public_report,
    write_report,
)


def _qualified_family(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "name": "BOS",
        "live_days": MIN_LIVE_DAYS + 30,
        "n_trades": MIN_LIVE_TRADES + 15,
        "kill_switch_fires": 0,
        "drift_verdict": next(iter(sorted(ACCEPTABLE_DRIFT_VERDICTS))),
    }
    base.update(overrides)
    return base


_MISSING = object()


def _emit_and_load(
    tmp_path: Path,
    families: list[dict[str, object]] | None,
    *,
    cal_payload: object = _MISSING,
):
    # build_public_report short-circuits to status='awaiting_first_run'
    # when cal_payload is None, and the trigger evaluator BLOCKs there
    # before reading families. The producer/consumer roundtrip tests
    # therefore default to a minimally-valid payload to reach
    # status='ok'; pass ``cal_payload=None`` explicitly to exercise
    # the awaiting_first_run branch.
    if cal_payload is _MISSING:
        cal_payload = _MIN_CAL_PAYLOAD
    report = build_public_report(
        cal_payload=cal_payload,  # type: ignore[arg-type]
        source_path=None,
        source_commit_sha="deadbeef",
        source_workflow_run="42",
        families=families,
    )
    out = tmp_path / "calibration_report_public.json"
    write_report(report, out)
    return report, out


# Smallest payload that drives ``build_public_report`` to ``status='ok'``
# (needs ``family_weights`` plus the keys consumed by the metric/n_events
# extractors). Keep this tight — the goal is producer→consumer wiring,
# not metric correctness.
_MIN_CAL_PAYLOAD: dict[str, object] = {
    "family_weights": {"BOS": 1.0},
    "n_events": 100,
    "weighted_hit_rate": 0.55,
    "metrics": {},
}


# --- producer schema contract --------------------------------------


def test_producer_emits_families_when_supplied(tmp_path: Path) -> None:
    report, path = _emit_and_load(tmp_path, [_qualified_family()])
    assert "families" in report
    assert isinstance(report["families"], list)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["families"] == report["families"]


def test_producer_omits_families_by_default(tmp_path: Path) -> None:
    report, _ = _emit_and_load(tmp_path, None)
    assert "families" not in report


def test_producer_rejects_non_list_families(tmp_path: Path) -> None:
    try:
        build_public_report(
            cal_payload=None,
            source_path=None,
            source_commit_sha="x",
            source_workflow_run="y",
            families="not-a-list",  # type: ignore[arg-type]
        )
    except TypeError as exc:
        assert "list" in str(exc)
    else:
        raise AssertionError("expected TypeError for non-list families")


def test_producer_rejects_family_missing_required_keys(tmp_path: Path) -> None:
    try:
        build_public_report(
            cal_payload=None,
            source_path=None,
            source_commit_sha="x",
            source_workflow_run="y",
            families=[{"name": "BOS"}],
        )
    except ValueError as exc:
        msg = str(exc)
        assert "missing" in msg
        assert "live_days" in msg
    else:
        raise AssertionError("expected ValueError for missing keys")


# --- producer → consumer GREEN/BLOCKED roundtrip -------------------


def test_trigger_green_via_emit_public_calibration_report(tmp_path: Path) -> None:
    """Full producer→consumer GREEN path: build_public_report → trigger."""
    _, path = _emit_and_load(
        tmp_path,
        [
            _qualified_family(name="BOS"),
            _qualified_family(name="OB", live_days=30),  # below threshold
        ],
    )
    result = evaluate_trigger(path)
    assert result.status == "GREEN", result.reasons
    assert result.families_evaluated == 2
    assert result.families_live_qualified == 1


def test_trigger_blocked_when_no_family_qualifies(tmp_path: Path) -> None:
    _, path = _emit_and_load(
        tmp_path,
        [
            _qualified_family(name="BOS", kill_switch_fires=1),
            _qualified_family(name="OB", drift_verdict="warn"),
            _qualified_family(name="FVG", n_trades=10),
        ],
    )
    result = evaluate_trigger(path)
    assert result.status == "BLOCKED", result.reasons
    assert result.families_live_qualified == 0
    assert result.failure_breakdown.get("kill_switch_has_fired") == 1
    assert result.failure_breakdown.get("drift_verdict_unacceptable") == 1
    assert result.failure_breakdown.get("n_trades_below_threshold") == 1


def test_trigger_blocked_when_families_omitted(tmp_path: Path) -> None:
    """Producer-side default (no families yet) → BLOCKED, not UNEVALUABLE."""
    _, path = _emit_and_load(tmp_path, None, cal_payload=None)
    result = evaluate_trigger(path)
    # Producer emitted status="awaiting_first_run" because cal_payload is
    # None, so the trigger short-circuits to BLOCKED — that's the correct
    # pre-Phase-B state.
    assert result.status == "BLOCKED", result.reasons
