"""Pin the C12 trigger gate to the C8 Phase-B criteria.

The C12 RL-execution gate is only safe once a family has reached
**Phase-B (live_small)**, not Phase-A (paper). This anchor ensures
that the numeric thresholds in :mod:`scripts.check_c12_trigger`
(``MIN_LIVE_DAYS``, ``MIN_LIVE_TRADES``) cannot silently drift away
from the runbook contract encoded in
``scripts.run_smc_live_incubation.PHASE_B_CRITERIA``.

If anyone lowers the C12 thresholds back toward Phase-A (e.g. 28d),
this test will fire and force a deliberate review.

stdlib only — no heavy imports.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_c12_trigger  # noqa: E402
from run_smc_live_incubation import PHASE_B_CRITERIA  # noqa: E402


def test_c12_min_live_days_matches_phase_b_runbook() -> None:
    assert check_c12_trigger.MIN_LIVE_DAYS == PHASE_B_CRITERIA.min_phase_days, (
        "C12 trigger MIN_LIVE_DAYS must mirror PHASE_B_CRITERIA.min_phase_days. "
        "Phase-A (paper, 28d) is NOT sufficient for RL hand-off."
    )


def test_c12_min_live_trades_matches_phase_b_runbook() -> None:
    assert (
        check_c12_trigger.MIN_LIVE_TRADES
        == PHASE_B_CRITERIA.min_trades_closed
    ), (
        "C12 trigger MIN_LIVE_TRADES must mirror "
        "PHASE_B_CRITERIA.min_trades_closed."
    )


def test_c12_acceptable_drift_verdicts_match_phase_b() -> None:
    assert set(check_c12_trigger.ACCEPTABLE_DRIFT_VERDICTS) == set(
        PHASE_B_CRITERIA.require_drift_verdict_in
    ), (
        "C12 ACCEPTABLE_DRIFT_VERDICTS must mirror "
        "PHASE_B_CRITERIA.require_drift_verdict_in."
    )
