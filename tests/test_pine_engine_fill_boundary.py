"""Pin: the engine's FVG fill decision is inclusive at the target level.

Background
==========

``FVG.update()`` decides ``filled`` by comparing the bar's fill source against
``fill_target_level`` (``top - ratio*size`` for bull, ``btm + ratio*size`` for
bear). It used to demand that price travel one tick *past* that level::

    this.filled := this.fill_target_level > fill_src    // bull

so a gap filled exactly to its target never retired. At the ``0.5`` default the
bug is invisible — price rarely lands on the midpoint to the tick. At ``1.0``,
which is what the context library needs (the golden contract keeps an FVG active
until ``FULL_MIT_PCT``), the target IS the gap floor and "filled exactly to the
bottom" is a real, reachable state that would have left a zombie in the active
buffer forever.

The Python contract already resolves the tie the other way:
``smc_imbalance_lifecycle`` counts ``mit_pct < FULL_MIT_PCT`` as active — so
``mit_pct == 1.0`` is mitigated — and clamps ``mit_pct`` to exactly ``1.0``. The
engine disagreed with its own golden at the boundary.

What this file does NOT do
--------------------------
It does not execute Pine. There is no Pine runtime in CI, so the behaviour table
(under target / exactly target / past target, bull and bear, close and highlow)
cannot be driven here — that is a manual operator gate on TradingView. These are
source contracts: they pin the operator's direction and inclusivity, and the
agreement with the golden threshold that motivates it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENGINE = REPO_ROOT / "SMC++" / "smc_engine_private.pine"
ORACLE = REPO_ROOT / "scripts" / "smc_imbalance_lifecycle.py"
GOLDEN = REPO_ROOT / "tests" / "fixtures" / "smc_context_golden.json"


def _update_method() -> str:
    """Body of ``export method update(FVG this)``, up to the next export."""
    src = ENGINE.read_text(encoding="utf-8")
    start = re.search(r"^export method update\(FVG this\) =>", src, re.MULTILINE)
    assert start, "export method update(FVG this) not found"
    rest = src[start.end() :]
    nxt = re.search(r"^export ", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def _filled_assignments() -> list[str]:
    return [
        m.group(1).strip()
        for m in re.finditer(r"this\.filled\s*:=\s*(.+)$", _update_method(), re.MULTILINE)
    ]


def test_update_decides_filled_on_both_sides() -> None:
    """One terminal decision per direction — bull and bear."""
    assignments = _filled_assignments()
    assert len(assignments) == 2, (
        f"expected exactly two `this.filled :=` decisions (bull, bear), found "
        f"{len(assignments)}: {assignments!r}"
    )


def test_bull_fill_is_inclusive_at_the_target_level() -> None:
    """Bull retires when the fill source reaches the target, not one tick past."""
    bull, _bear = _filled_assignments()
    assert bull == "fill_src <= this.fill_target_level", (
        f"bull fill decision is {bull!r}. It must be inclusive "
        "(`fill_src <= this.fill_target_level`): a strict comparison leaves a gap "
        "filled exactly to its target active forever, which at ratio 1.0 is the "
        "reachable exact-100% state."
    )


def test_bear_fill_is_inclusive_at_the_target_level() -> None:
    """Bear is the mirror of bull — the same tie must resolve the same way."""
    _bull, bear = _filled_assignments()
    assert bear == "fill_src >= this.fill_target_level", (
        f"bear fill decision is {bear!r}. It must be inclusive "
        "(`fill_src >= this.fill_target_level`)."
    )


def test_fill_decisions_are_direction_symmetric() -> None:
    """Bull and bear must differ only in the comparison direction.

    An asymmetry here is a silent long/short bias in every consumer of the FVG
    lifecycle.
    """
    bull, bear = _filled_assignments()
    assert bull.replace("<=", "OP") == bear.replace(">=", "OP"), (
        f"bull {bull!r} and bear {bear!r} are not mirror images — they must "
        "compare the same operands and differ only in direction"
    )


def test_progress_guards_stay_strict() -> None:
    """The `has price moved further in` guards must NOT become inclusive.

    They gate whether there is new fill progress at all. Making them inclusive
    would re-run the fill maths on every flat bar; only the terminal `filled`
    decision is about reaching the target.
    """
    body = _update_method()
    assert "if this.fill_current_level > fill_src" in body, (
        "the bull progress guard is no longer a strict `>` — this is not the "
        "comparison the inclusivity fix is about"
    )
    assert "if this.fill_current_level < fill_src" in body, (
        "the bear progress guard is no longer a strict `<`"
    )


def test_engine_boundary_agrees_with_the_golden_full_mitigation() -> None:
    """The inclusive tie-break is what the Python contract already asserts.

    The oracle counts `mit_pct < FULL_MIT_PCT` as active and clamps mit_pct to
    1.0, so exactly-full is mitigated there. If that ever flips to `<=`, the
    engine's inclusive `filled` would contradict it and this pin is the warning.
    """
    full_mit = json.loads(GOLDEN.read_text(encoding="utf-8"))["_meta"]["thresholds"][
        "imbalance"
    ]["FULL_MIT_PCT"]
    assert full_mit == 1.0, f"golden FULL_MIT_PCT moved to {full_mit}"

    oracle = ORACLE.read_text(encoding="utf-8")
    assert "if mit_pct < FULL_MIT_PCT:" in oracle, (
        "the oracle no longer treats `mit_pct < FULL_MIT_PCT` as the active "
        "condition, so exactly-full may no longer mean mitigated — re-check the "
        "engine's inclusive fill decision against it"
    )
    assert "min(fill_depth / gap_size, 1.0)" in oracle, (
        "the oracle no longer clamps mit_pct to 1.0, so exactly-full is not "
        "reachable there and the boundary contract is untestable"
    )
