# TV-Layout-Zustands-Wächter

**Datum:** 2026-08-22
**Status:** Entwurf, vom Operator abschnittsweise freigegeben. Nichts davon ist gebaut.

## Problem

Das gehandelte Primär-Chart verliert regelmäßig seine BUS-Bindungen, und nichts stellt sie
zuverlässig wieder her.

Gemessen am 2026-08-22:

- Der Producer-Refresh entfernt Instanzen und trägt sie neu auf. Alle abhängigen Eingänge
  fallen dabei auf den Default `Close`, und **TradingView persistiert das sofort** — anders
  als Input-Bindungen, die erst ein Layout-Save dauerhaft macht
  (Lauf 758: die um 05:37–05:47 neu aufgetragenen Instanzen überlebten Layoutwechsel und
  Sitzungsende, die 98 Reparaturen desselben Laufs nicht).
- Die Konsumenten binden an die **Ausgänge des Producers** (`SMC Long-Dip Suite: BUS Armed`).
  Ein Producer-Refresh vergibt eine neue Instanz-Id und reißt deshalb *alle* Konsumenten mit —
  eine Zerstörung mit Fächer.
- Die Reparatur ist heute Geisel des Quellen-Deploys: `resolveExecutionPlan` kennt nur
  `verify-only` (nichts mutiert) und `write`, und dort ist `saveSources: true` **fest
  verdrahtet**. Jeder Lauf, der Bindungen repariert, speichert zwangsläufig zwölf Quellen —
  und gerät damit in das Manifest-Fenster und die Library-Drift-Verweigerung.
- Zustand der Kette: von den letzten 30 Save-Läufen waren 16 abgebrochen, 5 rot, 9 wartend,
  **null grün**; der letzte grüne Save stammt vom 21.8. 06:16Z.
- Die Refresh-Crons laufen `1-5`, also Mo–Fr. Die volle Last liegt damit genau auf Handelstagen.

Die Kette **beobachtet** den Schaden bereits: Die geplanten Verify-Läufe (05:17 und 21:17 UTC)
lesen den echten Layout-Zustand und laden ihn als Artefakt hoch. Der Drift-Alarm feuert. Aber
**niemand handelt darauf**. Es fehlt nicht die Messung, sondern die Kante von der Messung zur
Handlung — die Dead-Dataflow-Klasse aus dem Verdrahtungs-Sweep.

## Erfolgskriterium

**Das gehandelte Layout trägt jederzeit korrekte BUS-Bindungen.** Operator-Entscheidung
2026-08-22: Das Kriterium ist der ZUSTAND, nicht der Durchsatz. Ob einzelne Save-Läufe rot
sind, ist zweitrangig; grüne Läufe sind Mittel, nicht Zweck.

**Nicht verhandelbar:** Jeder Library-Publish muss auf dem gehandelten Chart landen — eine
veraltete Instanz ist ein echtes Risiko (Operator-Entscheidung 2026-08-22). Die Refresh-Kadenz
steht damit fest; die Lösung darf sie nicht senken.

## Architektur

### Regelkreis

Der Wächter ist **kein neuer Beobachter**, sondern der fehlende Konsument einer vorhandenen
Beobachtung. Drei Teile:

**Auslöser.** Hängt an der Beendigung eines Verify-Laufs, liest dessen Bindings-Snapshot und
entscheidet an einer Zahl: Zeigt ein Layout Mismatches? Kein neuer Browser, keine neue
Laufzeit — ein `jq` über ein Artefakt, das ohnehin entsteht.

**Neuer Ausführungsmodus `repair-only`.** `repairBindings: true`, `saveLayout: true`,
`saveSources: false`, `refreshProducer: false`. Umgeht das Manifest-Fenster vollständig: Er
deployt nichts, er stellt her, was ein Refresh zerlegt hat. Wie die bestehenden Modi
eingefroren (`Object.freeze`).

**Schleifenschutz.** Ein Reparaturlauf darf sich nicht selbst erneut auslösen. Konkret: Der
Auslöser reagiert **ausschließlich** auf Snapshots mit `executionMode == "verify-only"`. Der
Snapshot eines Reparaturlaufs trägt `repair-only` und wird damit ignoriert — die Unterscheidung
liegt im Artefakt, nicht in einer Herkunfts-Heuristik.

### Serialisierung und Sicherheit

- **Bestehende Session-Gruppe.** Der Reparaturlauf ist derselbe Workflow mit anderem Modus und
  erbt die Concurrency-Gruppe („eine automatisierte Browser-Sitzung zur Zeit"). Er kann nie
  neben einem Save laufen; Warten oder Verdrängtwerden ist unschädlich, weil er **idempotent**
  ist — ist der Zustand korrekt, repariert er nichts.
- **Operator-Fenster.** `TV_OPERATOR_ACTIVE` gilt für ihn wie für jeden mutierenden Lauf. Die
  Vor-Mutations-Beobachtung läuft unverändert mit, damit eine bewusste Operator-Änderung nicht
  als Drift überschrieben wird.
- **Nur betroffene Layouts.** Repariert werden genau die Layouts, deren Snapshot Mismatches
  zeigt; saubere bleiben unberührt. **Kein Sonderfall für das Hold-Manager-Layout**
  (`twh98JLB`) — Operator-Entscheidung 2026-08-22: Es bleibt im Wirkungsbereich, und es gilt
  allein die allgemeine Regel. Dass es faktisch unberührt bleibt, solange es sauber ist, folgt
  aus dem Zustand, nicht aus einer Ausnahme.
- **Keine Stapelung.** Ist bereits ein Reparaturlauf angefordert oder wartend, wird kein
  zweiter ausgelöst (dieselbe Supersessions-Logik wie für Saves seit #4998).

### Fehlerverhalten und Sichtbarkeit

- **Versuchsdeckel: 3 Reparaturläufe je ET-Handelstag.** Danach hört der Wächter auf zu
  dispatchen und **sagt es**. Die Zahl ist bewusst klein: Drei gescheiterte Versuche an
  denselben Zielen sind kein Flake, sondern ein Befund — und ein vierter Lauf kostet einen
  Warteplatz in der Session-Gruppe, den ein echter Save braucht. Der Zähler läuft über den
  ET-Handelstag, nicht über 24 h, damit er zur Kadenz der Refreshes passt. Ein Regelkreis, der
  aufgibt, muss lauter sein als einer, der arbeitet.
- **Drei Alarmzustände statt einem.** *Drift erkannt, Reparatur unterwegs* (kein
  Handlungsbedarf) · *Reparatur gelungen* (der Alarm löscht sich selbst, was er heute nicht
  tut) · *Reparatur mehrfach gescheitert* (Operator nötig; der Alarm nennt Layout und
  blockierendes Skript).
- **Beweise geerbt.** Ein gescheiterter Reparaturlauf hinterlässt, was seit #5020 entsteht:
  Screenshot, Legendengeometrie, Klickpunkt-Treffer.

### Bindende Mechanik-Konsequenz

**Ein per `GITHUB_TOKEN` dispatchter Lauf erzeugt keinen Folge-Verify** (GitHubs
Rekursionsschutz, 13/13 gemessen am 22.8.). Zweierlei folgt daraus: Der Schleifenschutz ist von
der Plattform her halb geschenkt — und der Reparaturlauf wird **nicht** automatisch
nachverifiziert. Sein Erfolg muss aus seinem **eigenen Artefakt** gelesen werden, nicht aus
einem Folgelauf, den es nie geben wird. Genau hier scheitert ein naiver Regelkreis still.

## Testen

Die Browser-Hälfte ist lokal nicht testbar. Der Schnitt legt deshalb alle **Entscheidungen**
außerhalb des Browsers.

- **Drei reine Entscheidungen, je ein Unit-Test plus Mutationsprobe:** (1) Aus einem Snapshot
  ergibt sich, ob und welche Layouts repariert werden. (2) Darf dieser Lauf auslösen
  (Schleifenschutz)? (3) Ist das Tageskontingent aufgebraucht?
- **`repair-only` bekommt die Strenge von `verify-only`:** ein Test, der beweist, dass er genau
  zwei Dinge darf und Quellen-Save wie Producer-Refresh verweigert, auch wenn die
  Umgebungsvariablen gesetzt sind.
- **Gegen Vakuität:** ein synthetischer Snapshot mit Mismatches durch den gesamten
  Entscheidungspfad — der Beweis, dass der Wächter feuern *kann*, nicht nur, dass er schweigt.
- **Sonden-Eintrag (verbindliche Anforderung, nicht Prosa):** Der Wächter erhält einen eigenen
  Urteilsblock in `~/.claude/scripts/tv_gate_probe_check.sh` nach dem Muster von
  `#5013`/`#5018`/`#5020` — inhaltliche Versionsprobe über ein Feld, das es erst mit dieser
  Änderung gibt, damit ein Lauf mit älterem Code ehrlich „kann nicht bezeugen" meldet statt
  fälschlich PASS. Ohne diesen Block gilt die Live-Wirksamkeit als unbewiesen.

## Nicht im Umfang

- **Senkung der Refresh-Kadenz** — vom Operator ausgeschlossen (siehe Erfolgskriterium).
- **Vermeidung der Zerstörung** (Producer neu auftragen, bevor die alte Instanz verschwindet;
  oder Konsumenten an einen stabilen Bezug binden). Ob TradingView das hergibt, ist
  **ungemessen**. Wäre ein eigener Spike; ein Erfolg dort machte diesen Entwurf überflüssig.
- **Der ungegatete Abend-Zweig** von `run-c13-tws-reminder.sh` (eigener Befund vom 22.8.,
  bewusst offen gelassen).

## Ungesicherte Annahmen

- Dass ein `repair-only`-Lauf im echten Browser gelingt, ist **nicht bewiesen** — nur, dass die
  Entscheidung, ihn zu starten, korrekt fällt. Der Sonden-Eintrag oben ist der Mechanismus, der
  das nachmisst.
- Ob die Klasse-H-Fehler (Settings-Dialog geht nicht auf) nach #5018 verschwunden sind, ist zum
  Zeitpunkt dieses Entwurfs **offen**: Das Urteil der Sonde zu #5018 war zuletzt „nicht gültig",
  weil der beurteilte Lauf vor dem Merge startete. Bleibt Klasse H bestehen, scheitert auch der
  Reparaturlauf an denselben Zielen — dann trägt der Versuchsdeckel, nicht die Reparatur.
