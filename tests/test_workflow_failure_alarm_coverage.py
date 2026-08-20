"""Der Fehleralarm muss die merge-kritischen Workflows wirklich sehen.

Hintergrund (2026-08-20). Die Branch-Protection ging von
``strict_required_status_checks_policy: true`` auf ``false``: ein PR muss seinen
Kopf nicht mehr auf ``main`` nachziehen, bevor er merged. Damit wird der
main-Lauf zum Rueckfangnetz fuer den semantischen Konflikt zweier je gruener
PRs. Ein Rueckfangnetz zaehlt aber nur, wenn sein Reissen jemand bemerkt.

Am selben Tag gemessen: der Grafana-Alarm ``lo-workflow-run-failed`` hatte
**8** Zeitreihen bei **26** konfigurierten Workflow-IDs, und
``smc-fast-pr-gates`` — der einzige required Check — war in keiner der beiden
Mengen. Die Liste lebt ausschliesslich in ``GITHUB_WORKFLOW_MONITOR_IDS`` auf
dem live_overlay_daemon; kein Repo-Artefakt deklariert oder prueft sie, und die
Alarmregel steht auf ``noDataState: OK``, womit eine fehlende Zeitreihe genau
kein Signal ist.

Diese Datei pinnt die Entscheidungslogik des Waechters, nicht seinen Wortlaut.
Die Live-Abfrage selbst laeuft taeglich im meta-watchdog.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.check_workflow_failure_alarm_coverage import (
    REQUIRED_WORKFLOWS,
    RUN_PAGE_SIZE,
    evaluate,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
WATCHDOG = REPO_ROOT / ".github" / "workflows" / "meta-watchdog.yml"

NAMES = {
    "smc-fast-pr-gates.yml": "smc-fast-pr-gates",
    "ci.yml": "CI",
    "harmlos.yml": "harmlos",
}


def test_the_required_set_names_the_merge_critical_workflows() -> None:
    """Ohne diese zwei ist der Waechter Dekoration.

    ``smc-fast-pr-gates`` ist der einzige required Check und der einzige Ort,
    an dem ruff, actionlint, zizmor, der TS-Vakuitaets-Guard, der Docker-Bau
    samt Start-Probe und die Manifest-Drift-Pruefungen ueberhaupt laufen.
    ``ci.yml`` faehrt auf main die volle Suite.
    """
    assert "smc-fast-pr-gates.yml" in REQUIRED_WORKFLOWS
    assert "ci.yml" in REQUIRED_WORKFLOWS
    for datei, grund in REQUIRED_WORKFLOWS.items():
        assert len(grund) > 40, (
            f"{datei} steht ohne belastbare Begruendung in der Liste -- ein Eintrag, "
            "dessen Grund niemand kennt, wird beim naechsten Aufraeumen geloescht."
        )


def test_a_workflow_that_runs_but_is_unobserved_is_a_finding() -> None:
    """Der Fall, der am 20.8. real war: laeuft auf main, hat keine Zeitreihe."""
    blind, ok, stumm = evaluate(
        {"smc-fast-pr-gates.yml": "x" * 50},
        NAMES,
        in_page={"smc-fast-pr-gates"},
        observed={"CI"},
    )
    assert not ok and not stumm
    assert len(blind) == 1
    assert "KEINE Zeitreihe" in blind[0]


def test_a_workflow_without_a_run_in_the_window_yields_no_verdict() -> None:
    """Die Falle, die einen naiven Waechter jedes Wochenende falsch feuern liesse.

    Die Bruecke sieht nur EINE Seite der neuesten main-Laeufe; am 20.8. waren
    das rund fuenf Stunden. Ohne Lauf im Fenster gibt es keine Zeitreihe --
    das ist erwartbar und darf kein Fehlschlag sein. Es darf aber auch kein
    Bestehen sein, sonst meldet der Waechter gruen, ohne geprueft zu haben.
    """
    blind, ok, stumm = evaluate(
        {"smc-fast-pr-gates.yml": "x" * 50},
        NAMES,
        in_page={"CI"},
        observed={"CI"},
    )
    assert not blind, "ohne Lauf im Fenster darf nichts rot werden"
    assert not ok, "und es darf auch nichts als geprueft gelten"
    assert len(stumm) == 1 and "keine Aussage" in stumm[0]


def test_a_renamed_or_deleted_workflow_is_a_finding_not_a_pass() -> None:
    """Umbenennen darf den Waechter nicht still leerlaufen lassen.

    Der Schluessel ist der DATEIname; der Anzeigename steht im YAML und laesst
    sich aendern. Faende die Aufloesung nichts und liefe der Waechter weiter
    gruen, waere genau die Vakuitaet erreicht, gegen die er gebaut ist.
    """
    blind, ok, stumm = evaluate(
        {"gibt-es-nicht.yml": "x" * 50},
        NAMES,
        in_page={"CI"},
        observed={"CI"},
    )
    assert not ok and not stumm
    assert len(blind) == 1 and "kein Workflow dieses Dateinamens" in blind[0]


def test_the_happy_path_actually_passes() -> None:
    """Positivkontrolle: sonst koennte alles oben auch durch einen Dauer-Rotton entstehen."""
    blind, ok, stumm = evaluate(
        {"smc-fast-pr-gates.yml": "x" * 50, "ci.yml": "y" * 50},
        NAMES,
        in_page={"smc-fast-pr-gates", "CI"},
        observed={"smc-fast-pr-gates", "CI", "sonstiges"},
    )
    assert not blind and not stumm
    assert len(ok) == 2


def test_the_page_size_matches_the_bridge() -> None:
    """Eine groessere Seite als die Bruecke wuerde Fehlalarm erzeugen.

    ``services/live_overlay_daemon/config.py`` gibt ``per_page`` mit 100 vor.
    Sieht dieses Skript mehr Laeufe als die Bruecke, haelt es Workflows fuer
    'im Fenster', die sie nie zu Gesicht bekommt -- und fordert eine Zeitreihe,
    die es nicht geben kann.
    """
    quelle = (REPO_ROOT / "services" / "live_overlay_daemon" / "config.py").read_text(
        encoding="utf-8"
    )
    marker = "def github_workflow_per_page"
    assert marker in quelle, "die per_page-Vorgabe ist umgezogen -- Kopplung neu pruefen"
    block = quelle[quelle.index(marker) : quelle.index(marker) + 700]
    assert "100" in block, (
        "die Bruecken-Vorgabe fuer per_page ist nicht mehr 100; RUN_PAGE_SIZE "
        f"({RUN_PAGE_SIZE}) muss ihr folgen, sonst misst der Waechter ein anderes Fenster."
    )
    assert RUN_PAGE_SIZE <= 100


@pytest.fixture(scope="module")
def watchdog() -> dict:
    return yaml.safe_load(WATCHDOG.read_text(encoding="utf-8"))


def test_the_check_runs_daily_and_can_fail_the_job(watchdog: dict) -> None:
    """Ein Waechter, den kein Zeitplan startet, ist ein Skript im Repo.

    Und einer, dessen Fehlschlag den Job nicht rot macht, ist eine Notiz.
    """
    assert "schedule" in (watchdog.get(True) or watchdog.get("on")), (
        "meta-watchdog laeuft nicht mehr nach Zeitplan -- die Abdeckungspruefung "
        "wuerde dann nur noch auf Zuruf laufen."
    )
    steps = watchdog["jobs"]["probe"]["steps"]
    schritt = next((s for s in steps if s.get("id") == "alarm_coverage"), None)
    assert schritt is not None, "der Abdeckungs-Schritt ist verschwunden"
    assert "scripts.check_workflow_failure_alarm_coverage" in schritt["run"], (
        "der Schritt ruft das Pruefskript nicht mehr auf"
    )
    assert "GRAFANA_API_KEY" in (schritt.get("env") or {}), (
        "ohne Token kann der Schritt die Metrik nicht lesen und meldet ewig 'ungeprueft'"
    )

    fail_step = next(
        (s for s in steps if str(s.get("name", "")).startswith("Fail job on stale")), None
    )
    assert fail_step is not None, "der abschliessende Fehlschlag-Schritt wurde umbenannt"
    assert "steps.alarm_coverage.outputs.alarm_rc == '1'" in fail_step["if"], (
        "der Fehlschlag der Abdeckungspruefung macht den Job NICHT rot -- damit "
        "waere der Waechter genau so stumm wie der Alarm, den er bewacht."
    )


def test_an_invalid_probe_is_not_reported_as_healthy(watchdog: dict) -> None:
    """rc=8 heisst 'nicht gemessen'. Es darf weder rot noch gruen behaupten."""
    steps = watchdog["jobs"]["probe"]["steps"]
    schritt = next(s for s in steps if s.get("id") == "alarm_coverage")
    assert '"$rc" = "8"' in schritt["run"], "der Sondenfehler wird nicht gesondert behandelt"
    assert "KEIN Bestehen" in schritt["run"]

    fail_step = next(s for s in steps if str(s.get("name", "")).startswith("Fail job on stale"))
    assert "alarm_rc == '8'" not in fail_step["if"], (
        "ein Sondenfehler darf den Job nicht rot machen -- sonst faerbt jede "
        "Grafana-Stoerung den Watchdog rot und die echten Befunde gehen unter."
    )
