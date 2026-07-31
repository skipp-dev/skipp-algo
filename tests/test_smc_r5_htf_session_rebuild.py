"""Contract gates for the R5 live HTF and session companion rebuild."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from scripts.smc_r5_htf_session_rebuild_manifest import (
    DEFAULT_OUTPUT,
    HTF_SOURCE,
    SESSION_SOURCE,
    build_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
LEGACY_HTF = ROOT / "pine/legacy/SMC_HTF_Confluence_v1_snapshot.pine"
LEGACY_SESSION = ROOT / "pine/legacy/SMC_Session_Context_v1_snapshot.pine"
PRODUCT_CUT = ROOT / "artifacts/tradingview/smc_product_cut_manifest.json"
TRACEABILITY = ROOT / "artifacts/governance/pine_extended_migration_traceability.json"


def _code(path: Path) -> str:
    return "\n".join(
        line.split("//", 1)[0]
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("//")
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _surface(file_name: str) -> dict:
    payload = json.loads(PRODUCT_CUT.read_text(encoding="utf-8"))
    return next(surface for surface in payload["surfaceRoles"] if surface["file"] == file_name)


def _requirement(requirement_id: str) -> dict:
    trace = json.loads(TRACEABILITY.read_text(encoding="utf-8"))
    return next(
        requirement
        for phase in trace["phases"]
        for requirement in phase["requirements"]
        if requirement["id"] == requirement_id
    )


def test_rebuild_manifest_is_current_and_pins_both_source_hashes() -> None:
    manifest = build_manifest()

    assert json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8")) == manifest
    assert manifest["sources"] == {
        "htfConfluence": {
            "path": HTF_SOURCE.relative_to(ROOT).as_posix(),
            "sha256": _sha(HTF_SOURCE),
            "savedScript": "SMC HTF Confluence",
        },
        "sessionContext": {
            "path": SESSION_SOURCE.relative_to(ROOT).as_posix(),
            "sha256": _sha(SESSION_SOURCE),
            "savedScript": "SMC Session Context",
        },
    }
    assert manifest["caseCount"] == len(manifest["cases"])
    assert {case["caseId"] for case in manifest["cases"]} == {
        "R5-REBUILD-COMPILE-HTF",
        "R5-REBUILD-COMPILE-SESSION",
        "R5-REBUILD-HTF-15M",
        "R5-REBUILD-HTF-1H",
        "R5-REBUILD-HTF-4H",
        "R5-REBUILD-FAIL-CLOSED",
        "R5-REBUILD-LIVE-NO-REPAINT",
        "R5-REBUILD-DST-EU-GAP",
        "R5-REBUILD-DST-STANDARD",
        "R5-REBUILD-EXTENDED",
        "R5-REBUILD-ROLLBACK",
    }
    assert all(case["tradingViewStatus"] == "pending" for case in manifest["cases"])


def test_htf_root_uses_three_confirmed_live_request_sites() -> None:
    source = HTF_SOURCE.read_text(encoding="utf-8")
    code = _code(HTF_SOURCE)

    assert 'indicator("SMC HTF Confluence"' in source
    assert "dynamic_requests = true" in source
    assert "smc_micro_profiles_generated" not in source
    assert "mp." not in code
    assert code.count("request.security(") == 3
    assert code.count("barmerge.lookahead_on") == 3
    assert "barmerge.lookahead_off" not in code
    assert "_confirmed_tuple()" in code
    assert "time[1]" in code
    assert "time_close[1]" in code
    assert "barstate.isconfirmed[1]" in code
    assert "_strictly_higher" in code
    assert "frames_ordered" in code
    assert 'input.timeframe("15"' in code
    assert 'input.timeframe("60"' in code
    assert 'input.timeframe("240"' in code


def test_htf_root_exposes_required_product_context_and_freshness() -> None:
    source = HTF_SOURCE.read_text(encoding="utf-8")

    for diagnostic in (
        "HTF 15m Available",
        "HTF 1h Available",
        "HTF 4h Available",
        "HTF 15m Source Close",
        "HTF 1h Source Close",
        "HTF 4h Source Close",
        "HTF 15m Trend",
        "HTF 1h Trend",
        "HTF 4h Trend",
        "HTF 15m ATR Ratio",
        "HTF 1h ATR Ratio",
        "HTF 4h ATR Ratio",
        "HTF Confluence Bias",
        "HTF Confluence Score",
    ):
        assert f'"{diagnostic}"' in source
    for context in (
        "squeeze_on",
        "squeeze_released",
        "reversal_active",
        "bull_pattern",
        "bear_pattern",
        "bull_divergence",
        "bear_divergence",
        "vwap_hold",
        "retrace_ok",
    ):
        assert context in source


def test_session_root_is_confirmed_and_iana_zone_driven() -> None:
    source = SESSION_SOURCE.read_text(encoding="utf-8")
    code = _code(SESSION_SOURCE)

    assert 'indicator("SMC Session Context"' in source
    assert "smc_micro_profiles_generated" not in source
    assert "mp." not in code
    assert "request.security(" not in code
    assert '"America/New_York"' in source
    assert '"Europe/London"' in source
    assert '"Asia/Tokyo"' in source
    assert "barstate.isconfirmed" in code
    assert "session_changed" in code
    assert "cumulative_volume" in code
    assert "opening_active" in code
    assert "SESSION_NY_AM" in code
    assert "SESSION_NY_PM" in code


def test_snapshot_sources_are_archived_and_roots_are_compile_required() -> None:
    assert "smc_micro_profiles_generated/179" in LEGACY_HTF.read_text(encoding="utf-8")
    assert "smc_micro_profiles_generated/179" in LEGACY_SESSION.read_text(encoding="utf-8")

    # 2026-07-31 rollout: HTF Confluence deployed into the optional Pro HTF
    # preset (owner-ordered, after all 11 R5 cases and decision #4257);
    # Session Context stays not_deployed BY DECISION — it is in no preset and
    # serves as the R5 gate's measurement instrument.
    expected_rollout = {
        "SMC_HTF_Confluence.pine": "deployed",
        "SMC_Session_Context.pine": "not_deployed",
    }
    for file_name, rollout_state in expected_rollout.items():
        surface = _surface(file_name)
        assert surface["lifecycle"] == "active"
        assert surface["compile_expectation"] == "required"
        assert surface["known_missing_mp_fields"] == []
        assert surface["archive_state"] == "none"
        assert surface["rollout_state"] == rollout_state


def test_product_cut_exposes_private_r5_preflight_scope() -> None:
    payload = json.loads(PRODUCT_CUT.read_text(encoding="utf-8"))

    assert payload["preflightScopes"]["smcR5HtfSession"] == [
        {
            "file": "SMC_HTF_Confluence.pine",
            "scriptName": "SMC HTF Confluence",
            "savedScriptName": "SMC HTF Confluence",
            "checkInputs": False,
            "addToChart": True,
            "allowFreshDraftOnMissingExisting": True,
        },
        {
            "file": "SMC_Session_Context.pine",
            "scriptName": "SMC Session Context",
            "savedScriptName": "SMC Session Context",
            "checkInputs": False,
            "addToChart": True,
            "allowFreshDraftOnMissingExisting": True,
        },
    ]


def test_traceability_records_r5_rebuild_complete_with_all_case_evidence() -> None:
    """R5-REBUILD is complete; the claim must stay tied to the evidence.

    History of this pin: it held the requirement at "partial" through the
    CE10156 fix (#4239), the preflight stale-instance fix (#4241), and the
    replay/live/rollback executions (#4243-#4256), refusing to let openGates
    shrink without landed evidence. On 2026-07-31 the owner ordered the status
    change after every exit-gate item was recorded — all 11 manifest cases
    executed, rollback+reload verified, the Pro HTF preset decided (#4257),
    and the secret/source-capture check run over every artifact. "complete"
    is only as good as that chain, so the chain is asserted, not assumed.
    """
    requirement = _requirement("R5-REBUILD")
    manifest = build_manifest()

    assert requirement["status"] == "complete"
    # The completeness invariant in test_pine_extended_migration_traceability
    # additionally requires every evidence path to exist on disk.
    assert requirement["openGates"] == []

    assert HTF_SOURCE.relative_to(ROOT).as_posix() in requirement["evidence"]
    assert SESSION_SOURCE.relative_to(ROOT).as_posix() in requirement["evidence"]
    assert DEFAULT_OUTPUT.relative_to(ROOT).as_posix() in requirement["evidence"]

    # Completeness rests on all 11 cases having landed evidence — the same
    # facts test_every_manifest_case_now_has_landed_evidence pins in detail.
    assert manifest["status"] == "all_cases_executed"
    assert manifest["caseCount"] == 11


def test_compile_gate_evidence_is_recorded_and_reachable() -> None:
    """The closed compile gate must cite artifacts that exist and say so.

    An openGates entry removed without landed evidence is exactly the failure
    mode the R5 gates exist to prevent, so the claim is pinned to the files.
    """
    requirement = _requirement("R5-REBUILD")
    manifest = build_manifest()

    green = "artifacts/governance/smc_r5_htf_session_rebuild_preflight_green_2026-07-31.json"
    diagnosis = "artifacts/governance/smc_r5_htf_session_rebuild_ce10156_diagnosis_2026-07-31.json"

    for path in (green, diagnosis):
        assert path in requirement["evidence"]
        assert path in manifest["resultEvidence"]
        assert (ROOT / path).is_file()

    # The green run is the compile-gate proof: every axis true for both targets.
    report = json.loads((ROOT / green).read_text(encoding="utf-8"))
    assert report["overall_preflight_ok"] is True
    assert report["compile_green"] is True
    assert report["runtime_green"] is True
    assert {target["scriptName"] for target in report["targets"]} == {
        "SMC HTF Confluence",
        "SMC Session Context",
    }
    for target in report["targets"]:
        assert target["compile_ok"] is True
        assert target["script_found_on_chart_ok"] is True
        assert target["runtime_smoke_ok"] is True

    # Per-case status stays at the preregistered baseline; results live in
    # resultEvidence (the R5-HTF-SPIKE convention).
    assert all(case["tradingViewStatus"] == "pending" for case in manifest["cases"])
    assert "preregistered baseline" in manifest["statusSemantics"]


def test_live_no_repaint_evidence_is_recorded_and_reachable() -> None:
    """R5-REBUILD-LIVE-NO-REPAINT must cite a run that was actually live.

    This is the one case Bar Replay cannot stand in for: the property is what
    the script publishes while a higher-frame bar is still forming, which only
    exists on an open feed. The failure mode worth pinning is therefore not "the
    values moved" but "the values held still because nothing was moving at all"
    — a run taken after the close would report perfect stability and prove
    nothing. So the evidence has to carry the liveness proof, not just a verdict.
    """
    manifest = build_manifest()
    path = "artifacts/governance/smc_r5_htf_session_rebuild_live_no_repaint_2026-07-31.json"

    assert path in manifest["resultEvidence"]
    assert (ROOT / path).is_file()

    report = json.loads((ROOT / path).read_text(encoding="utf-8"))
    assert report["caseId"] == "R5-REBUILD-LIVE-NO-REPAINT"
    assert report["status"] == "pass"
    assert report["observedDiagnostics"]["confirmedValuesStableInsideOpenSourceBar"] == "1"
    assert report["observedDiagnostics"]["lookaheadOffProductPath"] == "0"

    verdict = report["verdict"]
    assert verdict["violations"] == []
    # The feed was demonstrably running, and the run looked INSIDE an open bar
    # rather than sampling one value per bar and calling it stable.
    assert verdict["chartWasTicking"] is True
    assert verdict["longestHoldSamples"] >= 3
    assert verdict["lookaheadLeaks"] == 0
    assert report["sessionOpenThroughout"] is True

    # Every expectation the manifest preregisters for the case is answered.
    case = next(entry for entry in manifest["cases"] if entry["caseId"] == "R5-REBUILD-LIVE-NO-REPAINT")
    for expectation in case["expectedDiagnostics"]:
        key, _, value = expectation.partition("=")
        assert report["observedDiagnostics"][key] == value


def test_landed_r5_evidence_is_all_referenced_by_the_manifest() -> None:
    """Evidence in the tree that the manifest does not cite is invisible.

    Between #4243 and #4250 five artifacts landed while resultEvidence still
    listed only the three compile-era ones, so the manifest — the index a
    reviewer reads — under-reported what had been executed.
    """
    manifest = build_manifest()
    for path in manifest["resultEvidence"]:
        assert (ROOT / path).is_file(), f"{path} is cited but missing"

    on_disk = {
        f"artifacts/governance/{entry.name}"
        for entry in (ROOT / "artifacts/governance").glob("smc_r5_htf_*.json")
        if entry.name != "smc_r5_htf_session_rebuild_manifest.json"
        # The survey records what was NOT runnable at the time, not a result.
        and entry.name != "smc_r5_htf_session_rebuild_survey_2026-07-31.json"
    }
    missing = sorted(on_disk - set(manifest["resultEvidence"]))
    assert not missing, f"landed R5 evidence not cited by the manifest: {missing}"


def test_rollback_evidence_records_a_drill_that_actually_perturbed_the_chart() -> None:
    """R5-REBUILD-ROLLBACK must prove a restore, not an untouched chart.

    The failure mode worth pinning is a drill that reports "restored" because it
    never changed anything. So the evidence has to show the perturbation took,
    the in-session restore matched, the layout was saved, AND the state survived
    a reload — a save that is never re-read proves only that a button was
    clicked.
    """
    manifest = build_manifest()
    path = "artifacts/governance/smc_r5_htf_session_rebuild_rollback_2026-07-31.json"

    assert path in manifest["resultEvidence"]
    assert (ROOT / path).is_file()

    report = json.loads((ROOT / path).read_text(encoding="utf-8"))
    assert report["caseId"] == "R5-REBUILD-ROLLBACK"
    assert report["status"] == "pass"

    # The source that was reinstalled is the one the manifest pins.
    assert report["sourceHashVerified"] is True
    assert report["sourceHash"] == manifest["sources"]["htfConfluence"]["sha256"]

    # The perturbation is what makes the restore meaningful.
    assert report["perturbationTook"] is True
    assert report["perturbationDifferences"], "a drill that changed nothing certifies nothing"

    assert report["inSessionComparison"]["restored"] is True
    assert report["layoutSaved"] is True
    assert report["reloadComparison"]["restored"] is True
    assert report["reloadComparison"]["differences"] == []

    # The baseline is the repaired chart, captured at drill time, and the
    # evidence says so rather than implying a record that was never taken.
    assert "step-1 record was never taken" in report["baselineOrigin"]

    case = next(entry for entry in manifest["cases"] if entry["caseId"] == "R5-REBUILD-ROLLBACK")
    for expectation in case["expectedDiagnostics"]:
        key, _, value = expectation.partition("=")
        assert report["observedDiagnostics"][key] == value


def test_every_manifest_case_now_has_landed_evidence() -> None:
    """All 11 R5 cases have been executed; the manifest must show it.

    `resultEvidence` is the index a reviewer reads. If a case is executed but its
    artifact is not cited, the gate under-reports itself — which is how five
    artifacts sat unreferenced between #4243 and #4250.
    """
    manifest = build_manifest()
    assert manifest["status"] == "all_cases_executed"
    assert manifest["caseCount"] == len(manifest["cases"]) == 11

    cited = "\n".join(manifest["resultEvidence"])
    for fragment in ("preflight_green", "replay", "extended", "availability", "live_no_repaint", "rollback"):
        assert fragment in cited, f"no evidence cited for {fragment}"


def test_pro_htf_preset_decision_is_recorded_with_its_premises() -> None:
    """The Pro HTF preset decision must stay tied to the facts it rests on.

    The exit gate's last open item was "the decision whether either companion
    enters the optional Pro HTF layout". It was decided on 2026-07-31: HTF
    Confluence is in, Session Context is not. The reasoning is checkable, so it
    is checked here rather than trusted — if any premise stops being true, this
    test fails and the decision gets revisited instead of quietly rotting.
    """
    runbook = (ROOT / "docs/SMC_R5_HTF_SESSION_REBUILD_RUNBOOK.md").read_text(encoding="utf-8")
    combinations = (ROOT / "docs/SMC_Chart_Combinations.md").read_text(encoding="utf-8")

    assert "Pro HTF preset decision (2026-07-31)" in runbook
    assert "the decision whether either companion enters the optional Pro HTF layout —" in runbook
    for doc in (runbook, combinations):
        assert "SMC HTF Confluence" in doc and "SMC Session Context" in doc

    # Premise 1: Context Overlay already renders the session surface, so a
    # separate Session script would be redundant in the preset.
    overlay = (ROOT / "SMC_Context_Overlay.pine").read_text(encoding="utf-8")
    for marker in ("CTX SessionCode", "CTX SessionKillzone", "CTX SessionRangeTop", "CTX OpeningRangeTop"):
        assert marker in overlay, f"Context Overlay no longer binds {marker}; revisit the decision"

    # Premise 2: that data comes from the Context BUS, not from Session Context.
    assert "CTX SessionCode" in (ROOT / "SMC_Context_Bus.pine").read_text(encoding="utf-8")

    # Premise 3: Session Context is unwired — it binds nothing and imports
    # nothing, so nothing in a preset would depend on it being present.
    session = (ROOT / "SMC_Session_Context.pine").read_text(encoding="utf-8")
    assert "input.source" not in session, "Session Context now binds inputs; it is no longer standalone"
    assert not re.search(r"^import ", session, re.MULTILINE), "Session Context now imports a library"

    # Premise 4, as decided: preset membership and deployment are separate
    # steps. On decision day both surfaces were not_deployed; the deployment
    # step followed the same evening on the owner's instruction and flipped
    # exactly the surface the decision put into a preset. The premise that
    # still holds — and is pinned — is the SEPARATION: Session Context gained
    # no deployment from the decision alone.
    product_cut = json.loads(PRODUCT_CUT.read_text(encoding="utf-8"))
    for file_name in ("SMC_HTF_Confluence.pine", "SMC_Session_Context.pine"):
        assert file_name in product_cut["companionOperatorOnlyFiles"]
    assert _surface("SMC_HTF_Confluence.pine")["rollout_state"] == "deployed"
    assert _surface("SMC_Session_Context.pine")["rollout_state"] == "not_deployed"

    # The follow-up must stay visible: session MSS exists only here.
    assert "Session MSS Bull Confirmed" in session
    assert "Session MSS" not in overlay
    assert "session-level MSS" in runbook


def test_no_r5_evidence_artifact_carries_source_or_secrets() -> None:
    """The exit gate demands "zero unredacted secret or editor-source capture".

    These artifacts are produced by a browser driving a logged-in TradingView
    session with the Pine editor open, so leaking either is a live risk rather
    than a theoretical one. Checked over every landed artifact, not sampled.
    """
    # Keyed on markers that only appear in a captured FILE, not on Pine
    # identifiers: the CE10156 diagnosis explains the bug in prose and names
    # `request.security` doing so. Naming a function is not capturing source,
    # and a pattern that cannot tell them apart would push future diagnoses
    # toward being vaguer than the evidence needs to be.
    patterns = {
        "pine source": re.compile(r"//@version|\bindicator\(\""),
        "bearer token": re.compile(r"Bearer\s+[A-Za-z0-9._-]{8}"),
        "session cookie": re.compile(r"sessionid", re.IGNORECASE),
        "password": re.compile(r"password", re.IGNORECASE),
    }
    artifacts = sorted((ROOT / "artifacts/governance").glob("smc_r5_htf_*.json"))
    assert artifacts, "no R5 evidence found to check"

    for artifact in artifacts:
        payload = artifact.read_text(encoding="utf-8")
        for label, pattern in patterns.items():
            assert not pattern.search(payload), f"{artifact.name} contains {label}"
