"""Die Kadenz-Entscheidung des Rolling-Benchmarks, tabellengetrieben.

Der Workflow feuerte bis zu neunmal je Werktag (``workflow_run`` je
Producer-Tick), obwohl sein Kopfkommentar von zwei Laeufen ausgeht — eine
Praemisse aus der Zeit, als der Producer 2x lief. Gemessen 2026-08-29: acht
Laeufe an einem Werktag, 366 Runner-Minuten.

Zwei Laeufe genuegen, aber es muessen die richtigen zwei sein: einer im
Fenster 11:00-12:30 UTC fuer die drei Tages-Gates (13:30/14:00/15:00), einer
ab 20:00 UTC fuer die nachgereiften Labels des 5-Tage-Ankerfensters.

Diese Datei prueft die ENTSCHEIDUNG, nicht den Shell-Code drumherum — sie ist
eine reine Funktion, damit genau das moeglich ist.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

import pytest
import yaml

from scripts.decide_rolling_benchmark_run import decide, main

UTC = _dt.UTC
_REPO_ROOT = Path(__file__).resolve().parent.parent


def _at(hhmm: str) -> _dt.datetime:
    h, m = hhmm.split(":")
    return _dt.datetime(2026, 8, 31, int(h), int(m), tzinfo=UTC)


def _run(hhmm: str, conclusion: str = "success", worked: bool | None = True) -> dict:
    """Ein heutiger Lauf. ``worked`` sagt, ob der Worker-Job wirklich lief.

    Ein vom Gate uebersprungener Fire endet AUCH mit ``conclusion=success``
    (der Gate-Job war erfolgreich, der Worker wurde uebersprungen) — er traegt
    ``worked=False``. ``None`` heisst: der Aufrufer konnte es nicht ermitteln.
    """
    return {
        "conclusion": conclusion,
        "created_at": f"2026-08-31T{hhmm}:00Z",
        "worked": worked,
    }


def _skipped(hhmm: str) -> dict:
    """Ein Fire, den das Gate selbst uebersprungen hat — gruen, aber leer."""
    return _run(hhmm, "success", worked=False)


@pytest.mark.parametrize(
    ("label", "now", "runs", "expect_run", "expect_window"),
    [
        # --- Fenster A -----------------------------------------------------
        ("leerer Tag, mitten in A", "11:30", [], True, "A"),
        ("leerer Tag, A-Untergrenze", "11:00", [], True, "A"),
        ("A bereits bedient", "12:00", [_run("11:10")], False, "A"),
        # --- vor A ---------------------------------------------------------
        ("zu frueh: 08-Tick", "09:05", [], False, "none"),
        ("zu frueh: knapp davor", "10:59", [], False, "none"),
        # --- Netz ----------------------------------------------------------
        ("A verpasst, Nachmittag", "14:10", [], True, "net"),
        ("A verpasst, Sicherheits-Cron", "16:30", [], True, "net"),
        ("A bedient, Nachmittag", "16:30", [_run("11:10")], False, "A"),
        # --- Fenster B -----------------------------------------------------
        ("B offen, A war bedient", "20:30", [_run("11:10")], True, "B"),
        ("B offen, Tag war leer", "21:05", [], True, "B"),
        ("B bereits bedient", "22:10", [_run("11:10"), _run("20:30")], False, "B"),
        # Ein FEHLGESCHLAGENER Lauf zaehlt nicht als bedient.
        ("nur Fehlschlag in A", "12:00", [_run("11:10", "failure")], True, "A"),
    ],
)
def test_the_two_windows(label, now, runs, expect_run, expect_window) -> None:
    d = decide(
        now=_at(now), event_name="workflow_run",
        producer_conclusion="success", todays_runs=runs,
    )
    assert d.run is expect_run, f"{label}: {d.reason}"
    assert d.window == expect_window, f"{label}: {d.reason}"


def test_a_failed_producer_never_runs() -> None:
    """Bestehende Bedingung, unveraendert: kein Producer-Erfolg, kein Lauf."""
    for conclusion in ("failure", "cancelled", "skipped", None):
        d = decide(
            now=_at("11:30"), event_name="workflow_run",
            producer_conclusion=conclusion, todays_runs=[],
        )
        assert d.run is False, conclusion


def test_a_manual_dispatch_always_runs() -> None:
    """Das Gate steht nicht zwischen Operator und Werkzeug."""
    d = decide(
        now=_at("03:00"), event_name="workflow_dispatch",
        producer_conclusion=None, todays_runs=[_run("11:10"), _run("20:30")],
    )
    assert d.run is True
    assert d.window == "manual"


# ---------------------------------------------------------------------------
# Positivkontrollen — ohne sie waere der Rest wertlos.
# ---------------------------------------------------------------------------


def test_blindness_runs_rather_than_skips() -> None:
    """Die wichtigste Eigenschaft: bei Unwissen wird GELAUFEN.

    Ein Gate, das ueberspringt, wenn es den Tageszustand nicht lesen kann,
    stoppt den Benchmark still und dauerhaft — und das Freshness-Budget stand
    bis 2026-08-29 auf ``:any``, haette also nichts gemeldet. Ein
    ueberfluessiger Lauf kostet 46 Minuten; ein stiller Stopp kostet die
    Drift-Erkennung, fuer die dieser Workflow existiert.
    """
    for when in ("03:00", "11:30", "16:30", "22:00"):
        d = decide(
            now=_at(when), event_name="workflow_run",
            producer_conclusion="success", todays_runs=None,
        )
        assert d.run is True, when
        assert d.window == "blind"


def test_a_day_without_any_success_always_gets_a_run_after_window_a_opens() -> None:
    """Kein Tag darf still ohne Schnappschuss bleiben.

    Ab Fenster-A-Beginn muss JEDE Stunde bis Mitternacht zu einem Lauf
    fuehren, solange der Tag keinen Erfolg trug — sonst koennte eine
    unglueckliche Fire-Verteilung einen ganzen Tag verschlucken.
    """
    for hour in range(11, 24):
        d = decide(
            now=_at(f"{hour:02d}:15"), event_name="workflow_run",
            producer_conclusion="success", todays_runs=[],
        )
        assert d.run is True, f"{hour}:15 wuerde einen leeren Tag durchlassen"


def test_the_happy_path_costs_exactly_two_runs() -> None:
    """Die Zusage des Entwurfs, an der Regel selbst geprueft.

    Neun Producer-Ticks, alle erfolgreich, Fires jeweils ~60 min spaeter.
    Genau zwei duerfen durchkommen.

    Die Welt ist hier so modelliert, wie GitHub sie meldet: JEDER Fire
    hinterlaesst einen Lauf mit ``conclusion=success`` — auch der, den das
    Gate uebersprungen hat. Die erste Fassung dieses Tests haengte nur die
    wirklich gelaufenen Fires an und pruefte damit eine Welt, die es nicht
    gibt; in der echten bediente der uebersprungene 09:00-Fire "Fenster A",
    und der Benchmark lief vom 2026-08-31 an nur noch abends.
    """
    fires = ["09:00", "11:00", "13:00", "15:00", "17:00", "19:00", "21:00", "22:00", "23:00"]
    runs: list[dict] = []
    ran: list[str] = []
    for fire in fires:
        d = decide(
            now=_at(fire), event_name="workflow_run",
            producer_conclusion="success", todays_runs=list(runs),
        )
        if d.run:
            ran.append(f"{fire}/{d.window}")
            runs.append(_run(fire))
        else:
            runs.append(_skipped(fire))
    assert ran == ["11:00/A", "21:00/B"], ran


# ---------------------------------------------------------------------------
# Ein uebersprungener Fire ist kein bedientes Fenster.
#
# Gemessen 2026-10-01 an den Laeufen vom 2026-09-30: 09:40 und 10:41 wurden
# vom Gate uebersprungen ("vor Fenster A") und endeten mit conclusion=success.
# Der naechste Fire meldete "Fenster A ist heute bereits bedient" — bedient
# hatte es niemand. Folge: kein datiertes Tagesartefakt vor 20:00 UTC,
# promotion-gate-daily (14:00 UTC) uebersprang 17 von 18 Laeufen seit 31.8.
# ---------------------------------------------------------------------------


def test_a_skipped_fire_does_not_serve_window_a() -> None:
    d = decide(
        now=_at("11:05"), event_name="workflow_run", producer_conclusion="success",
        todays_runs=[_skipped("09:40"), _skipped("10:41")],
    )
    assert d.run is True, d.reason
    assert d.window == "A"


def test_a_skipped_fire_does_not_serve_window_b() -> None:
    """Ein Fire ab 20:00, der wegen eines roten Producers uebersprungen wurde."""
    d = decide(
        now=_at("21:00"), event_name="workflow_run", producer_conclusion="success",
        todays_runs=[_run("11:10"), _skipped("20:10")],
    )
    assert d.run is True, d.reason
    assert d.window == "B"


def test_a_skipped_fire_does_not_cancel_the_afternoon_net() -> None:
    d = decide(
        now=_at("14:10"), event_name="schedule", producer_conclusion=None,
        todays_runs=[_skipped("09:40"), _skipped("10:41"), _skipped("12:42")],
    )
    assert d.run is True, d.reason
    assert d.window == "net"


def test_an_unknown_worker_state_counts_as_not_served() -> None:
    """Blindheit auf dieser Achse faellt wie jede andere auf LAUFEN.

    Kann der Aufrufer nicht ermitteln, ob der Worker lief (``worked`` fehlt
    oder ist ``None``), darf der Lauf kein Fenster bedienen — sonst kehrt der
    Fehler still zurueck, sobald die Job-Abfrage einmal ausfaellt.
    """
    for run in (_run("11:10", worked=None), {"conclusion": "success", "created_at": "2026-08-31T11:10:00Z"}):
        d = decide(
            now=_at("12:00"), event_name="workflow_run",
            producer_conclusion="success", todays_runs=[run],
        )
        assert d.run is True, run
        assert d.window == "A"


def test_the_measured_day_2026_09_30_gets_its_window_a_run() -> None:
    """Die Fire-Folge des 30.9. (aus der Run-Liste), unter der neuen Regel."""
    fires = ["09:40", "10:41", "12:42", "15:06", "17:06", "19:22", "21:16", "22:28", "22:39", "23:42"]
    runs: list[dict] = []
    ran: list[str] = []
    for fire in fires:
        d = decide(
            now=_at(fire), event_name="workflow_run",
            producer_conclusion="success", todays_runs=list(runs),
        )
        if d.run:
            ran.append(f"{fire}/{d.window}")
            runs.append(_run(fire))
        else:
            runs.append(_skipped(fire))
    # 12:42 liegt hinter Fenster A (Ende 12:30) — das Netz faengt den Tag.
    assert ran == ["12:42/net", "21:16/B"], ran


# ---------------------------------------------------------------------------
# CLI: die Zusammenfuehrung von Run-Liste und Worker-Befund.
# ---------------------------------------------------------------------------


def _cli(capsys, *argv: str) -> str:
    assert main(list(argv)) == 0
    return capsys.readouterr().out


def test_cli_marks_only_listed_ids_as_worked(capsys) -> None:
    runs = json.dumps([
        {"id": 1, "conclusion": "success", "created_at": "2026-08-31T09:40:00Z"},
        {"id": 2, "conclusion": "success", "created_at": "2026-08-31T11:10:00Z"},
    ])
    base = ("--now", "2026-08-31T12:00:00Z", "--event-name", "workflow_run",
            "--producer-conclusion", "success", "--todays-runs", runs)
    # Lauf 2 hat den Worker gefahren -> Fenster A bedient.
    assert "run=False window=A" in _cli(capsys, *base, "--worked-run-ids", "2")
    # Kein Lauf hat gearbeitet -> laufen.
    assert "run=True window=A" in _cli(capsys, *base, "--worked-run-ids", "")
    # Befund fehlt ganz (alter Aufrufer / Abfrage ausgefallen) -> laufen.
    assert "run=True window=A" in _cli(capsys, *base)
    # Muell statt Ids -> laufen, nicht abstuerzen.
    assert "run=True window=A" in _cli(capsys, *base, "--worked-run-ids", "nan\n2x")


# ---------------------------------------------------------------------------
# Kopplung an den Workflow: die Job-Abfrage muss den Job meinen, der arbeitet.
# ---------------------------------------------------------------------------


def test_the_gate_asks_about_the_job_that_actually_does_the_work() -> None:
    """Der Shell-Schritt filtert Jobs ueber ihren NAMEN.

    Wird der Worker-Job umbenannt (oder bekommt er ein ``name:``), faende die
    Abfrage nie wieder einen gelaufenen Worker — jeder Fire liefe (fail-open,
    also laut und teuer, nicht still). Dieser Test haelt Namen und Job
    zusammen, abgeleitet aus dem YAML statt aus einer zweiten Konstante.
    """
    wf = yaml.safe_load(
        (_REPO_ROOT / ".github" / "workflows" / "smc-measurement-benchmark-rolling.yml")
        .read_text(encoding="utf-8")
    )
    jobs = wf["jobs"]
    # Der Worker ist der Job, der den Benchmark selbst faehrt — erkannt am
    # Schritt, nicht am Namen (der Name ist ja gerade das Gepruefte).
    workers = [
        key for key, job in jobs.items()
        if any(s.get("name") == "Run daily rolling benchmark" for s in job.get("steps", []))
    ]
    assert len(workers) == 1, workers
    worker_key = workers[0]
    assert "needs.cadence-gate.outputs.run" in str(jobs[worker_key].get("if", ""))
    # Die API meldet `name`, falls gesetzt, sonst die Job-Id.
    reported_name = jobs[worker_key].get("name", worker_key)

    decide_steps = [
        s for s in jobs["cadence-gate"]["steps"] if s.get("id") == "decide"
    ]
    assert len(decide_steps) == 1
    step = decide_steps[0]
    assert step["env"]["GATE_WORKER_JOB"] == reported_name
    run = step["run"]
    assert "actions/runs/${run_id}/jobs" in run
    assert "${GATE_WORKER_JOB}" in run
    assert '--worked-run-ids "${WORKED}"' in run
