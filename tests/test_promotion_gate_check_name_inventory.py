"""F-008: every Blocker.check string emitted by PromotionGate.evaluate()
must be either in `BLOCKER_CHECK_NAMES` or start with one of
`BLOCKER_CHECK_NAME_PREFIXES`.

Dashboards / promotion-report consumers grep these strings; a silent
rename or a newly-added unlisted check name is a contract break.
"""
from __future__ import annotations

import re
from pathlib import Path

from governance.types import (
    BLOCKER_CHECK_NAME_PREFIXES,
    BLOCKER_CHECK_NAMES,
)

ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = ROOT / "governance" / "promotion_gate.py"

# Static scan: pick up every literal ``"check": "<name>"`` and every
# f-string variant ``"check": f"provenance.{key}"`` AND every check name
# passed via the ``name=`` kwarg to the ``_check()`` helper (which then
# writes ``"check": name`` internally).
_CHECK_LITERAL_RE = re.compile(r'"check"\s*:\s*"([A-Za-z0-9_.]+)"')
_CHECK_FSTRING_RE = re.compile(r'"check"\s*:\s*f"([A-Za-z0-9_.]+)\{')
_CHECK_KWARG_RE = re.compile(r'\bname\s*=\s*"([a-z][a-z0-9_]*)"')


def _emitted_check_names() -> set[str]:
    text = GATE_PATH.read_text(encoding="utf-8")
    literals = set(_CHECK_LITERAL_RE.findall(text))
    fstring_prefixes = set(_CHECK_FSTRING_RE.findall(text))
    kwargs = set(_CHECK_KWARG_RE.findall(text))
    return literals | fstring_prefixes | kwargs


def test_inventory_is_non_empty() -> None:
    assert BLOCKER_CHECK_NAMES, "BLOCKER_CHECK_NAMES must not be empty"


def test_every_emitted_check_name_is_inventoried() -> None:
    emitted = _emitted_check_names()
    assert emitted, (
        "no Blocker.check literals found in governance/promotion_gate.py - "
        "regex broke or file was restructured"
    )
    missing: list[str] = []
    for name in emitted:
        if name in BLOCKER_CHECK_NAMES:
            continue
        if any(name.startswith(p) or (p.rstrip(".") == name) for p in BLOCKER_CHECK_NAME_PREFIXES):
            continue
        missing.append(name)
    assert not missing, (
        "promotion_gate.py emits check names not listed in "
        "governance.types.BLOCKER_CHECK_NAMES / "
        "BLOCKER_CHECK_NAME_PREFIXES: "
        f"{sorted(missing)}. Add them to the inventory in the same commit."
    )


def test_no_stale_inventory_entries() -> None:
    """Guard the other direction: inventory entries that nothing emits
    indicate dead code / renamed checks that survived the rename only
    in the inventory."""
    emitted = _emitted_check_names()
    stale = sorted(name for name in BLOCKER_CHECK_NAMES if name not in emitted)
    assert not stale, (
        "BLOCKER_CHECK_NAMES contains entries no longer emitted by "
        f"promotion_gate.py: {stale}. Remove them or restore the emit site."
    )
