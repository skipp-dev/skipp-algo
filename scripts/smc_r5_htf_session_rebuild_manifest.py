#!/usr/bin/env python3
"""Generate the private TradingView execution matrix for the R5 rebuild."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

ROOT = Path(__file__).resolve().parents[1]
HTF_SOURCE = ROOT / "SMC_HTF_Confluence.pine"
SESSION_SOURCE = ROOT / "SMC_Session_Context.pine"
DEFAULT_OUTPUT = ROOT / "artifacts/governance/smc_r5_htf_session_rebuild_manifest.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest() -> dict[str, Any]:
    cases = [
        {
            "caseId": "R5-REBUILD-COMPILE-HTF",
            "mode": "compile",
            "target": "htfConfluence",
            "expectedDiagnostics": ["compileStatus=passed", "runtimeError=0"],
        },
        {
            "caseId": "R5-REBUILD-COMPILE-SESSION",
            "mode": "compile",
            "target": "sessionContext",
            "expectedDiagnostics": ["compileStatus=passed", "runtimeError=0"],
        },
        {
            "caseId": "R5-REBUILD-HTF-15M",
            "mode": "replay",
            "chartTimeframe": "5",
            "inspectTimeframe": "15",
            "expectedDiagnostics": [
                "available=1",
                "sourceConfirmed=1",
                "sourceCloseAdvancesOnlyAtBoundary=1",
            ],
        },
        {
            "caseId": "R5-REBUILD-HTF-1H",
            "mode": "replay",
            "chartTimeframe": "5",
            "inspectTimeframe": "60",
            "expectedDiagnostics": [
                "available=1",
                "sourceConfirmed=1",
                "sourceCloseAdvancesOnlyAtBoundary=1",
            ],
        },
        {
            "caseId": "R5-REBUILD-HTF-4H",
            "mode": "replay",
            "chartTimeframe": "5",
            "inspectTimeframe": "240",
            "expectedDiagnostics": [
                "available=1",
                "sourceConfirmed=1",
                "sourceCloseAdvancesOnlyAtBoundary=1",
            ],
        },
        {
            "caseId": "R5-REBUILD-FAIL-CLOSED",
            "mode": "replay",
            "chartTimeframes": ["15", "60", "240"],
            "expectedDiagnostics": [
                "equalOrLowerRequestedFrameAvailable=0",
                "partialDataAvailable=0",
            ],
        },
        {
            "caseId": "R5-REBUILD-LIVE-NO-REPAINT",
            "mode": "live_observation",
            "chartTimeframe": "5",
            "sessionMode": "regular",
            "expectedDiagnostics": [
                "confirmedValuesStableInsideOpenSourceBar=1",
                "lookaheadOffProductPath=0",
            ],
        },
        {
            "caseId": "R5-REBUILD-DST-EU-GAP",
            "mode": "replay",
            "checkpointUtc": "2025-10-27T13:45:00Z",
            "expectedDiagnostics": [
                "sessionCode=3",
                "sessionLabel=NY AM",
                "sourceCloseUtc=2025-10-27T13:45:00Z",
            ],
        },
        {
            "caseId": "R5-REBUILD-DST-STANDARD",
            "mode": "replay",
            "checkpointUtc": "2025-11-03T14:45:00Z",
            "expectedDiagnostics": [
                "sessionCode=3",
                "sessionLabel=NY AM",
                "sourceCloseUtc=2025-11-03T14:45:00Z",
            ],
        },
        {
            "caseId": "R5-REBUILD-EXTENDED",
            "mode": "replay",
            "sessionMode": "extended",
            "checkpointUtc": "2026-03-09T21:15:00Z",
            # Corrected 2026-07-31, on the first execution of this case, by
            # owner decision.
            #
            # It was preregistered as sessionCode=0 / "Outside", carried over
            # from the R5-HTF-SPIKE case R5-SESSION-01, which pins the SAME
            # instant and calls it "outside all configured context sessions".
            # That is true of the SPIKE script and false of this one, because
            # the two define the Asia window as opposite halves of the day:
            #
            #   spike   smc_htf_context_r5_spike.pine  asia "0900-1700" Tokyo
            #   product SMC_Session_Context.pine       asia "0000-0900" Tokyo
            #
            # 2026-03-09T21:15Z is 2026-03-10 06:15 in Asia/Tokyo, a Tuesday.
            # That is OUTSIDE 09:00-17:00 (so the spike is right to expect 0)
            # and INSIDE 00:00-09:00 (so this script is right to report Asia).
            # NY AM, NY PM and London are outside it either way, so
            # _session_code() falls through to Asia here.
            #
            # The chart agrees: with Extended session data the case observed
            # sessionCode=1 / "Asia" at a sourceCloseUtc of exactly
            # 2026-03-09T21:15:00Z. The expectation was wrong, not the script —
            # and the completed spike gate is NOT affected, so do not "fix" it.
            "expectedDiagnostics": [
                "sessionCode=1",
                "sessionLabel=Asia",
                "sourceConfirmed=1",
            ],
        },
        {
            "caseId": "R5-REBUILD-ROLLBACK",
            "mode": "layout_restore",
            "expectedDiagnostics": [
                "sourceHashVerified=1",
                "priorChartStateRestored=1",
                "layoutSaved=1",
            ],
        },
    ]
    for case in cases:
        case["tradingViewStatus"] = "pending"
    return {
        "schemaVersion": 1,
        "gate": "R5-REBUILD",
        "status": "all_cases_executed",
        "purpose": ("Validate the rebuilt live HTF Confluence and Session Context companions before any deployment."),
        "statusSemantics": (
            "Per-case tradingViewStatus values preserve the preregistered baseline, as in the "
            "R5-HTF-SPIKE manifest. Actual private runtime outcomes are recorded in resultEvidence."
        ),
        "resultEvidence": [
            # First execution: COMPILE-SESSION passed, COMPILE-HTF failed with CE10156.
            "artifacts/governance/smc_r5_htf_session_rebuild_tradingview_2026-07-31.json",
            # Compiler verdict for that failure and for the fix (pine-facade translate_light).
            "artifacts/governance/smc_r5_htf_session_rebuild_ce10156_diagnosis_2026-07-31.json",
            # Re-execution after the fix: both compile cases green on every axis.
            "artifacts/governance/smc_r5_htf_session_rebuild_preflight_green_2026-07-31.json",
            # The two DST replay cases, driven by Bar Replay checkpoints (#4243).
            "artifacts/governance/smc_r5_htf_session_rebuild_replay_2026-07-31.json",
            # EXTENDED, after the expectation itself was corrected to Asia (#4244/#4245).
            "artifacts/governance/smc_r5_htf_session_rebuild_extended_2026-07-31.json",
            # Why replay stepping only ever advanced once: the Forward control
            # drops its title attribute on click (#4250).
            "artifacts/governance/smc_r5_htf_stepping_mechanism_2026-07-31.json",
            # FAIL-CLOSED plus HTF-15M/1H certified; HTF-4H deliberately not (#4248/#4250).
            "artifacts/governance/smc_r5_htf_availability_2026-07-31.json",
            # LIVE-NO-REPAINT against the open regular session.
            "artifacts/governance/smc_r5_htf_session_rebuild_live_no_repaint_2026-07-31.json",
            # ROLLBACK: capture, perturb, restore, save, reload, verify.
            "artifacts/governance/smc_r5_htf_session_rebuild_rollback_2026-07-31.json",
        ],
        "sources": {
            "htfConfluence": {
                "path": HTF_SOURCE.relative_to(ROOT).as_posix(),
                "sha256": _sha256(HTF_SOURCE),
                "savedScript": "SMC HTF Confluence",
            },
            "sessionContext": {
                "path": SESSION_SOURCE.relative_to(ROOT).as_posix(),
                "sha256": _sha256(SESSION_SOURCE),
                "savedScript": "SMC Session Context",
            },
        },
        "caseCount": len(cases),
        "cases": cases,
        "requiredTradingView": {
            "account": "preuss_steffen",
            "layout": "SMC HTF Context R5 Validation",
            "symbol": "NASDAQ:AAPL",
            "visibility": "private",
            "publicationAllowed": False,
        },
        "operatorRules": [
            "Capture rendered chart and Data Window diagnostics only.",
            "Do not publish either root script during validation.",
            "Run historical checkpoints in the Europe/Berlin chart timezone.",
            "Restore and save the prior chart state after execution.",
        ],
    }


def main() -> int:
    atomic_write_text(
        json.dumps(build_manifest(), indent=2, sort_keys=False) + "\n",
        DEFAULT_OUTPUT,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
