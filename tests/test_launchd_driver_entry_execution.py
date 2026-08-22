"""Jeder launchd-Treiber wird AUSGEFUEHRT, nicht nur gelesen — auf beiden Plattformen.

Grenzgaenger-Sweep 2026-08-22, zweite Haelfte des Portabilitaets-Netzes:
``test_launchd_shell_portability.py`` (#4997) scannt TEXT — er findet nur die
Muster, die schon einmal bezahlt wurden. Das erste Netz ist strukturell: die
Suite laeuft lokal auf macOS/BSD (Pre-Push-Guard) und in CI auf Linux/GNU —
ein Treiber MIT ausfuehrendem Test bekommt den Beide-Plattformen-Beweis
geschenkt (so fiel die mktemp-Falle in #4992 auf, und so fiele ein
GNU-only-Konstrukt lokal auf, BEVOR es in Produktion auf dem Mac bricht).

Gemessen am 22.8.: dieses erste Netz hing an Zufall und Handarbeit —
``run-hold-manager-shadow-daily.sh`` hatte NULL Test-Referenzen, und welcher
Treiber ueberhaupt ausgefuehrt wird, war eine einmalige Grep-Heuristik. Dieser
Test mechanisiert es: Population von PLATTE (jeder neue Treiber ist
automatisch drin), jeder Treiber laeuft seinen Eintrittspfad im Sandkasten.

Sicherheit der Ausfuehrung (ueber die volle Population gemessen, 22.8.):
vor dem ET-Gate macht KEIN Treiber Netz-/Keychain-/Git-Zugriffe (zwei
Grep-Treffer waren Kommentare); die gesourcten Libs sind beim Sourcen
seiteneffektfrei (nur Zuweisungen + uname-Weiche); der einzige Gate-lose
Treiber (reconcile) endet auf leerem cache/live nachweislich VOR dem Push
(SUCCESS:no-audit-file, run-c13-reconcile.sh:82ff). Der Sandkasten kopiert
die Treiber in ein tmp-Repo (REPO leitet sich aus dem Skriptpfad ab), stellt
ein Stub-venv und stellt die Gate-Uhr weit weg vom Ziel.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LAUNCHD = REPO / "automation" / "launchd"

#: Population von PLATTE — Handlisten sind die Bug-Klasse (Doppelgaenger K5).
DRIVERS = sorted(LAUNCHD.glob("run-*.sh"))

#: Boden gegen ein vakuum-leeres Glob (Muster: #4997 / MARKER_DIRS-Zeuge).
_MIN_DRIVERS = 12

#: Treiber OHNE ET-Gate: fuer sie gibt es keinen generischen No-Op-Pfad, ihr
#: Eintrittspfad braucht eine EIGENE Erwartung unten. Ein neuer Gate-loser
#: Treiber muss hier BEWUSST eingetragen werden (mit Erwartung), sonst rot —
#: genau der Stolperdraht: "faehrt beim ersten Feuer ungeprueft" darf nicht
#: wieder still passieren.
_GATELESS_EXPECTED = {"run-c13-reconcile.sh"}

#: Catchup-Treiber (imbalance) exiten am Gate-Skip ABSICHTLICH nicht (B6-Fix
#: #4840: Skip setzt nur C13_CATCHUP_EXCLUDE_TODAY=1, der Backfill laeuft
#: weiter). Der Sandkasten setzt C13_CATCHUP_LOOKBACK_DAYS=0: kein
#: Rueckstau, heute ausgeschlossen -> deterministischer No-Op, und die
#: Catchup-Maschinerie (inkl. der BSD/GNU-date-Weiche in lib_c13_catchup)
#: laeuft trotzdem einmal durch.


def _gated(driver: Path) -> bool:
    return "c13_require_et_window" in driver.read_text(encoding="utf-8")


def _sandbox(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """Tmp-Repo mit allen Treibern+Libs, Stub-venv, isoliertem HOME."""
    repo = tmp_path / "repo"
    (repo / "automation" / "launchd").mkdir(parents=True)
    (repo / "cache" / "live").mkdir(parents=True)
    for src in LAUNCHD.glob("*.sh"):
        dst = repo / "automation" / "launchd" / src.name
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        dst.chmod(0o755)

    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "activate").write_text("# stub\n", encoding="utf-8")
    # Stub-python: bedient das us_equity_early_closes-Interface (eod-flatten
    # fragt seit #4990 VOR dem Gate 'trading-day' ab — ein leeres Echo hiesse
    # Feiertag und der Lauf endete am falschen Skip); alles andere endet 0
    # und schreibt nichts — der Eintrittspfad der SHELL ist das Messobjekt.
    # Muster: _stub_venv in test_c13_eod_flatten_target_selection.py.
    (venv / "bin" / "python").write_text(
        "#!/bin/bash\n"
        'for a in "$@"; do\n'
        '  case "$a" in\n'
        "    scripts.us_equity_early_closes)\n"
        '       for b in "$@"; do [ "$b" = "trading-day" ] && { echo 1; exit 0; }; done\n'
        '       echo "15 45"; exit 0 ;;\n'
        "  esac\n"
        "done\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (venv / "bin" / "python").chmod(0o755)

    home = tmp_path / "home"
    home.mkdir()
    # Defensive Stubs: kein Treiber erreicht sie auf dem No-Op-Pfad (gemessen),
    # aber ein kuenftiger Treiber, der VOR dem Gate notifiziert oder den
    # Keychain fragt, soll den Test roeten statt den Desktop zu bespielen.
    stubbin = tmp_path / "bin"
    stubbin.mkdir()
    for tool in ("osascript", "security"):
        p = stubbin / tool
        p.write_text(f'#!/bin/bash\necho "SANDBOX-VERLETZUNG: {tool} erreicht" >&2\nexit 97\n', encoding="utf-8")
        p.chmod(0o755)

    env = dict(os.environ)
    env.update(
        {
            "C13_VENV": str(venv),
            "HOME": str(home),
            "PATH": f"{stubbin}:{env.get('PATH', '')}",
            # Uhr weit weg von JEDEM Gate-Ziel (07:30-17:30 ET) -> Skip.
            "C13_GATE_NOW_ET": "03:00",
            "C13_GATE_NOW_DOW": "3",
            # Catchup-Treiber: kein Rueckstau-Fenster -> deterministischer
            # No-Op trotz leerem Marker-Verzeichnis (siehe Kommentar oben).
            "C13_CATCHUP_LOOKBACK_DAYS": "0",
        }
    )
    env.pop("C13_SKIP_ET_GATE", None)
    env.pop("C13_GATE_NOW_ET_DATE", None)
    return repo, env


def test_population_floor() -> None:
    assert len(DRIVERS) >= _MIN_DRIVERS, (
        f"nur {len(DRIVERS)} Treiber unter {LAUNCHD} — Glob gebrochen oder "
        "Checkout unvollstaendig; jede Zusicherung darunter waere vakuum"
    )


def test_gateless_set_is_exactly_the_documented_one() -> None:
    """Ein NEUER Gate-loser Treiber faehrt sonst beim ersten Schedule-Fire
    ungeprueft (Erstflug-Regel) — er muss hier bewusst eingetragen und unten
    mit einer eigenen Eintritts-Erwartung versehen werden."""
    gateless = {d.name for d in DRIVERS if not _gated(d)}
    assert gateless == _GATELESS_EXPECTED, (
        f"Gate-lose Treiber auf Platte: {sorted(gateless)}, dokumentiert: "
        f"{sorted(_GATELESS_EXPECTED)} — Eintrag + Eintritts-Erwartung ergaenzen"
    )


def test_every_driver_parses_on_this_platform() -> None:
    """bash -n: voller Syntax-Parse — lokal gegen bash 3.2, in CI gegen GNU.

    Schleife statt ``parametrize``: der Vakuitaets-Waechter kann einen
    Boden-Assert nur im SELBEN Scope sehen, und eine leere Parametrisierung
    waere ein gruener Waechter ueber nichts (Hausform:
    test_launchd_shell_portability.py).
    """
    drivers = DRIVERS
    assert len(drivers) >= _MIN_DRIVERS, (
        f"nur {len(drivers)} Treiber gefunden — sonst prueft dies nichts"
    )
    problems: list[str] = []
    for driver in drivers:
        proc = subprocess.run(
            ["/bin/bash", "-n", str(driver)], capture_output=True, text=True, timeout=30
        )
        if proc.returncode != 0:
            problems.append(f"{driver.name}: {proc.stderr.strip()}")
    assert not problems, "Treiber parsen nicht auf dieser Plattform:\n" + "\n".join(problems)


def test_every_gated_driver_entry_path_runs_to_the_gate_skip(tmp_path: Path) -> None:
    """Der Eintrittspfad (Zeile 1 bis Gate) LAEUFT auf dieser Plattform.

    Lokal (macOS/BSD) und in CI (Linux/GNU) — zusammen der Beide-Plattformen-
    Beweis, den der Text-Scanner (#4997) nicht liefern kann. Ein `timeout`
    oder `date -d` vor dem Gate roetet hier auf dem Mac, BEVOR es beim ersten
    echten Feuer den Treiber still legt.
    """
    gated = [d for d in DRIVERS if _gated(d)]
    assert len(gated) >= _MIN_DRIVERS - len(_GATELESS_EXPECTED), (
        f"nur {len(gated)} gegatete Treiber — Erkennung gebrochen, dieser "
        "Waechter misst sonst nichts"
    )
    problems: list[str] = []
    for i, driver in enumerate(gated):
        repo, env = _sandbox(tmp_path / f"d{i}")
        proc = subprocess.run(
            ["/bin/bash", str(repo / "automation" / "launchd" / driver.name)],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(repo),
            timeout=60,
        )
        if proc.returncode != 0:
            problems.append(
                f"{driver.name}: Eintrittspfad bricht (rc={proc.returncode})\n{proc.stderr}"
            )
            continue
        if "SANDBOX-VERLETZUNG" in proc.stderr:
            problems.append(
                f"{driver.name}: erreicht osascript/security VOR dem Gate\n{proc.stderr}"
            )
            continue
        # Die Skip-Meldung beweist, dass das GATE erreicht wurde — nicht
        # irgendein frueherer exit 0 (leere-Ausgabe-Vakuum).
        if not re.search(r"not the window, skip|is a weekend", proc.stderr):
            problems.append(
                f"{driver.name}: endete 0 OHNE Gate-Skip — Eintrittspfad kam "
                f"nie beim Gate an\n{proc.stderr}"
            )
    assert not problems, "\n\n".join(problems)


def test_reconcile_entry_path_stops_at_the_no_audit_exit(tmp_path: Path) -> None:
    """Der eine Gate-lose Treiber: sein deterministischer No-Op-Pfad ist der
    No-Audit-Exit (leeres cache/live) — Marker SUCCESS:no-audit-file, Ende
    VOR jedem Push. Genau der Pfad, der am 19.-21.8. taeglich lief."""
    repo, env = _sandbox(tmp_path)
    proc = subprocess.run(
        ["/bin/bash", str(repo / "automation" / "launchd" / "run-c13-reconcile.sh")],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(repo),
        timeout=60,
    )
    assert proc.returncode == 0, (
        f"reconcile Eintrittspfad bricht (rc={proc.returncode}):\n{proc.stderr}"
    )
    markers = sorted((repo / "cache" / "live").glob(".reconcile_status_*"))
    assert markers, "reconcile endete 0 ohne Status-Marker — falscher Pfad"
    content = markers[-1].read_text(encoding="utf-8")
    assert content.startswith("SUCCESS:no-audit-file"), (
        f"unerwarteter Marker {content!r} — der Sandkasten-Pfad hat sich "
        "verschoben; pruefen, ob noch VOR dem Push beendet wird"
    )
