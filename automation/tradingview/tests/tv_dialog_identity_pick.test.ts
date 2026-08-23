import assert from "node:assert/strict";
import { test } from "node:test";

import { pickDialogForScript } from "../lib/tv_shared.js";

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
