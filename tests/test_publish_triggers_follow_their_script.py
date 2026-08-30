"""Ein Publisher muss auf sein SKRIPT triggern, nicht nur auf seine Daten.

Warum es diesen File gibt
=========================

Am 2026-08-30 lag der Fix aus #5204 — der Routing-Upsert verwarf vier
Routen-Felder still — **zwanzig Minuten auf ``main``, ohne dass irgendetwas ihn
ausgeliefert hätte.** Beide Publish-Workflows triggern auf ``push``, aber ihre
``paths``-Liste nannte nur die YAML-Datei. Eine Änderung an der Upsert-LOGIK
erreicht die Produktion damit nie von selbst; deployt wurde sie erst durch einen
Hand-Dispatch.

Das ist die Klasse „gemergt ≠ ausgeliefert" an einer Stelle, an der sie
besonders teuer ist: der Publisher ist genau das Werkzeug, dessen Aufgabe das
Ausliefern IST.

Die Liste wird hier nicht gepflegt, sondern **abgeleitet**: aus dem Workflow das
aufgerufene Skript, aus dem Skript seine lokalen ``scripts.*``-Importe. Eine
handgeführte Liste hätte dieselbe Drift, die sie verhindern soll — und der
transitive Fall ist real: ``grafana_notification_routing_upsert`` bezieht
``_api_key``/``_request`` aus ``grafana_alert_rules_upsert``, eine Änderung dort
betrifft also BEIDE Publisher.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO / ".github" / "workflows"

#: Die Publisher, um die es geht. Bewusst benannt statt gesucht: ein Workflow,
#: der später Publisher wird und hier fehlt, soll durch den Populations-Test
#: unten auffallen, nicht stillschweigend ungeprüft bleiben.
_PUBLISHER = (
    "live-overlay-notification-routing-publish.yml",
    "live-overlay-alert-rules-publish.yml",
    "live-overlay-dashboard-publish.yml",
)

_SCRIPT_RE = re.compile(r"scripts/([a-z0-9_]+)\.py")
_IMPORT_RE = re.compile(r"^\s*from scripts\.([a-z0-9_]+) import", re.M)


def _push_paths(name: str) -> list[str]:
    doc = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    # `on:` wird von PyYAML als bool True gelesen (YAML 1.1) — beide Formen holen.
    on = doc.get(True) if doc.get(True) is not None else doc.get("on")
    return list(((on or {}).get("push") or {}).get("paths") or [])


def _invoked_scripts(name: str) -> set[str]:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    return {f"scripts/{m}.py" for m in _SCRIPT_RE.findall(text)}


def _local_imports(script_rel: str) -> set[str]:
    quelle = (REPO / script_rel).read_text(encoding="utf-8")
    return {f"scripts/{m}.py" for m in _IMPORT_RE.findall(quelle)}


@pytest.mark.parametrize("workflow", _PUBLISHER)
def test_the_publisher_triggers_on_the_script_it_runs(workflow: str) -> None:
    paths = _push_paths(workflow)
    assert paths, f"{workflow} hat keine push-paths — dann triggert es auf ALLES"
    aufgerufen = _invoked_scripts(workflow)
    assert aufgerufen, (
        f"{workflow} ruft kein scripts/*.py auf — die Ableitung ist blind, "
        "damit wäre die Aussage unten vakuum"
    )
    fehlend = sorted(s for s in aufgerufen if s not in paths)
    assert not fehlend, (
        f"{workflow} ruft {sorted(aufgerufen)} auf, triggert aber nicht darauf: "
        f"{fehlend} fehlt in `paths`. Eine Änderung an der Logik erreicht die "
        "Produktion damit nie von selbst — genau der Fall vom 2026-08-30, wo ein "
        "gemergter Fix 20 min unausgeliefert lag."
    )


@pytest.mark.parametrize("workflow", _PUBLISHER)
def test_the_publisher_also_triggers_on_what_its_script_imports(workflow: str) -> None:
    """Der transitive Fall, und er ist real.

    ``grafana_notification_routing_upsert`` bezieht ``_api_key``/``_request`` aus
    ``grafana_alert_rules_upsert``. Eine Änderung an der Auth- oder
    HTTP-Schicht betrifft BEIDE Publisher — träfe sie nur den einen Trigger,
    liefe der andere weiter mit der alten Logik.
    """
    paths = _push_paths(workflow)
    erwartet: set[str] = set()
    for skript in _invoked_scripts(workflow):
        erwartet |= _local_imports(skript)
    # Bewusst KEIN pytest.skip bei leerer Menge: ein uebersprungener Test ist
    # einer, der nicht laeuft, und das Repo fuehrt darueber zu Recht ein Budget.
    # Ohne lokale Importe ist die Aussage schlicht erfuellt — das ist ein
    # gueltiges Ergebnis, kein Grund, den Lauf auszulassen.
    fehlend = sorted(s for s in erwartet if s not in paths)
    assert not fehlend, (
        f"{workflow} haengt ueber Importe an {sorted(erwartet)}, triggert aber "
        f"nicht darauf: {fehlend} fehlt in `paths`."
    )


def test_the_publisher_list_still_matches_the_repo() -> None:
    """Populations-Kontrolle: ein neuer Publisher darf nicht unbemerkt entstehen.

    Ohne sie prüfte dieser File eine Teilmenge und schwiege über den Rest —
    dieselbe Klasse, gegen die er gebaut ist.
    """
    gefunden = {
        p.name
        for p in WORKFLOWS.glob("*publish*.yml")
        if "grafana" in p.read_text(encoding="utf-8")
    }
    fehlend = sorted(gefunden - set(_PUBLISHER))
    assert not fehlend, (
        f"neue Grafana-Publisher ohne Trigger-Pruefung: {fehlend} — in _PUBLISHER "
        "aufnehmen"
    )
