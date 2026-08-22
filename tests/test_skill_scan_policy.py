"""Kopplungs-Wächter für ``configs/skill_scan_policy.yaml``.

Der Cisco AI Security Scanner mischt eine Teil-Policy **nicht** in sein Preset:
eine Liste, die in der Policy-Datei auftaucht, ERSETZT die Preset-Liste. Gemessen
am 2026-08-22 gegen ``skill_scanner.core.scan_policy.ScanPolicy`` (Extension
``cisco-ai.cisco-ai-security-scanner`` 1.0.6, Paketversion 2.0.9)::

    skip_in_docs mit 1 Eintrag geschrieben  ->  Policy hat 1 Eintrag,
                                                nicht 14 + 1.

Das ist die gefährliche Richtung: der Scan wird dadurch **grüner und blinder
zugleich**, und beides sieht in der Oberfläche identisch aus. Dieser Test hält
die 14 Preset-Einträge und die zwei bewussten Ergänzungen zusammen und verlangt
für jede global abgeschaltete Regel eine Begründung in der Datei selbst.

Grenze, ausdrücklich: die Grundlinie unten ist eine **gepinnte Kopie** des
``balanced``-Presets zum Stand 2026-08-22. Ein Test in CI kann sie nicht gegen
das Original prüfen — der Scanner ist ein VS-Code-Extension-Paket und in CI nicht
installiert. Erweitert Cisco das Preset in einer neuen Version, bleibt dieser
Test grün, während unsere Datei den neuen Eintrag wegersetzt: UNGESICHERT.
Auf einer Maschine MIT installiertem Scanner schließt ``test_baseline_matches_
installed_preset`` genau diese Lücke; dort wird die Policy auch bearbeitet.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
POLICY_PATH = REPO / "configs" / "skill_scan_policy.yaml"

# Gepinnte Kopie von ScanPolicy.from_preset("balanced").rule_scoping.skip_in_docs
# (skill-scanner 2.0.9, gemessen 2026-08-22). Siehe Docstring zur Grenze.
BALANCED_SKIP_IN_DOCS = frozenset(
    {
        "COMMAND_INJECTION_JS_CHILD_PROCESS",
        "COMMAND_INJECTION_JS_FUNCTION_CONSTRUCTOR",
        "DATA_EXFIL_JS_FS_ACCESS",
        "DATA_EXFIL_JS_NETWORK",
        "FIND_EXEC_PATTERN",
        "GLOB_HIDDEN_FILE_TARGETING",
        "PROMPT_INJECTION_IGNORE_INSTRUCTIONS",
        "SECRET_CONNECTION_STRING",
        "TOOL_ABUSE_SYSTEM_MODIFICATION",
        "code_execution_generic",
        "command_injection_generic",
        "credential_harvesting_generic",
        "script_injection_generic",
        "system_manipulation_generic",
    }
)

# Bewusst LEER. Jede Ergänzung hier ist eine Regel, die in Doku-Pfaden nicht mehr
# feuert — und sie wirkt nur für Regeln des *static*-Analyzers. Für Regeln aus dem
# behavioral analyzer (u. a. MDBLOCK_*) ist ein Eintrag hier folgenlos; gemessen
# 2026-08-22. Siehe den Kommentarblock in configs/skill_scan_policy.yaml.
DELIBERATE_DOC_SCOPED: frozenset[str] = frozenset()


@pytest.fixture(scope="module")
def policy() -> dict:
    return yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))


def test_policy_file_exists_and_declares_its_base(policy: dict) -> None:
    """Ohne ``preset_base`` erbt die Policy nichts und wird stillschweigend leer."""
    assert policy["preset_base"] == "balanced"
    assert policy["policy_name"] == "skipp-algo"


def test_skip_in_docs_keeps_every_preset_entry(policy: dict) -> None:
    """Der eigentliche Wächter: Ersetzen darf nie zum Verlieren werden."""
    configured = set(policy["rule_scoping"]["skip_in_docs"])
    missing = BALANCED_SKIP_IN_DOCS - configured
    assert not missing, (
        "skip_in_docs ERSETZT die Preset-Liste, es ergänzt sie nicht. "
        f"Diese Preset-Einträge fehlen und wären damit wieder scharf gestellt: {sorted(missing)}"
    )


def test_skip_in_docs_holds_nothing_undocumented(policy: dict) -> None:
    """Die andere Richtung: jeder Eintrag über dem Preset ist eine Entscheidung.

    Wer hier etwas hinzufügt, muss es in ``DELIBERATE_DOC_SCOPED`` eintragen —
    und dabei prüfen, ob die Regel überhaupt aus dem *static*-Analyzer stammt,
    sonst ist der Eintrag folgenlos.
    """
    configured = set(policy["rule_scoping"]["skip_in_docs"])
    unexplained = configured - BALANCED_SKIP_IN_DOCS - DELIBERATE_DOC_SCOPED
    assert not unexplained, f"Nicht dokumentierte Doku-Ausnahmen: {sorted(unexplained)}"


def test_every_disabled_rule_carries_a_written_reason() -> None:
    """Ein Mute ohne Begründung in der Datei ist ein Mute, den niemand zurücknehmen kann."""
    text = POLICY_PATH.read_text(encoding="utf-8")
    body = text.split("disabled_rules:", 1)
    assert len(body) == 2, "configs/skill_scan_policy.yaml hat keinen disabled_rules-Block"

    for line_no, line in enumerate(body[1].splitlines()):
        entry = re.match(r"\s*-\s*(\S+)", line)
        if not entry:
            continue
        preceding = [ln.strip() for ln in body[1].splitlines()[:line_no] if ln.strip()]
        assert preceding and preceding[-1].startswith("#"), (
            f"Regel {entry.group(1)!r} ist abgeschaltet, ohne dass unmittelbar darüber "
            "ein Kommentar den Grund nennt."
        )


def test_baseline_matches_installed_preset() -> None:
    """Schließt die UNGESICHERT-Lücke dort, wo der Scanner installiert ist.

    In CI ist er das nicht — dann prüft dieser Test nichts, und die drei Tests
    oben tragen die Last. Kein ``pytest.skip``: der Test soll nicht als
    übersprungen gezählt werden, er hat auf dieser Maschine schlicht keine
    zweite Quelle.
    """
    try:
        from skill_scanner.core.scan_policy import ScanPolicy  # type: ignore[import-not-found]
    except ImportError:
        return

    installed = set(ScanPolicy.from_preset("balanced").rule_scoping.skip_in_docs)
    assert installed == set(BALANCED_SKIP_IN_DOCS), (
        "Das installierte balanced-Preset weicht von der gepinnten Grundlinie ab. "
        f"Neu: {sorted(installed - set(BALANCED_SKIP_IN_DOCS))} · "
        f"Entfallen: {sorted(set(BALANCED_SKIP_IN_DOCS) - installed)}. "
        "configs/skill_scan_policy.yaml und BALANCED_SKIP_IN_DOCS zusammen nachziehen."
    )
