#!/usr/bin/env python3
"""Urteiler fuer die persistierte Quell-Ruecklese — liest das save-JOB-LOG.

Run 33031264859 (2026-08-27, Pin /364) schrieb den Strategy-Quelltext in den
gespeicherten Slot "SMC Long-Dip Mobile" und meldete trotzdem matches=true:
die alte Ruecklese WAEHLTE den Monaco-Puffer anhand des ERWARTETEN
Deklarationstitels aus — sie beantwortete "sieht irgendein sichtbarer Puffer
aus wie erwartet", nie "was liegt im gespeicherten Bestand". Der Fix liest
den Bestand ueber die pine-facade (``source-readback-authority facade:...``)
und lehnt Fremd-Deklarationen fail-closed ab
(``source-readback-identity-mismatch <name>:<gefundenerTitel>``).

Alle Spuren stehen im Job-LOG, nie im Artefakt (gleiche Klasse wie #5018) —
daher ``evidence_source = "job_log"`` und ``{"log": "<text>"}`` als Evidenz.

WICHTIG: nicht ``tv_legend_click`` wiederverwenden — dessen Zweig
``"identity-mismatch" in log`` wuerde auf ``source-readback-identity-mismatch``
anspringen und einen korrekt feuernden Waechter als Klick-FAIL fehlurteilen.
"""

from __future__ import annotations

from scripts.proof_judges import Verdict


def judge(evidence: dict, entry) -> Verdict:
    del entry  # Versionsprobe ist die Spur selbst, siehe Ledger-Eintrag
    log = str(evidence.get("log") or "")
    if not log:
        return Verdict("KANN_NICHT_BEZEUGEN", branch="no_log", detail="Log leer")

    if "source-readback-identity-mismatch" in log or "source-save-persisted-mismatch" in log:
        # Der fail-closed-Zweig hat GEFEUERT: die Ruecklese hat einen Slot mit
        # fremder Deklaration (oder falschem Bestands-Hash) abgelehnt. Das
        # BEWEIST den Mechanismus live — und meldet zugleich einen Bestand,
        # den der Operator ansehen muss (Cross-Write-Klasse 33031264859).
        return Verdict(
            "PASS",
            branch="fail_closed_fired",
            detail="Identitaets-/Bestandswaechter hat abgelehnt — Mechanismus "
            "bewiesen; der betroffene Slot braucht Operator-Blick",
        )

    facade_reads = log.count("source-readback-authority facade:")
    fallback_reads = log.count("source-readback-authority editor-fallback:")
    if facade_reads == 0 and fallback_reads == 0:
        # Abwesenheit beweist nichts (#5018-Regel): der Lauf trug den Fix
        # nicht, oder die Quell-Verifikation lief nie (z. B. verify-only-Abbruch
        # am Publish-Drift-Gate).
        return Verdict(
            "STEHT_AUS",
            branch="readback_never_ran",
            detail="keine source-readback-authority-Spur — Lauf ohne Fix oder "
            "ohne Quell-Verifikation; das ist kein bestandener Beweis",
        )
    if facade_reads == 0:
        # Jede Ruecklese fiel auf den Editor zurueck: die Bestands-Autoritaet
        # (pine-facade get) hat fuer diesen Lauf NIE geliefert. Genau die
        # Endpoint-Annahme, die der Fix traegt, ist damit fuer diesen Lauf
        # widerlegt — laut melden, nicht als Haertung durchwinken.
        return Verdict(
            "FAIL",
            branch="facade_never_resolved",
            detail=f"{fallback_reads} Ruecklese(n), alle editor-fallback — die "
            "pine-facade-Saved-Source-Annahme hat nicht getragen",
        )
    return Verdict(
        "PASS",
        branch="facade_authoritative",
        detail=f"facade={facade_reads} editor-fallback={fallback_reads}",
    )
