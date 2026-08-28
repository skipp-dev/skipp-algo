"""Jeder required Kontext muss auf dem Merge-Queue-Ref auch DISPATCHEN.

GitHubs Merge Queue validiert einen Batch auf einem eigenen Ref
(``refs/heads/gh-readonly-queue/main/...``) und mergt ihn erst, wenn alle
required Kontexte dort gruen gemeldet haben. Ein Workflow ohne
``merge_group``-Trigger startet dort NIE — der Batch wartet dann bis zum
Timeout auf einen Check, den niemand mehr schicken wird. Der Fehler ist
still: nichts wird rot, die Queue steht einfach.

Gemessen 2026-08-29: ``smc-fast-pr-gates.yml`` traegt den Trigger samt
Begruendung, ``ci.yml`` trug ihn NICHT — obwohl seine vier ``validate (N)``
Shards seit 2026-08-27 required sind (ADR-0012 Operator-Punkt 1). Eine an
diesem Tag aktivierte Merge Queue haette auf vier Kontexte gewartet, die auf
dem Queue-Ref nie dispatchen.

**Population ABGELEITET, nicht wiederholt.** Die Liste der required Kontexte
lebt seit #5121/#5160 in ``scripts.verify_branch_protection.REQUIRED_STATUS_CHECKS``
und wird taeglich gegen das Live-Ruleset abgeglichen
(``scripts/check_workflow_failure_alarm_coverage.py``, Drift-Arm). Dieser
Waechter liest SIE und ordnet jeden Kontext seinem Workflow zu, indem er die
Jobs der Workflow-Dateien aufloest — eine zweite Handliste hier waere genau
die Drift-Falle, gegen die der Drift-Arm gebaut wurde. Kommt ein required
Kontext dazu, dessen Workflow den Trigger nicht hat, geht dieser Test rot,
ohne dass ihn jemand anfasst.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from scripts.verify_branch_protection import REQUIRED_STATUS_CHECKS

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"

# Ein Matrix-Job meldet sich als ``<jobname> (<wert>)``. Nur diese eine Form
# wird zerlegt; alles andere gilt als blanker Jobname.
_MATRIX_CONTEXT = re.compile(r"^(?P<base>.+?) \((?P<value>[^()]+)\)$")


def _on_block(doc: dict) -> dict:
    """``on:`` aus einem Workflow — YAML liest das blanke ``on`` als True."""
    block = doc.get("on") if "on" in doc else doc.get(True)
    assert isinstance(block, dict), "Workflow ohne `on:`-Mapping"
    return block


def _job_names(doc: dict) -> set[str]:
    """Wie sich die Jobs eines Workflows als Check-Kontext melden.

    Der Kontext ist ``name:`` falls gesetzt, sonst der Job-Schluessel — und
    bei einer Matrix haengt GitHub die Auspraegung in Klammern an. Hier
    interessiert nur die BASIS; die Klammer-Form loest
    :func:`_workflow_for_context` selbst auf.
    """
    names: set[str] = set()
    for key, job in (doc.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        name = job.get("name")
        names.add(str(name) if isinstance(name, str) and "${{" not in name else key)
    return names


def _workflows() -> dict[Path, dict]:
    docs: dict[Path, dict] = {}
    for path in sorted(WORKFLOW_DIR.glob("*.yml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:  # pragma: no cover - kaputte YAML faengt ein anderer Guard
            continue
        if isinstance(doc, dict) and doc.get("jobs"):
            docs[path] = doc
    return docs


def _workflow_for_context(context: str, docs: dict[Path, dict]) -> list[Path]:
    """Welche Workflows koennen diesen Kontext melden?

    Zuerst der blanke Jobname, dann — falls der Kontext wie ein Matrix-Job
    aussieht — die Basis vor der Klammer. Mehrdeutigkeit wird NICHT
    aufgeloest, sondern zurueckgegeben: zwei Workflows mit gleichem Jobnamen
    sind selbst ein Befund, und beide muessen den Trigger tragen.
    """
    hits = [p for p, d in docs.items() if context in _job_names(d)]
    if hits:
        return hits
    match = _MATRIX_CONTEXT.match(context)
    if match:
        base = match.group("base")
        return [p for p, d in docs.items() if base in _job_names(d)]
    return []


def test_the_required_context_population_is_not_empty() -> None:
    """Positivkontrolle: ein leerer Roster wuerde alles unten durchwinken."""
    assert len(REQUIRED_STATUS_CHECKS) >= 6, (
        f"nur {len(REQUIRED_STATUS_CHECKS)} required Kontexte — gemessen waren es "
        "am 2026-08-29 sechs (fast-gates, gate, validate (1)-(4)). Ein "
        "geschrumpfter Roster laesst diesen Waechter ueber nichts urteilen."
    )


def test_every_required_context_maps_to_a_workflow() -> None:
    """Ohne Zuordnung koennte der Trigger-Test still ueber 0 Dateien laufen."""
    docs = _workflows()
    unmapped = [c for c in REQUIRED_STATUS_CHECKS if not _workflow_for_context(c, docs)]
    assert not unmapped, (
        f"required Kontext(e) ohne erkennbaren Workflow: {unmapped}. Entweder "
        "wurde ein Job umbenannt (dann meldet er den required Kontext nicht "
        "mehr und JEDER Merge blockiert), oder diese Aufloesung passt nicht "
        "mehr zur Job-Benennung."
    )


def test_every_required_check_declares_merge_group() -> None:
    """Der eigentliche Satz: kein required Kontext ohne Merge-Queue-Trigger.

    Rot-zuerst bewiesen 2026-08-29: gegen den Stand vor diesem PR nennt die
    Fehlermeldung ``ci.yml`` mit den vier ``validate``-Shards.
    """
    docs = _workflows()
    missing: dict[str, list[str]] = {}
    for context in REQUIRED_STATUS_CHECKS:
        for path in _workflow_for_context(context, docs):
            if "merge_group" not in _on_block(docs[path]):
                missing.setdefault(path.name, []).append(context)
    assert not missing, (
        "Workflow(s) ohne `merge_group`-Trigger, die required Kontexte melden: "
        + "; ".join(f"{f} -> {sorted(c)}" for f, c in sorted(missing.items()))
        + ". Eine aktivierte Merge Queue wartet auf diese Kontexte, bis der "
        "Batch verfaellt — still, ohne dass etwas rot wird."
    )
