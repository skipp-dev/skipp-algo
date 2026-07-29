"""Build the fail-closed operational contract for the R1 companion rollout.

The generated contract stays separate from the immutable private TradingView
evidence.  It may report the rollout complete only while the checked-in
evidence path is registered and the canonical source hashes remain current.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Final

from scripts.smc_atomic_write import atomic_write_text
from scripts.smc_bus_manifest import (
    EVENT_OVERLAY_BUS_LABELS,
    EXIT_SIGNAL_BUS_LABELS,
)

ROOT: Final = Path(__file__).resolve().parents[1]
EVENT_SOURCE: Final = ROOT / "SMC_Event_Overlay.pine"
EXIT_SOURCE: Final = ROOT / "SMC_Exit_Signal.pine"
CONFIG: Final = ROOT / "automation" / "tradingview" / "preflight-r1-companions.json"
DEFAULT_OUTPUT: Final = ROOT / "artifacts" / "governance" / "smc_r1_live_rollout_contract.json"
EXECUTION_EVIDENCE: Final = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_r1_live_rollout_evidence_2026-07-29.json"
)


def _source(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def _event_library_pin() -> dict:
    text = EVENT_SOURCE.read_text(encoding="utf-8")
    match = re.search(
        r"import preuss_steffen/smc_micro_profiles_generated/(\d+) as mp",
        text,
    )
    if match is None:
        raise RuntimeError("Event Overlay micro-profile import pin not found")
    return {
        "importPath": "preuss_steffen/smc_micro_profiles_generated",
        "version": int(match.group(1)),
    }


def build_rollout_contract() -> dict:
    return {
        "schemaVersion": 1,
        "gate": "R1-LIVE-ROLLOUT",
        "status": "authorized_execution_completed",
        "executionPerformed": True,
        "executionEvidence": EXECUTION_EVIDENCE.relative_to(ROOT).as_posix(),
        "preflight": {
            "config": CONFIG.relative_to(ROOT).as_posix(),
            "scope": "smcR1Companions",
            "command": (
                "npx tsx scripts/tv_preflight.ts "
                "--config automation/tradingview/preflight-r1-companions.json "
                "--execution-mode mutating"
            ),
        },
        "targets": [
            {
                **_source(EVENT_SOURCE),
                "scriptName": "SMC Event Overlay",
                "bindingLabels": list(EVENT_OVERLAY_BUS_LABELS),
                "libraryPin": _event_library_pin(),
                "requiredAlerts": [
                    "Event Restriction Hard Block Started",
                    "Event Restriction Window Started",
                ],
            },
            {
                **_source(EXIT_SOURCE),
                "scriptName": "SMC Exit Signal",
                "bindingLabels": list(EXIT_SIGNAL_BUS_LABELS),
                "requiredAlerts": [
                    "ENTER LONG (trigger filled)",
                    "EXIT — Stop hit",
                    "EXIT — TP1 (take half)",
                    "EXIT — TP2 (close rest)",
                    "EXIT — Defensive (setup invalidated)",
                    "EXIT (any full close)",
                ],
            },
        ],
        "layoutContract": {
            "preset": "Simple Management",
            "requiredScripts": [
                "SMC Long-Dip Suite",
                "SMC Event Overlay",
                "SMC Exit Signal",
            ],
            "actionableExitMode": "exit_signal",
            "forbiddenConcurrentActionableExitMode": "hold_manager",
        },
        "requiredEvidence": [
            "authenticated private TradingView account and intended layout identity",
            "post-save compile success for both canonical sources",
            "persisted saved-source SHA-256 equality after chart reload",
            "one Event Overlay and nine Exit Signal BUS bindings to SMC Long-Dip Suite",
            "alert-condition inventory and single-edge replay evidence",
            "saved Simple Management layout with Hold Manager actionable alerts disabled",
            "rollback drill removing both companions without changing the Suite or existing consumers",
        ],
        "claimPolicy": [
            "This contract and its repository tests do not independently prove live TradingView state; the registered immutable execution evidence does.",
            "Keep these targets deployed only while the registered source hashes, bindings, alert inventory, layout exclusivity, reload, and rollback evidence remain valid.",
        ],
        "openGates": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    atomic_write_text(
        json.dumps(build_rollout_contract(), indent=2, sort_keys=True) + "\n",
        args.out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
