# Beweis-Ledger — SCHLAFEND ist nicht PASS

**Datum:** 2026-08-23
**Status:** Entwurf, vom Operator abschnittsweise freigegeben. Nichts davon ist gebaut.

## Problem

Änderungen, deren Wirkung die Testsuite prinzipiell nicht sehen kann — Browser-Automation,
Cron-Workflows, Eingriffe in externe Systeme — sind nach dem Merge **unbewiesen**. Der Beweis
kommt erst aus einem echten Lauf, und ob er je kommt, bemerkt heute niemand mechanisch.

Gemessen am 2026-08-22/23 an der TradingView-Kette:

- **Der Beweis lebt in einem persönlichen Skript.** `~/.claude/scripts/tv_gate_probe_check.sh`
  fällt die Urteile zu #5013, #5018, #5020 und dem Layout-Wächter. Es läuft nur, wenn ein
  Mensch `/morning-triage` aufruft. Sein eigener Kopf nennt das Löschkriterium „löschbar, sobald
  alle vier je einmal PASS gemeldet haben" — ein Kriterium, das ein nie feuernder Zweig
  strukturell nie erfüllt.
- **Ein Urteilszweig war einen Tag lang vakuös, ohne dass etwas anschlug.** Der `#5018`-Zweig
  suchte `hit-target-miss` in `bindings.failed[].error`. Über die Grundgesamtheit geprüft
  (2026-08-23): Die Zeichenkette hat repo-weit **genau eine** Emissionsstelle,
  `automation/tradingview/lib/tv_shared.ts:6175`, und die ruft `tracePageEvent` — das schreibt
  in einen In-Memory-Tracker und nach `console.error`, also ins CI-Log. Der Tracker
  (`pageLifecycleTrackers` / `pushLifecycleEvent`) wird außerhalb von `tv_shared.ts` nirgends
  referenziert und in keinen Report serialisiert. Der Zweig war **strukturell** unerreichbar,
  nicht zufällig ungefeuert — und hat trotzdem Urteile gedruckt.
- **Zwei Zustände sehen im Grünen gleich aus.** „Die Bedingung trat nicht ein" (SCHLAFEND) und
  „die Bedingung trat ein, der Zweig wurde aber nie erreicht" (STEHT AUS) sind verschiedene
  Aussagen. #5013 hat in einer Nacht beide durchlaufen, und niemand hätte den Übergang
  bemerkt: um 00:23Z stand es auf **STEHT AUS** (Lauf `32556181388`,
  `layoutSaveRequested=false` — der Lauf stirbt bei `openSettingsForScript`, bevor die
  Save-Entscheidung ansteht), um 05:49Z auf **PASS** (Lauf `32620808573`,
  `partiallyRepairedChartUrls: [vWgAWyfC]` **und** `savedChartUrls: [vWgAWyfC]`,
  `abandonedChartUrls: []`, 98 Bindungen repariert). Dreizehn Stunden lang war der Zustand
  von „schlafend, also wohl in Ordnung" nicht zu unterscheiden, und der Übergang wurde nur
  deshalb sichtbar, weil ein Mensch zufällig zur richtigen Zeit ein Skript aufrief.

- **Die Lauf-Conclusion ist als Urteilsquelle untauglich.** Ebenjener Lauf `32620808573` war
  `conclusion: failure` — weil `report.ok` an einem nicht leeren
  `partiallyRepairedChartUrls` hängt. Ein **roter Lauf, der exakt das Richtige tat.** Wer
  über die Conclusion urteilt, führt hier einen bestandenen Beweis als Fehlschlag. Deshalb
  urteilt dieses Ledger ausschließlich über Evidenz*inhalt*.
- **Die Prämisse, unter der #5013 als schlafend geführt wurde, ist überholt.** Sie lautete
  „#5018 entfernt die Bedingung, unter der #5013 feuern könnte". #5018 hat Klasse H nicht
  behoben (2026-08-23 live widerlegt: `hit-target-miss: 0`, `box-degenerate: 0`, Dialog geht
  trotzdem nicht auf). Die Bedingung besteht fort.

Es fehlt nicht die Messung. Es fehlt, dass „noch nicht bewiesen" einen Halter mit Frist hat und
dass ein Urteiler beweisen muss, überhaupt urteilsfähig zu sein.

## Erfolgskriterium

**Keine gemergte Änderung dieser Klasse steht unbemerkt ohne Beweis, und kein Urteil über sie
stammt von einem Zweig, der nicht feuern kann.**

Nicht verhandelbar: Der Merge-Pfad darf nicht an der GitHub-API hängen. `fast-gates` ist nach
ADR-0011 der einzige required Check; ein Netzaufruf dort macht ihn zur Geisel von API-Zustand
und Actions-Budget.

## Architektur

Zwei getrennte Hälften, nach dem Vorbild von `_DEPLOYMENT_IS_CONFIGURED`
(`docs/superpowers/plans/2026-08-04-guard-dormancy-and-probe-payload.md`): die **Deklaration**
liegt im Repo und wird offline bewacht, die **Netz-Messung** liegt in einem scheduled Workflow.

### Datenmodell

Eine TOML-Quelle nach dem Vorbild von `pin_registry.toml`: genau ein Loader, datierte
Begründungen im Klartext, Editier-Regeln im Kopf der Datei.

```toml
[[proof]]
kind          = "merge"                   # "merge" | "defect"
id            = "5013"
merged_at     = "2026-08-22T16:42:54Z"
merge_sha     = "7733f988c"
claim         = "Ein unerreichbares Ziel fuehrt zum Partial-Save statt zum Verwerfen"

witness         = "tv-save-consumer-source"
witness_job     = "save"
evidence_source = "artifact"              # "artifact" | "job_log"
artifact        = "tradingview-consumer-bindings"
version_probe   = "mutations.partiallyRepairedChartUrls"
judge           = "tv_partial_save"

state         = "OFFEN"
due_by        = "2026-08-29"
owner         = "operator"
```

Feldregeln:

- **`version_probe` ist Pflicht.** Es ist der einzige Griff, der ohne Zeitrechnung sagt „dieser
  Lauf trug den Code": das Feld existiert erst seit `merge_sha`. Wo es keins gibt, muss der
  Eintrag das benennen (`version_probe = "KEINE"` plus Begründung), statt still auf den
  schwächeren Job-Start auszuweichen. Für #5018 ist das der Fall.
- **`witness_job.started_at` entscheidet, nie `head_sha`.** `tv-save-consumer-source.yml` hat
  einen Fast-Forward-Schritt; ein Lauf misst mit dem main-Stand seines Job-Starts. Kronzeuge:
  Lauf `32544827322`, head_sha `775174db1` (ohne #5013 als Ancestor), Artefakt trägt
  `partiallyRepairedChartUrls`. Wer `head_sha` nimmt, verwirft gültige Zeugen.
- **`evidence_source`** trennt Artefakt von Job-Log. Ohne dieses Feld würde ein Fix, dessen
  Evidenz nur im Log steht, fälschlich als „nicht bezeugbar" geführt — derselbe Fehler in Grün,
  den der vakuöse #5018-Zweig in Rot war: die Frage an der falschen Quelle stellen.
- **`judge` benennt ein Modul, keinen Ausdruck.** Eine Ausdrucks-Minisprache im TOML wäre eine
  zweite Implementierung neben der ersten — was `scripts/check_r1_attested_sources.py` in
  seinem Docstring ausdrücklich ablehnt. Ein Modul kann außerdem ein Korpus haben.
- **`kind = "defect"`** ist die Eintragsart für einen offenen Defekt ohne Merge. `merge_sha`,
  `version_probe` und `judge` entfallen; `claim`, `owner`, `due_by` und `state = "UNGESICHERT"`
  bleiben Pflicht. Damit bekommt auch ein Befund einen Halter mit Frist, statt zu verdunsten.

**Gespeicherte Zustände:** `OFFEN` · `PASS` · `FAIL` · `SCHLAFEND` · `UNERREICHBAR` ·
`UNGESICHERT`.
**Vom Urteiler erzeugt, nie gespeichert:** `STEHT_AUS` · `KANN_NICHT_BEZEUGEN` · `PRUEFEN`.

Der tragende Trennstrich:

| | Bedingung trat ein? | Zweig erreicht? | Folge |
|---|---|---|---|
| `SCHLAFEND` | nein | — | Durchgangszustand, braucht einen Ausgang |
| `STEHT_AUS` | ja | nein | Befund, kein Warten |

### Aufnahme: die Klasse wird abgeleitet, nicht aufgezählt

```
Extern   = Workflows ohne pull_request-Trigger
Code     = { in Workflow-Text referenziert } \ { von einem Test importiert/ausgefuehrt }
KLASSE   = Extern  ∪  { Code, den mindestens ein externer Workflow aufruft }
```

Die Trigger-Ableitung trägt die Last: läuft ein Workflow auf `pull_request`, beweist der nächste
PR-Lauf die Änderung selbst. Ein Workflow, der nur auf `schedule`/`workflow_dispatch`/
`workflow_run` läuft, tut das nicht.

**Gemessen 2026-08-23 gegen `origin/main` @ `9803e4253`:**

| Größe | Wert |
|---|---|
| Workflows gesamt | 71 |
| davon selbstbeweisend (`pull_request`) | 8 |
| davon extern | 63 |
| von Workflows referenzierter Code | 528 |
| davon von Tests importiert | 174 |
| **KLASSE** | **411** (63 YAMLs + 348 Code) |
| beweispflichtige Merges (letzte 200 auf main) | **26 (13 %)** |
| davon Library-Refresh-Bot | **0** |

Diese Zahlen sind die **Untergrenzen** des Wächters, nach dem Muster von `pin_registry.toml` am
gemessenen Wert eingetragen und datiert. Fällt eine darunter, ist der Parser kaputt und nicht
die Welt sauberer — eine leere Zwischenmenge ist ein Fehler, kein Ergebnis.

Validierung der Ableitung: Die 26 Treffer sind namentlich genau die Änderungen, deren Beweise
heute im Bash-Skript hängen — #5013, #5014, #5020, der Layout-Wächter, das Supersession-Gate
#4998, die expected-stale-Deklarationen #5007, die Marker-Ampel. Die Ableitung findet die
Klasse, für die das Ledger gebaut wird, ohne dass ihr diese Fälle genannt wurden.

Zwei frühere Fassungen und warum sie fielen:

- **Stamm-Heuristik** („Dateiname kommt unter `tests/` vor"): an der eigenen Positivkontrolle
  gescheitert. `scripts/tv_batch_consumer_rollout.ts` galt als abgedeckt, weil ein Vertragstest
  die Datei **parst**. Geparst ist nicht ausgeführt; 524 von 528 Dateien fielen fälschlich
  heraus.
- **Alle Workflow-YAMLs in der Klasse**: 40 statt 26 beweispflichtige Merges, davon 35 allein
  wegen YAML-Berührungen. Lautester Verursacher `smc-fast-pr-gates.yml` mit 13 Treffern — ein
  Workflow, der sich im nächsten PR-Lauf selbst beweist.

### Das Offline-Gate

`scripts/check_proof_ledger.py --range A...B`, in `fast-gates` neben den anderen
`check_*`-Wächtern. Kein Netz.

**Drei Punkte, nicht zwei.** `git diff A..B` ist kein Bereich, sondern ein Vergleich zweier
Bäume; auf einem älteren PR-Branch meldet er fremde main-Änderungen als eigene. Gemessen am
2026-08-04 an `d3d387a80..233adebc0`, wo der R1-Guard #4373 fälschlich rot machte.

**Nur der PR-Diff, nie der Ist-Zustand von main.** Sonst scheitert jeder PR an Altlasten,
einschließlich desjenigen, der sie repariert — die Begründung steht ausformuliert im Docstring
von `check_r1_attested_sources.py`.

Vier Prüfungen:

1. **Aufnahmepflicht** — berührt der Diff die Klasse, braucht er einen neuen `[[proof]]`-Eintrag
   oder einen `[[exempt]]` mit Begründung.
2. **Wohlgeformtheit** — jeder Eintrag trägt die für seine `kind` vorgeschriebenen Felder.
3. **`judge` existiert** und ist importierbar.
4. **Anti-Willkür-Kopplung** — `SCHLAFEND` und `UNERREICHBAR` nur mit einer prüfbaren
   Repo-Tatsache als Begründung:

   ```toml
   state = "UNERREICHBAR"
   unreachable_because = "symbol:automation/tradingview/lib/tv_shared.ts#resolveLegendDoubleClickPoint"
   ```

   Verschwindet das Symbol, wird der Test rot. Ein Beweis lässt sich nicht durch Umschreiben
   eines Wortes stilllegen; es braucht eine zweite, reviewbare Änderung.

Zwei Zusätze, die aus der Messung folgen:

- **Die Klasse wird im Gate live aus dem PR-Baum abgeleitet, nie eingefroren.** Eine
  eingefrorene Liste driftet genau wie die hartkodierte Wächter-Liste, die am 2026-08-22 das
  neue `mutations`-Feld aus #5013 nicht bemerkte.
- **Ein PR, der einen Workflow von extern auf `pull_request` umstellt, schrumpft die Klasse.**
  Das ist eine Stilllegung und bekommt dieselbe Anti-Willkür-Behandlung wie `SCHLAFEND`:
  benannt und begründet, nicht still.

Wie die übrigen Wächter trägt das Gate einen `_REMEDY`-Text, der den Ausweg nennt, statt nur
rot zu sein.

### Der Urteiler

`scripts/proof_judges/<name>.py` exportiert genau eine Funktion:

```python
def judge(evidence: dict | str, entry: ProofEntry) -> Verdict: ...
```

**Rein:** kein Netz, kein `gh`, keine Uhr. Das Holen der Evidenz macht der Workflow, das
Entscheiden der Urteiler — dieselbe Naht, die der Layout-Wächter-Entwurf zieht („alle
**Entscheidungen** außerhalb des Browsers"). Ein reiner Urteiler ist gegen ein Korpus laufbar;
der heutige Bash-Urteiler ist es nicht, und genau deshalb konnte sein #5018-Zweig einen Tag lang
Urteile drucken, ohne je feuern zu können.

Die Urteilsmenge ist geschlossen. Ein Urteiler, der etwas anderes zurückgibt, ist ein Fehler,
kein Ergebnis.

### Anti-Vakuität: das Korpus

Jeder Urteiler hat ein Korpus aus **aufgezeichneten echten** Evidenzen mit Herkunft (Lauf-Id,
Ladedatum), reduziert auf die Felder, die er liest. Das Offline-Gate lässt jeden Urteiler über
sein Korpus laufen und zählt, welche Zweige dabei erreicht wurden:

| Zweig erreicht von … | Bedeutung | Folge |
|---|---|---|
| einer **echten** Evidenz | kann in Produktion feuern | `PASS`-fähig |
| nur einer **synthetischen** | nur im Drill erreichbar | `DRILL_ONLY` — nie `PASS` aus Live-Beobachtung |
| **nichts** | vakuös | **rot**, außer ausdrücklich deklariert |

Das ist die Lehre vom 2026-08-22 als Mechanismus: *eine Positivkontrolle beweist, dass der
Detektor das Signal sehen kann — nicht, dass die gestellte Frage es enthalten kann.* Eine
handgeschriebene Fixture erkauft deshalb ausdrücklich nur `DRILL_ONLY`.

Am #5018-Zweig durchgespielt: Kein Korpus-Eintrag erreicht ihn, kein synthetischer ist
hinterlegt ⇒ **rot am Tag des Merges**, mit der Aufforderung, ihn zu deklarieren. Beim
Deklarieren fällt auf, was tatsächlich der Fall ist — die Evidenz steht im Log, nicht im
Artefakt.

### Ausgänge aus SCHLAFEND

`SCHLAFEND` ist ein Durchgangszustand mit Frist, nie ein Endzustand. Genau drei Ausgänge:

| Ausgang | Beweislast | Endzustand |
|---|---|---|
| Drill bestanden | synthetischer Input durch den **echten** Entscheidungspfad | `PASS (Drill)` |
| Deklariert unerreichbar | `unreachable_because` = prüfbare Repo-Tatsache | `UNERREICHBAR` |
| Akzeptiert ungesichert | Besitzer + Frist; läuft sie ab, ist es wieder offen | `UNGESICHERT` |

Ein Drill führt synthetischen Input durch den echten Entscheidungspfad, nie durch einen Nachbau
— sonst vergleicht man zwei Implementierungen miteinander statt gegen die Evidenz. Sein Ergebnis
wird als `PASS (Drill)` geführt, getrennt von `PASS (Live)`.

Diese Trennung liefert eine Aussage, die es heute nicht gibt: **`PASS (Drill)` bei anhaltendem
`STEHT_AUS` live** heißt *die Entscheidung ist korrekt, aber der Zweig wird in Produktion nicht
erreicht.* Für #5013 war genau das der Verdacht in der Nacht des 23.8. — er ist um 05:49Z
**widerlegt** worden, und zwar von einem Lauf, den der Layout-Wächter angefordert hat. Die
Unterscheidung bleibt trotzdem nötig: Sie ist der Grund, warum der Verdacht überhaupt formuliert
werden konnte, statt als „schlafend" abgelegt zu werden.

### Alarm

`.github/workflows/proof-ledger-monitor.yml`, scheduled. Für `kind = "merge"`: Zeugen holen
(`witness_job.started_at`), `version_probe` anwenden, Urteiler rufen, Urteil mit dem
**deklarierten** Zustand vergleichen. Für `kind = "defect"` gibt es weder Zeugen noch Urteiler —
dort greift allein die Frist. Zwei Alarmklassen:

- **ÜBERFÄLLIG** — nicht-terminaler Eintrag über `due_by`
- **WIDERSPRUCH** — deklariert `PASS`, gemessen `FAIL`/`STEHT_AUS`; oder deklariert
  `UNERREICHBAR`, und der Zweig hat gefeuert

Die zweite Klasse ist der eigentliche Gewinn: sie macht aus dem Ledger eine überprüfbare
Behauptung statt einer Wunschliste.

**Der Monitor schreibt das Ledger nicht zurück.** Er meldet in *ein* Issue (Muster des
Freshness-Monitors: aktualisieren, nicht duplizieren). Zustandsänderungen macht ein Mensch im
PR, wo das Offline-Gate sie prüft. Ein Bot mit Schreibrecht auf die Beweisführung ist die
Konstruktion, durch die der Library-Refresh-Bot am 2026-07-31 und 2026-08-01 zweimal durch den
R1-Vertrag lief.

**Was er sehr wohl schreibt: das Korpus.** Jede beurteilte Evidenz wird reduziert abgelegt. Ohne
das läuft die Anti-Vakuitätsprüfung nach 30 Tagen Artefakt-Retention leer, und ein später
gebauter Urteiler bliebe auf ewig `DRILL_ONLY`.

## Schnitt

| Datei | Rolle | Änderung |
|---|---|---|
| `proof_ledger.toml` | Quelle, neben `pin_registry.toml` | neu |
| `scripts/proof_ledger.py` | der **eine** Loader + Schema (Vorbild `tests/_pin_registry.py`) | neu |
| `scripts/check_proof_ledger.py` | Offline-Gate | neu |
| `scripts/proof_judges/*.py` | reine Urteiler, einer je Eintrag | neu |
| `tests/proof_corpus/<judge>/*.json` | aufgezeichnete echte Evidenzen mit Herkunft | neu |
| `tests/test_proof_ledger.py` | Schema, Untergrenzen, Anti-Vakuität, Mutationsproben | neu |
| `.github/workflows/proof-ledger-monitor.yml` | Zeuge holen, urteilen, Widerspruch melden | neu |
| `.github/workflows/smc-fast-pr-gates.yml` | ein Wächter-Schritt mehr | ändern |

`~/.claude/scripts/tv_gate_probe_check.sh` wird dünner Aufrufer oder entfällt. Sein
Löschkriterium wird durch die Frist ersetzt — es war unerfüllbar, solange ein Eintrag nie `PASS`
erreichen kann.

## Testen

Jede Zusicherung braucht eine Mutationsprobe: ausführen, nicht lesen. Vier Pflichtproben:

1. Eine Datei aus einem Workflow entfernen ⇒ Klasse schrumpft ⇒ **rot**.
2. Ein PR berührt die Klasse ohne Eintrag ⇒ **rot**.
3. Ein Urteilszweig, den kein Korpus erreicht ⇒ **rot** (die #5018-Probe).
4. Das in `unreachable_because` genannte Symbol entfernen ⇒ **rot**.

Dazu die Positivkontroll-Liste bekannter Klassen-Mitglieder und Nicht-Mitglieder
(`tv_batch_consumer_rollout.ts` drin; `check_r1_attested_sources.py` und
`detect_vacuous_claims.py` draußen), erweitert bei jedem neuen Fund.

## Migration

Geseedet werden die vier Einträge, die heute im Bash-Skript hängen, mit dem Zustand vom
2026-08-23 05:49Z:

| Eintrag | Zustand | Zeuge |
|---|---|---|
| #5013 Partial-Save | `PASS (Live)` | Lauf `32620808573` |
| Layout-Wächter #5025 | `PASS (Live)` | Lauf `32620808573` (`executionMode: repair-only`) |
| #5020 Beweisdateien | `PASS (Live)` | Lauf `32556181388` |
| #5018 Legenden-Klick | `OFFEN`, `evidence_source = "job_log"` | kein Urteil aus dem Artefakt |

Dazu zwei `defect`-Einträge: **Klasse H** (Settings-Dialog geht nicht auf; aktueller
Ursachenkandidat ist #5027, mehrere gleichzeitig offene Dialoge) und der **irreführende
`in_flight`-Grund des Wächters** (er zählt jeden wartenden `workflow_dispatch`, auch die
read-only-Verifikation, und meldet dann „ein Reparaturlauf ist bereits in flight", wo keiner
ist — der Mechanismus stimmt, der Text lügt; am 2026-08-23 gefunden, nicht behoben).

Lauf `32620808573` ist zugleich der erste echte **Korpus-Eintrag** für `tv_partial_save`: Er
erreicht den PASS-Zweig mit echter Evidenz, nicht mit einer Fixture.
**Keine rückwirkenden Einträge** für die 26 gemessenen Altfälle: Ein Zustandscheck auf main
machte jeden PR rot, auch den reparierenden. Die Begründung ist dieselbe wie beim R1-Guard.

## Nicht im Umfang

- **Die Ursache von Klasse H** (Settings-Dialog geht nicht auf). Sie ist offen; der nächste
  Ansatzpunkt ist nach der 2026-08-23-Messung der Zustand des Skripts bzw. der TV-Sitzung, nicht
  die Klickgeometrie. Sie bekommt hier einen `defect`-Eintrag mit Besitzer und Frist, damit sie
  einen Halter hat — der Mechanismus löst sie nicht.
- **Das Beheben der beiden `defect`-Einträge.** Klasse H und der lügende `in_flight`-Text
  bekommen hier einen Halter mit Frist, damit sie nicht verdunsten. Der Mechanismus löst sie
  nicht.
- **Die Browser-Hälfte drillbar machen.** Der Schnitt legt die Entscheidungen nach außen; was im
  Browser bleibt, bleibt ehrlich unbewiesen.

## Ungesicherte Annahmen

- **Dass 13 % beweispflichtige Merges tragbar sind, ist aus 200 Commits geschätzt, nicht
  erlebt.** Fällt es zur Last, ist die Stellschraube die Trigger-Ableitung, nicht die
  Aufweichung der Pflicht.
- **Die Abdeckungserkennung ist Regex, kein Importgraph.** Sie irrt meist in die sichere
  Richtung (zu viel in der Klasse). Eine **Namenskollision** — zwei Dateien gleichen Stamms, eine
  getestet — würde eine Datei fälschlich als abgedeckt herauswerfen. Gegenmittel ist die
  Positivkontroll-Liste; sie deckt nur ab, was jemand schon einmal bemerkt hat.
- **Dass ein Korpus aus echten Evidenzen für jeden Urteiler zusammenkommt, ist nicht bewiesen.**
  Bei seltenen Zweigen kann es dauern; bis dahin gilt `DRILL_ONLY`, und das ist die ehrliche
  Auskunft, nicht ein Mangel des Mechanismus.
