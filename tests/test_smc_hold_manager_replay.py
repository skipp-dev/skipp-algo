"""Contracts for the Hold Manager R2.4 repository replay preflight."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import scripts.smc_hold_manager_replay as replay_module
from scripts.smc_hold_manager_replay import (
    CASE_BUILDERS,
    DEFAULT_OUTPUT,
    HARNESS_LIBRARY_PIN,
    build_replay_preflight,
    freeze_library_pin,
)

ROOT = Path(__file__).resolve().parents[1]
TRACE_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "pine_extended_migration_traceability.json"
)
TRADINGVIEW_PRECONDITIONS_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_tradingview_preconditions_2026-07-27.json"
)
BUILD_1_TRADINGVIEW_PRECONDITIONS_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_tradingview_preconditions_2026-07-28.json"
)
HISTORICAL_TRADINGVIEW_REPLAY_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_tradingview_replay_2026-07-28.json"
)
BUILD_2_TRADINGVIEW_REPLAY_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_tradingview_replay_2026-08-16.json"
)
TRADINGVIEW_REPLAY_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_tradingview_replay_2026-08-16_build3.json"
)
SHADOW_CONTRACT_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_shadow_contract.json"
)

EXPECTED_CASES = (
    ("R2.4-01", "arm without entry"),
    ("R2.4-02", "delayed entry after a long wait"),
    ("R2.4-03", "time-stop starts only at entry"),
    ("R2.4-04", "entry and Target 1 on one bar"),
    ("R2.4-05", "entry and stop on one bar"),
    ("R2.4-06", "gap across entry"),
    ("R2.4-07", "gap across stop"),
    ("R2.4-08", "break-even after Target 1"),
    ("R2.4-09", "Chandelier stop never decreases"),
    ("R2.4-10", "Target 2 full exit"),
    ("R2.4-11", "reset during each state"),
    ("R2.4-12", "reload during Armed"),
    ("R2.4-13", "reload during In Trade"),
    ("R2.4-14", "new plan while In Trade"),
    ("R2.4-15", "schema mismatch"),
    ("R2.4-16", "missing BUS input"),
    ("R2.4-17", "stale Micro-Profile context"),
    ("R2.4-18", "event warning without forced false exit"),
    ("R2.4-19", "no duplicate edge alerts"),
    ("R2.4-20", "non-intraday timeframe behavior"),
)


def _trace_requirement() -> dict:
    trace = json.loads(TRACE_PATH.read_text(encoding="utf-8"))
    return next(
        requirement
        for phase in trace["phases"]
        for requirement in phase["requirements"]
        if requirement["id"] == "R2-REPLAY"
    )


def test_replay_preflight_executes_the_exact_twenty_case_matrix() -> None:
    payload = build_replay_preflight()

    assert len(CASE_BUILDERS) == 20
    assert payload["caseCount"] == 20
    assert [
        (case["caseId"], case["name"]) for case in payload["cases"]
    ] == list(EXPECTED_CASES)
    assert all(
        case["repositoryPreflightStatus"] == "passed"
        for case in payload["cases"]
    )


def test_every_case_keeps_tradingview_evidence_pending() -> None:
    payload = build_replay_preflight()

    assert payload["gateStatus"] == "partial"
    assert payload["repositoryPreflightStatus"] == "passed"
    assert payload["tradingViewStatus"] == "pending"
    assert all(
        case["tradingViewStatus"] == "pending" for case in payload["cases"]
    )
    assert payload["openGates"]
    assert any(
        "not execution evidence from the Pine runtime" in limitation
        for limitation in payload["limitations"]
    )


def test_preflight_alert_counts_never_duplicate_a_single_event() -> None:
    payload = build_replay_preflight()

    for case in payload["cases"]:
        assert all(
            count <= case["runCount"]
            for count in case["alertCounts"].values()
        ), case["caseId"]


def test_preflight_artifact_is_current_and_source_pinned() -> None:
    expected = build_replay_preflight()
    actual = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))

    assert actual == expected
    assert actual["source"]["path"] == "SMC_Hold_Manager.pine"
    assert len(actual["source"]["sha256"]) == 64


def test_library_republish_does_not_move_the_preflight_source_hash() -> None:
    """A refresh-only pin bump must not restate the pinned repository evidence.

    ``smc-library-refresh`` rewrites the canonical micro-profiles import three
    times per trading day and cannot regenerate these governance artifacts.
    Since none of the R2.4 evidence depends on the library's contents, the pin
    is frozen before hashing — anything else in the canonical still fails
    closed via ``test_preflight_artifact_is_current_and_source_pinned``.
    """

    baseline = build_replay_preflight()["source"]["sha256"]
    source = replay_module.HOLD_MANAGER_SOURCE.read_text(encoding="utf-8")
    canonical_pin = re.search(
        r"import preuss_steffen/smc_micro_profiles_generated/(\d+)", source
    )
    assert canonical_pin is not None, (
        "Canonical no longer imports the generated micro-profiles library — "
        "the decoupling premise changed, re-read HARNESS_LIBRARY_PIN."
    )
    republished = source.replace(
        f"smc_micro_profiles_generated/{canonical_pin.group(1)}",
        f"smc_micro_profiles_generated/{int(canonical_pin.group(1)) + 99}",
    )
    assert republished != source

    assert (
        hashlib.sha256(freeze_library_pin(republished).encode()).hexdigest()
        == baseline
    )
    assert (
        hashlib.sha256(freeze_library_pin(source).encode()).hexdigest()
        == baseline
    )


def test_freeze_library_pin_touches_only_the_micro_profiles_import() -> None:
    source = replay_module.HOLD_MANAGER_SOURCE.read_text(encoding="utf-8")
    frozen = freeze_library_pin(source)

    assert (
        f"import preuss_steffen/smc_micro_profiles_generated/"
        f"{HARNESS_LIBRARY_PIN} as mp" in frozen
    )
    assert len(frozen.splitlines()) == len(source.splitlines())
    assert [
        line
        for line in frozen.splitlines()
        if "smc_micro_profiles_generated" not in line
    ] == [
        line
        for line in source.splitlines()
        if "smc_micro_profiles_generated" not in line
    ]


def test_historical_tradingview_preconditions_remain_bounded() -> None:
    evidence = json.loads(
        TRADINGVIEW_PRECONDITIONS_PATH.read_text(encoding="utf-8")
    )

    assert evidence["scope"] == (
        "TradingView preconditions only; not R2.4 replay-case evidence"
    )
    assert len(evidence["source"]["repositorySha256"]) == 64
    assert evidence["source"]["savedSourceReadbackStatus"] == "pending"
    assert evidence["tradingView"]["compileStatus"] == "passed"
    assert evidence["tradingView"]["compileDiagnostics"] == []
    assert evidence["tradingView"]["addToChartStatus"] == "passed"
    assert evidence["tradingView"]["bindingStatus"] == "passed_after_reload"
    assert evidence["tradingView"]["bindings"] == {
        f"BUS {name}": f"SMC Long-Dip Suite: BUS {name}"
        for name in (
            "SchemaVersion",
            "ZoneActive",
            "Armed",
            "Confirmed",
            "Ready",
            "Trigger",
            "Invalidation",
            "QualityScore",
            "SourceKind",
            "StateCode",
            "StopLevel",
            "Target1",
            "Target2",
        )
    }
    assert evidence["replay"]["status"] == "pending"
    assert evidence["replay"]["completedCaseIds"] == []
    assert evidence["replay"]["pendingCaseIds"] == [
        case_id for case_id, _name in EXPECTED_CASES
    ]


def _tv_proven_build(evidence_sha256: str) -> tuple[int, dict[str, object]]:
    """Resolve which contract build the dated TV evidence describes.

    2026-08-14 (build 2): the decoupling spec lands semantic Pine edits EARLY
    while TradingView keeps running the previously proven build — the contract
    declares that split via buildHistory + alertWireShape.cutOver. The dated
    evidence therefore no longer pins the CURRENT source unconditionally; it
    pins the build it was captured for, and the pending gap is only legal
    while the cutover is explicitly open (cutOver=false). The wire-shape
    cutover test holds the other half: cutOver=true demands evidence for the
    current hash. Together nothing can go live unproven, and nothing can
    drift silently — a hash outside buildHistory still fails here.
    """
    contract = json.loads(SHADOW_CONTRACT_PATH.read_text(encoding="utf-8"))
    by_hash = {
        entry["sha256"]: entry["build"] for entry in contract["buildHistory"]
    }
    assert evidence_sha256 in by_hash, (
        "the dated TradingView evidence names a hash that no contract build "
        "ever carried — that is drift, not a pending rollout"
    )
    return by_hash[evidence_sha256], contract


def _assert_pending_gap_is_declared(
    proven_build: int, contract: dict[str, object]
) -> None:
    """proven < current is legal only while the gap is DECLARED.

    Before the wire-shape cutover the declaration was cutOver=false. After it
    (2026-08-16, build 3) re-mounting the legacy route to declare a gap would
    destroy step 3, so a build advance declares itself via
    alertWireShape.buildAdvancePending instead — naming the current build as
    its target and the newest TV-proven build explicitly. The wire-shape
    cutover test enforces the declaration's own honesty (not stale, not
    boastful) and that clearing it requires evidence for the current hash.
    """
    current_build = contract["source"]["build"]
    assert proven_build <= current_build
    if proven_build < current_build:
        wire = contract["alertWireShape"]
        pending = wire.get("buildAdvancePending")
        if wire["cutOver"] is False:
            return
        assert pending is not None, (
            "the contract claims the cutover happened, but the newest "
            "TradingView evidence still describes an older build and no "
            "build advance is declared"
        )
        assert pending["build"] == current_build
        assert pending["provenBuild"] == proven_build, (
            "the declared TV-proven build does not match what the newest "
            "dated evidence actually proves"
        )


def test_build_one_tradingview_preconditions_stay_covered() -> None:
    """The executed 2026-07-28 preconditions stay covered as build-1 history.

    Like the historical replay evidence above: hash must resolve in
    buildHistory, but the pending-gap declaration binds only the NEWEST dated
    evidence, which the 2026-08-16 cutover-sitting set is now.
    """
    evidence = json.loads(
        BUILD_1_TRADINGVIEW_PRECONDITIONS_PATH.read_text(encoding="utf-8")
    )

    proven_build, _contract = _tv_proven_build(
        evidence["source"]["repositorySha256"]
    )
    assert proven_build == 1
    assert evidence["source"]["transferredSourceSha256"] == (
        evidence["source"]["repositorySha256"]
    )
    assert evidence["source"]["savedSourceReadbackStatus"] == (
        "bounded_visible_match_after_reload"
    )
    assert evidence["source"]["savedSourceReadbackSha256"] is None
    assert evidence["tradingView"]["account"] == "preuss_steffen"
    assert evidence["tradingView"]["visibility"] == "private"
    assert evidence["tradingView"]["publicationStatus"] == "not_published"
    assert evidence["tradingView"]["compileStatus"] == "passed"
    assert evidence["tradingView"]["compileDiagnostics"] == []
    assert evidence["tradingView"]["addToChartStatus"] == "passed"
    assert evidence["tradingView"]["coLocationStatus"] == (
        "passed_after_reload"
    )
    assert evidence["tradingView"]["consumerChart"] == "Chart #2"
    assert evidence["tradingView"]["producerLegend"] == "SMC Long-Dip Suite"
    assert evidence["tradingView"]["consumerLegend"] == "SMC Hold Manager"
    assert evidence["tradingView"]["orphanConsumerOnChart1"] is False
    assert evidence["tradingView"]["bindingStatus"] == "passed_after_reload"
    assert evidence["tradingView"]["planSource"] == "Engine BUS v2"
    assert evidence["tradingView"]["bindings"] == {
        f"BUS {name}": f"SMC Long-Dip Suite: BUS {name}"
        for name in (
            "SchemaVersion",
            "ZoneActive",
            "Armed",
            "Confirmed",
            "Ready",
            "Trigger",
            "Invalidation",
            "QualityScore",
            "SourceKind",
            "StateCode",
            "StopLevel",
            "Target1",
            "Target2",
        )
    }
    assert evidence["tradingView"]["layoutStateAfterReload"] == {
        "chartCount": 2,
        "timeframeMinutes": 5,
        "replayActive": False,
        "layoutSaved": True,
        "pineEditorClosed": True,
    }
    assert evidence["replay"]["status"] == "complete"
    assert evidence["shadowCutover"] == {
        "status": "not_started",
        "publicationPerformed": False,
        "alertsCreated": False,
        "serverAlertDeliveryStatus": "pending",
    }


def test_historical_tradingview_replay_evidence_reports_success() -> None:
    """The executed 2026-07-28 replay stays covered as build-1 history.

    No pending-gap assertion here: that declaration binds the NEWEST dated
    evidence to the contract state, and this artifact stopped being the
    newest when the 2026-08-16 cutover-sitting evidence landed. Its hash must
    still resolve inside buildHistory — dated evidence naming a hash no build
    ever carried is drift regardless of age.
    """
    evidence = json.loads(
        HISTORICAL_TRADINGVIEW_REPLAY_PATH.read_text(encoding="utf-8")
    )

    proven_build, _contract = _tv_proven_build(
        evidence["canonicalSource"]["sha256"]
    )
    assert proven_build == 1
    # The fixture hash below is the FROZEN content of the dated artifact:
    # it describes the build-1 fixture and never moves, because dated
    # evidence is never rewritten in this repository.
    assert evidence["fixture"]["sha256"] == (
        "2dadabfdf400e1adb11b597f609d7cd18a09c0642966fff426171886e4888f1d"
    )
    assert evidence["fixture"]["visibility"] == "private"
    assert evidence["fixture"]["publicationStatus"] == "not_published"
    assert evidence["fixture"]["compileStatus"] == "passed"
    assert evidence["tradingView"]["physicalRunsExecuted"] == 23
    assert evidence["tradingView"]["logicalCasesExecuted"] == 20
    assert evidence["tradingView"]["canonicalChartStateRestored"] is True
    assert evidence["results"]["status"] == "passed"
    assert evidence["results"]["passedLogicalCases"] == 20
    assert evidence["results"]["failedLogicalCases"] == 0
    assert evidence["results"]["passedCaseIds"] == [
        case_id for case_id, _name in EXPECTED_CASES
    ]
    assert evidence["results"]["failures"] == []
    assert evidence["results"]["delayedEntryCheck"][
        "observedAtBothCheckpoints"
    ]["phase"] == "IN_TRADE"
    assert evidence["serverAlertDelivery"]["status"] == "pending"


BUILD_2_TRADINGVIEW_PRECONDITIONS_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_tradingview_preconditions_2026-08-16.json"
)
CURRENT_TRADINGVIEW_PRECONDITIONS_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_tradingview_preconditions_2026-08-16_build3.json"
)


def test_current_tradingview_preconditions_describe_the_current_build() -> None:
    """The build-3 preconditions carry the build-advance sitting of 2026-08-16.

    Transfer + 13-input rebinding (run 31946232476), the operator's alert
    swap onto the build-3 instance, and the post-swap readback + binding
    re-verification (run 31948499911) — each a CI-run report rather than an
    operator attestation. The frozen source hash must resolve to the CURRENT
    contract build, which is what the wire-shape cutover guard consumes.
    """
    evidence = json.loads(
        CURRENT_TRADINGVIEW_PRECONDITIONS_PATH.read_text(encoding="utf-8")
    )

    proven_build, contract = _tv_proven_build(
        evidence["source"]["repositorySha256"]
    )
    _assert_pending_gap_is_declared(proven_build, contract)
    assert proven_build == 3  # the buildAdvancePending declaration was
    # removed with this evidence set; proven == current again
    assert evidence["source"]["transfer"]["preWriteIdentityMode"] == "declaration"
    assert evidence["source"]["transfer"]["stagedSourceVerified"] is True
    assert evidence["source"]["transfer"]["postSaveSourceVerified"] is True
    assert evidence["tradingView"]["bindingsObserved"] == 13
    assert evidence["tradingView"]["bindingMismatches"] == 0
    assert evidence["tradingView"]["bindingRuntimeErrors"] == 0
    assert evidence["tradingView"]["layoutSaved"] is True
    for referenced in (
        evidence["alertReadback"]["evidence"],
        evidence["replay"]["evidence"],
    ):
        assert (ROOT / referenced).is_file(), referenced
    readback = json.loads(
        (ROOT / evidence["alertReadback"]["evidence"]).read_text(encoding="utf-8")
    )
    assert readback["buildAlert"]["running"] is True
    assert readback["legacyChannelAlertsRemaining"] == []
    assert readback["extraPrefixAlerts"] == []
    assert evidence["shadowCutover"]["serverAlertDeliveryStatus"] == "pending"


def test_current_replay_evidence_describes_the_current_build() -> None:
    """The build-3 replay evidence closes the declared build-3 gap.

    Its case results come from structural inheritance (bridge test below) plus
    repository execution of the inserted transport; this test pins the claims
    the wire-shape cutover guard relies on.
    """
    evidence = json.loads(TRADINGVIEW_REPLAY_PATH.read_text(encoding="utf-8"))

    proven_build, contract = _tv_proven_build(
        evidence["canonicalSource"]["sha256"]
    )
    _assert_pending_gap_is_declared(proven_build, contract)
    assert proven_build == 3  # the buildAdvancePending declaration was
    # removed with this evidence set; proven == current again
    assert evidence["canonicalSource"]["path"] == "SMC_Hold_Manager.pine"
    assert evidence["inheritance"]["basis"] == (
        "artifacts/governance/smc_hold_manager_tradingview_replay_2026-07-28.json"
    )
    assert evidence["inheritance"]["basisFrozenSha256"] == (
        json.loads(
            HISTORICAL_TRADINGVIEW_REPLAY_PATH.read_text(encoding="utf-8")
        )["canonicalSource"]["sha256"]
    )
    for test_path in evidence["executedForTheDelta"]["tests"]:
        assert (ROOT / test_path).is_file(), test_path
    assert evidence["serverAlertDelivery"]["status"] == "pending"


def test_build_two_cutover_evidence_stays_covered_as_history() -> None:
    """The 2026-08-16 cutover-sitting set stays covered as build-2 history.

    Like the 2026-07-28 build-1 set: once the build-3 evidence became the
    newest, the pending-gap declaration stopped binding these artifacts, but
    their hashes must still resolve inside buildHistory — dated evidence
    naming a hash no build ever carried is drift regardless of age.
    """
    replay = json.loads(
        BUILD_2_TRADINGVIEW_REPLAY_PATH.read_text(encoding="utf-8")
    )
    preconditions = json.loads(
        BUILD_2_TRADINGVIEW_PRECONDITIONS_PATH.read_text(encoding="utf-8")
    )

    replay_build, _contract = _tv_proven_build(
        replay["canonicalSource"]["sha256"]
    )
    preconditions_build, _contract = _tv_proven_build(
        preconditions["source"]["repositorySha256"]
    )
    assert replay_build == 2
    assert preconditions_build == 2
    assert replay["inheritance"]["basisFrozenSha256"] == json.loads(
        HISTORICAL_TRADINGVIEW_REPLAY_PATH.read_text(encoding="utf-8")
    )["canonicalSource"]["sha256"]


def test_the_structural_bridge_reproduces_build_one_from_the_tree() -> None:
    """The inheritance claim is recomputed, not trusted.

    The artifact records the inserted block verbatim. Removing the block at
    exactly that position from the FROZEN current source must reproduce the
    build-1 hash the 2026-07-28 TradingView replay executed against — proving
    byte-identity of every inherited decision path without needing git
    history. A refresh pin bump cannot move either side (both hands are
    frozen); a semantic edit OUTSIDE the 8b insert breaks the reconstruction
    and fails here.

    2026-08-16 (build 3): under a declared build advance the tree already
    carries the next build, whose insert differs INSIDE while keeping the
    recorded position and length. The reconstruction to build 1 stays
    load-bearing in both states; the verbatim-insert equality binds only
    while the artifact's build is the tree's build.
    """
    evidence = json.loads(TRADINGVIEW_REPLAY_PATH.read_text(encoding="utf-8"))
    bridge = evidence["inheritance"]["structuralBridge"]
    contract = json.loads(SHADOW_CONTRACT_PATH.read_text(encoding="utf-8"))
    by_build = {
        entry["build"]: entry["sha256"] for entry in contract["buildHistory"]
    }
    pending = contract["alertWireShape"].get("buildAdvancePending")

    frozen = freeze_library_pin(
        replay_module.HOLD_MANAGER_SOURCE.read_text(encoding="utf-8")
    )
    tree_sha = hashlib.sha256(frozen.encode()).hexdigest()

    lines = frozen.splitlines(keepends=True)
    start = bridge["insertAfterFrozenLine"]
    end = start + bridge["insertLineCount"]
    removed = "".join(lines[start:end])

    if pending is None:
        assert tree_sha == evidence["canonicalSource"]["sha256"]
        assert removed == bridge["insert"]
        assert (
            hashlib.sha256(removed.encode()).hexdigest()
            == bridge["insertSha256"]
        )
    else:
        assert tree_sha == by_build[pending["build"]]
        assert (
            evidence["canonicalSource"]["sha256"]
            == by_build[pending["provenBuild"]]
        )
        assert removed != bridge["insert"], (
            "the pending build's insert is byte-identical to the proven "
            "build's -- then nothing advanced and the declaration is noise"
        )

    remainder = "".join(lines[:start] + lines[end:])
    assert (
        hashlib.sha256(remainder.encode()).hexdigest()
        == evidence["inheritance"]["basisFrozenSha256"]
    )


def test_traceability_marks_r2_replay_complete() -> None:
    requirement = _trace_requirement()

    assert requirement["status"] == "complete"
    assert requirement["evidence"] == [
        "scripts/smc_hold_manager_replay.py",
        "scripts/generate_smc_hold_manager_tv_fixture.py",
        "tests/test_smc_hold_manager_replay.py",
        "tests/test_smc_hold_manager_tradingview_fixture.py",
        "tests/fixtures/pine/smc_hold_manager_r2_4_fixture.pine",
        "artifacts/governance/smc_hold_manager_replay_preflight.json",
        (
            "artifacts/governance/"
            "smc_hold_manager_tradingview_fixture_manifest.json"
        ),
        (
            "artifacts/governance/"
            "smc_hold_manager_tradingview_fixture_compile_2026-07-27.json"
        ),
        (
            "artifacts/governance/"
            "smc_hold_manager_tradingview_fixture_compile_2026-07-28.json"
        ),
        (
            "artifacts/governance/"
            "smc_hold_manager_tradingview_replay_2026-07-28.json"
        ),
        (
            "artifacts/governance/"
            "smc_hold_manager_tradingview_preconditions_2026-07-27.json"
        ),
        (
            "artifacts/governance/"
            "smc_hold_manager_tradingview_preconditions_2026-07-28.json"
        ),
    ]
    assert requirement["openGates"] == []
