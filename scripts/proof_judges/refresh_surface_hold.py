#!/usr/bin/env python3
"""Urteiler fuer den Customer-Surface-Hold im Refresh-Publish (refresh-surface-hold).

Liest das JOB-LOG des ``publish``-Jobs von ``smc-library-publish.yml``.
Der Zeuge ist der Output des Steps "Hold customer surfaces unless the change
is pin-only" (``scripts/hold_customer_surfaces.py``): entweder die Nulllesung
``No customer surface held (N checked).`` oder mindestens eine aktive
Rueckhaltung ``held at current-main content: ...``.

Dieser Urteiler existiert wegen Lauf 33150273077 (2026-08-28): das YAML wird
bei Run-Erstellung von main gepinnt, der publish-Job checkt aber
``steps.source_tree.outputs.ref`` aus — Stunden aelter. Der Step starb dort
mit ``No module named scripts.hold_customer_surfaces`` NACH dem TV-Publish
und VOR dem Manifest-Commit; das Manifest blieb eine Version hinter
TradingView haengen und jeder tv-save-Lauf starb fail-closed am
Library-Drift. Die Signatur wird deshalb explizit als FAIL geurteilt, nicht
als "nie gelaufen".

Ein Log ohne alle drei Spuren heisst "nie gelaufen", nicht "bestanden" — die
leere Beobachtung ist kein Befund: ein Lauf kann vor dem Step sterben
(fehlende TV-Auth, Preflight), und der wuerde sonst als Beweis eines Holds
gelesen, den er nie angefasst hat.
"""

from __future__ import annotations

import re

from scripts.proof_judges import Verdict

#: Aktive Rueckhaltung — druckt scripts/hold_customer_surfaces.py genau dann,
#: wenn eine Oberflaeche auf den frisch gefetchten main-Stand zurueckgesetzt
#: wurde.
_ACTIVE_HOLD = re.compile(r"held at current-main content: ")

#: Nulllesung MIT gezaehlter Population — nie ohne Zahl, damit "lief ueber
#: nichts" nicht wie "lief sauber" aussieht.
_NULL_READING = re.compile(r"No customer surface held \((\d+) checked\)\.")

#: Die 33150273077-Signatur: YAML kennt den Step, der gepinnte Checkout das
#: Modul nicht. Der Fix fuellt die Namespace-Luecke aus FETCH_HEAD; taucht
#: die Zeile wieder auf, ist die Naht gerissen.
_MODULE_MISSING = re.compile(r"No module named ['\"]?scripts\.hold_customer_surfaces")


def judge(evidence: dict, entry) -> Verdict:
    del entry  # Versionsprobe ist der Step-Output selbst, siehe Ledger
    log = str(evidence.get("log") or "")
    if not log:
        return Verdict("KANN_NICHT_BEZEUGEN", branch="no_log", detail="Log leer")
    if _MODULE_MISSING.search(log):
        return Verdict(
            "FAIL",
            branch="module_missing_regression",
            detail=(
                "der gepinnte Checkout kennt das Hold-Modul nicht und die "
                "FETCH_HEAD-Namespace-Fuellung hat nicht gegriffen (Klasse "
                "Lauf 33150273077: Publish ohne Manifest-Commit strandet "
                "das Manifest hinter TradingView)"
            ),
        )
    if _ACTIVE_HOLD.search(log):
        return Verdict(
            "PASS",
            branch="held_a_stale_surface",
            detail="der Hold hat eine Oberflaeche aktiv auf den main-Stand zurueckgehalten",
        )
    null_reading = _NULL_READING.search(log)
    if null_reading:
        return Verdict(
            "PASS",
            branch="clean_full_check",
            detail=(
                f"{null_reading.group(1)} Kundenoberflaechen gegen frisches "
                "main geprueft, nichts zu halten"
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
