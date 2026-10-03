#!/usr/bin/env python3
"""Urteiler: fuehrt ``promotion-gate-daily`` die grobe Bilanz? (ADR-0031, Nachtrag 2026-10-03 IV)

Seit dem Nachtrag schreibt der Schritt ``ledger`` neben den beiden Ledgern des
Track Records ein drittes: BOS auf dem Korn der Pine-Engine
(``pivot_lookup`` 50, ``ledger/returns_ledger_15m_p50.jsonl``). Skript und
Schritt sind suite-ausgefuehrt; nicht suite-sichtbar ist, ob der Workflow den
Schritt im echten Lauf mit dem neuen Stand erreicht und ob der Benchmark
grobe Events in den Pool legt.

Der Zeuge ist die Zeile, die ``scripts/accumulate_returns_ledger.py`` fuer das
grobe Ledger nach getaner Arbeit druckt::

    returns ledger 15m [pivot_lookup=50]: pool 2371/13822 events on plane, 12 closed trades observed, …, ledger now 12 (BOS:12)

Vor der Aenderung druckte der Schritt nur ``returns ledger 1D:`` und
``returns ledger 15m:`` — ohne eckigen Block. Die Zeile steht in keinem
run-Block: der Runner druckt den Aufruf (``python -m
scripts.accumulate_returns_ledger …``), nicht dessen Ausgabe. Gelesen wird nur
die AUSGEGEBENE Zeile, verankert am Zeilenstempel des Runners.

``ledger now 0`` ist ein PASS: am ersten Lauf nach dem Merge kann der Pool
noch keine groben Events tragen (der Benchmark muss erst auf dem neuen Stand
laufen); die Bilanz ist eroeffnet, sobald die Zeile da ist. Die Verweigerung
(``error: … holds rows under … structure grain``) ist der FAIL — sie hiesse,
dass zwei Koerner in einer Datei lagen.
"""

from __future__ import annotations

import re

from scripts.proof_judges import Verdict

_COARSE_GRAIN = 50
#: Die ausgegebene Zeile des groben Ledgers, am Zeitstempel des Runners
#: verankert; ein run-Block-Echo traegt zwischen Stempel und Text die ANSI-Farbe.
_STAMPED = re.compile(
    r"^\S+Z returns ledger 15m \[pivot_lookup=(?P<grain>\d+)\]: .*?ledger now (?P<rows>\d+)",
    re.MULTILINE,
)
#: Die Verweigerung des Ledger-Produzenten, in ihrer ausgegebenen Form.
_REFUSED = re.compile(r"^\S+Z error: \S+ holds rows under .* A ledger carries ONE trade definition", re.MULTILINE)


def judge(evidence: dict, entry) -> Verdict:
    del entry  # die Versionsprobe ist der eckige Block selbst: vor dem Merge druckt ihn niemand
    log = str(evidence.get("log") or "")
    if not log:
        return Verdict(
            "KANN_NICHT_BEZEUGEN",
            branch="kein_log",
            detail="Job-Log leer oder nicht abrufbar",
        )

    refused = _REFUSED.search(log)
    if refused:
        return Verdict("FAIL", branch="verweigert", detail=refused.group(0)[-160:])

    coarse = [int(m.group("rows")) for m in _STAMPED.finditer(log) if int(m.group("grain")) == _COARSE_GRAIN]
    if not coarse:
        return Verdict(
            "STEHT_AUS",
            branch="nicht_gestempelt",
            detail=(
                "keine Zeile 'returns ledger 15m [pivot_lookup=50]' — der Lauf liegt vor "
                "dem Merge, oder das Gate hat nichts produziert und der Schritt wurde uebersprungen"
            ),
        )

    return Verdict("PASS", branch="korn_geschrieben", detail=f"grobes Ledger: {coarse[-1]} Zeilen")
