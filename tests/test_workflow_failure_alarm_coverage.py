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

import os
import subprocess
import urllib.error
from pathlib import Path

import pytest
import yaml

import scripts.check_workflow_failure_alarm_coverage as cov
from scripts.check_workflow_failure_alarm_coverage import (
    REQUIRED_WORKFLOWS,
    RUN_PAGE_SIZE,
    _mit_transient_retry,
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

    ``smc-fast-pr-gates`` traegt fast-gates+gate (required, seit 27.8. mit den validate-Shards) und ist der einzige Ort,
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


def test_the_probe_call_survives_the_default_shell_dash_e(watchdog: dict) -> None:
    """`rc=$?` hinter einem nackten Aufruf ist unter `-e` toter Code.

    Die Default-Shell der run-Steps ist `bash -e -o pipefail`; ohne
    `set +e`-Klammer beendet ein rc!=0 den Step, BEVOR alarm_rc geschrieben
    wird — genau so faerbte am 2026-08-25 ein einzelner GitHub-503 den ganzen
    Watchdog rot (Lauf 32821936783), obwohl rc=8 laut Vertrag nur eine
    Warnung ist. Die Schwester-Steps (probe/dag) tragen dieselbe Klammer.
    """
    steps = watchdog["jobs"]["probe"]["steps"]
    schritt = next(s for s in steps if s.get("id") == "alarm_coverage")
    assert (
        "set +e\npython -m scripts.check_workflow_failure_alarm_coverage\nrc=$?\nset -e"
        in schritt["run"]
    ), "die set+e-Klammer um den Sondenaufruf fehlt — rc-Fang ist unter -e unerreichbar"


def test_a_transient_503_is_retried_and_the_probe_still_measures() -> None:
    calls = {"n": 0}

    def fetch(arg: str) -> dict:
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.HTTPError("u", 503, "Service Unavailable", None, None)
        return {"arg": arg}

    naps: list[float] = []
    result = _mit_transient_retry(fetch, "x", schlaf=naps.append)
    assert result == {"arg": "x"}
    assert calls["n"] == 3
    assert naps == [cov._TRANSIENT_BACKOFF_S, cov._TRANSIENT_BACKOFF_S]


def test_a_persistent_transient_still_fails_closed() -> None:
    calls = {"n": 0}

    def fetch() -> None:
        calls["n"] += 1
        raise urllib.error.HTTPError("u", 503, "Service Unavailable", None, None)

    with pytest.raises(urllib.error.HTTPError):
        _mit_transient_retry(fetch, schlaf=lambda _s: None)
    assert calls["n"] == cov._TRANSIENT_VERSUCHE


def test_a_real_client_error_is_not_retried() -> None:
    """4xx ist Konfiguration, nicht Wetter — sofort laut, kein Versuch 2."""
    calls = {"n": 0}

    def fetch() -> None:
        calls["n"] += 1
        raise urllib.error.HTTPError("u", 403, "Forbidden", None, None)

    with pytest.raises(urllib.error.HTTPError):
        _mit_transient_retry(fetch, schlaf=lambda _s: None)
    assert calls["n"] == 1


def test_main_routes_the_fetches_through_the_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verdrahtungs-Pin: ohne die Huelle in main() waere der Fix rueckbaubar."""
    calls = {"n": 0}

    def kaputt(key: str) -> set[str]:
        calls["n"] += 1
        raise urllib.error.HTTPError("u", 503, "Service Unavailable", None, None)

    monkeypatch.setattr(cov, "observed_workflows", kaputt)
    monkeypatch.setattr(cov, "_api_key", lambda: "k")
    monkeypatch.setattr(cov, "_TRANSIENT_BACKOFF_S", 0.0)
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    rc = cov.main([])
    assert rc == 8, "endgueltig toter Transport bleibt fail-closed (exit 8)"
    assert calls["n"] == cov._TRANSIENT_VERSUCHE, (
        "main() muss die Abrufe durch die Retry-Huelle schicken"
    )


def test_the_alarm_step_script_survives_rc8_under_dash_e(
    tmp_path: Path, watchdog: dict
) -> None:
    """Verhaltens-Drill (proof_ledger #5077), nicht nur Text-Pin.

    Der ECHTE Step-Text aus dem YAML laeuft unter der ECHTEN Default-Shell
    (`bash -e -o pipefail`), mit einem python-Stub, der wie im Cron-Lauf
    32821936783 mit rc=8 stirbt. Vor dem Fix toetete `-e` den Step VOR der
    alarm_rc-Zuweisung (Job rot, Vertrag gebrochen); mit der Klammer endet
    der Step gruen und schreibt alarm_rc=8. Rueckbau der Klammer macht
    diesen Test rot — er ist die dauerhaft ausfuehrbare Fassung des Drills.
    """
    steps = watchdog["jobs"]["probe"]["steps"]
    script = next(s for s in steps if s.get("id") == "alarm_coverage")["run"]

    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    stub = stub_bin / "python"
    stub.write_text(
        "#!/bin/sh\necho 'SONDE UNGUELTIG: HTTPError: HTTP Error 503' >&2\nexit 8\n"
    )
    stub.chmod(0o755)
    github_output = tmp_path / "github_output"
    github_output.write_text("")

    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"
    env["GITHUB_OUTPUT"] = str(github_output)
    env["GRAFANA_API_KEY"] = "drill-dummy"

    # Fester bash-Pfad, Step-Text stammt aus dem Repo-YAML — keine Fremdeingabe.
    proc = subprocess.run(
        ["/bin/bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, (
        f"Step stirbt unter -e trotz Klammer: rc={proc.returncode}\n{proc.stderr}"
    )
    assert "alarm_rc=8" in github_output.read_text(), (
        "alarm_rc wurde nicht geschrieben — der rc-Fang ist wieder unerreichbar"
    )


# ---------------------------------------------------------------------------
# Ruleset-Drift-Arm (Geburtsfehler-Sweep 2026-08-28)
#
# Am 27.8. nahm der Operator `gate` mit ins main-governance-Ruleset auf; der
# Nachzug #5121 uebertrug nur die vier validate-Shards. Kein Waechter lief je
# gegen den LIVE-Zustand — verify_branch_protection.py startet kein Workflow.
# Diese Tests pinnen den Arm, der das schliesst, und den Drift-Faenger fuer
# die Handliste REQUIRED_WORKFLOWS.
# ---------------------------------------------------------------------------

WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def test_the_repo_truth_carries_the_gate_context() -> None:
    """Der Boden unter der abgeleiteten Pruefung — die #5121-Luecke, gepinnt.

    Live gemessen 2026-08-28 (Ruleset 15245308): sechs Kontexte. Eine
    abgeleitete Liste ohne Boden kann ihre eigene Drift nicht fangen.
    """
    assert {
        "fast-gates", "gate",
        "validate (1)", "validate (2)", "validate (3)", "validate (4)",
    } <= set(cov.REQUIRED_STATUS_CHECKS)


def test_a_context_the_ruleset_lost_is_a_finding() -> None:
    findings = cov.evaluate_ruleset_drift(["fast-gates", "gate"], {"fast-gates"})
    assert len(findings) == 1
    assert "'gate'" in findings[0] and "verloren" in findings[0]


def test_a_context_the_repo_truth_does_not_know_is_a_finding() -> None:
    """Die Richtung, in der 'gate' am 27.8. tatsaechlich durchgefallen ist."""
    findings = cov.evaluate_ruleset_drift(["fast-gates"], {"fast-gates", "gate"})
    assert len(findings) == 1
    assert "REQUIRED_STATUS_CHECKS" in findings[0]


def test_an_empty_live_context_set_is_loud_not_clean() -> None:
    """Null required Checks = Governance weg. Das darf nie wie 'kein Drift' aussehen."""
    findings = cov.evaluate_ruleset_drift(["fast-gates"], set())
    assert len(findings) == 1 and "NULL" in findings[0]


def test_matching_context_sets_yield_no_drift() -> None:
    """Positivkontrolle gegen einen Dauer-Rotton."""
    assert cov.evaluate_ruleset_drift(["a", "b"], {"a", "b"}) == []


def test_a_403_on_the_ruleset_read_is_not_measurable_not_a_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def gh(url: str, token: str) -> dict:
        raise urllib.error.HTTPError("u", 403, "Forbidden", None, None)

    monkeypatch.setattr(cov, "_gh", gh)
    assert cov.live_required_contexts("r", "t") is None


def test_a_5xx_on_the_ruleset_read_stays_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    """5xx ist Wetter — es gehoert in den Transient-Retry, nicht ins stille None."""
    def gh(url: str, token: str) -> dict:
        raise urllib.error.HTTPError("u", 503, "Service Unavailable", None, None)

    monkeypatch.setattr(cov, "_gh", gh)
    with pytest.raises(urllib.error.HTTPError):
        cov.live_required_contexts("r", "t")


def test_contexts_come_from_active_rulesets_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def gh(url: str, token: str):  # Testdouble
        if url.endswith("/rulesets"):
            return [{"id": 1, "enforcement": "active"}, {"id": 2, "enforcement": "disabled"}]
        assert url.endswith("/rulesets/1"), "ein disabled Ruleset darf nicht abgefragt werden"
        return {"rules": [{"type": "required_status_checks", "parameters": {
            "required_status_checks": [{"context": "fast-gates"}, {"context": "gate"}],
        }}]}

    monkeypatch.setattr(cov, "_gh", gh)
    assert cov.live_required_contexts("r", "t") == {"fast-gates", "gate"}


def _files_hosting_job(base: str, workflows_dir: Path) -> set[str]:
    """Workflow-Dateien, deren Job-Schluessel ODER Anzeigename `base` ist.

    Ein required-Check-Kontext ist der Job-Name; jede Workflow-Datei, die so
    einen Job traegt, meldet diesen Kontext. Population von Platte, keine
    Handliste (Doppelgaenger K5 / hartkodierte Waechter-Listen-Klasse).
    """
    hosts: set[str] = set()
    for wf in sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml")):
        doc = yaml.safe_load(wf.read_text(encoding="utf-8")) or {}
        jobs = doc.get("jobs")
        if not isinstance(jobs, dict):
            continue
        for job_key, job in jobs.items():
            name = str((job or {}).get("name") or job_key)
            if base in (str(job_key), name):
                hosts.add(wf.name)
    return hosts


def test_every_required_context_is_hosted_and_its_workflow_is_monitored() -> None:
    """Der Drift-Faenger fuer die Handliste REQUIRED_WORKFLOWS.

    Gemessen 2026-08-28 ueber alle 72 Workflow-Dateien: fast-gates+gate leben
    in smc-fast-pr-gates.yml, validate in ci.yml — exakt die zwei Eintraege
    der Handliste. Kommt morgen ein required Check in einer DRITTEN Datei
    dazu (oder zieht einer um), wird dieser Test rot, statt dass der
    Fehleralarm still blind bleibt. Kontext ohne Job = Ruleset und Repo sind
    auseinander (Umbenennungs-Falle).
    """
    alle = sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(WORKFLOWS_DIR.glob("*.yaml"))
    assert len(alle) >= 30, "Vakuitaets-Boden: das Workflows-Glob findet fast nichts"
    hosting: set[str] = set()
    for context in cov.REQUIRED_STATUS_CHECKS:
        base = context.split(" (")[0]
        hosts = _files_hosting_job(base, WORKFLOWS_DIR)
        assert hosts, (
            f"Kontext {context!r}: kein Workflow-Job dieses Namens im Repo -- "
            "Ruleset-Kontext und Repo sind auseinander (Umbenennung?)"
        )
        hosting |= hosts
    assert hosting == set(REQUIRED_WORKFLOWS), (
        "Die Workflows, die required-Check-Kontexte melden, und die vom "
        f"Fehleralarm geforderten Dateien driften: hosting={sorted(hosting)} "
        f"vs REQUIRED_WORKFLOWS={sorted(REQUIRED_WORKFLOWS)}"
    )


def test_a_new_workflow_hosting_a_required_job_is_caught(tmp_path: Path) -> None:
    """Mutationsprobe fuer die Ableitung — synthetische dritte Datei."""
    (tmp_path / "neu.yml").write_text(
        "jobs:\n  gate:\n    runs-on: x\n", encoding="utf-8"
    )
    (tmp_path / "anders.yml").write_text(
        "jobs:\n  bau:\n    name: gate\n    runs-on: x\n", encoding="utf-8"
    )
    assert _files_hosting_job("gate", tmp_path) == {"anders.yml", "neu.yml"}
    assert _files_hosting_job("validate", tmp_path) == set()


def _gesunde_sonde(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cov, "_api_key", lambda: "k")
    monkeypatch.setattr(
        cov, "observed_workflows", lambda key: {"smc-fast-pr-gates", "CI"}
    )
    monkeypatch.setattr(
        cov,
        "workflow_names_by_file",
        lambda repo, token: {"smc-fast-pr-gates.yml": "smc-fast-pr-gates", "ci.yml": "CI"},
    )
    monkeypatch.setattr(
        cov, "workflows_in_run_page", lambda repo, token: {"smc-fast-pr-gates", "CI"}
    )
    monkeypatch.setenv("GITHUB_TOKEN", "t")


def test_live_drift_turns_the_daily_probe_red(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _gesunde_sonde(monkeypatch)
    monkeypatch.setattr(cov, "live_required_contexts", lambda repo, token: {"fast-gates"})
    rc = cov.main([])
    assert rc == 1, "Ruleset-Drift muss den taeglichen Lauf rot machen"
    assert "DRIFT" in capsys.readouterr().out


def test_an_unreadable_ruleset_is_ungesichert_not_a_verdict(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """403 heisst 'nicht messbar' — sichtbar im Log, aber weder rot noch gruen.

    Sonst faerbte ein Token ohne administration:read jeden Tageslauf, und die
    echten Befunde gingen im Dauerrot unter (Muster der rc=8-Semantik).
    """
    _gesunde_sonde(monkeypatch)
    monkeypatch.setattr(cov, "live_required_contexts", lambda repo, token: None)
    rc = cov.main([])
    captured = capsys.readouterr()
    assert rc == 0
    assert "UNGESICHERT" in captured.err


def test_matching_live_contexts_keep_the_probe_green(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positivkontrolle der Verdrahtung in main()."""
    _gesunde_sonde(monkeypatch)
    monkeypatch.setattr(
        cov,
        "live_required_contexts",
        lambda repo, token: set(cov.REQUIRED_STATUS_CHECKS),
    )
    assert cov.main([]) == 0


def test_the_per_page_hint_reaches_the_blind_runbook(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """B-Richtung des Sweeps: die kopierte Fenstergroesse steht jetzt im Runbook.

    Der Daemon exponiert per_page nirgends; wer einem Blind-Befund nachgeht,
    muss die Praemisse dieses Skripts (RUN_PAGE_SIZE) gegen die Railway-Env
    halten koennen, ohne den Quelltext zu lesen.
    """
    _gesunde_sonde(monkeypatch)
    monkeypatch.setattr(cov, "observed_workflows", lambda key: {"CI"})
    monkeypatch.setattr(
        cov,
        "live_required_contexts",
        lambda repo, token: set(cov.REQUIRED_STATUS_CHECKS),
    )
    rc = cov.main([])
    assert rc == 1
    assert "GITHUB_WORKFLOW_MONITOR_PER_PAGE" in capsys.readouterr().err
