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
