#!/usr/bin/env python3
"""Urteiler fuer #5682: rotiert tradingview-storage-refresh das Secret wieder?

Zeuge ist das Job-Log von ``tradingview-storage-refresh`` (Job ``refresh``).
Von 2026-09-08 an starb jeder Lauf in "Validate captured storage state" an
``/usr/bin/python: Argument list too long`` (exit 126); #5682 beschneidet den
Mitschnitt auf TradingViews Cookies und uebergibt ihn als Datei.

Versionsprobe ist die Zeile, die erst der neue Schritt druckt:
``Pruned storage state: cookies <n> -> <m>``. Gelesen werden AUSGABE-Zeilen
(Zeitstempel, Leerzeichen, Text) -- GitHub druckt beim Start eines Schritts
auch dessen Skript ins Log, und dort steht das ``echo`` der Erfolgsmeldung
woertlich. Ein Abgleich per Teilstring hielte schon den Start des
Schreibschritts fuer den Erfolg.
"""

from __future__ import annotations

import re

from scripts.proof_judges import Verdict

_PRUNED = re.compile(r"Z Pruned storage state: cookies \d+ -> \d+")
_REFUSED = re.compile(r"refusing to write an unusable session")
_WRITTEN = re.compile(r"Z TV_STORAGE_STATE secret updated successfully\.\s*$", re.MULTILINE)
_ERROR = re.compile(r"##\[error\](.*)")


def judge(evidence: dict, entry) -> Verdict:
    del entry  # Versionsprobe ist die Prune-Zeile selbst
    log = str(evidence.get("log") or "")
    if not log:
        return Verdict("KANN_NICHT_BEZEUGEN", branch="no_log", detail="Log leer")
    if _REFUSED.search(log):
        return Verdict(
            "FAIL",
            branch="prune_verweigert",
            detail="kein sessionid-Cookie nach dem Beschneiden -- Mitschnitt ohne TradingView-Sitzung, Secret unveraendert",
        )
    pruned = _PRUNED.search(log)
    if pruned is None:
        return Verdict(
            "STEHT_AUS",
            branch="kein_prune_lauf",
            detail="keine Prune-Zeile -- Lauf vor #5682, oder der Mitschnitt scheiterte vor dem Beschneiden",
        )
    after = log[pruned.end():]
    if _WRITTEN.search(after):
        return Verdict("PASS", branch="rotiert", detail=f"{pruned.group(0)[2:]}; Secret geschrieben")
    fehler = _ERROR.findall(after)
    if fehler:
        return Verdict(
            "FAIL",
            branch="nach_prune_gescheitert",
            detail=f"nach dem Beschneiden gescheitert: {fehler[0].strip()[:200]}",
        )
    return Verdict(
        "STEHT_AUS",
        branch="trockenlauf",
        detail="beschnitten und ohne Fehler, aber nicht geschrieben (dry_run) -- beweist den Weg, nicht die Rotation",
    )
