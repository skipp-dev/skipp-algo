"""Der Halbtags-Zielwahlpfad des EOD-Flatten-Wrappers, ausgefuehrt statt gelesen.

Befund Doppelgaenger-Sweep K16 (2026-08-19): ``C13_GATE_NOW_ET_DATE`` war als
Test-Hook dokumentiert, hatte aber **null Setzer und null Tests**. Damit war
der halbe Pfad unbelegt, der an Halbtagen ueber Erfolg oder Schaden
entscheidet: zielt das Gate dort weiter auf 15:45 ET, laeuft der Flatten
NACH dem 13:00-Close — ``reqGlobalCancel`` toetet dann nur noch den
GTC-Schutz, schliessen kann er nichts mehr, und die Position steht ueber Nacht
ungesichert. Genau die Zombie-Klasse, die der Flatten beseitigen soll.

``tests/test_c13_eod_flatten.py`` prueft die Plist-Kandidaten und die
Zielfunktion je fuer sich. Was hier fehlte, ist die Naht dazwischen: dass der
WRAPPER das ET-Datum an ``scripts.us_equity_early_closes`` reicht und dessen
Antwort ins Gate fuettert. Dieser Test faehrt den Wrapper wirklich — mit
gestellter Uhr, damit das Gate no-optet, bevor irgendetwas IBKR beruehrt.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.us_equity_early_closes import EARLY_CLOSES_ET_1300, FULL_CLOSURES_ET
from tests._guard_corpus import iter_tracked_files

REPO = Path(__file__).resolve().parents[1]
WRAPPER = REPO / "automation" / "launchd" / "run-c13-eod-flatten.sh"

# Ein regulaerer Handelstag und ein echter Halbtag aus dem Kalender-SSOT --
# nicht abgeschrieben, sondern entnommen, damit ein Kalender-Update den Test
# mitnimmt statt ihn stillschweigend an einem toten Datum weiterlaufen zu
# lassen.
_EARLY_CLOSE = min(EARLY_CLOSES_ET_1300).isoformat()
_REGULAR = "2026-08-19"
# Ebenfalls dem SSOT entnommen, nicht abgeschrieben: eine Ganztags-Schliessung.
_FULL_CLOSURE = min(FULL_CLOSURES_ET).isoformat()


def _fake_venv(tmp_path: Path) -> Path:
    """Minimaler venv-Stub: activate + ein python, der der echte ist.

    Bewusst kein Rueckgriff auf ein vorhandenes .venv im Baum -- dessen
    Existenz ist eine Umgebungsannahme, und ein uebersprungener Test beweist
    nichts.
    """
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "activate").write_text("# stub\n", encoding="utf-8")
    (venv / "bin" / "python").symlink_to(sys.executable)
    return venv


def _run_wrapper(tmp_path: Path, et_date: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update(
        {
            "C13_VENV": str(_fake_venv(tmp_path)),
            # Der Hook, um den es geht: welches ET-Datum die Zielwahl sieht.
            "C13_GATE_NOW_ET_DATE": et_date,
            # Uhr weit weg vom Ziel -> das Gate no-optet, der Wrapper beendet
            # sich mit 0, bevor c13_eod_flatten (und damit IBKR) laeuft.
            "C13_GATE_NOW_ET": "01:00",
            "C13_GATE_NOW_DOW": "1",
        }
    )
    env.pop("C13_SKIP_ET_GATE", None)
    return subprocess.run(
        ["/bin/bash", str(WRAPPER)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(REPO),
        timeout=120,
    )


@pytest.mark.parametrize(
    ("et_date", "expected_target"),
    [(_REGULAR, "15:45"), (_EARLY_CLOSE, "12:45")],
    ids=["regulaerer-tag", "halbtag"],
)
def test_wrapper_targets_the_days_close(
    tmp_path: Path, et_date: str, expected_target: str
) -> None:
    result = _run_wrapper(tmp_path, et_date)

    assert result.returncode == 0, (
        "Der Wrapper muss beim no-op sauber mit 0 enden, sonst zaehlt launchd "
        f"jeden Kandidatenschuss als Fehlschlag.\nstderr:\n{result.stderr}"
    )
    assert f"target {expected_target}" in result.stderr, (
        f"ET-Datum {et_date} haette auf {expected_target} zielen muessen; die "
        "Gate-Meldung sagt etwas anderes. An Halbtagen bedeutet ein 15:45-Ziel "
        f"einen Flatten NACH dem Close.\nstderr:\n{result.stderr}"
    )
    assert "not the window, skip" in result.stderr, (
        "Der Testaufbau haengt daran, dass das Gate no-optet — sonst haette "
        f"dieser Lauf IBKR beruehrt.\nstderr:\n{result.stderr}"
    )


def test_wrapper_skips_full_market_holidays_before_the_gate(tmp_path: Path) -> None:
    """Grenzgaenger-Sweep 2026-08-22, ausgefuehrt statt gelesen.

    Das ET-Gate lehnt nur Wochenenden ab; an einem ganztaegigen Feiertag gab
    der Kalender brav 16:00 zurueck und der Wrapper lief bis zum Flatten
    durch. Er muss stattdessen aussteigen wie am Wochenende — mit 0 (sonst
    zaehlt launchd einen Fehlschlag) und OHNE die Gate-Meldung, denn das
    Gate darf gar nicht mehr erreicht werden.
    """
    result = _run_wrapper(tmp_path, _FULL_CLOSURE)

    assert result.returncode == 0, (
        f"Feiertags-Skip muss sauber mit 0 enden.\nstderr:\n{result.stderr}"
    )
    assert "not a US trading day" in result.stderr, (
        f"{_FULL_CLOSURE} ist eine Ganztags-Schliessung; der Wrapper haette "
        f"vor dem Gate aussteigen muessen.\nstderr:\n{result.stderr}"
    )
    assert "target " not in result.stderr, (
        "Der Wrapper hat trotz Feiertag ein Gate-Ziel bestimmt — der Skip "
        f"sitzt hinter der Zielwahl statt davor.\nstderr:\n{result.stderr}"
    )


def test_a_trading_day_still_reaches_the_gate(tmp_path: Path) -> None:
    """Positivkontrolle zum Feiertags-Skip: er darf nicht jeden Tag schlucken."""
    result = _run_wrapper(tmp_path, _REGULAR)

    assert "not a US trading day" not in result.stderr, (
        f"Regulaerer Handelstag als Feiertag abgewiesen.\nstderr:\n{result.stderr}"
    )
    assert "target 15:45" in result.stderr, (
        f"Der Wrapper hat das Gate nicht erreicht.\nstderr:\n{result.stderr}"
    )


def test_the_two_calendar_cases_really_differ(tmp_path: Path) -> None:
    """Vakuitaets-Boden: ohne diesen Test wuerde ein Wrapper, der IMMER 15:45
    zielt, den Halbtags-Fall oben nur dann roeten, wenn jemand die Erwartung
    liest. Hier steht die Differenz selbst unter Beobachtung."""
    regular = _run_wrapper(tmp_path / "a", _REGULAR).stderr
    early = _run_wrapper(tmp_path / "b", _EARLY_CLOSE).stderr

    def _target(text: str) -> str:
        marker = "target "
        return text[text.index(marker) + len(marker) :].split(" ", 1)[0]

    assert _target(regular) != _target(early), (
        "Regulaerer Tag und Halbtag ergeben dasselbe Gate-Ziel — die "
        "Kalenderabfrage im Wrapper ist wirkungslos geworden."
    )


def test_the_date_hook_has_a_setter() -> None:
    """C13_GATE_NOW_ET_DATE hatte am 2026-08-19 null Setzer im ganzen Baum.

    Ein Test-Hook ohne Setzer ist kein Hook, sondern ein Kommentar: der Pfad,
    den er oeffnen soll, bleibt unbelegt. Dieser Test macht das Fehlen sichtbar,
    falls die Nutzung wieder verschwindet.
    """
    # iter_tracked_files statt eines Baum-Laufs: Repo-Politik (der Korpus muss
    # git-abgeleitet und in CI identisch sein, tests/test_guard_corpus_tracked_
    # files.py erzwingt das). Der erste Wurf lief hier mit rglob und wurde
    # korrekt rot -- festgehalten, weil derselbe Reflex ("Dateisystem sieht
    # mehr") beim naechsten Wachhund wiederkommt.
    hits = [
        path.name
        for path in iter_tracked_files("test_*.py", (), root=REPO / "tests")
        if "C13_GATE_NOW_ET_DATE" in path.read_text(encoding="utf-8", errors="ignore")
    ]
    assert hits, (
        "kein Test setzt C13_GATE_NOW_ET_DATE — der Halbtags-Zielwahlpfad "
        "waere wieder unbelegt"
    )
