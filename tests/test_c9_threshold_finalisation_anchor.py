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

import pytest

from scripts import c9_threshold_replay
from scripts.check_c12_trigger import evaluate_trigger


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
    family with ≥ 28 live-incubation days) AND the detector alphas are
    still synthetic-tuned, this test fails.

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
            "C12 trigger is GREEN (≥ 1 family with ≥ 28 live-incubation "
            "days) but scripts/c9_threshold_replay.py::CALIBRATION_SOURCE "
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
