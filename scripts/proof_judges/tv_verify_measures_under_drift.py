#!/usr/bin/env python3
"""Urteiler: misst ein Lesepass jetzt AUCH unter Library-Drift?

Zeuge ist der Bericht von ``tv-save-consumer-source`` (Job ``save``). Bis zum
2026-08-29 brach jeder ``verify-only``-Lauf bei Library-Publish-Drift ab,
BEVOR er irgendetwas las — Signatur ``checkedConsumers: 0`` bei
``expectedConsumers: 10``, und zwar strukturell: die Session-Queue hat 4-6 h
Latenz, die Publishes kommen etwa stuendlich, also faellt ein wartender Lauf
fast immer in ein Drift-Fenster.

Die Entscheidung selbst ist suite-ausfuehrbar (``resolveLibraryDriftGate``,
Tests in ``automation/tradingview/tests/tv_consumer_rollout_evidence.test.ts``).
Was die Suite NICHT sehen kann, ist die Verdrahtung im Playwright-Lauf. Genau
dafuer steht dieser Urteiler.

Der PASS-Fall ist eng gefasst, damit er nicht versehentlich vom Normalbetrieb
erfuellt wird: Drift beobachtet UND trotzdem gemessen. Ein Lauf ohne Drift
beweist nichts ueber diese Aenderung — er haette auch vorher gemessen.
"""

from __future__ import annotations

from scripts.proof_judges import Verdict


def _bindings(report: dict) -> dict:
    value = report.get("bindings")
    return value if isinstance(value, dict) else {}


def judge(evidence: dict, entry) -> Verdict:
    del entry  # Versionsprobe ist `sources.notJudgedReason`, siehe Ledger
    report = evidence.get("artifact")
    if not isinstance(report, dict):
        return Verdict("KANN_NICHT_BEZEUGEN", branch="no_artifact", detail="kein Bericht")

    if report.get("executionMode") != "verify-only":
        return Verdict(
            "STEHT_AUS",
            branch="not_a_read_only_run",
            detail="schreibender Lauf — er bricht bei Drift weiter ab, wie vorgesehen",
        )

    observed = report.get("tradingViewObserved") or {}
    library = observed.get("libraryRelease") or {}
    checked = _bindings(report).get("checkedConsumers")

    if library.get("verdict") != "drift":
        return Verdict(
            "STEHT_AUS",
            branch="no_drift_yet",
            detail=(
                "dieser Lauf sah keine Drift — er haette auch vor der Aenderung "
                "gemessen und beweist sie deshalb nicht"
            ),
        )

    if not isinstance(checked, int):
        return Verdict(
            "KANN_NICHT_BEZEUGEN",
            branch="no_checked_field",
            detail="Bericht ohne bindings.checkedConsumers",
        )

    if checked > 0:
        sources = report.get("sources") or {}
        reason = sources.get("notJudgedReason")
        if not reason:
            # Gemessen UND Quellen beurteilt waere die halbe Aenderung: die
            # Grenze der Aussage muss im Artefakt stehen, sonst liest ein
            # spaeterer Leser ein Quell-Urteil, das unter Drift nicht traegt.
            return Verdict(
                "FAIL",
                branch="measured_without_naming_the_limit",
                detail=(
                    "unter Drift gemessen, aber sources.notJudgedReason fehlt — "
                    "die Grenze der Aussage steht nicht im Artefakt"
                ),
            )
        return Verdict(
            "PASS",
            branch="measured_under_drift",
            detail=(
                f"Drift beobachtet und trotzdem {checked} Consumer gelesen; "
                "Quell-Urteil ausdruecklich ausgesetzt"
            ),
        )

    return Verdict(
        "FAIL",
        branch="still_blind_under_drift",
        detail=(
            "Drift beobachtet und checkedConsumers=0 — der Lesepass stirbt "
            "weiter vor der Messung, die Aenderung wirkt nicht"
        ),
    )
