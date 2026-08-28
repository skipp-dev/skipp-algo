"""One wall-clock budget for guard subprocesses, and a self-describing overrun.

Why
---
Three guard files spawn subprocesses under a fixed wall-clock timeout:
``tests/_workflow_step_shell.run_step`` (60 s), ``tests/test_import_safety``
(90 s per module) and ``tests/test_workflow_invoked_scripts_importable``
(60 s per script). The budgets are not tight. Measured on an idle machine
(2026-08-29):

===============================================================  ======  ======
Test                                                             actual  budget
===============================================================  ======  ======
test_refresh_hold_survives_a_checkout_that_predates_the_script    2.4 s    60 s
test_r10_module_imports_in_hostile_env[open_prep.streamlit_...]   1.5 s    90 s
test_r10_module_imports_in_hostile_env[open_prep.databento_...]   0.5 s    90 s
===============================================================  ======  ======

That is 25x to 167x of headroom, so an overrun does not mean "slightly too
slow" — it means the process made 25x to 167x less progress than it does
unloaded. The suite reaches that state on its own: ``test_import_safety``
alone spawns **89** full interpreters, one per production module, and they
compete with the other ~4240 tests under ``-n 4``. Measured under that load,
one such import took 16.7 s wall for 1.13 s user + 0.64 s sys — fifteen
seconds of waiting for 1.8 s of work. (A repeat run against the now-warm
``HOME`` was slower still, at 22.4 s, which rules out a cold cache.)

The defect this module fixes is therefore NOT the budget. It is that an
overrun surfaces as a bare ``subprocess.TimeoutExpired`` traceback, or as a
message blaming the thing under test ("did not terminate within 60 seconds"),
which is indistinguishable from a real hang. On 2026-08-29 four consecutive
pre-push guard runs each failed a *different* pair drawn from these three
files, and each pair passed in isolation; the first investigation cost a full
round of "is my own diff to blame?" before the pattern was visible. For a
guard whose whole product is trust, a failure that cannot explain its own
class is a real defect: it charges every future reader the same investigation.

What this module deliberately does NOT do
-----------------------------------------
* It does not raise the budgets. A larger budget hides a genuine hang, which
  is the failure these timeouts exist to catch.
* It does not retry. A retry inside a guard converts a reproducible failure
  into an intermittent one and hides exactly what should be seen.
* It does not exempt the three files from the guard run.

It makes the overrun say what it is, and lets a slow machine raise the budget
through the environment instead of an edit.
"""

from __future__ import annotations

import os
import subprocess

BUDGET_ENV = "SKIPP_GUARD_SUBPROCESS_BUDGET_S"
"""Override the wall-clock budget, e.g. on a loaded developer machine.

CI leaves it unset and keeps the strict per-call-site default. The value is a
number of seconds; anything unparseable or below :data:`MINIMUM_BUDGET_S` is
refused rather than silently ignored, so a typo cannot quietly disable the
timeout that catches a hang.
"""

MINIMUM_BUDGET_S = 5.0


def budget_seconds(default: float) -> float:
    """Return the wall-clock budget for one guard subprocess."""
    raw = os.getenv(BUDGET_ENV, "").strip()
    if not raw:
        return float(default)
    try:
        value = float(raw)
    except ValueError as exc:
        raise AssertionError(
            f"{BUDGET_ENV}={raw!r} is not a number of seconds"
        ) from exc
    if value < MINIMUM_BUDGET_S:
        raise AssertionError(
            f"{BUDGET_ENV}={raw!r} is below the {MINIMUM_BUDGET_S}s floor; a budget "
            "that small turns every run into a timeout and stops catching hangs"
        )
    return value


def overrun_message(what: str, budget: float, *, detail: str = "") -> str:
    """The shared diagnosis for a wall-clock overrun.

    Names the class of failure first, because the reader's next question is
    always "is it my change?" and the answer is nearly always no.
    """
    lines = [
        f"WALL-CLOCK BUDGET EXCEEDED ({budget:g}s) while running: {what}",
        "",
        "This is a budget/scheduling symptom, not necessarily a defect in the",
        "thing under test. These budgets carry 25x-167x headroom when the",
        "machine is idle, so an overrun usually means the process was starved",
        "-- the guard suite spawns ~89 interpreters of its own under `-n 4`.",
        "",
        "Confirm before you investigate the code:",
        "  1. re-run THIS test alone; if it passes, it was load, not the code",
        f"  2. on a slow machine, raise the budget: {BUDGET_ENV}=180",
        "  3. if it still times out alone, it IS a hang -- that is what this",
        "     timeout exists to catch, and it needs a real fix, not a bigger",
        "     budget",
    ]
    if detail:
        lines += ["", detail]
    return "\n".join(lines)


def run_within_budget(
    command: list[str],
    *,
    what: str,
    default_budget_s: float,
    **kwargs: object,
) -> subprocess.CompletedProcess:
    """``subprocess.run`` whose timeout explains itself instead of exploding."""
    budget = budget_seconds(default_budget_s)
    try:
        return subprocess.run(command, timeout=budget, **kwargs)  # type: ignore[arg-type]
    except subprocess.TimeoutExpired as exc:
        captured = []
        for stream_name in ("stdout", "stderr"):
            raw = getattr(exc, stream_name, None)
            if raw:
                text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
                captured.append(f"--- {stream_name} before the kill ---\n{text}")
        raise AssertionError(
            overrun_message(what, budget, detail="\n".join(captured))
        ) from None
