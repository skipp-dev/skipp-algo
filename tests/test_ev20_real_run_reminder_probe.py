"""What ``ev20-real-run-reminder.yml``'s probe decides, executed.

References the workflow stem ``ev20-real-run-reminder`` so the orphan-workflow
inventory stays closed.

``probe`` publishes ``due`` plus the suggested out-of-sample window; the
issue-opening step hangs on ``due``. Measured 2026-08-04 with a
value-preserving arm swap (``DUE`` false <-> true, the token multiset left
unchanged so any substring assertion is blind by construction): all 10
assertions in the one file that names this workflow stayed green -- while a
reminder stuck on ``false`` never fires again and one stuck on ``true`` opens
an issue every month regardless of coverage.

The clock is supplied. ``date -u -d`` is a GNU extension BSD rejects, and
unlike the export watchdog this step has no fallback -- the shim below gives it
GNU semantics locally so the test measures the workflow rather than the
developer's coreutils. That is not a claim about the workflow: CI runs Ubuntu
and has the real thing.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

from tests._workflow_step_shell import Stub, run_step

WORKFLOW = "ev20-real-run-reminder.yml"
PROBE_STEP = "Check last real run and compute suggested window"

_NOW = dt.datetime(2026, 8, 4, 12, 0, tzinfo=dt.UTC)

# GNU `date` as this step uses it: `-d <iso>`, `-d "<date> -3 months"`, and the
# plain `+FORMAT` reads. Implemented against a fixed clock so the window
# arithmetic is deterministic; month subtraction is spelled out rather than
# pulled from a library because that is the whole behaviour under test.
_GNU_DATE = '''
exec "$REAL_PYTHON" -c '
import datetime as dt, sys, re
NOW = dt.datetime.fromisoformat(sys.argv[1])
args = sys.argv[2:]
spec, fmt = None, "%a %b %e %H:%M:%S %Z %Y"
i = 0
while i < len(args):
    a = args[i]
    if a == "-u":
        pass
    elif a == "-d":
        i += 1; spec = args[i]
    elif a.startswith("+"):
        fmt = a[1:]
    i += 1
when = NOW
if spec is not None:
    m = re.match(r"^(\\S+)(?:\\s+([-+]\\d+)\\s+months?)?$", spec.strip())
    if not m:
        sys.exit(1)
    base = m.group(1)
    try:
        when = dt.datetime.fromisoformat(base.replace("Z", "+00:00"))
    except ValueError:
        sys.exit(1)
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.UTC)
    if m.group(2):
        months = int(m.group(2))
        total = (when.year * 12 + when.month - 1) + months
        when = when.replace(year=total // 12, month=total % 12 + 1)
if fmt == "%s":
    print(int(when.timestamp()))
else:
    print(when.strftime(fmt))
' "$FAKE_NOW" "$@"
'''


def _probe(
    tmp_path: Path,
    *,
    last_success: str | None,
    skip_within_days: int = 30,
):
    """Run the real step with `gh` and the clock supplied."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    return run_step(
        WORKFLOW, PROBE_STEP, tmp_path,
        env={
            "REAL_PYTHON": sys.executable,
            "FAKE_NOW": _NOW.isoformat(),
            "GH_REPO": "skipp-dev/skipp-algo",
            "GH_TOKEN": "stub-token",
            "SKIP_IF_SUCCESS_WITHIN_DAYS": str(skip_within_days),
        },
        stubs={
            "gh": Stub(stdout=last_success or ""),
            "date": Stub(script=_GNU_DATE),
        },
    )


def _days_ago(days: int) -> str:
    return (_NOW - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_a_pipeline_that_never_succeeded_is_due(tmp_path: Path) -> None:
    """No successful run at all is the strongest case for a reminder."""
    result = _probe(tmp_path, last_success=None)
    assert result.returncode == 0, result.stderr
    assert result.outputs["due"] == "true"
    assert result.outputs["last_success"] == "none"
    assert result.outputs["age_days"] == "n/a"


def test_recent_coverage_suppresses_the_reminder(tmp_path: Path) -> None:
    result = _probe(tmp_path, last_success=_days_ago(10), skip_within_days=30)
    assert result.outputs["due"] == "false", (
        f"a 10-day-old success is inside the 30-day window; got {result.outputs}"
    )
    assert result.outputs["age_days"] == "10"


def test_stale_coverage_makes_it_due_again(tmp_path: Path) -> None:
    """The control direction: without it, `due=false` could be a constant."""
    result = _probe(tmp_path, last_success=_days_ago(45), skip_within_days=30)
    assert result.outputs["due"] == "true"
    assert result.outputs["age_days"] == "45"


def test_the_threshold_is_inclusive_on_both_sides(tmp_path: Path) -> None:
    """30 still counts as covered, 31 does not.

    The whole decision is one comparison; asserting one side leaves an off-by-one
    indistinguishable from a correct bound.
    """
    assert _probe(tmp_path / "a", last_success=_days_ago(30)).outputs["due"] == "false"
    assert _probe(tmp_path / "b", last_success=_days_ago(31)).outputs["due"] == "true"


def test_only_a_successful_run_counts_as_coverage(tmp_path: Path) -> None:
    """The point is a fresh archived verdict, not a fresh attempt.

    Asserted off the recorded invocation: the status filter has to survive line
    continuations and quoting and actually reach the command line.
    """
    call = _probe(tmp_path, last_success=_days_ago(10)).called_with("run list")
    assert call, "the probe never asked for the last run"
    assert "--status success" in call[0], (
        f"failed attempts must not count as coverage; asked: {call[0]}"
    )
    assert "edge-pipeline-real-run.yml" in call[0]


def test_the_window_is_the_three_months_before_this_one(tmp_path: Path) -> None:
    """Each monthly run adds exactly one fresh month.

    The window is [first of the month three months back, first of this month),
    so windows are never re-tested wholesale. With the clock at 2026-08-04 that
    is 2026-05-01 -> 2026-08-01.
    """
    result = _probe(tmp_path, last_success=None)
    assert result.outputs["window_end"] == "2026-08-01"
    assert result.outputs["window_start"] == "2026-05-01", (
        f"the suggested window drifted; got {result.outputs}"
    )


def test_the_operator_summary_carries_the_verdict(tmp_path: Path) -> None:
    """The reminder is read on the run page, not in the outputs."""
    result = _probe(tmp_path, last_success=_days_ago(45))
    assert "reminder due: `true`" in result.summary, result.summary
    assert "2026-05-01" in result.summary and "2026-08-01" in result.summary
