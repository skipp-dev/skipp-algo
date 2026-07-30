"""Canonical private replay matrix for the R5 HTF Context technical spike."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/pine/smc_htf_context_r5_spike.pine"
DEFAULT_OUTPUT = (
    ROOT / "artifacts/governance/smc_htf_context_r5_spike_manifest.json"
)


@dataclass(frozen=True)
class SpikeCase:
    case_id: str
    name: str
    category: str
    chart_timeframe: str
    inspect_timeframe: str
    session_mode: str
    runtime_mode: str
    checkpoint_utc: str | None
    expected_diagnostics: tuple[str, ...]


CASES: tuple[SpikeCase, ...] = (
    SpikeCase(
        "R5-HTF-01",
        "private fixture compiles with ContextFrame builder in request.security",
        "compile",
        "5",
        "15",
        "regular",
        "compile",
        None,
        ("compileStatus=passed", "memoryError=0", "runtimeError=0"),
    ),
    SpikeCase(
        "R5-HTF-02",
        "15m confirmed publication on a 5m chart",
        "timeframe",
        "5",
        "15",
        "regular",
        "replay",
        None,
        ("available=1", "sourceConfirmed=1", "publishOnlyAt15mBoundary=1"),
    ),
    SpikeCase(
        "R5-HTF-03",
        "1h confirmed publication on a 5m chart",
        "timeframe",
        "5",
        "60",
        "regular",
        "replay",
        None,
        ("available=1", "sourceConfirmed=1", "publishOnlyAt1hBoundary=1"),
    ),
    SpikeCase(
        "R5-HTF-04",
        "4h confirmed publication on a 5m chart",
        "timeframe",
        "5",
        "240",
        "regular",
        "replay",
        None,
        ("available=1", "sourceConfirmed=1", "publishOnlyAt4hBoundary=1"),
    ),
    SpikeCase(
        "R5-HTF-05",
        "equal 15m request fails closed while higher frames remain available",
        "timeframe_relation",
        "15",
        "15",
        "regular",
        "replay",
        None,
        ("15mRelationValid=0", "1hRelationValid=1", "4hRelationValid=1"),
    ),
    SpikeCase(
        "R5-HTF-06",
        "lower and equal requests fail closed on a 1h chart",
        "timeframe_relation",
        "60",
        "60",
        "regular",
        "replay",
        None,
        ("15mRelationValid=0", "1hRelationValid=0", "4hRelationValid=1"),
    ),
    SpikeCase(
        "R5-HTF-07",
        "all fixed frames fail closed on a 4h chart",
        "timeframe_relation",
        "240",
        "240",
        "regular",
        "replay",
        None,
        ("15mRelationValid=0", "1hRelationValid=0", "4hRelationValid=0"),
    ),
    SpikeCase(
        "R5-HTF-08",
        "raw lookahead_off arm can diverge during an open 15m bar",
        "repaint_probe",
        "5",
        "15",
        "regular",
        "live_observation",
        None,
        (
            "confirmedSourceCloseStableUntilBoundary=1",
            "rawProbeEnabled=1",
            "recordRawDiffersFromConfirmed",
        ),
    ),
    SpikeCase(
        "R5-DST-01",
        "New York open before US spring DST",
        "dst",
        "5",
        "15",
        "regular",
        "replay",
        "2026-03-06T14:45:00Z",
        (
            "sourceOpenUtc=2026-03-06T14:30:00Z",
            "sessionCode=3",
            "sourceConfirmed=1",
        ),
    ),
    SpikeCase(
        "R5-DST-02",
        "New York open during the US-only spring DST gap",
        "dst",
        "5",
        "15",
        "regular",
        "replay",
        "2026-03-09T13:45:00Z",
        (
            "sourceOpenUtc=2026-03-09T13:30:00Z",
            "sessionCode=3",
            "sourceConfirmed=1",
        ),
    ),
    SpikeCase(
        "R5-DST-03",
        "New York open after European spring DST",
        "dst",
        "5",
        "15",
        "regular",
        "replay",
        "2026-03-30T13:45:00Z",
        (
            "sourceOpenUtc=2026-03-30T13:30:00Z",
            "sessionCode=3",
            "sourceConfirmed=1",
        ),
    ),
    SpikeCase(
        "R5-DST-04",
        "New York open during the Europe-only autumn DST gap",
        "dst",
        "5",
        "15",
        "regular",
        "replay",
        "2026-10-26T13:45:00Z",
        (
            "sourceOpenUtc=2026-10-26T13:30:00Z",
            "sessionCode=3",
            "sourceConfirmed=1",
        ),
    ),
    SpikeCase(
        "R5-DST-05",
        "New York open after US autumn DST",
        "dst",
        "5",
        "15",
        "regular",
        "replay",
        "2026-11-02T14:45:00Z",
        (
            "sourceOpenUtc=2026-11-02T14:30:00Z",
            "sessionCode=3",
            "sourceConfirmed=1",
        ),
    ),
    SpikeCase(
        "R5-SESSION-01",
        "extended-hours bar outside all configured context sessions",
        "session",
        "5",
        "15",
        "extended",
        "replay",
        "2026-03-09T21:15:00Z",
        (
            "sourceOpenUtc=2026-03-09T21:00:00Z",
            "sessionCode=0",
            "sourceConfirmed=1",
        ),
    ),
    SpikeCase(
        "R5-PERF-01",
        "request and execution budget capture",
        "performance",
        "5",
        "15",
        "extended",
        "profiler",
        None,
        (
            "uniqueRequestSites<=4",
            "drawingObjects=0",
            "memoryError=0",
            "runtimeError=0",
            "recordProfilerRuntime",
        ),
    ),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "gate": "R5-HTF-SPIKE",
        "gateStatus": "partial",
        "surfaceClass": "test_only_not_managed_not_publishable",
        "fixture": {
            "path": FIXTURE.relative_to(ROOT).as_posix(),
            "scriptName": "SMC HTF Context R5 Spike TEST ONLY",
            "sha256": _sha256(FIXTURE),
            "publishedContextLibrary": (
                "preuss_steffen/smc_context_engine_private/4"
            ),
        },
        "semantics": {
            "acceptedConfirmedPattern": (
                "one-requested-bar expression offset plus "
                "barmerge.lookahead_on"
            ),
            "diagnosticOnlyPattern": (
                "unoffset expression plus barmerge.lookahead_off"
            ),
            "timeframeRelation": "strictly_higher_only",
            "fixedTimeframes": ["15", "60", "240"],
            "calcBarsCount": 1000,
        },
        "caseCount": len(CASES),
        "cases": [
            {
                **asdict(case),
                "expected_diagnostics": list(case.expected_diagnostics),
                "tradingViewStatus": "pending",
            }
            for case in CASES
        ],
        "performanceBudget": {
            "maxUniqueRequestSites": 4,
            "maxDrawingObjects": 0,
            "requiresProfilerRuntimeCapture": True,
            "mustAvoidMemoryLimitError": True,
            "mustAvoidRuntimeTimeout": True,
        },
        "requiredTradingView": {
            "layoutName": "SMC HTF Context R5 Validation",
            "symbol": "NASDAQ:AAPL",
            "chartTimeframes": ["5", "15", "60", "240"],
            "defaultChartTimeframe": "5",
            "savedScript": "SMC HTF Context R5 Spike TEST ONLY",
            "visibility": "private",
            "publicationAllowed": False,
        },
        "operatorRules": [
            "Use only the private SMC HTF Context R5 Validation layout.",
            "Do not publish the fixture or add it to a managed layout.",
            "Run live-observation and replay cases separately.",
            "Capture redacted Data Window and Pine Profiler evidence only.",
            "Restore the previous chart state after the spike.",
        ],
        "openGates": [
            "Private TradingView compile is pending.",
            "Fifteen-case replay/live-observation matrix is pending.",
            "Pine Profiler and memory/runtime evidence is pending.",
            "The direct-stateful versus dedicated-stateless implementation decision is pending.",
        ],
        "references": [
            "https://www.tradingview.com/pine-script-docs/concepts/repainting/",
            "https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/",
            "https://www.tradingview.com/pine-script-docs/writing/limitations/",
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
            raise SystemExit(f"R5 HTF spike manifest drift: {args.output}")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
