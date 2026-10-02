#!/usr/bin/env python3
"""Urteiler fuer #5586 — wertet der Frische-Monitor seine PRODUKT-Zeile aus?

#5586 gibt ``workflow-freshness-monitor`` eine Zeile, die nicht die Farbe eines
Laufs prueft, sondern das Alter des juengsten datierten Gate-Berichts im
Checkout (``docs/calibration/gates/track_record_gate_*.json``). Die Regel
selbst ist suite-ausfuehrbar; nicht suite-sichtbar ist, ob der Workflow die
Zeile wirklich traegt, ob das Muster im Checkout des Monitors (``fetch-depth:
1`` auf main) Dateien findet und ob die Annotation sie ausgibt.

Der Zeuge ist das Job-Log der Sonde. Gelesen wird die AUSGEGEBENE Annotation
(``##[notice|warning|error]product:<Muster>: …``). Der run-Block, den der
Runner in jedes Log druckt, nennt die Zeile als ``--product "docs/…"`` — ohne
das Praefix ``product:``; das Echo kann den Zeugen also nicht vortaeuschen.

Seit dem 2026-10-02 prueft die Zeile ``returns_series_*.json`` statt
``track_record_gate_*.json``: unter der neuen Ertragsregel (ADR-0031, Nachtrag
2026-10-02 II) entsteht an einem Tag ohne Trades kein Gate-Urteil, die Serie
aber immer — der Bericht, dessen Ausbleiben die Zeile melden soll, ist die
Serie. Welche der beiden Zeilen ein Eintrag bezeugt, sagt seine
``version_probe``; eine Zeile des anderen Musters ist fuer ihn kein Zeuge.

PASS heisst hier: die Zeile wurde AUSGEWERTET — gleich ob frisch, deklariert
alt oder rot. Welches der drei stimmt, ist der Befund des Monitors, nicht der
Beweis dieses PRs. FAIL ist der Fall, in dem die Zeile da ist und nichts
sieht: ``MISSING`` (das Muster findet im Checkout keine datierte Datei).
"""

from __future__ import annotations

import re

from scripts.proof_judges import Verdict

#: Die Produkte, die die Zeile bisher geprueft hat, in der Reihenfolge ihres Einsatzes.
_PRODUCTS = ("track_record_gate", "returns_series")


def _row_pattern(entry) -> re.Pattern[str]:
    """Die ausgegebene Annotation fuer das Produkt, das ``entry`` bezeugt.

    #5586 (``version_probe`` nennt ``track_record_gate_``) ist die Zeile in
    ihrer ersten Form und zugleich der Rueckfall fuer Eintraege ohne Probe.
    """
    probe = str(getattr(entry, "version_probe", "") or "")
    product = next((name for name in _PRODUCTS if f"gates/{name}_" in probe), _PRODUCTS[0])
    return re.compile(
        r"##\[(?:notice|warning|error)\]"
        rf"product:docs/calibration/gates/{product}_\*\.json: (?P<rest>.*)"
    )


def judge(evidence: dict, entry) -> Verdict:
    log = str(evidence.get("log") or "")
    if not log:
        return Verdict(
            "KANN_NICHT_BEZEUGEN",
            branch="kein_log",
            detail="Job-Log leer oder nicht abrufbar",
        )

    row = _row_pattern(entry).search(log)
    if row is None:
        return Verdict(
            "STEHT_AUS",
            branch="zeile_fehlt",
            detail=(
                "keine ausgegebene product:-Annotation — die Sonde lief ohne die "
                "Zeile (Lauf vor dem Merge) oder starb vor dem Annotieren"
            ),
        )

    rest = row.group("rest").strip()
    if rest.startswith("MISSING") or rest.startswith("api_error"):
        return Verdict(
            "FAIL",
            branch="muster_findet_nichts",
            detail=f"Zeile vorhanden, aber blind: {rest}",
        )

    return Verdict(
        "PASS",
        branch="zeile_ausgewertet",
        detail=f"Produkt-Zeile ausgewertet: {rest}",
    )
