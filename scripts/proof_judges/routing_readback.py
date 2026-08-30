#!/usr/bin/env python3
"""Urteiler über den Publish-Lauf des Benachrichtigungs-Routings (#5204).

Bewiesen werden soll das, woran diese Änderung scheitern kann, ohne dass es
auffällt: dass die **Rücklese wirklich stattgefunden hat**.

Der Vorfall dahinter ist gemessen. Am 2026-08-30 waren beide Publish-Workflows
grün, und trotzdem kamen vier Routen-Felder (``group_by``, ``group_wait``,
``group_interval``, ``repeat_interval``) nie bei Grafana an — ``build_policy_body``
verwarf sie still. Ein Upsert, der nur sendet, kann das strukturell nicht
bemerken: er hat ja alles getan, was er kennt. Ein grüner Lauf war damit kein
Beleg für einen angekommenen Zustand, sondern nur für einen abgeschickten.

Deshalb urteilt dieser Judge NICHT über „war der Lauf grün" — das war er vorher
auch. Er urteilt über die Zeile, die es erst seit der Rücklese gibt, und über
die Zahl darin: eine Rücklese über **null** Routen wäre wieder nur ein
abgeschickter Zustand.
"""

from __future__ import annotations

import re
from typing import Any

from scripts.proof_judges import Verdict

#: "policy-readback: N Route(n) unveraendert angekommen" — existiert erst seit
#: dieser Änderung und ist damit zugleich die Versionsprobe. Bewusst NICHT auf
#: ``^`` verankert: im Job-Log trägt jede Zeile ein Präfix aus Job, Step und
#: Zeitstempel (#5181 kostete genau diese Lektion).
#: 2026-08-31 additiv erweitert: derselbe Urteiler bedient jetzt BEIDE
#: Grafana-Upserts. Die Zusicherung ist identisch — "die Ruecklese hat
#: stattgefunden und über wie viele Objekte" —, nur der Schreiber ist ein
#: anderer (`policy-readback:` aus dem Routing-Upsert seit #5204,
#: `rules-readback:` aus dem alert-rules-Upsert seit #5208). Ein zweiter
#: Urteiler waere ein Doppelgaenger derselben Regel gewesen.
_READBACK_RE = re.compile(
    r"(?:policy|rules)-readback:\s*(?P<n>\d+)\s*(?:Route|Regel)\(n\)\s*unveraendert"
)


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
            detail="kein Job-Log — über die Wirkung sagt das nichts",
        )

    treffer = _READBACK_RE.search(log)
    if treffer is None:
        return Verdict(
            "FAIL",
            branch="no_readback_line",
            detail=(
                "die Rücklese-Zeile fehlt. Entweder lief eine Fassung vor dieser "
                "Änderung, oder der Upsert brach vorher ab — in beiden Fällen ist "
                "ein grüner Lauf nur ein abgeschickter, kein angekommener Zustand"
            ),
        )

    routen = int(treffer.group("n"))
    if routen == 0:
        return Verdict(
            "FAIL",
            branch="readback_over_nothing",
            detail=(
                "Rücklese über 0 Routen. Das ist kein Beleg: eine leere Prüfung "
                "findet folgerichtig keine Abweichung und meldet Erfolg"
            ),
        )

    return Verdict(
        "PASS",
        branch="readback_confirmed",
        detail=f"{routen} Route(n) zurückgelesen und unverändert vorgefunden",
    )
