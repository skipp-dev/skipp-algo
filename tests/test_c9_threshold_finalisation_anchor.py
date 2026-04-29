"""C9 Bauchgefühl-Anker — fires *exactly when* the live sample is
sufficient to recalibrate **and** the interim thresholds are still
hardcoded.

Until both conditions are true this test is a no-op pass; the moment
both flip true, CI fails and the team must close
https://github.com/skippALGO/skipp-algo/issues/298 before further
public-calibration releases.

Why an anchor and not just an open issue?
The C-sprint deep review identified the C9 mean-shift / variance-ratio
literals (``0.3``, ``0.5``, ``2.0``) as MAJOR risk: prose FIXMEs +
deferred GitHub issues are easily forgotten. This test makes the
deferral CI-checkable so the deferral cannot quietly outlive its
precondition.
"""

from __future__ import annotations

import inspect
import re

import pytest

from scripts import c9_threshold_replay
from scripts.check_c12_trigger import evaluate_trigger

_BAUCHGEFUEHL_LITERALS = (
    # Detector 3 — mean-shift threshold in σ-units of baseline.
    re.compile(r"mean_shift\s*>=\s*0\.3\b"),
    # Detector 4 — variance ratio outer bounds.
    re.compile(r"ratio\s*<\s*0\.5\b"),
    re.compile(r"ratio\s*>\s*2\.0\b"),
)


def _episode_fires_source() -> str:
    return inspect.getsource(c9_threshold_replay._episode_fires)


def test_bauchgefuehl_literals_are_still_present_today() -> None:
    """Sanity pin: today the source still contains the three literals.

    If this fails, somebody has already replaced the bauchgefühl
    detectors and the anchor test below should be deleted/updated.
    """
    src = _episode_fires_source()
    missing = [p.pattern for p in _BAUCHGEFUEHL_LITERALS if p.search(src) is None]
    assert not missing, (
        "expected bauchgefühl literals no longer present in "
        "_episode_fires — has C9/T7 been finalised? If yes, delete "
        f"this anchor test. Missing patterns: {missing}"
    )


def test_anchor_fires_when_live_sample_sufficient_and_literals_unchanged() -> None:
    """The anchor: as soon as the C12 trigger flips to GREEN (≥ 1
    family with ≥ 28 live-incubation days) AND the bauchgefühl
    literals are still present, this test fails.

    Failure means: live sample is now sufficient to recalibrate, and
    https://github.com/skippALGO/skipp-algo/issues/298 must be closed
    before the next public-calibration release.

    Today (no families have produced live outcomes yet) this is a
    no-op pass.
    """
    result = evaluate_trigger()
    src = _episode_fires_source()
    literals_unchanged = all(p.search(src) is not None for p in _BAUCHGEFUEHL_LITERALS)

    if result.status == "GREEN" and literals_unchanged:
        pytest.fail(
            "C12 trigger is GREEN (≥ 1 family with ≥ 28 live-incubation "
            "days) but the C9 bauchgefühl literals (0.3 / 0.5 / 2.0) "
            "in scripts/c9_threshold_replay.py::_episode_fires are "
            "still unchanged. Close issue #298 by re-tuning detector-3 "
            "(mean-shift) and detector-4 (variance ratio) against the "
            "live sample, then update or delete this anchor test."
        )


def test_anchor_passes_silently_while_trigger_is_blocked() -> None:
    """Today the trigger is BLOCKED, so the anchor must remain a
    no-op pass regardless of the literal state.
    """
    result = evaluate_trigger()
    if result.status != "GREEN":
        # Anchor is dormant — assertion holds trivially.
        return
    pytest.skip("C12 trigger is GREEN; the actual anchor test runs.")
