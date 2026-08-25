import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import {
  classifyDialogAtFailure,
  formatLegendDblclickBoxDetail,
  pickDialogForScript,
  recordSettingsIdentityMismatch,
  resetSettingsIdentityMismatchCount,
  SETTINGS_IDENTITY_MISMATCH_ESCALATION_THRESHOLD,
  settingsIdentityMismatchCount,
  shouldEscalateSettingsOpenPath,
  type SettingsIdentityMismatchCounts,
} from "../lib/tv_shared.js";

// Source-pin helpers (same shape as tv_open_script_identity.test.ts): the
// pure map-helper tests above prove the counting/threshold LOGIC in
// isolation, but say nothing about whether openSettingsForScript actually
// calls into it. Review Fix-Runde 1, I3: four rollbacks (reset call removed,
// mismatch recording removed, escalation dispatch removed, dblclick-start
// detail removed) left the full suite green because nothing pinned the
// WIRING itself.
const _dir = path.dirname(fileURLToPath(import.meta.url));

function tvSharedSource(): string {
  return fs.readFileSync(path.join(_dir, "..", "lib", "tv_shared.ts"), "utf-8");
}

function functionBody(source: string, header: string): string {
  const start = source.indexOf(header);
  assert.ok(start !== -1, `expected to find ${JSON.stringify(header)} in tv_shared.ts`);
  const next = source.indexOf("\nexport ", start + header.length);
  return source.slice(start, next === -1 ? source.length : next);
}

// 2026-08-23, Lauf 32556181388: Ziel `SMC Long-Dip Alerts` sah in EINEM Lauf
// drei VERSCHIEDENE fremde Dialoge — `SMC Breakout Overlay` (4x),
// `SMC Setup Check` (2x) und den Producer `SMC Long-Dip Suite` (2x). Bei einem
// einzigen haengengebliebenen Dialog waere der Fremde immer derselbe gewesen;
// drei verschiedene sind nur moeglich, wenn MEHRERE Dialoge gleichzeitig
// sichtbar sind.
//
// Die Pruefung nahm bis dahin `dialogs.find(titled)` — den ERSTEN mit Titel,
// nicht den passenden. Bei mehreren offenen Dialogen ist das eine Lotterie: der
// richtige Dialog kann offen sein und trotzdem abgelehnt werden, was den
// 60-s-Timeout erzeugt.
//
// Reine Auswahl, ohne Browser beweisbar. Der DOM-Teil (welche Dialoge ueberhaupt
// sichtbar sind) bleibt Playwright-gegen-TradingView.

const d = (title: string) => ({ title, text: "", labelTexts: [] as string[] });

test("der passende Dialog wird gewaehlt, auch wenn er nicht der erste ist", () => {
  const picked = pickDialogForScript(
    [d("SMC Breakout Overlay"), d("SMC Long-Dip Suite"), d("SMC Long-Dip Alerts")],
    "SMC Long-Dip Alerts",
  );
  assert.equal(picked.verdict, "match");
  assert.equal(picked.dialog?.title, "SMC Long-Dip Alerts");
});

test("passt der erste, bleibt es beim ersten", () => {
  const picked = pickDialogForScript([d("SMC Setup Check")], "SMC Setup Check");
  assert.equal(picked.verdict, "match");
});

test("passt KEINER, ist es ein echter Mismatch — und er nennt die Anzahl", () => {
  const picked = pickDialogForScript(
    [d("SMC Breakout Overlay"), d("SMC Long-Dip Suite")],
    "SMC Long-Dip Alerts",
  );
  assert.equal(picked.verdict, "mismatch");
  assert.equal(picked.visibleCount, 2, "die Anzahl gehoert in die Spur — sie ist der Befund");
  assert.equal(picked.dialog?.title, "SMC Breakout Overlay");
});

test("kein Dialog mit Titel bleibt 'untitled', nicht 'mismatch'", () => {
  // Das ist der bestehende implicit-surface-Pfad: eine sichtbare
  // Einstellungsflaeche ohne lesbaren Titel wird NICHT als falsches Skript
  // gewertet. Diese Unterscheidung darf die Aenderung nicht verlieren.
  assert.equal(pickDialogForScript([], "SMC Setup Check").verdict, "untitled");
  assert.equal(pickDialogForScript([d("   ")], "SMC Setup Check").verdict, "untitled");
});

test("der Versions-Chip steht dem Treffer nicht im Weg", () => {
  const picked = pickDialogForScript([d("SMC Long-Dip Alerts · 69.0")], "SMC Long-Dip Alerts");
  assert.equal(picked.verdict, "match");
});

test("die Auswahl erbt die Semantik des bestehenden Matchers, sie erfindet keine", () => {
  // settingsDialogTitleMatchesScriptName behandelt "candidate startsWith
  // scriptName" ABSICHTLICH als Treffer — so werden Versions-Chips abgedeckt.
  // Folge: ein kuerzerer Zielname trifft auch einen laengeren Dialogtitel.
  // Hier festgehalten, damit die Erbschaft sichtbar ist und niemand sie fuer
  // ein Versehen dieser Funktion haelt. In der Praxis harmlos, weil die
  // Rollout-Config nur vollstaendige Skriptnamen fuehrt.
  // Gemessen am echten Matcher (nicht vermutet): er ist in BEIDEN Richtungen
  // permissiv.
  assert.equal(pickDialogForScript([d("SMC Long-Dip Dashboard")], "SMC Long-Dip").verdict, "match");
  assert.equal(pickDialogForScript([d("SMC Long-Dip")], "SMC Long-Dip Dashboard").verdict, "match");

  // Fuer den realen Fall traegt das trotzdem: die Skriptnamen, um die es geht,
  // teilen kein Praefix. Genau darauf beruht der Nutzen dieser Auswahl.
  assert.equal(
    pickDialogForScript([d("SMC Breakout Overlay"), d("SMC Long-Dip Alerts")], "SMC Long-Dip Alerts").dialog?.title,
    "SMC Long-Dip Alerts",
  );
});

// Ledger klasse-h, Kandidat (A): "der Dialog war spaeter da" beweist noch
// nicht "die Erkennung war zu schnell". classifyDialogAtFailure ist die
// Entscheidungslogik hinter der Messprobe, die genau DAS am realen Lauf
// entscheidet — angewandt auf die Dialoge, die GENAU im Moment der
// Fehlschlag-Deklaration sichtbar sind (nicht die spaeter geschriebene
// Beweisdatei). Vier Zustaende, damit "kein Dialog", "Dialog mit fremdem
// Titel" und "Dialog ohne lesbaren Titel" nicht ununterscheidbar zusammenfallen.
test("classifyDialogAtFailure: kein sichtbarer Dialog ist 'no-dialog', nicht 'untitled'", () => {
  const classified = classifyDialogAtFailure([], "SMC Long-Dip Alerts");
  assert.equal(classified.verdict, "no-dialog");
  assert.equal(classified.title, null);
  assert.equal(classified.visibleCount, 0);
});

test("classifyDialogAtFailure: der Zieldialog ist sichtbar -> 'target-visible' (Kandidat A waere bewiesen)", () => {
  const classified = classifyDialogAtFailure(
    [d("SMC Breakout Overlay"), d("SMC Long-Dip Alerts")],
    "SMC Long-Dip Alerts",
  );
  assert.equal(classified.verdict, "target-visible");
  assert.equal(classified.title, "SMC Long-Dip Alerts");
  assert.equal(classified.visibleCount, 2);
});

test("classifyDialogAtFailure: ein fremder Dialog ist sichtbar -> 'foreign-visible' mit seinem Titel", () => {
  const classified = classifyDialogAtFailure([d("SMC Setup Check")], "SMC Long-Dip Alerts");
  assert.equal(classified.verdict, "foreign-visible");
  assert.equal(classified.title, "SMC Setup Check");
  assert.equal(classified.visibleCount, 1);
});

test("classifyDialogAtFailure: ein sichtbarer Dialog ohne lesbaren Titel ist 'untitled-visible', nicht 'no-dialog'", () => {
  const classified = classifyDialogAtFailure([d("   ")], "SMC Long-Dip Alerts");
  assert.equal(classified.verdict, "untitled-visible");
  assert.equal(classified.title, null);
});

// Ledger klasse-h, Eskalation (Lauf 32803019213, save-Job 2026-08-25
// 11:52:50Z): der Doppelklick-Pfad trifft stabil den Legenden-NACHBARN
// (Alerts->Setup Check 2x, Alerts->Breakout Overlay 1x, symmetrisch Setup
// Check->Alerts 1x). Ab dem ZWEITEN Mismatch fuer dasselbe Ziel eskaliert
// openSettingsForScript auf den zeilengebundenen Knopf-Pfad statt erneut
// doppelzuklicken. Reine Zaehl-/Entscheidungslogik auf einer Map, ohne
// Browser beweisbar.

test("der erste Mismatch fuer ein Ziel eskaliert noch nicht", () => {
  const counts: SettingsIdentityMismatchCounts = new Map();
  const afterFirst = recordSettingsIdentityMismatch(counts, "SMC Long-Dip Alerts");
  assert.equal(afterFirst, 1);
  assert.equal(shouldEscalateSettingsOpenPath(afterFirst), false);
});

test("der zweite Mismatch fuer dasselbe Ziel eskaliert", () => {
  const counts: SettingsIdentityMismatchCounts = new Map();
  recordSettingsIdentityMismatch(counts, "SMC Long-Dip Alerts");
  const afterSecond = recordSettingsIdentityMismatch(counts, "SMC Long-Dip Alerts");
  assert.equal(afterSecond, 2);
  assert.equal(shouldEscalateSettingsOpenPath(afterSecond), true);
  assert.equal(
    afterSecond,
    SETTINGS_IDENTITY_MISMATCH_ESCALATION_THRESHOLD,
    "die Schwelle ist die gemessene aus Lauf 32803019213",
  );
});

test("die Zaehlung ist je Ziel getrennt -- ein fremdes Skript eskaliert nicht mit", () => {
  // Review-Probe (Fix-Runde 1, "elfte Instanz"): eine reine Abwesenheits-
  // Behauptung (count(fremd)===0) bleibt gruen, selbst wenn die Trennung nach
  // Ziel komplett entfaellt und alle Mismatches unter einem globalen
  // Schluessel ("*") landen -- dann waere count(fremd) IMMER 0, weil es gar
  // kein "fremd" mehr gibt. Behauptet deshalb zusaetzlich ANWESENHEIT fuer
  // BEIDE Ziele: Alerts traegt exakt seine zwei Mismatches, Setup Check
  // seinen einen, unabhaengig voneinander.
  const counts: SettingsIdentityMismatchCounts = new Map();
  recordSettingsIdentityMismatch(counts, "SMC Long-Dip Alerts");
  recordSettingsIdentityMismatch(counts, "SMC Long-Dip Alerts");
  recordSettingsIdentityMismatch(counts, "SMC Setup Check");

  assert.equal(settingsIdentityMismatchCount(counts, "SMC Long-Dip Alerts"), 2);
  assert.equal(settingsIdentityMismatchCount(counts, "SMC Setup Check"), 1);
  assert.equal(shouldEscalateSettingsOpenPath(settingsIdentityMismatchCount(counts, "SMC Setup Check")), false);
});

test("resetSettingsIdentityMismatchCount macht die Zaehlung fuer einen neuen openSettingsForScript-Aufruf leer", () => {
  // "je openSettingsForScript-Aufruf" (Auftragstext): ein Rest aus einem
  // FRUEHEREN Aufruf fuer dasselbe Ziel darf einen neuen Aufruf nicht sofort
  // eskalieren lassen, bevor der ueberhaupt einen Mismatch gesehen hat.
  const counts: SettingsIdentityMismatchCounts = new Map();
  recordSettingsIdentityMismatch(counts, "SMC Long-Dip Alerts");
  recordSettingsIdentityMismatch(counts, "SMC Long-Dip Alerts");
  assert.equal(shouldEscalateSettingsOpenPath(settingsIdentityMismatchCount(counts, "SMC Long-Dip Alerts")), true);

  resetSettingsIdentityMismatchCount(counts, "SMC Long-Dip Alerts");
  assert.equal(settingsIdentityMismatchCount(counts, "SMC Long-Dip Alerts"), 0);
  assert.equal(shouldEscalateSettingsOpenPath(settingsIdentityMismatchCount(counts, "SMC Long-Dip Alerts")), false);
});

// Ledger klasse-h, offene Messfrage (Lauf 32803019213): das dblclick-start-
// Trace-Detail bekommt Boxmasse und Klickpunkt-Offset der tatsaechlich
// geklickten Box, damit der naechste natuerliche Fehlschlag entscheidet, ob
// ein mehrzeiliger Wrapper die Geometrie verschiebt (~40px+ Boxhoehe) oder TV
// die Zeile intern falsch zuordnet (~20px Boxhoehe). Reine Formatierung, ohne
// Browser beweisbar -- kein Verhaltenseingriff.

test("formatLegendDblclickBoxDetail nennt Boxmasse und den Klickpunkt-Offset zur Box", () => {
  const box = { x: 100, y: 200, width: 138, height: 18 };
  const point = { x: 134, y: 209 };
  assert.equal(formatLegendDblclickBoxDetail(box, point), "138x18@34,9");
});

test("formatLegendDblclickBoxDetail unterscheidet Einzelzeile (~20px) von mehrzeiligem Wrapper (~40px+)", () => {
  const singleLineRow = { x: 0, y: 0, width: 140, height: 20 };
  const wrappedTwoLineRow = { x: 0, y: 0, width: 140, height: 42 };
  const point = { x: 35, y: 10 };
  assert.equal(formatLegendDblclickBoxDetail(singleLineRow, point), "140x20@35,10");
  assert.equal(formatLegendDblclickBoxDetail(wrappedTwoLineRow, point), "140x42@35,10");
});

test("formatLegendDblclickBoxDetail rundet auf ganze Pixel", () => {
  const box = { x: 10.4, y: 20.6, width: 138.2, height: 17.7 };
  const point = { x: 44.9, y: 29.1 };
  assert.equal(formatLegendDblclickBoxDetail(box, point), "138x18@35,9");
});

// Review Fix-Runde 1, I3: die vier Verdrahtungs-Zusicherungen, die die reinen
// Map-/Formatierungs-Tests oben NICHT sehen -- ob openSettingsForScript und
// verifyOpenedSettingsDialogIdentity tatsaechlich in die neue Zaehlung
// einhaengen, ob der Eskalations-Dispatch (mitsamt I5-Fallback) existiert und
// ob dblclick-start das Boxdetail an BEIDEN Stellen traegt. Muster aus
// tv_open_script_identity.test.ts: Quelltext lesen, nicht ausfuehren.

test("openSettingsForScript setzt die Mismatch-Zaehlung fuer jeden Aufruf zurueck (I3)", () => {
  const body = functionBody(tvSharedSource(), "export async function openSettingsForScript(");
  assert.match(
    body,
    /resetSettingsIdentityMismatchCount\(/,
    "openSettingsForScript muss die Zaehlung je Aufruf zuruecksetzen -- sonst eskaliert ein Rest "
    + "aus einem frueheren Aufruf fuer dasselbe Ziel, bevor dieser Aufruf ueberhaupt einen "
    + "Mismatch gesehen hat",
  );
});

test("verifyOpenedSettingsDialogIdentity zaehlt jeden Mismatch mit (I3)", () => {
  const body = functionBody(tvSharedSource(), "async function verifyOpenedSettingsDialogIdentity(");
  const calls = body.match(/recordSettingsIdentityMismatch\(/g) ?? [];
  assert.equal(
    calls.length,
    2,
    "beide Mismatch-Zweige (der implicit-surface-Rueckgabezweig UND der werfende Zweig) "
    + "muessen recordSettingsIdentityMismatch aufrufen, sonst zaehlt die Eskalation an einer "
    + "der beiden Erkennungslagen nicht mit",
  );
});

test("openSettingsForScript eskaliert auf den Knopf-Pfad und faellt bei dessen Fehlschlag auf die Leiter zurueck (I3/I5)", () => {
  const body = functionBody(tvSharedSource(), "export async function openSettingsForScript(");
  assert.match(
    body,
    /\(await openSettingsForScriptViaLegendButton\(page, scriptName\)\)\s*\|\|\s*\(await openSettingsForScriptOnce\(page, scriptName\)\)/,
    "der Eskalationszweig muss openSettingsForScriptViaLegendButton aufrufen UND per `||` auf "
    + "openSettingsForScriptOnce durchfallen (I5) -- sonst verliert ein Ziel, dessen Zeile der "
    + "Knopf-Pfad nicht findet, seinen zweiten Rettungsversuch ersatzlos",
  );
});

test("tryOpenScriptSettingsByDoubleClick traegt das Boxdetail an BEIDEN dblclick-start-Stellen (I3/I4)", () => {
  const body = functionBody(tvSharedSource(), "async function tryOpenScriptSettingsByDoubleClick(");
  const calls = body.match(/formatLegendDblclickBoxDetail\(/g) ?? [];
  assert.equal(
    calls.length,
    2,
    "sowohl der normale dblclick-start als auch der hit-target-remeasured-Retry nach einem "
    + "hit-target-miss muessen formatLegendDblclickBoxDetail tragen -- ausgerechnet der "
    + "Remeasure-Fall ist der, in dem eine verschobene Wrapper-Geometrie am ehesten schuld waere",
  );
});
