"""`.test_durations` darf nicht verrotten — und der Boden darf nicht zurückbleiben.

`ci.yml` nennt seine Aufteilung *duration-balanced*. Die Gewichte dafür kommen
aus `.test_durations`. Für jeden Test, den die Datei nicht kennt, setzt
`pytest-split` kommentarlos den MITTELWERT ein — bei einem Median von 0,82 ms
gegen ein Mittel von 58,13 ms (Faktor 70, gemessen 2026-08-20) heißt das: eine
unbekannte Datei gilt als exakt durchschnittlich schwer, egal was sie kostet.

Am 2026-08-21 kannte die Datei **73,2 %** der 1705 Testdateien. Sie stammt vom
23.7. — dem Wurzel-Commit der Historie — und verliert rund 6,7 Prozentpunkte pro
Woche, weil neue Testdateien dazukommen und niemand nachmisst.

## Zwei Zusicherungen, nicht eine

`test_the_duration_map_still_covers_the_suite` hält den Ist-Stand fest: fällt die
Abdeckung unter den Boden, wird es rot und die Meldung nennt den Reparaturweg.

`test_the_floor_does_not_lag_the_measurement` ist der Grund, warum hier kein
Satz der Form „der Boden wird angehoben, sobald die Runner-Messung landet" steht.
Solche Sätze feuern nicht (CLAUDE.md, *Forward promises need a mechanism*).
Stattdessen rötet die zweite Zusicherung, sobald die tatsächliche Abdeckung mehr
als `_MAX_FLOOR_LAG` Punkte über dem Boden liegt — und verlangt, den Boden im
selben PR nachzuziehen. Landet die Runner-Aufzeichnung bei ~100 %, ist der
Abstand zu 73 sofort zu groß und der Boden MUSS auf ≥ 85 steigen. Kein
menschliches Gedächtnis beteiligt.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests._guard_corpus import iter_tracked_files

REPO_ROOT = Path(__file__).resolve().parent.parent
DURATIONS = REPO_ROOT / ".test_durations"

# 2026-08-21 gemessen: 1248 von 1705 Testdateien = 73,2 %. Der Boden ist der
# HEUTIGE Stand, nicht das Ziel — er stoppt das Weiterverrotten sofort, ohne
# eine Messung zu behaupten, die es noch nicht gibt.
#
# 2026-08-21, nachgezogen: die erste Aufzeichnung AUF DEM RUNNER (Lauf
# 32508396491, vier Shards je in eigenem Prozess) hebt die Abdeckung auf
# 1707 von 1709 Testdateien = 99,9 %. Der Ratschen-Test hat den Nachzug
# erzwungen, wie gebaut — 26,9 Punkte Abstand bei erlaubten 15.
#
# 95,0 statt 99,0: die beiden fehlenden Dateien sind der Rest, den ein Lauf
# nicht erfasst (vollstaendig uebersprungene Module), und normale Zu- und
# Abgaenge im Testbestand duerfen den Boden nicht sofort wieder reissen.
# 4,9 Punkte Luft, und der Ratschen-Test zieht selbst nach, sobald eine
# spaetere Messung dauerhaft hoeher liegt.
_COVERAGE_FLOOR = 95.0

# Wie weit der Boden hinter der Wirklichkeit herhinken darf, bevor er nachgezogen
# werden MUSS. 15 Punkte lassen normalen Zuwachs zu und erzwingen den Nachzug,
# sobald eine Neuaufzeichnung die Abdeckung sprunghaft hebt.
_MAX_FLOOR_LAG = 15.0

_RECORD_COMMAND = (
    "Workflow `record-test-durations` von Hand ausloesen (workflow_dispatch) — "
    "er misst auf dem RUNNER und oeffnet den PR. Lokal aufzeichnen NICHT: eine "
    "lokale serielle Aufzeichnung blaehte am 2026-08-21 fuenf Tests um das 20- "
    "bis 130-fache auf und verschlechterte die Balance (PR #4943)."
)


def _python_test_files() -> set[str]:
    """Die GIT-gefuehrte Liste, kein Arbeitsbaum-Walk.

    Ein ungetrackter Streuner (`tests/test_scratch.py` aus einer Fehlersuche)
    wuerde den Nenner heben und die Abdeckung schlechter aussehen lassen, als
    sie ist -- lokal anders als in CI. Der Korpus muss identisch sein, sonst
    misst der Waechter die Aufraeumdisziplin des Entwicklers statt der Datei.
    """
    return {
        p.relative_to(REPO_ROOT).as_posix()
        for p in iter_tracked_files("tests/test_*.py", exclude_dirs=("__pycache__",))
    }


def duration_file_coverage(durations: dict[str, float], test_files: set[str]) -> float:
    """Anteil der Testdateien mit mindestens einem aufgezeichneten Test, in Prozent."""
    if not test_files:
        return 100.0
    recorded = {key.split("::")[0] for key in durations}
    return 100.0 * len(test_files & recorded) / len(test_files)


def _measured_coverage() -> float:
    durations = json.loads(DURATIONS.read_text(encoding="utf-8"))
    return duration_file_coverage(durations, _python_test_files())


def test_the_duration_map_still_covers_the_suite() -> None:
    coverage = _measured_coverage()
    assert coverage >= _COVERAGE_FLOOR, (
        f".test_durations kennt nur {coverage:.1f} % der {len(_python_test_files())} "
        f"Testdateien, Boden ist {_COVERAGE_FLOOR:.0f} %. Jede unbekannte Datei "
        f"bekommt von pytest-split den MITTELWERT, also ein erfundenes Gewicht. "
        f"{_RECORD_COMMAND}"
    )


def test_the_floor_does_not_lag_the_measurement() -> None:
    """Der Boden muss der Wirklichkeit folgen, sonst schuetzt er nichts mehr.

    Ein Boden von 73 gegen eine echte Abdeckung von 100 laesst 27 Punkte
    Verrottung zu, bevor irgendetwas rot wird — der Waechter waere dann fuer
    Monate wirkungslos, ohne dass man es ihm ansieht.
    """
    coverage = _measured_coverage()
    lag = coverage - _COVERAGE_FLOOR
    assert lag <= _MAX_FLOOR_LAG, (
        f"die Abdeckung liegt bei {coverage:.1f} %, der Boden bei "
        f"{_COVERAGE_FLOOR:.0f} % — {lag:.1f} Punkte Abstand, erlaubt sind "
        f"{_MAX_FLOOR_LAG:.0f}. _COVERAGE_FLOOR in dieser Datei im SELBEN PR "
        f"nachziehen (auf hoechstens {coverage:.0f}, sinnvoll etwa "
        f"{coverage - 10:.0f}), sonst schuetzt der Boden nichts mehr."
    )


def test_the_coverage_measure_is_not_vacuous() -> None:
    """Positivkontrolle — sonst genuegte der Messfunktion ein ``return 100.0``.

    Ohne diese Probe koennte `duration_file_coverage` konstant 100 liefern und
    beide Zusicherungen oben blieben fuer immer gruen.
    """
    files = {"tests/test_a.py", "tests/test_b.py", "tests/test_c.py", "tests/test_d.py"}
    assert duration_file_coverage({}, files) == 0.0
    assert duration_file_coverage({"tests/test_a.py::t": 1.0}, files) == 25.0
    assert duration_file_coverage({f"{f}::t": 1.0 for f in files}, files) == 100.0
    # Ein Eintrag fuer eine geloeschte Datei darf die Abdeckung NICHT heben.
    assert duration_file_coverage({"tests/test_weg.py::t": 1.0}, files) == 0.0
