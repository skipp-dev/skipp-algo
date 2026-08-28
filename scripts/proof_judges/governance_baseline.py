#!/usr/bin/env python3
"""Urteiler fuer #5161 — laeuft der Governance-Verifier taeglich WIRKLICH?

Der Beweis dieses PRs ist genau der, den ein Drill NICHT fuehren kann. Die
Suite kann den Step-Text ausfuehren (das tun fuenf Drills in
``tests/test_meta_watchdog_workflow_contract.py``), aber sie kann nicht
bezeugen, dass der Step im echten Cron STARTET — und genau das war der
Befund: ``scripts/verify_branch_protection.py`` existierte seit ADR-0011 und
lief in KEINEM Workflow. Ein Waechter, der nie startet, ist keiner.

Deshalb liest dieser Urteiler das JOB-LOG des ``probe``-Jobs von
``meta-watchdog`` und sucht die Spuren, die der Verifier selbst schreibt —
nicht die Echos meines Step-Wrappers. Das ist der Unterschied zwischen "mein
YAML sagt, es laeuft" und "das Werkzeug hat geantwortet":

* ``Verifying branch protection for`` — die Kopfzeile von
  ``verify_branch_protection.main()``. Sie kann in diesem Log nur stehen,
  seit dieser PR den Step eingebaut hat (Versionsprobe).
* ``Result: PASS``/``Result: FAIL`` — das Verdikt von
  ``ProtectionReport.print_summary()``.

**Leere Beobachtung ist kein Bestehen.** Faehrt der Job, ohne dass die
Kopfzeile auftaucht, ist das STEHT_AUS und nicht PASS — dieselbe Falle, die
``tv_legend_click.settings_never_attempted`` und
``tv_failure_evidence.nothing_failed`` abfangen: "kein Fehler gefunden" und
"nie versucht" sind verschiedene Aussagen.
"""

from __future__ import annotations

from scripts.proof_judges import Verdict

# Kopfzeile aus verify_branch_protection.main(). Bewusst OHNE das
# Repo-Slug-Suffix: OWNER/REPO stehen dort als Konstanten, und ein Umzug des
# Repos soll diesen Urteiler nicht still verstummen lassen (er wuerde sonst
# ewig STEHT_AUS melden statt zu urteilen).
_VERIFIER_HEADLINE = "Verifying branch protection for"
_RESULT_PASS = "Result: PASS"
_RESULT_FAIL = "Result: FAIL"
# Der rc=2-Ausgang des Skripts: Token fehlt/zu schwach. Das ist NICHT
# messbar — weder rot noch gruen (siehe rc-Vertrag im Step).
_TOKEN_MISSING = "GITHUB_TOKEN environment variable is required"


def judge(evidence: dict, entry) -> Verdict:
    del entry  # die Versionsprobe steckt in der Kopfzeile, nicht im Eintrag
    log = str(evidence.get("log") or "")
    if not log:
        return Verdict("KANN_NICHT_BEZEUGEN", branch="no_log", detail="Log leer")

    if _VERIFIER_HEADLINE not in log:
        return Verdict(
            "STEHT_AUS",
            branch="verifier_never_ran",
            detail=(
                "die Kopfzeile des Verifiers steht nicht im Log — der Step lief "
                "nicht (alter Workflow-Stand, frueher Job-Abbruch). Das ist "
                "kein bestandener Beweis, sondern eine leere Beobachtung"
            ),
        )

    if _TOKEN_MISSING in log:
        return Verdict(
            "STEHT_AUS",
            branch="probe_not_measurable",
            detail=(
                "der Verifier lief, konnte aber nicht messen (Token fehlt oder "
                "traegt administration:read nicht) — rc=2, kein Urteil"
            ),
        )

    if _RESULT_FAIL in log:
        return Verdict(
            "FAIL",
            branch="governance_baseline_broken",
            detail=(
                "der Verifier hat gemessen und die Baseline verletzt gefunden "
                "(Result: FAIL) — welcher Check fehlt, steht in den "
                "Report-Zeilen darueber"
            ),
        )

    if _RESULT_PASS in log:
        return Verdict(
            "PASS",
            branch="verifier_ran_and_baseline_holds",
            detail="der Verifier lief im Cron und meldete Result: PASS",
        )

    return Verdict(
        "PRUEFEN",
        branch="verifier_ran_without_verdict",
        detail=(
            "Kopfzeile da, aber weder Result: PASS noch Result: FAIL — der "
            "Verifier starb zwischen Start und Zusammenfassung"
        ),
    )
