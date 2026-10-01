#!/usr/bin/env python3
"""Urteiler fuer #5584 — findet ``promotion-gate-daily`` sein Tagesartefakt wieder?

#5584 behebt zwei Ursachen im Rolling-Benchmark (Kadenz-Gate zaehlte
uebersprungene Fires als bedientes Fenster; der Restore starb an HTTP 500 des
repo-weiten Artefakt-Index). Beide haben EINE Wirkung, und die liegt nicht im
Benchmark, sondern bei seinem Konsumenten: ``promotion-gate-daily`` (14:00 UTC)
sucht ``smc-measurement-benchmark-rolling-<heute>`` in den letzten acht
Bench-Laeufen. Gemessen 2026-10-01: in 17 von 18 Laeufen seit dem 31.8. fand es
nichts und uebersprang gruen.

Deshalb ist der Zeuge der KONSUMENT. Ein Bench-Lauf, der selbst gruen ist, hat
nichts bewiesen — gruen war er die ganze Zeit.

WARUM DER URTEILER DIE AUSGEGEBENE ZEILE LIEST, NICHT DEN TEXT
---------------------------------------------------------------
Der Runner druckt den run-Block jedes Schritts ins Log, bevor er ihn
ausfuehrt. Das Log JEDES Laufs enthaelt deshalb die Zeile

    echo "::notice title=promotion-gate-daily::artifact ${ART_NAME} fetched from run ${rid}"

— auch dann, wenn der Zweig nie lief. Eine Suche nach ``fetched from run``
besteht auf dem Skript-Echo und waere in beiden aufgezeichneten Logs wahr,
auch in dem vom 30.9., das nichts fand (gemessen: je 2 Treffer). Ausgegeben
sieht die Zeile anders aus: der Runner rendert sie als ``##[notice]artifact
smc-measurement-benchmark-rolling-<Datum> fetched from run <id>``, mit
aufgeloestem Namen. Nur darauf wird geprueft.
"""

from __future__ import annotations

import re

from scripts.proof_judges import Verdict

_ARTIFACT = r"smc-measurement-benchmark-rolling-\d{4}-\d{2}-\d{2}"
#: Gemessen an Job 106472364384 (Lauf 35641718088, 2026-09-21).
_FETCHED = re.compile(rf"##\[notice\]artifact {_ARTIFACT} fetched from run \d+")
#: Gemessen an Job 109923374032 (Lauf 36726137478, 2026-09-30).
_NOT_FOUND = re.compile(
    rf"##\[warning\]artifact {_ARTIFACT} not found in the last 8 completed rolling-bench runs"
)
_NO_BENCH_RUN = "##[warning]no recent completed rolling-bench run on main"


def judge(evidence: dict, entry) -> Verdict:
    del entry  # keine Versionsprobe: das Log des Konsumenten aendert sich nicht, siehe Ledger
    log = str(evidence.get("log") or "")
    if not log:
        return Verdict(
            "KANN_NICHT_BEZEUGEN",
            branch="kein_log",
            detail="Job-Log leer oder nicht abrufbar",
        )

    fetched = _FETCHED.search(log)
    if fetched:
        return Verdict(
            "PASS",
            branch="tagesartefakt_gefunden",
            detail=fetched.group(0).removeprefix("##[notice]"),
        )

    if _NOT_FOUND.search(log) or _NO_BENCH_RUN in log:
        # Nicht FAIL: aus diesem Log allein ist nicht trennbar, ob der Benchmark
        # sein Fenster wieder verpasst hat (der Defekt) oder ob der Producer an
        # diesem Morgen kein Buendel lieferte (dann kann es kein Tagesartefakt
        # geben). PRUEFEN sagt "sieh nach", FAIL saehe wie ein Beweis aus.
        return Verdict(
            "PRUEFEN",
            branch="tagesartefakt_fehlt",
            detail=(
                "das Gate fand um 14:00 UTC kein datiertes Bench-Artefakt — "
                "Fenster A wieder verpasst, oder der Producer lieferte nicht"
            ),
        )

    return Verdict(
        "STEHT_AUS",
        branch="download_nicht_erreicht",
        detail=(
            "weder Fund noch Fehlanzeige ausgegeben — der Job starb vor dem "
            "Download-Schritt; das Skript-Echo allein ist kein Zeuge"
        ),
    )
