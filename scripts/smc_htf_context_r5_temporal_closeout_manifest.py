"""Immediate temporal closeout matrix for the R5 HTF Context spike."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/pine/smc_htf_context_r5_spike.pine"
BASE_EVIDENCE = (
    ROOT
    / "artifacts/governance/"
    "smc_htf_context_r5_spike_tradingview_2026-07-30.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "artifacts/governance/"
    "smc_htf_context_r5_temporal_closeout_manifest.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "gate": "R5-HTF-SPIKE",
        "status": "ready_for_private_execution",
        "purpose": (
            "Close the three temporal cases left open by the 2026-07-30 "
            "private TradingView run without waiting for future bars."
        ),
        "fixture": {
            "path": FIXTURE.relative_to(ROOT).as_posix(),
            "sha256": _sha256(FIXTURE),
            "savedScript": "SMC HTF Context R5 Spike TEST ONLY",
        },
        "baseEvidence": BASE_EVIDENCE.relative_to(ROOT).as_posix(),
        "historicalEquivalentPolicy": {
            "rule": (
                "A completed prior-year checkpoint may close the semantic DST "
                "gate when it has the same IANA-zone offset relationship and "
                "New York regular-session boundary as the future checkpoint."
            ),
            "futureRevalidationIsGateBlocking": False,
            "zones": [
                "America/New_York",
                "Europe/Berlin",
            ],
        },
        "caseCount": 3,
        "cases": [
            {
                "caseId": "R5-HTF-08",
                "closesCaseId": "R5-HTF-08",
                "mode": "live_observation",
                "chartTimeframe": "5",
                "inspectTimeframe": "15",
                "sessionMode": "regular",
                "eligibleWindow": "09:30-16:00 America/New_York",
                "expectedDiagnostics": [
                    "confirmedSourceCloseStableUntilBoundary=1",
                    "rawProbeEnabled=1",
                    "recordRawDiffersFromConfirmed",
                ],
                "tradingViewStatus": "pending",
            },
            {
                "caseId": "R5-DST-04-HISTORICAL-EQUIVALENT",
                "closesCaseId": "R5-DST-04",
                "mode": "replay",
                "chartTimeframe": "5",
                "inspectTimeframe": "15",
                "sessionMode": "regular",
                "checkpointUtc": "2025-10-27T13:45:00Z",
                "expectedDiagnostics": [
                    "sourceOpenUtc=2025-10-27T13:30:00Z",
                    "sourceCloseUtc=2025-10-27T13:45:00Z",
                    "sessionCode=3",
                    "sourceConfirmed=1",
                    "publishEdge=1",
                ],
                "tradingViewStatus": "pending",
            },
            {
                "caseId": "R5-DST-05-HISTORICAL-EQUIVALENT",
                "closesCaseId": "R5-DST-05",
                "mode": "replay",
                "chartTimeframe": "5",
                "inspectTimeframe": "15",
                "sessionMode": "regular",
                "checkpointUtc": "2025-11-03T14:45:00Z",
                "expectedDiagnostics": [
                    "sourceOpenUtc=2025-11-03T14:30:00Z",
                    "sourceCloseUtc=2025-11-03T14:45:00Z",
                    "sessionCode=3",
                    "sourceConfirmed=1",
                    "publishEdge=1",
                ],
                "tradingViewStatus": "pending",
            },
        ],
        "futureRevalidation": [
            {
                "caseId": "R5-DST-04",
                "checkpointUtc": "2026-10-26T13:45:00Z",
                "gateBlocking": False,
            },
            {
                "caseId": "R5-DST-05",
                "checkpointUtc": "2026-11-02T14:45:00Z",
                "gateBlocking": False,
            },
        ],
        "requiredTradingView": {
            "account": "preuss_steffen",
            "layout": "SMC HTF Context R5 Validation",
            "symbol": "NASDAQ:AAPL",
            "visibility": "private",
            "publicationAllowed": False,
        },
        "operatorRules": [
            "Run the two historical replay cases independently from the live observation.",
            "Enable the raw diagnostic probe only for R5-HTF-08.",
            "Capture redacted Data Window values only.",
            "Restore and save the prior chart state after each run.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    rendered = json.dumps(build_manifest(), indent=2, ensure_ascii=False) + "\n"
    if args.check:
        if (
            not args.output.exists()
            or args.output.read_text(encoding="utf-8") != rendered
        ):
            raise SystemExit(f"R5 temporal closeout manifest drift: {args.output}")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
