"""The customer-facing Pine surfaces must not speak internal plumbing.

Phase 3 of `docs/commercial/COMMERCIAL_PRODUCT_BASELINE_AND_ACTION_PLAN.md`
requires that the design-partner pilot "hide operator/BUS/provider plumbing
from product UX". Measured on 2026-08-12, before this guard existed, the four
customer surfaces carried 17 leaks across 252 customer-visible inputs plus 11
group labels: nine settings groups literally named "Operator Only - ...",
three internal-operations switches sitting in the customer's first group, and
tooltips quoting plan sections, work-package ids, repo paths and library names.

What this guard checks, and what it deliberately does not:

* POPULATION - every input declaration in the guarded surfaces, minus the
  internal groups listed in :data:`INTERNAL_GROUP_VARS`. Four incident
  surfaces until 2026-08-28; since then every onboarding consumer the
  Chart-Link rename could reach (nine files — `SMC_Exit_Signal.pine` stays
  out because it is R1-attested and hash-frozen until the next re-attestation
  session). Both strings a customer can read in the settings panel are
  inspected: the title and the tooltip. Customer-visible group labels are
  inspected too. Since 2026-08-28 a third arm inspects the RENDERED chart
  strings: literals in `table.cell(...)`/`label.new(...)` statements
  (multi-line concatenations joined), in derived render wrappers, and in
  assignments one level above such a statement — the Mobile fallback line,
  the Dashboard version warning and the Hero tooltips live there, not in any
  input declaration.
* NOT CHECKED - the input TITLES inside the internal groups. The "BUS ..."
  names are the TradingView binding contract that the onboarding automation
  matches on (SSOT `automation/tradingview/lib/bus_binding_labels.mjs`);
  renaming them is a separate change that has to move the matcher, the drift
  monitor and the saved TradingView copies in one step. Also not chased by the
  rendered arm: `plot()` titles, helper-function return values and
  var-to-var flow deeper than one assignment level.

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
    MIN_RENDERED,
    PINE_FILES,
    group_label_leaks,
    input_leaks,
    main,
    rendered_string_leaks,
    spec_partition_disagreements,
)
from tests._fast_gates_gate import step_conditions, third_party_import_chain


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


@pytest.mark.parametrize("pine_file", PINE_FILES)
def test_rendered_chart_strings_carry_no_plumbing_vocabulary(pine_file: str) -> None:
    found, rendered = rendered_string_leaks(pine_file)
    assert rendered >= MIN_RENDERED[pine_file], (
        f"{pine_file}: only {rendered} rendered chart strings parsed, expected at "
        f"least {MIN_RENDERED[pine_file]} — the parser broke, so a pass here would "
        "be vacuous"
    )
    assert not found, "internal vocabulary in a rendered chart string:\n" + "\n".join(found)


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


GUARD_STEP = "Guard customer chart surfaces"


def test_the_guard_import_chain_needs_nothing_installed() -> None:
    """Die Bot-Spur installiert NICHTS — hier hängt der Wächter dran.

    `run_heavy=false` überspringt „Set up pinned Python", „Resolve Python 3.12
    interpreter" und „Install dependencies", der Schritt fährt aber trotzdem
    `python -m scripts.check_customer_surface_vocabulary`. Das geht nur, solange
    jedes beim Import ausgeführte Modul stdlib oder repo-lokal ist.

    Der R1-Wächter hat diesen Test seit dem 4.8. — #4668 stellte am 13.8. einen
    ZWEITEN Wächter auf dieselbe Spur, ohne ihn mitzunehmen. Ein einzelnes
    `import yaml` weiter unten fiele keinem Review auf; es würde jeden
    pine-berührenden Bot-PR rot machen, also genau die Spur, auf der der
    Bibliothekslauf fährt. Und das Repo hat diese Klasse schon einmal bezahlt:
    `scripts/smc_atomic_write.py` trägt seinen pandas-Import unter
    TYPE_CHECKING, weil ein Cron ohne pandas beim Import abstürzte.
    """
    third_party = third_party_import_chain(
        "scripts.check_customer_surface_vocabulary"
    )
    assert not third_party, (
        "die Importkette des Oberflächen-Wächters hat stdlib+repo verlassen: "
        + ", ".join(f"{mod} (importiert von {by})" for mod, by in sorted(third_party.items()))
        + ". Die Bot-Spur installiert nichts — entweder den Import unter "
        "TYPE_CHECKING oder in eine Funktion ziehen, oder der Spur eine "
        "Abhängigkeitsinstallation geben."
    )


def test_the_guard_really_runs_on_the_lane_it_was_built_for() -> None:
    """Ohne `run_pine_guard` im `if:` ist die ganze Übung wirkungslos.

    Der Schritt existiert genau deshalb, weil `tests/…_vocabulary.py` nur bei
    `run_heavy=true` läuft — also nie auf der Spur, auf der der Refresh fährt.
    Stünde hier eines Tages nur noch `run_heavy`, wäre die Lücke zurück und
    nichts würde es melden: der Schritt bliebe grün, weil er gar nicht liefe.
    Dieselbe Zusicherung hält `test_check_r1_attested_sources.py` für den
    R1-Wächter.
    """
    conditions = step_conditions()
    assert GUARD_STEP in conditions, (
        f"der Schritt {GUARD_STEP!r} steht nicht mehr in smc-fast-pr-gates.yml — "
        "die Bot-Spur prüft die Kundenoberflächen dann wieder gar nicht"
    )
    assert "run_pine_guard" in conditions[GUARD_STEP], (
        f"{GUARD_STEP!r} läuft nicht mehr auf der pine-Spur ({conditions[GUARD_STEP]!r}). "
        "Das ist exakt die Lücke, durch die #4646 und #4665 unbeobachtet mergten."
    )
    for installer in (
        "Set up pinned Python (GitHub-hosted)",
        "Resolve Python 3.12 interpreter",
        "Install dependencies",
    ):
        assert "run_pine_guard" not in conditions[installer], (
            f"{installer!r} läuft jetzt auch auf der pine-Spur. Damit ist die "
            "Stdlib-Bedingung oben nicht mehr tragend — entweder jenen Test "
            "mit dieser Änderung entfernen oder diesen."
        )


def test_every_surface_is_covered_by_all_bounds() -> None:
    """Über die GANZE Menge: keine Oberfläche ohne alle drei Untergrenzen."""
    assert set(PINE_FILES) == set(MIN_INPUTS) == set(MIN_GROUP_LABELS)
    assert set(PINE_FILES) == set(MIN_RENDERED)
    assert set(PINE_FILES) == set(INTERNAL_GROUP_VARS)


# ---------------------------------------------------------------------------
# Stolperdrähte für die zwei Consumer, die die Chart-Link-Vervollständigung
# (2026-08-28) NICHT erreichen durfte. Muster: test_hold_manager_wiring_rides_
# the_next_build — schlafen, solange der einfrierende Vertrag den Altstand
# pinnt; feuern, sobald sich die Quelle legitim bewegt, und dann das Rename
# samt Guard-Aufnahme in DERSELBEN PR verlangen.
# ---------------------------------------------------------------------------

_EXIT_SIGNAL_ATTESTED_SHA = (
    # R1-Evidenz smc_r1_live_rollout_evidence_2026-08-21T163804Z.json,
    # sources['SMC Exit Signal'].repositorySha256 — der Hash, den
    # scripts/check_r1_attested_sources.py gegen jede PR-Bewegung hält.
    "82136e25457f2d0cc9754b84a410f01f6b880b2500624001d297e4ced3b5076c"
)

_HOLD_MANAGER_BUILD3_SHA = (
    # artifacts/governance/smc_hold_manager_shadow_contract.json
    # source.sha256 @ build 3 — der Hash, den der deployte Shadow-Receiver
    # (payload.sourceBuild == contract.source.build) am Leben hält.
    "88d20484055c850f2a558434aa65b9429e60b9f17373c225d24a931325e82048"
)


def test_exit_signal_rename_rides_the_next_reattestation() -> None:
    """Schläft, solange die R1-Evidenz den Altstand pinnt; feuert danach.

    Feuer-Semantik: Die Re-Attestation-Session hat SMC_Exit_Signal.pine
    bewegt — nimm das Chart-Link-Rename in DERSELBEN PR mit: Gruppen-Labels
    '3./4. Chart Link - …', die gerenderte "BUS"-Tabellenzelle, den
    Registry-Eintrag EXIT_SIGNAL_GROUP_TITLES_BY_KEY und den Guard-Eintrag
    (INTERNAL_GROUP_VARS + Floors) für diese Datei.
    """
    import hashlib

    from tests.smc_manifest_test_utils import ROOT as REPO_ROOT

    source = (REPO_ROOT / "SMC_Exit_Signal.pine").read_text(encoding="utf-8")
    if hashlib.sha256(source.encode()).hexdigest() == _EXIT_SIGNAL_ATTESTED_SHA:
        assert "SMC_Exit_Signal.pine" not in PINE_FILES, (
            "die Datei ist R1-eingefroren — sie in die Guard-Population zu "
            "nehmen, macht den Guard rot, ohne dass jemand sie ändern darf"
        )
        return
    assert "SMC_Exit_Signal.pine" in PINE_FILES, (
        "SMC_Exit_Signal.pine hat sich von der attestierten Quelle bewegt: "
        "nimm das Chart-Link-Rename in dieser PR mit (Labels, 'BUS'-Zelle, "
        "Registry-Titel, Guard-Population + Floors) — oder pinne den neuen "
        "attestierten Hash hier mit datiertem Kommentar, wenn die Session "
        "das Rename ausdrücklich NICHT mitgenommen hat"
    )


def test_hold_manager_rename_rides_the_next_build() -> None:
    """Schläft, solange der Shadow-Vertrag Build 3 pinnt; feuert auf Build 4+.

    Feuer-Semantik: Die Hold-Manager-Spur hat einen neuen Build geprägt —
    nimm das Chart-Link-Rename in DERSELBEN PR mit: gBus-Label, deutsche
    Titel/Tooltips → Englisch, Status-Label-Strings ('Engine BUS v2',
    '\\nBUS: ', STALE_CONTEXT-Zeile), Registry-Eintrag
    HOLD_MANAGER_GROUP_TITLES_BY_KEY, Guard-Eintrag (INTERNAL_GROUP_VARS
    {'gBus'} + Floors) und den camelCase-Arm von _GROUP_DEF_RE.
    """
    import json

    from tests.smc_manifest_test_utils import ROOT as REPO_ROOT

    contract = json.loads(
        (
            REPO_ROOT / "artifacts" / "governance"
            / "smc_hold_manager_shadow_contract.json"
        ).read_text(encoding="utf-8")
    )
    if contract["source"]["sha256"] == _HOLD_MANAGER_BUILD3_SHA:
        assert "SMC_Hold_Manager.pine" not in PINE_FILES, (
            "die Spur ist auf Build 3 eingefroren — Population jetzt zu "
            "erweitern, macht den Guard rot, ohne dass jemand die Datei "
            "ändern darf"
        )
        return
    assert "SMC_Hold_Manager.pine" in PINE_FILES, (
        "die Hold-Manager-Spur hat einen neuen Build geprägt: nimm das "
        "Chart-Link-Rename in dieser PR mit (gBus-Label, Übersetzungen, "
        "Registry-Titel, Guard-Population + Floors, camelCase-Arm) — oder "
        "pinne den neuen Build-Hash hier mit datiertem Kommentar, wenn der "
        "Build das Rename ausdrücklich NICHT mitgenommen hat"
    )


# ---------------------------------------------------------------------------
# Rot-zuerst-Beweise der drei Blindstellen aus dem 10-Winkel-Review (2026-08-28).
# Jeder Fall wurde GEGEN DEN ALTEN WÄCHTER ausgeführt und schlug dort fehl
# (der alte Code akzeptierte die eingeschleuste Zeile); erst die Härtung im
# Skript macht ihn grün. Die Injektionen sind synthetisch, die Mechanik ist
# jeweils die des echten Live-Falls.
# ---------------------------------------------------------------------------


def test_tooltip_capture_survives_an_embedded_other_quote(monkeypatch) -> None:
    """Mechanik 1: Das JEWEILS ANDERE Anführungszeichen beendete den Capture.

    Die alte `_TOOLTIP_RE`-Zeichenklasse schloss BEIDE Quotezeichen aus, obwohl
    nur das äußere Delimiter das Ende bestimmt. Ein einfach-quotierter Tooltip,
    der ein "-Zitat enthält, wurde nach dem Kopf abgeschnitten — der Schwanz
    (hier: ein Repo-Pfad) shippte grün. Live-Fall: der Trend-Scaffold-Tooltip
    der Suite, 49 von 295 Zeichen geprüft.
    """
    import scripts.check_customer_surface_vocabulary as module

    unpatched = module.read_lines
    target = PINE_FILES[0]
    injected = [
        "x_qq = input.bool(false, 'Compact', group = g_surface, "
        "tooltip = 'Head quotes \"another input\" and only the tail cites "
        "docs/internal_plan.md')"
    ]

    def with_leak(pine_file: str) -> list[str]:
        lines = unpatched(pine_file)
        return lines + injected if pine_file == target else lines

    monkeypatch.setattr(module, "read_lines", with_leak)
    found, _ = module.input_leaks(target)
    assert any("x_qq" in entry and "repo path" in entry for entry in found), (
        "the tooltip capture still stops at an embedded quote of the other "
        f"type — the repo path in the tail went unseen: {found!r}"
    )
    assert module.main([]) == 1


def test_literal_escape_sequences_do_not_hide_the_word_boundary(monkeypatch) -> None:
    """Mechanik 2: Pines literales Zwei-Zeichen-`\\n` klebt vor dem Muster.

    In `'…contract.\\n\\nPlan 1.4: …'` steht vor dem P ein literales `n` —
    ein Wortzeichen, also feuert `\\bPlan` nie. Live-Fall: der
    `min_htf_alignment_count`-Tooltip der Suite.
    """
    import scripts.check_customer_surface_vocabulary as module

    unpatched = module.read_lines
    target = PINE_FILES[0]
    injected = [
        'x_nl = input.int(2, "Floor", group = g_surface, '
        'tooltip = "matches the contract.\\n\\nPlan 1.4: the preset raises it")'
    ]

    def with_leak(pine_file: str) -> list[str]:
        lines = unpatched(pine_file)
        return lines + injected if pine_file == target else lines

    monkeypatch.setattr(module, "read_lines", with_leak)
    found, _ = module.input_leaks(target)
    assert any(
        "x_nl" in entry and "internal plan reference" in entry for entry in found
    ), (
        "a literal \\n escape directly before the pattern still eats the "
        f"word boundary: {found!r}"
    )
    assert module.main([]) == 1


def test_title_capture_survives_an_embedded_other_quote(monkeypatch) -> None:
    """Mechanik 1b (2026-08-28): dieselbe Trunkierungsklasse traf auch TITEL.

    `_TITLE_RE` schloss BEIDE Quotezeichen aus, obwohl nur das äußere
    Delimiter das Ende bestimmt — ein doppelt-quotierter Titel, der ein
    '-Zitat enthält, wurde nach dem Kopf abgeschnitten und sein Schwanz
    shippte ungeprüft. In #5142 bewusst ausgelassen, hier geschlossen.
    """
    import scripts.check_customer_surface_vocabulary as module

    unpatched = module.read_lines
    target = PINE_FILES[0]
    injected = [
        'x_tq = input.bool(false, "Mirror the \'Compact\' toggle from '
        'scripts/render_plan.py", group = g_surface)'
    ]

    def with_leak(pine_file: str) -> list[str]:
        lines = unpatched(pine_file)
        return lines + injected if pine_file == target else lines

    monkeypatch.setattr(module, "read_lines", with_leak)
    found, _ = module.input_leaks(target)
    assert any("x_tq" in entry and "repo path" in entry for entry in found), (
        "the title capture still stops at an embedded quote of the other "
        f"type — the repo path in the tail went unseen: {found!r}"
    )
    assert module.main([]) == 1


def test_rendered_chart_strings_are_part_of_the_population(monkeypatch) -> None:
    """Mechanik 3: table.cell/label.new-Strings waren gar keine Population.

    Der Wächter las nur Input-Deklarationen und Gruppen-Labels — die Strings,
    die TradingView tatsächlich AUF DEN CHART malt (Tabellenzellen, Labels,
    auch mehrzeilig konkateniert), sah niemand. Live-Fälle: Mobile-Fallback
    „Add SMC Core Engine first", Dashboard-Versionswarnung, Hero-Tooltip.
    """
    import scripts.check_customer_surface_vocabulary as module

    unpatched = module.read_lines
    target = PINE_FILES[0]
    injected = [
        "if barstate.islast",
        '    table.cell(t, 0, 0, "Powered by the BUS Preset* contract")',
        "    label.new(bar_index, high,",
        '         "See pine/generated/fvg_context_health.json" +',
        '         " for the detail breakdown",',
        "         color = color.red)",
    ]

    def with_leak(pine_file: str) -> list[str]:
        lines = unpatched(pine_file)
        return lines + injected if pine_file == target else lines

    monkeypatch.setattr(module, "read_lines", with_leak)
    assert module.main([]) == 1
    found, rendered = module.rendered_string_leaks(target)
    assert any("BUS channel name" in entry for entry in found), found
    assert any("repo path" in entry for entry in found), (
        "the multi-line label.new concatenation was not joined into one "
        f"statement: {found!r}"
    )
    assert rendered >= module.MIN_RENDERED[target]
