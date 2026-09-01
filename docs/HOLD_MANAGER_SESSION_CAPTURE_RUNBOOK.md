# Hold-Manager-Shadow: Session erfassen — Schritt für Schritt

**Für wen:** den Operator, täglich nach US-Börsenschluss.
**Dauer:** 5–10 Minuten an einem ruhigen Tag.
**Warum es diese Datei gibt:** die Feldnamen des Protokolls (`expectedServerAlerts`,
`unclassifiedTransitionDifferenceCount`, …) sagen nicht, *wo* man hinschaut. Bis zum
2026-09-01 gab es dafür keine Anleitung, und die Erfassung ist genau daran gescheitert.

---

## Uhrzeiten (die häufigste Verwechslung)

| | ET (Börse) | UTC | Berlin |
|---|---|---|---|
| Eröffnung | 09:30 | **13:30Z** | **15:30** |
| Schluss | 16:00 | **20:00Z** | **22:00** |

Im Sommer ist ET = UTC−4 und Berlin = UTC+2. **„15:30" ist Berliner Zeit, nicht Z.**
Wer rechnet, holt die ET-Zeit aus der Uhr (`TZ=America/New_York date`), nicht aus einer Notiz.

---

## Was du gar nicht machen musst

Drei Dinge holt die Maschine selbst — nicht abtippen, nicht schätzen:

| Feld | Woher |
|---|---|
| `deliveredServerAlerts` | Empfänger-Ledger, per `reconcile`-Skript |
| `bindingStatus` | CI-Artefakt `tradingview-consumer-bindings` (`SMC Hold Manager: ok`) |
| `runtimeErrorCount` | dasselbe Artefakt (`runtimeErrors`) |

**Falle beim Artefakt:** nur Snapshots mit `checkedConsumers > 0` sind Evidenz. Ein
Snapshot mit `checkedConsumers: 0, mismatches: 0` liest sich wie „grün" und ist die
*leere Beobachtung* — er sagt nichts.

---

## Dein Teil: neun Felder, drei Handgriffe

Alles passiert auf **einem** Chart: Layout **„SMC Hold R2.4 Validation"**, Symbol
**BKNG**, Zeitrahmen **5m**.

### Handgriff 1 — Alarme zählen (liefert `expectedServerAlerts`)

1. Chart öffnen, rechte Seitenleiste, **Glocken-Symbol** („Alerts"/„Alarme").
2. Dort gibt es zwei Ansichten: die **Liste** der angelegten Alarme und das
   **Protokoll** der ausgelösten (in der TV-Oberfläche „Log" bzw. „Protokoll").
   Du brauchst das **Protokoll**.
3. Auf heute filtern und die Einträge des Alarms zählen.

**Wichtig, sonst suchst du sechs Alarme und findest einen:** seit dem Cutover am
2026-08-16 trägt **ein einziger** Alarm alle sechs Kanäle. Welcher Kanal gefeuert hat,
steht im **Nachrichtentext** des Protokolleintrags, im Feld `"channel"`:

```
{"schemaVersion":1,"requirementId":"R2-SHADOW-CUTOVER","channel":"HM_ENTRY", …}
```

Zähle je Kanal, wie oft er im Protokoll auftaucht:

| Kanal | Bedeutung |
|---|---|
| `HM_ENTRY` | Position übernommen |
| `HM_T1` / `HM_T2` | Teilziel 1 / 2 erreicht |
| `HM_STOP` | Stop ausgelöst |
| `HM_TIMESTOP` | Zeit-Stop ausgelöst |
| `HM_EXIT_ANY` | irgendein Ausstieg (Sammelkanal) |

**Ein ruhiger Tag ergibt überall 0 — das ist ein gültiges Ergebnis, kein Fehler.**

> **Nicht kopieren:** der Nachrichtentext enthält am Ende einen `authToken`. Zähle die
> Kanäle, gib den Text nicht weiter und schicke ihn nicht in einen Chat.

### Handgriff 2 — Ausstiegs-Modus prüfen (liefert `activeActionableExitModes`)

Der Vertrag verlangt **genau einen** handelnden Ausstiegs-Modus: `["hold_manager"]`.

1. In der Alarm-**Liste** (nicht Protokoll) nachsehen, dass der Hold-Manager-Alarm auf
   `BKNG`, `5m` und **Active** steht.
2. Sicherstellen, dass **kein** konkurrierender Ausstiegs-Alarm aus `SMC Exit Signal`
   oder `SMC Long-Dip Strategy` aktiv ist.

Trifft beides zu → `["hold_manager"]`. Sonst die tatsächlich aktiven Modi eintragen.

### Handgriff 3 — Vergleichen (liefert die restlichen sechs Felder)

Auf demselben Chart liegen `SMC Exit Signal` und `SMC Long-Dip Strategy`. Vergleiche
ihre Ausstiege mit denen des Hold Managers.

| Feld | Frage | Vertrag erwartet |
|---|---|---|
| `completeUsMarketSession` | Session von 15:30 bis 22:00 (Berlin) durchgehend beobachtet? | `true` |
| `exclusionReason` | nur falls oben `false`: warum | `null` |
| `exitSignalCompared` | mit `SMC Exit Signal` verglichen? | `true` |
| `strategyCompared` | mit `SMC Long-Dip Strategy` verglichen? | `true` |
| `falseExitAlertCount` | Alarme ohne zugehörigen Ausstieg auf dem Chart | `0` |
| `duplicateActionableExitAlertCount` | derselbe Ausstieg doppelt gemeldet | `0` |
| `unclassifiedTransitionDifferenceCount` | Unterschied, der in keine der beiden Klassen passt | `0` |

**An einem Tag ohne einen einzigen Alarm sind die drei Zähler zwangsläufig 0** — es gab
nichts, was falsch, doppelt oder unklar sein könnte. Die beiden Vergleiche musst du
trotzdem tatsächlich angeschaut haben, sonst ist `true` eine Falschangabe.

---

## Was du dann sagst

Ein Satz reicht, z. B.:

> Session beobachtet, keine Alarme, Exit Signal und Strategy verglichen, nichts Auffälliges.

Daraus wird:

```json
"completeUsMarketSession": true,
"exclusionReason": null,
"activeActionableExitModes": ["hold_manager"],
"exitSignalCompared": true,
"strategyCompared": true,
"falseExitAlertCount": 0,
"duplicateActionableExitAlertCount": 0,
"unclassifiedTransitionDifferenceCount": 0,
"expectedServerAlerts": {"HM_ENTRY":0,"HM_T1":0,"HM_T2":0,"HM_STOP":0,"HM_TIMESTOP":0,"HM_EXIT_ANY":0}
```

---

## Wenn du einen Tag NICHT beobachtet hast

Dann ist der Tag ein **Loch**, und das ist die ehrliche Buchung. Trage **keine** Zeile
nach — auch keine `excluded`-Zeile: der Evaluator verlangt auch in ausgeschlossenen
Zeilen die vollen TradingView-Attestierungen, und eine Zeile für einen unbeobachteten
Tag wäre eine Falschangabe (Lehre vom 2026-08-17).

Ein Loch kostet einen Kandidatentag. Reichen die verbleibenden nicht mehr für fünf
vollständige Sessions, wird `dueBy` in `docs/commercial/HOLD_MANAGER_COMMERCIAL_DECISION.json`
**datiert** verschoben — mit Eintrag in `dueByHistory`, nie stillschweigend.

---

## Der Aggregat-Haken, der einen ruhigen Tag teuer macht

Fünf saubere Sessions **reichen nicht**, wenn in keiner davon etwas passiert ist. Das
Protokoll verlangt zusätzlich über alle Sessions zusammen:

- mindestens **eine** `HM_ENTRY`-Kante,
- mindestens **eine** `HM_EXIT_ANY`-Kante,
- mindestens **einen** terminalen Ausstieg.

Fünf Nulltage erfüllen die Sessionzahl und den Daten-Trigger trotzdem nicht. Wer das
früh sieht, kann rechtzeitig verlängern statt am Stichtag festzustellen, dass es nicht
mehr geht.

---

## Was ich (die Automation) danach mache

`reconcile` füllt die zugestellte Seite aus dem Empfänger, der Evaluator rechnet, der
gepinnte Zustands-Test zieht im selben PR mit. Du musst nur die neun Werte nennen.

## Grenze dieser Anleitung

Die Schritte 1–3 sind aus dem Repo abgeleitet: der Cutover-Record belegt den **einen**
Alarm mit allen sechs Kanälen, der Pine-Quelltext den `"channel"`-Schlüssel im
Nachrichtentext, `tv_readback_hold_manager_alerts.ts` die Alarmliste mit Symbol und
Status. **Nicht aus dem Repo belegbar ist, wie die Protokoll-Ansicht in der aktuellen
TradingView-Oberfläche genau heißt und wo sie sitzt** — Beschriftungen ändern sich mit
TV-Releases. Findest du sie an anderer Stelle, korrigiere diese Datei; sie ist der Ort
dafür.
