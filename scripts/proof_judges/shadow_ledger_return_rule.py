#!/usr/bin/env python3
"""Urteiler: stempelt der taegliche Shadow-Lauf die Ertragsregel? (ADR-0031, Nachtrag 2026-10-02 II)

``scripts/run_magnitude_shadow_ledger.py`` haengt je Lauf eine Zeile pro
Familie an das Move-Size-Ledger. Seit dem 2026-10-02 traegt jede Zeile
``return_rule``, und das Wochen-Urteil zaehlt nur Zeilen der aktuellen Regel.
Das Skript ist suite-ausgefuehrt; nicht suite-sichtbar ist, ob der Workflow
``adr0023-magnitude-shadow-daily`` es im echten Lauf mit dem neuen Stand
ausfuehrt.

Der Zeuge ist die Zusammenfassung, die das Skript nach dem Anhaengen nach
stderr druckt. Seit der Aenderung nennt sie die Regel::

    shadow ledger artifacts/governance/magnitude_resolution_shadow.jsonl [next_open_then_horizon_close]: BOS(candidate): …

Vorher stand dort kein eckiger Block::

    shadow ledger artifacts/governance/magnitude_resolution_shadow.jsonl: BOS(candidate): …

Die Zeile steht in keinem run-Block: der Runner druckt den Aufruf
(``python scripts/run_magnitude_shadow_ledger.py …``), nicht dessen Ausgabe.
Gelesen wird nur die AUSGEGEBENE Zeile, verankert am Zeilenstempel des Runners.
"""

from __future__ import annotations

import re

from scripts.proof_judges import Verdict

_EXPECTED_RULE = "next_open_then_horizon_close"
#: Die ausgegebene Zusammenfassung MIT Regel. Der Zeitstempel des Runners steht
#: davor; ein run-Block-Echo traegt zwischen Stempel und Text die ANSI-Farbe.
_STAMPED = re.compile(r"^\S+Z shadow ledger \S+ \[(?P<rule>[a-z_]+)\]: ", re.MULTILINE)


def judge(evidence: dict, entry) -> Verdict:
    del entry  # die Versionsprobe ist der eckige Block selbst: vor dem Merge druckt ihn niemand
    log = str(evidence.get("log") or "")
    if not log:
        return Verdict(
            "KANN_NICHT_BEZEUGEN",
            branch="kein_log",
            detail="Job-Log leer oder nicht abrufbar",
        )

    rules = sorted({m.group("rule") for m in _STAMPED.finditer(log)})
    if not rules:
        return Verdict(
            "STEHT_AUS",
            branch="nicht_gestempelt",
            detail=(
                "keine Zusammenfassung mit Regel — der Lauf liegt vor dem Merge, "
                "oder er hat keine Zeile angehaengt (unveraenderter Feed, rc 5)"
            ),
        )

    if rules != [_EXPECTED_RULE]:
        return Verdict(
            "FAIL",
            branch="falsche_regel",
            detail=f"gestempelt: {rules}; erwartet: {_EXPECTED_RULE}",
        )

    return Verdict("PASS", branch="regel_gestempelt", detail=f"Zeilen tragen {_EXPECTED_RULE}")
