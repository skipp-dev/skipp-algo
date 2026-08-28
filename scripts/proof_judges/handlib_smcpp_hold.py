#!/usr/bin/env python3
"""Urteiler fuer den SMC++-Quellen-Hold im handlibs-Publish (smcpp-source-hold).

Liest das JOB-LOG des ``publish``-Jobs von ``pine-library-publish-handlibs.yml``.
Der Zeuge ist der Output des Steps "Hold SMC++ library sources unless the
change is pin-only" (``scripts/hold_smcpp_sources.py``): entweder die
Nulllesung ``No SMC++ source held (N checked).`` — der Hold LIEF ueber die
volle Population, es gab nichts zurueckzuhalten — oder mindestens eine aktive
Rueckhaltung ``held at current-main content: SMC++/...``. Die Untergrenze der
Population prueft das Modul selbst fail-closed (``hand_lib_sources`` bricht
unter dem Floor ab und der Step wird rot); dieser Urteiler zaehlt sie nicht
nach, denn eine zweite Kopie der Zahl waere genau die Drift-Klasse, gegen die
der Floor steht.

Ein Log ohne beide Spuren heisst "nie gelaufen", nicht "bestanden" — die
leere Beobachtung ist kein Befund (dieselbe Klasse wie
``tv_legend_click.settings_never_attempted``): ein Lauf kann vor dem Step
sterben (fehlende TV-Auth beendet den Job frueher), und der wuerde sonst als
Beweis eines Holds gelesen, den er nie angefasst hat.
"""

from __future__ import annotations

import re

from scripts.proof_judges import Verdict

#: Aktive Rueckhaltung — die Zeile druckt scripts/hold_smcpp_sources.py
#: (ueber scripts.hold_customer_surfaces.hold) genau dann, wenn eine Quelle
#: auf den frisch gefetchten main-Stand zurueckgesetzt wurde.
_ACTIVE_HOLD = re.compile(r"held at current-main content: SMC\+\+/")

#: Nulllesung MIT gezaehlter Population — nie ohne Zahl, damit "lief ueber
#: nichts" nicht wie "lief sauber" aussieht.
_NULL_READING = re.compile(r"No SMC\+\+ source held \((\d+) checked\)\.")


def judge(evidence: dict, entry) -> Verdict:
    del entry  # Versionsprobe ist der Step-Output selbst, siehe Ledger
    log = str(evidence.get("log") or "")
    if not log:
        return Verdict("KANN_NICHT_BEZEUGEN", branch="no_log", detail="Log leer")
    if _ACTIVE_HOLD.search(log):
        return Verdict(
            "PASS",
            branch="held_a_stale_source",
            detail="der Hold hat eine Quelle aktiv auf den main-Stand zurueckgehalten",
        )
    null_reading = _NULL_READING.search(log)
    if null_reading:
        return Verdict(
            "PASS",
            branch="clean_full_check",
            detail=(
                f"{null_reading.group(1)} SMC++-Quellen gegen frisches main "
                "geprueft, nichts zu halten"
            ),
        )
    return Verdict(
        "STEHT_AUS",
        branch="hold_never_ran",
        detail=(
            "keine Hold-Spur im Log — der Step lief nie (Lauf vor dem Step "
            "gestorben oder Verdrahtung tot); 'nie versucht' ist kein Beweis"
        ),
    )
