"""Contract pins for the open-prep diff-base persistence (F3, 2026-08-18).

``artifacts/open_prep/last_result.json`` is gitignored and the CI checkout
cleans ignored files, so the diff base could never survive between daily
runs: every run was ``first_run=true``, ``compute_diff(None, ...)`` marked
EVERY candidate a new entrant, and the realtime 🆕 column was permanently
lit for all symbols (proven on the published bot/live-open-prep-snapshot:
``diff.first_run: true`` with the full candidate list, daily). These pins
keep both halves of the transport edge alive:

  restore  bot/live-open-prep-snapshot -> working tree, BEFORE the run
  publish  working tree -> bot/live-open-prep-snapshot, after the run
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "run-open-prep-daily.yml"
LAST_RESULT = "artifacts/open_prep/last_result.json"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_the_daily_run_restores_the_diff_base_before_running() -> None:
    text = _text()
    restore_marker = f"origin/bot/live-open-prep-snapshot:{LAST_RESULT}"
    assert restore_marker in text, "diff base is never restored from the bot branch"
    # The restore must happen BEFORE open_prep runs, or the run diffs
    # against nothing and the treadmill returns.
    assert text.index(restore_marker) < text.index("-m open_prep.run_open_prep")


def test_the_daily_run_publishes_the_diff_base_for_the_next_run() -> None:
    text = _text()
    assert f'LAST_RESULT="{LAST_RESULT}"' in text
    assert '--copy-if-present "${LAST_RESULT}=${LAST_RESULT}"' in text, (
        "diff base is not published to the bot branch — the restore above "
        "would find nothing and every run stays first_run=true"
    )
