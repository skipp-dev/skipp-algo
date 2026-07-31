"""Contract gates for the R5 live HTF and session companion rebuild."""

from __future__ import annotations

import hashlib
import json
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

    for file_name in ("SMC_HTF_Confluence.pine", "SMC_Session_Context.pine"):
        surface = _surface(file_name)
        assert surface["lifecycle"] == "active"
        assert surface["compile_expectation"] == "required"
        assert surface["known_missing_mp_fields"] == []
        assert surface["archive_state"] == "none"
        assert surface["rollout_state"] == "not_deployed"


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


def test_traceability_keeps_r5_rebuild_partial_until_private_runtime() -> None:
    requirement = _requirement("R5-REBUILD")

    assert requirement["status"] == "partial"
    assert HTF_SOURCE.relative_to(ROOT).as_posix() in requirement["evidence"]
    assert SESSION_SOURCE.relative_to(ROOT).as_posix() in requirement["evidence"]
    assert DEFAULT_OUTPUT.relative_to(ROOT).as_posix() in requirement["evidence"]
    # 2026-07-31: the private compile gate is closed. Both root companions
    # compiled and ran green on the private validation layout after the
    # CE10156 line-wrapping fix (#4239) and the preflight stale-instance fix
    # (#4241) — the second of which is what let the gate observe the fix
    # instead of re-measuring the failed instance. The replay,
    # live-observation and rollback cases stay open, so the requirement stays
    # partial and this list must not shrink further without their evidence.
    assert requirement["openGates"] == [
        "Execute the replay, live-observation, and rollback cases in smc_r5_htf_session_rebuild_manifest.json.",
        "Record replay, layout, and rollback evidence before deployment.",
    ]


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
