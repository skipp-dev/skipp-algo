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
    # settings_never_attempted (2026-08-24, Coordinator-Fund am Live-Monitor):
    # "kein Fehlermarker gefunden" und "nie versucht" sind VERSCHIEDENE
    # Aussagen -- die zweite als bestandenen Beweis zu fuehren ist die
    # Leere-Beobachtung-Falle (dieselbe Klasse wie
    # tv_failure_evidence.nothing_failed / checkedConsumers:0). Diese Probe
    # muss VOR der PRUEFEN-Pruefung stehen: sie ist die POSITIVE
    # Voraussetzung fuer alles danach (inklusive PASS), nicht ein
    # Durchfall-Fall am Ende. GEMESSEN an Lauf 32745395799 (workflow_dispatch,
    # verify-/repair-only, save-Job-Log 89431 B): openSettingsForScript kommt
    # NULL Mal vor, die Klick-Operation lief also nie -- und wurde vor diesem
    # Fix trotzdem als "all_dialogs_opened"/PASS gemeldet. Ein Verify-Lauf
    # haette damit einen Klasse-H-Fix "bewiesen", den er nie angefasst hat.
    if "openSettingsForScript" not in log:
        return Verdict(
            "STEHT_AUS",
            branch="settings_never_attempted",
            detail="openSettingsForScript kommt im Log nicht vor -- die "
            "Operation wurde nie versucht, das ist kein bestandener Beweis",
        )
    # Ab hier ist "openSettingsForScript" im Log garantiert vorhanden (der
    # Zweig oben haette sonst schon zurueckgegeben) -- die Praesenzpruefung
    # unten ist damit tautologisch wahr, bleibt aber als eigener, benannter
    # Zweig stehen (Symmetrie zur Abwesenheitspruefung, AST-lesbares Label).
    # Diesselbe Symmetrie macht den PASS-Fall am Ende STRUKTURELL
    # unerreichbar: bei Abwesenheit greift settings_never_attempted, bei
    # Anwesenheit IMMER dialog_stuck_without_miss -- siehe die aktualisierte
    # [[unreachable_branch]]-Begruendung in proof_ledger.toml.
    if "openSettingsForScript" in log:
        return Verdict(
            "PRUEFEN",
            branch="dialog_stuck_without_miss",
            detail="Timeout, aber der Klick traf — Ursache liegt woanders",
        )
    return Verdict("PASS", branch="all_dialogs_opened", detail="keine Klick-Spur")
