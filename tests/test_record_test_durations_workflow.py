"""Die Aufzeichnung muss die PR-Lane NACHBILDEN, nicht approximieren.

`.test_durations` gewichtet den Shard-Zuschnitt in `ci.yml`. Eine Messung, die
in einer anderen Form entsteht als die Lane, die sie steuert, misst das falsche
System — und das ist keine Theorie, sondern am 2026-08-21 bezahlt: eine lokale
serielle Aufzeichnung (26030 Tests in EINEM Prozess) blähte fünf Tests um das
20- bis 130-fache auf, und auf dem Runner wurde der längste Shard danach
*länger* statt kürzer (358,8 s → 368,8 s, Spreizung 2,12× → 4,86×; PR #4943).

Diese Datei nagelt beides fest: die Form des Workflows und die drei Weigerungen
des Merge-Skripts. Jede Weigerung existiert, weil ihr Ausbleiben eine
FEHLMESSUNG erzeugt, die vollständig aussieht.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.merge_shard_durations import merge_shards
from tests._workflow_yaml import load_workflow

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "record-test-durations.yml"


def _record_step_command() -> str:
    """Der ausgefuehrte Befehl OHNE Kommentarzeilen.

    Beim ersten Entwurf zitierte der Kommentar des Schritts seine eigene
    Zusicherung ("Bewusst OHNE ``--maxfail``") — und der Test darunter wurde
    prompt rot, obwohl der Befehl korrekt war. Ein Waechter, der Prosa mitzaehlt,
    misst die Erklaerung statt der Sache; dieselbe Klasse hat main am 20.8.
    dreizehn Laeufe lang rot gehalten (#4926). Deshalb faellt hier alles weg,
    was mit ``#`` beginnt, bevor irgendetwas geprueft wird.
    """
    workflow = load_workflow(WORKFLOW)
    for step in workflow["jobs"]["record"]["steps"]:
        run = str(step.get("run", ""))
        if "pytest" not in run:
            continue
        return "\n".join(
            line for line in run.split("\n") if not line.strip().startswith("#")
        )
    raise AssertionError("kein Schritt in job 'record' ruft pytest auf")


def test_the_recording_mirrors_the_pr_lane_shape() -> None:
    """Gleiche Aufteilung, gleiche Serialität — sonst misst sie ein anderes System.

    `ci.yml` fährt ``--splits 4 --group N`` OHNE ``-n``. Eine unter xdist
    gemessene Dauer ist nicht die Dauer, die in der Lane anfällt: Worker teilen
    sich Kerne, und die Zeit eines Tests haengt dann an seinen Nachbarn.
    """
    run = _record_step_command()
    assert "--splits 4" in run, "die Aufzeichnung muss dieselbe Aufteilung fahren wie ci.yml"
    assert "--store-durations" in run
    assert " -n " not in run and "-n auto" not in run, (
        "die Aufzeichnung darf nicht unter xdist laufen — die PR-Lane ist innerhalb "
        "eines Shards seriell, und nur diese Zeiten gewichten den Zuschnitt korrekt"
    )


def test_the_recording_never_stops_early() -> None:
    """``--maxfail`` würde alle Gewichte HINTER dem ersten Fehlschlag verschlucken.

    Das Ergebnis waere eine Datei mit einem Loch, das niemand sieht: die fehlenden
    Tests bekommen von pytest-split den Mittelwert, nicht eine Fehlermeldung.
    """
    run = _record_step_command()
    assert "--maxfail" not in run, (
        "eine Aufzeichnung mit --maxfail misst nur bis zum ersten roten Test; der "
        "Rest der Suite bekaeme stillschweigend den Mittelwert"
    )


def test_every_shard_is_recorded_even_if_one_fails() -> None:
    """``fail-fast: false`` — sonst kostet ein roter Shard drei weitere Messungen."""
    workflow = load_workflow(WORKFLOW)
    strategy = workflow["jobs"]["record"]["strategy"]
    assert strategy.get("fail-fast") is False
    assert [str(g) for g in strategy["matrix"]["group"]] == ["1", "2", "3", "4"], (
        "die Matrix muss dieselben vier Gruppen fahren wie ci.yml"
    )


def test_the_workflow_is_dispatch_only() -> None:
    """Kein eigener Cron.

    Die Frage "wann muss neu gemessen werden?" beantwortet bereits der
    Abdeckungs-Wächter über `.test_durations`. Ein zweiter, schwächerer
    Auslöser daneben waere eine weitere unbeobachtete geplante Fläche (#4878).
    """
    workflow = load_workflow(WORKFLOW)
    triggers = workflow["on"] if "on" in workflow else workflow[True]
    assert set(triggers) == {"workflow_dispatch"}, (
        f"erwartet ausschliesslich workflow_dispatch, gefunden: {sorted(triggers)}"
    )


def test_a_missing_shard_is_refused(tmp_path: Path) -> None:
    """Drei von vier Dateien ergeben eine Datei, die VOLLSTAENDIG AUSSIEHT.

    Genau das ist die teure Variante: pytest-split gibt jedem unbekannten Test
    den Mittelwert, meldet aber nichts. Der Zuschnitt waere dann fuer ein
    Viertel der Suite geraten.
    """
    for group in ("1", "2", "3"):
        (tmp_path / f"durations-{group}.json").write_text(
            json.dumps({f"tests/test_{group}.py::test_a": 1.0}), encoding="utf-8"
        )
    with pytest.raises(SystemExit, match="erwartet 4"):
        merge_shards(tmp_path, expected=4)


def test_an_empty_shard_is_refused(tmp_path: Path) -> None:
    """Null Eintraege sind ein Werkzeugfehler, kein Befund."""
    for group in ("1", "2", "3"):
        (tmp_path / f"durations-{group}.json").write_text(
            json.dumps({f"tests/test_{group}.py::test_a": 1.0}), encoding="utf-8"
        )
    (tmp_path / "durations-4.json").write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="leer"):
        merge_shards(tmp_path, expected=4)


def test_overlapping_shards_are_refused(tmp_path: Path) -> None:
    """Zwei Shards mit demselben Test heisst: die Aufteilung war nicht disjunkt.

    Dann misst der Lauf eine andere Zerlegung als die, die in ci.yml faehrt —
    und der zweite Wert ueberschreibt den ersten stillschweigend.
    """
    for group in ("1", "2", "3", "4"):
        (tmp_path / f"durations-{group}.json").write_text(
            json.dumps({"tests/test_same.py::test_a": float(group)}), encoding="utf-8"
        )
    with pytest.raises(SystemExit, match="teilt"):
        merge_shards(tmp_path, expected=4)


def test_the_happy_path_actually_merges(tmp_path: Path) -> None:
    """Positivkontrolle: ohne sie genuegte den drei Weigerungen ein ``raise``.

    Ein Merge-Skript, das IMMER scheitert, besteht jeden der drei Tests oben.
    Diese Probe verlangt, dass der gute Fall auch wirklich vereinigt.
    """
    for group in ("1", "2", "3", "4"):
        (tmp_path / f"durations-{group}.json").write_text(
            json.dumps({f"tests/test_{group}.py::test_a": float(group)}), encoding="utf-8"
        )
    merged = merge_shards(tmp_path, expected=4)
    assert len(merged) == 4
    assert merged["tests/test_3.py::test_a"] == 3.0
