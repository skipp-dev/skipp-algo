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
from scripts.smc_liquidity_pools import IMBALANCE_SIG_THRESHOLD
from scripts.smc_liquidity_sweeps import (
    SWEEP_DEPTH_MIN_PCT,
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
    }
    assert thresholds["pools"] == {"IMBALANCE_SIG_THRESHOLD": IMBALANCE_SIG_THRESHOLD}


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

    magnets = {v["expected"]["POOL_MAGNET_DIRECTION"] for v in g["liquidity_pools"].values()}
    assert {"UP", "DOWN", "NONE"} <= magnets
    for v in g["liquidity_pools"].values():
        assert -1.0 <= v["expected"]["POOL_IMBALANCE"] <= 1.0
        assert 0 <= v["expected"]["POOL_QUALITY_SCORE"] <= 5
