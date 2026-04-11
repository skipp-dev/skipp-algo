# SMC Bundle To Library Recovery Plan

Stand: 2026-04-09

## Status Update

Stand nach der Umsetzung von Phase 1 und 2 am 2026-04-09:

1. Der CLI-/Workflow-Vertrag trennt jetzt Bundle-/Base-Artefakte von den
   kanonischen Library-Outputs ueber `--export-dir` und `--output-root`.
2. Die deterministische Seed-Referenz wurde nach
   `tests/fixtures/generated_seed/pine/generated/` verschoben.
3. `pine/generated/` ist jetzt der kanonische bundle-/scan-derived Stand und
   wurde aus dem realen 2026-04-05-Bundle neu erzeugt.
4. Der aktuelle kanonische Manifest-Stand ist nicht mehr fixture-basiert und
   traegt `publish_ready = true`.
5. Offen bleiben die Hardening-Schritte aus Phase 3 und 4.

## Verifizierte Ist-Lage

Die aktuelle Repo-Lage ist inkonsistent, aber der Root Cause ist kein fehlender
Bundle-zu-Base-Mechanismus.

Verifiziert ist:

1. Ein echter Databento-Full-Universe-Export vom 2026-04-05 liegt unter
   `artifacts/smc_microstructure_exports/` vor.
2. Das kanonische eingecheckte Library-Manifest unter `pine/generated/` ist
   weiter fixture-basiert.
3. Fuer den 2026-04-05-Lauf liegen keine abgeleiteten
   `__smc_microstructure_base_*`-Ausgaben als nachvollziehbarer finaler Repo-
   Stand vor.
4. Der Code kann ein bestehendes Export-Bundle bereits in einen Base-Snapshot
   und anschliessend in die Pine-Library ueberfuehren.
5. Der aktuelle CLI-Vertrag koppelt den finalen Library-Output an denselben
   Pfad wie Bundle- und Base-Artefakte, waehrend Workflow und Runbooks den
   kanonischen Library-Stand unter `pine/generated/` im Repo-Root erwarten.

## Evidenzpunkte

- Das aktuelle kanonische Manifest bleibt fixture-basiert:
  - `asof_date = 2026-03-23`
  - `input_path = tests/fixtures/seed_base_snapshot.csv`
  - `event_risk_source = defaults`
  - `publish_ready = false`
  - `fixture_input_detected = true`
  - `placeholder_symbols` ist gesetzt
- Das reale Bundle vom 2026-04-05 ist vorhanden und gross genug fuer einen
  produktiven Lauf:
  - `dataset = DBEQ.BASIC`
  - `export_generated_at = 2026-04-05T08:08:17+00:00`
  - `universe_rows = 6852`
  - `supported_universe_rows = 6847`
  - `detail_symbol_count = 3897`
  - `ranked_rows = 26210`
  - `summary_rows = 26210`
  - `selected_symbol = STAK`

## Root-Cause-Einschaetzung

Das Problem ist mit hoher Wahrscheinlichkeit zweistufig:

1. Es gab keinen sauber abgeschlossenen Handoff vom realen 2026-04-05-Bundle
   zum kanonischen finalen Library-Stand.
2. Dieser Handoff ist leicht zu verfehlen, weil `--export-dir` derzeit sowohl
   fuer Bundle-/Base-Artefakte als auch fuer die finalen Generator-Outputs als
   `output_root` verwendet wird.

Dadurch entsteht eine unklare Vertragslage:

- Das Schema definiert `pine/generated/...` als relative Generator-Outputs.
- Der Publisher schreibt diese Pfade relativ zu `output_root`.
- Die Workflow-Validierung liest aber `pine/generated/...` im Repo-Root.
- Gleichzeitig ist `artifacts/smc_microstructure_exports/` in `.gitignore`,
  also ungeeignet als kanonischer Commit-Nachweis fuer den finalen Stand.

## Action Plan

## Phase 1: Output-Vertrag trennen

Ziel:

- Bundle-/Base-Artefakte und kanonische Repo-Outputs muessen getrennte,
  explizite Ziele bekommen.

Arbeitspakete:

1. Im CLI einen separaten Parameter `--output-root` einfuehren.
2. `--export-dir` nur noch fuer Bundle- und Base-Artefakte verwenden.
3. `finalize_pipeline(...)` und den Publisher so verdrahten, dass
   `pine/generated/...` bewusst nach `--output-root` geschrieben wird.
4. Den Default fuer `--output-root` auf `.` setzen, damit Workflow und lokaler
   Repo-Stand dieselbe kanonische Stelle verwenden.
5. Den Lauf-Output explizit loggen:
   - verwendetes Bundle-Manifest
   - Base-Artefaktverzeichnis
   - finales Library-Output-Root

Exit-Kriterien:

- Ein `--bundle`-Lauf mit bestehendem Export kann final nach `pine/generated/`
  im Repo-Root schreiben, ohne Bundle-Artefakte aus `artifacts/...` zu
  verdrängen.

## Phase 2: Vorhandenes 2026-04-05-Bundle rehydrieren

Ziel:

- Den bereits vorhandenen echten Export verwenden, statt den Full-Universe-Scan
  erneut zu fahren.

Arbeitspakete:

1. Nach Phase 1 den Generator gegen das bestehende Manifest fahren:

```bash
./.venv/bin/python scripts/generate_smc_micro_base_from_databento.py \
  --bundle artifacts/smc_microstructure_exports/databento_volatility_production_20260405_080817_manifest.json \
  --enrich-all \
  --export-dir artifacts/smc_microstructure_exports \
  --output-root .
```

1. Danach den kanonischen Output pruefen:
   - `pine/generated/smc_micro_profiles_generated.json`
   - `pine/generated/smc_micro_profiles_generated.pine`
   - `pine/generated/smc_micro_profiles_core_import_snippet.pine`
2. Manifest-Gates verifizieren:
   - `input_path` zeigt nicht mehr auf `tests/fixtures/...`
   - `fixture_input_detected = false`
   - `publish_ready = true`
   - `placeholder_symbols` leer
   - `event_risk_source != defaults`

Exit-Kriterien:

- Der kanonische Repo-Stand ist nicht mehr fixture-basiert und verweist logisch
  auf den realen Bundle-Lauf.

## Phase 3: Workflow und Contract Gates anpassen

Ziel:

- Zukuenftige Refreshes muessen denselben Handoff deterministisch treffen.

Arbeitspakete:

1. `.github/workflows/smc-library-refresh.yml` explizit mit beiden Pfaden
   fahren:
   - `--export-dir artifacts/smc_microstructure_exports`
   - `--output-root .`
2. Nach dem Generatorlauf zwei Dinge pruefen:
   - Repo-Root `pine/generated/...` existiert und wurde aktualisiert
   - im Export-Verzeichnis existiert ein `__smc_microstructure_base_manifest`
     fuer denselben Lauf
3. Falls kein Base-Manifest entsteht, den Workflow hart fehlschlagen lassen.
4. Einen kleinen Smoke-Test fuer die Output-Pfad-Semantik ergaenzen.

Exit-Kriterien:

- Ein Workflow-Lauf kann nicht mehr erfolgreich durchlaufen, wenn nur das
  Bundle erzeugt wurde, aber der kanonische Library-Stand unveraendert blieb.

## Phase 4: Commit-faehige Provenienz sichtbar machen

Ziel:

- Weil `artifacts/smc_microstructure_exports/` ignoriert ist, muss der
  commit-faehige Repo-Stand die Herkunft des finalen Library-Laufs sichtbar
  machen.

Arbeitspakete:

1. Im commit-faehigen Manifest oder in einer kleinen Sidecar-Datei mindestens
   diese Provenienzfelder sichtbar machen:
   - Quell-Bundle-Manifest oder Basename
   - `export_generated_at`
   - `dataset`
   - `asof_date`
2. Das lokale Erstlauf-Runbook und die Publish-Doku auf den getrennten
   Output-Vertrag aktualisieren.
3. In der Change-Doku festhalten, dass 2026-04-05 der erste reale Bundle-Stand
   war, der in den kanonischen Library-Stand ueberfuehrt wurde.

Exit-Kriterien:

- Ein spaeterer Audit muss den finalen Repo-Stand auf einen konkreten produktiv
  erzeugten Bundle-Lauf zurueckfuehren koennen, ohne auf ignorierte Artefakte
  angewiesen zu sein.

## Reihenfolgeempfehlung

Die pragmatische Reihenfolge ist:

1. Pfadvertrag trennen
2. 2026-04-05-Bundle rehydrieren
3. Manifest/Gates verifizieren
4. Workflow absichern
5. Provenienz sichtbar machen

Damit wird zuerst der echte fachliche Rueckstand geschlossen und erst danach
der Ablauf gegen Wiederholung gehaertet.
