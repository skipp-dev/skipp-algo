#!/usr/bin/env python3
"""Urteiler: wartet die Re-Attestierung auf offene Refresh-PRs, bevor sie neu baut?

``tv-save-consumer-source`` im Re-Attest-Modus (Dispatch auf ``bot/r1-reattest*``)
baut seinen Vorschlag auf dem aktuellen main neu ("Rebuild the proposal on
current main"). ``smc-library-publish`` gibt die ``tradingview-session``-Sperre
frei, sobald es veroeffentlicht hat; sein Manifest-PR (``bot/library-refresh-*``)
merged erst Minuten spaeter. Ein wartender Re-Attest-Lauf bekam die Sperre genau
in diesem Fenster, baute auf dem alten main und das Rollout-Werkzeug verweigerte
mit "Library publish drift" -- 3 von 3 Re-Attest-Laeufen seit 18:00Z am
2026-10-06 (Korpus). Der neue Schritt "Await open library-refresh PRs before
rebuilding" wartet, bis keiner mehr offen ist.

Wie bei ``tv_save_awaits_refresh_pr`` liest der Urteiler nur AUSGEGEBENE Zeilen
(``##[notice]…``/``##[error]…`` und die aufgeloeste ``attested=/N published=/M``),
nie den vom Runner mitgedruckten Skripttext.
"""

from __future__ import annotations

import re

from scripts.proof_judges import Verdict

#: Ausgabe des neuen Schritts; existiert erst mit dem Fix.
_WAITED = "##[notice]No library-refresh PR is open"
#: Derselbe Schritt, Obergrenze erreicht.
_STUCK = re.compile(r"##\[error\]Library-refresh PR\(s\) [\d ]+ still open after \d+s")
#: Aufgeloeste Ausgabe des Rebuild-Schritts: nur Re-Attest-Laeufe drucken sie.
#: Gemessen an Job 112482410834 (Lauf 37508171373, 2026-10-06): "attested=/562 published=/566".
_REBUILT = re.compile(r"^\S+Z attested=/\d+ published=/\d+\s*$", re.MULTILINE)
#: Die Verweigerung des Rollout-Werkzeugs, als JSON-Zeile (derselbe Job).
_DRIFT_REFUSAL = '"error":"Library publish drift:'


def judge(evidence: dict, entry) -> Verdict:
    del entry
    log = str(evidence.get("log") or "")
    if not log:
        return Verdict("KANN_NICHT_BEZEUGEN", branch="kein_log", detail="Job-Log leer oder nicht abrufbar")

    stuck = _STUCK.search(log)
    if stuck:
        # Der Schritt hat gewartet; ein haengender Refresh-PR ist ein anderer Befund.
        return Verdict("PRUEFEN", branch="refresh_pr_haengt", detail=stuck.group(0).removeprefix("##[error]"))

    waited = _WAITED in log
    refused = _DRIFT_REFUSAL in log
    if waited and not refused:
        return Verdict("PASS", branch="gewartet_ohne_drift", detail="Re-Attest wartete auf Refresh-PRs und lief ohne Drift-Verweigerung")
    if waited and refused:
        return Verdict(
            "FAIL",
            branch="gewartet_trotzdem_drift",
            detail="gewartet, und derselbe Lauf verweigerte trotzdem mit Library publish drift",
        )
    if _REBUILT.search(log) and refused:
        return Verdict(
            "FAIL",
            branch="ohne_warten_neu_gebaut",
            detail="Re-Attest baute ohne Warte-Schritt neu und verweigerte mit Library publish drift (Code vor dem Fix)",
        )
    return Verdict(
        "STEHT_AUS",
        branch="kein_reattest_lauf",
        detail="kein Re-Attest-Lauf mit Drift-Signatur -- Zeitplan-, Ketten- oder Verify-Lauf",
    )
