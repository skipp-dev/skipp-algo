"""Guard the SMC context golden-vector contract against silent drift.

``tests/fixtures/smc_context_golden.json`` is the cross-language scoring/rule
parity contract that the Pine context library (``smc_context_engine_private``,
Phase 3) must reproduce exactly. It is generated from the authoritative Python
builders by ``scripts/gen_smc_context_golden.py``.

This test regenerates the golden in-memory from the *live* builders and asserts
byte-equality with the committed file. Any change to a threshold or rule in
``smc_imbalance_lifecycle`` / ``smc_liquidity_sweeps`` / ``smc_liquidity_pools``
that is not accompanied by a deliberate regeneration trips RED here — the Python
source of truth cannot move without the frozen contract moving with it.
"""

from __future__ import annotations

import json

from scripts.gen_smc_context_golden import GOLDEN_PATH, build_golden
from scripts.smc_imbalance_lifecycle import (
    FULL_MIT_PCT,
    LIQ_VOID_MIN_SIZE_PCT,
    PARTIAL_MIT_PCT,
)
from scripts.smc_liquidity_pools import (
    CLUSTER_STRONG_COUNT,
    IMBALANCE_SIG_THRESHOLD,
    PROXIMITY_NEAR_PCT,
)
from scripts.smc_liquidity_sweeps import (
    SWEEP_DEPTH_MIN_PCT,
    SWEEP_DEPTH_STOP_HUNT_PCT,
    SWEEP_RECLAIM_MAX_BARS,
    SWEEP_VOLUME_RATIO_MIN,
)


def _frozen() -> dict:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))


def test_golden_file_matches_live_builders() -> None:
    regenerated = json.dumps(build_golden(), indent=2, sort_keys=True) + "\n"
    committed = GOLDEN_PATH.read_text(encoding="utf-8")
    assert regenerated == committed, (
        "smc_context_golden.json is stale — a Python reference builder changed. "
        "Regenerate with `python -m scripts.gen_smc_context_golden` and review the diff."
    )


def test_frozen_thresholds_match_live_constants() -> None:
    thresholds = _frozen()["_meta"]["thresholds"]
    assert thresholds["imbalance"] == {
        "PARTIAL_MIT_PCT": PARTIAL_MIT_PCT,
        "FULL_MIT_PCT": FULL_MIT_PCT,
        "LIQ_VOID_MIN_SIZE_PCT": LIQ_VOID_MIN_SIZE_PCT,
    }
    assert thresholds["sweeps"] == {
        "SWEEP_DEPTH_MIN_PCT": SWEEP_DEPTH_MIN_PCT,
        "SWEEP_RECLAIM_MAX_BARS": SWEEP_RECLAIM_MAX_BARS,
        "SWEEP_VOLUME_RATIO_MIN": SWEEP_VOLUME_RATIO_MIN,
        "SWEEP_DEPTH_STOP_HUNT_PCT": SWEEP_DEPTH_STOP_HUNT_PCT,
    }
    assert thresholds["pools"] == {
        "IMBALANCE_SIG_THRESHOLD": IMBALANCE_SIG_THRESHOLD,
        "PROXIMITY_NEAR_PCT": PROXIMITY_NEAR_PCT,
        "CLUSTER_STRONG_COUNT": CLUSTER_STRONG_COUNT,
    }


def test_stop_hunt_depth_gate_is_an_inclusive_clean_three_tenths() -> None:
    """The STOP_HUNT depth gate is its own constant, and 0.3 means 0.3.

    It used to read ``SWEEP_DEPTH_MIN_PCT * 3``. ``0.1 * 3`` is
    0.30000000000000004 in IEEE-754, so a depth of exactly 0.3 fell just short and
    classified LIQUIDITY_GRAB — an artifact of the arithmetic, not a rule anyone
    chose. Removed deliberately, as its own behaviour change (this test previously
    pinned the artifact so it could not be dropped as a side effect of a port).

    Pinned in both directions: the gate must equal 0.3 *and* must not be the
    derived value again, so the coupling cannot creep back.
    """
    assert SWEEP_DEPTH_STOP_HUNT_PCT == 0.3
    assert SWEEP_DEPTH_STOP_HUNT_PCT != SWEEP_DEPTH_MIN_PCT * 3, (
        "the stop-hunt gate is derived from SWEEP_DEPTH_MIN_PCT again — that is "
        "what put 0.30000000000000004 on the boundary in the first place"
    )
    boundary = _frozen()["liquidity_sweeps"]["stop_hunt_depth_boundary"]
    assert boundary["row"]["sweep_depth_pct"] == 0.3
    assert boundary["expected"]["SWEEP_TYPE"] == "STOP_HUNT"


def test_golden_covers_every_rule_branch() -> None:
    """The contract must exercise every discriminating branch, so it can never
    silently degrade into an all-defaults fixture set that a broken Pine port
    would still pass."""
    g = _frozen()

    imb_states = {v["expected"]["IMBALANCE_STATE"] for v in g["imbalance_lifecycle"].values()}
    assert {"FVG_BULL", "BPR", "LIQ_VOID", "NONE"} <= imb_states
    # BPR direction is resolved from last_close vs overlap mid.
    assert g["imbalance_lifecycle"]["bpr_overlap"]["expected"]["BPR_DIRECTION"] in ("BULL", "BEAR")
    assert g["imbalance_lifecycle"]["bull_fvg_full_mitigation"]["expected"]["BULL_FVG_FULL_MITIGATION"] is True

    sweep_types = {v["expected"]["SWEEP_TYPE"] for v in g["liquidity_sweeps"].values()}
    assert {"STOP_HUNT", "LIQUIDITY_GRAB", "INDUCEMENT", "NONE"} <= sweep_types
    # Quality score stays within the documented 0-5 contract.
    for v in g["liquidity_sweeps"].values():
        assert 0 <= v["expected"]["SWEEP_QUALITY_SCORE"] <= 5
    # Both-sides sweep with no explicit bias must stay ambiguous (NONE), not
    # silently default to BULL.
    assert g["liquidity_sweeps"]["both_sides_ambiguous"]["expected"]["SWEEP_DIRECTION"] == "NONE"

    # _classify_sweep_type has TWO paths, and covering the four output *values*
    # above only exercises one of them (the depth/volume derivation). An explicit
    # row ``sweep_type`` is returned verbatim and skips the derivation entirely.
    # Assert a fixture actually takes that branch — and that it is discriminating,
    # i.e. its inputs would derive a *different* type if the branch were missed.
    passthrough = g["liquidity_sweeps"]["explicit_type_passthrough"]
    assert passthrough["row"]["sweep_type"] == "INDUCEMENT"
    assert passthrough["expected"]["SWEEP_TYPE"] == "INDUCEMENT"
    assert passthrough["row"]["sweep_depth_pct"] >= SWEEP_DEPTH_STOP_HUNT_PCT
    assert passthrough["row"]["sweep_volume_ratio"] >= SWEEP_VOLUME_RATIO_MIN, (
        "the passthrough fixture must carry inputs that would derive STOP_HUNT, "
        "otherwise it cannot catch a port that skips the passthrough branch"
    )

    magnets = {v["expected"]["POOL_MAGNET_DIRECTION"] for v in g["liquidity_pools"].values()}
    assert {"UP", "DOWN", "NONE"} <= magnets
    for v in g["liquidity_pools"].values():
        assert -1.0 <= v["expected"]["POOL_IMBALANCE"] <= 1.0
        assert 0 <= v["expected"]["POOL_QUALITY_SCORE"] <= 5

    sessions = g["session_context"]
    assert sessions["none"]["expected"]["SESSION_CONTEXT"] == "NONE"
    assert sessions["asia_killzone"]["expected"]["SESSION_CONTEXT"] == "ASIA"
    assert sessions["london_killzone_during_us_dst"]["expected"]["SESSION_CONTEXT"] == "LONDON"
    assert sessions["ny_am_killzone_during_eu_overlap"]["expected"]["SESSION_CONTEXT"] == "NY_AM"
    assert sessions["ny_am_killzone_during_eu_overlap"]["expected"]["SESSION_DIRECTION_BIAS"] == "BULLISH"
    assert sessions["ny_pm_bearish"]["expected"]["SESSION_CONTEXT"] == "NY_PM"
    assert sessions["ny_pm_bearish"]["expected"]["SESSION_DIRECTION_BIAS"] == "BEARISH"
    for fixture in sessions.values():
        assert 0 <= fixture["expected"]["SESSION_CONTEXT_SCORE"] <= 7
