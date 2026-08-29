#!/usr/bin/env python3
"""Urteiler über den Job-Log des Stillstands-Wächters (#5183).

Bewiesen werden soll das, woran diese Sonde scheitern KANN, ohne dass es
auffällt: dass sie überhaupt eine Flotte gesehen hat. Ein Lauf, der null
in-flight-Läufe zurückbekommt — leere API-Antwort, falsch gebaute Abfrage,
stillschweigend gefilterte Statuswerte — urteilt über eine leere Menge, findet
folgerichtig nichts und meldet Erfolg. Im Run-Status ist das von einer gesunden
Flotte nicht zu unterscheiden.

Der Zeuge ist deshalb die Zeile mit dem gemessenen Umfang, nicht das Urteil.
Ein Lauf, der 0 Läufe geprüft hat, ist KEIN Beweis für Ruhe — und genau diese
Verwechslung ist die teure (``skipp-empty-observation-poisons-baseline``).

Evidenz ist der Job-Log: die Sonde schreibt nach stdout, der Aufrufer teet in
die Step Summary. Die Zeilen tragen dort ein Präfix aus Job-Name, Step-Name und
Zeitstempel — die Muster unten sind deshalb bewusst NICHT auf ``^`` verankert
(#5181 kostete genau diese Lektion).
"""

from __future__ import annotations

import re
from typing import Any

from scripts.proof_judges import Verdict

#: "N Lauf/Laeufe in Arbeit geprueft (Budget: queued 60 min, in_progress 330 min)."
#: Existiert erst seit dieser Aenderung und ist damit zugleich die Versionsprobe.
_SCOPE_RE = re.compile(
    r"(?P<n>\d+)\s+Lauf/Laeufe in Arbeit geprueft\s*\(Budget:\s*queued\s+(?P<q>\d+)\s*min,"
    r"\s*in_progress\s+(?P<p>\d+)\s*min\)"
)

_QUIET = "Kein Lauf ueber seinem Budget"

#: Die Budgets, wie sie beim Bauen gemessen wurden. Von Hand notiert: ein
#: Urteiler, der seine Erwartung aus dem Prueflung zieht, ist mit jeder
#: Aenderung einverstanden.
_EXPECTED_QUEUED = 60
_EXPECTED_IN_PROGRESS = 330


def judge(evidence: Any, entry) -> Verdict:  # entry ist Teil des Urteiler-Vertrags
    log = ""
    if isinstance(evidence, dict):
        log = str(evidence.get("log") or "")
    elif isinstance(evidence, str):
        log = evidence

    if not log.strip():
        return Verdict(
            "FAIL",
            branch="log_empty",
            detail="kein Job-Log — ueber die Wirkung der Sonde sagt das nichts",
        )

    scope = _SCOPE_RE.search(log)
    if scope is None:
        return Verdict(
            "FAIL",
            branch="no_scope_line",
            detail=(
                "die Zeile mit dem gemessenen Umfang fehlt. Entweder lief die alte "
                "Fassung, oder die Sonde brach vor dem Bericht ab — in beiden "
                "Faellen ist ihre Wirkung nicht belegt"
            ),
        )

    geprueft = int(scope.group("n"))
    queued, in_progress = int(scope.group("q")), int(scope.group("p"))

    if (queued, in_progress) != (_EXPECTED_QUEUED, _EXPECTED_IN_PROGRESS):
        return Verdict(
            "FAIL",
            branch="budgets_drifted",
            detail=(
                f"Budgets im Lauf sind queued={queued}/in_progress={in_progress}, "
                f"erwartet {_EXPECTED_QUEUED}/{_EXPECTED_IN_PROGRESS}. Geaendert "
                "werden duerfen sie — dann gehoert dieser Urteiler in denselben "
                "Commit, sonst urteilt er ueber eine Sonde, die es nicht mehr gibt"
            ),
        )

    if geprueft == 0:
        return Verdict(
            "FAIL",
            branch="empty_fleet",
            detail=(
                "0 Laeufe geprueft. Das ist KEIN Beweis fuer Ruhe: eine leere "
                "Abfrage findet folgerichtig nichts und meldet Erfolg. Der Lauf "
                "beweist ueber die Sonde nichts"
            ),
        )

    ruhig = _QUIET in log
    return Verdict(
        "PASS",
        branch="fleet_measured",
        detail=(
            f"{geprueft} Lauf/Laeufe in Arbeit gegen die Budgets "
            f"{queued}/{in_progress} min gehalten; Urteil: "
            + ("keiner ueber Budget" if ruhig else "mindestens einer steht")
        ),
    )
