"""Deterministic R3 detection replay contracts."""

from __future__ import annotations

import json

from scripts.smc_context_detection_replay import (
    DEFAULT_OUTPUT,
    build_detection_replay,
)


def test_checked_in_detection_replay_is_current() -> None:
    assert json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8")) == build_detection_replay()


def test_sweep_vectors_cover_reclaim_duplicate_stale_and_ambiguity() -> None:
    sweeps = build_detection_replay()["sweepCases"]

    assert sweeps["immediateStopHuntReclaim"] == {
        "bull": True,
        "bear": False,
        "type": 1,
        "direction": 1,
        "reclaimed": True,
        "age": 0,
        "fresh": True,
        "quality": 5,
    }
    assert sweeps["noDuplicateWhileLevelRemainsPierced"]["age"] == 1
    assert sweeps["delayedReclaimBefore"]["reclaimed"] is False
    assert sweeps["delayedReclaimAfter"]["reclaimed"] is True
    assert sweeps["staleAfterFreshWindow"]["fresh"] is False
    assert sweeps["twoSidedAmbiguous"]["direction"] == 0


def test_pool_vectors_cover_cluster_magnet_and_removal() -> None:
    pools = build_detection_replay()["poolCases"]
    clustered = pools["clusterSteps"][-1]

    assert clustered["buyStrength"] == 3
    assert clustered["clusterDensity"] == 3
    assert clustered["magnet"] == 1
    assert clustered["quality"] == 5
    assert pools["takenPoolRemoved"]["buyLevel"] is None


def test_aggregate_vectors_cover_bull_neutral_and_bear() -> None:
    cases = build_detection_replay()["aggregateCases"]

    assert cases["bullishAgreement"]["bias"] == 1
    assert cases["conflictedNeutral"]["bias"] == 0
    assert cases["bearishAgreement"]["bias"] == -1
    assert all(0 <= case["qualityScore"] <= 100 for case in cases.values())
