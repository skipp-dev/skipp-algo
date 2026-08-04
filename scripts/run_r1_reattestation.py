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
* **PR2 (the ``measure`` subcommand)** -- reads back the two runs the
  operator's dispatch produced (the mutating consumer save, then the
  auto-re-verify it triggers) and writes a NEW dated evidence artifact --
  ``executionState: "executed"`` if both runs are green,
  ``executionState: "pending"`` (with the failure on record) otherwise -- and
  rotates the rollout contract's constants the same way PR1 did. Only a green
  measurement closes ``OPEN_GATES``.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
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


def _git(root: Path, *args: str) -> str:
    # Splatted through a local variable (mirrors scripts/hold_r1_attested_sources.py's
    # `_git` helper) rather than a bare literal argv: ruff's bandit S603 check treats a
    # fully-literal call list as provably safe and would flag the noqa below as unused.
    git_args = list(args)
    result = subprocess.run(  # noqa: S603
        ["git", *git_args],  # noqa: S607
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _git_head(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD")


_REPO_SLUG_RE = re.compile(r"[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$")


def _repo_slug(root: Path) -> str:
    """``"<owner>/<repo>"`` parsed from the ``origin`` remote's URL.

    Accepts both the SSH (``git@github.com:owner/repo.git``) and HTTPS
    (``https://github.com/owner/repo.git``) forms ``git remote get-url``
    prints back.
    """
    url = _git(root, "remote", "get-url", "origin")
    match = _REPO_SLUG_RE.search(url)
    if match is None:
        raise RuntimeError(f"could not parse owner/repo from origin remote URL: {url!r}")
    return f"{match.group('owner')}/{match.group('repo')}"


def _default_fetch_run(root: Path) -> Callable[[str], dict]:
    """Default ``fetch_run``: ``gh api repos/<owner>/<repo>/actions/runs/<id>``."""
    repo = _repo_slug(root)

    def fetch(run_id: str) -> dict:
        api_path = f"repos/{repo}/actions/runs/{run_id}"
        result = subprocess.run(  # noqa: S603
            ["gh", "api", api_path],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    return fetch


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


def _open_gates_literal(gates: tuple[str, ...]) -> str:
    if not gates:
        return "OPEN_GATES: Final = ()"
    return "OPEN_GATES: Final = (\n    " + ",\n    ".join(repr(g) for g in gates) + ",\n)"


_OPEN_GATES_START_RE = re.compile(r"^OPEN_GATES: Final = \(", re.MULTILINE)


def _replace_open_gates(contract_text: str, replacement: str) -> tuple[str, int]:
    """Replace the ``OPEN_GATES: Final = (...)`` tuple, balancing parens by hand.

    A plain ``\\([^)]*\\)`` regex breaks the moment a gate STRING itself
    contains a literal ``)`` -- PENDING_GATES has one
    (``"post-save verification (auto-re-verify) green for the bumped pin"``),
    which truncated the match at that inner paren instead of the tuple's real
    close and produced a syntactically broken file.

    Scanning parens by depth instead of by regex finds the true matching
    close paren when the parens inside the string literals are themselves
    BALANCED. It is NOT guaranteed to find it when they are not: a gate
    string with a single stray, unbalanced ``)`` (no matching ``(``) makes
    the depth counter hit zero at that inner paren instead of the real one,
    still returns count=1, and would silently corrupt the file. Guard against
    that explicitly rather than trusting the scan: verify the matched span
    actually parses back as a tuple literal via ``ast.literal_eval`` before
    reporting success, so this raises HERE -- before anything is written --
    instead of relying on the caller's ``ast.parse`` syntax guard to catch it
    by accident downstream.
    """
    start_match = _OPEN_GATES_START_RE.search(contract_text)
    if start_match is None:
        return contract_text, 0
    open_paren = start_match.end() - 1
    depth = 0
    end_paren = None
    for i in range(open_paren, len(contract_text)):
        ch = contract_text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end_paren = i
                break
    if end_paren is None:
        return contract_text, 0
    matched_span = contract_text[open_paren : end_paren + 1]
    try:
        parsed = ast.literal_eval(matched_span)
    except (SyntaxError, ValueError, TypeError) as exc:
        raise RuntimeError(
            "OPEN_GATES: Final = (...) -- the paren-depth scan landed on a "
            f"span that does not parse as a tuple literal ({exc!r}); a gate "
            "string with an unbalanced parenthesis would otherwise silently "
            f"corrupt the file here. Matched span: {matched_span!r}"
        ) from exc
    if not isinstance(parsed, tuple):
        raise RuntimeError(
            "OPEN_GATES: Final = (...) -- the paren-depth scan landed on a "
            f"span that evaluates to a {type(parsed).__name__}, not a tuple; "
            f"refusing to write a possibly-corrupted contract. Matched span: "
            f"{matched_span!r}"
        )
    new_text = contract_text[: start_match.start()] + replacement + contract_text[end_paren + 1 :]
    return new_text, 1


def _rotate_evidence_constants(
    contract_text: str,
    *,
    new_execution_name: str,
    prior_execution_name: str,
    open_gates_replacement: str | None,
) -> str:
    """Swap EXECUTION_EVIDENCE -> new, its old value -> PRIOR_EXECUTION_EVIDENCE.

    Shared by ``prepare`` (PR1) and ``measure`` (PR2) -- both rotate the same
    two constants the same way, only the OPEN_GATES treatment differs: pass
    the literal replacement text to rewrite it (``prepare`` always does;
    ``measure`` only on a green result), or ``None`` to leave OPEN_GATES
    untouched entirely (``measure`` on a red result -- the gates it was
    supposed to close stay open).

    Callers MUST have already resolved ``new_execution_name`` /
    ``prior_execution_name`` via ``_execution_and_prior_names`` on this same
    ``contract_text`` -- that call is what proves the two regexes match, so
    the ``.sub(count=1)`` calls below do not need their own not-found guard.
    """
    contract_text = _EXECUTION_BLOCK_RE.sub(
        lambda m: m.group(0).replace(m.group("name"), new_execution_name),
        contract_text,
        count=1,
    )
    contract_text = _PRIOR_BLOCK_RE.sub(
        lambda m: m.group(0).replace(m.group("name"), prior_execution_name),
        contract_text,
        count=1,
    )
    if open_gates_replacement is None:
        return contract_text
    contract_text, open_gates_subs = _replace_open_gates(contract_text, open_gates_replacement)
    if open_gates_subs != 1:
        # re.sub silently returns the input unchanged when the pattern does not
        # match -- the caller's ast.parse syntax guard would not notice either,
        # since the file stays syntactically valid. Fail loudly instead of
        # writing a contract whose OPEN_GATES tuple was never actually rotated.
        raise RuntimeError(
            "OPEN_GATES: Final = (...) not found in "
            "scripts/smc_r1_rollout_contract.py -- refusing to write a contract "
            "whose OPEN_GATES tuple was not actually rotated"
        )
    return contract_text


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
    # The name EXECUTION_EVIDENCE held before this edit becomes the new
    # PRIOR_EXECUTION_EVIDENCE -- the artifact this call supersedes.
    contract_text = _rotate_evidence_constants(
        contract_text,
        new_execution_name=new_execution_name,
        prior_execution_name=execution_name,
        open_gates_replacement=_open_gates_literal(PENDING_GATES),
    )
    ast.parse(contract_text)  # syntax guard: never write a broken file
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


def measure(
    *,
    root: Path,
    date: str,
    save_run_id: str,
    verify_run_id: str,
    fetch_run: Callable[[str], dict] | None = None,
) -> int:
    """Build PR2: read back the save + verify runs, write a NEW evidence artifact.

    Fail-closed: an incomplete run writes NOTHING at all (not even a pending
    artifact) -- there is nothing to attest about a run that has not finished.
    A completed-but-red run DOES get an artifact, because the failure itself
    is the measurement; it just stays ``executionState: "pending"`` and never
    touches ``OPEN_GATES``.

    Ordering (every read happens before the first write, so a guard failure
    anywhere below never leaves partial state on disk):

    1. Fetch both runs and require ``status == "completed"`` on each --
       return 1 before touching the filesystem otherwise.
    2. Resolve the artifact-exists guard, the current contract text, the
       ``supersedes`` path, and the old/new EXECUTION_EVIDENCE names.
    3. Compute the fully rotated contract text (constants + OPEN_GATES, the
       latter only on a green result) and syntax-check it with
       ``ast.parse`` -- still nothing written.
    4. Read the pin and hash the sources -- still nothing written.
    5. Only now: write the new evidence artifact, then the rotated contract.
    """
    if fetch_run is None:
        fetch_run = _default_fetch_run(root)

    save_run = fetch_run(save_run_id)
    verify_run = fetch_run(verify_run_id)
    if save_run["status"] != "completed" or verify_run["status"] != "completed":
        print(
            "::error::save run and/or verify run has not completed yet -- "
            "nothing written, rerun measure once both are done",
            file=sys.stderr,
        )
        return 1

    save_ok = save_run["conclusion"] == "success"
    verify_ok = verify_run["conclusion"] == "success"
    green = save_ok and verify_ok

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
    execution_name, _prior_name = _execution_and_prior_names(contract_text)

    new_execution_name = f"smc_r1_live_rollout_evidence_{date}.json"
    new_contract_text = _rotate_evidence_constants(
        contract_text,
        new_execution_name=new_execution_name,
        prior_execution_name=execution_name,
        open_gates_replacement=_open_gates_literal(()) if green else None,
    )
    ast.parse(new_contract_text)  # syntax guard: never write a broken file

    event_text = (root / "SMC_Event_Overlay.pine").read_text(encoding="utf-8")
    pin_match = PIN_RE.search(event_text)
    if pin_match is None:
        print("::error::pin line not found in SMC_Event_Overlay.pine", file=sys.stderr)
        return 1
    published = int(pin_match.group(1))

    evidence_runs = [
        {
            "runId": save_run_id,
            "conclusion": save_run["conclusion"],
            "createdAt": save_run["created_at"],
            "name": save_run["name"],
        },
        {
            "runId": verify_run_id,
            "conclusion": verify_run["conclusion"],
            "createdAt": verify_run["created_at"],
            "name": verify_run["name"],
        },
    ]
    remaining_gates = [gate for gate, ok in zip(PENDING_GATES, (save_ok, verify_ok)) if not ok]
    repo_commit_sha = _git_head(root)

    artifact = {
        "schemaVersion": 2,
        "executionState": "executed" if green else "pending",
        "capturedAt": _utc_now_iso(),
        "scope": (
            "Measurement of the mutating consumer save "
            f"(run {save_run_id}) and its auto-re-verify (run {verify_run_id}) "
            "the operator dispatched after PR1. "
            + (
                "Both runs completed green -- the pin move is now live."
                if green
                else "At least one run completed red -- the pin move is NOT "
                "attested live; the failing run's conclusion is on record below."
            )
        ),
        "supersedes": supersedes,
        "supersessionNote": "Superseded as the CURRENT attestation, not corrected.",
        "sources": [_source_entry(root, rel) for rel in _TARGET_SOURCES],
        "tradingView": {
            "observed": True,
            "note": "observed via the dispatched save + auto-re-verify run pair",
        },
        "openGates": remaining_gates,
        "evidenceRuns": evidence_runs,
        "repoCommitSha": repo_commit_sha,
        "libraryReleaseVersion": published,
    }

    # Every read-only check above passed -- write the artifact, THEN the
    # contract it registers on (deliberately the opposite order from
    # `prepare`'s pin-then-contract-then-artifact: if the process dies
    # between these two writes, the contract should never end up pointing at
    # an EXECUTION_EVIDENCE file that does not exist on disk yet).
    atomic_write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", artifact_path)
    atomic_write_text(new_contract_text, contract_path)

    if not green:
        print(
            "PR2 measured RED -- artifact written as executionState=pending, "
            "OPEN_GATES left untouched:",
            file=sys.stderr,
        )
        print(f"  save run {save_run_id}: {save_run['conclusion']}", file=sys.stderr)
        print(f"  verify run {verify_run_id}: {verify_run['conclusion']}", file=sys.stderr)
        return 1

    print("PR2 measured green. OPEN_GATES closed.")
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

    measure_parser = subparsers.add_parser(
        "measure",
        help=(
            "Build PR2: read back the save + verify runs, write a new "
            "evidence artifact, close OPEN_GATES only if both are green."
        ),
    )
    measure_parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="repository working tree to operate on (default: this checkout)",
    )
    measure_parser.add_argument(
        "--date",
        default=None,
        help="date stamp (YYYY-MM-DD) for the new evidence artifact (default: today, UTC)",
    )
    measure_parser.add_argument(
        "--save-run-id", required=True, help="run ID of the mutating consumer save"
    )
    measure_parser.add_argument(
        "--verify-run-id", required=True, help="run ID of the auto-re-verify it triggered"
    )

    args = parser.parse_args(argv)

    if args.command == "prepare":
        target_date = args.date or datetime.now(UTC).date().isoformat()
        return prepare(root=Path(args.root).resolve(), date=target_date)

    if args.command == "measure":
        target_date = args.date or datetime.now(UTC).date().isoformat()
        return measure(
            root=Path(args.root).resolve(),
            date=target_date,
            save_run_id=args.save_run_id,
            verify_run_id=args.verify_run_id,
        )

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
