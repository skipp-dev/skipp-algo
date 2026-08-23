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
