"""F-09 regression: ``--require-progress`` exits 3 on silent no-op.

Audit finding F-09: ``open_prep.outcome_backfill`` would return a
``{"resolved":0,"failed":0,"skipped":0,"dates_processed":0}`` summary on
no-op runs (e.g. when no candidates were due for resolution) and the
scheduled workflow had no assertion that any progress was made — the
job silently went green even when zero outcomes were processed.

The opt-in ``--require-progress`` flag turns that silent no-op into a
loud exit 3. These tests pin the matrix:

    flag set?  any progress?   expected exit
    ─────────  ─────────────   ─────────────
    no         no              0   (legacy behaviour preserved)
    no         yes             0
    yes        no              3   (NEW — the F-09 tripwire)
    yes        yes             0
    (any)      failed > 0      2   (existing loud-failure path)
"""
from __future__ import annotations

from typing import Any

import pytest

from open_prep import outcome_backfill


@pytest.mark.parametrize(
    "flag,summary,expected_exit",
    [
        # Legacy: silent no-op returns 0 when --require-progress is absent.
        ([], {"resolved": 0, "failed": 0, "skipped": 0, "dates_processed": 0}, 0),
        # Legacy: progress without flag → 0.
        ([], {"resolved": 5, "failed": 0, "skipped": 1, "dates_processed": 1}, 0),
        # F-09 NEW: silent no-op WITH flag → 3.
        (
            ["--require-progress"],
            {"resolved": 0, "failed": 0, "skipped": 0, "dates_processed": 0},
            3,
        ),
        # With flag + real progress → 0.
        (
            ["--require-progress"],
            {"resolved": 3, "failed": 0, "skipped": 0, "dates_processed": 1},
            0,
        ),
        # Pre-existing loud-failure path (resolved==0 AND failed>0) → 2,
        # still wins over --require-progress.
        (
            ["--require-progress"],
            {"resolved": 0, "failed": 2, "skipped": 0, "dates_processed": 1},
            2,
        ),
    ],
)
def test_require_progress_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
    flag: list[str],
    summary: dict[str, Any],
    expected_exit: int,
) -> None:
    monkeypatch.setattr(
        outcome_backfill,
        "backfill_outcomes",
        lambda **_kwargs: summary,
    )
    monkeypatch.setattr(
        outcome_backfill,
        "_write_backfill_run_log",
        lambda **_kwargs: None,
    )

    rc = outcome_backfill.main(["--dry-run", *flag])
    assert rc == expected_exit


def test_require_progress_flag_exists_in_parser() -> None:
    """Guard against accidental removal of the F-09 tripwire flag."""
    parser = outcome_backfill.build_parser()
    actions = {a.dest for a in parser._actions}
    assert "require_progress" in actions
