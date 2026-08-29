"""Der Wert-Waechter vor den vier required `validate (N)`-Shards — ausgefuehrt.

Warum es diesen File gibt
=========================

``ci.yml`` waehlt den Runner der ``validate``-Shards seit 2026-08-29 ueber
``${{ vars.SMC_CI_ARM_RUNNER || vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest' }}``.
Der erste Operand ist eine **Repo-Variable**: ihr Wert steht in keiner
Repo-Datei, kein Guard sieht ihn, und die bestehenden Runner-Contract-Tests
pinnen ausschliesslich den *Ausdruck*.

Ein Tippfehler in dieser Variablen erzeugt keinen roten Lauf, sondern gar
keinen. Drei belegte Bausteine ergeben zusammen den blinden Fleck:

* GitHub findet kein passendes Label und plant den Job nie ein — er bleibt
  ``queued``, und zwar UNBEFRISTET: die 24-h-Zeile der Actions-Limits gilt nur
  self-hosted und nur je JOB, und ein Lauf ohne angelegten Job hat keinen, der
  eine Uhr startet (korrigiert 2026-08-29, vorher stand hier ein 24-h-Limit).
* ``timeout-minutes`` faengt das nicht. Dieselbe Erkenntnis steht seit laengerem
  in ``tests/test_workflow_runner_pinned.py`` fuer fast-gates: *"timeout-minutes
  is only enforced by the runner itself"* — es laeuft erst, wenn ein Runner den
  Job angenommen HAT.
* Der Fehleralarm ``lo-workflow-run-failed`` wertet ``latest run failed`` aus
  (``scripts/check_workflow_failure_alarm_coverage.py``) und steht auf
  ``noDataState: OK``. Ein Lauf, der nie endet, erzeugt kein ``failure``.

Seit 2026-08-27 sind ``validate (1)``-``(4)`` required (ADR-0012). Der
Ausfall waere also: jeder PR haengt auf "Expected — waiting for status", kein
Alert, kein Log, kein Artefakt — der Job hat nie gestartet, es gibt keine
Steps. Es gaebe keine diagnostische Oberflaeche, weil es keinen Lauf gibt.

Warum ausgefuehrt statt gelesen
===============================

Ein Test, der die Allowlist als Substring im YAML sucht, kann "lehnt unbekannte
Labels ab" nicht von "nennt sie in einem Kommentar" unterscheiden — und haette
eine invertierte ``case``-Bedingung nicht bemerkt. ``tests/_workflow_step_shell``
existiert genau dafuer: der Block wird mit ``bash -e -o pipefail`` gefahren und
das Urteil am Exit-Code gemessen.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests._workflow_step_shell import (
    WORKFLOWS,
    declares_bash_default,
    run_step,
    step_by_name,
)

_WORKFLOW = "ci.yml"
_STEP = "Arm-Runner-Label gegen Allowlist pruefen"
_PREFLIGHT_JOB = "runner-preflight"

# Die Labels, die GitHub fuer linux-arm64 als STANDARD-Runner anbietet. Bewusst
# hier dupliziert und nicht aus dem YAML gelesen: ein Test, der seine Erwartung
# aus dem Pruefling ableitet, ist mit jeder Aenderung automatisch einverstanden.
_KNOWN_ARM_LABELS = ("ubuntu-24.04-arm", "ubuntu-22.04-arm")


def _ci_jobs() -> dict:
    doc = yaml.safe_load((WORKFLOWS / _WORKFLOW).read_text(encoding="utf-8"))
    jobs = doc.get("jobs")
    assert isinstance(jobs, dict), "ci.yml MUSS eine jobs-Mapping haben"
    return jobs


def test_workflow_declares_the_bash_default_this_module_assumes() -> None:
    """Beide Seiten des Shell-Vertrags pinnen, nicht nur eine.

    ``_workflow_step_shell`` faehrt den Block mit ``-e -o pipefail``, weil
    ``ci.yml`` ``defaults: run: shell: bash`` deklariert. Faellt die Deklaration
    weg, misst dieser File etwas anderes als die Produktion.
    """
    assert declares_bash_default(_WORKFLOW), (
        "ci.yml deklariert kein `defaults: run: shell: bash` mehr — die "
        "Ausfuehrung in diesem File wuerde dann strenger laufen als der echte Lauf"
    )


def test_preflight_does_not_depend_on_the_variable_it_validates() -> None:
    """Die tragende Eigenschaft: der Waechter darf nicht am eigenen Prueffall haengen.

    Zeigte ``runner-preflight.runs-on`` auf ``SMC_CI_ARM_RUNNER``, wuerde ein
    falsches Label den Waechter selbst in dieselbe Endlos-Queue schicken — der
    Schutz waere exakt dann abwesend, wenn er gebraucht wird.
    """
    preflight = _ci_jobs().get(_PREFLIGHT_JOB)
    assert isinstance(preflight, dict), (
        f"ci.yml hat keinen Job `{_PREFLIGHT_JOB}` mehr — der Wert-Waechter vor "
        "den vier required Shards ist weg"
    )
    runs_on = preflight.get("runs-on")
    assert isinstance(runs_on, str), (
        f"{_PREFLIGHT_JOB}.runs-on ist kein String: {runs_on!r}"
    )
    assert "SMC_CI_ARM_RUNNER" not in runs_on, (
        f"{_PREFLIGHT_JOB} laeuft selbst auf der Variablen, die er prueft "
        f"({runs_on!r}) — ein falsches Label wuerde den Waechter mit in die "
        "Queue nehmen, statt ihn rot zu machen"
    )
    assert runs_on.endswith("|| 'ubuntu-latest' }}"), (
        f"{_PREFLIGHT_JOB}.runs-on traegt nicht mehr den Hosted-Rueckfall: {runs_on!r}"
    )
    timeout = preflight.get("timeout-minutes")
    assert isinstance(timeout, int) and timeout <= 15, (
        f"{_PREFLIGHT_JOB} braucht eine harte, kleine Zeitgrenze; ist: {timeout!r}"
    )


def test_validate_waits_for_the_preflight() -> None:
    """Ein Waechter ohne Kante zum Geschuetzten ist Dekoration."""
    validate = _ci_jobs().get("validate")
    assert isinstance(validate, dict)
    assert validate.get("needs") == _PREFLIGHT_JOB, (
        "validate wartet nicht mehr auf den Wert-Waechter — die vier required "
        f"Shards koennen wieder vor {_PREFLIGHT_JOB} in die Queue laufen; "
        f"ist: {validate.get('needs')!r}"
    )


def test_unset_variable_passes_and_says_so(tmp_path: Path) -> None:
    """Der Normalfall: Variable nicht gesetzt = kein Urteil, aber eine Aussage.

    Wichtig, weil ein Waechter, der bei ungesetzter Variable rot wird, sofort
    wieder ausgebaut wuerde — und weil die Run-Uebersicht auch im gruenen Fall
    beantworten muss, auf welcher Architektur die Shards liefen.
    """
    run = run_step(_WORKFLOW, _STEP, tmp_path, env={"ARM_RUNNER": ""})

    assert run.returncode == 0, (
        f"ungesetzte Variable wurde abgelehnt (rc={run.returncode}):\n{run.stdout}\n{run.stderr}"
    )
    assert "arm_runner=<unset>" in run.stdout
    assert "resolution_reason=ci_policy_no_arm_override" in run.stdout
    assert "SMC_CI_ARM_RUNNER" in run.summary, (
        "die Run-Uebersicht sagt nicht, dass die Lane auf der bisherigen Wahl faehrt"
    )


@pytest.mark.parametrize("label", _KNOWN_ARM_LABELS)
def test_known_arm_label_passes_and_names_itself(tmp_path: Path, label: str) -> None:
    run = run_step(_WORKFLOW, _STEP, tmp_path, env={"ARM_RUNNER": label})

    assert run.returncode == 0, (
        f"bekanntes Label {label!r} wurde abgelehnt (rc={run.returncode}):\n{run.stdout}\n{run.stderr}"
    )
    assert f"arm_runner={label}" in run.stdout
    assert "resolution_reason=ci_policy_arm_override" in run.stdout
    assert label in run.summary, (
        f"die Run-Uebersicht nennt das gewaehlte Label {label!r} nicht — genau "
        "das braucht die Triage um 3 Uhr nachts"
    )


@pytest.mark.parametrize(
    "label",
    [
        # Die Falle, die ci.yml selbst benennt: dieses Label existiert nicht,
        # GitHub bietet fuer linux-arm64 nur VERSIONIERTE Formen an.
        "ubuntu-latest-arm",
        "ubuntu-24.04-ARM",  # Gross-/Kleinschreibung ist bei Labels nicht egal
        "ubuntu-24.04",  # x86-Label an der arm-Variablen: stiller Etikettenschwindel
        "arm64",
        "self-hosted",  # der Weg, den die Runner-Policy ausdruecklich verbietet
        " ubuntu-24.04-arm",  # fuehrendes Leerzeichen aus der GitHub-UI
    ],
)
def test_unknown_label_fails_loudly_and_names_the_value(tmp_path: Path, label: str) -> None:
    """Der eigentliche Zweck: aus stillem Stillstand einen roten Lauf machen.

    Geprueft wird nicht nur der Exit-Code, sondern dass der WERT im Fehlertext
    steht. Ein ``::error::`` ohne den konkreten Wert liesse den Geweckten den
    Run oeffnen, die Variable in den Repo-Settings nachschlagen und raten —
    dieselbe Messlatte wie beim credential-health-Alarm, der ``91.6h >= 72.0h``
    sagt statt "expired".
    """
    run = run_step(_WORKFLOW, _STEP, tmp_path, env={"ARM_RUNNER": label})

    assert run.returncode != 0, (
        f"unbekanntes Label {label!r} wurde DURCHGELASSEN — die vier required "
        f"Shards liefen damit in eine Endlos-Queue:\n{run.stdout}\n{run.stderr}"
    )
    emitted = run.stdout + run.stderr
    assert "::error::" in emitted, (
        f"Ablehnung von {label!r} ohne ::error::-Annotation — im Run steht dann "
        f"nur ein Exit-Code:\n{emitted}"
    )
    assert label.strip() in emitted, (
        f"der Fehlertext nennt den abgelehnten Wert {label!r} nicht:\n{emitted}"
    )
    for allowed in _KNOWN_ARM_LABELS:
        assert allowed in emitted, (
            f"der Fehlertext nennt die erlaubte Alternative {allowed!r} nicht — "
            f"der Geweckte muesste sie im YAML nachschlagen:\n{emitted}"
        )
    assert "loeschen" in run.summary or "loeschen" in emitted, (
        "das Rueckrollrezept (Repo-Variable loeschen) steht weder in der "
        "Run-Uebersicht noch im Fehlertext"
    )


def test_step_is_reachable_from_the_preflight_job() -> None:
    """``step_by_name`` sucht workflow-weit — hier wird die Zuordnung gepinnt.

    Sonst koennte der Block in einen anderen Job wandern und die
    Ausfuehrungstests blieben gruen, waehrend `runner-preflight` leer laeuft.
    """
    preflight = _ci_jobs()[_PREFLIGHT_JOB]
    names = [s.get("name") for s in preflight.get("steps") or []]
    assert _STEP in names, (
        f"{_PREFLIGHT_JOB} enthaelt den Pruefschritt nicht mehr; Steps: {names!r}"
    )
    # Und der Block, den die Tests oben gefahren haben, ist genau dieser.
    assert step_by_name(_WORKFLOW, _STEP).get("run"), (
        f"Step {_STEP!r} hat keinen run-Block mehr"
    )
