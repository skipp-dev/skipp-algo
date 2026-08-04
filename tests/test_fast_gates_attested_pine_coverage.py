"""Every R1-attested source must raise fast-gates' ``run_pine_guard`` flag.

Regression this prevents
------------------------
``scripts/smc_r1_rollout_contract.py`` hashes its targets into the rollout
contract, and
``tests/test_check_tv_unattested_sources.py::test_the_guard_reads_the_registered_evidence_not_a_second_copy``
asserts those hashes equal the registered evidence artifact. So a change to any
attested target has a real, CI-visible consequence: it un-attests the rollout.

``.github/workflows/smc-fast-pr-gates.yml`` decides per changed path whether a
``bot/*`` pull request runs anything beyond the cheap lane. Its data-only
exemption covered ``*.pine`` outright, which skipped the **checkout**, which
skipped ``Guard R1-attested sources`` with it — so the one producer the guard
was built to stop was the one it could not see:

* **#4284** (refresh 2026-08-01 02:55Z) drifted the attestation; repaired four
  hours later by the manual re-attestation PR #4290.
* **#4371** (refresh 2026-08-04 02:16Z) drifted it again. ``fast-gates`` passed
  in **7 seconds**, the PR merged green, and ``origin/main`` was left red on
  that test for the next unrelated pull request. Nobody noticed.

#4376 closed that hole with a ``run_pine_guard`` output: a pine touch pulls in
the checkout plus the guard step, and nothing else — pine stays off the heavy
suite. #4377 then made those tests execute the gate rather than read it.

Why this file still exists on top of #4376/#4377
------------------------------------------------
Their trigger is PATH-shaped::

    *.pine|pine/generated/*) pine=true ;;

The attested roster is not. It is whatever ``build_rollout_contract()``
returns, and nothing constrains those paths to those two globs. An attested
target registered under ``artifacts/``, ``docs/``, ``reports/`` or any other
prefix would sail past the arm above **and** match the data-only exemption
below — invisible to the R1 guard in exactly the shape #4371 was invisible,
with a green suite over it. ``tests/test_check_r1_attested_sources.py`` pins
that the mechanism works for the paths it is handed; this file pins that the
mechanism is handed every path that matters.

That precise failure — a hand-maintained list going stale against a derived
one — cost this repository 12 consecutive failed ``smc-library-refresh`` runs
on 2026-08-03 (#4333), and ``tests/test_credential_probe_consumers.py`` was
written to stop it. This guard follows that pattern: the roster comes from the
contract, and the gate is asked about each entry.

The gate is EXECUTED, not read (#4377)
--------------------------------------
Source text cannot tell "raises the flag for this path" apart from "publishes
``run_pine_guard=false`` forever". :func:`run_gate` — imported from
``tests/test_check_r1_attested_sources.py`` rather than copied, so there is one
harness and a rename fails loudly instead of drifting — lifts the gate step's
own shell out of the workflow YAML, stubs ``gh`` to emit a chosen file list,
and reads the resulting ``GITHUB_OUTPUT``.

The roster is derived UNFILTERED (see :func:`_attested_source_paths`) and the
non-vacuity floor is imported from the contract rather than re-typed (see
:data:`scripts.smc_r1_rollout_contract.MIN_ATTESTED_SOURCES`). The refresh
workflow's notice step derives the same roster against the same floor; a second
local copy of either would be the very duplication this file guards against.

Registration
------------
Like ``tests/test_credential_probe_consumers.py``, this file sits on the
required path unconditionally (the "Run pin / ledger drift guard" step in
``smc-fast-pr-gates.yml`` — ``fast-gates`` is the only required check,
ADR-0011), mirrored in ``tests/test_fast_gates_silent_skip_coverage.py`` and
``tests/_fast_inventory.py``. The diff-driven "Run every guard that reads a
workflow this PR changed" step is not sufficient on its own: adding a target to
``scripts/smc_r1_rollout_contract.py`` touches no workflow file, so that
selection would pick nothing — which is the same blind spot this test closes.
"""

from __future__ import annotations

from pathlib import Path

from scripts.smc_r1_rollout_contract import (
    MIN_ATTESTED_SOURCES,
    ROOT,
    build_rollout_contract,
)
from tests._fast_gates_gate import run_gate

FAST_GATES_WORKFLOW = ROOT / ".github" / "workflows" / "smc-fast-pr-gates.yml"

# A path that is neither attested nor pine-shaped. Used as the negative
# direction: without it, a gate hardcoding run_pine_guard=true would satisfy
# every assertion below while running the checkout on every bot PR.
NON_PINE_DATA_PATH = "artifacts/governance/some_measurement.json"


def _attested_source_paths() -> list[str]:
    """Repository-relative path of EVERY source the contract attests.

    DERIVED from ``scripts/smc_r1_rollout_contract.py`` on purpose — see the
    module docstring. ``build_rollout_contract()`` is the same function
    ``scripts/check_tv_unattested_sources.py`` reads, so the roster this test
    enforces and the roster the attestation guard checks cannot disagree.

    Deliberately UNFILTERED — no ``.endswith(".pine")``. Every target is hashed
    into the contract, so every target un-attests the rollout when it changes,
    whatever its extension. Filtering to ``*.pine`` would be fail-open in
    exactly the shape this file closes: it would drop precisely the targets the
    path-shaped ``*.pine|pine/generated/*`` arm cannot see, which is the only
    case where this guard has anything left to say. The refresh workflow's
    notice step derives the roster unfiltered for the same reason; the two must
    not diverge.
    """
    return sorted({str(target["path"]) for target in build_rollout_contract()["targets"]})


def test_the_attested_roster_is_real_before_anything_is_asserted_about_it() -> None:
    """Witness: this guard reads a real roster of files that really exist."""
    attested = _attested_source_paths()
    assert attested, (
        "derived NO attested source from scripts/smc_r1_rollout_contract.py. "
        "Every loop in this file iterates that roster, so an empty one makes this "
        "whole guard report green while observing nothing — fix "
        "_attested_source_paths rather than accepting the pass."
    )
    assert len(attested) >= MIN_ATTESTED_SOURCES, (
        f"derived only {len(attested)} attested source(s) from "
        f"scripts/smc_r1_rollout_contract.py: {attested}. Expected at least "
        f"{MIN_ATTESTED_SOURCES}. Either the derivation broke (then fix "
        "_attested_source_paths — a guard that observes nothing and reports green "
        "is worse than no guard) or a source was genuinely removed from the "
        "contract (then lower MIN_ATTESTED_SOURCES in the same PR, with a "
        "reason)."
    )
    for path in attested:
        assert (ROOT / path).is_file(), (
            f"the rollout contract attests {path!r}, which does not exist. The "
            "contract hashes it, so this cannot be true."
        )


def test_every_attested_source_raises_the_pine_guard_flag(tmp_path: Path) -> None:
    """The core assertion: no attested source may leave the R1 guard skipped.

    Asked one path at a time, because that is the question — "would a bot PR
    touching ONLY this attested source run the guard?" Handing the gate the
    whole roster at once would let a single covered entry carry the uncovered
    ones, which is precisely the drift being guarded against.
    """
    uncovered: list[str] = []
    for path in _attested_source_paths():
        # run_gate builds a `bin/` stub directory under the path it is given,
        # so each invocation needs its own.
        work = tmp_path / path.replace("/", "_")
        work.mkdir(parents=True)
        outputs = run_gate([path], work)
        if outputs.get("run_pine_guard") != "true":
            uncovered.append(path)

    assert not uncovered, (
        f"{uncovered} are hashed into the R1 rollout contract, but a bot/* PR "
        "that changes only them does NOT raise run_pine_guard in the "
        f"'Determine if heavy gates should run' step of {FAST_GATES_WORKFLOW.name}. "
        "Without that flag the Checkout step is skipped, and 'Guard R1-attested "
        "sources' is skipped with it — the #4371 hole, where fast-gates passed "
        "in 7 seconds and left main red on "
        "tests/test_check_tv_unattested_sources.py for the next unrelated PR.\n"
        "Remedy: widen the run_pine_guard case arm so it matches each listed "
        "path. The arm is path-shaped (*.pine|pine/generated/*) while this "
        "roster is derived from scripts/smc_r1_rollout_contract.py, so an "
        "attested target registered outside those globs needs its own pattern — "
        "added ABOVE nothing in particular, since that arm is its own case "
        "block, but the pattern must exist."
    )


def test_a_non_attested_data_path_leaves_the_flag_down(tmp_path: Path) -> None:
    """Control: the coverage above must be a discrimination, not a constant.

    A gate publishing ``run_pine_guard=true`` unconditionally would satisfy
    every attested path while checking out the repository on every data-only
    bot PR. Only both directions pin the behaviour.
    """
    attested = set(_attested_source_paths())
    assert NON_PINE_DATA_PATH not in attested, (
        f"{NON_PINE_DATA_PATH} became an attested target, so it can no longer "
        "serve as the negative direction. Pick another non-attested data path."
    )

    outputs = run_gate([NON_PINE_DATA_PATH], tmp_path)
    assert outputs.get("run_pine_guard") == "false", (
        "a data-only bot PR that touches no attested source still raises "
        "run_pine_guard. The flag is then a constant, and the coverage "
        "assertion above measures nothing."
    )


def test_the_flag_reaches_the_steps_that_make_it_mean_something(tmp_path: Path) -> None:
    """A raised flag that gates nothing is the same skip with extra output.

    #4376's own finding: the guard step was skipped because the CHECKOUT was
    skipped. Both conditions therefore have to honour ``run_pine_guard``, and
    this file asserts it alongside the coverage rather than trusting that the
    roster reaching a flag is the end of the story.
    """
    import yaml

    doc = yaml.safe_load(FAST_GATES_WORKFLOW.read_text(encoding="utf-8"))
    steps = doc["jobs"]["fast-gates"]["steps"]
    conditions = {
        str(step.get("name")): str(step.get("if", ""))
        for step in steps
        if isinstance(step, dict)
    }

    for name in ("Checkout", "Guard R1-attested sources"):
        assert name in conditions, (
            f"{FAST_GATES_WORKFLOW.name} has no step named {name!r} in job "
            "'fast-gates'. Either it was renamed (update this test in the same "
            "PR) or the R1 guard path was removed — in which case the roster "
            "coverage above is about a flag nobody reads."
        )
        assert "run_pine_guard" in conditions[name], (
            f"the {name!r} step does not consider steps.gate.outputs."
            "run_pine_guard, so a pine-only bot PR raises the flag and is "
            "skipped anyway. That is #4371 verbatim: the guard was skipped "
            "because the checkout was."
        )
