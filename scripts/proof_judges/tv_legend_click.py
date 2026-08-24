#!/usr/bin/env python3
"""Urteiler fuer #5018 — liest das JOB-LOG, nicht das Artefakt.

Der Sondenzweig vom 2026-08-22 suchte ``hit-target-miss`` in
``bindings.failed[].error``. Diese Spur geht ins Log und steht dort nie; der
Zweig konnte nie feuern und druckte trotzdem einen Tag lang Urteile. Deshalb
traegt der Ledger-Eintrag ``evidence_source = "job_log"`` und dieser Urteiler
bekommt ``{"log": "<text>"}``, nicht den Artefakt-Snapshot.
"""

from __future__ import annotations

from scripts.proof_judges import Verdict


def judge(evidence: dict, entry) -> Verdict:
    del entry  # keine inhaltliche Versionsprobe moeglich, siehe Ledger
    log = str(evidence.get("log") or "")
    if not log:
        return Verdict("KANN_NICHT_BEZEUGEN", branch="no_log", detail="Log leer")
    if "-hit-target-miss" in log:
        return Verdict(
            "FAIL",
            branch="click_missed_its_row",
            detail="Klickpunkt lag ausserhalb der Zeile",
        )
    if "identity-mismatch" in log:
        return Verdict(
            "FAIL",
            branch="identity_mismatch",
            detail="es ging der falsche Dialog auf",
        )
    if "openSettingsForScript" in log:
        return Verdict(
            "PRUEFEN",
            branch="dialog_stuck_without_miss",
            detail="Timeout, aber der Klick traf — Ursache liegt woanders",
        )
    return Verdict("PASS", branch="all_dialogs_opened", detail="keine Klick-Spur")
