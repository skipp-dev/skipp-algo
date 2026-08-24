#!/usr/bin/env python3
"""Urteiler fuer #5037 — laedt die gebumpte Action noch, oder degradiert sie still?

Der PR hebt ``dawidd6/action-download-artifact`` von v21 auf v24 in sieben
geplanten Workflows. Gemessen am 2026-08-24 stehen dort **18 Verwendungen, von
denen 11 fail-soft sind** (``if_no_artifact_found: warn``): bei
``plan-2-8-weekly-digest`` alle sieben, dazu ``promotion-gate-daily`` (der
Tier-1-Richtungseingang), ``adr0023-magnitude-shadow-daily`` (zwei) und
``plan-2-8-monthly-digest``.

Genau das ist die Beweislage. Braeche v24 den Download, blieben diese elf
Stellen **leer statt laut** — die Felder stuenden auf "nicht gemessen" und der
Workflow bliebe gruen. Die Testsuite kann das prinzipiell nicht sehen: sie
fuehrt keinen Runner aus.

WARUM DIESER URTEILER AUF POSITIVE EVIDENZ PRUEFT
-------------------------------------------------
Der Miss-Wortlaut von v24 ist hier NICHT bekannt — ohne einen echten Lauf mit
v24 waere jedes Muster dafuer geraten. Ein geratenes Suchmuster ist eine Probe,
die nichts probiert. Deshalb sucht dieser Urteiler ausschliesslich nach den
Zeilen, die ein GELUNGENER Download hinterlaesst; ihre Abwesenheit ist
"unbewiesen", nie "bestanden". Fail-closed in der einzigen Richtung, die man
ohne den Fehlerfall belegen kann.

Beide Muster sind an einem ECHTEN Log gemessen (Lauf 32737297322, Job
97463068400, ``promotion-gate-daily`` vom 2026-08-24), nicht der Dokumentation
der Action entnommen.
"""

from __future__ import annotations

from scripts.proof_judges import Verdict

#: Zeilen, die die Action bei einem gelungenen Download druckt. Gemessen, nicht
#: abgeschrieben:
#:     ==> (found) Run ID: 32726931240
#:     ==> Downloading: scored-family-events-accumulated.zip (1.33 MB)
_FOUND = "==> (found) Run ID:"
_DOWNLOADING = "==> Downloading:"


def judge(evidence: dict, entry) -> Verdict:
    log = str(evidence.get("log") or "")
    if not log:
        return Verdict(
            "KANN_NICHT_BEZEUGEN",
            branch="kein_log",
            detail="Job-Log leer oder nicht abrufbar",
        )

    # Versionsprobe ZUERST. `entry.version_probe` traegt den v24-Commit-SHA;
    # der Runner druckt beim Laden jeder Action ihre aufgeloeste SHA
    # ("Download action repository '<repo>@<sha>' (SHA:<sha>)"). Steht sie
    # nicht im Log, hat dieser Lauf noch die alte Version gefahren — dann ist
    # jedes weitere Urteil eine Aussage ueber den falschen Baum.
    if entry.version_probe != "KEINE" and entry.version_probe not in log:
        return Verdict(
            "STEHT_AUS",
            branch="zeuge_faehrt_noch_v21",
            detail=f"Log ohne {entry.version_probe} — Lauf liegt vor dem Bump",
        )

    found = log.count(_FOUND)
    downloaded = log.count(_DOWNLOADING)

    if found and downloaded:
        return Verdict(
            "PASS",
            branch="download_geliefert",
            detail=f"v24 lieferte: {found}x gefunden, {downloaded}x geladen",
        )

    if found and not downloaded:
        # Gefunden, aber nichts geholt: genau die stille Degradation, gegen die
        # dieser Eintrag steht. Nicht PRUEFEN — der Widerspruch ist der Befund.
        return Verdict(
            "FAIL",
            branch="gefunden_aber_nicht_geladen",
            detail=f"{found}x '(found)', aber 0x '{_DOWNLOADING}'",
        )

    # Kein Fund. Das kann der Defekt sein ODER ein Lauf, in dem schlicht kein
    # Vorgaenger-Artefakt existierte (die fail-soft-Stellen holen Vorgaenger).
    # Diese beiden sind aus dem Log allein nicht trennbar, also wird hier NICHT
    # angeklagt: PRUEFEN sagt "sieh selbst nach", FAIL saehe wie ein Beweis aus.
    return Verdict(
        "PRUEFEN",
        branch="kein_fund_im_log",
        detail=(
            "v24 lief, aber keine '(found)'-Zeile — entweder kein "
            "Vorgaenger-Artefakt vorhanden oder der Download bricht"
        ),
    )
