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

PASS heisst hier: die Zeile wurde AUSGEWERTET — gleich ob frisch, deklariert
alt oder rot. Welches der drei stimmt, ist der Befund des Monitors, nicht der
Beweis dieses PRs. FAIL ist der Fall, in dem die Zeile da ist und nichts
sieht: ``MISSING`` (das Muster findet im Checkout keine datierte Datei).
"""

from __future__ import annotations

import re

from scripts.proof_judges import Verdict

_ROW = re.compile(
    r"##\[(?:notice|warning|error)\]"
    r"product:docs/calibration/gates/track_record_gate_\*\.json: (?P<rest>.*)"
)


def judge(evidence: dict, entry) -> Verdict:
    del entry  # die Versionsprobe ist die Zeile selbst: vor dem Merge gibt es sie nicht
    log = str(evidence.get("log") or "")
    if not log:
        return Verdict(
            "KANN_NICHT_BEZEUGEN",
            branch="kein_log",
            detail="Job-Log leer oder nicht abrufbar",
        )

    row = _ROW.search(log)
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
