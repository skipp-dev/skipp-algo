"""Der Canary darf sich nicht selbst blind machen.

Vorfall 2026-08-16 bis 2026-08-26, zehn Tage taegliches Rot ohne dass jemand
sah, was kaputt war. Zwei Defekte, hier je gepinnt:

1. **Die Pruefungen toeteten einander.** Drei gewoehnliche Steps ohne
   ``continue-on-error``: schlug die erste fehl, uebersprang GitHub die
   folgenden. Gemessen an Lauf 32813924394 (2026-08-25) — "Check pinned
   schemas" failure, Audit skipped, Probe skipped. Die toten Slack- und
   Notion-Verbindungen waren nicht verdeckt, sondern NIE GEMESSEN.
2. **Ein Sammel-Rot statt eines Urteils je Verbindung.** Wer den Grund suchte,
   fand den Versionsdrift und hielt ihn fuer den ganzen Befund.

Der dritte Punkt — die Altersanzeige — steht im Bericht-Skript: ein Canary,
der seit zehn Tagen rot ist, sieht in der Lauf-Liste aus wie einer, der seit
gestern rot ist, und wird deshalb genauso ignoriert.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from scripts.composio_canary_report import (
    _ESKALATION_TAGE,
    annotations,
    main,
    summary,
    verdicts,
)
from tests._fast_gates_gate import evaluate_condition, step_conditions

WORKFLOW_PFAD = (
    Path(__file__).resolve().parents[1] / ".github" / "workflows" / "composio-canary.yml"
)
_FAIL_STEP = "Fail when any check reported a problem"


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW_PFAD.read_text(encoding="utf-8"))


def _pruef_steps(workflow: dict) -> dict[str, dict]:
    """Die Steps, die eine Pruefung FAHREN — abgeleitet, nicht gelistet.

    Kriterium: ein Step mit `id`, der ein `scripts/composio_*.py` aufruft.
    Ein neu hinzugefuegter Pruef-Step ist damit ab seiner ersten Zeile
    mitgeprueft; eine hartkodierte Liste faenge genau die Drift nicht, die
    sie fangen soll.
    """
    treffer = {}
    for step in workflow["jobs"]["probe"]["steps"]:
        run = str(step.get("run", ""))
        if step.get("id") and "scripts/composio_" in run:
            treffer[step["id"]] = step
    return treffer


def test_the_check_step_population_is_not_empty(workflow: dict) -> None:
    """Vakuitaetsboden: ein kaputter Parser darf nicht als 'alles gut' gelten."""
    steps = _pruef_steps(workflow)
    assert len(steps) >= 4, f"nur {sorted(steps)} gefunden — Ableitung kaputt?"


def test_no_check_can_kill_the_others(workflow: dict) -> None:
    """Der Defekt vom 25.8.: Step 1 rot ⇒ Steps 2 und 3 skipped.

    Ohne `continue-on-error` beendet ein fehlgeschlagener Step den Job und
    GitHub ueberspringt alle folgenden. Genau so blieben die Verbindungen
    ungemessen, waehrend der Canary taeglich rot meldete.
    """
    for step_id, step in sorted(_pruef_steps(workflow).items()):
        assert step.get("continue-on-error") is True, (
            f"Step {step_id!r} laeuft ohne continue-on-error — sein Fehlschlag "
            "ueberspringt jede folgende Pruefung, und deren Ergebnis fehlt "
            "still (Lauf 32813924394)."
        )
        assert 'rc=$?' in str(step["run"]) and "GITHUB_OUTPUT" in str(step["run"]), (
            f"Step {step_id!r} publiziert kein rc — der Fail-Step unten kann "
            "ihn dann nicht bewerten, und sein Fehlschlag verschwindet."
        )


def test_every_check_can_still_fail_the_job(workflow: dict) -> None:
    """Entkoppeln darf nicht heissen: nichts wird mehr rot.

    Ueber die GRUNDGESAMTHEIT der Pruef-Steps, beide Richtungen — jedes
    einzelne rc!=0 muss den Job faellen, und ein sauberer Lauf darf gruen
    bleiben.
    """
    bedingung = step_conditions(WORKFLOW_PFAD, job="probe")[_FAIL_STEP]
    ids = sorted(_pruef_steps(workflow))
    sauber = {f"{i}.rc": "0" for i in ids}

    assert not evaluate_condition(bedingung, dict(sauber)), (
        "ein Lauf, in dem jede Pruefung 0 meldet, darf nicht rot werden"
    )
    for step_id in ids:
        lage = dict(sauber)
        lage[f"{step_id}.rc"] = "1"
        assert evaluate_condition(bedingung, lage), (
            f"rc=1 von {step_id!r} macht den Job NICHT rot — dieser Fehlschlag "
            "waere unsichtbar, genau wie am 25.8."
        )


def test_a_skipped_check_does_not_read_as_green(workflow: dict) -> None:
    """Die null-Coercion-Falle aus #5199, hier praeventiv geprueft.

    Ein uebersprungener Step liefert `null`; GitHub castet `null` und `'0'`
    beide nach 0. Ohne die `!= ''`-Klausel waere das Gate fuer genau den
    Zustand blind, den dieser Fix behebt.
    """
    bedingung = step_conditions(WORKFLOW_PFAD, job="probe")[_FAIL_STEP]
    assert "!= ''" in bedingung, (
        "dem Fail-Gate fehlt die Leerwert-Klausel — ein uebersprungener Step "
        "liest sich dann als rc=0"
    )


# --- Urteil je Verbindung ----------------------------------------------------

def _bericht(*probes: dict) -> dict:
    return {"ok": all(p.get("ok") for p in probes), "probes": list(probes)}


TOT = {"toolkit": "slack", "tool": "SLACK_TEST_AUTH", "ok": False, "skipped": False,
       "detail": "Slack API error: token_revoked"}
LEBT = {"toolkit": "github", "tool": "GITHUB_GET_THE_AUTHENTICATED_USER", "ok": True,
        "skipped": False, "detail": "delivered"}
UNGEMESSEN = {"toolkit": "notion", "tool": "NOTION_GET_ABOUT_USER", "ok": False,
              "skipped": True, "detail": "not configured"}


def test_each_connection_gets_its_own_verdict() -> None:
    """Der Kern: nicht EIN Sammelurteil, sondern eines je Verbindung."""
    urteile = verdicts(_bericht(TOT, LEBT, UNGEMESSEN))
    assert [u["urteil"] for u in urteile] == ["TOT", "OK", "UNGEMESSEN"]


def test_a_dead_connection_is_named_in_its_own_annotation() -> None:
    """Ohne Namen im Alarm muss man ins Log — und genau das unterblieb."""
    zeilen = annotations(verdicts(_bericht(TOT, LEBT)), rot_seit_tagen=1)
    treffer = [z for z in zeilen if z.startswith("::error") and "slack" in z]
    assert len(treffer) == 1, zeilen
    assert "token_revoked" in treffer[0], "der Grund fehlt in der Annotation"
    assert not [z for z in zeilen if "github" in z], (
        "eine gesunde Verbindung darf keine Annotation erzeugen"
    )


def test_an_unmeasured_connection_is_not_reported_as_healthy() -> None:
    """`skipped` heisst ungemessen. Als gruen zu fuehren waere die Luege."""
    urteile = verdicts(_bericht(UNGEMESSEN))
    assert urteile[0]["urteil"] == "UNGEMESSEN"
    zeilen = annotations(urteile, rot_seit_tagen=0)
    assert zeilen and "UNGEMESSEN" in zeilen[0]


def test_a_long_red_streak_escalates() -> None:
    """Dauerrot wird uebersehen — ab drei Tagen sagt die Ausgabe es ausdruecklich."""
    kurz = annotations(verdicts(_bericht(TOT)), rot_seit_tagen=_ESKALATION_TAGE - 1)
    lang = annotations(verdicts(_bericht(TOT)), rot_seit_tagen=_ESKALATION_TAGE)
    assert not [z for z in kurz if "seit" in z and "Tagen ohne gruenen" in z]
    eskalation = [z for z in lang if "Tagen ohne gruenen" in z]
    assert len(eskalation) == 1, lang
    assert eskalation[0].startswith("::error")


def test_a_green_run_escalates_nothing() -> None:
    """Gegenrichtung: ohne toten Zweig keine Eskalation, egal wie alt."""
    assert annotations(verdicts(_bericht(LEBT)), rot_seit_tagen=99) == []


def test_a_missing_probe_report_is_loud(tmp_path: Path, capsys) -> None:
    """Der Zustand vom 25.8.: der Probe-Step lief gar nicht.

    Ein Bericht, der das als 'nichts zu melden' behandelt, waere so blind
    wie sein Vorgaenger.
    """
    rc = main(["--report", str(tmp_path / "gibtsnicht.json")])
    assert rc == 1
    assert "GAR NICHT geprueft" in capsys.readouterr().out


def test_the_summary_lists_every_connection() -> None:
    text = summary(verdicts(_bericht(TOT, LEBT, UNGEMESSEN)), rot_seit_tagen=4)
    for toolkit in ("slack", "github", "notion"):
        assert f"`{toolkit}`" in text, toolkit
    assert "vor 4 Tag(en)" in text


def test_main_returns_nonzero_when_any_connection_is_dead(tmp_path: Path) -> None:
    """Positivkontrolle in beide Richtungen — sonst koennte alles rot sein."""
    rot = tmp_path / "rot.json"
    rot.write_text(json.dumps(_bericht(TOT, LEBT)), encoding="utf-8")
    assert main(["--report", str(rot)]) == 1

    gruen = tmp_path / "gruen.json"
    gruen.write_text(json.dumps(_bericht(LEBT)), encoding="utf-8")
    assert main(["--report", str(gruen)]) == 0
