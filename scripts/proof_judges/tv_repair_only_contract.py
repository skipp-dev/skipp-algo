#!/usr/bin/env python3
"""Urteiler fuer #5025: haelt ``repair-only`` seinen Vertrag?

Er darf genau zwei Dinge — Bindungen reparieren und das Layout speichern — und
weder Quellen deployen noch Instanzen entfernen. Am 2026-08-23 (Lauf
32620808573) gemessen: sourceSavesCompleted 0, producerInstancesRemoved 0,
consumerInstancesRemoved 0.

2026-10-01: bis dahin pruefte dieser Urteiler NUR die Verbots-Haelfte ("nichts
deployt, nichts zerlegt"). Die Gebots-Haelfte der Behauptung -- "repariert UND
SPEICHERT" -- las er nicht. TradingView baute Ende August den Speicherknopf um;
32 repair-/write-Laeufe in Folge reparierten ihre Bindungen, scheiterten am
Layout-Save und galten hier als ``PASS/contract_held`` (Korpus 35590264660).
Einen Monat lang standen 108 Bindungen auf ``Close``, ohne dass der Monitor
einen Widerspruch sah. Seither:

* repariert, aber nicht gespeichert  -> FAIL (die Reparatur ueberlebt das
  naechste Laden nicht -- das ist der Schaden, nicht ein Schoenheitsfehler);
* nichts repariert                  -> STEHT_AUS (ein Lauf, der nichts tat,
  bezeugt "repariert und speichert" nicht; Korpus 36820265832 erreichte den
  Browser nie).
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
    repaired = mutations.get("bindingsRepaired") or 0
    if not repaired:
        return Verdict(
            "STEHT_AUS",
            branch="nothing_repaired",
            detail="bindingsRepaired=0 — der Lauf bezeugt weder Reparatur noch Save",
        )
    if not mutations.get("layoutSaved"):
        return Verdict(
            "FAIL",
            branch="repaired_not_saved",
            detail=(
                f"{repaired} Bindungen repariert, layoutSaved="
                f"{mutations.get('layoutSaved')!r}, abandonedChartUrls="
                f"{mutations.get('abandonedChartUrls')!r} — die Reparatur ist nicht persistiert"
            ),
        )
    return Verdict(
        "PASS",
        branch="contract_held",
        detail=f"{repaired} Bindungen repariert und gespeichert; nichts deployt, nichts zerlegt",
    )
