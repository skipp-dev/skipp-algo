#!/usr/bin/env python3
"""Fail a PR that moves an R1-attested source away from its execution evidence.

``artifacts/governance/smc_r1_live_rollout_contract.json`` claims
``status: authorized_execution_completed`` with ``openGates: []``. That claim
rests entirely on the registered immutable evidence, and the contract says so
itself:

    Keep these targets deployed only while the registered source hashes,
    bindings, alert inventory, layout exclusivity, reload, and rollback
    evidence remain valid.

``tests/test_smc_r1_rollout_contract.py`` already asserts that. It is not on
the fast-gates allowlist, so it only runs in the main-push job — AFTER a merge.
The library-refresh bot walked straight through that hole twice on 2026-07-31 /
2026-08-01: #4272 bumped ``SMC_Event_Overlay.pine`` from
``smc_micro_profiles_generated/179`` to ``/180`` and #4284 went on to ``/182``,
each time changing the source hash the evidence attests to. Both PRs were green
when they merged; main has been red on the R1 contract ever since.

This guard closes the merge path rather than the state. It is deliberately
scoped to the PR's own diff:

* main is ALREADY drifted, so a state check here would fail every PR in the
  repo — including the ones that would repair it;
* what must not happen again is a change that moves an attested source further
  from its evidence without anyone noticing before the merge.

So a PR fails only when it touches an attested source AND leaves that source
disagreeing with the evidence. A PR that restores the attested content, or that
lands a fresh rollout with new evidence, passes. Everything that does not touch
these files is not this guard's business — the main-push contract test keeps
reporting the standing state.

The attested set, the file paths and the hash function all come from
``scripts.smc_r1_rollout_contract``. Re-deriving them here would mean comparing
one implementation against another instead of against the evidence.

Run it as a module -- ``python -m scripts.check_r1_attested_sources`` -- from the
repository root. Invoked by path it cannot import the ``scripts`` package unless
the caller happens to export ``PYTHONPATH``, and a guard that silently passes in
a lane that forgot an environment variable is worse than no guard at all.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys

from scripts.smc_r1_rollout_contract import (
    EXECUTION_EVIDENCE,
    ROOT,
    build_rollout_contract,
)

_REMEDY = """
An R1-attested source may not change while the registered evidence still
attests to the previous content.

  1. Re-run the R1 companion rollout against the new source
     (scripts/tv_preflight.ts --config
     automation/tradingview/preflight-r1-companions.json
     --execution-mode mutating; the smc-r4-context-readback workflow runs the
     TradingView session from CI).
  2. Record a NEW dated evidence artifact for that run.
  3. Point artifacts/governance/smc_r1_live_rollout_contract.json at it.

Do NOT edit the existing dated evidence artifact to match. It records what was
measured on that date; rewriting it falsifies a measurement rather than fixing
a drift.
""".strip()


def _changed_paths(commit_range: str) -> set[str]:
    result = subprocess.run(  # noqa: S603
        ["git", "diff", "--name-only", commit_range],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    )
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def attested_sources() -> dict:
    """The ``scriptName -> {repositorySha256: ...}`` map the evidence registers."""
    return json.loads(EXECUTION_EVIDENCE.read_text(encoding="utf-8"))["sources"]


def find_offenders(
    changed: set[str],
    *,
    targets: list[dict] | None = None,
    sources: dict | None = None,
) -> list[str]:
    """Attested sources this change touches while leaving them un-attested.

    Two different inputs, deliberately: the range says WHICH files this change
    is responsible for, and the CHECKED-OUT content says what they now hash to.
    In fast-gates the checkout is the PR head, so that pair reads as "this PR
    touched the file and left it disagreeing with the evidence". Run over an
    arbitrary historical range in a different working tree it still answers a
    well-defined question, just not that one -- the hash reported is always the
    one on disk.

    ``targets`` / ``sources`` default to the live contract and evidence. They
    are injectable so the tests can exercise BOTH branches deterministically:
    keying them off whatever happens to be drifted today would make the test
    skip itself the moment the repo is repaired, which is the vacuity this repo
    has been removing (#4267).
    """
    if targets is None:
        targets = build_rollout_contract()["targets"]
    if sources is None:
        sources = attested_sources()
    offenders: list[str] = []

    for target in targets:
        path = target["path"]
        if path not in changed:
            continue
        script_name = target["scriptName"]
        attested = sources[script_name]["repositorySha256"]
        current = target["sha256"]
        if current == attested:
            continue
        offenders.append(
            f"{path} ({script_name})\n"
            f"    evidence attests: {attested}\n"
            f"    checked out now : {current}"
        )
    return offenders


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--range",
        required=True,
        dest="commit_range",
        help="git commit range to inspect, e.g. BASE_SHA..HEAD_SHA",
    )
    args = parser.parse_args()

    offenders = find_offenders(_changed_paths(args.commit_range))
    if not offenders:
        return 0

    evidence_path = EXECUTION_EVIDENCE.relative_to(ROOT).as_posix()
    print(
        f"::error::R1-attested source changed without new rollout evidence "
        f"({evidence_path})",
        file=sys.stderr,
    )
    for offender in offenders:
        print(f"  {offender}", file=sys.stderr)
    print(f"\n{_REMEDY}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
