"""The TypeScript vacuity guard must run on the lane that gates merges.

What this closes
----------------
``scripts/detect_vacuous_claims.py`` — the Python half — has gated merges
since #4355, because the tests that run it sit in ``fast-gates``. The
TypeScript half (``scripts/detect_vacuous_claims_ts.ts``, exercised by
``automation/tradingview/tests/vacuous_claims_ts.test.ts``) shipped with
#4356 and #4381 and gated **nothing**: it ran only in
``tv-onboarding-packages.yml``, which is not a required check.
``fast-gates`` is the only required check by design (ADR-0011), so that
workflow can go red and a merge still lands.

The shape of that is worth naming. A guard whose whole purpose is to find
checks that report green without observing anything was itself running
without anyone observing it. It could have been broken since the day it
shipped and nothing would have said so.

Why these assertions and not a source-text match
------------------------------------------------
Three separate things have to hold, and each of them failed somewhere in
this repository on 2026-08-04:

1. **The step exists in the required workflow.** Anything less gates
   nothing.
2. **Its condition is not narrower than the lane's own.** Being listed in
   ``fast-gates`` is not the same as running: the "Run pin / ledger drift
   guard" step is itself gated ``if: run_heavy == 'true'``, so a file being
   registered in that step, in :mod:`tests._fast_inventory` and in the
   silent-skip coverage test puts it INTO the step without making the step
   run. That misreading was written into a workflow comment and repeated in
   review before anyone measured it.
3. **The file it names actually exists.** #4383 moved a test harness, #4385
   merged a reference to its old location, and ``main`` went red on an
   ImportError. A workflow naming a path is a hand-typed reference to a
   moving target, exactly like the pytest node ID the refresh workflow
   prints.

``run_heavy`` is the right gate rather than an unconditional step, and that
is measured rather than assumed: the data-only exemption in the gate is
``artifacts/*|docs/*|reports/*|pine/generated/*|*.pine``, so any PR touching
a ``.ts`` file forces heavy. :func:`test_the_gate_cannot_exempt_typescript`
pins that, because the guard's coverage is only as good as that arm.

Registration
------------
On the required path unconditionally — the run-step file list in
``smc-fast-pr-gates.yml``, ``tests/_fast_inventory.py``, and
``tests/test_fast_gates_silent_skip_coverage.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FAST_GATES = ROOT / ".github" / "workflows" / "smc-fast-pr-gates.yml"
GUARD_STEP = "Guard against vacuous TypeScript claims"
GATE_CONDITION = "steps.gate.outputs.run_heavy == 'true'"


def _fast_gates_steps() -> list[dict]:
    doc = yaml.safe_load(FAST_GATES.read_text(encoding="utf-8"))
    return [s for s in doc["jobs"]["fast-gates"]["steps"] if isinstance(s, dict)]


def _guard_step() -> dict:
    for step in _fast_gates_steps():
        if step.get("name") == GUARD_STEP:
            return step
    raise AssertionError(
        f"{FAST_GATES.name}: no step named {GUARD_STEP!r} in job 'fast-gates'. "
        "The TypeScript vacuity analyzer then gates nothing again — it would "
        "run only in tv-onboarding-packages.yml, which is not a required "
        "check, so it can go red while merges keep landing."
    )


def test_the_typescript_vacuity_guard_runs_in_fast_gates() -> None:
    """It is in the only required check, and it runs the real analyzer."""
    run = str(_guard_step().get("run", ""))
    assert "vacuous_claims_ts.test.ts" in run, (
        f"the {GUARD_STEP!r} step no longer runs the TypeScript vacuity test:\n{run}"
    )


def test_the_guard_step_is_not_gated_more_narrowly_than_the_lane() -> None:
    """Registered is not the same as run.

    A condition narrower than the lane's own would leave the guard listed and
    silent — the failure mode that made a workflow comment claim a floor was
    pinned "on every pull request" while its step was `run_heavy`-gated.
    """
    condition = str(_guard_step().get("if", "")).strip()
    assert condition == GATE_CONDITION, (
        f"the {GUARD_STEP!r} step is gated on {condition!r}, not on the lane's "
        f"own {GATE_CONDITION!r}. Anything narrower silently reduces coverage; "
        "anything wider runs Node on PRs that cannot contain TypeScript."
    )


def test_the_test_file_the_workflow_names_actually_exists() -> None:
    """A hand-typed path is a reference to a moving target.

    #4383 moved a harness, #4385 merged a reference to its old location, and
    `main` went red. `npx tsx --test <missing path>` does not fail the same
    way in every Node version, so assert the file rather than trust it.
    """
    run = str(_guard_step().get("run", ""))
    named = re.findall(r"automation/[\w/.-]+\.test\.ts", run)
    assert named, f"the guard step names no TypeScript test file:\n{run}"
    for rel in named:
        assert (ROOT / rel).is_file(), (
            f"{FAST_GATES.name} runs {rel!r}, which does not exist. The step "
            "would pass or fail on Node's argument handling rather than on the "
            "analyzer's verdict."
        )


def test_node_is_available_to_the_guard_step() -> None:
    """`npx tsx` needs both a Node toolchain and the installed devDependency.

    Without either, the step fails for a reason that has nothing to do with
    vacuous claims — and a guard that always fails gets disabled, which is the
    same end state as a guard that never runs.
    """
    steps = _fast_gates_steps()
    names = [str(s.get("name", "")) for s in steps]
    guard_at = names.index(GUARD_STEP)

    earlier = steps[:guard_at]
    assert any("actions/setup-node" in str(s.get("uses", "")) for s in earlier), (
        "no setup-node step runs before the TypeScript vacuity guard"
    )
    assert any("npm ci" in str(s.get("run", "")) for s in earlier), (
        "nothing installs the Node dependencies before the guard runs; `npx "
        "tsx` would resolve tsx from the network or not at all"
    )


def test_the_gate_cannot_exempt_typescript() -> None:
    """`run_heavy` only covers this guard while .ts forces heavy.

    The guard's gate is sufficient BECAUSE the data-only exemption cannot
    match a TypeScript file. If a future edit adds `*.ts` (or a directory
    containing them) to that arm, this guard would stop running on exactly the
    PRs it exists for, with no other test noticing.
    """
    text = FAST_GATES.read_text(encoding="utf-8")
    arm = re.search(
        r"^\s*(artifacts/\*\|[^)]*)\)\s*;;\s*$",
        text,
        re.M,
    )
    assert arm, (
        "the data-only exemption arm could not be located in the gate step; "
        "this test can no longer tell whether TypeScript forces heavy gates"
    )
    patterns = arm.group(1).split("|")
    offending = [
        p
        for p in patterns
        if p.endswith(".ts")
        or (p.endswith("*") and p.rstrip("*").rstrip("/") in {"automation", "scripts"})
    ]
    assert not offending, (
        f"the data-only exemption now matches TypeScript paths {offending}. A "
        "PR changing only those would skip heavy gates, and with them the "
        "TypeScript vacuity guard — on precisely the PRs it exists to check."
    )
