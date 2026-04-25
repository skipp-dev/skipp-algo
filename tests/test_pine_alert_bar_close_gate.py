"""Defense-pin: every ``alertcondition()`` in root-surface Pine files must be
gated against intra-bar firing (H-1, system review 2026-04-24).

Why
---
Without a bar-close gate, ``alertcondition()`` evaluates on every tick of
the live bar and can fire repeatedly inside the same bar — TradingView
debounces some, but the *intent* of an alert is "this just happened".
Live ticks are also subject to repaint: a condition that flickers true
mid-bar may evaporate by close. The audit (H-1) flagged
``SkippALGO_Confluence.pine`` and ``SMC_Event_Overlay.pine`` for
publishing alerts without an explicit gate while ``SMC_Core_Engine.pine``
already gates each alert inline via ``barstate.isconfirmed``.

Discipline
----------
For every Pine file at the repo root that declares ``alertcondition()``,
each call's first argument must reference at least one of:

  - ``_alertGate``  (the user-toggleable shared gate;
                     pattern: ``_alertGate = barCloseOnly ?
                     barstate.isconfirmed : true``)
  - ``barstate.isconfirmed``
  - ``barstate.islastconfirmedhistory``

Files in ``pine/legacy/`` are out of scope (they have a separate freeze
contract).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

from tests._pine_text import strip_pine_strings_and_line_comments

ROOT = Path(__file__).resolve().parent.parent

_PINE_GENERATED_NAMES = frozenset({"_snippet.pine"})

_ALERTCOND_RE = re.compile(r"\balertcondition\s*\(")

_ACCEPTED_GATE_TOKENS = (
    "_alertGate",
    "barstate.isconfirmed",
    "barstate.islastconfirmedhistory",
)


def _iter_root_pine_files() -> Iterator[Path]:
    """Yield only top-level ``*.pine`` files (excludes pine/, automation/, etc.)."""
    for p in sorted(ROOT.glob("*.pine")):
        if p.name in _PINE_GENERATED_NAMES:
            continue
        yield p


def _alertcondition_call_blocks(src: str) -> list[str]:
    """Return the **first argument** (condition expression) of each
    ``alertcondition(...)`` call, paren-balanced.

    The accepted-token check intentionally inspects the *condition
    only* — a token appearing in the ``title=`` or ``message=`` slots
    must not be allowed to satisfy the gate (Copilot review of
    PR #190). Strings and ``//`` comments are sanitised first so an
    unbalanced ``)`` in a literal does not corrupt depth tracking.
    """
    sanitized = strip_pine_strings_and_line_comments(src)
    blocks: list[str] = []
    for m in _ALERTCOND_RE.finditer(sanitized):
        i = m.end()  # just past the opening "("
        depth = 1
        first_arg_end: int | None = None
        n = len(sanitized)
        while i < n and depth > 0:
            ch = sanitized[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    if first_arg_end is None:
                        first_arg_end = i
                    break
            elif ch == "," and depth == 1 and first_arg_end is None:
                first_arg_end = i
            i += 1
        if depth != 0 or first_arg_end is None:
            # Malformed (unterminated call) — record an empty block so
            # the gate-token search cannot accidentally pass on text
            # from later in the file (Copilot review of PR #195).
            blocks.append("")
            continue
        blocks.append(sanitized[m.end():first_arg_end])
    return blocks


def test_root_pine_alerts_are_bar_close_gated() -> None:
    """Every root-surface Pine alert must reference an accepted gate token."""
    violations: list[str] = []
    for path in _iter_root_pine_files():
        try:
            src = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not _ALERTCOND_RE.search(src):
            continue  # file has no alerts — nothing to gate
        for idx, block in enumerate(_alertcondition_call_blocks(src), start=1):
            if not any(tok in block for tok in _ACCEPTED_GATE_TOKENS):
                violations.append(
                    f"{path.name}: alertcondition()#{idx} has no gate "
                    f"(accepted: {', '.join(_ACCEPTED_GATE_TOKENS)})"
                )
    assert not violations, (
        "Root-surface Pine alerts must be gated to bar-close "
        "(H-1, system review 2026-04-24):\n  - "
        + "\n  - ".join(violations)
    )
