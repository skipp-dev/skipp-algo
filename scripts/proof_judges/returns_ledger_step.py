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

Dasselbe gilt fuer die beiden lauten Verweigerungen — nur in ihrer
ausgegebenen Form, siehe ``_REFUSALS``.
"""

from __future__ import annotations

import re

from scripts.proof_judges import Verdict

_PLANES = ("1D", "15m")
_LINE = re.compile(r"returns ledger (?P<plane>1D|15m): .*?ledger now (?P<rows>\d+)")
#: Die beiden Arten, wie der Schritt laut scheitert — in ihrer AUSGEGEBENEN Form.
#:
#: 2026-10-01, am ersten echten Lauf gemessen (36909606203, Job 110528686974):
#: die erste Fassung suchte den blossen Text ``the events pool is gone`` und
#: fand ihn im Skript-Echo — der Runner druckt den run-Block samt
#: ``echo "::error …::… the events pool is gone"`` in JEDES Log. Ein
#: fehlerfreier Lauf mit beiden Ledger-Zeilen wurde so als FAIL geurteilt.
#: Ausgegeben sieht die Zeile anders aus (``##[error]…``); die Regel-Verweigerung
#: druckt das Skript selbst nach stderr (``error: … holds rows under …``), sie
#: steht in keinem run-Block.
_REFUSALS = (
    re.compile(r"##\[error\]gates step reported produced=true but the events pool is gone"),
    re.compile(r"^.*error: \S+ holds rows under .* A ledger carries ONE trade definition", re.MULTILINE),
)


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
    refused = [m.group(0)[-120:] for m in (pattern.search(log) for pattern in _REFUSALS) if m]

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
