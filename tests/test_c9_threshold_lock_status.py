"""Tracking-anchor test for the C9 threshold-lock-in milestone.

The C9 sprint plan parks production-threshold tuning until the C8
live-incubation backfill has accrued 90 days of real outcomes. This test
is a no-op until ``LOCK_BY`` so the milestone surfaces in CI rather than
living only in a document. After the date, it asserts
``docs/c9_threshold_tuning.md`` records the lock-in (a real
``Status: locked`` STATUS LINE) so the C9 stack does not silently keep
running on scaffolded thresholds.

The calendar date is only the upper bound: the substantive, event-driven
criterion lives in ``tests/test_c9_threshold_finalisation_anchor.py``,
which fires the moment the C12 trigger flips GREEN while
``CALIBRATION_SOURCE`` still reads ``"synthetic"``.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

import pytest

# Extended three times, honestly each time (the alternative — faking a
# ``Status: locked`` doc — is exactly what this anchor guards against):
#   2026-07-25 → 2026-08-16 (2026-07-25, #4025): C8 backfill short of ≥90d.
#   2026-08-16 → 2026-09-30 (2026-08-25): still short — and the first
#     extension's 3-week guess proved too tight, so this one is sized to the
#     quarter boundary. Discovered during the 2026-08-25 failed-runs triage:
#     the 08-16 deadline had ALREADY passed unnoticed, because the old
#     substring match below was vacuously green (see _status_line_locked).
#   2026-09-30 → 2026-12-31 (2026-10-01, operator direction "31.12."): not
#     short but EMPTY — measured that day with scripts.check_c12_trigger:
#     status BLOCKED, 0 of 4 families live-qualified, every family at
#     live_days 0 / n_trades 0 (calibration report generated 2026-08-28). With
#     MIN_LIVE_DAYS = 90 the gate cannot open before 2026-12-30 even if live
#     incubation starts on the day of this extension, so any earlier date
#     would only schedule a fourth extension. The deadline had passed for a
#     day in a repo whose last human commit was 2026-09-01.
LOCK_BY = _dt.date(2026, 12, 31)
DOC = Path(__file__).resolve().parent.parent / "docs" / "c9_threshold_tuning.md"

# Fenced code blocks are quotations, never the document's own status.
_FENCED_BLOCK = re.compile(r"^[ \t]*```.*?^[ \t]*```", re.MULTILINE | re.DOTALL)

# Line anchor, not substring: the line must BE a status line declaring
# ``locked`` — ``**Status:** locked …``, ``**Status**: locked …`` or
# ``Status: locked …`` at the start of a line (optionally as a list item).
#
# The trailing lookahead is what separates a declaration from a sentence:
# ``locked`` must end the line or be followed by a dash/punctuation, so
# "Status: locked was never recorded here." — prose that merely starts with
# the words — is NOT a lock. That hole was found in code review 2026-08-29,
# after the same class of hole (substring matching the doc's own self-quote)
# had already let the 2026-08-16 deadline pass unnoticed.
#
# Deliberately NOT matched: a blockquoted ``> Status: locked``. In this
# repo's docs a blockquote marks a superseded or quoted note, which is
# exactly the "prose about the status" that must never count as the status.
_LOCKED_STATUS_LINE = re.compile(
    r"^[ \t]{0,3}(?:[-*+][ \t]+)?(?:\*\*)?Status(?:\*\*)?[ \t]*:(?:\*\*)?[ \t]+"
    r"locked\b(?=[ \t]*$|[ \t]*[.,;]|[ \t]+[—–-])",
    re.MULTILINE | re.IGNORECASE,
)


def _status_line_locked(text: str) -> bool:
    """True only if a real status LINE declares ``locked``.

    2026-08-25: the previous check (``"Status: locked" in text``) was
    vacuously green — it matched the self-quote "rather than recording a
    false ``Status: locked``" inside the extension rationale, not the
    status line. Prose ABOUT the status must never count as the status.
    """
    return bool(_LOCKED_STATUS_LINE.search(_FENCED_BLOCK.sub("", text)))


def test_c9_thresholds_locked_after_deadline() -> None:
    today = _dt.date.today()
    if today < LOCK_BY:
        pytest.skip(
            f"C9 threshold lock-in scheduled for {LOCK_BY.isoformat()}; "
            f"today is {today.isoformat()} — tracking only."
        )
    assert DOC.exists(), f"{DOC} missing after lock-in deadline"
    text = DOC.read_text(encoding="utf-8")
    assert _status_line_locked(text), (
        f"{DOC} still records scaffolded thresholds after the "
        f"{LOCK_BY.isoformat()} lock-in deadline. Run "
        "scripts/c9_threshold_replay.py against ≥90d of live outcomes "
        "and update the doc."
    )


def test_prose_mentioning_a_locked_status_is_not_a_lock() -> None:
    # Verbatim the wording that made the old substring check vacuous.
    prose = (
        "**Status:** synthetic-tuned — detectors 3 + 4 are p-value tests\n\n"
        "the deadline was moved rather than recording a false "
        "`Status: locked`).\n"
    )
    assert not _status_line_locked(prose)


def test_a_real_locked_status_line_is_recognised() -> None:
    assert _status_line_locked("# C9\n\n**Status:** locked — tuned against 92d of live outcomes\n")
    assert _status_line_locked("Status: locked\n")


def test_the_current_doc_does_not_already_count_as_locked() -> None:
    # Sharpness probe with the REAL artefact: as long as the doc says
    # synthetic-tuned, the anchor must not read it as locked — otherwise the
    # anchor is vacuous again. Retire this test in the lock-in PR (the same
    # PR that flips the doc's status line and CALIBRATION_SOURCE).
    text = DOC.read_text(encoding="utf-8")
    assert "synthetic-tuned" in text  # premise: doc still in the pre-lock state
    assert not _status_line_locked(text)


def test_prose_that_merely_starts_with_the_words_is_not_a_lock() -> None:
    """Found in code review 2026-08-29 — the line anchor alone was not enough.

    A sentence that BEGINS at the line start with "Status: locked" satisfied
    the first anchored version. That is the same failure class as the
    substring bug it replaced: prose about the status counting as the status.
    """
    assert not _status_line_locked("Status: locked was never recorded here.\n")
    assert not _status_line_locked("**Status:** locked is what we would write if\n")


def test_a_fenced_example_is_not_a_lock() -> None:
    """A code block is a quotation, not the document's own status."""
    assert not _status_line_locked(
        "# C9\n\n**Status:** synthetic-tuned\n\n"
        "Write it like this once the replay is done:\n\n"
        "```markdown\n**Status:** locked — tuned against 92d\n```\n"
    )


def test_the_usual_markdown_spellings_of_a_real_lock_all_count() -> None:
    """The counter-direction: a genuine lock must not be missed on a comma."""
    for zeile in (
        "**Status:** locked — tuned against 92d of live outcomes\n",
        "**Status**: locked — tuned against 92d\n",
        "Status: locked\n",
        "Status: LOCKED\n",
        "- **Status:** locked, replay 2026-09-28\n",
        "**Status:** locked.\n",
    ):
        assert _status_line_locked(f"# C9\n\n{zeile}\n"), zeile
