# TV-Layout-Zustands-Wächter — Implementierungsplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein Regelkreis stellt die BUS-Bindungen des gehandelten Layouts selbsttätig wieder her, ohne dafür Quellen deployen zu müssen.

**Architecture:** Der Wächter ist kein neuer Beobachter. `tv-post-mutation-verify.yml` hält den Bindings-Snapshot eines beendeten Laufs bereits in der Hand und dispatcht bereits per `curl` auf `tv-save-consumer-source.yml` — dort kommt eine zusätzliche Entscheidung hinzu. Gerepariert wird über einen neuen, dritten Ausführungsmodus `repair-only`, der Bindungen repariert und das Layout speichert, aber weder Quellen speichert noch den Producer refresht; dadurch umgeht er das Manifest-Fenster, an dem die schreibenden Läufe heute scheitern.

**Tech Stack:** TypeScript (Node 20, `npx tsx --test`), Python 3.12 (pytest, Vertragstests gegen Workflow-YAML), GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-22-tv-layout-state-watchdog-design.md`

## Global Constraints

- **Der Ausführungsplan ist eingefroren.** `RolloutExecutionPlan` ist `Readonly<…>` und wird per `Object.freeze` zurückgegeben. Jeder neue Modus muss dieselbe Form wahren.
- **Die Refresh-Kadenz wird NICHT angefasst.** Operator-Entscheidung: eine veraltete Instanz ist ein echtes Risiko.
- **Kein Sonderfall für das Hold-Manager-Layout** (`twh98JLB`). Es gilt allein: repariert wird, was Mismatches zeigt.
- **Versuchsdeckel: 3 Reparaturläufe je ET-Handelstag.**
- **Schleifenschutz über Tatsachen, nicht Heuristik:** Auslösen nur bei `executionMode == "verify-only"` im Snapshot.
- **Ein per `GITHUB_TOKEN` dispatchter Lauf erzeugt keinen Folge-Verify** (GitHubs Rekursionsschutz, 13/13 gemessen 2026-08-22). Der Erfolg eines Reparaturlaufs muss aus seinem eigenen Artefakt gelesen werden.
- **Neue `.ts`-Testdateien brauchen DREI Registrierungsstellen** in `.github/workflows/tv-onboarding-packages.yml`: beide `paths:`-Filter und den `npx tsx --test`-Run-Step. Sonst rötet `tests/test_fast_gates_silent_skip_coverage.py::test_every_ts_test_is_gated_or_exempt`.
- **Vor jedem Push:** `git add -A`, dann `./scripts/run_ledger_drift_guard.sh` UND `ruff check .` getrennt; Guard nie in einen Leser pipen.

---

### Task 1: Der dritte Ausführungsmodus `repair-only`

**Files:**
- Modify: `automation/tradingview/lib/tv_consumer_rollout_evidence.ts`
- Test: `automation/tradingview/tests/tv_repair_only_execution_plan.test.ts` (create)

**Interfaces:**
- Consumes: nichts.
- Produces: `RolloutExecutionMode` erhält den Wert `"repair-only"`. `resolveExecutionPlan(args, env)` liefert bei `args.includes("--repair-only")` den eingefrorenen Plan `{mode: "repair-only", saveSources: false, refreshProducer: false, repairBindings: true, saveLayout: true}`.

- [ ] **Step 1: Write the failing test**

```ts
import assert from "node:assert/strict";
import { test } from "node:test";

import { resolveExecutionPlan } from "../lib/tv_consumer_rollout_evidence.js";

// Der Modus existiert, damit eine Reparatur NICHT mehr Geisel des Quellen-
// Deploys ist: `write` hat `saveSources: true` fest verdrahtet und geraet
// dadurch in das Manifest-Fenster, an dem die Saves am 2026-08-22 reihenweise
// verweigerten. repair-only deployt nichts.
test("repair-only repariert und speichert das Layout, deployt aber nichts", () => {
  const plan = resolveExecutionPlan(["--repair-only"], {});
  assert.equal(plan.mode, "repair-only");
  assert.equal(plan.repairBindings, true);
  assert.equal(plan.saveLayout, true);
  assert.equal(plan.saveSources, false);
  assert.equal(plan.refreshProducer, false);
});

test("repair-only ist eingefroren wie die anderen Modi", () => {
  const plan = resolveExecutionPlan(["--repair-only"], {});
  assert.equal(Object.isFrozen(plan), true);
});

// Spiegel der bestehenden verify-only-Zusicherung: der Modus muss JEDE
// schreibende Eingabe ablehnen, bevor ein Browser startet — nicht sie still
// ignorieren, sonst glaubt der Aufrufer, sein Refresh sei gelaufen.
test("repair-only lehnt schreibende Eingaben ab statt sie zu schlucken", () => {
  assert.throws(
    () => resolveExecutionPlan(["--repair-only"], { TV_REFRESH_PRODUCER: "true" }),
    /repair-only/,
  );
});

test("repair-only und verify-only schliessen einander aus", () => {
  assert.throws(
    () => resolveExecutionPlan(["--repair-only", "--verify-only"], {}),
    /repair-only/,
  );
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx tsx --test automation/tradingview/tests/tv_repair_only_execution_plan.test.ts`
Expected: FAIL — der Plan liefert `mode: "write"` mit `saveSources: true`, die beiden `throws`-Tests schlagen fehl.

- [ ] **Step 3: Write minimal implementation**

In `tv_consumer_rollout_evidence.ts`, Zeile 6, den Typ erweitern:

```ts
export type RolloutExecutionMode = "write" | "verify-only" | "repair-only";
```

In `resolveExecutionPlan`, direkt NACH dem `verifyOnly`-Block und VOR dem `refreshProducer && !forceRebind`-Wurf:

```ts
  const repairOnly = args.includes("--repair-only");
  if (repairOnly) {
    // Der Modus stellt her, was ein Producer-Refresh zerlegt hat, und deployt
    // dabei NICHTS. Schreibende Eingaben werden abgelehnt statt ignoriert:
    // ein stillschweigend verworfenes TV_REFRESH_PRODUCER liesse den Aufrufer
    // glauben, sein Refresh sei gelaufen.
    if (verifyOnly) {
      throw new Error("--repair-only conflicts with --verify-only");
    }
    if (isTrue(env.TV_REFRESH_PRODUCER)) {
      throw new Error("--repair-only refuses TV_REFRESH_PRODUCER=true: it repairs, it does not refresh");
    }
    return Object.freeze({
      mode: "repair-only" as const,
      saveSources: false,
      refreshProducer: false,
      repairBindings: true,
      saveLayout: true,
    });
  }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx tsx --test automation/tradingview/tests/tv_repair_only_execution_plan.test.ts`
Expected: PASS (4 Tests). Danach `npx tsc --noEmit` → RC=0.

- [ ] **Step 5: Register the new test file (sonst rötet der Gate-Wächter)**

In `.github/workflows/tv-onboarding-packages.yml` an DREI Stellen `automation/tradingview/tests/tv_repair_only_execution_plan.test.ts` ergänzen: die beiden `paths:`-Listen und den `npx tsx --test`-Run-Step.

Run: `.venv/bin/python -m pytest tests/test_fast_gates_silent_skip_coverage.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(tv): repair-only — reparieren ohne zu deployen"
```

---

### Task 2: Der Workflow-Schalter `repair_only`

**Files:**
- Modify: `.github/workflows/tv-save-consumer-source.yml`
- Test: `tests/test_workflow_tv_save_consumer_source_contract.py`

**Interfaces:**
- Consumes: den CLI-Schalter `--repair-only` aus Task 1.
- Produces: `workflow_dispatch.inputs.repair_only` (boolean, default false); der Save-Step übergibt `--repair-only`, wenn der Schalter gesetzt ist.

- [ ] **Step 1: Write the failing test**

```python
def test_repair_only_input_reaches_the_cli() -> None:
    """Der Schalter muss den CLI-Flag erreichen, nicht nur existieren.

    Ein Eingabefeld, das nirgends ankommt, ist die vakuose Variante dieses
    Features: der Dispatch sieht erfolgreich aus, der Lauf repariert nichts.
    """
    wf = _load()
    inputs = wf["on"]["workflow_dispatch"]["inputs"]
    assert "repair_only" in inputs, "der Schalter fehlt"
    assert inputs["repair_only"]["type"] == "boolean"
    assert inputs["repair_only"]["default"] is False

    save_step = next(
        step for step in wf["jobs"]["save"]["steps"]
        if step.get("id") == "save"
    )
    assert "--repair-only" in save_step["run"], (
        "der Schalter erreicht die CLI nicht — der Lauf wuerde als write laufen"
    )
    assert "inputs.repair_only" in save_step["run"]


def test_the_repair_run_obeys_the_operator_window() -> None:
    """Ein Reparaturlauf mutiert — also gilt das Operator-Gate fuer ihn.

    Sonst kaempft die Automatik gegen die Hand des Operators, waehrend er
    selbst am Chart arbeitet.
    """
    wf = _load()
    gate = next(
        step for step in wf["jobs"]["save"]["steps"]
        if "Refuse to mutate inside the operator" in step.get("name", "")
    )
    assert "verify_only" in gate["if"] or "verify_only" in gate.get("run", ""), (
        "das Gate unterscheidet heute nur verify-only von write"
    )
    assert "repair_only" not in gate.get("if", ""), (
        "repair_only darf das Gate NICHT umgehen — es mutiert das Layout"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_workflow_tv_save_consumer_source_contract.py::test_repair_only_input_reaches_the_cli -q`
Expected: FAIL — `der Schalter fehlt`.

- [ ] **Step 3: Write minimal implementation**

In `tv-save-consumer-source.yml` bei `workflow_dispatch.inputs`, direkt nach `verify_only`:

```yaml
      repair_only:
        description: "Nur Bindungen reparieren und Layout speichern — kein Quellen-Save, kein Producer-Refresh. Umgeht das Manifest-Fenster."
        type: boolean
        required: false
        default: false
```

Im Save-Step (`id: save`) die Modus-Auswahl erweitern — dort, wo heute `--verify-only` gesetzt wird:

```bash
          MODE_FLAGS=""
          if [ "${{ github.event.inputs.verify_only }}" = "true" ]; then
            MODE_FLAGS="--verify-only"
          elif [ "${{ github.event.inputs.repair_only }}" = "true" ]; then
            MODE_FLAGS="--repair-only"
          fi
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_workflow_tv_save_consumer_source_contract.py -q`
Expected: PASS (alle Tests der Datei).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(tv): workflow-Schalter repair_only, verdrahtet bis zur CLI"
```

---

### Task 3: Nur betroffene Layouts reparieren

**Files:**
- Modify: `automation/tradingview/lib/tv_out_of_band_drift.ts` (reiner Selektor, liegt bei den anderen Snapshot-Auswertungen)
- Modify: `scripts/tv_batch_consumer_rollout.ts`
- Test: `automation/tradingview/tests/tv_layouts_needing_repair.test.ts` (create)

**Interfaces:**
- Consumes: den Bindings-Snapshot (`bindings.consumers[]` mit `scriptName` und `mismatches[]`).
- Produces: `selectLayoutsNeedingRepair(consumers, targets)` → `string[]` der Chart-URLs mit Mismatches, in Besuchsreihenfolge, dedupliziert.

- [ ] **Step 1: Write the failing test**

```ts
import assert from "node:assert/strict";
import { test } from "node:test";

import { selectLayoutsNeedingRepair } from "../lib/tv_out_of_band_drift.js";

const targets = [
  { scriptName: "SMC Decision Board", chartUrl: "https://tv/chart/A/" },
  { scriptName: "SMC Setup Check", chartUrl: "https://tv/chart/A/" },
  { scriptName: "SMC Hold Manager", chartUrl: "https://tv/chart/B/" },
];

test("nur Layouts mit Mismatches werden ausgewaehlt", () => {
  const consumers = [
    { scriptName: "SMC Decision Board", mismatches: [] },
    { scriptName: "SMC Setup Check", mismatches: [{ label: "BUS Armed" }] },
    { scriptName: "SMC Hold Manager", mismatches: [] },
  ];
  assert.deepEqual(selectLayoutsNeedingRepair(consumers, targets), ["https://tv/chart/A/"]);
});

test("ein sauberer Snapshot waehlt nichts aus", () => {
  const consumers = targets.map((t) => ({ scriptName: t.scriptName, mismatches: [] }));
  assert.deepEqual(selectLayoutsNeedingRepair(consumers, targets), []);
});

// Kein Sonderfall fuer das Hold-Manager-Layout: driftet es, wird es repariert.
// Operator-Entscheidung 2026-08-22 — es gilt allein die allgemeine Regel.
test("auch das Hold-Manager-Layout wird ausgewaehlt, wenn es driftet", () => {
  const consumers = [
    { scriptName: "SMC Decision Board", mismatches: [] },
    { scriptName: "SMC Setup Check", mismatches: [] },
    { scriptName: "SMC Hold Manager", mismatches: [{ label: "BUS Armed" }] },
  ];
  assert.deepEqual(selectLayoutsNeedingRepair(consumers, targets), ["https://tv/chart/B/"]);
});

test("jedes Layout erscheint hoechstens einmal", () => {
  const consumers = [
    { scriptName: "SMC Decision Board", mismatches: [{ label: "x" }] },
    { scriptName: "SMC Setup Check", mismatches: [{ label: "y" }] },
    { scriptName: "SMC Hold Manager", mismatches: [] },
  ];
  assert.deepEqual(selectLayoutsNeedingRepair(consumers, targets), ["https://tv/chart/A/"]);
});

// Ein Konsument, den der Snapshot gar nicht kennt, darf nicht still als sauber
// gelten — leere Beobachtung ist nicht gruen.
test("ein im Snapshot fehlender Konsument waehlt sein Layout aus", () => {
  const consumers = [{ scriptName: "SMC Decision Board", mismatches: [] }];
  assert.deepEqual(selectLayoutsNeedingRepair(consumers, targets), [
    "https://tv/chart/A/",
    "https://tv/chart/B/",
  ]);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx tsx --test automation/tradingview/tests/tv_layouts_needing_repair.test.ts`
Expected: FAIL — `does not provide an export named 'selectLayoutsNeedingRepair'`.

- [ ] **Step 3: Write minimal implementation**

In `automation/tradingview/lib/tv_out_of_band_drift.ts` anhängen:

```ts
export type RepairCandidateConsumer = {
  scriptName: string;
  mismatches: readonly unknown[];
};

export type RepairCandidateTarget = {
  scriptName: string;
  chartUrl: string;
};

/**
 * Die Layouts, die eine Reparatur brauchen — und nur die.
 *
 * Ein Konsument, den der Snapshot NICHT nennt, zaehlt als reparaturbeduerftig:
 * eine leere Beobachtung ist kein gruener Befund (2026-08-14, `bindings: []`
 * vergiftete die Drift-Grundlinie). Lieber einmal zu viel reparieren — die
 * Reparatur ist idempotent — als ein zerlegtes Layout fuer sauber halten.
 */
export function selectLayoutsNeedingRepair(
  consumers: readonly RepairCandidateConsumer[],
  targets: readonly RepairCandidateTarget[],
): string[] {
  const byName = new Map(consumers.map((c) => [c.scriptName, c]));
  const needed: string[] = [];
  for (const target of targets) {
    const observed = byName.get(target.scriptName);
    const broken = !observed || observed.mismatches.length > 0;
    if (broken && !needed.includes(target.chartUrl)) {
      needed.push(target.chartUrl);
    }
  }
  return needed;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx tsx --test automation/tradingview/tests/tv_layouts_needing_repair.test.ts`
Expected: PASS (5 Tests).

- [ ] **Step 5: Wire it into the rollout**

In `scripts/tv_batch_consumer_rollout.ts`, in der Layout-Schleife (`for (const layout of groupTargetsByLayout(...))`), unmittelbar nach dem `mutatingLayout`-Zeile einfügen:

```ts
        // Im repair-only-Modus wird NUR angefasst, was der Vor-Mutations-
        // Snapshot als defekt gemeldet hat. Saubere Layouts bleiben unberuehrt —
        // ein Reparaturlauf darf kein zweiter Zerstoerer werden.
        if (executionPlan.mode === "repair-only" && !layoutsNeedingRepair.includes(layout.chartUrl)) {
          tracePageEvent(session.page, "repair-skip-clean-layout", layout.chartUrl);
          continue;
        }
```

`layoutsNeedingRepair` wird direkt nach der Vor-Mutations-Beobachtung berechnet:

```ts
    const layoutsNeedingRepair = executionPlan.mode === "repair-only"
      ? selectLayoutsNeedingRepair(report.bindings.consumers, config.verifyTargets)
      : [];
```

- [ ] **Step 6: Run the surrounding lane**

Run: `npx tsc --noEmit` und `npx tsx --test automation/tradingview/tests/tv_rollout_verify_order.test.ts automation/tradingview/tests/tv_rollout_layout_save_points.test.ts`
Expected: RC=0, alle PASS.

- [ ] **Step 7: Register the new test file + commit**

Drei Registrierungsstellen wie in Task 1, dann:

```bash
git add -A
git commit -m "feat(tv): repair-only fasst nur die Layouts mit Mismatches an"
```

---

### Task 4: Die Wächter-Entscheidung

**Files:**
- Create: `scripts/tv_repair_watchdog_decision.py`
- Create: `tests/test_tv_repair_watchdog_decision.py`

**Interfaces:**
- Consumes: den Bindings-Snapshot als JSON-Datei; die Zahl der heute bereits erfolgten Reparatur-Dispatches.
- Produces: `decide(snapshot: dict, dispatches_today: int, repair_in_flight: bool = False) -> Decision` mit `Decision.dispatch: bool`, `Decision.reason: str`. CLI: `python -m scripts.tv_repair_watchdog_decision --snapshot <pfad> --dispatches-today <n> [--repair-in-flight]` → exit 0 und `dispatch=true|false` plus `reason=` nach `$GITHUB_OUTPUT`.

- [ ] **Step 1: Write the failing test**

```python
"""Die Entscheidung des Waechters, ausserhalb des Browsers und einzeln beweisbar."""
from __future__ import annotations

import pytest

from scripts.tv_repair_watchdog_decision import DAILY_DISPATCH_CAP, decide


def _snapshot(mode: str = "verify-only", mismatches: int = 0) -> dict:
    return {
        "executionMode": mode,
        "bindings": {
            "checkedConsumers": 10,
            "consumers": [
                {"scriptName": "SMC Setup Check", "mismatches": [{"label": "BUS Armed"}] * mismatches},
            ],
        },
    }


def test_drift_in_a_verify_snapshot_triggers_a_repair() -> None:
    decision = decide(_snapshot(mismatches=1), dispatches_today=0)
    assert decision.dispatch is True
    assert "mismatch" in decision.reason.lower()


def test_a_clean_snapshot_triggers_nothing() -> None:
    assert decide(_snapshot(mismatches=0), dispatches_today=0).dispatch is False


def test_a_repair_snapshot_never_triggers_another_repair() -> None:
    """Schleifenschutz ueber eine Tatsache im Artefakt, nicht ueber Herkunft."""
    decision = decide(_snapshot(mode="repair-only", mismatches=1), dispatches_today=0)
    assert decision.dispatch is False
    assert "repair-only" in decision.reason


def test_a_write_snapshot_never_triggers_a_repair() -> None:
    assert decide(_snapshot(mode="write", mismatches=1), dispatches_today=0).dispatch is False


def test_the_cap_stops_dispatching_and_says_so() -> None:
    decision = decide(_snapshot(mismatches=1), dispatches_today=DAILY_DISPATCH_CAP)
    assert decision.dispatch is False
    assert str(DAILY_DISPATCH_CAP) in decision.reason
    assert "operator" in decision.reason.lower(), (
        "ein Regelkreis, der aufgibt, muss lauter sein als einer, der arbeitet"
    )


def test_a_repair_already_in_flight_blocks_a_second_one() -> None:
    """Kein Stapeln: ein wartender Reparaturlauf genuegt.

    Der Deckel allein reicht dafuer nicht — drei Laeufe duerften sich sonst
    gleichzeitig um denselben Warteplatz der Session-Gruppe draengen.
    """
    decision = decide(_snapshot(mismatches=1), dispatches_today=0, repair_in_flight=True)
    assert decision.dispatch is False
    assert "flight" in decision.reason.lower() or "wartet" in decision.reason.lower()


def test_an_empty_observation_is_not_green() -> None:
    """checkedConsumers=0 heisst UNBEKANNT, nicht sauber."""
    empty = _snapshot(mismatches=0)
    empty["bindings"]["checkedConsumers"] = 0
    empty["bindings"]["consumers"] = []
    decision = decide(empty, dispatches_today=0)
    assert decision.dispatch is False
    assert "leer" in decision.reason.lower() or "empty" in decision.reason.lower()


@pytest.mark.parametrize("missing", ["executionMode", "bindings"])
def test_a_malformed_snapshot_refuses_rather_than_guesses(missing: str) -> None:
    broken = _snapshot(mismatches=1)
    del broken[missing]
    decision = decide(broken, dispatches_today=0)
    assert decision.dispatch is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_tv_repair_watchdog_decision.py -q`
Expected: FAIL — `ModuleNotFoundError: scripts.tv_repair_watchdog_decision`.

- [ ] **Step 3: Write minimal implementation**

```python
"""Entscheidet, ob ein Bindings-Snapshot einen Reparaturlauf ausloest.

Rein und ohne Netz, damit die Entscheidung einzeln beweisbar ist — die
Browser-Haelfte laesst sich nicht testen, die Entscheidung schon.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path

#: Drei Fehlschlaege an denselben Zielen sind kein Flake, sondern ein Befund —
#: und ein vierter Lauf kostet einen Warteplatz in der Session-Gruppe, den ein
#: echter Save braucht.
DAILY_DISPATCH_CAP = 3


@dataclass(frozen=True)
class Decision:
    dispatch: bool
    reason: str


def decide(snapshot: dict, dispatches_today: int, repair_in_flight: bool = False) -> Decision:
    mode = snapshot.get("executionMode")
    if mode != "verify-only":
        # Schleifenschutz: ein Reparatur-Snapshot traegt "repair-only" und darf
        # keinen weiteren ausloesen. Ein "write"-Lauf repariert ohnehin selbst.
        return Decision(False, f"executionMode={mode!r} — nur verify-only loest aus")

    bindings = snapshot.get("bindings")
    if not isinstance(bindings, dict):
        return Decision(False, "Snapshot ohne bindings — fail closed, kein Urteil")

    if not bindings.get("checkedConsumers"):
        # Leer ist nicht gruen (2026-08-14): ein Fehlschlag pusht bindings: [].
        # Daraus eine Reparatur abzuleiten hiesse, auf Rauschen zu mutieren.
        return Decision(False, "leere Beobachtung (checkedConsumers=0) — kein Urteil")

    drifted = [
        c.get("scriptName")
        for c in bindings.get("consumers") or []
        if c.get("mismatches")
    ]
    if not drifted:
        return Decision(False, "keine Mismatches — nichts zu reparieren")

    if repair_in_flight:
        # Kein Stapeln: ein wartender Reparaturlauf reicht. Der Deckel allein
        # verhindert das nicht — drei Laeufe koennten sich sonst gleichzeitig um
        # denselben Warteplatz der Session-Gruppe draengen.
        return Decision(False, "ein Reparaturlauf ist bereits in flight — kein zweiter")

    if dispatches_today >= DAILY_DISPATCH_CAP:
        return Decision(
            False,
            f"Deckel erreicht: {dispatches_today}/{DAILY_DISPATCH_CAP} Reparaturlaeufe heute — "
            f"Operator noetig, betroffen: {', '.join(str(d) for d in drifted)}",
        )

    return Decision(True, f"mismatch bei: {', '.join(str(d) for d in drifted)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--dispatches-today", type=int, default=0)
    parser.add_argument("--repair-in-flight", action="store_true")
    args = parser.parse_args()

    try:
        snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - jede Lesefehlerart faellt fail-closed
        decision = Decision(False, f"Snapshot unlesbar: {exc}")
    else:
        decision = decide(snapshot, args.dispatches_today, args.repair_in_flight)

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"dispatch={'true' if decision.dispatch else 'false'}\n")
            handle.write(f"reason={decision.reason}\n")
    print(f"dispatch={decision.dispatch} reason={decision.reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_tv_repair_watchdog_decision.py -q`
Expected: PASS (8 Tests).

- [ ] **Step 5: Mutationsprobe (nach dem Commit, nicht davor)**

Erst committen:

```bash
git add -A
git commit -m "feat(tv): Waechter-Entscheidung — rein, fail-closed, gedeckelt"
```

Dann den Schleifenschutz entfernen (`mode != "verify-only"`-Block auskommentieren) und `pytest tests/test_tv_repair_watchdog_decision.py -q` fahren: `test_a_repair_snapshot_never_triggers_another_repair` MUSS rot werden. Danach `git checkout -- scripts/tv_repair_watchdog_decision.py`.

---

### Task 5: Verdrahtung im Verify-Workflow und Sichtbarkeit

**Files:**
- Modify: `.github/workflows/tv-post-mutation-verify.yml`
- Test: `tests/test_workflow_tv_post_mutation_verify_contract.py`

**Interfaces:**
- Consumes: `scripts/tv_repair_watchdog_decision.py` aus Task 4; den `repair_only`-Schalter aus Task 2.
- Produces: nichts, worauf spätere Tasks aufbauen.

- [ ] **Step 1: Write the failing test**

```python
def test_the_watchdog_dispatches_a_repair_and_says_why() -> None:
    """Die fehlende Kante von der Messung zur Handlung.

    Der Verify-Lauf misst den Layout-Zustand bereits und laedt ihn hoch; bis
    2026-08-22 handelte niemand darauf. Diese Kante ist der ganze Waechter.
    """
    steps = {step["name"]: step for step in _steps()}
    decision = steps["Decide whether the layout needs a repair"]
    assert "scripts/tv_repair_watchdog_decision.py" in decision["run"]
    assert "--snapshot" in decision["run"]
    assert "--dispatches-today" in decision["run"], (
        "ohne Deckel-Argument liefe der Waechter unbegrenzt"
    )

    dispatch = steps["Dispatch the repair run"]
    assert "repair_only" in dispatch["run"], "der Dispatch muss den Modus setzen"
    assert "verify_only" not in dispatch["run"], (
        "ein Verify repariert nichts — das waere die vakuose Variante"
    )
    assert "steps.repair_decision.outputs.dispatch == 'true'" in dispatch["if"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_workflow_tv_post_mutation_verify_contract.py::test_the_watchdog_dispatches_a_repair_and_says_why -q`
Expected: FAIL — `KeyError: 'Decide whether the layout needs a repair'`.

- [ ] **Step 3: Write minimal implementation**

In `tv-post-mutation-verify.yml`, nach dem bestehenden Mode-Step und vor dem Dispatch-Step:

```yaml
      - name: Decide whether the layout needs a repair
        id: repair_decision
        if: ${{ always() && steps.mode.outputs.mode == 'verify-only' }}
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          set -euo pipefail
          # Wie viele Reparaturlaeufe hat der Waechter heute schon ausgeloest?
          # Gezaehlt wird ueber die dispatch-Laeufe des Save-Workflows mit
          # repair_only — die Plattform ist der Zaehler, kein eigener Zustand.
          # ET-Handelstag, nicht UTC-Tag: der Deckel soll zur Kadenz der
          # Refreshes passen, und die haengt am US-Markt.
          today="$(TZ=America/New_York date +%F)"
          runs="$(gh api "repos/${GITHUB_REPOSITORY}/actions/workflows/tv-save-consumer-source.yml/runs?event=workflow_dispatch&per_page=100")"
          count="$(printf '%s' "$runs" | jq "[.workflow_runs[] | select((.created_at | fromdateiso8601 | strflocaltime(\"%Y-%m-%d\")) == \"${today}\")] | length")"
          in_flight="$(printf '%s' "$runs" | jq '[.workflow_runs[] | select(.status != "completed")] | length')"
          flag=""
          [ "${in_flight}" -gt 0 ] && flag="--repair-in-flight"
          python3 scripts/tv_repair_watchdog_decision.py \
            --snapshot snapshot/tradingview_consumer_bindings.json \
            --dispatches-today "${count}" ${flag}

      - name: Dispatch the repair run
        if: ${{ always() && steps.repair_decision.outputs.dispatch == 'true' }}
        env:
          GITHUB_TOKEN: ${{ github.token }}
        run: |
          set -euo pipefail
          echo "::warning title=Layout repair dispatched::${{ steps.repair_decision.outputs.reason }}"
          curl -sS -X POST \
            -H "Authorization: Bearer ${GITHUB_TOKEN}" \
            -H "Accept: application/vnd.github+json" \
            "https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/workflows/tv-save-consumer-source.yml/dispatches" \
            -d '{"ref":"main","inputs":{"repair_only":"true"}}'

      - name: Say it when the watchdog gives up
        if: ${{ always() && steps.repair_decision.outputs.dispatch == 'false' && contains(steps.repair_decision.outputs.reason, 'Deckel erreicht') }}
        run: |
          echo "::error title=Layout repair gave up::${{ steps.repair_decision.outputs.reason }}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_workflow_tv_post_mutation_verify_contract.py -q`
Expected: PASS (alle Tests der Datei — auch der abgeleitete Feldlisten-Test aus #5017 muss gruen bleiben).

- [ ] **Step 5: Sonden-Eintrag (verbindliche Anforderung aus dem Spec)**

In `~/.claude/scripts/tv_gate_probe_check.sh` einen Urteilsblock nach dem Muster von `#5013`/`#5020` ergänzen: inhaltliche Versionsprobe über `executionMode == "repair-only"` in einem Artefakt — ein Lauf ohne diesen Modus meldet „KANN NICHT BEZEUGEN" statt fälschlich PASS. Ohne diesen Block gilt die Live-Wirksamkeit als unbewiesen.

Run: `bash ~/.claude/scripts/tv_gate_probe_check.sh`
Expected: RC=0, der neue Block meldet ein Urteil (kein `PROBE-FEHLER`).

- [ ] **Step 6: Guard, ruff, commit**

```bash
git add -A
ruff check .
PYTEST_ADDOPTS="-n 4" ./scripts/run_ledger_drift_guard.sh > /tmp/guard.out 2>&1; echo "RC=$?"; grep -c FAILED /tmp/guard.out
git commit -m "feat(tv): der Waechter schliesst die Kante von der Messung zur Reparatur"
```

---

## Zum dritten Alarmzustand

Das Spec nennt drei Zustaende. Zwei bekommen in Task 5 eigene Schritte:
*Reparatur unterwegs* (`::warning::`) und *Reparatur aufgegeben* (`::error::`).
Der dritte — *Reparatur gelungen, Alarm loescht sich selbst* — braucht **keinen
eigenen Task**: Der Drift-Alarm leitet sich aus dem publizierten Bindings-Snapshot
ab, und der naechste Verify-Lauf schreibt ihn ohne Mismatches fort. Wer hier einen
fehlenden Task sucht, sucht vergebens; wer den Alarm nach einer erfolgreichen
Reparatur weiter brennen sieht, hat dagegen einen echten Befund.

## Was dieser Plan bewusst NICHT tut

- Die Refresh-Kadenz senken (Operator-Entscheidung).
- Die Zerstörung vermeiden (eigener Spike, im Spec als ungemessen markiert).
- Den ungegateten Abend-Zweig von `run-c13-tws-reminder.sh` anfassen.
