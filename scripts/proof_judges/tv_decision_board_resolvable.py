#!/usr/bin/env python3
"""Urteiler fuer #5231: findet die Verify-/Save-Kette das Decision Board wieder?

Geburtsfehler vom April: die Quelle deklarierte seit dem 15.4. "SMC Long-Dip
Dashboard", die Rollout-Config suchte "SMC Decision Board". Jeder Lauf seit
mind. 2026-08-29 warf "Existing chart instance not found" gegen ein gesundes
Chart, und outOfBandDrift blieb dadurch "unknown". #5231 legt Titel, Datei und
Config wieder auf EINEN Namen; die Suite kann das nicht sehen, weil die
Wirkung im Playwright-Lauf gegen das echte Chart liegt.

Leere Beobachtung zaehlt nicht (checkedConsumers==0 ist STEHT_AUS, nie PASS —
die Klasse aus skipp-empty-observation-poisons-baseline).
"""

from __future__ import annotations

from scripts.proof_judges import Verdict

_NAME = "SMC Decision Board"


def _bindings(report: dict) -> dict:
    value = report.get("bindings")
    return value if isinstance(value, dict) else {}


def judge(evidence: dict, entry) -> Verdict:
    del entry  # Versionsprobe steckt im Artefakt selbst (repositoryExpected)
    report = evidence.get("artifact")
    if not isinstance(report, dict):
        report = evidence if isinstance(evidence, dict) else {}
    if not report:
        return Verdict("KANN_NICHT_BEZEUGEN", branch="no_artifact", detail="kein Bericht")

    expected = report.get("repositoryExpected") or {}
    sources = expected.get("sources") or []
    paths = {s.get("repoRelativePath") for s in sources if isinstance(s, dict)}
    if "SMC_Decision_Board.pine" not in paths:
        return Verdict(
            "KANN_NICHT_BEZEUGEN",
            branch="pre_fix_tree",
            detail="Lauf ohne Rename-Baum: SMC_Decision_Board.pine fehlt in repositoryExpected",
        )

    bindings = _bindings(report)
    if not (bindings.get("checkedConsumers") or 0):
        return Verdict(
            "STEHT_AUS",
            branch="empty_observation",
            detail="checkedConsumers=0 — leere Beobachtung, kein Beweis",
        )

    for failure in bindings.get("failed") or []:
        target = str((failure or {}).get("target") or "")
        error = str((failure or {}).get("error") or "")
        if target == _NAME and "Existing chart instance not found" in error:
            return Verdict("FAIL", branch="still_not_found", detail=error[:120])

    for consumer in bindings.get("consumers") or []:
        if not isinstance(consumer, dict) or consumer.get("scriptName") != _NAME:
            continue
        if consumer.get("ok") is True:
            n = len(consumer.get("bindings") or [])
            return Verdict("PASS", branch="board_read_ok", detail=f"{_NAME} gelesen: {n} Bindings")
        return Verdict(
            "PRUEFEN",
            branch="found_but_not_ok",
            detail=f"{_NAME} erreicht, aber ok={consumer.get('ok')!r}",
        )

    return Verdict(
        "STEHT_AUS",
        branch="board_not_in_run",
        detail=f"{_NAME} in diesem Lauf weder geprueft noch gescheitert",
    )
