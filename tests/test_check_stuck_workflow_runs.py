"""Die Sonde, die Läufe meldet, die nicht enden.

Warum es diesen File gibt
=========================

Der Workflow-Fehleralarm wertet nur Endzustände aus (``latest run failed``,
``noDataState: OK``). Ein Lauf, der ewig ``queued`` oder ``in_progress`` bleibt,
erzeugt kein ``failure`` — er blockiert required Kontexte und damit jeden
offenen PR, ohne dass irgendwo etwas rot wird. Diese Sonde schließt die
Sichtbarkeitslücke.

Geprüft wird hier das Urteil selbst, über gebaute Zustände, plus zwei
Kontrollen gegen die **echte** Repo-Population: dass das ``in_progress``-Budget
noch über jedem deklarierten ``timeout-minutes`` liegt (sonst meldet die Sonde
gesunde Langläufer), und dass diese Ableitung überhaupt etwas findet.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

import scripts.check_stuck_workflow_runs as mod
from scripts.check_stuck_workflow_runs import (
    IN_PROGRESS_BUDGET_MIN,
    QUEUED_BUDGET_MIN,
    evaluate,
    fetch_in_flight,
    main,
    max_declared_timeout,
)

_NOW = dt.datetime(2026, 8, 29, 12, 0, 0, tzinfo=dt.UTC)


def _run(**over):
    base = {
        "id": 1,
        "name": "CI",
        "head_branch": "main",
        "status": "in_progress",
        "created_at": "2026-08-29T11:55:00Z",
        "run_started_at": "2026-08-29T11:55:00Z",
        "html_url": "https://example/1",
    }
    base.update(over)
    return base


def _minutes_ago(minutes: int) -> str:
    return (_NOW - dt.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------
# Kontrollen gegen die echte Population
# --------------------------------------------------------------------------


def test_the_in_progress_budget_stays_above_every_declared_job_timeout() -> None:
    """Sonst meldet die Sonde einen gesunden Langläufer.

    Bewusst gegen die ECHTEN Workflows gemessen statt gegen eine Zahl im
    Kommentar: wächst irgendwo ein Job-Limit über das Budget, wird DIESER Test
    rot — und nicht die Sonde falsch laut.
    """
    groesstes = max_declared_timeout()
    assert groesstes > 0, (
        "kein einziges literales `timeout-minutes` in .github/workflows gefunden — "
        "die Ableitung ist blind, damit ist die Aussage unten vakuum"
    )
    assert groesstes < IN_PROGRESS_BUDGET_MIN, (
        f"IN_PROGRESS_BUDGET_MIN={IN_PROGRESS_BUDGET_MIN} liegt nicht mehr ueber dem "
        f"groessten deklarierten timeout-minutes ({groesstes}). Ein Job, der sein "
        "eigenes Limit legitim ausschoepft, wuerde als Stillstand gemeldet — "
        "Budget anheben, nicht den Test."
    )


def test_the_queued_budget_is_shorter_than_the_running_budget() -> None:
    """Warten auf einen Runner ist ein anderer Vorgang als Arbeiten.

    Ein gemeinsames Budget haette die Diagnose eingeebnet, um die es hier geht.
    """
    assert QUEUED_BUDGET_MIN < IN_PROGRESS_BUDGET_MIN


# --------------------------------------------------------------------------
# Das Urteil
# --------------------------------------------------------------------------


def test_a_healthy_fleet_produces_no_finding() -> None:
    runs = [
        _run(id=1, status="in_progress", run_started_at=_minutes_ago(30)),
        _run(id=2, status="queued", created_at=_minutes_ago(5), run_started_at=None),
    ]
    assert evaluate(runs, _NOW) == []


def test_a_long_queued_run_is_found_and_blamed_on_the_runner_label() -> None:
    runs = [_run(id=7, status="queued", created_at=_minutes_ago(QUEUED_BUDGET_MIN + 5), run_started_at=None)]
    found = evaluate(runs, _NOW)
    assert len(found) == 1
    f = found[0]
    assert f.status == "queued"
    assert "kein Runner" in f.diagnosis
    assert "haengenden" in f.diagnosis, (
        "die queued-Diagnose muss den Leser ausdruecklich VOM Suite-Hang wegschicken"
    )
    assert "7" in f.as_error_annotation() and "::error" in f.as_error_annotation()


def test_a_long_running_run_is_found_and_blamed_on_the_job() -> None:
    runs = [_run(id=8, status="in_progress", run_started_at=_minutes_ago(IN_PROGRESS_BUDGET_MIN + 5))]
    found = evaluate(runs, _NOW)
    assert len(found) == 1
    assert found[0].status == "in_progress"
    assert "endet nicht" in found[0].diagnosis
    assert "timeout-minutes" in found[0].diagnosis


def test_a_queued_run_is_judged_against_the_shorter_budget() -> None:
    """Die eigentliche Trennung: dieselbe Dauer, zwei Urteile.

    Ohne getrennte Budgets waere ein zwei Stunden wartender Job unsichtbar,
    weil er unter dem Laufbudget liegt — genau der Fall, der PRs blockiert.
    """
    alter = QUEUED_BUDGET_MIN + 30
    assert alter < IN_PROGRESS_BUDGET_MIN, "Testaufbau kaputt: Dauer muss zwischen den Budgets liegen"
    wartend = [_run(id=9, status="queued", created_at=_minutes_ago(alter), run_started_at=None)]
    laufend = [_run(id=10, status="in_progress", run_started_at=_minutes_ago(alter))]
    assert len(evaluate(wartend, _NOW)) == 1
    assert evaluate(laufend, _NOW) == []


def test_a_queued_run_without_run_started_at_still_has_an_age() -> None:
    """``run_started_at`` fehlt, solange nichts lief.

    Faellt die Sonde darauf zurueck, hat der wartende Lauf kein Alter und
    verschwindet still aus der Betrachtung — die Ausfallart, die sie sehen soll.
    """
    runs = [_run(id=11, status="queued", run_started_at=None, created_at=_minutes_ago(600))]
    found = evaluate(runs, _NOW)
    assert len(found) == 1
    assert found[0].age_min == pytest.approx(600, abs=1)


def test_a_queued_run_ignores_a_present_run_started_at() -> None:
    """Der Fall, den die Produktion lieferte: beide Felder gesetzt, Status queued.

    Waere hier `run_started_at` bevorzugt worden, stuende im Alarm die falsche
    Groesse — und bei einem spaeter gesetzten `run_started_at` auch die falsche
    ZAHL, naemlich eine zu kleine.
    """
    runs = [_run(id=13, status="queued",
                 created_at=_minutes_ago(600), run_started_at=_minutes_ago(30))]
    found = evaluate(runs, _NOW)
    assert len(found) == 1
    assert found[0].age_min == pytest.approx(600, abs=1), (
        "queued wurde ab run_started_at gemessen — die Wartezeit waere um 570 min zu kurz"
    )


def test_completed_runs_are_ignored() -> None:
    runs = [_run(id=12, status="completed", run_started_at=_minutes_ago(10_000))]
    assert evaluate(runs, _NOW) == []


def test_findings_are_ordered_oldest_first() -> None:
    runs = [
        _run(id=1, status="queued", created_at=_minutes_ago(90), run_started_at=None),
        _run(id=2, status="queued", created_at=_minutes_ago(400), run_started_at=None),
    ]
    assert [f.run_id for f in evaluate(runs, _NOW)] == [2, 1]


# --------------------------------------------------------------------------
# Fail-closed statt still gruen
# --------------------------------------------------------------------------


def test_missing_token_is_rc8_not_rc0(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert main(["--repo", "skipp-dev/skipp-algo"]) == 8


def test_api_failure_is_rc8_not_rc0(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "t")

    def boom(repo, token, fetcher=None):
        raise OSError("TLS handshake failed")

    monkeypatch.setattr("scripts.check_stuck_workflow_runs.fetch_in_flight", boom)
    assert main(["--repo", "skipp-dev/skipp-algo"]) == 8


def test_unusable_api_shape_raises_rather_than_returning_empty() -> None:
    with pytest.raises(ValueError):
        fetch_in_flight("o/r", "t", fetcher=lambda url, headers: {"message": "Not Found"})


def test_all_three_in_flight_statuses_are_asked_for() -> None:
    """Ein vergessener Status ist eine stille Luecke.

    ``waiting`` (Deployment-Freigabe) sieht im Zaehler aus wie ``queued`` und
    blockiert genauso — wird er nicht abgefragt, meldet die Sonde Ruhe.
    """
    gefragt: list[str] = []

    def fetcher(url, headers):
        gefragt.append(url.split("status=")[1].split("&")[0])
        return {"workflow_runs": []}

    fetch_in_flight("o/r", "t", fetcher=fetcher)
    assert set(gefragt) == {"queued", "waiting", "in_progress"}


def test_the_same_run_is_not_counted_twice_across_status_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ein Lauf kann zwischen zwei Abfragen den Status wechseln."""

    def fetcher(url, headers):
        return {"workflow_runs": [{"id": 42, "status": "in_progress"}]}

    runs = fetch_in_flight("o/r", "t", fetcher=fetcher)
    assert [r["id"] for r in runs] == [42]


def test_a_standing_run_makes_main_return_rc1(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setattr(
        "scripts.check_stuck_workflow_runs.fetch_in_flight",
        lambda repo, token, fetcher=None: [
            _run(id=77, name="smc-fast-pr-gates", status="queued",
                 created_at="2020-01-01T00:00:00Z", run_started_at=None)
        ],
    )
    rc = main(["--repo", "skipp-dev/skipp-algo"])
    out = capsys.readouterr()
    assert rc == 1
    assert "smc-fast-pr-gates" in out.out
    assert "77" in out.err and "::error" in out.err


def test_a_quiet_fleet_makes_main_return_rc0(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """Ruhige Flotte OHNE Quittungen -> rc 0.

    2026-08-29 praezisiert: die leere Flotte allein genuegt als Praemisse nicht
    mehr. Steht ein Lauf in PHANTOM_RUN_IDS und taucht in der Liste NICHT auf,
    dann ist er aufgeloest — und die tote Quittung ist zu Recht ein Befund
    (test_a_dead_acknowledgement_makes_the_probe_red_with_a_non_alarming_text).
    Dieser Test prueft die Ruhe, nicht die Quittungslage, und macht das jetzt
    explizit statt sich darauf zu verlassen, dass die Menge leer ist.
    """
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setattr("scripts.check_stuck_workflow_runs.PHANTOM_RUN_IDS", frozenset())
    monkeypatch.setattr(
        "scripts.check_stuck_workflow_runs.fetch_in_flight",
        lambda repo, token, fetcher=None: [],
    )
    assert main(["--repo", "skipp-dev/skipp-algo"]) == 0
    assert "Kein Lauf ueber seinem Budget" in capsys.readouterr().out


def test_the_age_source_follows_the_status_not_the_presence_of_a_field() -> None:
    """Am ersten echten Lauf bezahlt (2026-08-29).

    GitHub setzt ``run_started_at`` AUCH fuer ``queued``, identisch zu
    ``created_at`` (Lauf 32985711996). Eine Praeferenz-Reihenfolge stempelte
    darum "gemessen ab run_started_at" auf einen Lauf, der nie gestartet ist —
    das las sich wie 68 h Arbeit, wo 68 h Warten standen. Die Zahl stimmte, das
    Etikett log, und zwar in genau dem Fall, fuer den es erfunden wurde.

    Deshalb entscheidet der STATUS, nicht die Anwesenheit eines Feldes.
    """
    wartend = evaluate(
        [_run(id=1, status="queued",
              run_started_at=_minutes_ago(600), created_at=_minutes_ago(600))], _NOW
    )
    laufend = evaluate(
        [_run(id=2, status="in_progress", run_started_at=_minutes_ago(600))], _NOW
    )
    assert "Wartezeit" in wartend[0].age_source, (
        f"queued wurde als {wartend[0].age_source!r} etikettiert — der Lauf hat nicht gearbeitet"
    )
    assert "created_at" in wartend[0].age_source
    assert "Laufzeit" in laufend[0].age_source
    assert "Wartezeit" in wartend[0].as_error_annotation()
    assert "Laufzeit" in laufend[0].as_error_annotation()


def test_the_queued_diagnosis_names_the_orphan_cause_too() -> None:
    """Die zweite Ursache, die den ERSTEN Fund dieses Waechters erklaerte.

    2026-08-29: tv-onboarding-packages stand 4140 min in `queued`, und die
    damals einzige Diagnose schickte den Leser zum Runner-Label. Gemessen war
    es etwas anderes: der Lauf gehoerte zu PR #5101, der 20 min nach dem
    Queue-Eintritt mergte; der Branch `ci/pin-playwright-browser` verschwand
    dabei (`git ls-remote` = 0 Refs), und GitHub raeumt so einen PR-Lauf nie
    ab. Repo-weit war das der EINZIGE wartende Lauf (`status=queued` ->
    total_count 1) — die Klasse ist selten, aber ihre Fehldiagnose kostet
    jedes Mal eine Suche am intakten Label.

    Ein Alarm, der wahr ist und falsch begruendet, ist die teuerste Sorte:
    er wird geglaubt.
    """
    f = evaluate(
        [
            _run(
                status="queued",
                created_at="2026-08-26T15:38:15Z",
                run_started_at="2026-08-26T15:38:15Z",
                name="tv-onboarding-packages",
            )
        ],
        _NOW,
    )[0]
    assert "verwaist" in f.diagnosis, (
        "die Waisen-Ursache fehlt — der Leser prueft dann ein intaktes Label"
    )
    assert "Runner-Label" in f.diagnosis, (
        "die Label-Ursache darf dabei nicht verloren gehen; beide sind moeglich"
    )


def test_the_orphan_hint_does_not_stop_at_cancel() -> None:
    """`gh run cancel` allein ist eine Sackgasse — am 29.8. gemessen.

    Beide Endpunkte verweigerten den Waisen, und zwar mit einander
    widersprechenden Meldungen: `gh run cancel` -> "Cannot cancel a workflow
    run that is completed", force-cancel -> "Cannot cancel a workflow run that
    has not been queued yet" (HTTP 409) — waehrend Lauf UND Check-Suite
    unveraendert `queued` meldeten. Ein Hinweis, der dort endet, schickt den
    Leser in genau diese Schleife; der Ausweg (DELETE) gehoert daneben.
    """
    run = _run(
        status="queued",
        created_at="2026-08-26T15:38:15Z",
        run_started_at="2026-08-26T15:38:15Z",
    )
    f = evaluate([run], _NOW)[0]
    assert "cancel" in f.diagnosis and "DELETE" in f.diagnosis, (
        f"der Hinweis endet bei cancel und laesst den Leser stehen: {f.diagnosis}"
    )
    assert "PHANTOM_RUN_IDS" in f.diagnosis, (
        "der Hinweis muss den einzigen verbleibenden Weg nennen — sonst "
        "verspricht er einen Ausweg, den es nachweislich nicht gibt"
    )


def test_a_phantom_run_does_not_keep_the_watcher_permanently_red(phantom: int) -> None:
    """Die Ausnahme wirkt — sonst faellt der Waechter seinem ersten Fund zum Opfer.

    Ohne Ausnahme meldet der Waechter einen unaufloesbaren Waisen bei JEDEM
    Lauf, und ein dauerhaft roter Draht wird abgeschaltet.

    2026-08-29 auf eine SYNTHETISCHE ID umgestellt. Vorher stand hier der echte
    Lauf 32985711996 — der ist inzwischen aufgeloest (16:28:07Z, `completed` /
    `cancelled`, nach 72,8 h in `queued`), und der Test waere mit der geleerten
    Ausnahmemenge gefallen. Er prueft den MECHANISMUS, nicht den Bestand: eine
    Zusicherung, die an einem einzelnen Vorfall haengt, stirbt mit ihm, obwohl
    das Verhalten weiter gilt.
    """
    haenger = _run(
        id=phantom,
        status="queued",
        created_at="2026-08-26T15:38:15Z",
        run_started_at="2026-08-26T15:38:15Z",
        name="tv-onboarding-packages",
    )
    assert evaluate([haenger], _NOW) == [], "der Phantom-Lauf faerbt weiter rot"


def test_the_phantom_exception_is_narrow_and_not_a_pattern(phantom: int) -> None:
    """Ein ANDERER haengender Lauf desselben Workflows muss weiter feuern.

    Die Ausnahme ist eine ID-Liste, kein Muster. Ein Muster ("alles, was
    verwaist aussieht") wuerde genau die Klasse stumm schalten, um die es
    geht — die Ausfallart ohne Alarm, gegen die #5183 gebaut wurde.
    """
    anderer = _run(
        id=999999999,
        status="queued",
        created_at="2026-08-26T15:38:15Z",
        run_started_at="2026-08-26T15:38:15Z",
        name="tv-onboarding-packages",
    )
    assert len(evaluate([anderer], _NOW)) == 1, (
        "die Ausnahme greift zu breit — sie darf NUR die eine gemessene ID decken"
    )


def test_no_phantom_id_has_outlived_its_reason() -> None:
    """Die Gegenrichtung: eine Ausnahme, deren Grund entfallen ist, muss auffallen.

    Der Eintrag steht nur, WEIL GitHub den Lauf nicht aufloest. Loest GitHub
    ihn doch noch auf, ist die Ausnahme gegenstandslos — und eine
    gegenstandslose Ausnahme ist schlimmer als keine: sie behauptet, ein Lauf
    koenne nicht gemeldet werden, waehrend er laengst weg ist. Dieselbe
    Mechanik wie bei den `[[unreachable_branch]]`-Deklarationen des
    Beweis-Ledgers: die Deklaration muss sterben koennen.

    Netzlos geprueft: der Eintrag muss im Modul begruendet sein (ID im
    Kommentarblock ueber der Menge). Wer eine ID ohne Begruendung eintraegt,
    faellt hier auf.
    """
    quelle = Path(mod.__file__).read_text(encoding="utf-8")
    # An der ZUWEISUNG ankern, nicht am ersten Vorkommen des Namens: seit die
    # Diagnose den Namen selbst nennt, traf ein naiver split() den Text im
    # Meldungs-String und schnitt den Begruendungsblock weg. Der Test fiel
    # dadurch auf seine eigene Suche herein — genau die Klasse, die er bewacht.
    marker = "PHANTOM_RUN_IDS: frozenset[int] = frozenset("
    assert marker in quelle, "die Zuweisung ist umgezogen — Anker neu setzen"
    block = quelle.split(marker)[0]
    for run_id in mod.PHANTOM_RUN_IDS:
        assert str(run_id) in block, (
            f"Lauf {run_id} steht in PHANTOM_RUN_IDS, aber der Kommentarblock "
            "darueber begruendet ihn nicht — eine Ausnahme ohne Grund wird nie "
            "wieder geprueft"
        )


def test_the_phantom_exception_carries_a_deadline_and_expires() -> None:
    """Eine Ausnahme ohne Frist ist ein Mute — und der eigene Text verspricht eine.

    Der Diagnosetext der Sonde nennt die Ausnahme "datiert"; bis 2026-08-29 war
    die Zuweisung ein undatiertes ``frozenset``. Name und Ausdruck fielen
    auseinander, und was blieb, war ein Dauer-Stummschalter fuer genau die
    Ausfallart, gegen die #5183 gebaut wurde.

    Diese Zeile IST der Stolperdraht: ab der Frist faellt sie rot und erzwingt
    ein Nachmessen. Beide Ausgaenge verlangen eine Handlung — GitHub hat den
    Waisen abgeraeumt (id entfernen, sonst ist sie tot und deckt kuenftig einen
    ECHTEN Stillstand), oder er steht weiter (Datum UND Begruendung erneuern).
    """
    frist = dt.date.fromisoformat(mod.PHANTOM_REVIEW_BY)
    assert dt.date.today() <= frist, (
        f"Die Phantom-Ausnahme ist seit {mod.PHANTOM_REVIEW_BY} faellig. "
        f"Nachmessen, ob {sorted(mod.PHANTOM_RUN_IDS)} noch stehen: "
        "geraeumt -> id entfernen; steht weiter -> Datum und Begruendung "
        "erneuern. Nicht einfach das Datum hochsetzen."
    )


def test_every_phantom_id_is_covered_by_the_deadline() -> None:
    """Kein Eintrag darf an der Frist vorbei existieren.

    Ohne diese Kopplung koennte eine zweite id spaeter dazukommen und waere
    unbefristet — die Luecke von 2026-08-29 in klein.

    Die LEERE Menge ist seit 2026-08-29 der Normalzustand (der einzige Waise
    wurde aufgeloest) und ausdruecklich zulaessig. Sie macht die Aussage aber
    vakuum, deshalb wird sie benannt statt stillschweigend durchgelassen: was
    dann noch traegt, ist die Frist selbst — sie muss lesbar bleiben, sonst
    verrottet sie unbemerkt bis zum naechsten Eintrag.
    """
    assert mod.PHANTOM_REVIEW_BY, "Frist fehlt, die naechste Ausnahme waere wieder ein Mute"
    frist = dt.date.fromisoformat(mod.PHANTOM_REVIEW_BY)
    # Bewusst KEIN pytest.skip bei leerer Menge: ein uebersprungener Test ist
    # einer, der nicht laeuft, und das Repo fuehrt darueber zu Recht ein Budget.
    # Die Frist wird immer geprueft; die Deckungsaussage gilt zusaetzlich,
    # sobald es ueberhaupt einen Eintrag gibt.
    for pid in mod.PHANTOM_RUN_IDS:
        assert isinstance(pid, int) and pid > 0, f"unbrauchbare Ausnahme-ID {pid!r}"
    assert frist.year >= 2026, "die Frist zeigt in die Vergangenheit"


# --------------------------------------------------------------------------
# Quittiert heisst ausgewiesen, nicht weggelassen (2026-08-29)
# --------------------------------------------------------------------------


#: Eine SYNTHETISCHE Ausnahme-ID fuer die Tests unten.
#:
#: Bis 2026-08-29 lasen sie die erste ID aus der echten Menge. Seit diese leer
#: ist (der Waise wurde aufgeloest), waere das ein IndexError gewesen — und der
#: naheliegende "Fix", die Tests bei leerer Menge zu ueberspringen, haette den
#: MECHANISMUS ungeprueft gelassen, obwohl er weiterhin existiert. Die Tests
#: pruefen das Verhalten, nicht den Ist-Bestand; deshalb setzen sie ihre eigene
#: Ausnahme.
_SYNTH_PHANTOM = 424242


@pytest.fixture
def phantom(monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(
        "scripts.check_stuck_workflow_runs.PHANTOM_RUN_IDS", frozenset({_SYNTH_PHANTOM})
    )
    return _SYNTH_PHANTOM


def test_an_acknowledged_run_is_excluded_from_the_verdict(phantom: int) -> None:
    """Der Exit-Code darf sich durch eine Quittung nicht aendern."""
    runs = [_run(id=phantom, status="queued",
                 created_at=_minutes_ago(5000), run_started_at=None)]
    assert evaluate(runs, _NOW) == []


def test_an_acknowledged_run_is_still_reported(phantom: int) -> None:
    """Der eigentliche Punkt: sichtbar bleiben.

    Vorher verschwand ein quittierter Lauf per `continue` aus BEIDEM — Urteil
    und Bericht. In der Form ist eine Quittung von einem Mute nicht zu
    unterscheiden, und ein Mute nimmt auch dem naechsten, echten Stillstand die
    Zeile weg.
    """
    runs = [_run(id=phantom, status="queued",
                 created_at=_minutes_ago(5000), run_started_at=None)]
    ausgewiesen = mod.acknowledged_over_budget(runs, _NOW)
    assert len(ausgewiesen) == 1
    assert ausgewiesen[0].run_id == phantom
    assert ausgewiesen[0].age_min == pytest.approx(5000, abs=1)


def test_verdict_and_acknowledged_are_complementary_over_the_same_population(phantom: int) -> None:
    """Kein Lauf faellt zwischen die beiden Listen — und keiner steht in beiden.

    Beide teilen sich EINE Klassifikation (`_over_budget`); diese Zeile pinnt,
    dass die Aufteilung danach vollstaendig und ueberschneidungsfrei ist. Ohne
    sie koennte ein Umbau einen stehenden Lauf lautlos in keine der beiden
    Listen fallen lassen.
    """
    runs = [
        _run(id=phantom, status="queued", created_at=_minutes_ago(5000), run_started_at=None),
        _run(id=901, status="queued", created_at=_minutes_ago(5000), run_started_at=None),
        _run(id=902, status="in_progress", run_started_at=_minutes_ago(10)),  # gesund
    ]
    urteil = {f.run_id for f in evaluate(runs, _NOW)}
    quittiert = {f.run_id for f in mod.acknowledged_over_budget(runs, _NOW)}
    assert urteil == {901}
    assert quittiert == {phantom}
    assert not (urteil & quittiert), "ein Lauf steht in beiden Listen"
    ueber_budget = {r["id"] for r in runs if mod._over_budget(r, _NOW)}
    assert urteil | quittiert == ueber_budget, "ein stehender Lauf faellt zwischen die Listen"


def test_a_dead_acknowledgement_is_detected_when_the_run_is_gone(phantom: int) -> None:
    """Die Laufzeit-Haelfte, die der netzlose Test nicht leisten kann.

    `test_no_phantom_id_has_outlived_its_reason` verspricht in seinem Docstring,
    dass eine gegenstandslos gewordene Ausnahme auffaellt — er prueft aber nur,
    ob die ID im Kommentar begruendet ist. Ob der Lauf noch EXISTIERT, sieht nur
    eine Sonde mit Netz.
    """
    assert mod.dead_acknowledgements([]) == [phantom]
    noch_da = [_run(id=phantom, status="queued")]
    assert mod.dead_acknowledgements(noch_da) == []


def test_a_dead_acknowledgement_makes_the_probe_red_with_a_non_alarming_text(
    monkeypatch: pytest.MonkeyPatch, capsys, phantom: int
) -> None:
    """Rot, aber der Text sagt, dass es die GUTE Nachricht ist.

    Sonst sucht der Geweckte nach einem Schaden, den es nicht gibt — dieselbe
    Klasse wie eine falsche Anschuldigung, nur andersherum.
    """
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setattr(
        "scripts.check_stuck_workflow_runs.fetch_in_flight",
        lambda repo, token, fetcher=None: [],
    )
    rc = main(["--repo", "skipp-dev/skipp-algo"])
    err = capsys.readouterr().err
    assert rc == 1
    assert str(phantom) in err
    assert "GUTE Nachricht" in err and "entfernen" in err
