"""What ``smc-export-cron-watchdog.yml``'s decide step decides, executed.

References the workflow stem ``smc-export-cron-watchdog`` so the
orphan-workflow inventory stays closed.

``decide`` publishes ``decision``, and the dispatch step hangs on it. The
workflow exists to fire a backstop dispatch of the sharded Databento producer
when its cron did not, so both directions cost real money: a decision stuck on
``skip`` silently drops the backstop, and one stuck on ``dispatch`` pays for a
duplicate export on every tick.

Measured 2026-08-04 with a value-preserving arm swap (``decision``
dispatch <-> skip, the token multiset left unchanged so any substring assertion
is blind by construction): all 21 assertions across the 2 files that name this
workflow stayed green.

The clock is supplied rather than observed. ``date -u -d`` is a GNU extension
that BSD rejects, and the step already carries a ``python3`` fallback for
exactly that -- the stub below lets ``-d`` fail on purpose so the fallback is
what computes the slot epoch, which is what happens on any non-GNU host and
what no test had ever exercised.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

from tests._workflow_step_shell import Stub, run_step

WORKFLOW = "smc-export-cron-watchdog.yml"
DECIDE_STEP = "Determine current slot and decide"

# Mirrors the workflow-level `env:` block, and nothing more. A variable the
# workflow adds and this dict does not expands to "" under `-u` and would abort
# the step -- loudly, which is the point of keeping the two in step.
WORKFLOW_ENV = {
    "TARGET_WORKFLOW": "smc-databento-production-export-sharded.yml",
    "TARGET_REPO": "skipp-dev/skipp-algo",
    "SLOT_HOURS": "12 16",
    "WATCHDOG_THRESHOLD_MIN": "45",
    "WATCHDOG_WINDOW_MAX_MIN": "90",
}

_WEEKDAY = dt.datetime(2026, 8, 4, tzinfo=dt.UTC)  # a Tuesday
_WEEKEND = dt.datetime(2026, 8, 8, tzinfo=dt.UTC)  # a Saturday


def _clock(day: dt.datetime, *, minutes_after_noon_slot: int) -> Stub:
    """`date` answering only what this step asks, with `-d` deliberately absent.

    Longest format first: `+%Y-%m-%dT%H:%M:%SZ` starts with `+%Y-%m-%d`, so the
    other order would answer the timestamp query with a bare date and the slot
    arithmetic would silently drift.
    """
    now = day.replace(hour=12) + dt.timedelta(minutes=minutes_after_noon_slot)
    return Stub(script=f'''
case "$*" in
  *-d*)                    exit 1 ;;
  *"+%Y-%m-%dT%H:%M:%SZ"*) printf '%s\\n' "{now.strftime('%Y-%m-%dT%H:%M:%SZ')}" ;;
  *"+%Y-%m-%d"*)           printf '%s\\n' "{day.strftime('%Y-%m-%d')}" ;;
  *"+%s"*)                 printf '%s\\n' "{int(now.timestamp())}" ;;
  *"+%u"*)                 printf '%s\\n' "{day.isoweekday()}" ;;
  *) exit 1 ;;
esac
''')


def _decide(
    tmp_path: Path,
    *,
    day: dt.datetime = _WEEKDAY,
    minutes_after_noon_slot: int = 60,
    runs_in_slot: int = 0,
    force_dispatch: str = "false",
):
    # Several tests below run the step more than once against sibling paths so
    # each invocation gets its own stub dir and output file; the harness works
    # inside the directory it is handed rather than creating it.
    tmp_path.mkdir(parents=True, exist_ok=True)
    return run_step(
        WORKFLOW, DECIDE_STEP, tmp_path,
        env={**WORKFLOW_ENV, "FORCE_DISPATCH": force_dispatch, "GH_TOKEN": "stub-token"},
        stubs={
            "date": _clock(day, minutes_after_noon_slot=minutes_after_noon_slot),
            "gh": Stub(stdout=str(runs_in_slot)),
            "python3": Stub(passthrough=sys.executable),
        },
    )


def test_a_missed_slot_dispatches_the_backstop(tmp_path: Path) -> None:
    """The reason the workflow exists: the cron did not fire, so we do."""
    result = _decide(tmp_path, minutes_after_noon_slot=60, runs_in_slot=0)
    assert result.returncode == 0, result.stderr
    assert result.outputs["decision"] == "dispatch", (
        f"a slot with no run and past the grace period must dispatch; got {result.outputs}"
    )
    assert result.outputs["elapsed_min"] == "60"


def test_a_slot_that_already_ran_is_not_dispatched_again(tmp_path: Path) -> None:
    """The race guard. Without it every tick pays for a duplicate export."""
    result = _decide(tmp_path, minutes_after_noon_slot=60, runs_in_slot=1)
    assert result.outputs["decision"] == "skip"
    assert result.outputs["runs_in_slot"] == "1"


def test_the_grace_period_is_respected(tmp_path: Path) -> None:
    """Below the threshold the cron may still be on its way."""
    result = _decide(tmp_path, minutes_after_noon_slot=30)
    assert result.outputs["decision"] == "skip", (
        f"30 min is inside the 45 min grace period; got {result.outputs}"
    )


def test_the_window_closes(tmp_path: Path) -> None:
    """Past the window a dispatch would land in the next slot's territory."""
    result = _decide(tmp_path, minutes_after_noon_slot=120)
    assert result.outputs["decision"] == "skip", (
        f"120 min is past the 90 min window; got {result.outputs}"
    )


def test_both_edges_of_the_window_are_where_they_claim_to_be(tmp_path: Path) -> None:
    """45 and 90 are inclusive bounds; 44 and 91 are outside.

    Asserting one side only leaves a window off by one indistinguishable from a
    correct one, and the whole decision is a comparison against these two.
    """
    assert _decide(tmp_path / "a", minutes_after_noon_slot=44).outputs["decision"] == "skip"
    assert _decide(tmp_path / "b", minutes_after_noon_slot=45).outputs["decision"] == "dispatch"
    assert _decide(tmp_path / "c", minutes_after_noon_slot=90).outputs["decision"] == "dispatch"
    assert _decide(tmp_path / "d", minutes_after_noon_slot=91).outputs["decision"] == "skip"


def test_the_weekend_gate_holds_and_can_be_bypassed(tmp_path: Path) -> None:
    """Mon-Fri only, unless an operator asks for the end-to-end drill.

    Both directions: a weekend gate that never opens makes the documented
    bypass a dead input, and one that never closes pays for weekend exports.
    """
    gated = _decide(tmp_path / "gated", day=_WEEKEND, minutes_after_noon_slot=60)
    assert gated.outputs["decision"] == "skip"

    forced = _decide(
        tmp_path / "forced", day=_WEEKEND, minutes_after_noon_slot=60, force_dispatch="true"
    )
    assert forced.outputs["decision"] == "dispatch", (
        f"force_dispatch must exercise the dispatch path on a weekend; got {forced.outputs}"
    )


def test_a_forced_dispatch_overrides_the_race_guard(tmp_path: Path) -> None:
    """Otherwise the drill would no-op against whatever the cron just did."""
    result = _decide(tmp_path, minutes_after_noon_slot=60, runs_in_slot=2,
                     force_dispatch="true")
    assert result.outputs["decision"] == "dispatch"


def test_an_unparseable_force_dispatch_fails_before_anything_runs(tmp_path: Path) -> None:
    result = _decide(tmp_path, force_dispatch="yes-please")
    assert result.returncode != 0, "an invalid force_dispatch must fail the step"
    assert not result.outputs, f"nothing may be published before validation: {result.outputs}"


def test_the_slot_epoch_survives_without_gnu_date(tmp_path: Path) -> None:
    """The python3 fallback is the only path on a non-GNU host.

    `date -u -d` fails in every case above by construction, so each of them
    already exercises it -- this names the property so a removal of the fallback
    fails as itself rather than as a mysterious wrong slot.
    """
    result = _decide(tmp_path, minutes_after_noon_slot=60)
    assert result.outputs["active_slot"].endswith("T12:00:00Z"), (
        f"the slot epoch was not resolved without GNU date; got {result.outputs}"
    )
