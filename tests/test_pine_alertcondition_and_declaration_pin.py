"""Defense-pin: Pine ``alertcondition()`` ledger + single-declaration discipline.

Two complementary pins on top of `*.pine` artifacts:

A. ``alertcondition()`` budget ledger
   ----------------------------------
   ``alertcondition()`` exposes user-facing TradingView alert slots. New
   alerts are not free — each one expands the user-visible alert surface
   and must be added intentionally with a corresponding alert-name in the
   compile preflight. Frozen total = 35 across 6 files.

B. Single declaration per Pine file
   --------------------------------
   Every standalone Pine file must contain exactly one top-level
   ``indicator(...)``, ``strategy(...)``, or ``library(...)`` declaration.
   A second declaration would silently shadow the first and make TV's
   "Add to chart" pick the wrong one. The frozen distribution covers
   20 indicator/strategy entries (one per file).

Defense-only, no Pine code changes.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_PINE_GENERATED_NAMES = frozenset({"_snippet.pine"})


def _iter_pine_files() -> Iterator[Path]:
    for p in sorted(ROOT.glob("*.pine")):
        if p.name in _PINE_GENERATED_NAMES:
            continue
        yield p


def _strip_strings_and_comments(line: str) -> str:
    """Remove ``//`` comments while honouring ``"`` and ``'`` string literals."""
    out: list[str] = []
    i = 0
    n = len(line)
    while i < n:
        ch = line[i]
        if ch == "/" and i + 1 < n and line[i + 1] == "/":
            break
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            while i < n:
                out.append(line[i])
                if line[i] == "\\" and i + 1 < n:
                    out.append(line[i + 1])
                    i += 2
                    continue
                if line[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------------------
# Layer A — alertcondition ledger
# ---------------------------------------------------------------------------

_ALERTCOND_RE = re.compile(r"\balertcondition\s*\(")

_FROZEN_ALERTCOND_COUNTS: dict[str, int] = {
    "SMC_Breakout_Overlay.pine": 3,
    # SMC_Long_Dip_Suite.pine converted its 16 alertcondition() to alert() so the
    # 64-channel BUS producer stays within TradingView's 64-plot budget
    # (alertcondition() counts as a plot-count; RE10140). It now declares zero.
    # SMC_Long_Dip_Alerts.pine is the companion that restores those 16 as
    # individually-selectable alertcondition() slots (it produces no BUS, so its
    # plot budget is unconstrained).
    "SMC_Long_Dip_Alerts.pine": 16,
    "SMC_Event_Overlay.pine": 2,
    "SMC_Exit_Signal.pine": 6,
    "SMC_Hold_Manager.pine": 6,
    "SMC_Confluence_Hub.pine": 2,
}
_FROZEN_ALERTCOND_TOTAL = sum(_FROZEN_ALERTCOND_COUNTS.values())


def _scan_alertconditions() -> dict[str, int]:
    out: dict[str, int] = {}
    for p in _iter_pine_files():
        try:
            src = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        n = 0
        for line in src.splitlines():
            stripped = _strip_strings_and_comments(line)
            n += len(_ALERTCOND_RE.findall(stripped))
        if n:
            out[p.name] = n
    return out


def test_pine_inventory_sane() -> None:
    files = list(_iter_pine_files())
    assert len(files) >= 15, f"Pine inventory shrank: {len(files)}"


def test_alertcondition_total_frozen() -> None:
    counts = _scan_alertconditions()
    total = sum(counts.values())
    assert total == _FROZEN_ALERTCOND_TOTAL, (
        f"alertcondition() total drifted: expected {_FROZEN_ALERTCOND_TOTAL}, "
        f"got {total}; per-file = {counts}"
    )


def test_alertcondition_no_new_files() -> None:
    counts = _scan_alertconditions()
    new = sorted(set(counts) - set(_FROZEN_ALERTCOND_COUNTS))
    assert not new, (
        "New Pine files declare alertcondition() — add to ledger and "
        f"register the alert names in the compile preflight: {new}"
    )


def test_alertcondition_no_stale_entries() -> None:
    counts = _scan_alertconditions()
    stale = sorted(set(_FROZEN_ALERTCOND_COUNTS) - set(counts))
    assert not stale, (
        "Frozen alertcondition() ledger lists files with no remaining "
        f"alerts — remove from _FROZEN_ALERTCOND_COUNTS: {stale}"
    )


@pytest.mark.parametrize("name,expected", sorted(_FROZEN_ALERTCOND_COUNTS.items()))
def test_alertcondition_per_file_count(name: str, expected: int) -> None:
    counts = _scan_alertconditions()
    actual = counts.get(name, 0)
    assert actual == expected, (
        f"{name}: alertcondition() count drifted (expected {expected}, "
        f"got {actual})."
    )


@pytest.mark.parametrize("name", sorted(_FROZEN_ALERTCOND_COUNTS))
def test_alertcondition_files_exist(name: str) -> None:
    assert (ROOT / name).is_file(), f"Ledger Pine file missing: {name}"


# ---------------------------------------------------------------------------
# Layer B — single top-level declaration per Pine file
# ---------------------------------------------------------------------------

_DECL_RE = re.compile(r"^(indicator|strategy|library)\s*\(", re.MULTILINE)

# Frozen distribution: file -> declaration kind. Exactly one per file.
_FROZEN_DECL_KIND: dict[str, str] = {
    "SMC_Breakout_Overlay.pine": "indicator",
    "SMC_Long_Dip_Suite.pine": "indicator",
    "SMC_Long_Dip_Dashboard.pine": "indicator",
    "SMC_Event_Overlay.pine": "indicator",
    "SMC_Exit_Signal.pine": "indicator",
    "SMC_HTF_Confluence.pine": "indicator",
    "SMC_Hold_Manager.pine": "indicator",
    "SMC_Imbalance_Context.pine": "indicator",
    "SMC_Liquidity_Context.pine": "indicator",
    "SMC_Liquidity_Structure.pine": "indicator",
    "SMC_Long_Dip_Strategy.pine": "strategy",
    "SMC_Long_Dip_Mobile.pine": "indicator",
    "SMC_Orderflow_Overlay.pine": "indicator",
    "SMC_Profile_Context.pine": "indicator",
    "SMC_Session_Context.pine": "indicator",
    "SMC_Setup_Check.pine": "indicator",
    "SMC_Structure_Context.pine": "indicator",
    "SMC_Regime_and_News.pine": "indicator",
    "SMC_Volume_Profile_Overlay.pine": "indicator",
    "SMC_Confluence_Hub.pine": "indicator",
    "SMC_Long_Dip_Alerts.pine": "indicator",
    "test_div.pine": "indicator",
}


def _scan_declarations() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for p in _iter_pine_files():
        try:
            src = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        # Strip comments line-by-line first, then match.
        cleaned_lines = []
        for line in src.splitlines():
            stripped = _strip_strings_and_comments(line)
            cleaned_lines.append(stripped)
        cleaned = "\n".join(cleaned_lines)
        kinds = _DECL_RE.findall(cleaned)
        if kinds:
            out[p.name] = kinds
    return out


def test_declaration_no_new_files() -> None:
    decls = _scan_declarations()
    new = sorted(set(decls) - set(_FROZEN_DECL_KIND))
    assert not new, (
        "New Pine files contain top-level indicator/strategy/library — "
        f"append to _FROZEN_DECL_KIND: {new}"
    )


def test_declaration_no_stale_entries() -> None:
    decls = _scan_declarations()
    stale = sorted(set(_FROZEN_DECL_KIND) - set(decls))
    assert not stale, (
        "Frozen declaration ledger lists files with no remaining "
        f"declaration — remove from _FROZEN_DECL_KIND: {stale}"
    )


@pytest.mark.parametrize("name,expected_kind", sorted(_FROZEN_DECL_KIND.items()))
def test_declaration_single_and_correct_kind(name: str, expected_kind: str) -> None:
    decls = _scan_declarations()
    kinds = decls.get(name, [])
    assert len(kinds) == 1, (
        f"{name}: expected exactly 1 top-level declaration, got {len(kinds)}: "
        f"{kinds}. A second indicator/strategy/library would silently shadow "
        "the first."
    )
    assert kinds[0] == expected_kind, (
        f"{name}: declaration kind drifted (expected {expected_kind!r}, "
        f"got {kinds[0]!r}). Switching indicator <-> strategy is breaking."
    )


@pytest.mark.parametrize("name", sorted(_FROZEN_DECL_KIND))
def test_declaration_files_exist(name: str) -> None:
    assert (ROOT / name).is_file(), f"Ledger Pine file missing: {name}"


# ---------------------------------------------------------------------------
# Layer C — dynamic-alert gate on the Suite's alert() sites
# ---------------------------------------------------------------------------
#
# The Suite's 'Enable dynamic alerts' input promises "Disable to silence all
# dynamic alert output". Unlike alertcondition() — which TradingView switches
# off per-slot in the UI — an alert() call fires purely on its enclosing
# condition, so that promise only holds while every site carries the flag.
# It did not: #3622 removed the gated emitter and #3642 rebuilt the sites as
# plain alert() without re-applying the flag, leaving the toggle inert.

_ALERT_GATE_FLAG = "enable_dynamic_alerts"
_ALERT_CALL_RE = re.compile(r"\balert\s*\(")

# Frozen: the 16 alert() sites that replaced the Suite's 16 alertcondition()
# slots (see _FROZEN_ALERTCOND_COUNTS above — SMC_Long_Dip_Alerts.pine still
# carries the same 16 as individually-selectable alertcondition() entries).
_FROZEN_SUITE_ALERT_SITES = 16
_SUITE_NAME = "SMC_Long_Dip_Suite.pine"


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _enclosing_if_conditions(lines: list[str], idx: int) -> list[str]:
    """Conditions of every ``if`` block enclosing ``lines[idx]``.

    Walks outward by indentation rather than assuming a fixed depth, so a
    site nested deeper than the prevailing one-indent shape still resolves
    to its real owners.
    """
    conditions: list[str] = []
    indent = _indent_of(lines[idx])
    for j in range(idx - 1, -1, -1):
        line = lines[j]
        if not line.strip():
            continue
        outer = _indent_of(line)
        if outer >= indent:
            continue
        code = _strip_strings_and_comments(line).strip()
        if code.startswith(("if ", "else if ")):
            conditions.append(code)
        indent = outer
        if outer == 0:
            break
    return conditions


def _scan_suite_alert_sites() -> list[tuple[int, list[str]]]:
    """``(1-indexed line, enclosing if-conditions)`` per alert() call site."""
    lines = (ROOT / _SUITE_NAME).read_text(encoding="utf-8").splitlines()
    sites: list[tuple[int, list[str]]] = []
    for i, line in enumerate(lines):
        if _ALERT_CALL_RE.search(_strip_strings_and_comments(line)):
            sites.append((i + 1, _enclosing_if_conditions(lines, i)))
    return sites


def test_suite_alert_site_count_frozen() -> None:
    sites = _scan_suite_alert_sites()
    assert len(sites) == _FROZEN_SUITE_ALERT_SITES, (
        f"{_SUITE_NAME}: alert() site count drifted (expected "
        f"{_FROZEN_SUITE_ALERT_SITES}, got {len(sites)}). A new alert() widens "
        f"the user-visible alert surface — add it gated on {_ALERT_GATE_FLAG} "
        "and bump this pin deliberately."
    )


def test_every_suite_alert_site_is_gated_on_the_dynamic_alerts_toggle() -> None:
    ungated = [
        line
        for line, conditions in _scan_suite_alert_sites()
        if not any(_ALERT_GATE_FLAG in c for c in conditions)
    ]
    assert not ungated, (
        f"{_SUITE_NAME}: alert() at line(s) {ungated} fire regardless of "
        f"'{_ALERT_GATE_FLAG}', so disabling the input does not silence them "
        "as its tooltip promises. Carry the flag in an enclosing if-condition."
    )


# ---------------------------------------------------------------------------
# Layer D — the alert surface must not arm lower-timeframe sampling
# ---------------------------------------------------------------------------
#
# The 16 alert() messages are static text: they carry no LTF fields, so nothing
# in the alert surface may pull `request.security_lower_tf()` into the runtime
# path. A `use_ltf_for_dynamic_alerts` input used to do exactly that — it armed
# real sampling to decorate messages that never read the result. Same class as
# the `dynamic_long_alert_mode` input removed in #3548.

_LTF_GATE_VAR = "ltf_needed"
_ALERT_TOKENS = ("alert", "_ALERT")


def _ltf_needed_expression() -> str:
    """Right-hand side of the ``ltf_needed`` decision in the Suite."""
    for line in (ROOT / _SUITE_NAME).read_text(encoding="utf-8").splitlines():
        code = _strip_strings_and_comments(line)
        m = re.match(rf"\s*(?:bool\s+)?{_LTF_GATE_VAR}\s*(?::=|=)\s*(.+)$", code)
        if m:
            return m.group(1).strip()
    raise AssertionError(f"{_SUITE_NAME}: no `{_LTF_GATE_VAR}` decision found")


def test_ltf_sampling_is_not_armed_by_the_alert_surface() -> None:
    expr = _ltf_needed_expression()
    offenders = [t for t in _ALERT_TOKENS if t in expr]
    assert not offenders, (
        f"{_SUITE_NAME}: `{_LTF_GATE_VAR}` depends on {offenders} — the alert "
        "surface would arm request.security_lower_tf() for messages that carry "
        f"no LTF fields. Derive `{_LTF_GATE_VAR}` from real consumers only "
        "(dashboard, strict entry)."
    )
