#!/usr/bin/env python3
"""Urteiler fuer #5674 (Producer-Refresh prueft den Quelltext jeder Chart-Instanz).

Behauptung: Ein Producer-Refresh meldet je Chart-Pane, welchen Quelltext die
angewandte Instanz rechnet, und der Bericht faellt durch, wenn eine davon nicht
der Repo-Stand ist. Anlass 2026-10-05: Lauf 37280173216 war gruen, und beide
Suite-Instanzen auf vWgAWyfC rechneten alten Code.

Liest AUSSCHLIESSLICH Artefaktinhalt, nie den Erfolgsstatus des Runner-Laufs.
"""

from __future__ import annotations

from scripts.proof_judges import Verdict, has_path


def judge(evidence: dict, entry) -> Verdict:
    refresh = evidence.get("producerRefresh") or {}
    if not refresh.get("requested"):
        return Verdict("STEHT_AUS", branch="not_a_refresh_run", detail="producerRefresh.requested=false")
    if entry.version_probe != "KEINE" and not has_path(evidence, entry.version_probe):
        return Verdict("KANN_NICHT_BEZEUGEN", branch="pre_fix_code", detail=f"Artefakt ohne {entry.version_probe}")

    applied = refresh.get("appliedInstances") or []
    stale = refresh.get("staleInstances") or []
    if not applied:
        return Verdict(
            "PRUEFEN",
            branch="no_instance_read",
            detail="Refresh lief, aber keine Instanz gelesen (Refresh vorher abgebrochen?)",
        )
    if stale and evidence.get("ok") is False:
        return Verdict(
            "PASS",
            branch="stale_detected_red",
            detail=f"{len(stale)} von {len(applied)} Instanz(en) veraltet und der Bericht ist durchgefallen",
        )
    if stale:
        return Verdict(
            "FAIL",
            branch="stale_but_green",
            detail=f"{len(stale)} veraltete Instanz(en), Bericht trotzdem ok",
        )
    return Verdict(
        "PASS",
        branch="all_current",
        detail=f"{len(applied)} Instanz(en) gelesen, alle auf dem Repo-Stand",
    )
