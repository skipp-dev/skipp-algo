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

**Die Regeln selbst stehen seit 2026-08-13 in
`scripts/check_customer_surface_vocabulary.py`**, nicht mehr hier. Grund: Auf
der `bot/*`-Spur von `smc-fast-pr-gates.yml` läuft kein pytest, und genau dort
hat der Bibliothekslauf die vier Oberflächen dreimal unbeobachtet
zurückgedreht (#4646, #4665; repariert als #4650, #4652, #4666). Das Skript ist
stdlib-only und läuft deshalb auch auf dieser Spur. Dieser Test fährt dieselben
Funktionen — es gibt keine zweite Kopie der Regeln.
"""

from __future__ import annotations

import pytest

from scripts.check_customer_surface_vocabulary import (
    INTERNAL_GROUP_VARS,
    MIN_GROUP_LABELS,
    MIN_INPUTS,
    PINE_FILES,
    group_label_leaks,
    input_leaks,
    main,
    spec_partition_disagreements,
)


@pytest.mark.parametrize("pine_file", PINE_FILES)
def test_customer_visible_inputs_carry_no_plumbing_vocabulary(pine_file: str) -> None:
    found, population = input_leaks(pine_file)
    assert population >= MIN_INPUTS[pine_file], (
        f"{pine_file}: only {population} customer-visible inputs parsed, expected at least "
        f"{MIN_INPUTS[pine_file]} — the parser broke, so a pass here would be vacuous"
    )
    assert not found, "internal vocabulary on a customer surface:\n" + "\n".join(found)


@pytest.mark.parametrize("pine_file", PINE_FILES)
def test_customer_visible_group_labels_carry_no_plumbing_vocabulary(pine_file: str) -> None:
    found, labels = group_label_leaks(pine_file)
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
    assert spec_partition_disagreements() == []


def test_the_script_the_bot_lane_runs_agrees_with_these_tests() -> None:
    """Die `bot/*`-Spur fährt das SKRIPT, nicht pytest.

    Ohne diesen Fall könnte das Skript stillschweigend etwas anderes prüfen als
    die Tests — und die Spur wäre wieder blind, diesmal auf eine Art, die
    niemandem auffällt. Der Aufruf ist derselbe wie im Workflow.
    """
    assert main([]) == 0


def test_the_script_fails_when_a_surface_leaks(monkeypatch) -> None:
    """Gegenprobe: Ein Leck muss das Skript mit Exit 1 beenden.

    Sonst liefe im Workflow ein Schritt, der grundsätzlich grün ist — genau die
    Sorte Gate, die den Vorfall überhaupt erst durchgelassen hat. Eingeschleust
    wird die Signatur des echten Vorfalls: eine Werkpaket-Kennung im Tooltip.
    """
    import scripts.check_customer_surface_vocabulary as module

    unpatched = module.read_lines
    target = PINE_FILES[0]
    injected = [
        'x_leak = input.bool(false, "Compact", group = g_surface, '
        'tooltip = "WP-OV5: internal")'
    ]

    def with_leak(pine_file: str) -> list[str]:
        lines = unpatched(pine_file)
        return lines + injected if pine_file == target else lines

    monkeypatch.setattr(module, "read_lines", with_leak)
    assert module.main([]) == 1


def test_every_surface_is_covered_by_both_bounds() -> None:
    """Über die GANZE Menge: keine Oberfläche ohne beide Untergrenzen."""
    assert set(PINE_FILES) == set(MIN_INPUTS) == set(MIN_GROUP_LABELS)
    assert set(PINE_FILES) == set(INTERNAL_GROUP_VARS)
