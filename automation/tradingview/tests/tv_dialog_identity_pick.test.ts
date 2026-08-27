import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import {
  classifyDialogAtFailure,
  formatLegendDblclickBoxDetail,
  formatLegendRowScanDetail,
  isSingleLegendRowActionSet,
  pickDialogForScript,
  recordSettingsIdentityMismatch,
  resetSettingsIdentityMismatchCount,
  SETTINGS_IDENTITY_MISMATCH_ESCALATION_THRESHOLD,
  SETTINGS_IDENTITY_RE_READ_WAITS_MS,
  settingsIdentityMismatchCount,
  settleDialogPick,
  shouldEscalateSettingsOpenPath,
  type DialogPick,
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

// Ledger klasse-h, STAND 2026-08-26 (Lauf 32886027492): dialogAtFailureVerdict
// = target-visible — im Moment der Fehlschlag-Deklaration stand der RICHTIGE
// Dialog offen, Titel korrekt, genau einer sichtbar. Zusammen mit dem
// 24.8.-Befund ("der gelesene Dialog ist immer der des VORHERIGEN Ziels")
// zeigt das auf ein wiederverwendetes Settings-Modal, dessen TITEL dem Inhalt
// nachzieht: die einmalige Sofort-Lesung sieht den alten Titel, deklariert
// Mismatch — und closeModal schliesst den gerade korrekt geoeffneten Dialog.
// Ein Mismatch gilt deshalb erst, wenn er eine kurze Nachlese ueberlebt.
// Reine Schleifenlogik, ohne Browser beweisbar.

const pickOf = (verdict: DialogPick["verdict"], title: string | null): DialogPick => ({
  verdict,
  dialog: title === null ? null : { title },
  visibleCount: title === null ? 0 : 1,
});

function fakeReader(sequence: DialogPick[]): { read: () => Promise<DialogPick>; reads: () => number } {
  let n = 0;
  return {
    read: async () => {
      const pick = sequence[Math.min(n, sequence.length - 1)];
      n += 1;
      return pick;
    },
    reads: () => n,
  };
}

test("settleDialogPick: ein Mismatch, der sich in der Nachlese als Treffer entpuppt, ist ein Treffer", async () => {
  const reader = fakeReader([
    pickOf("mismatch", "SMC Setup Check"),
    pickOf("match", "SMC Long-Dip Alerts"),
  ]);
  const sleeps: number[] = [];
  const settled = await settleDialogPick(reader.read, SETTINGS_IDENTITY_RE_READ_WAITS_MS, async (ms) => {
    sleeps.push(ms);
  });
  assert.equal(settled.pick.verdict, "match");
  assert.equal(settled.pick.dialog?.title, "SMC Long-Dip Alerts");
  assert.equal(settled.reads, 2);
  assert.deepEqual(sleeps, [SETTINGS_IDENTITY_RE_READ_WAITS_MS[0]], "genau eine Wartezeit vor der zweiten Lesung");
});

test("settleDialogPick: ein Mismatch, der alle Nachlesen uebersteht, bleibt ein Mismatch", async () => {
  const reader = fakeReader([pickOf("mismatch", "SMC Setup Check")]);
  const settled = await settleDialogPick(reader.read, SETTINGS_IDENTITY_RE_READ_WAITS_MS, async () => {});
  assert.equal(settled.pick.verdict, "mismatch");
  assert.equal(
    settled.reads,
    SETTINGS_IDENTITY_RE_READ_WAITS_MS.length + 1,
    "erst nach ALLEN Nachlesen darf der Mismatch deklariert werden",
  );
});

test("settleDialogPick: ein sofortiger Treffer wartet keine Millisekunde", async () => {
  const reader = fakeReader([pickOf("match", "SMC Long-Dip Alerts")]);
  const sleeps: number[] = [];
  const settled = await settleDialogPick(reader.read, SETTINGS_IDENTITY_RE_READ_WAITS_MS, async (ms) => {
    sleeps.push(ms);
  });
  assert.equal(settled.pick.verdict, "match");
  assert.equal(settled.reads, 1);
  assert.deepEqual(sleeps, [], "der Erfolgspfad darf nicht langsamer werden");
});

test("settleDialogPick: verschwindet der Dialog in der Nachlese, endet sie als 'untitled'", async () => {
  // Review-Fund 27.8. (Follow-up zu #5098): genau die Sequenz, in der die
  // Surface-Messung des Aufrufers veraltet — der Aufrufer muss sie frisch
  // bestaetigen, bevor er implicit-surface-Erfolg meldet.
  const reader = fakeReader([pickOf("mismatch", "SMC Setup Check"), pickOf("untitled", null)]);
  const settled = await settleDialogPick(reader.read, SETTINGS_IDENTITY_RE_READ_WAITS_MS, async () => {});
  assert.equal(settled.pick.verdict, "untitled");
  assert.equal(settled.reads, 2, "nach untitled darf keine weitere Nachlese folgen");
});

test("ein 'untitled' NACH der Nachlese gilt nur mit frisch bestaetigter Surface (Verdrahtung)", () => {
  const body = functionBody(tvSharedSource(), "async function verifyOpenedSettingsDialogIdentity(");
  assert.match(
    body,
    /-identity-surface-gone-after-settle/,
    "ein untitled aus der Nachlese traegt eine bis zu 1,2 s alte Surface-Messung; ohne "
    + "frische Bestaetigung ist das kein Erfolg — der Zweig braucht seinen eigenen, "
    + "benannten Ausgang (return false, KEIN Mismatch-Zaehler-Tick)",
  );
});

test("settleDialogPick: 'untitled' ist KEIN Mismatch und wird nicht nachgelesen", async () => {
  // untitled hat eigene Zweige (implicit-surface bzw. missing-title-throw) —
  // eine Nachlese wuerde beide Pfade verlangsamen, ohne etwas zu entscheiden.
  const reader = fakeReader([pickOf("untitled", null)]);
  const settled = await settleDialogPick(reader.read, SETTINGS_IDENTITY_RE_READ_WAITS_MS, async () => {
    assert.fail("untitled darf keine Wartezeit ausloesen");
  });
  assert.equal(settled.pick.verdict, "untitled");
  assert.equal(settled.reads, 1);
});

test("die Nachlese-Staffel ist kurz und endlich — sie lebt im 60-s-Budget des Steps", () => {
  const total = SETTINGS_IDENTITY_RE_READ_WAITS_MS.reduce((a, b) => a + b, 0);
  assert.ok(SETTINGS_IDENTITY_RE_READ_WAITS_MS.length >= 1, "mindestens eine Nachlese, sonst ist der Fix leer");
  assert.ok(total <= 2_000, `Nachlese-Staffel ${total}ms — mehr frisst das Step-Budget der Leiter auf`);
});

test("verifyOpenedSettingsDialogIdentity liest ueber settleDialogPick, in BEIDEN Erkennungslagen (Verdrahtung)", () => {
  const body = functionBody(tvSharedSource(), "async function verifyOpenedSettingsDialogIdentity(");
  const calls = body.match(/settleDialogPick\(/g) ?? [];
  assert.equal(
    calls.length,
    2,
    "beide Zweige (Inputs-Surface sichtbar UND nicht sichtbar) muessen die Nachlese fahren — "
    + "sonst deklariert eine der beiden Lagen weiter nach einer einzigen Sofort-Lesung "
    + "Mismatch und closeModal schliesst den gerade korrekt geoeffneten Dialog",
  );
  assert.match(
    body,
    /-identity-title-settled/,
    "ein Treffer erst in der Nachlese muss eine eigene Spur tragen — sie ist die inhaltliche "
    + "Versionsprobe dieses Fixes am echten Lauf",
  );
});

// Eskalations-Befund desselben Laufs: escalation-rows SMC Long-Dip Alerts:0 —
// die Zeilenauflösung fand im Eskalationsmoment NULL Zeilen, und die Spur
// nennt nur das Endergebnis. findLegendRowWrappersByVisibleText hat sechs
// stille Skip-Gruende (unsichtbar, excluded, kein Wrapper, Text leer/>300,
// Action-Count != 1, Duplikat); welcher zutraf, ist aus dem Log nicht
// rekonstruierbar. Der Scan-Zaehler benennt beim naechsten Leer-Ergebnis den
// Grund. Reine Formatierung, kein Verhaltenseingriff.

test("formatLegendRowScanDetail nennt jeden stillen Skip-Grund mit seiner Zahl", () => {
  const detail = formatLegendRowScanDetail({
    matches: 3,
    invisible: 1,
    excluded: 1,
    noWrapper: 1,
    badText: 0,
    actionCount: 0,
    dup: 0,
  });
  assert.equal(detail, "matches=3:invisible=1:excluded=1:no-wrapper=1:text=0:actions=0:dup=0");
});

// Lauf 32957051467 (27.8., erste Auswertung der #5098-Skip-Zaehler): beide
// Alerts-Scans starben mit actions=1 — der einzige sichtbare, nicht
// ausgeschlossene Kandidat fiel am alten `count !== 1` ueber BEIDE
// Knopfarten, weil die Hover-Leiste der Zeile Settings- UND More-Knopf
// traegt (Summe 2). Der Container-Diskriminator ist die Zahl der
// SETTINGS-Knoepfe, nicht die Gesamtsumme.

test("die gemessene Zielzeile (Settings+More gleichzeitig) ist eine enge Zeile", () => {
  assert.equal(isSingleLegendRowActionSet(1, 1), true, "genau der Fall, der die Eskalation blockierte");
});

test("eine Zeile mit nur einem der beiden Knoepfe bleibt zugelassen", () => {
  assert.equal(isSingleLegendRowActionSet(1, 0), true);
  assert.equal(isSingleLegendRowActionSet(0, 1), true, "bisheriges Verhalten fuer More-only-Zeilen");
});

test("Pane-Container (mehrere Zeilen-Knopfsaetze) und knopflose Wrapper bleiben draussen", () => {
  assert.equal(isSingleLegendRowActionSet(2, 2), false, "2 Zeilen im Container");
  assert.equal(isSingleLegendRowActionSet(3, 3), false);
  assert.equal(isSingleLegendRowActionSet(2, 0), false);
  assert.equal(isSingleLegendRowActionSet(0, 2), false);
  assert.equal(isSingleLegendRowActionSet(0, 0), false, "ohne Knopf ist nichts klickbar");
});

test("der Zeilen-Scan filtert ueber das Praedikat, mit getrennten Zaehlungen (Verdrahtung)", () => {
  const body = functionBody(tvSharedSource(), "export async function findLegendRowWrappersByVisibleText(");
  assert.match(
    body,
    /isSingleLegendRowActionSet\(/,
    "der actions-Filter muss durch das Praedikat laufen — die alte Summenregel "
    + "`count !== 1` frass die Zielzeile mit Settings+More (Lauf 32957051467)",
  );
});

test("findLegendRowWrappersByVisibleText benennt ein Leer-Ergebnis mit den Scan-Zaehlern (Verdrahtung)", () => {
  const body = functionBody(tvSharedSource(), "export async function findLegendRowWrappersByVisibleText(");
  assert.match(
    body,
    /legend-text-wrapper-scan-empty/,
    "ein leeres Ergebnis muss seine Zaehler in die Spur schreiben — ein schweigender Zweig "
    + "sieht aus wie ein gesunder (escalation-rows:0 war genau das)",
  );
  assert.match(body, /formatLegendRowScanDetail\(/, "die Spur muss aus den echten Zaehlern formatiert sein");
});
