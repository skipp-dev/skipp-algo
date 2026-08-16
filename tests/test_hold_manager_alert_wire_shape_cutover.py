"""The legacy alert route must exist exactly as long as it is the rollback path.

Two failures are possible around a staged cutover, and they point in opposite
directions. Leaving the legacy route mounted forever is dead surface nobody
remembers to remove. Removing it before the operator has actually switched the
live alerts destroys the rollback path -- recreating the six alerts from
``smc_hold_manager_shadow_alert_templates.json`` only works while the receiver
still speaks that shape.

So the guard is two-sided and reads its expectation from contract state rather
than from a date. A date would need a clock, and a clock that can be moved is a
guard that can be silenced; ``alertWireShape.cutOver`` cannot be moved by
waiting. While it is false the legacy route is *required* to be present, which
is what keeps this file from being a vacuous "if never true, assert nothing".

See docs/superpowers/specs/2026-08-13-hold-manager-alert-decoupling-design.md.
"""

from __future__ import annotations

import copy
import json
import secrets
from collections.abc import Collection
from pathlib import Path
from typing import Any

import pytest

from services.live_overlay_daemon.hold_manager_shadow_receiver import build_router

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    ROOT / "artifacts" / "governance" / "smc_hold_manager_shadow_contract.json"
)
TEMPLATES_PATH = (
    ROOT / "artifacts" / "governance" / "smc_hold_manager_shadow_alert_templates.json"
)

LEGACY_ROUTE = "/tradingview/hold-manager-shadow"
BUILD_ROUTE = "/{token}/tradingview/hold-manager-shadow"
SHAPES = ("legacy_hash_body_token", "build_path_token")


def _contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _mounted_paths() -> set[str]:
    """Executed, not grepped.

    A string search of the module would also match the route path inside a
    comment or a docstring; mounting the router answers what the service
    actually serves.
    """
    return {route.path for route in build_router(secrets.compare_digest).routes}


def _verify(wire_shape: dict[str, Any], paths: Collection[str]) -> None:
    if wire_shape["current"] not in SHAPES or wire_shape["target"] not in SHAPES:
        raise AssertionError(f"unknown wire shape in {wire_shape}")
    if BUILD_ROUTE not in paths:
        raise AssertionError(
            "the build-pinned route is missing; the cutover has no target"
        )
    if wire_shape["cutOver"]:
        if LEGACY_ROUTE in paths:
            raise AssertionError(
                "the cutover is recorded as done but the legacy route is still "
                "mounted -- step 3 of the decoupling design is unfinished"
            )
    elif LEGACY_ROUTE not in paths:
        raise AssertionError(
            "the legacy route was removed while the contract still records the "
            "cutover as pending -- the rollback path is gone"
        )


def test_the_repository_state_is_consistent() -> None:
    _verify(_contract()["alertWireShape"], _mounted_paths())


def _dated_evidence(name: str) -> dict[str, Any]:
    return json.loads(
        (CONTRACT_PATH.parent / name).read_text(encoding="utf-8")
    )


def _expected_evidence_sha(contract: dict[str, Any]) -> str:
    """The hash the newest dated TV evidence must carry, per contract state.

    Without a declared build advance that is the current source hash. With
    one (`alertWireShape.buildAdvancePending`, introduced 2026-08-16 for
    build 3), it is exactly the hash of the build the declaration names as
    still TV-proven — nothing older, nothing else. The declaration must name
    the CURRENT build as its target, so it cannot linger after the advance
    completes or be pre-declared for a build that is not in the tree yet.
    """
    wire = contract["alertWireShape"]
    pending = wire.get("buildAdvancePending")
    by_build = {
        entry["build"]: entry["sha256"] for entry in contract["buildHistory"]
    }
    if pending is None:
        return contract["source"]["sha256"]
    if pending["build"] != contract["source"]["build"]:
        raise AssertionError(
            "buildAdvancePending names a build that is not the current one -- "
            "the declaration is stale and must be removed or corrected"
        )
    if pending["provenBuild"] >= pending["build"]:
        raise AssertionError(
            "buildAdvancePending claims the pending build is already proven"
        )
    return by_build[pending["provenBuild"]]


def _verify_cutover_evidence(
    cut_over: bool,
    expected_sha: str,
    replay_sha: str,
    preconditions_sha: str,
) -> None:
    """cutOver=true demands dated TradingView evidence for the expected hash.

    The other half of the pending-gap pattern (2026-08-14, build 2): the
    replay/preconditions currency tests allow the repository to carry a source
    TradingView has not proven yet — but only while the gap is DECLARED:
    before the wire-shape cutover via cutOver=false, afterwards via
    buildAdvancePending (which moves the expectation to the declared proven
    build, see _expected_evidence_sha). This side makes the exit condition
    executable. Between the two, "live" and "proven" cannot diverge silently.
    """
    if not cut_over:
        return
    if replay_sha != expected_sha or preconditions_sha != expected_sha:
        raise AssertionError(
            "cutOver=true, but the newest dated TradingView evidence does not "
            "describe the expected source hash -- the switch would go live on "
            "an unproven build. Capture new preconditions + replay evidence "
            "in the cutover sitting first."
        )


def test_the_cutover_evidence_rule_holds_for_the_repository_state() -> None:
    """The newest dated evidence set is the build-3 advance of 2026-08-16.

    It names the build-3 hash and landed together with the removal of the
    buildAdvancePending declaration (its recorded exit condition), so the
    expected hash is the current source hash again and the rule holds
    without weakening: evidence for an older build or a hash outside the
    history still fails.
    """
    contract = _contract()
    replay = _dated_evidence(
        "smc_hold_manager_tradingview_replay_2026-08-16_build3.json"
    )
    preconditions = _dated_evidence(
        "smc_hold_manager_tradingview_preconditions_2026-08-16_build3.json"
    )

    _verify_cutover_evidence(
        contract["alertWireShape"]["cutOver"],
        _expected_evidence_sha(contract),
        replay["canonicalSource"]["sha256"],
        preconditions["source"]["repositorySha256"],
    )


def test_a_cutover_on_stale_evidence_is_refused() -> None:
    """Forward probe with real artifacts, so the guard cannot be vacuous.

    The 2026-07-28 set permanently describes build 1, so flipping cutOver
    against it must raise for as long as the contract carries anything newer.
    Before 2026-08-16 this probe used the same artifacts as the state test
    above; it was moved onto the historical set when the cutover-sitting
    evidence landed, keeping the raise path executed instead of letting the
    probe's premise silently disappear.
    """
    contract = _contract()
    replay = _dated_evidence("smc_hold_manager_tradingview_replay_2026-07-28.json")
    preconditions = _dated_evidence(
        "smc_hold_manager_tradingview_preconditions_2026-07-28.json"
    )

    expected_sha = _expected_evidence_sha(contract)
    assert replay["canonicalSource"]["sha256"] != expected_sha, (
        "the historical build-1 evidence now names the expected hash -- "
        "buildHistory must have collapsed, investigate before trusting this "
        "guard"
    )

    with pytest.raises(AssertionError, match="unproven build"):
        _verify_cutover_evidence(
            True,
            expected_sha,
            replay["canonicalSource"]["sha256"],
            preconditions["source"]["repositorySha256"],
        )


def test_a_stale_or_boastful_pending_declaration_is_refused() -> None:
    """The pending declaration cannot outlive or precede its build.

    The real build-3 declaration was removed with the build-3 evidence set
    (2026-08-16), so the probes run on a synthesized declaration grafted onto
    the real contract — first shown to be ACCEPTED, so the mutations below
    fail for their declared reason and not because the graft itself is
    malformed. Then both raise paths: a declaration left behind after a
    further build advance (names build N while the source moved to N+1), and
    one that claims its own build as already proven.
    """
    contract = _contract()
    assert contract["alertWireShape"].get("buildAdvancePending") is None, (
        "the contract carries a real pending declaration again -- point the "
        "probes back at the real one instead of the synthetic graft"
    )

    by_build = {
        entry["build"]: entry["sha256"] for entry in contract["buildHistory"]
    }
    current_build = contract["source"]["build"]
    base = copy.deepcopy(contract)
    base["alertWireShape"]["buildAdvancePending"] = {
        "build": current_build,
        "provenBuild": current_build - 1,
    }
    assert _expected_evidence_sha(base) == by_build[current_build - 1]

    stale = copy.deepcopy(base)
    stale["source"]["build"] = current_build + 1
    stale["buildHistory"] = [
        *stale["buildHistory"],
        {"build": current_build + 1, "sha256": "f" * 64},
    ]
    with pytest.raises(AssertionError, match="stale"):
        _expected_evidence_sha(stale)

    boastful = copy.deepcopy(base)
    boastful["alertWireShape"]["buildAdvancePending"]["provenBuild"] = (
        boastful["alertWireShape"]["buildAdvancePending"]["build"]
    )
    with pytest.raises(AssertionError, match="already proven"):
        _expected_evidence_sha(boastful)


def test_the_rollback_template_still_matches_the_channels() -> None:
    """The legacy route without its message templates is not a rollback path.

    Unconditional on purpose. The first draft skipped once the cutover was
    done, which is the kind of state-dependent skip that quietly stops
    checking anything -- and the repository's skip budget rejected it. The
    artifact is never deleted, only marked superseded, because dated evidence
    is not rewritten here, so the assertion holds on both sides of the
    cutover.
    """
    templates = json.loads(TEMPLATES_PATH.read_text(encoding="utf-8"))

    assert [alert["condition"] for alert in templates["alerts"]] == list(
        _contract()["activationRequirements"]["holdAlertChannels"]
    )


@pytest.mark.parametrize(
    ("label", "cut_over", "paths", "expected"),
    [
        # Tuples, not set literals: tests/test_pytest_xdist_parametrize_
        # determinism.py forbids parametrizing from an unordered iterable,
        # because xdist workers must collect identical test ids. The ids
        # happened to be stable here -- measured across three PYTHONHASHSEED
        # values -- but the rule is static and the guard is right to be, since
        # "stable today" is not a property anyone can keep checking.
        ("pending, both mounted", False, (LEGACY_ROUTE, BUILD_ROUTE), None),
        (
            "pending, legacy removed early",
            False,
            (BUILD_ROUTE,),
            "rollback path is gone",
        ),
        ("done, legacy removed", True, (BUILD_ROUTE,), None),
        (
            "done, legacy still mounted",
            True,
            (LEGACY_ROUTE, BUILD_ROUTE),
            "step 3 of the decoupling design is unfinished",
        ),
        (
            "build route never added",
            False,
            (LEGACY_ROUTE,),
            "the cutover has no target",
        ),
    ],
)
def test_both_directions_actually_fail(
    label: str,
    cut_over: bool,
    paths: tuple[str, ...],
    expected: str | None,
) -> None:
    """Every branch is exercised with synthetic state.

    Without this the file would only ever run one of its two directions -- the
    one today's contract happens to select -- and the other would be untested
    code pretending to be a guard.
    """
    wire_shape = {
        "current": SHAPES[1] if cut_over else SHAPES[0],
        "target": SHAPES[1],
        "cutOver": cut_over,
    }

    if expected is None:
        _verify(wire_shape, paths)
        return

    with pytest.raises(AssertionError, match=expected):
        _verify(wire_shape, paths)
