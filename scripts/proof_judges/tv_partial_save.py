#!/usr/bin/env python3
"""Urteiler fuer #5013 (Partial-Save) und #5025 (Layout-Waechter).

Liest AUSSCHLIESSLICH Artefaktinhalt, nie den Erfolgsstatus des Runner-Laufs
(dessen Feldname bewusst nicht wiederholt wird — ein Test in
``tests/test_proof_ledger.py`` pinnt seine Abwesenheit hier). Lauf
32620808573 endete rot und hat dabei exakt das Richtige getan —
``report.ok`` haengt an einem nicht leeren ``partiallyRepairedChartUrls``.
Wer den Runner-Status statt den Artefaktinhalt liest, fuehrt einen
bestandenen Beweis als Fehlschlag.
"""

from __future__ import annotations

from scripts.proof_judges import Verdict, has_path


def judge(evidence: dict, entry) -> Verdict:
    # Inhaltliche Versionsprobe zuerst: ohne das Feld lief aelterer Code, und
    # dann ist JEDES weitere Urteil eine Aussage ueber den falschen Baum.
    if entry.version_probe != "KEINE" and not has_path(evidence, entry.version_probe):
        return Verdict(
            "KANN_NICHT_BEZEUGEN",
            branch="pre_fix_code",
            detail=f"Artefakt ohne {entry.version_probe}",
        )

    mutations = evidence.get("mutations") or {}
    partial = set(mutations.get("partiallyRepairedChartUrls") or [])
    saved = set(mutations.get("savedChartUrls") or [])
    abandoned = set(mutations.get("abandonedChartUrls") or [])

    if partial and (partial & saved):
        return Verdict(
            "PASS",
            branch="partial_saved",
            detail=f"{len(partial)} Layout(s) unvollstaendig repariert UND gespeichert",
        )
    if partial:
        return Verdict(
            "PRUEFEN",
            branch="pruefen_partial_not_saved",
            detail=f"partiallyRepaired={sorted(partial)} nicht in savedChartUrls",
        )
    if not mutations.get("layoutSaveRequested"):
        # Die Bedingung mag vorgelegen haben — der Lauf ist nur nie so weit
        # gekommen. Das ist STEHT_AUS, nicht SCHLAFEND, und die beiden zu
        # verwechseln kostete am 23.8. dreizehn Stunden.
        return Verdict(
            "STEHT_AUS",
            branch="save_phase_never_reached",
            detail="layoutSaveRequested=false",
        )
    if abandoned:
        return Verdict(
            "PRUEFEN",
            branch="abandoned_after_fix",
            detail=f"abandoned={sorted(abandoned)} — nach #5013 nur noch per "
            "unbestaetigtem Save erreichbar",
        )
    return Verdict(
        "SCHLAFEND",
        branch="clean_run",
        detail="sauberer Durchlauf, der Zweig wurde nicht betreten",
    )
