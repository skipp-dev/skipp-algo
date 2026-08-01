#!/usr/bin/env python3
"""Keep an automated TradingView save from silently un-attesting an R1 source.

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

What this guard does NOT do, deliberately:

* It does not fail the run before the browser opens. The chained save exists to
  stop applied chart instances freezing on an old library ("Library 9d alt",
  2026-07-22); killing the whole run would trade a stale attestation for a
  stale deployment across all eleven consumers.
* It does not touch anything the ``--verify-only`` contract governs. Holding a
  target back only matters when sources are being written at all.

What it does: name the attested sources whose repository content no longer
matches the registered evidence, so the rollout can skip exactly those and
leave what is deployed equal to what is attested. Everything else saves
normally, and the run is expected to end red -- an attestation that needs a
human is a fact about the system, not a detail to swallow.

Run as a module from the repository root::

    python -m scripts.tv_attested_source_holdback --config <rollout config>

The attested set and the hash function come from
``scripts.smc_r1_rollout_contract``; re-deriving them here would compare one
implementation against another instead of against the evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.smc_r1_rollout_contract import (
    EXECUTION_EVIDENCE,
    ROOT,
    build_rollout_contract,
)

DEFAULT_CONFIG = ROOT / "automation" / "tradingview" / "config" / "consumer-rollout.json"

_REMEDY = """
This save would replace an R1-attested source on TradingView with repository
content the registered evidence does not attest.

The targets below are held back; everything else saves normally. What is
deployed for them stays equal to what {evidence} attests, which is the only
reason the R1 contract may claim anything at all. The run ends red on purpose.

To resolve, one of:

  * Re-attest: run the rollout against the R1 layout, measure it, and register a
    NEW dated evidence artifact. Do NOT edit the existing dated artifact to
    match today's hashes -- that falsifies a measurement rather than repeating
    it.
  * Revert the source change if it was not intended to reach the live account.

Held back:
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


def holdback_names(config_path: Path, drifted: list[dict]) -> list[str]:
    """Drifted attested scripts that this rollout config would actually save.

    Intersecting with the config matters: a source can be attested without being
    a save target, and holding back a name the rollout never writes would report
    a hold that did not happen.
    """
    config = json.loads(config_path.read_text(encoding="utf-8"))
    save_targets = {target["scriptName"] for target in config.get("saveTargets", [])}
    return sorted(item["scriptName"] for item in drifted if item["scriptName"] in save_targets)


def _render(drifted: list[dict], held: list[str]) -> str:
    lines = [_REMEDY.format(evidence=EXECUTION_EVIDENCE.relative_to(ROOT).as_posix())]
    by_name = {item["scriptName"]: item for item in drifted}
    for name in held:
        item = by_name[name]
        lines.append(f"  {name}  ({item['path']})")
        lines.append(f"      evidence attests: {item['attestedSha256']}")
        lines.append(f"      repository now  : {item['repositorySha256']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()

    drifted = drifted_attested_targets()
    held = holdback_names(args.config, drifted)

    # stdout carries ONLY the machine value, so the caller can append it to
    # $GITHUB_ENV without parsing prose. Writing that file from here would mean
    # a raw append in scripts/, and appending is the one thing an atomic
    # replace cannot do without clobbering what other steps exported.
    print(json.dumps(held))

    if held:
        print(_render(drifted, held), file=sys.stderr)
    else:
        print(
            "R1-attested sources agree with the registered evidence; nothing held back.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
