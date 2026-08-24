#!/usr/bin/env python3
"""Urteiler fuer #5020: hinterlaesst ein gescheitertes Ziel eine Beweisdatei?

Beweisdateien entstehen NUR beim endgueltigen Scheitern eines Ziels. Ohne
Fehlschlag kein Beweis — das ist SCHLAFEND, nicht PASS.
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
    bindings = evidence.get("bindings") or {}
    beweise = bindings.get("evidence") or []
    gescheitert = bindings.get("failed") or []
    if beweise:
        return Verdict(
            "PASS",
            branch="evidence_written",
            detail=f"{len(beweise)} Beweisdatei(en)",
        )
    if gescheitert:
        return Verdict(
            "PRUEFEN",
            branch="failed_without_evidence",
            detail=f"{len(gescheitert)} Ziel(e) gescheitert, keine Beweisdatei",
        )
    return Verdict(
        "SCHLAFEND",
        branch="nothing_failed",
        detail="kein Ziel endgueltig gescheitert",
    )
