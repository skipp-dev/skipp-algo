#!/usr/bin/env python3
"""Urteiler fuer house-rules-watch: laeuft die Hausregel-Wache wirklich?

Zeuge ist das Job-Log von ``pine-release-notes-watch`` (Job ``watch``). Der
neue Step druckt ``[house-rules-watch] unchanged|changed|broken``; vor dem
Merge existiert keine dieser Spuren (Versionsprobe = der Tag selbst).

``changed``/``broken`` sind PRUEFEN, nicht FAIL: genau dafuer existiert die
Wache -- ein feuernder Draht ist Arbeit fuer den Operator (ADR-0034
neu bewerten), kein Defekt des Drahts.
"""

from __future__ import annotations

from scripts.proof_judges import Verdict

_TAG = "[house-rules-watch]"


def judge(evidence: dict, entry) -> Verdict:
    del entry  # Versionsprobe ist die Log-Spur selbst
    log = str(evidence.get("log") or "")
    if not log:
        return Verdict("KANN_NICHT_BEZEUGEN", branch="no_log", detail="Log leer")
    if _TAG not in log:
        return Verdict(
            "STEHT_AUS",
            branch="pre_fix_run",
            detail="keine house-rules-watch-Spur -- Lauf ohne den Step",
        )
    if f"{_TAG} unchanged" in log:
        return Verdict("PASS", branch="watched_and_stable", detail="Regel-Seite unveraendert beobachtet")
    return Verdict(
        "PRUEFEN",
        branch="rules_changed_or_broken",
        detail="Wache hat gefeuert (changed/broken) -- ADR-0034 neu bewerten",
    )
