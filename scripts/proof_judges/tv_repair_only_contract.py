#!/usr/bin/env python3
"""Urteiler fuer #5025: haelt ``repair-only`` seinen Vertrag?

Er darf genau zwei Dinge — Bindungen reparieren und das Layout speichern — und
weder Quellen deployen noch Instanzen entfernen. Am 2026-08-23 (Lauf
32620808573) gemessen: sourceSavesCompleted 0, producerInstancesRemoved 0,
consumerInstancesRemoved 0.
"""

from __future__ import annotations

from scripts.proof_judges import Verdict, has_path


def judge(evidence: dict, entry) -> Verdict:
    if entry.version_probe != "KEINE" and not has_path(evidence, entry.version_probe):
        return Verdict(
            "KANN_NICHT_BEZEUGEN",
            branch="pre_fix_code",
            detail=f"Artefakt ohne {entry.version_probe}",
        )
    if evidence.get("executionMode") != "repair-only":
        return Verdict(
            "STEHT_AUS",
            branch="not_a_repair_run",
            detail=f"executionMode={evidence.get('executionMode')!r}",
        )
    mutations = evidence.get("mutations") or {}
    verletzt = {
        name: mutations.get(name)
        for name in (
            "sourceSavesCompleted",
            "producerInstancesRemoved",
            "consumerInstancesRemoved",
        )
        if mutations.get(name)
    }
    if verletzt:
        return Verdict(
            "FAIL",
            branch="contract_broken",
            detail=f"repair-only hat mutiert: {verletzt}",
        )
    return Verdict(
        "PASS",
        branch="contract_held",
        detail="nichts deployt, nichts zerlegt",
    )
