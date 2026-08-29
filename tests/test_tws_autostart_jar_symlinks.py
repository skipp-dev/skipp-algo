"""Der Autostart darf sich nicht auf handgesetzte Jar-Symlinks verlassen.

Bezahlt am 2026-08-29 (Paper-Flip-Readiness, Gate 6): der TWS-"Offline"-Build
hatte ``jts4launch-1045-macos-arm`` am 5.8. gegen ein NEU BENANNTES ``.dat``
getauscht. Der am 2.8. von Hand gesetzte ``*.jar``-Symlink zeigte seither ins
Leere, IBCs Classpath-Glob sammelt nur ``*.jar``, und weil ``jclient/LoginFrame``
genau in ``jts4launch-*.dat`` liegt, starb IBC an jedem Werktag mit
``exit code=1107``. Gemessen: 8 DEGRADED / 6 SUCCESS in 14 Tagen — und ALLE
sechs SUCCESS trugen ``already-running``, also einen Handstart. Kein einziger
IBC-getriebener Start gelang zwischen dem 5. und dem 29.8.

Der Skript-Kopf behauptete woertlich *"The offline build never self-updates, so
the symlinks are durable"*. Diese Praemisse ist widerlegt; eine handgepflegte
Liste kann ihre eigene Drift nicht fangen (Klasse
``skipp-hardcoded-guard-list-cannot-catch-its-own-drift``). Der Treiber leitet
die Symlink-Population deshalb vor jedem Start aus den ``.dat``-Dateien ab.

Diese Datei fuehrt den echten Treiber AUS statt seinen Text zu lesen: der
Sandkasten baut alle drei Zustaende nach, die auf der Platte real vorkamen.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "automation" / "launchd" / "run-c13-tws-autostart.sh"

#: Ein Port, auf dem nichts lauscht — sonst entscheidet der Zustand der
#: Entwicklermaschine (laeuft TWS gerade?) ueber den Testpfad. 9 ist
#: "discard" und in dieser Umgebung nachweislich zu; der Treiber laeuft
#: damit deterministisch bis zur IBC-Pruefung und endet dort DEGRADED.
_CLOSED_PORT = "9"


def _sandbox(tmp_path: Path) -> tuple[Path, Path, dict[str, str]]:
    """Repo-Kopie mit Treiber+Lib, TWS-Jars-Attrappe, leerem IBC_HOME."""
    repo = tmp_path / "repo"
    (repo / "automation" / "launchd").mkdir(parents=True)
    (repo / "cache" / "live").mkdir(parents=True)
    for name in ("run-c13-tws-autostart.sh", "lib_c13_et_gate.sh"):
        src = REPO / "automation" / "launchd" / name
        dst = repo / "automation" / "launchd" / name
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        dst.chmod(0o755)

    jars = tmp_path / "Applications" / "Trader Workstation 10.45" / "jars"
    jars.mkdir(parents=True)

    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "C13_SKIP_ET_GATE": "1",
        "C13_TWS_PATH": str(tmp_path / "Applications"),
        "C13_TWS_MAJOR_VRSN": "10.45",
        "C13_TWS_PORT": _CLOSED_PORT,
        "C13_IBC_HOME": str(tmp_path / "ibc-does-not-exist"),
    }
    (tmp_path / "home").mkdir()
    return repo, jars, env


def _run(repo: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/bash", str(repo / "automation" / "launchd" / "run-c13-tws-autostart.sh")],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _marker(repo: Path) -> str:
    hits = sorted((repo / "cache" / "live").glob(".tws_autostart_status_*"))
    assert hits, "der Treiber hat keinen Marker geschrieben"
    return hits[-1].read_text(encoding="utf-8").strip()


def test_a_renamed_dat_gets_a_fresh_link_and_the_dead_one_goes(tmp_path: Path) -> None:
    """Der 5.8.-Fall, exakt nachgebaut: .dat umbenannt, alter Link tot.

    Ohne die Ableitung bleibt der tote Link im Classpath und IBC stirbt an
    ``jclient/LoginFrame`` — das war 24 Tage lang der Produktionszustand.
    """
    repo, jars, env = _sandbox(tmp_path)
    neu = jars / "jts4launch-1045-macos-arm_1785962214000.dat"
    neu.write_bytes(b"PK\x03\x04neu")
    tot = jars / "jts4launch-1045-macos-arm_1784580295000.jar"
    tot.symlink_to("jts4launch-1045-macos-arm_1784580295000.dat")  # Ziel weg
    assert tot.is_symlink() and not tot.exists(), "Vorbedingung: Link ist tot"

    proc = _run(repo, env)

    frisch = jars / "jts4launch-1045-macos-arm_1785962214000.jar"
    assert frisch.is_symlink() and frisch.exists(), (
        f"kein Link auf das neue .dat angelegt; stdout={proc.stdout} stderr={proc.stderr}"
    )
    assert os.readlink(frisch) == neu.name, "der Link muss RELATIV zeigen, nicht absolut"
    assert not tot.is_symlink(), "der tote Link blieb im Classpath stehen"
    assert "jarlinks-repaired=2" in _marker(repo), (
        f"die Reparatur steht nicht im Marker: {_marker(repo)}"
    )
    assert "selbst aktualisiert" in proc.stderr, "die Reparatur war nicht laut"


def test_a_healthy_install_is_left_alone_and_stays_quiet(tmp_path: Path) -> None:
    """Positivkontrolle: ohne Drift kein Eingriff und KEIN Marker-Rauschen.

    Ohne diese Zeile koennte die Ableitung jeden Lauf "reparieren" und der
    Marker traege dauerhaft einen Vermerk, den niemand mehr liest.
    """
    repo, jars, env = _sandbox(tmp_path)
    dat = jars / "jts4launch-1045-macos-arm_1785962214000.dat"
    dat.write_bytes(b"PK\x03\x04neu")
    (jars / "jts4launch-1045-macos-arm_1785962214000.jar").symlink_to(dat.name)

    proc = _run(repo, env)

    assert "jarlinks-repaired" not in _marker(repo), (
        f"gesunder Baum meldet trotzdem eine Reparatur: {_marker(repo)}"
    )
    assert "repariert" not in proc.stderr


def test_every_dat_gets_a_link_not_just_the_first(tmp_path: Path) -> None:
    """Population, nicht Stichprobe: die echte Installation traegt 13 Paare."""
    repo, jars, env = _sandbox(tmp_path)
    namen = [f"lib-{i}_17859622140{i:02d}.dat" for i in range(6)]
    for n in namen:
        (jars / n).write_bytes(b"PK\x03\x04x")

    _run(repo, env)

    fehlend = [n for n in namen if not (jars / n[:-4]).with_suffix(".jar").exists()]
    assert not fehlend, f"ohne Link geblieben: {fehlend}"
    assert "jarlinks-repaired=6" in _marker(repo)


def test_the_repair_runs_before_the_port_check(tmp_path: Path) -> None:
    """Ein laufender TWS darf die Heilung nicht verschlucken.

    Faellt die Selbst-Aktualisierung an einem Tag an, an dem TWS noch aus dem
    Vortag laeuft, wuerde eine Reparatur NACH der Port-Pruefung erst am
    naechsten Kaltstart greifen — also genau dann, wenn sie zu spaet kommt.
    """
    repo, jars, env = _sandbox(tmp_path)
    (jars / "jts4launch_1785962214000.dat").write_bytes(b"PK\x03\x04x")
    # Port, auf dem WIR lauschen: der Treiber nimmt den already-running-Zweig.
    import socket

    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    env["C13_TWS_PORT"] = str(srv.getsockname()[1])
    try:
        _run(repo, env)
    finally:
        srv.close()

    assert (jars / "jts4launch_1785962214000.jar").exists(), (
        "bei laufendem TWS wurde nicht repariert — die Heilung kaeme einen Tag zu spaet"
    )
    marker = _marker(repo)
    assert "already-running" in marker and "jarlinks-repaired=1" in marker, marker


def test_a_missing_jars_directory_is_survivable(tmp_path: Path) -> None:
    """Kein Verzeichnis, kein Absturz: der Treiber muss trotzdem sein Urteil faellen."""
    repo, _jars, env = _sandbox(tmp_path)
    env["C13_TWS_PATH"] = str(tmp_path / "gibt-es-nicht")

    proc = _run(repo, env)

    assert proc.returncode == 1, "erwartet: DEGRADED an der IBC-Pruefung"
    assert "ibc-missing" in _marker(repo)


@pytest.mark.parametrize("marker_text", ["already-running", "started-in:"])
def test_the_marker_still_distinguishes_a_handstart_from_a_real_start(
    marker_text: str,
) -> None:
    """Text-Pin mit Grund: die Unterscheidung ist der Triage-Hebel.

    Alle sechs SUCCESS-Marker zwischen dem 5. und 28.8. trugen
    ``already-running`` — ein Handstart, kein geglueckter Autostart. Wer nur
    das Verdikt liest, haelt einen toten Autostart drei Wochen fuer gesund.
    Verschwindet eine der beiden Nachrichten aus dem Treiber, faellt genau
    diese Unterscheidung weg.
    """
    assert marker_text in DRIVER.read_text(encoding="utf-8")
