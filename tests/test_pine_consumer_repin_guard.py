"""Der Wächter gegen den Vorfall vom 2026-08-12 (PR #4646, Refresh-Lauf 1192).

Der Lauf hatte `main` beim Start ausgecheckt, lief einen Tag lang, und
committete die Kundenoberflächen am Ende vollständig aus diesem tagealten
Arbeitsbaum — auf einen frischen Elternteil. Damit stand alles, was inzwischen
gemergt war, im Commit als Rücknahme: das Operator-Vokabular, das #4639
59 Sekunden zuvor entfernt hatte, war wieder da. Gesehen hat es niemand, weil
`bot/*`-PRs die schweren Gates überspringen und automatisch mergen.

Geprüft wird deshalb nicht der Text, sondern die Zusage: **an einer
Kundenoberfläche ändert ein Bibliothekslauf die Pin-Zeile und sonst nichts.**
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.check_pine_consumer_repin import pin_only_violations

# Ein Consumer im Kleinen: Pin-Zeile plus eine Zeile, die dem Kunden angezeigt
# wird. Mehr braucht die Aussage nicht.
BASE = """//@version=6
indicator("SMC Long-Dip Dashboard", overlay = true)

import preuss_steffen/smc_micro_profiles_generated/220 as mp

var string g_bus_diag = "3. Chart Link - Context Signals"
"""


def _with(pin: str = "220", label: str = "3. Chart Link - Context Signals") -> str:
    return BASE.replace(
        "smc_micro_profiles_generated/220", f"smc_micro_profiles_generated/{pin}"
    ).replace("3. Chart Link - Context Signals", label)


def test_a_pure_repin_passes() -> None:
    """Der Normalfall muss durchgehen, sonst wird der Wächter abgeschaltet."""
    assert pin_only_violations(BASE, _with(pin="221"), expected_version="221") == []


def test_the_incident_is_caught() -> None:
    """Genau der Commit, der am 12.8. durchgerutscht ist.

    Pin von 220 auf 221 UND die Gruppenbezeichnung zurück auf den internen
    Namen — das ist die Signatur eines Laufs, der eine fremde Änderung
    überschreibt.
    """
    reverted = _with(pin="221", label="3. Operator Only - Diagnostic Support")
    violations = pin_only_violations(BASE, reverted, expected_version="221")
    assert violations, "der Wächter hätte den Vorfall durchgelassen"
    assert any("not the library pin" in violation for violation in violations)


def test_a_text_change_without_any_repin_is_caught() -> None:
    """Auch ohne Pin-Bump darf der Lauf den Text nicht anfassen."""
    violations = pin_only_violations(
        BASE, _with(label="3. Operator Only - Diagnostic Support"),
        expected_version="220",
    )
    assert any("not the library pin" in violation for violation in violations)


def test_a_removed_line_is_caught() -> None:
    """Ein Repin fügt keine Zeile hinzu und nimmt keine weg."""
    shortened = "\n".join(BASE.splitlines()[:-1]) + "\n"
    violations = pin_only_violations(BASE, shortened, expected_version="220")
    assert any("line count changed" in violation for violation in violations)


@pytest.mark.parametrize(
    ("new_pin", "expected", "needle"),
    [
        ("219", "221", "repinned to 219"),
        ("220", "221", "pin left at 220"),
    ],
    ids=["repinned-to-the-wrong-version", "not-repinned-at-all"],
)
def test_the_pin_must_land_on_the_requested_version(
    new_pin: str, expected: str, needle: str
) -> None:
    """Sonst bliebe ein Consumer still auf der alten Bibliothek zurück —
    genau der Fehler vom 2026-04-22, den der Schritt beheben sollte."""
    violations = pin_only_violations(
        BASE, _with(pin=new_pin), expected_version=expected
    )
    assert any(needle in violation for violation in violations)


def test_a_file_without_a_pin_is_not_silently_accepted() -> None:
    """Eine Datei ohne Import-Pin ist kein Consumer; sie stillschweigend
    durchzuwinken hieße, den Wächter über eine leere Menge laufen zu lassen."""
    plain = 'indicator("no imports here")\n'
    violations = pin_only_violations(plain, plain, expected_version="221")
    assert any("not a consumer" in violation for violation in violations)


def test_every_pinned_consumer_in_the_repository_passes_its_own_guard() -> None:
    """Über die GANZE Menge, nicht über ein Beispiel.

    Jede eingecheckte Kundenoberfläche mit einem Pin muss sich selbst gegenüber
    als unverändert ausweisen — sonst behauptet der Wächter etwas über eine
    Datei, auf die er gar nicht anwendbar ist.
    """
    root = Path(__file__).resolve().parents[1]
    consumers = [
        path
        for path in sorted(root.glob("*.pine"))
        if "smc_micro_profiles_generated/" in path.read_text(encoding="utf-8")
    ]
    assert consumers, "keine gepinnte Kundenoberfläche gefunden — Auswahl ist leer"
    for path in consumers:
        text = path.read_text(encoding="utf-8")
        version = text.split("smc_micro_profiles_generated/")[1].split()[0]
        assert pin_only_violations(text, text, expected_version=version) == [], path.name
