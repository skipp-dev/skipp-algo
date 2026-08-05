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
import importlib.util
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

# The two R1-attested sources every evidence artifact re-hashes, as
# ``repo-relative path -> scriptName``. The scriptName is the KEY the v2
# evidence schema files each source under, and it is what
# `scripts/check_r1_attested_sources.py` indexes by
# (``sources[scriptName]["repositorySha256"]``) -- an artifact that keyed them
# any other way would crash that guard rather than fail it.
#
# Kept as a literal here rather than derived from the rollout contract's
# `targets`: `prepare` runs BEFORE the contract's own constants are rotated, so
# reading `build_rollout_contract()` at this point would still be describing the
# artifact this call is about to supersede.
_TARGET_SOURCES: Final = {
    "SMC_Event_Overlay.pine": "SMC Event Overlay",
    "SMC_Exit_Signal.pine": "SMC Exit Signal",
}

# `measure`'s artifact carries this suffix so a prepare and a measure on the
# SAME day cannot collide. The one-day PR1 -> dispatch -> PR2 round trip is the
# NORMAL operator flow, and the pre-#4453 driver aborted on it -- which forced
# the operator to pass a `--date` that was not the measurement's date, i.e. to
# falsify the one field a dated artifact exists to carry.
_MEASURE_SUFFIX: Final = "-measure"

# The workflow BOTH runs must belong to. The mutating consumer save and the
# auto-re-verify it triggers run in the same workflow (the re-verify is a
# `workflow_run` chain onto itself), so this is one name, not two. Without it
# `measure` attests the pin move from ANY two green runs in the repository.
_SAVE_WORKFLOW_NAME: Final = "tv-save-consumer-source"

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
#
# The name pattern spells the date out (``YYYY-MM-DD``) with an OPTIONAL
# ``-measure`` suffix rather than the older, laxer ``[0-9-]+``: `measure` now
# writes ``..._<date>-measure.json`` (see `_MEASURE_SUFFIX`), which ``[0-9-]+``
# would not have matched -- the rotation would then have silently found no
# EXECUTION_EVIDENCE block to swap.
_EVIDENCE_NAME_PATTERN: Final = (
    r"smc_r1_live_rollout_evidence_[0-9]{4}-[0-9]{2}-[0-9]{2}(?:-measure)?\.json"
)
_EXECUTION_BLOCK_RE = re.compile(
    r'^EXECUTION_EVIDENCE: Final = \(\s*'
    r'ROOT\s*/\s*"artifacts"\s*/\s*"governance"\s*/\s*'
    rf'"(?P<name>{_EVIDENCE_NAME_PATTERN})"\s*\)',
    re.MULTILINE,
)
_PRIOR_BLOCK_RE = re.compile(
    r'^PRIOR_EXECUTION_EVIDENCE: Final = \(\s*'
    r'ROOT\s*/\s*"artifacts"\s*/\s*"governance"\s*/\s*'
    rf'"(?P<name>{_EVIDENCE_NAME_PATTERN})"\s*\)',
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


def _parse_run_timestamp(value: str) -> datetime:
    """GitHub's ``created_at`` (ISO 8601, ``Z``-suffixed) as an aware datetime.

    Python 3.11+ ``fromisoformat`` accepts the ``Z`` suffix directly; parsed
    rather than compared as strings so a future format drift fails loudly
    instead of ordering lexically.
    """
    return datetime.fromisoformat(value)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _repository_hashes(root: Path, *, event_text: str) -> dict[str, str]:
    """``scriptName -> sha256`` of the sources as this call will leave them.

    ``event_text`` is passed in rather than re-read so `prepare` can hash the
    BUMPED Event Overlay before it has written anything at all -- every read
    happens before the first write.
    """
    hashes: dict[str, str] = {}
    for relpath, script_name in _TARGET_SOURCES.items():
        text = event_text if relpath == "SMC_Event_Overlay.pine" else (
            (root / relpath).read_text(encoding="utf-8")
        )
        hashes[script_name] = _sha256(text)
    return hashes


def _pending_sources(hashes: dict[str, str]) -> dict:
    """The v2 ``sources`` map for an artifact that has NOT been saved live.

    Same shape and same keys as an executed artifact -- ``check_r1_attested_sources``
    indexes ``sources[scriptName]["repositorySha256"]`` and must not have to
    know which kind of artifact is registered -- but every field that only a
    TradingView session can fill says so instead of carrying a value:
    ``savedSourceReadbackSha256: null`` and ``compileStatus: "pending"``. That
    is the same honesty the 2026-08-01 artifact showed with
    ``rollback.status: "not_run"``: a field that was not measured reads as not
    measured, rather than being omitted or filled with the repository's own
    hash (which would assert that the repo content is live on TradingView --
    precisely the claim `measure` exists to make and `prepare` may not).
    """
    return {
        script_name: {
            "path": relpath,
            "repositorySha256": hashes[script_name],
            "savedSourceReadbackSha256": None,
            "compileStatus": "pending",
            "compileDiagnostics": [],
            "compileEvidenceMechanism": (
                "Nothing was saved to TradingView by this step. The saved source and "
                "its compile status are unknown until the mutating consumer save and "
                "its auto-re-verify have run -- both are listed in openGates."
            ),
        }
        for relpath, script_name in _TARGET_SOURCES.items()
    }


def _measured_sources(
    hashes: dict[str, str], *, green: bool, save_run_id: str, verify_run_id: str
) -> dict:
    """The v2 ``sources`` map for an artifact backed by the save + verify pair.

    On GREEN, ``savedSourceReadbackSha256`` equals the repository hash and
    ``compileStatus`` is ``passed`` -- and ``compileEvidenceMechanism`` says
    exactly how that is known, because this driver never opened a browser: the
    save step throws unless the post-save compile settles clean, and the
    auto-re-verify re-reads every saved source and fails on any drift. A green
    pair therefore MEANS "saved == repository, compiled clean"; the field
    carries that derivation and the two run IDs rather than a hash transcript
    this process did not read. That is the same mechanism the 2026-08-04
    artifact recorded by hand.

    On RED nothing of the sort is known, so both fields fall back to the
    pending reading and the failing pair is still named.
    """
    if not green:
        pending = _pending_sources(hashes)
        for entry in pending.values():
            entry["compileEvidenceMechanism"] = (
                f"The save run {save_run_id} and/or the auto-re-verify run {verify_run_id} "
                "completed RED, so nothing about the saved source or its compile status "
                "is attested. See evidenceRuns for the conclusions."
            )
            entry["saveRun"] = save_run_id
            entry["savedSourceReadbackRun"] = verify_run_id
        return pending
    return {
        script_name: {
            "path": relpath,
            "repositorySha256": hashes[script_name],
            "savedSourceReadbackSha256": hashes[script_name],
            "compileStatus": "passed",
            "compileDiagnostics": [],
            "compileEvidenceMechanism": (
                f"Derived from two green runs, not from a hash this tool read back: "
                f"run {save_run_id} saves each consumer source and throws unless the "
                f"post-save compile settles without a visible error, and run "
                f"{verify_run_id} re-reads every saved source and fails on any drift "
                "from the repository. Both concluded success, which is what makes "
                "savedSourceReadbackSha256 equal to repositorySha256 here. No attended "
                "observation of the compile badge was made."
            ),
            "saveRun": save_run_id,
            "savedSourceReadbackRun": verify_run_id,
        }
        for relpath, script_name in _TARGET_SOURCES.items()
    }


def _carry_forward(superseded: dict, supersedes: str, *, accounted: tuple[str, ...]) -> dict:
    """The measurements a new artifact inherits instead of re-running.

    Three sections, all derived from the artifact being superseded rather than
    invented:

    * ``rollback`` / ``replay`` -- carried over with the SAME evidence path the
      predecessor named (or the predecessor itself, if it ran the measurement),
      plus a justification that says it was not re-run here.
    * ``carriedOverGates`` -- every gate the predecessor listed as open that
      this artifact neither lists as open itself nor measured (``accounted``).
      Without it those gates would simply cease to exist the moment a new
      artifact is registered: the contract's ``closedSinceRegisteredEvidence``
      entries are scoped to a NAMED registered artifact, so they drop out on
      rotation, and the predecessor's openGates are not inherited by default.
      Four gates would have vanished silently on the first `prepare`.
    """
    rollback = superseded.get("rollback", {})
    replay = superseded.get("replay", {})
    carried_gates = [dict(entry) for entry in superseded.get("carriedOverGates", [])]
    known = {entry["gate"] for entry in carried_gates}
    for gate in superseded.get("openGates", []):
        if gate in accounted or gate in known:
            continue
        carried_gates.append(
            {
                "gate": gate,
                "status": "not_measured_here",
                "priorArtifact": supersedes,
                "note": (
                    "Listed as open by the artifact this one supersedes and NOT "
                    "measured by this step. Whatever dated artifact closed it "
                    "did so against the superseded registration; re-registering "
                    "that closure requires a closedSinceRegisteredEvidence entry "
                    "scoped to THIS artifact."
                ),
            }
        )
    return {
        "rollback": {
            "status": "carried_over",
            "evidence": rollback.get("evidence", supersedes),
            "justification": (
                "The companion rollback drill was NOT re-run here. Its own dated "
                "artifact carries it, exactly as it did for the artifact this one "
                f"supersedes ({supersedes})."
            ),
        },
        "replay": {
            "status": "carried_over",
            "passedLogicalCases": replay.get("passedLogicalCases"),
            "evidence": replay.get("evidence", supersedes),
            "justification": (
                "The single-edge replay covers SMC Exit Signal, whose source is "
                "byte-identical to the value the superseded artifact attests. "
                "Nothing the replay measured changed, so it is carried rather "
                "than re-run."
            ),
        },
        "carriedOverGates": carried_gates,
    }


def _replay_not_carried(supersedes: str) -> dict:
    """Exit Signal moved, so the older replay no longer describes it."""
    return {
        "status": "not_carried_over",
        "evidence": None,
        "justification": (
            "SMC Exit Signal is NOT byte-identical to the value the superseded "
            f"artifact ({supersedes}) attests, so the earlier replay describes a "
            "source nobody replayed. It is deliberately not carried forward."
        ),
    }


def _regenerate_contract_json(root: Path) -> Path:
    """Re-run the contract generator IN ``root`` after rotating its constants.

    ``artifacts/governance/smc_r1_live_rollout_contract.json`` is a GENERATED
    file, and ``test_checked_in_rollout_contract_is_current`` asserts it equals
    ``build_rollout_contract()`` exactly. Rotating the module's constants
    without regenerating it leaves the checked-in JSON pointing at the previous
    evidence -- red on the main-push job, in a PR whose entire purpose is to
    move that pointer.

    Loaded from ``root`` by file location rather than imported as
    ``scripts.smc_r1_rollout_contract``: the module derives every path from its
    OWN ``__file__``, so this is what makes the regeneration apply to the tree
    being operated on (and lets the tests prove it against a throwaway tree).
    Its own imports still resolve through ``sys.path`` -- they are behavior
    (atomic writes, the BUS label roster), not paths.
    """
    module_path = root / "scripts" / "smc_r1_rollout_contract.py"
    spec = importlib.util.spec_from_file_location("_r1_rollout_contract_at_root", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load the rollout contract module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output: Path = module.DEFAULT_OUTPUT
    atomic_write_text(
        json.dumps(module.build_rollout_contract(), indent=2, sort_keys=True) + "\n",
        output,
    )
    return output


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

    superseded_path = root / supersedes
    if not superseded_path.exists():
        print(
            f"::error::the registered evidence {supersedes} is not in this tree -- "
            "refusing to write an artifact that claims to supersede something it "
            "never read",
            file=sys.stderr,
        )
        return 1
    superseded = json.loads(superseded_path.read_text(encoding="utf-8"))

    # Everything below is still read-only. The BUMPED source is hashed from
    # this string, so the artifact describes the tree this call is about to
    # leave behind -- never the pre-bump content, and never a file that has
    # been written before the last guard has run.
    bumped_text = PIN_RE.sub(
        f"import preuss_steffen/smc_micro_profiles_generated/{published} as mp",
        text,
    )
    hashes = _repository_hashes(root, event_text=bumped_text)
    superseded_sources = superseded["sources"]
    exit_unchanged = (
        superseded_sources["SMC Exit Signal"]["repositorySha256"] == hashes["SMC Exit Signal"]
    )
    carried = _carry_forward(superseded, supersedes, accounted=PENDING_GATES)
    if not exit_unchanged:
        carried["replay"] = _replay_not_carried(supersedes)

    new_execution_name = f"smc_r1_live_rollout_evidence_{date}.json"
    # The name EXECUTION_EVIDENCE held before this edit becomes the new
    # PRIOR_EXECUTION_EVIDENCE -- the artifact this call supersedes.
    contract_text = _rotate_evidence_constants(
        contract_text,
        new_execution_name=new_execution_name,
        prior_execution_name=execution_name,
        open_gates_replacement=_open_gates_literal(PENDING_GATES),
    )
    # Syntax guard: never write a broken file. `filename=` so a SyntaxError
    # names the contract instead of "<unknown>".
    ast.parse(contract_text, filename=str(contract_path))

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
        "supersessionKind": "source_change",
        "supersessionNote": "Superseded as the CURRENT attestation, not corrected.",
        "reattestationTrigger": {
            "reason": (
                "Deliberate re-attestation of the R1 companion library pin. Since the "
                "library refresh HOLDS the attested companions, the pin only moves here, "
                "by an operator acting on the r1-pin-drift watcher."
            ),
            "attestedEventOverlaySha256": superseded_sources["SMC Event Overlay"][
                "repositorySha256"
            ],
            "supersededByRepositorySha256": hashes["SMC Event Overlay"],
            "sourceDiffCharacter": (
                f"library pin {current} -> {published} in the import line; "
                + (
                    "SMC Exit Signal is byte-identical to the superseded attested value "
                    "and is re-attested unchanged."
                    if exit_unchanged
                    else "SMC Exit Signal ALSO differs from the superseded attested "
                    "value -- see the replay section."
                )
            ),
        },
        "sources": _pending_sources(hashes),
        "tradingView": {
            "observed": False,
            "note": (
                "Repository-only preparation: nothing was saved to, read from, or "
                "otherwise observed on TradingView here -- see openGates."
            ),
            "bindings": "not_observed",
            "bindingsChecked": "not_observed",
            "bindingMismatches": "not_observed",
            "unknownParentRuntimeError": "not_observed",
            "suitePresence": "not_observed",
            "alertConditionInventory": "not_run",
            "holdManagerPresent": "not_run",
            "forbiddenConcurrentScriptsPresent": "not_run",
            "finalInventory": "not_run",
            "compileStatusAfterFinalReload": "not_run",
        },
        **carried,
        "openGates": list(PENDING_GATES),
        "evidenceRuns": [],
        "repoCommitSha": _git_head(root),
        # The library release this attestation COVERS -- i.e. the pin the
        # sources above carry, not whatever the manifest happens to publish
        # later. `prepare` sets it to `published` because it has just bumped
        # the pin to exactly that; `measure` reads it back off the pin line.
        "libraryReleaseVersion": published,
    }

    # Every guard above has passed. Writes start here, in dependency order:
    # source, then the contract module that registers the artifact, then the
    # artifact, then the generated contract JSON (which reads both).
    atomic_write_text(bumped_text, event)
    atomic_write_text(contract_text, contract_path)
    atomic_write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", artifact_path)
    contract_json = _regenerate_contract_json(root)

    print("PR1 prepared. Next steps:")
    print(f"  0. regenerated {contract_json.relative_to(root).as_posix()} -- include it in PR1")
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

    1. Fetch both runs, require ``status == "completed"`` on each, and prove
       they are the RIGHT runs (both from the ``tv-save-consumer-source``
       workflow, verify not created before save) -- return 1 before touching
       the filesystem otherwise.
    2. Resolve the artifact-exists guard, the current contract text, the
       ``supersedes`` path, the superseded artifact itself, and the old/new
       EXECUTION_EVIDENCE names.
    3. Compute the fully rotated contract text (constants + OPEN_GATES, the
       latter only on a green result) and syntax-check it with
       ``ast.parse`` -- still nothing written.
    4. Read the pin and hash the sources -- still nothing written.
    5. Only now: write the new evidence artifact, then the rotated contract,
       then regenerate the contract JSON.
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

    # Run IDENTITY, before anything is derived from the pair. Without this,
    # `measure` attests "the pin move is live on TradingView" from ANY two
    # completed green runs in the repository -- a lint run and a docs build
    # would do. The mutating save and the auto-re-verify it chains both run in
    # `tv-save-consumer-source`, so the workflow name is one value for both,
    # and the verify can never predate the save that triggered it.
    for label, run_id, run in (
        ("save", save_run_id, save_run),
        ("verify", verify_run_id, verify_run),
    ):
        if run.get("name") != _SAVE_WORKFLOW_NAME:
            print(
                f"::error::{label} run {run_id} belongs to workflow {run.get('name')!r}, "
                f"not {_SAVE_WORKFLOW_NAME!r} -- nothing written; an R1 attestation may "
                "only be built from the consumer-save workflow's own runs",
                file=sys.stderr,
            )
            return 1
    if _parse_run_timestamp(verify_run["created_at"]) < _parse_run_timestamp(
        save_run["created_at"]
    ):
        print(
            f"::error::verify run {verify_run_id} was created "
            f"({verify_run['created_at']}) BEFORE save run {save_run_id} "
            f"({save_run['created_at']}) -- it cannot be the re-verify of that save; "
            "nothing written",
            file=sys.stderr,
        )
        return 1

    save_ok = save_run["conclusion"] == "success"
    verify_ok = verify_run["conclusion"] == "success"
    green = save_ok and verify_ok

    artifact_path = (
        root
        / "artifacts"
        / "governance"
        / f"smc_r1_live_rollout_evidence_{date}{_MEASURE_SUFFIX}.json"
    )
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

    superseded_path = root / supersedes
    if not superseded_path.exists():
        print(
            f"::error::the registered evidence {supersedes} is not in this tree -- "
            "refusing to write an artifact that claims to supersede something it "
            "never read",
            file=sys.stderr,
        )
        return 1
    superseded = json.loads(superseded_path.read_text(encoding="utf-8"))

    new_execution_name = f"smc_r1_live_rollout_evidence_{date}{_MEASURE_SUFFIX}.json"
    new_contract_text = _rotate_evidence_constants(
        contract_text,
        new_execution_name=new_execution_name,
        prior_execution_name=execution_name,
        open_gates_replacement=_open_gates_literal(() if green else PENDING_GATES),
    )
    # Syntax guard: never write a broken file. `filename=` so a SyntaxError
    # names the contract instead of "<unknown>".
    ast.parse(new_contract_text, filename=str(contract_path))

    event_text = (root / "SMC_Event_Overlay.pine").read_text(encoding="utf-8")
    pin_match = PIN_RE.search(event_text)
    if pin_match is None:
        print("::error::pin line not found in SMC_Event_Overlay.pine", file=sys.stderr)
        return 1
    # The pin PR1 moved the source to. Not "the version published right now":
    # the manifest may have moved on since PR1 merged, and this attestation
    # covers the pin the measured save actually pushed.
    pin_version = int(pin_match.group(1))

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
    hashes = _repository_hashes(root, event_text=event_text)
    # On RED the artifact's openGates stay BOTH pending gates, exactly like the
    # contract's OPEN_GATES tuple that `measure` deliberately does not touch:
    # the contract tests pin OPEN_GATES == evidence.openGates - closedSince, and
    # a per-failed-gate subset here would break that invariant on precisely the
    # red-path PR2 whose whole content is "the gates are still open". Which run
    # failed lives in evidenceRuns, not in the gate roster.
    open_gates = [] if green else list(PENDING_GATES)
    carried = _carry_forward(superseded, supersedes, accounted=PENDING_GATES)
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
        "supersessionKind": "execution_measurement",
        "supersessionNote": "Superseded as the CURRENT attestation, not corrected.",
        "sources": _measured_sources(
            hashes, green=green, save_run_id=save_run_id, verify_run_id=verify_run_id
        ),
        "tradingView": (
            {
                "observed": True,
                "note": (
                    "Observed via the dispatched save + auto-re-verify run pair; "
                    "no attended browser session was opened by this driver."
                ),
                # No per-label inventory was READ here -- the verify run fails
                # on any binding mismatch, so a green pair proves the bindings
                # without this process holding the label map. The reference
                # must point at a run recorded green in evidenceRuns; the
                # contract tests enforce exactly that shape.
                "bindings": {"status": "verified_by_run", "run": verify_run_id},
                "bindingsChecked": {"status": "verified_by_run", "run": verify_run_id},
                "bindingMismatches": {"status": "verified_by_run", "run": verify_run_id},
                "unknownParentRuntimeError": {
                    "status": "verified_by_run",
                    "run": verify_run_id,
                },
                "suitePresence": "inferred",
                "alertConditionInventory": "not_run",
                "holdManagerPresent": "not_run",
                "forbiddenConcurrentScriptsPresent": "not_run",
                "finalInventory": "not_run",
                "compileStatusAfterFinalReload": "not_run",
            }
            if green
            else {
                "observed": False,
                "note": (
                    "The dispatched pair completed RED -- nothing about the live "
                    "TradingView state is attested by this artifact; see "
                    "evidenceRuns for the conclusions."
                ),
                "bindings": "not_observed",
                "bindingsChecked": "not_observed",
                "bindingMismatches": "not_observed",
                "unknownParentRuntimeError": "not_observed",
                "suitePresence": "not_observed",
                "alertConditionInventory": "not_run",
                "holdManagerPresent": "not_run",
                "forbiddenConcurrentScriptsPresent": "not_run",
                "finalInventory": "not_run",
                "compileStatusAfterFinalReload": "not_run",
            }
        ),
        **carried,
        "openGates": open_gates,
        "evidenceRuns": evidence_runs,
        "repoCommitSha": repo_commit_sha,
        # The pin PR1 moved the source to -- see the comment at `pin_version`.
        "libraryReleaseVersion": pin_version,
    }

    # Every read-only check above passed -- write the artifact, THEN the
    # contract it registers on (deliberately the opposite order from
    # `prepare`'s pin-then-contract-then-artifact: if the process dies
    # between these two writes, the contract should never end up pointing at
    # an EXECUTION_EVIDENCE file that does not exist on disk yet).
    atomic_write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", artifact_path)
    atomic_write_text(new_contract_text, contract_path)
    _regenerate_contract_json(root)

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
