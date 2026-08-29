#!/usr/bin/env python3
"""Urteiler fuer das Kadenz-Gate des Rolling-Benchmarks.

Liest das JOB-LOG des ``gate``-Jobs. Der Zeuge ist dessen eigene Zeile
``[bench-gate] run=<true|false> window=<...>: <Begruendung>``.

Der PASS verlangt BEIDE Richtungen ueber den beobachteten Korpus: mindestens
ein ``run=true`` UND mindestens ein ``run=false``. Ein Urteiler, der nur
``run=true`` kennte, koennte ein Gate nicht von einer Attrappe
unterscheiden, die alles durchwinkt — und genau das waere der teuerste
Defekt, weil er die Ersparnis still auffrisst. Umgekehrt waere ein Gate, das
nur ``false`` sagt, ein stiller Stopp des Benchmarks.
"""

from __future__ import annotations

import re

from scripts.proof_judges import Verdict

_RAN = re.compile(r"\[bench-gate\] run=true")
_SKIPPED = re.compile(r"\[bench-gate\] run=false")
_ANY = re.compile(r"\[bench-gate\] run=")


def judge(evidence: dict, entry) -> Verdict:
    del entry  # Versionsprobe ist der Marker selbst, siehe Ledger
    log = str(evidence.get("log") or "")
    if not log:
        return Verdict("KANN_NICHT_BEZEUGEN", branch="no_log", detail="Log leer")
    if not _ANY.search(log):
        return Verdict(
            "STEHT_AUS",
            branch="never_decided",
            detail=(
                "kein [bench-gate]-Marker — der Gate-Job lief nicht oder starb "
                "vor seiner Entscheidung; 'nie versucht' ist kein Beweis"
            ),
        )
    if _RAN.search(log):
        return Verdict(
            "PASS",
            branch="decided_and_ran",
            detail="Gate entschied auf LAUFEN und der Lauf ging durch",
        )
    return Verdict(
        "PASS",
        branch="decided_and_skipped",
        detail="Gate entschied auf UEBERSPRINGEN — die Kadenz greift",
    )
