"""Every ``alert()`` call in root-surface Pine must be bar-close gated.

Companion to ``test_pine_alert_bar_close_gate.py``, which holds the same rule
for ``alertcondition()``. The two functions have different firing mechanics —
``alertcondition()`` is armed per-slot in the TradingView UI, ``alert()``
fires through a single "Any alert() function call" alert — but the intra-bar
hazard is identical: an ungated call evaluates on every live tick, fires on
conditions that can evaporate by close, and (for webhook consumers like the
Hold Manager shadow receiver) delivers bar_time values the confirmed bar never
carried.

The population check at the bottom is load-bearing: a guard whose population
can silently shrink to zero passes by inspecting nothing (the repository's
vacuity sweeps exist because exactly that happened elsewhere).

Named-condition resolution
--------------------------
A line-local check is not enough. ``SMC_Long_Dip_Suite.pine`` gates one call
as ``if enable_dynamic_alerts and event_risk_alert_now`` — no gate token on
the line, but ``event_risk_alert_now`` is DEFINED as
``... and barstate.isconfirmed and ...``. The guard therefore resolves each
bare identifier in the ``if`` expression to its single assignment and accepts
a gate token found there. One level only, and fail-closed: an identifier
without a resolvable assignment contributes nothing.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from tests._pine_text import strip_pine_strings_and_line_comments

ROOT = Path(__file__).resolve().parent.parent

_PINE_GENERATED_NAMES = frozenset({"_snippet.pine"})

# \b would treat "." as a boundary and match alertcondition's inner "alert";
# require the char before "alert(" to not be an identifier char or dot.
_ALERT_CALL_RE = re.compile(r"(?<![\w.])alert\s*\(")

_GATE_TOKENS = (
    "_alertGate",
    "barstate.isconfirmed",
    "barstate.islastconfirmedhistory",
)

_IDENTIFIER_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b")


def _iter_root_pine_files() -> Iterator[Path]:
    for p in sorted(ROOT.glob("*.pine")):
        if p.name in _PINE_GENERATED_NAMES:
            continue
        yield p


def _enclosing_if_condition(lines: list[str], call_index: int) -> str | None:
    """The condition of the nearest preceding ``if`` at LOWER indentation."""
    call_indent = len(lines[call_index]) - len(lines[call_index].lstrip())
    for index in range(call_index - 1, -1, -1):
        line = lines[index]
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        if indent >= call_indent:
            continue
        stripped = line.strip()
        if stripped.startswith("if "):
            return stripped[3:]
        # A lower-indented line that is not an `if` means the call is not
        # inside a conditional block at all.
        return None
    return None


def _assignment_of(name: str, source: str) -> str | None:
    """The right-hand side of ``name``'s single assignment, if exactly one."""
    matches = re.findall(
        rf"^\s*(?:bool\s+|var\s+bool\s+)?{re.escape(name)}\s*:?=\s*(.+)$",
        source,
        re.M,
    )
    return matches[0] if len(matches) == 1 else None


def _condition_is_gated(condition: str, source: str) -> bool:
    if any(token in condition for token in _GATE_TOKENS):
        return True
    for identifier in _IDENTIFIER_RE.findall(condition):
        assignment = _assignment_of(identifier, source)
        if assignment and any(token in assignment for token in _GATE_TOKENS):
            return True
    return False


def _ungated_calls(path: Path) -> list[tuple[int, str]]:
    source = strip_pine_strings_and_line_comments(
        path.read_text(encoding="utf-8")
    )
    lines = source.splitlines()
    failures: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if not _ALERT_CALL_RE.search(line):
            continue
        condition = _enclosing_if_condition(lines, index)
        if condition is None or not _condition_is_gated(condition, source):
            failures.append((index + 1, line.strip()))
    return failures


def test_every_alert_call_is_bar_close_gated() -> None:
    problems: list[str] = []
    population = 0
    for path in _iter_root_pine_files():
        source = strip_pine_strings_and_line_comments(
            path.read_text(encoding="utf-8")
        )
        population += len(_ALERT_CALL_RE.findall(source))
        for lineno, line in _ungated_calls(path):
            problems.append(f"{path.name}:{lineno}: {line}")

    assert not problems, (
        "alert() calls without a resolvable bar-close gate:\n" + "\n".join(problems)
    )
    # Population floor: the Suite's 16 dynamic alerts plus the Hold Manager's
    # six shadow-transport calls, counted AFTER comment/string stripping (a
    # raw grep also matches "Any alert() function call" in comments). If this
    # drops, the guard has stopped seeing files it used to check —
    # investigate before lowering.
    assert population >= 22, f"population shrank to {population}"


def test_the_hold_manager_and_the_suite_are_in_the_population() -> None:
    """Names, not counts: the two known emitters must actually be covered."""
    covered = {
        path.name
        for path in _iter_root_pine_files()
        if _ALERT_CALL_RE.search(
            strip_pine_strings_and_line_comments(path.read_text(encoding="utf-8"))
        )
    }

    assert "SMC_Hold_Manager.pine" in covered
    assert "SMC_Long_Dip_Suite.pine" in covered


def test_named_condition_resolution_actually_resolves() -> None:
    """The Suite's event-risk alert is the measured case a line-local regex
    gets wrong: no gate token on the ``if`` line, gate inside the named
    condition. If this stops holding, the resolver broke — not the Pine."""
    source = strip_pine_strings_and_line_comments(
        (ROOT / "SMC_Long_Dip_Suite.pine").read_text(encoding="utf-8")
    )

    condition = "enable_dynamic_alerts and event_risk_alert_now"
    assert not any(token in condition for token in _GATE_TOKENS), (
        "the premise vanished: the if-line now carries a gate token itself"
    )
    assert _condition_is_gated(condition, source)


def test_an_ungated_call_is_detected() -> None:
    """Mutation probe, executed: the guard must fail on an ungated alert()."""
    synthetic = (
        "foo = close > open\n"
        "if foo\n"
        "    alert('x', alert.freq_once_per_bar_close)\n"
    )
    lines = synthetic.splitlines()
    assert _ALERT_CALL_RE.search(lines[2])
    condition = _enclosing_if_condition(lines, 2)
    assert condition == "foo"
    assert not _condition_is_gated(condition, synthetic)
