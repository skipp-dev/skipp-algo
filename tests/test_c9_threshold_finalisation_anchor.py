"""C9 Live-Retune-Anker — fires *exactly when* the live sample is
sufficient to recalibrate **and** the detector alphas are still only
synthetic-tuned.

History: the original bauchgefühl literals (mean shift ``0.3``,
variance ratio ``0.5``/``2.0``) were replaced on 2026-06-11 by
p-value detectors (Welch-t / Brown-Forsythe) whose alpha ladder was
validated against the mixed-distribution synthetic episode bank
(structural part of issue #298). The *live* re-tune — alphas
calibrated against ≥ 90 days of real outcome windows — is still
outstanding; ``scripts.c9_threshold_replay.CALIBRATION_SOURCE``
records the provenance.

Until the C12 trigger flips GREEN this test is a no-op pass; the
moment it does while ``CALIBRATION_SOURCE`` still reads
``"synthetic"``, CI fails and the team must close
https://github.com/skippALGO/skipp-algo/issues/298 before further
public-calibration releases.

Why an anchor and not just an open issue?
The C-sprint deep review identified deferred threshold work as MAJOR
risk: prose FIXMEs + deferred GitHub issues are easily forgotten. This
test makes the deferral CI-checkable so it cannot quietly outlive its
precondition.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scripts import c9_threshold_replay
from scripts.check_c12_trigger import MIN_LIVE_DAYS, MIN_LIVE_TRADES, evaluate_trigger


def test_documented_precondition_matches_the_gate() -> None:
    """Every prose statement of the window must quote the real gate.

    This file used to describe the precondition as a 28-day window while
    ``check_c12_trigger`` has required ``MIN_LIVE_DAYS = 90`` (and a trade
    count the prose never mentioned at all). A deferral anchor that
    misstates its own release condition invites the reader to conclude it
    is due when it is not — the numbers here are the only thing telling a
    human when #298 may be worked. Derive the check from the constant so
    the next change to the gate has to update the prose with it.
    """
    # \b so sprint names ("the C8 live-incubation backfill") are not read as
    # a quoted window -- C8 has no word boundary before the digit.
    quoted_days = re.compile(r"\b(\d+)\s+live-incubation")
    surfaces = (
        Path(__file__),
        Path(__file__).resolve().parents[1] / "docs" / "c9_threshold_tuning.md",
    )
    seen = 0
    for path in surfaces:
        found = quoted_days.findall(path.read_text(encoding="utf-8"))
        seen += len(found)
        assert all(int(day) == MIN_LIVE_DAYS for day in found), (
            f"{path.name} quotes a live-incubation window of {sorted(set(found))} "
            f"but check_c12_trigger.MIN_LIVE_DAYS is {MIN_LIVE_DAYS}"
        )
    assert seen, "expected the precondition to be stated in prose somewhere"


def test_calibration_source_is_a_known_value() -> None:
    """Sanity pin: the provenance marker only takes documented values.

    ``"synthetic"`` — alphas validated on the synthetic episode bank
    only (today's state). ``"live"`` — alphas re-tuned against the
    locked-in live windows; flipping to this value is the PR that
    closes issue #298, and that PR should also delete/retire this
    anchor file.
    """
    assert c9_threshold_replay.CALIBRATION_SOURCE in {"synthetic", "live"}


def test_anchor_fires_when_live_sample_sufficient_and_still_synthetic() -> None:
    """The anchor: as soon as the C12 trigger flips to GREEN (≥ 1
    family with ≥ 90 live-incubation days AND ≥ 30 closed trades) AND
    the detector alphas are still synthetic-tuned, this test fails.

    Failure means: the live sample is now sufficient to recalibrate.
    Re-run ``scripts/c9_threshold_replay.py`` against the locked-in
    baseline + live windows from the C8 incubation cron, lock the
    winning alpha ladder into ``drift_alert.compute_drift_report``,
    flip ``CALIBRATION_SOURCE`` to ``"live"`` and close
    https://github.com/skippALGO/skipp-algo/issues/298.

    Today (no families have produced live outcomes yet) this is a
    no-op pass.
    """
    result = evaluate_trigger()
    if result.status == "GREEN" and c9_threshold_replay.CALIBRATION_SOURCE == "synthetic":
        pytest.fail(
            f"C12 trigger is GREEN (≥ 1 family with ≥ {MIN_LIVE_DAYS} "
            f"live-incubation days and ≥ {MIN_LIVE_TRADES} closed trades) "
            "but scripts/c9_threshold_replay.py::CALIBRATION_SOURCE "
            "still reads 'synthetic'. The Welch-t / Brown-Forsythe alpha "
            "ladder must now be re-tuned against the live sample: run the "
            "threshold replay on the locked-in live windows, update the "
            "compute_drift_report defaults, flip CALIBRATION_SOURCE to "
            "'live', and close issue #298."
        )


def test_anchor_passes_silently_while_trigger_is_blocked() -> None:
    """Today the trigger is BLOCKED, so the anchor must remain a
    no-op pass regardless of the calibration provenance.
    """
    result = evaluate_trigger()
    if result.status != "GREEN":
        # Anchor is dormant — assertion holds trivially.
        return
    pytest.skip("C12 trigger is GREEN; the actual anchor test runs.")
