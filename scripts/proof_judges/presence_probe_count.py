#!/usr/bin/env python3
"""Urteiler über die Präsenz-Sonde im meta-watchdog (#5218).

Bewiesen werden soll das, woran diese Änderung scheitern kann, ohne dass es
auffällt: dass die Präsenz-Überwachung ihren **Umfang überhaupt nennt**.

Der Vorfall dahinter ist gemessen. ``live_overlay_github_workflow_expected_present``
hatte am 2026-08-31 in sieben Tagen **null** Zeitreihen — die einzige Metrik von
193 ohne jedes Datum —, und die einzige Regel darauf ist die, die „ein
deklarierter Workflow läuft gar nicht mehr" erkennen soll. Sie ist fail-open
formuliert (``or on() vector(0)``), meldet ohne Metrik also 0 statt NoData.
Ihre Stille sah damit aus wie Gesundheit; nichts im ganzen Stack sagte, dass
diese Überwachung schlicht **aus** ist.

Deshalb urteilt dieser Judge NICHT über „war der Lauf grün" — das war er vorher
auch, und zwar genau deshalb. Er urteilt über die Zeile, die es erst seit dieser
Änderung gibt: den gemessenen Zählwert der Präsenz-Zeitreihen.

Drei Zweige, und der mittlere ist der wichtige:

* eine Zahl  → PASS. Die Sonde hat gezählt, egal ob 0 oder 40.
* ``UNGESICHERT`` → kein Urteil. Der Präsenz-Arm hat sein eigenes ``try`` und
  degradiert bei API-Fehlern zu dieser Zeile. Das ist ein KORREKTER Zustand;
  ihn als Fehlschlag zu werten hieße, einen Wächter zu bauen, der korrekte
  Zustände anklagt.
* gar keine Zeile → FAIL. Dann läuft die alte Fassung, und der ganze Punkt der
  Änderung fehlt.
"""

from __future__ import annotations

import re
from typing import Any

from scripts.proof_judges import Verdict

#: "Praesenz-Zeitreihen : N" — existiert erst seit dieser Änderung und ist damit
#: zugleich die Versionsprobe. Bewusst NICHT auf ``^`` verankert: im Job-Log
#: trägt jede Zeile ein Präfix aus Job, Step und Zeitstempel (#5181 kostete
#: genau diese Lektion).
_COUNT_RE = re.compile(r"Praesenz-Zeitreihen\s*:\s*(?P<n>\d+)")
_UNSURE_RE = re.compile(r"Praesenz-Zeitreihen\s*:\s*UNGESICHERT")


def judge(evidence: Any, entry) -> Verdict:  # entry ist Teil des Urteiler-Vertrags
    log = ""
    if isinstance(evidence, dict):
        log = str(evidence.get("log") or "")
    elif isinstance(evidence, str):
        log = evidence

    if not log.strip():
        return Verdict(
            state="FAIL",
            branch="no_log",
            detail="kein Job-Log — ohne Ausgabe ist nichts belegt",
        )

    if _UNSURE_RE.search(log):
        return Verdict(
            state="UNGESICHERT",
            branch="probe_degraded",
            detail=(
                "der Praesenz-Arm meldet UNGESICHERT — er hat sein eigenes try und "
                "degradiert bei API-Fehlern absichtlich so. Kein Fehlschlag, aber "
                "auch kein Beleg: der naechste Lauf urteilt erneut."
            ),
        )

    treffer = _COUNT_RE.search(log)
    if not treffer:
        return Verdict(
            state="FAIL",
            branch="marker_missing",
            detail=(
                "keine Zeile 'Praesenz-Zeitreihen : N' im Log. Dann laeuft die "
                "Fassung VOR #5218, und dass die Praesenz-Ueberwachung aus ist, "
                "bleibt weiterhin unsichtbar."
            ),
        )

    anzahl = int(treffer.group("n"))
    return Verdict(
        state="PASS",
        branch="counted",
        detail=(
            f"die Sonde nennt ihren Umfang: {anzahl} Praesenz-Zeitreihe(n). "
            + (
                "Null ist hier der ERWARTETE Stand, solange "
                "GITHUB_WORKFLOW_MONITOR_EXPECTED leer ist — bewiesen ist, dass "
                "dieser Zustand jetzt ausgesprochen wird statt still zu bleiben."
                if anzahl == 0
                else "Die Erwartungsliste ist gesetzt und die Sonde sieht sie."
            )
        ),
    )
