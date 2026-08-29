"""Ein Guard, der liest, darf nicht blind bleiben, wenn seine Vorlage sich aendert.

``tv-onboarding-packages.yml`` faehrt eine Reihe Node-Tests, die NICHT das
Verhalten von Code messen, sondern seinen QUELLTEXT lesen und Formen darin
pinnen (``fs.readFileSync(path.join(repoRoot, "scripts", "..."))``). Ein
solcher Pin ist nur so viel wert wie sein Ausloeser: steht die gelesene Datei
nicht in den ``paths:`` des Workflows, kann genau sie sich aendern, ohne dass
der Pin je laeuft.

Gemessen 2026-08-29, und zwar am eigenen Fehler: ``scripts/tv_batch_consumer_
rollout.ts`` wurde von VIER Tests dieses Workflows gelesen und stand in
keiner der beiden ``paths``-Listen. #5177 aenderte die Datei und stellte
``tv_producer_refresh_layouts.test.ts`` rot — der Job lief nur, weil der PR
zufaellig auch ``automation/tradingview/lib/**`` anfasste. Der Nachzug-PR,
der genau diesen Pin reparierte, haette den Job NICHT ausgeloest: er fasst
nur das Skript an. Ein Fix ohne Beweis, in einem Repo, das Beweise verlangt.

Dieser Guard laeuft in pytest und damit auf dem REQUIRED Pfad (fast-gates /
validate), waehrend der Node-Job selbst pfadgefiltert ist. Genau darum geht
es: die Aussage "der Pin kann feuern" darf nicht von demselben Pfadfilter
abhaengen, ueber den sie urteilt.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tv-onboarding-packages.yml"
TEST_DIR = REPO_ROOT / "automation" / "tradingview" / "tests"

#: ``path.join(repoRoot, "scripts", "name.ts")`` — die Form, mit der die
#: Node-Tests dieses Workflows Quelldateien einlesen.
_READ = re.compile(r'path\.join\(\s*repoRoot\s*,\s*"scripts"\s*,\s*"([^"]+)"\s*\)')


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _declared_paths() -> set[str]:
    """Alle ``paths:``-Eintraege ueber ALLE Trigger dieses Workflows."""
    doc = _workflow()
    triggers = doc.get("on") if "on" in doc else doc.get(True)
    assert isinstance(triggers, dict), "Workflow ohne `on:`-Mapping"
    declared: set[str] = set()
    for spec in triggers.values():
        if isinstance(spec, dict):
            declared.update(str(p) for p in (spec.get("paths") or []))
    return declared


def _tests_run_by_the_workflow() -> set[Path]:
    """Die Testdateien, die der Workflow wirklich startet (aus seinem Run-Step)."""
    text = WORKFLOW.read_text(encoding="utf-8")
    names = set(re.findall(r"automation/tradingview/tests/([A-Za-z0-9_.]+\.test\.ts)", text))
    return {TEST_DIR / n for n in names if (TEST_DIR / n).is_file()}


def test_the_derivation_is_not_empty() -> None:
    """Positivkontrolle: ohne Tests und ohne Pfade urteilt der Guard ueber nichts."""
    tests = _tests_run_by_the_workflow()
    assert len(tests) >= 20, (
        f"nur {len(tests)} Testdateien aus dem Workflow abgeleitet — am "
        "2026-08-29 waren es ueber 60. Die Ableitung ist kollabiert."
    )
    assert len(_declared_paths()) >= 20, "paths-Liste unerwartet kurz"


def test_every_script_a_workflow_test_reads_is_also_watched() -> None:
    """Was ein Pin liest, muss ihn ausloesen koennen."""
    declared = _declared_paths()
    missing: dict[str, set[str]] = {}
    found_any = False
    for test_file in sorted(_tests_run_by_the_workflow()):
        for script in _READ.findall(test_file.read_text(encoding="utf-8")):
            found_any = True
            rel = f"scripts/{script}"
            # Ein Glob wie `scripts/tv_publish_*.ts` deckt seine Familie ab.
            covered = rel in declared or any(
                p.endswith("*.ts") and rel.startswith(p[:-4]) for p in declared
            )
            if not covered:
                missing.setdefault(rel, set()).add(test_file.name)
    assert found_any, (
        "kein einziger `path.join(repoRoot, \"scripts\", ...)`-Lesezugriff "
        "gefunden — die Regex passt nicht mehr zur Schreibweise der Tests, "
        "und dieser Guard urteilt ueber nichts"
    )
    assert not missing, (
        "Diese Skripte werden von Tests dieses Workflows GELESEN, stehen aber "
        "in keiner seiner `paths:`-Listen — eine Aenderung an ihnen kann die "
        "Pins brechen, ohne dass der Job laeuft:\n  "
        + "\n  ".join(f"{s} <- {', '.join(sorted(t))}" for s, t in sorted(missing.items()))
    )
