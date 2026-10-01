#!/usr/bin/env python3
"""Urteiler fuer den Ledger-Schritt von ``promotion-gate-daily`` (ADR-0031, Nachtrag 2026-10-01).

Der Schritt ``ledger`` rechnet die 15m-Beobachtungsserie und haengt je Ebene
die neu abgeschlossenen Trades an ein committetes Ledger an. Skript und
Schritt sind suite-ausfuehrbar (der Schritt wird mit den echten Producern
ausgefuehrt, nicht gestubbt). Nicht suite-sichtbar ist, ob er im echten Lauf
ueberhaupt erreicht wird — er haengt an ``steps.gates.outputs.produced ==
'true'``, und das Gate hat seit dem 31.8. in 17 von 18 Laeufen nichts
produziert.

Der Zeuge ist die Zeile, die ``scripts/accumulate_returns_ledger.py`` je Ebene
nach getaner Arbeit druckt::

    returns ledger 15m: pool 740/6245 events on plane, 551 closed trades observed, …, ledger now 551 (…)

Sie steht nur im Log, wenn das Skript durchlief. Der run-Block, den der Runner
in jedes Log druckt, enthaelt sie nicht (dort steht der Modulname
``scripts.accumulate_returns_ledger`` und der Dateiname mit Unterstrich).
"""

from __future__ import annotations

import re

from scripts.proof_judges import Verdict

_PLANES = ("1D", "15m")
_LINE = re.compile(r"returns ledger (?P<plane>1D|15m): .*?ledger now (?P<rows>\d+)")
#: Die beiden Arten, wie der Schritt laut scheitert (siehe Workflow und Skript).
_REFUSALS = ("A ledger carries ONE trade definition", "the events pool is gone")


def judge(evidence: dict, entry) -> Verdict:
    del entry  # die Versionsprobe ist die Zeile selbst: vor dem Merge druckt sie niemand
    log = str(evidence.get("log") or "")
    if not log:
        return Verdict(
            "KANN_NICHT_BEZEUGEN",
            branch="kein_log",
            detail="Job-Log leer oder nicht abrufbar",
        )

    rows = {m.group("plane"): int(m.group("rows")) for m in _LINE.finditer(log)}
    refused = [text for text in _REFUSALS if text in log]

    if not rows and not refused:
        return Verdict(
            "STEHT_AUS",
            branch="schritt_lief_nicht",
            detail=(
                "keine 'returns ledger'-Zeile — der Lauf liegt vor dem Merge, oder "
                "das Gate hat nichts produziert und der Schritt wurde uebersprungen"
            ),
        )

    if refused or set(rows) != set(_PLANES):
        return Verdict(
            "FAIL",
            branch="ledger_unvollstaendig",
            detail=f"Ebenen mit Ledger-Zeile: {sorted(rows)}; Verweigerungen: {refused}",
        )

    return Verdict(
        "PASS",
        branch="ledger_geschrieben",
        detail="; ".join(f"{plane}: {rows[plane]} Zeilen" for plane in _PLANES),
    )
