# R1-Re-Attestation als wiederholbarer Ablauf — Design

Datum: 2026-08-04 · Status: entworfen, vom Operator abschnittsweise freigegeben
· Vorgänger-Spec im selben Format: `2026-08-02-tv-second-writer-design.md`

## Problem

Seit #4435 hält der Library-Refresh die R1-attestierten Companions
(`SMC_Event_Overlay.pine`, `SMC_Exit_Signal.pine`) auf ihrem attestierten
Inhalt. Das schließt die Treadmill — und bedeutet zugleich: **ein attestierter
Companion bewegt sich nie mehr automatisch.** Sein Library-Pin
(`import preuss_steffen/smc_micro_profiles_generated/<N>`) friert ein, während
die Library weiterläuft (am 2026-08-04: Pin /183, TV /186). Die Library *ist*
die generierten Mikro-Profile; der Lag ist also potenziell handelsrelevant,
nicht kosmetisch. Bewegung braucht fortan einen bewussten, wiederholbaren
Vorgang: die Re-Attestation. Dafür existiert bisher weder Werkzeug noch
Runbook — die einzige bisherige Re-Attestation (Artefakt vom 2026-08-04) war
eine reaktive Nachmessung zweier bereits gelaufener Runs.

## Entscheidungen (vom Operator getroffen, 2026-08-04)

1. **Auslöser:** Drift-Wächter + manuelle Ausführung. Kein Automatismus
   mutiert; der Lag wird sichtbar gemacht, die Ausführung bleibt
   Operator-Entscheidung.
2. **Ausführungsgestalt:** Treiber-Skript baut die PRs deterministisch; TV
   wird ausschließlich über die vorhandenen Pfade beschrieben. Kein neuer
   TV-Schreibpfad. (Verworfen: eigener End-to-End-Workflow — ein neuer
   Produzent auf TV-nahen Pfaden, genau die Klasse, die die Treadmill
   erzeugte. Verworfen: reines Runbook — die 4.8.-Erfahrung zeigt, wie viele
   Stellen konsistent wandern müssen.)
3. **Wächter-Ort:** `workflow-freshness-monitor.yml` (täglich 06:30 UTC, hat
   bereits `issues: write` und Issue-Mechanik). Erkennungslatenz damit bis zu
   24 h — bei Schwelle ≥ 3 und ~1–2 Versionen/Handelstag verkraftbar; lokal
   ist der Wächter jederzeit aufrufbar.
4. **Schwelle:** `publishedVersion − pinVersion ≥ 3`. Zwei Ganzzahlen aus dem
   Repo; keine Git-Archäologie für Altersmessung.
5. **Evidenzschnitt:** Zwei PRs — Absicht (Autorisierung) und Messung. Jedes
   Artefakt behauptet nur, was zu seinem Zeitpunkt beobachtbar war.
   (Verworfen: ein PR mit Pending-Klausel — die CURRENT-Attestation enthielte
   dauerhaft eine unbeobachtete Behauptung, und die Lauf-IDs der Verifikation
   können nie im selben Artefakt stehen.)
6. **TV-Schreiben nach PR1:** expliziter `workflow_dispatch` von
   `tv-save-consumer-source` mit Companion-Mapping — nicht passiv auf die
   nächste Refresh-Kette warten. Deterministischer Messzeitpunkt, vorhandene
   Gates (Operator-Fenster, Preflight, Attestations-Abgleich).

## Verifizierte Grundlagen (gemessen 2026-08-04, nicht angenommen)

- Der Guard (`scripts/check_r1_attested_sources.py`) lässt einen PR
  ausdrücklich passieren, der „a fresh rollout with new evidence" im selben
  Diff landet. PR1 ist die Konstruktion, für die er gebaut ist.
- `tv-save-consumer-source` triggert auf `workflow_run` (smc-library-refresh
  completed), Cron 05:17/21:17 UTC (read-only) und `workflow_dispatch` mit
  `mapping`-Input. **Ein Merge nach main triggert ihn nicht.**
- Manifest-Schlüssel: `artifacts/tradingview/library_release_manifest.json →
  library.publishedVersion`.
- Contract: `build_rollout_contract()["targets"]` — `SMC_Event_Overlay.pine`
  trägt `libraryPin {importPath, version}`, **`SMC_Exit_Signal.pine` trägt
  keinen `libraryPin`**.
- Evidenz-Artefakte: `artifacts/governance/smc_r1_live_rollout_evidence_
  <YYYY-MM-DD>.json`, schemaVersion 2, mit `supersedes`/`supersessionNote`;
  datierte Artefakte werden superseded, nie umgeschrieben.

## Komponente 1: Drift-Wächter

Funktion in einem neuen `scripts/check_r1_pin_drift.py`, aufgerufen vom
freshness-monitor-Job:

- Liest Contract-Targets und `library.publishedVersion`.
- Pro Target mit `libraryPin`: Abstand berechnen. Targets **ohne** `libraryPin`
  werden explizit als „nicht drift-fähig" ausgewiesen (Exit_Signal) — weder
  Crash noch stilles Grün.
- Abstand ≥ 3 bei mindestens einem Target → Issue öffnen oder aktualisieren
  (Label `r1-pin-drift`): Versionsabstand, betroffene Companions, fertiger
  Treiber-Aufruf als Copy-Paste. Ein Issue pro Drift-Episode.
- Abstand überall < 3 → offenes `r1-pin-drift`-Issue schließen, mit Verweis
  auf den heilenden PR.
- Degradation fail-closed: Manifest unlesbar, Contract leer, `libraryPin`
  fehlt am Event-Overlay → Fehler, nie still grün.

## Komponente 2: Treiber-Skript `scripts/run_r1_reattestation.py`

Beide Unterbefehle sind idempotent und gegenüber TradingView read-only; sie
verändern nur den Arbeitsbaum. Committen, pushen, PR öffnen, dispatchen bleibt
beim Operator.

### `prepare` → PR1 (Absicht)

1. Publizierte Version aus dem Manifest lesen; Ziel-Pin bestimmen.
2. Import-Pin der Companion(s) mit `libraryPin` bumpen; neue SHA-256 rechnen.
3. Autorisierungs-Artefakt schreiben: `status: authorized_execution_pending`,
   `supersedes` auf das aktuelle Artefakt, TV-Sektion ehrlich als „not yet
   observed", erwarteter Zwischenzustand des Verify-Crons dokumentiert.
4. Contract aktualisieren: Target-SHAs, `libraryPin.version`,
   `executionEvidence` → neues Artefakt, `priorExecutionEvidence` → Vorgänger.
5. Abbruch mit Meldung, wenn der Pin schon auf Ziel steht oder das heutige
   Artefakt existiert (Same-Day-Zweitlauf ist Operator-Sonderfall).
6. Gibt am Ende das fertige Dispatch-Kommando für Schritt „TV-Schreiben" aus.
   Das Mapping umfasst **nur die in PR1 geänderten Quellen** (aktuell also nur
   `SMC_Event_Overlay.pine`) — eine unveränderte attestierte Quelle wird nicht
   erneut gespeichert.

### `measure` → PR2 (Messung)

1. Liest per `gh api` die nach dem PR1-Merge abgeschlossenen Läufe von
   `tv-save-consumer-source` (mutierender Dispatch) und dem Auto-Re-Verify.
2. Keine abgeschlossenen Läufe → Abbruch, nichts geschrieben. Keine vakuöse
   Messung.
3. Mess-Artefakt nach dem 4.8.-Muster („reads runs that had already
   happened"): beobachtete SHAs/Versionen, Lauf-IDs in `evidenceRuns`.
4. Grüne Messung → Status `authorized_execution_reattested`, Contract-Pointer
   auf das Mess-Artefakt. Rote Messung → Artefakt wird **trotzdem**
   geschrieben, mit dem Fehlschlag als Befund; Status bleibt
   `authorized_execution_pending`; `openGates` wächst.

## Ablauf (Soll-Pfad)

```text
Wächter-Issue (oder Operator-Entscheid)
  → prepare  → PR1: Pin + Autorisierungs-Artefakt + Contract   [Guard grün]
  → Merge PR1
  → Operator dispatcht tv-save-consumer-source (mutierend, Companion-Mapping)
      [vorhandene Gates: Operator-Fenster, Preflight, Attestations-Abgleich]
  → Auto-Re-Verify läuft (vorhandene Mechanik, #4318)
  → measure  → PR2: Mess-Artefakt + Contract-Pointer            [Guard: Quelle unberührt]
  → Merge PR2
  → Wächter schließt das Issue beim nächsten Cron
```

## Fehlerpfade

- **Save/Verify rot nach Dispatch:** Status bleibt `…_pending` (ehrlich — es
  ist eine offene Ausführung). Wiederholungsweg ist erneuter Dispatch bzw. die
  Auto-Re-Verify-Mechanik. Kein Rollback-Automatismus: Die Pin-Rücknahme ist
  laut 4.8.-Befund die invasivere Option.
- **Refresh läuft zwischen PR1-Merge und Dispatch:** Der Hold stellt auf
  HEAD-Inhalt zurück — nach PR1-Merge ist das der neue Pin. Konsistent; die
  Refresh-Kette speichert die Quellen ohnehin aus main.
- **Verify-Cron im Zwischenfenster:** meldet erwartbar Quelldrift (Repo neu,
  TV alt). Im Autorisierungs-Artefakt als erwarteter Zwischenzustand
  dokumentiert.
- **PR1 bleibt liegen:** Wächter-Issue bleibt offen; der Wächter misst gegen
  main.

## Tests (ausführend, nach Repo-Disziplin)

- **Wächter:** Fixture-Contract/-Manifest — ≥ 3 → Issue-Payload; < 3 →
  Schließpfad; pin-loses Target → „nicht drift-fähig"; leerer Contract →
  Fehler. Mutationsproben: Schwelle invertiert, Drift-Berechnung entfernt →
  jeweils rot.
- **prepare:** temporäres Git-Repo — exakter Pin-Bump, SHA-Berechnung,
  Artefakt-Schema (v2, supersedes-Kette), Contract-Update, Idempotenz-Abbruch.
- **measure:** gestubbtes `gh` mit argv-Log (Harness-Muster
  `tests/_workflow_step_shell.py`) — inklusive Fail-closed ohne Läufe.
- **Ledger:** neue `scripts/`-Dateien treffen erfahrungsgemäß vier Ledger
  gleichzeitig (noqa, atomic-write, subprocess-Pin, sys.path); Registrierung
  im selben Commit, Guard **nach** dem Staging fahren.
- **Workflow-Edit** (freshness-monitor): `pytest tests/ -k workflow` Pflicht;
  neue Schritte per `run_step` ausführen, nicht string-matchen.

## Erstausführung

Die erste Re-Attestation (nach dem 22:00-UTC-Tick am 2026-08-04) läuft einmal
von Hand entlang exakt dieses Zwei-PR-Schnitts und ist damit der Realitätstest
des Designs. Das Skript automatisiert anschließend den Weg, der sich bewährt
hat; Abweichungen fließen zurück in dieses Spec.

## Nicht-Ziele

- Kein neuer TV-Schreibpfad, kein neuer Workflow.
- Keine automatische Re-Attestation, egal wie groß der Drift wird.
- Keine Änderung am Hold, am Guard oder am Evidenz-Schema.
- Kein Nachziehen des pin-losen Exit_Signal-Targets — es hat keinen
  Library-Import und braucht keine Pin-Bewegung.
