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

#: 2026-08-31 (Wirkungs-Sweep Befund C): die Population wird ABGELEITET statt
#: gepflegt. Vorher standen hier drei benannte Grafana-Publisher; der Sweep fand
#: denselben Defekt bei zwei Watchern und der TV-Onboarding-Kette — also genau
#: dort, wo die gepflegte Liste nicht hinsah. Eine handgefuehrte Liste hat
#: dieselbe Drift, die sie verhindern soll (die Lehre aus #5205, hier ein
#: zweites Mal bezahlt).
#:
#: Betroffen ist JEDER Workflow, der auf `push.paths` triggert UND ein
#: `scripts/*.py` beruehrt: fehlt dieses Skript (oder etwas, das es importiert)
#: in `paths`, erreicht eine Aenderung daran die Produktion nie von selbst.


def _push_paths(name: str) -> list[str]:
    doc = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    # `on:` wird von PyYAML als bool True gelesen (YAML 1.1) — beide Formen holen.
    on = doc.get(True) if doc.get(True) is not None else doc.get("on")
    return list(((on or {}).get("push") or {}).get("paths") or [])


def _invoked_scripts(name: str) -> set[str]:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    return {f"scripts/{m}.py" for m in _SCRIPT_RE.findall(text)}


def _path_triggered_workflows() -> tuple[str, ...]:
    raus = []
    for pfad in sorted(WORKFLOWS.glob("*.yml")):
        if not _push_paths(pfad.name):
            continue
        if _invoked_scripts(pfad.name):
            raus.append(pfad.name)
    return tuple(raus)

_SCRIPT_RE = re.compile(r"scripts/([a-z0-9_]+)\.py")
_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+scripts\.([a-z0-9_]+)", re.M)

def _local_imports(script_rel: str) -> set[str]:
    """Transitive Huelle der lokalen ``scripts.*``-Importe.

    2026-08-31: vorher nur EINE Ebene. Die TV-Onboarding-Kette haengt zwei tief
    (``smc_bus_manifest`` -> ``smc_context_bus_manifest`` -> ``smc_atomic_write``),
    und eine Aenderung an der untersten Ebene erreicht den Trigger sonst nicht.
    """
    gesehen: set[str] = set()
    rand = [script_rel]
    while rand:
        aktuell = rand.pop()
        datei = REPO / aktuell
        if not datei.exists():
            continue
        for modul in _IMPORT_RE.findall(datei.read_text(encoding="utf-8")):
            treffer = f"scripts/{modul}.py"
            if treffer not in gesehen and (REPO / treffer).exists():
                gesehen.add(treffer)
                rand.append(treffer)
    gesehen.discard(script_rel)
    return gesehen


@pytest.mark.parametrize("workflow", _path_triggered_workflows())
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


@pytest.mark.parametrize("workflow", _path_triggered_workflows())
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
    """Positivkontrolle der ABLEITUNG: ein leeres Ergebnis darf nicht gruen sein.

    Seit 2026-08-31 wird die Population abgeleitet statt gepflegt. Damit
    verschiebt sich das Risiko: nicht mehr "jemand vergisst einen Eintrag",
    sondern "die Ableitung findet nichts und alle Tests darueber sind vakuum".
    Genau dagegen steht dieser Test — mit den drei Grafana-Publishern als
    unabhaengigem Zeugen, die NICHT aus der Ableitung stammen.
    """
    abgeleitet = set(_path_triggered_workflows())
    assert len(abgeleitet) >= 5, (
        f"Ableitung findet nur {len(abgeleitet)} Workflows — sie ist vermutlich "
        "defekt, und dann prueft dieser File nichts."
    )
    zeugen = {
        p.name
        for p in WORKFLOWS.glob("*publish*.yml")
        if "grafana" in p.read_text(encoding="utf-8")
    }
    assert zeugen, "kein Grafana-Publisher gefunden — der Zeuge selbst ist blind"
    fehlend = sorted(zeugen - abgeleitet)
    assert not fehlend, (
        f"Grafana-Publisher, die die Ableitung NICHT findet: {fehlend} — "
        "entweder fehlt ihnen `push.paths` (dann triggern sie auf ALLES) oder "
        "die Ableitung greift daneben."
    )
