#!/usr/bin/env python3
"""Driver for an R1 companion re-attestation, split into PR1 / PR2.

An R1 re-attestation moves the ``SMC_Event_Overlay.pine`` library pin to the
currently published ``smc_micro_profiles_generated`` release and then proves
the moved pin is live on TradingView. That is two distinct acts separated by
a mutating TradingView session this script never performs itself:

* **PR1 (this module's ``prepare`` subcommand)** -- repo-only intent. Bumps
  the pin, writes a NEW dated evidence artifact with
  ``executionState: "pending"``, and rotates the rollout contract's
  ``EXECUTION_EVIDENCE`` / ``PRIOR_EXECUTION_EVIDENCE`` constants and
  ``OPEN_GATES`` tuple to point at it. Read-only against TradingView --
  nothing here saves a consumer source, dispatches a workflow, commits, or
  pushes. That is left to the operator, printed as the "Next steps" below.
* **PR2 (the ``measure`` subcommand)** -- reads back the runs the operator's
  dispatch produced and closes the artifact to ``executionState: "executed"``.
  Not implemented by this module yet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from scripts.smc_atomic_write import atomic_write_text

ROOT: Final = Path(__file__).resolve().parents[1]

PIN_RE = re.compile(r"import preuss_steffen/smc_micro_profiles_generated/(\d+) as mp")

# The gates PR1 leaves open. `measure` (Task 5) is the only sanctioned way to
# close them -- each needs a run ID this module never dispatches.
PENDING_GATES: Final = (
    "mutating consumer save of SMC_Event_Overlay.pine at the bumped pin",
    "post-save verification (auto-re-verify) green for the bumped pin",
)

# The two R1-attested sources every evidence artifact re-hashes. Kept as a
# tuple here rather than derived from the rollout contract's `targets`:
# `prepare` runs BEFORE the contract's own constants are rotated, so reading
# `build_rollout_contract()` at this point would still be describing the
# artifact this call is about to supersede.
_TARGET_SOURCES: Final = ("SMC_Event_Overlay.pine", "SMC_Exit_Signal.pine")

# `scripts/smc_r1_rollout_contract.py` carries its two evidence-path
# constants as fixed four-line blocks:
#
#   EXECUTION_EVIDENCE: Final = (
#       ROOT
#       / "artifacts"
#       / "governance"
#       / "smc_r1_live_rollout_evidence_<date>.json"
#   )
#
# and the same shape for `PRIOR_EXECUTION_EVIDENCE`. Anchored on `^NAME:
# Final = (` (MULTILINE) so `PRIOR_EXECUTION_EVIDENCE` -- which contains
# `EXECUTION_EVIDENCE` as a substring -- never matches the `EXECUTION_EVIDENCE`
# pattern.
_EXECUTION_BLOCK_RE = re.compile(
    r'^EXECUTION_EVIDENCE: Final = \(\s*'
    r'ROOT\s*/\s*"artifacts"\s*/\s*"governance"\s*/\s*'
    r'"(?P<name>smc_r1_live_rollout_evidence_[0-9-]+\.json)"\s*\)',
    re.MULTILINE,
)
_PRIOR_BLOCK_RE = re.compile(
    r'^PRIOR_EXECUTION_EVIDENCE: Final = \(\s*'
    r'ROOT\s*/\s*"artifacts"\s*/\s*"governance"\s*/\s*'
    r'"(?P<name>smc_r1_live_rollout_evidence_[0-9-]+\.json)"\s*\)',
    re.MULTILINE,
)


def _git_head(root: Path) -> str:
    # Splatted through a local variable (mirrors scripts/hold_r1_attested_sources.py's
    # `_git` helper) rather than a bare literal argv: ruff's bandit S603 check treats a
    # fully-literal call list as provably safe and would flag the noqa below as unused.
    git_args = ["rev-parse", "HEAD"]
    result = subprocess.run(  # noqa: S603
        ["git", *git_args],  # noqa: S607
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _source_entry(root: Path, relpath: str) -> dict:
    text = (root / relpath).read_text(encoding="utf-8")
    return {"path": relpath, "sha256": hashlib.sha256(text.encode()).hexdigest()}


def _execution_and_prior_names(contract_text: str) -> tuple[str, str]:
    """``(execution_filename, prior_filename)`` as currently written.

    Verifies ``EXECUTION_EVIDENCE`` precedes ``PRIOR_EXECUTION_EVIDENCE`` in
    the file -- the ordering the swap in ``prepare`` depends on -- instead of
    silently assuming it.
    """
    execution_match = _EXECUTION_BLOCK_RE.search(contract_text)
    prior_match = _PRIOR_BLOCK_RE.search(contract_text)
    if execution_match is None or prior_match is None:
        raise RuntimeError(
            "could not locate the EXECUTION_EVIDENCE / PRIOR_EXECUTION_EVIDENCE "
            "constant blocks in scripts/smc_r1_rollout_contract.py"
        )
    if execution_match.start() >= prior_match.start():
        raise RuntimeError(
            "expected EXECUTION_EVIDENCE to precede PRIOR_EXECUTION_EVIDENCE in "
            "scripts/smc_r1_rollout_contract.py -- the swap below assumes that "
            "order and it has drifted"
        )
    return execution_match.group("name"), prior_match.group("name")


def _current_registered_relpath(contract_text: str) -> str:
    """Repo-relative path of the artifact this call's `prepare` supersedes."""
    execution_name, _prior_name = _execution_and_prior_names(contract_text)
    return f"artifacts/governance/{execution_name}"


def prepare(*, root: Path, date: str) -> int:
    """Build PR1: bump the pin, write a pending evidence artifact, rotate the contract.

    Read-only against TradingView. Leaves the diff uncommitted -- committing,
    pushing, opening PR1, and dispatching the mutating save stay with the
    operator (printed below).
    """
    event = root / "SMC_Event_Overlay.pine"
    manifest_path = root / "artifacts" / "tradingview" / "library_release_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    published = manifest["library"]["publishedVersion"]

    text = event.read_text(encoding="utf-8")
    match = PIN_RE.search(text)
    if match is None:
        print("::error::pin line not found in SMC_Event_Overlay.pine", file=sys.stderr)
        return 1
    current = int(match.group(1))
    if current >= published:
        print(
            f"pin {current} already at/above published {published} -- nothing to prepare",
            file=sys.stderr,
        )
        return 1

    artifact_path = root / "artifacts" / "governance" / f"smc_r1_live_rollout_evidence_{date}.json"
    if artifact_path.exists():
        print(
            f"{artifact_path.name} exists -- same-day rerun is an operator special case",
            file=sys.stderr,
        )
        return 1

    contract_path = root / "scripts" / "smc_r1_rollout_contract.py"
    contract_text = contract_path.read_text(encoding="utf-8")
    supersedes = _current_registered_relpath(contract_text)
    execution_name = supersedes.rsplit("/", 1)[-1]

    # Bump the pin FIRST: the artifact hashes the working tree AFTER the
    # bump, never the pre-bump content.
    atomic_write_text(
        PIN_RE.sub(
            f"import preuss_steffen/smc_micro_profiles_generated/{published} as mp",
            text,
        ),
        event,
    )

    new_execution_name = f"smc_r1_live_rollout_evidence_{date}.json"
    contract_text = _EXECUTION_BLOCK_RE.sub(
        lambda m: m.group(0).replace(m.group("name"), new_execution_name),
        contract_text,
        count=1,
    )
    # The name EXECUTION_EVIDENCE held before this edit becomes the new
    # PRIOR_EXECUTION_EVIDENCE -- the artifact this call supersedes.
    contract_text = _PRIOR_BLOCK_RE.sub(
        lambda m: m.group(0).replace(m.group("name"), execution_name),
        contract_text,
        count=1,
    )
    contract_text, open_gates_subs = re.subn(
        r"OPEN_GATES: Final = \([^)]*\)",
        "OPEN_GATES: Final = (\n    "
        + ",\n    ".join(repr(g) for g in PENDING_GATES)
        + ",\n)",
        contract_text,
        count=1,
    )
    if open_gates_subs != 1:
        # re.sub silently returns the input unchanged when the pattern does not
        # match -- compile() would not notice either, since the file stays
        # syntactically valid. Fail loudly instead of writing a contract whose
        # OPEN_GATES tuple was never actually rotated to PENDING_GATES.
        raise RuntimeError(
            "OPEN_GATES: Final = (...) not found in "
            "scripts/smc_r1_rollout_contract.py -- refusing to write a contract "
            "whose OPEN_GATES tuple was not actually rotated"
        )
    compile(contract_text, str(contract_path), "exec")  # never write a broken file
    atomic_write_text(contract_text, contract_path)

    artifact = {  # honest: repo measured, TradingView not observed
        "schemaVersion": 2,
        "executionState": "pending",
        "capturedAt": _utc_now_iso(),
        "scope": (
            f"Authorization to move the SMC_Event_Overlay.pine library pin {current} -> "
            f"{published}. Repository-side measurement only; TradingView is deliberately "
            "NOT observed here -- the save has not happened yet. The verify cron may "
            "report source drift between this PR's merge and the dispatch; that is the "
            "expected intermediate state."
        ),
        "supersedes": supersedes,
        "supersessionNote": "Superseded as the CURRENT attestation, not corrected.",
        "sources": [_source_entry(root, rel) for rel in _TARGET_SOURCES],
        "tradingView": {"observed": False, "note": "not yet observed -- see openGates"},
        "openGates": list(PENDING_GATES),
        "evidenceRuns": [],
        "repoCommitSha": _git_head(root),
        "libraryReleaseVersion": published,
    }
    atomic_write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", artifact_path)

    print("PR1 prepared. Next steps:")
    print("  1. review the diff, commit, push, open PR1, merge it")
    print("  2. dispatch the mutating save:")
    print(
        "     gh workflow run tv-save-consumer-source.yml "
        '-f mapping=\'[{"source":"SMC_Event_Overlay.pine","scriptName":"SMC Event Overlay"}]\''
    )
    print(
        "  3. after save + auto-re-verify: python -m scripts.run_r1_reattestation "
        "measure --save-run-id <id> --verify-run-id <id>"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser(
        "prepare",
        help=(
            "Build PR1: bump the pin, write a pending evidence artifact, "
            "rotate the rollout contract constants."
        ),
    )
    prepare_parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="repository working tree to operate on (default: this checkout)",
    )
    prepare_parser.add_argument(
        "--date",
        default=None,
        help="date stamp (YYYY-MM-DD) for the new evidence artifact (default: today, UTC)",
    )

    args = parser.parse_args(argv)

    if args.command == "prepare":
        target_date = args.date or datetime.now(UTC).date().isoformat()
        return prepare(root=Path(args.root).resolve(), date=target_date)

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
