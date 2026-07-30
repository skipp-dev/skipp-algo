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
            "expectedDiagnostics": [
                "sessionCode=0",
                "sessionLabel=Outside",
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
        "status": "ready_for_private_execution",
        "purpose": ("Validate the rebuilt live HTF Confluence and Session Context companions before any deployment."),
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
