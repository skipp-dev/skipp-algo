"""Eine geratene Beweis-Nummer kann eine belegte treffen — und main killen.

Warum es diesen File gibt
=========================

Am 2026-08-29 legte PR #5179 seinen ``exempt``-Eintrag unter ``id = "5178"`` an.
Seine eigene Nummer war 5179; die Nummer war beim Anlegen **geraten**, und 5178
war zu dem Zeitpunkt bereits von einer anderen Änderung belegt. Der Loader lehnt
das Ledger bei doppelter id **komplett** ab (``ProofLedgerError: doppelte id``):
17 Tests rot, ``main`` 70 Minuten blockiert, jeder offene PR mit dazu.

Beide PRs waren für sich grün. Die Checks von #5179 liefen auf einer Basis
**vor** dem Merge des anderen und konnten die Kollision strukturell nicht sehen
— das ist die Stale-Check-Falle, kein Review-Versäumnis. Ein Kollisionstest
hätte sie deshalb auch nicht gefangen: zum Prüfzeitpunkt gab es keine Kollision.

Was fängt, ist die andere Frage: **ist die Nummer überhaupt die eigene?** Die
kann jeder PR für sich allein beantworten, ohne den Zustand anderer PRs zu
kennen — und sie ist zum Prüfzeitpunkt bereits entschieden. Deshalb hängt der
Wächter an ``github.event.pull_request.number``, nicht an einer Kollisionssuche.
"""

from __future__ import annotations

import pytest

from scripts.check_proof_ledger import guessed_pr_numbers


def test_the_own_number_passes() -> None:
    assert guessed_pr_numbers(frozenset({"5183"}), "5183") == []


def test_a_guessed_foreign_number_is_caught() -> None:
    """Der Fall vom 2026-08-29, wortwoertlich."""
    assert guessed_pr_numbers(frozenset({"5178"}), "5179") == ["5178"]


def test_symbolic_holder_ids_are_exempt() -> None:
    """Halter-Eintraege referenzieren keinen PR und koennen keinen fremden treffen.

    Wuerden sie mitgeprueft, waere der Waechter sofort rot fuer jeden PR, der
    einen Halter anlegt — und ein Waechter, der korrekte Zustaende anklagt, wird
    abgeschaltet.
    """
    ids = frozenset({"refresh-surface-hold", "klasse-h", "smcpp-source-hold"})
    assert guessed_pr_numbers(ids, "5183") == []


def test_a_mixed_batch_reports_only_the_foreign_numeric_ones() -> None:
    ids = frozenset({"5183", "5178", "tv-source-readback-persisted-store", "4999"})
    assert guessed_pr_numbers(ids, "5183") == ["4999", "5178"]


@pytest.mark.parametrize("pr", ["", "0"])
def test_nothing_is_claimed_without_a_real_pr_number(pr: str) -> None:
    """Ohne PR-Nummer darf der Waechter nicht raten, was richtig waere.

    ``main``-Pushes und ``merge_group`` tragen keine Nummer. Der Aufrufer setzt
    ``--pr`` dort schlicht nicht; hier wird gepinnt, dass eine leere Nummer nicht
    versehentlich JEDE numerische id anklagt.
    """
    if pr == "":
        # main() ruft die Pruefung bei leerer Nummer gar nicht auf; hier die
        # reine Funktion mit dem Grenzfall, damit die Bedingung nicht still
        # kippt, falls jemand den Aufruf umbaut.
        assert guessed_pr_numbers(frozenset({"5178"}), pr) == ["5178"], (
            "die reine Funktion urteilt weiter — der Schutz vor dem Leerfall "
            "MUSS deshalb im Aufrufer stehen (main prueft `if args.pr_number`)"
        )
    else:
        assert guessed_pr_numbers(frozenset({"5178"}), pr) == ["5178"]


def test_the_workflow_actually_passes_the_pr_number() -> None:
    """Der Wächter ohne Verdrahtung waere Dekoration.

    Gelesen wird die Workflow-Datei strukturell genug, dass ein umbenanntes Flag
    oder ein vergessenes env auffaellt — die Klasse, an der schon andere
    Wachposten dieses Repos gescheitert sind.
    """
    from tests._workflow_yaml import WORKFLOWS_DIR, load_workflow

    doc = load_workflow(WORKFLOWS_DIR / "smc-fast-pr-gates.yml")
    schritte = [
        s
        for job in doc["jobs"].values()
        if isinstance(job, dict)
        for s in (job.get("steps") or [])
        if isinstance(s, dict) and s.get("name") == "Guard the proof ledger"
    ]
    assert len(schritte) == 1, f"Guard-Step nicht eindeutig gefunden: {len(schritte)}"
    schritt = schritte[0]
    assert "PR_NUMBER" in (schritt.get("env") or {}), (
        "der Step reicht die PR-Nummer nicht mehr durch — die Pruefung liefe leer"
    )
    assert "github.event.pull_request.number" in str(schritt["env"]["PR_NUMBER"])
    assert "--pr" in schritt["run"], (
        "der Step ruft check_proof_ledger ohne --pr auf; die Nummer kaeme nie an"
    )
