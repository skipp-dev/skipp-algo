"""Der Laufzeit-Waechter des EOD-Flatten-Wrappers, ausgefuehrt statt gelesen.

Grenzgaenger-Sweep 2026-08-22: der Lauf vom 21.8. 15:45 ET hing 8 h 41 min.
``ib.connect()`` war zurueckgekehrt, danach liefen alle vier
ib_async-Startup-Requests in Timeouts und der Prozess stand. Der Schaden war
nicht der verlorene Tag — launchd startet KEINE zweite Instanz eines noch
laufenden Jobs, also fiel auch das 22:45-Folgefeuer aus und jeder weitere Tag
waere ausgefallen. Beweis damals: im ``.err`` fehlt fuer den 21.8. die Zeile
``ET now 16:45 ... skip``, die am 20.8. noch da war.

Die drei Faelle unten sind die volle Matrix. Der Normallauf ist dabei kein
Beiwerk: ohne ihn waere ein Waechter, der einfach ALLES abschiesst, gruen.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# Stub-Verhalten fuer den "python", den der Wrapper aufruft.
_HANG_TERM_OK = "trap 'exit 143' TERM; while true; do sleep 1; done"
_HANG_TERM_DEAF = "trap '' TERM; while true; do sleep 1; done"
_NORMAL = 'echo "eod-flatten: 0 position(s), 0 closed, 0 unfilled, flat=True"; exit 0'


def _stub_venv(tmp_path: Path, flatten_behaviour: str) -> Path:
    """venv-Stub, dessen python die Zielwahl bedient und den Flatten spielt."""
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "activate").write_text("# stub\n", encoding="utf-8")
    (venv / "bin" / "python").write_text(
        "#!/bin/bash\n"
        'for a in "$@"; do\n'
        "  case \"$a\" in\n"
        "    scripts.us_equity_early_closes)\n"
        '       for b in "$@"; do [ "$b" = "trading-day" ] && { echo 1; exit 0; }; done\n'
        '       echo "15 45"; exit 0 ;;\n'
        "    scripts.c13_eod_flatten)\n"
        f"       {flatten_behaviour} ;;\n"
        "  esac\n"
        "done\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (venv / "bin" / "python").chmod(0o755)
    return venv


def _sandbox_repo(tmp_path: Path) -> Path:
    """Wrapper + Gate-Lib in ein tmp-Repo spiegeln.

    Der Wrapper leitet REPO aus seinem EIGENEN Pfad ab und schreibt Gate- und
    Status-Marker nach ``$REPO/cache/live``. Liefe der Test gegen die echte
    Datei, wuerden (a) die Faelle sich das Exactly-once-Marker des Gates
    gegenseitig wegnehmen — unter ``-n 4`` gewinnt einer die noclobber-Wette
    und der Rest bekommt "already ran" — und (b) die Suite in den Baum
    schreiben. Kopiert wird zur Laufzeit, der Test prueft also immer den
    aktuellen Inhalt.
    """
    repo = tmp_path / "repo"
    (repo / "automation" / "launchd").mkdir(parents=True)
    (repo / "cache" / "live").mkdir(parents=True)
    for name in ("run-c13-eod-flatten.sh", "lib_c13_et_gate.sh"):
        (repo / "automation" / "launchd" / name).write_text(
            (REPO / "automation" / "launchd" / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    return repo


def _run(tmp_path: Path, behaviour: str, *, limit: str, grace: str) -> subprocess.CompletedProcess[str]:
    repo = _sandbox_repo(tmp_path)
    env = dict(os.environ)
    env.update(
        {
            "C13_VENV": str(_stub_venv(tmp_path, behaviour)),
            "C13_GATE_NOW_ET_DATE": "2026-08-19",
            "C13_GATE_NOW_ET": "15:45",
            "C13_GATE_NOW_DOW": "3",
            "C13_EOD_FLATTEN_TIMEOUT_SECS": limit,
            "C13_EOD_FLATTEN_KILL_GRACE_SECS": grace,
        }
    )
    env.pop("C13_SKIP_ET_GATE", None)
    result = subprocess.run(
        ["/bin/bash", str(repo / "automation" / "launchd" / "run-c13-eod-flatten.sh")],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(repo),
        timeout=120,
    )
    result.sandbox_repo = repo  # type: ignore[attr-defined]
    return result


def _marker_text(result: subprocess.CompletedProcess[str]) -> str:
    repo: Path = result.sandbox_repo  # type: ignore[attr-defined]
    hits = sorted((repo / "cache" / "live").glob(".eod_flatten_status_*"))
    return hits[-1].read_text(encoding="utf-8") if hits else ""


@pytest.mark.parametrize(
    ("behaviour", "expected_rc_in_marker"),
    [(_HANG_TERM_OK, "rc=143"), (_HANG_TERM_DEAF, "rc=137")],
    ids=["haengt-term-willig", "haengt-term-taub"],
)
def test_watchdog_kills_a_hanging_flatten(
    tmp_path: Path, behaviour: str, expected_rc_in_marker: str
) -> None:
    """Ein haengender Lauf muss sterben — sonst ist der Treiber dauerhaft tot.

    Der TERM-taube Fall belegt die Eskalation auf KILL: ein Prozess, der das
    Signal ignoriert, darf den Job nicht trotzdem blockieren.
    """
    result = _run(tmp_path, behaviour, limit="2", grace="2")

    assert result.returncode == 1, (
        f"Waechter haette mit rc 1 enden muessen.\nstderr:\n{result.stderr}"
    )
    assert "runtime limit" in result.stderr, (
        f"Kein Waechter-Eingriff sichtbar.\nstderr:\n{result.stderr}"
    )
    marker = _marker_text(result)
    assert "flatten-timeout" in marker, (
        f"Marker unterscheidet Haenger nicht von normalem Fehlschlag: {marker!r}"
    )
    assert expected_rc_in_marker in marker, (
        f"Erwartete Signalspur {expected_rc_in_marker} fehlt im Marker: {marker!r}"
    )


def test_watchdog_leaves_a_normal_run_alone(tmp_path: Path) -> None:
    """Positivkontrolle: ohne sie waere ein Waechter, der alles abschiesst, gruen."""
    result = _run(tmp_path, _NORMAL, limit="2", grace="2")

    assert result.returncode == 0, (
        f"Normallauf wurde abgewuergt.\nstderr:\n{result.stderr}"
    )
    assert "runtime limit" not in result.stderr, (
        f"Waechter hat in einen gesunden Lauf eingegriffen.\nstderr:\n{result.stderr}"
    )
    assert _marker_text(result).startswith("SUCCESS"), (
        f"Normallauf hat keinen SUCCESS-Marker: {_marker_text(result)!r}"
    )


def test_the_flatten_turns_sigterm_into_a_clean_exit() -> None:
    """Ohne Handler liefe ``ib.disconnect()`` beim Abschuss nicht.

    Dann bliebe clientId in TWS haengen und der NAECHSTE Lauf scheiterte am
    Connect — der Waechter haette den Ausfall nur verschoben statt behoben.
    """
    import signal as _signal

    from scripts.c13_eod_flatten import install_sigterm_clean_exit

    previous = _signal.getsignal(_signal.SIGTERM)
    try:
        install_sigterm_clean_exit()
        handler = _signal.getsignal(_signal.SIGTERM)
        assert callable(handler), "SIGTERM haengt noch am Default — finally laeuft nicht"
        with pytest.raises(SystemExit) as excinfo:
            handler(_signal.SIGTERM, None)
        assert excinfo.value.code == 128 + int(_signal.SIGTERM)
    finally:
        _signal.signal(_signal.SIGTERM, previous)
