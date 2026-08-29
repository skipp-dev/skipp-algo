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
    monkeypatch.setenv("GITHUB_TOKEN", "t")
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


def test_a_phantom_run_does_not_keep_the_watcher_permanently_red() -> None:
    """Die Ausnahme wirkt — sonst faellt der Waechter seinem ersten Fund zum Opfer.

    Lauf 32985711996 ist am 2026-08-29 gegen alle drei Aufloesungswege
    gemessen worden (cancel / force-cancel / DELETE — alle verweigern, mit
    widerspruechlichen Begruendungen, waehrend der Lauf `queued` meldet).
    Ohne Ausnahme meldet der Waechter ihn bei JEDEM Lauf, und ein dauerhaft
    roter Draht wird abgeschaltet.
    """
    phantom = _run(
        id=32985711996,
        status="queued",
        created_at="2026-08-26T15:38:15Z",
        run_started_at="2026-08-26T15:38:15Z",
        name="tv-onboarding-packages",
    )
    assert evaluate([phantom], _NOW) == [], "der Phantom-Lauf faerbt weiter rot"


def test_the_phantom_exception_is_narrow_and_not_a_pattern() -> None:
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
