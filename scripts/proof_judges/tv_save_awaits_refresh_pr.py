#!/usr/bin/env python3
"""Urteiler: wartet der Ketten-Save auf den Refresh-PR, bevor er misst?

``tv-save-consumer-source`` wird vom Abschluss des Library-Refresh ausgeloest
und soll vor dem Checkout auf den Merge des Refresh-PRs warten (Schritt "Await
the refresh commit on main"). Vom 2026-08-13 bis 2026-10-01 suchte er den PR
unter der Id des REFRESH-Laufs, waehrend ``smc-library-publish`` den Branch nach
seiner EIGENEN Lauf-Id benannte. Die Suche traf nichts; "kein PR" galt als
"nichts geaendert". 14 von 14 gescheiterten Ketten-Saves vom 24.9. bis 1.10.
starteten so auf dem Baum vor dem Refresh und verweigerten mit "Library
publish drift".

WARUM DER URTEILER DIE AUSGEGEBENE ZEILE LIEST, NICHT DEN TEXT
---------------------------------------------------------------
Der Runner druckt den run-Block jedes Schritts ins Log, bevor er ihn ausfuehrt.
Jedes Log eines Ketten-Saves enthaelt deshalb BEIDE Skript-Zeilen

    echo "::notice::No ${prefix}* PR exists — the refresh reported …"
    echo "::notice::Refresh commit ${sha} (PR #${number}) is on main; …"

— gleich, welcher Zweig lief. Ausgegeben sehen sie anders aus: der Runner
rendert ``##[notice]…`` mit aufgeloesten Werten (Ziffern statt ``${prefix}``,
ein SHA statt ``${sha}``). Nur darauf wird geprueft.

"Kein PR" allein ist KEIN Fehlschlag: der Refresh oeffnet nur dann einen PR,
wenn die Regeneration etwas geaendert hat. Zum Defekt wird es erst zusammen mit
der Verweigerung im selben Lauf — der Save hat dann einen Manifest-Stand
gemessen, den TradingView schon ueberholt hatte.
"""

from __future__ import annotations

import re

from scripts.proof_judges import Verdict

#: Gemessen: noch an keinem Lauf (der Zweig entsteht erst mit diesem Fix).
_AWAITED = re.compile(r"##\[notice\]Refresh commit [0-9a-f]{7,40} \(PR #\d+\) is on main")
#: Gemessen an Job 110585304746 (Lauf 36919569655, 2026-10-01).
_NO_PR = re.compile(r"##\[notice\]No bot/library-refresh-\d+-\* PR exists")
#: Derselbe Job: die Verweigerung des Rollout-Werkzeugs, als JSON-Zeile.
_DRIFT_REFUSAL = '"error":"Library publish drift:'
_NOT_MERGED = re.compile(
    r"##\[error\]PR #\d+ for refresh run \d+ (did not merge within|was closed without merging)"
)


def judge(evidence: dict, entry) -> Verdict:
    del entry  # keine Versionsprobe: der neue Zweig IST die ausgegebene Zeile, siehe Ledger
    log = str(evidence.get("log") or "")
    if not log:
        return Verdict(
            "KANN_NICHT_BEZEUGEN",
            branch="kein_log",
            detail="Job-Log leer oder nicht abrufbar",
        )

    awaited = _AWAITED.search(log)
    if awaited:
        return Verdict(
            "PASS",
            branch="refresh_commit_abgewartet",
            detail=awaited.group(0).removeprefix("##[notice]"),
        )

    stuck = _NOT_MERGED.search(log)
    if stuck:
        # Der Schritt HAT gewartet — die Zuordnung stimmt also. Dass der PR
        # nicht kam, ist ein anderer Befund (blockierter Check, geschlossener
        # PR) und braucht einen Blick, kein Urteil ueber diesen Fix.
        return Verdict(
            "PRUEFEN",
            branch="refresh_pr_nicht_gemergt",
            detail=stuck.group(0).removeprefix("##[error]"),
        )

    no_pr = _NO_PR.search(log)
    if no_pr and _DRIFT_REFUSAL in log:
        return Verdict(
            "FAIL",
            branch="vor_dem_refresh_pr_gestartet",
            detail=(
                no_pr.group(0).removeprefix("##[notice]")
                + " — und derselbe Lauf verweigerte mit Library publish drift"
            ),
        )
    if no_pr:
        return Verdict(
            "STEHT_AUS",
            branch="kein_refresh_pr",
            detail=(
                "kein Refresh-PR gefunden und keine Verweigerung — der Lauf kann "
                "nicht bezeugen, ob gewartet worden waere"
            ),
        )

    return Verdict(
        "STEHT_AUS",
        branch="kein_ketten_save",
        detail=(
            "der Await-Schritt hat nichts ausgegeben — Zeitplan- oder "
            "Dispatch-Lauf, oder der Job starb davor"
        ),
    )
