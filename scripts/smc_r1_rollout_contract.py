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
    / "smc_r1_live_rollout_evidence_2026-08-04.json"
)
# Every superseded artifact stays checked in and unmodified. Each is a dated
# measurement and remains true of its day; it is superseded as the CURRENT
# attestation, never rewritten to match today's state. 2026-07-29 -> 2026-08-01
# -> 2026-08-04, each step driven by a library refresh moving the Event Overlay
# import pin and the chained consumer save pushing the new source live.
PRIOR_EXECUTION_EVIDENCE: Final = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_r1_live_rollout_evidence_2026-08-01.json"
)

# The rollback gate, and ONLY that gate, is closed by a later run on the same
# day (30710010604, 17:23:24Z). Its own dated artifact carries it. The R1
# evidence above still reads rollback.status = not_run and stays that way: it
# was captured at 05:05:15Z, when no implementation existed, and a dated
# measurement is repeated by a new artifact rather than rewritten to match a
# later one.
ROLLBACK_DRILL_EVIDENCE: Final = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_r1_rollback_drill_2026-08-01.json"
)

# The three fields no automation reports -- alert-condition inventory, layout
# inventory with Hold Manager exclusivity, compile status after a final reload.
# The operator read them off the live layout on 2026-08-01 at 19:40Z and
# supplied screenshots, exactly as on 2026-07-29. The readonly preflight still
# does not report them, so this stays an attended observation by design.
OPERATOR_OBSERVATION_EVIDENCE: Final = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_r1_operator_observation_2026-08-01.json"
)

# Empty, and that is a claim in its own right. It is only allowed to be empty
# because every gate the registered evidence lists as open now has its own
# dated artifact below; the tests derive this from those artifacts rather than
# trusting the literal.
OPEN_GATES: Final = ()

# How many sources ``build_rollout_contract()["targets"]`` must register, held
# here because more than one consumer derives that roster and each needs a
# non-vacuity floor: a derivation that silently yields nothing would let both
# report a clean all-clear forever.
#
# Consumers (both DERIVE the roster, neither hand-lists it):
#   * tests/test_fast_gates_attested_pine_coverage.py -- asserts every attested
#     source is picked up by the run_pine_guard arm in smc-fast-pr-gates.yml,
#     which is what pulls the R1 guard onto a pine-only bot PR.
#   * the "Report R1 attestation drift caused by this refresh" step in
#     .github/workflows/smc-library-refresh.yml.
#
# It lives here rather than in either consumer because it is a property of the
# contract, not of the thing reading it. Two unlinked copies of this number is
# the defect those consumers exist to prevent: a legitimate roster change would
# update one, and the other would then be wrong -- the test pinning a stale
# floor, or the refresh hard-failing on a roster that is actually correct.
# Lower it only together with a reason, in the same PR that shrinks the roster.
MIN_ATTESTED_SOURCES: Final = 2


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
        "status": "authorized_execution_reattested",
        "executionPerformed": True,
        "executionEvidence": EXECUTION_EVIDENCE.relative_to(ROOT).as_posix(),
        "priorExecutionEvidence": PRIOR_EXECUTION_EVIDENCE.relative_to(ROOT).as_posix(),
        # Gates the registered evidence lists as open and that a LATER dated
        # artifact has since closed. This list is the only sanctioned way for a
        # gate to leave openGates: the alternative is editing the registered
        # evidence so it agrees with today, which replaces a measurement with a
        # fabrication. The tests derive openGates from the evidence minus this
        # list, so a gate cannot be dropped without an artifact behind it.
        "closedSinceRegisteredEvidence": [
            {
                "gate": "rollback drill removing and restoring both companions",
                "status": "passed",
                "evidence": ROLLBACK_DRILL_EVIDENCE.relative_to(ROOT).as_posix(),
                "run": 30710010604,
                "note": (
                    "The registered evidence still records rollback.status = not_run "
                    "as of 05:05:15Z, when no implementation existed. The drill ran at "
                    "17:23:24Z. Both readings are true of their own moment; the dated "
                    "measurement is repeated by a new artifact, never rewritten."
                ),
            },
            *(
                {
                    "gate": gate,
                    "status": "passed",
                    "evidence": OPERATOR_OBSERVATION_EVIDENCE.relative_to(ROOT).as_posix(),
                    "observer": "preuss_steffen",
                    "note": (
                        "Read off the live layout at 19:40Z with screenshots. No automation "
                        "reports this field, which is why the 05:05:15Z evidence records it "
                        "as not_run and keeps doing so."
                    ),
                }
                for gate in (
                    "alert-condition inventory for both companions",
                    "Hold Manager exclusivity and Simple Management layout inventory",
                    "chart-instance compile status after a final reload",
                )
            ),
        ],
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
            "An automated consumer save can overwrite an attested source without passing any pull request, so a source hash matching the evidence proves re-attestation only for the axes the evidence actually measured. Read openGates before treating this contract as complete.",
        ],
        "openGates": list(OPEN_GATES),
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
