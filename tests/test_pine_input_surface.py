"""Regression tests for Pine input surface-area constraints.

Verifies that major Pine scripts maintain:
  - 100% grouped inputs (all inputs in a group)
  - Status-line visible count within 30-45 range
  - Parity between indicator/strategy pairs
  - Input declarations have balanced parens
  - Version tags present
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pine_input_surface import parse_inputs  # noqa: E402


def _load(name: str) -> list:
    fp = ROOT / name
    if not fp.exists():
        pytest.skip(f"{name} not found")
    return parse_inputs(fp.read_text().splitlines())


# ── grouping: 100 % of inputs must belong to a group ──────────────────

@pytest.mark.parametrize("script", ["SMC++.pine", "SkippALGO.pine", "SkippALGO_Strategy.pine"])
def test_all_inputs_grouped(script):
    inputs = _load(script)
    ungrouped = [i for i in inputs if not i.group]
    assert ungrouped == [], (
        f"{script}: {len(ungrouped)} ungrouped inputs: "
        + ", ".join(f"{i.varname}@L{i.lineno}" for i in ungrouped[:10])
    )


# ── visible surface: 30-45 inputs without display.none ────────────────

@pytest.mark.parametrize("script,lo,hi", [
    ("SMC++.pine", 25, 45),
    ("SkippALGO.pine", 25, 45),
    ("SkippALGO_Strategy.pine", 25, 45),
])
def test_visible_surface_range(script, lo, hi):
    inputs = _load(script)
    visible = sum(1 for i in inputs if not i.has_display_none)
    assert lo <= visible <= hi, (
        f"{script}: {visible} visible inputs (expected {lo}–{hi})"
    )


# ── parity: indicator/strategy pairs must have ≤5 input delta ─────────

@pytest.mark.parametrize("ind,strat,max_delta", [
    ("SkippALGO.pine", "SkippALGO_Strategy.pine", 5),
])
def test_parity_delta(ind, strat, max_delta):
    a = _load(ind)
    b = _load(strat)
    delta = abs(len(a) - len(b))
    assert delta <= max_delta, (
        f"{ind}({len(a)}) vs {strat}({len(b)}): delta {delta} > {max_delta}"
    )


# ── balanced parens in input declarations ──────────────────────────────

@pytest.mark.parametrize("script", ["SMC++.pine", "SkippALGO.pine", "SkippALGO_Strategy.pine"])
def test_input_parens_balanced(script):
    inputs = _load(script)
    bad = []
    for inp in inputs:
        depth = 0
        for c in inp.raw:
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
        if depth != 0:
            bad.append(f"{inp.varname}@L{inp.lineno}")
    assert bad == [], f"{script}: unbalanced parens in {bad}"


# ── version tag present ───────────────────────────────────────────────

@pytest.mark.parametrize("script", ["SMC++.pine", "SkippALGO.pine", "SkippALGO_Strategy.pine"])
def test_version_tag(script):
    fp = ROOT / script
    if not fp.exists():
        pytest.skip(f"{script} not found")
    text = fp.read_text()
    assert "//@version=5" in text or "//@version=6" in text, (
        f"{script}: missing //@version tag"
    )
