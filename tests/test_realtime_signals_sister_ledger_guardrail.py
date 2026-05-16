"""Guardrail for the ``open_prep/realtime_signals.py`` sister-ledger hotspot.

Why this exists
===============

Recent CI failures showed a recurring drift pattern: when nearby edits move the
``subprocess.run(...)`` / ``subprocess.Popen(...)`` call sites in
``open_prep/realtime_signals.py``, the matching ``# noqa: S603`` suppressions in
``tests/test_noqa_budget.py`` drift at the same time.

The individual ledgers already pin the exact line numbers. This test deliberately
*does not* re-pin those lines a third time. Instead, it guards the coupling so a
one-sided rebaseline fails loudly with hotspot-specific context.
"""

from __future__ import annotations

from tests.test_noqa_budget import _FROZEN_SITES
from tests.test_subprocess_spawn_sites_ledger import (
    SUBPROCESS_POPEN_LEDGER,
    SUBPROCESS_RUN_LEDGER,
)

_REALTIME_SIGNALS = "open_prep/realtime_signals.py"
_S603 = ("S603",)


def _realtime_signals_noqa_s603_lines() -> set[int]:
    return {
        lineno
        for rel, lineno, codes in _FROZEN_SITES
        if rel == _REALTIME_SIGNALS and codes == _S603
    }


def _realtime_signals_subprocess_lines() -> set[int]:
    return {
        lineno
        for rel, lineno in (SUBPROCESS_RUN_LEDGER | SUBPROCESS_POPEN_LEDGER)
        if rel == _REALTIME_SIGNALS
    }


def test_realtime_signals_sister_ledgers_stay_in_lockstep() -> None:
    """Keep the hotspot ledgers coupled without re-pinning absolute coordinates."""
    noqa_lines = _realtime_signals_noqa_s603_lines()
    subprocess_lines = _realtime_signals_subprocess_lines()

    assert subprocess_lines, (
        "realtime_signals subprocess hotspot disappeared from the ledger scan — "
        "verify whether the daemon launch / discovery paths moved or were removed."
    )
    assert noqa_lines == subprocess_lines, (
        "`open_prep/realtime_signals.py` is a sister-ledger hotspot: every "
        "`subprocess.run(...)` / `subprocess.Popen(...)` site pinned in "
        "`tests/test_subprocess_spawn_sites_ledger.py` must have a matching "
        "`# noqa: S603` entry in `tests/test_noqa_budget.py`, and vice versa. "
        "Update both ledgers together when the file shifts.\n"
        f"noqa_lines = {sorted(noqa_lines)}\n"
        f"subprocess_lines = {sorted(subprocess_lines)}"
    )
