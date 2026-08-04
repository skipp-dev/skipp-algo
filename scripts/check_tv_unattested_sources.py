#!/usr/bin/env python3
"""Report when an automated TradingView save un-attests an R1 source.

``scripts/check_r1_attested_sources.py`` (#4286) closes the PULL REQUEST path:
a diff that moves an attested source away from its evidence fails the gate.
It does not close the path the 2026-08-01 incident actually took.

``tv-save-consumer-source`` pushes the repository's Pine sources into the saved
TradingView scripts. It runs on ``schedule``, on ``workflow_dispatch``, and --
this is the one that fired -- chained on a successful ``smc-library-refresh``.
None of those is a pull request, so no gate observed it. The refresh bumped the
Event Overlay micro-profile pin ``179 -> 182``, the chained save pushed the new
source, and the source the R1 evidence attests stopped existing anywhere. The
evidence still read ``authorized_execution_completed`` with ``openGates: []``.

The gap was never that the save happened. It is that nobody learned the
attestation had died. So this does not block the save and does not skip a
target: everything is pushed, exactly as before, and the run reports that an
attested source is now deployed un-attested.

The alternative -- holding the drifted targets back -- was built first and
deliberately dropped (operator decision, 2026-08-01). It keeps the evidence
literally true but freezes those two scripts on an old pinned library while the
producer moves on, which is a live divergence traded for a bookkeeping one.

Run as a module from the repository root::

    python -m scripts.check_tv_unattested_sources --config <rollout config>

The attested set and the hash function come from
``scripts.smc_r1_rollout_contract``; re-deriving them here would compare one
implementation against another instead of against the evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Final

from scripts.smc_r1_rollout_contract import (
    EXECUTION_EVIDENCE,
    ROOT,
    build_rollout_contract,
)

DEFAULT_CONFIG = ROOT / "automation" / "tradingview" / "config" / "consumer-rollout.json"

#: The resolution paths for a dead R1 attestation, held exactly ONCE.
#:
#: Two producers report this same drift and must not be able to describe it
#: differently: this script (the automated-save path, via :data:`_REMEDY`
#: below) and the "Report R1 attestation drift caused by this refresh" step in
#: ``.github/workflows/smc-library-refresh.yml`` (the library-refresh path,
#: which IMPORTS this constant instead of re-typing the prose). A hand-copy in
#: the workflow would be the same defect class that
#: ``tests/test_fast_gates_attested_pine_coverage.py`` exists to close and that
#: cost 12 production runs in #4333 -- a hand-maintained duplicate going stale
#: -- applied to prose rather than to a file list. The failure would be that
#: someone adds a resolution path here, both scripts follow, and the refresh PR
#: body keeps telling operators the old thing.
#:
#: Carries an ``{evidence}`` placeholder; format it before emitting.
#:
#: The placeholder sits on a line of its own. It renders to a ~66-character
#: repository path, so interpolating it mid-sentence produced a 189-character
#: line -- which broke the 80-column stderr block on the save path and forced
#: horizontal scrolling inside the fenced block in the refresh PR body. One
#: break fixes both consumers; the rendered width is pinned by
#: tests/test_smc_library_refresh_workflow.py.
RESOLUTION: Final = """To resolve, one of:

  * Re-attest: run the rollout against the R1 layout, measure it, and register a
    NEW dated evidence artifact alongside the registered one:
      {evidence}
    Do NOT edit that artifact to match today's hashes. A dated measurement is
    superseded by a NEW artifact, never rewritten -- editing it
    replaces a measurement with a fabrication.
    Then repoint the registration, or nothing reads the new artifact. Both
    pointers in scripts/smc_r1_rollout_contract.py move together: set
    EXECUTION_EVIDENCE to the new artifact and PRIOR_EXECUTION_EVIDENCE to the
    one it supersedes. Regenerate
    artifacts/governance/smc_r1_live_rollout_contract.json, which mirrors both
    as executionEvidence / priorExecutionEvidence.
    tests/test_smc_r1_rollout_contract.py pins the module and the artifact
    equal on BOTH pointers, so dropping a new artifact beside the old one and
    stopping there leaves the repo red -- as does moving only the first.
  * Revert the source change if it was not intended to reach the live account,
    then re-run the tv-save-consumer-source workflow to push the attested
    content back.
"""

_REMEDY = """
This save replaces an R1-attested source on TradingView with repository content
the registered evidence does not attest.

The save is NOT blocked -- the sources below are pushed like every other
consumer, so the deployment stays consistent with the repository. What changes
is that
  {evidence}
stops describing what is deployed the moment this run finishes. The run ends
red for exactly that reason.

{resolution}
Saved without attestation:
"""


def attested_sources() -> dict:
    """The registered evidence, which is the only authority on what is attested."""
    return json.loads(EXECUTION_EVIDENCE.read_text(encoding="utf-8"))["sources"]


def drifted_attested_targets(
    *,
    targets: list[dict] | None = None,
    sources: dict | None = None,
) -> list[dict]:
    """Attested scripts whose repository content no longer matches the evidence.

    ``targets``/``sources`` are injectable so the tests can drive real drift and
    real agreement instead of skipping when the checked-in state happens to be
    clean. A guard whose tests skip is the vacuity #4267 removed.
    """
    if targets is None:
        targets = build_rollout_contract()["targets"]
    if sources is None:
        sources = attested_sources()

    drifted: list[dict] = []
    for target in targets:
        script_name = target["scriptName"]
        attested = sources.get(script_name, {}).get("repositorySha256")
        if attested is None or attested == target["sha256"]:
            continue
        drifted.append(
            {
                "scriptName": script_name,
                "path": target["path"],
                "attestedSha256": attested,
                "repositorySha256": target["sha256"],
            }
        )
    return drifted


def unattested_save_targets(config_path: Path, drifted: list[dict]) -> list[str]:
    """Drifted attested scripts that this rollout config actually saves.

    Intersecting with the config matters: a source can be attested without being
    a save target, and reporting a name the rollout never writes would claim an
    un-attestation that did not happen.
    """
    config = json.loads(config_path.read_text(encoding="utf-8"))
    save_targets = {target["scriptName"] for target in config.get("saveTargets", [])}
    return sorted(item["scriptName"] for item in drifted if item["scriptName"] in save_targets)


def _render(drifted: list[dict], unattested: list[str]) -> str:
    evidence = EXECUTION_EVIDENCE.relative_to(ROOT).as_posix()
    lines = [_REMEDY.format(evidence=evidence, resolution=RESOLUTION.format(evidence=evidence))]
    by_name = {item["scriptName"]: item for item in drifted}
    for name in unattested:
        item = by_name[name]
        lines.append(f"  {name}  ({item['path']})")
        lines.append(f"      evidence attests: {item['attestedSha256']}")
        lines.append(f"      being saved now : {item['repositorySha256']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()

    drifted = drifted_attested_targets()
    unattested = unattested_save_targets(args.config, drifted)

    # stdout carries ONLY the machine value: the caller writes it into a step
    # output, and any prose here would land in that value.
    print(json.dumps(unattested))

    if unattested:
        print(_render(drifted, unattested), file=sys.stderr)
    else:
        print(
            "R1-attested sources agree with the registered evidence; this save keeps them attested.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
