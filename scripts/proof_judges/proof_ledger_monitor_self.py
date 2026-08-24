#!/usr/bin/env python3
"""Urteiler ueber den eigenen Report von ``scripts/judge_proof_ledger.py``.

Der Monitor ist selbst beweispflichtig (jede Workflow-Datei ist es
unbedingt, ``scripts/proof_class.py``). Was hier bewiesen werden kann, ist
schmal und bewusst so gehalten: nicht "urteilt der Monitor RICHTIG ueber ein
einzelnes TV-Artefakt" (das pruefen die judge-spezifischen Urteiler und ihr
eigener Korpus), sondern die EINE Zusicherung, die Task 7 explizit verlangt
und die sonst nirgends automatisiert nachgehalten wird: eine uebersprungene
Pruefung (``evidence_source != "artifact"``) darf im Report nie wie ein
erfolgloser Zeugensuchversuch (``KEIN_ZEUGE``) aussehen. Evidenz ist die vom
Monitor selbst geschriebene ``proof_ledger_monitor_report.json`` (eine LISTE
von Zeilen, kein Objekt mit benannten Feldern) -- deshalb ``version_probe =
"KEINE"``, siehe die Begruendung im Ledger-Eintrag.
"""

from __future__ import annotations

from typing import Any

from scripts.proof_judges import Verdict


def judge(evidence: Any, entry) -> Verdict:  # entry ist Teil des Urteiler-Vertrags, hier ungenutzt
    if not isinstance(evidence, list) or not evidence:
        return Verdict(
            "FAIL",
            branch="report_empty",
            detail="Report ist leer oder keine Liste -- der Lauf hat kein einziges Urteil geschrieben",
        )
    mislabeled = [
        row.get("id")
        for row in evidence
        if isinstance(row, dict)
        and row.get("evidence_source") != "artifact"
        and row.get("measured") == "KEIN_ZEUGE"
    ]
    if mislabeled:
        return Verdict(
            "FAIL",
            branch="skip_mislabeled_as_missing_witness",
            detail=(
                "uebersprungene Eintraege (evidence_source != artifact) als "
                f"KEIN_ZEUGE ausgegeben statt als KEIN_URTEIL: {mislabeled}"
            ),
        )
    return Verdict(
        "PASS",
        branch="report_shaped_as_expected",
        detail=f"{len(evidence)} Zeile(n), keine maskierte Auslassung",
    )
