"""The customer-facing Pine surfaces must not speak internal plumbing.

Phase 3 of `docs/commercial/COMMERCIAL_PRODUCT_BASELINE_AND_ACTION_PLAN.md`
requires that the design-partner pilot "hide operator/BUS/provider plumbing
from product UX". Measured on 2026-08-12, before this guard existed, the four
customer surfaces carried 17 leaks across 252 customer-visible inputs plus 11
group labels: nine settings groups literally named "Operator Only - ...",
three internal-operations switches sitting in the customer's first group, and
tooltips quoting plan sections, work-package ids, repo paths and library names.

What this guard checks, and what it deliberately does not:

* POPULATION - every input declaration in the four surfaces, minus the
  internal groups listed in :data:`INTERNAL_GROUP_VARS`. Both strings a
  customer can read in the settings panel are inspected: the title and the
  tooltip. Customer-visible group labels are inspected too.
* NOT CHECKED - the input TITLES inside the internal groups. Those 68 "BUS ..."
  names are the TradingView binding contract that the onboarding automation
  matches on (`automation/tradingview/lib/tv_shared.ts`); renaming them is a
  separate change that has to move the matcher, the drift monitor and the
  saved TradingView copies in one step.

The partition is keyed on the group VARIABLE, never on its label, so the
customer-facing wording stays free to change.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO_ROOT / "spec" / "hero_surface_input_map.json"

# Group VARIABLES whose inputs the customer is told not to touch: the chart-link
# bindings that SMC Onboarding fills automatically, the debug mirrors and the
# manual internal overrides.
INTERNAL_GROUP_VARS: dict[str, frozenset[str]] = {
    "SMC_Long_Dip_Dashboard.pine": frozenset({
        "g_bus_lifecycle", "g_bus_diag", "g_bus_plan", "g_bus_diag_rows",
        "g_bus_blockers", "g_bus_detail", "g_bus_lean", "g_bus_preset",
        "g_local_debug", "g_operator_ops",
    }),
    "SMC_Long_Dip_Mobile.pine": frozenset({"g_bus"}),
    "SMC_Long_Dip_Alerts.pine": frozenset({"g_bus"}),
    "SMC_Long_Dip_Suite.pine": frozenset(),
}

# Lower bounds on what the parser must still find. Without them a broken regex
# would empty the population and report a clean surface (the failure mode the
# 2026-08 vacuity sweep kept finding: a guard that passes by measuring nothing).
# Measured 2026-08-12 and pinned at the measured value, so removing a customer
# input is a deliberate pin update rather than a silent shrink. Adding inputs
# never trips these.
MIN_INPUTS: dict[str, int] = {
    "SMC_Long_Dip_Dashboard.pine": 11,
    "SMC_Long_Dip_Mobile.pine": 5,
    "SMC_Long_Dip_Alerts.pine": 2,
    "SMC_Long_Dip_Suite.pine": 227,
}

# Same, for settings-group labels. Cross-checked 2026-08-12 against
# `grep -cE "^\s*(var\s+)?(string\s+)?g_[a-z_0-9]+\s*="`: 26/12/3/3, identical.
MIN_GROUP_LABELS: dict[str, int] = {
    "SMC_Long_Dip_Dashboard.pine": 12,
    "SMC_Long_Dip_Mobile.pine": 3,
    "SMC_Long_Dip_Alerts.pine": 3,
    "SMC_Long_Dip_Suite.pine": 26,
}

# Vocabulary that belongs to internal plumbing rather than a product UX.
PLUMBING_PATTERNS: dict[str, str] = {
    "BUS channel name": r"\bBUS\b",
    "operator role": r"\boperator\b",
    "sidecar": r"\bsidecar\b",
    "internal plan reference": r"\bPlan\s*(?:§|W\d|\d+\.\d)|\bAddendum\s+\d",
    "work-package id": r"\bWP-[A-Z]+\d*\b",
    "repo path": r"\b(?:docs|pine|scripts|artifacts|smc_core)/[\w./-]+",
    "internal library name": r"\bsmc_[a-z_]+\b",
    "retired umbrella name": r"\bCore Engine\b|\bSkippALGO\b",
}

# Terms that look internal but are legitimate customer vocabulary, each with the
# reason it is allowed. Applied before the patterns run.
ALLOWED_TERMS: dict[str, str] = {
    "SMC_Hold_Manager": "real TradingView script name a customer adds to the chart",
    "SMC_Exit_Signal": "real TradingView script name a customer adds to the chart",
}

_INPUT_RE = re.compile(
    r"^(?:var\s+)?(?:(?:bool|int|float|string|color)\s+)?(?P<var>\w+)\s*=\s*input(?:\.\w+)?\("
)
_GROUP_RE = re.compile(r"\bgroup\s*=\s*(?P<var>\w+)")
_TITLE_RE = re.compile(r"""input(?:\.\w+)?\(\s*(?:[^,]*,\s*)?["'](?P<t>[^"']{2,})["']""")
_TOOLTIP_RE = re.compile(r"""\btooltip\s*=\s*["'](?P<t>(?:[^"'\\]|\\.)*)["']""")
# All three declaration styles in the tree: `var string g_x = "..."` (Dashboard),
# `var g_x = '...'` (Suite) and a bare `g_x = '...'` (Alerts). Missing one of them
# silently shrinks the population — the Suite alone declares its groups as `var
# g_x` and a `var string`-only pattern saw 1 of its 40 labels.
_GROUP_DEF_RE = re.compile(
    r"""^\s*(?:var\s+)?(?:string\s+)?(?P<var>g_\w+)\s*=\s*["'](?P<label>[^"']+)["']\s*$"""
)

PINE_FILES = sorted(INTERNAL_GROUP_VARS)


def _leaks(text: str) -> list[str]:
    for term in ALLOWED_TERMS:
        text = text.replace(term, "")
    return [
        name for name, pattern in PLUMBING_PATTERNS.items()
        if re.search(pattern, text, re.IGNORECASE)
    ]


def _read(pine_file: str) -> list[str]:
    return (REPO_ROOT / pine_file).read_text(encoding="utf-8").splitlines()


@pytest.mark.parametrize("pine_file", PINE_FILES)
def test_customer_visible_inputs_carry_no_plumbing_vocabulary(pine_file: str) -> None:
    internal = INTERNAL_GROUP_VARS[pine_file]
    found: list[str] = []
    population = 0

    for lineno, line in enumerate(_read(pine_file), 1):
        match = _INPUT_RE.match(line.strip())
        if not match:
            continue
        group_match = _GROUP_RE.search(line)
        group = group_match.group("var") if group_match else None
        if group in internal:
            continue
        population += 1

        title_match, tooltip_match = _TITLE_RE.search(line), _TOOLTIP_RE.search(line)
        title = title_match.group("t") if title_match else ""
        tooltip = tooltip_match.group("t") if tooltip_match else ""
        for where, text in (("title", title), ("tooltip", tooltip)):
            for leak in _leaks(text):
                found.append(f"{pine_file}:{lineno} {match.group('var')} {where} -> {leak}")

    assert population >= MIN_INPUTS[pine_file], (
        f"{pine_file}: only {population} customer-visible inputs parsed, expected at least "
        f"{MIN_INPUTS[pine_file]} — the parser broke, so a pass here would be vacuous"
    )
    assert not found, "internal vocabulary on a customer surface:\n" + "\n".join(found)


@pytest.mark.parametrize("pine_file", PINE_FILES)
def test_customer_visible_group_labels_carry_no_plumbing_vocabulary(pine_file: str) -> None:
    found: list[str] = []
    labels = 0

    for lineno, line in enumerate(_read(pine_file), 1):
        match = _GROUP_DEF_RE.match(line)
        if not match:
            continue
        labels += 1
        for leak in _leaks(match.group("label")):
            found.append(f"{pine_file}:{lineno} {match.group('label')!r} -> {leak}")

    assert labels >= MIN_GROUP_LABELS[pine_file], (
        f"{pine_file}: only {labels} group labels parsed, expected at least "
        f"{MIN_GROUP_LABELS[pine_file]} — the parser broke, so a pass here would be vacuous"
    )
    assert not found, "internal vocabulary in a settings group label:\n" + "\n".join(found)


def test_internal_group_partition_matches_the_hero_surface_spec() -> None:
    """The two internal-group lists must not drift apart.

    ``spec/hero_surface_input_map.json`` drives the display.none invariant and
    this guard drives the vocabulary one. Until 2026-08-12 the spec omitted
    ``g_bus_blockers`` and ``g_bus_preset``, so two of the nine internal
    Dashboard groups were checked by neither.
    """
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    for pine_file, spec_entry in spec["files"].items():
        assert set(spec_entry["operator_only_groups"]) == set(INTERNAL_GROUP_VARS[pine_file]), (
            f"{pine_file}: spec operator_only_groups and INTERNAL_GROUP_VARS disagree"
        )
