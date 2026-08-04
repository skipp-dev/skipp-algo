"""What ``c13-daily-cron.yml``'s backfill step decides, executed.

References the workflow stem ``c13-daily-cron`` so the orphan-workflow
inventory stays closed.

``backfill`` publishes ``rc``, and six later steps in the daily chain hang on
it. Measured 2026-08-04 with a value-preserving arm swap (``rc`` 0 <-> 78, the
token multiset left unchanged so any substring assertion is blind by
construction): all 121 assertions across the 7 files that name this workflow
stayed green.

Two things only execution can see here:

* ``rc=${PIPESTATUS[0]}`` -- the backfill is piped through ``tee``, so ``$?``
  would report ``tee``'s status, which is always 0. A step that captured the
  wrong one would publish ``rc=0`` for every failed backfill and the advisory
  chain would read a broken day as a clean one.
* the ``--imbalance-index`` argument is soft-skipped via
  ``${VAR:+--flag "$VAR"}``. Whether that expands to nothing or to an empty
  argument is invisible in the source and decides whether the backfill runs at
  all on weekends and pre-rollout days.
"""

from __future__ import annotations

import sys
from pathlib import Path

from tests._workflow_step_shell import Stub, run_step

WORKFLOW = "c13-daily-cron.yml"
BACKFILL_STEP = "Step 1 — backfill live outcomes (advisory)"
DATE = "2026-08-04"
LIVE_DIR = "live"

# The workflow's own contract: no audit file for the day is not a failure, it is
# a documented "nothing to do" code that later steps branch on.
NO_AUDIT_RC = "78"


def _backfill(tmp_path: Path, *, audit: bool, imbalance: bool, script_rc: int = 0):
    live = tmp_path / LIVE_DIR
    live.mkdir(exist_ok=True)
    if audit:
        (live / f"incubation_{DATE}.jsonl").write_text("{}\n", encoding="utf-8")
    if imbalance:
        index = tmp_path / "cache" / "imbalance"
        index.mkdir(parents=True, exist_ok=True)
        (index / f"{DATE}.jsonl").write_text("{}\n", encoding="utf-8")
    return run_step(
        WORKFLOW, BACKFILL_STEP, tmp_path,
        env={"REAL_PYTHON": sys.executable, "LIVE_DIR": LIVE_DIR},
        stubs={"python": Stub(
            script=f'case "$1" in -c) exec "$REAL_PYTHON" "$@" ;; esac\nexit {script_rc}'
        )},
        expressions={"steps.date.outputs.date": DATE},
    )


def test_a_day_without_an_audit_file_reports_the_documented_code() -> None:
    """No audit is a known state with its own code, not a generic failure."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        result = _backfill(Path(tmp), audit=False, imbalance=False)
    assert result.returncode == int(NO_AUDIT_RC)
    assert result.outputs["rc"] == NO_AUDIT_RC
    assert not result.calls, "nothing may run when there is no audit file"


def test_a_missing_imbalance_index_is_soft_skipped(tmp_path: Path) -> None:
    """Absence is expected on weekends and pre-rollout days.

    The backfill must still run -- without the argument, not with an empty one,
    which would make the tool reject its own command line.
    """
    result = _backfill(tmp_path, audit=True, imbalance=False)
    assert result.returncode == 0, result.stderr
    assert result.outputs["rc"] == "0"
    assert result.calls, "the backfill must still run"
    assert "--imbalance-index" not in result.calls[0], (
        f"a missing index must drop the argument entirely; it ran: {result.calls[0]}"
    )


def test_a_present_imbalance_index_is_wired(tmp_path: Path) -> None:
    """The control direction: without it, the soft-skip above is a constant."""
    result = _backfill(tmp_path, audit=True, imbalance=True)
    assert "--imbalance-index" in result.calls[0], result.calls
    assert f"cache/imbalance/{DATE}.jsonl" in result.calls[0], result.calls


def test_the_reported_code_is_the_backfills_own_not_tees(tmp_path: Path) -> None:
    """``rc=${PIPESTATUS[0]}`` is load-bearing.

    The backfill is piped through ``tee``, which succeeds regardless. Capturing
    ``$?`` instead would publish rc=0 for every failed backfill, and the
    advisory chain would read a broken day as a clean one.
    """
    result = _backfill(tmp_path, audit=True, imbalance=True, script_rc=3)
    assert result.outputs["rc"] == "3", (
        f"the step must report the backfill's exit code, not the pipe's; "
        f"got {result.outputs}"
    )
