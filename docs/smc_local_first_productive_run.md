# SMC Local First Productive Run

Stand: 2026-04-08

## Ziel

Dieses Runbook beschreibt den kuerzesten belastbaren lokalen Pfad von:

- fixture-basierter Micro-Library

zu:

- echtem publish-ready Source-Stand
- erfolgreichem TradingView-Publish
- gruener Mainline-Validierung

Es ist bewusst auf den ersten produktiven SMC-Lauf fokussiert. Es ist kein
allgemeines Architektur- oder Refactoring-Programm.

## Definition of Done

Der lokale Erstlauf ist erst dann abgeschlossen, wenn alle folgenden Punkte
erfuellt sind:

1. `pine/generated/smc_micro_profiles_generated.json` ist nicht mehr
   fixture-basiert.
2. `productivity_gate.publish_ready = true`.
3. `fixture_input_detected = false`.
4. `placeholder_symbols` ist leer.
5. `event_risk_source` ist nicht `defaults`.
6. `npm run smc:verify-micro-publish` ist gruen.
7. der TradingView-Publish liefert einen Report mit `ok = true` und
   `publishStatus = published`.
8. `npm run tv:preflight:smc-mainline` ist gruen.

## Empfohlener Pfad

Der bevorzugte Ablauf ist:

1. lokale Erzeugung mit echten Daten
2. lokale Contract-Gates
3. lokaler TradingView-Publish
4. lokaler Mainline-Preflight

Damit wird der Root Cause direkt adressiert: der aktuelle generierte Source-Stand
ist nicht publish-ready.

Wenn bereits ein echter Databento-Export vorliegt, aber der kanonische
Library-Stand noch fixture-basiert ist, gilt zusaetzlich der Recovery-Plan in
`docs/smc_bundle_to_library_recovery_plan_2026-04-09.md`.

Wichtig: Dieses Runbook beschreibt den produktiven Zielpfad. Die saubere
Trennung zwischen Bundle-/Base-Artefakten und kanonischem Repo-Output ist dort
noch nicht als eigener Korrekturschritt ausformuliert.

## Work Package 0: Voraussetzungen herstellen

## Pflicht-Inputs

Mindestens diese Secrets oder Umgebungsvariablen muessen verfuegbar sein:

1. `DATABENTO_API_KEY`
2. `FMP_API_KEY`

Praktisch empfohlen:

1. `BENZINGA_API_KEY`
2. `NEWSAPI_KEY` optional

## Live-News-Sidecar: Provider und API-Reduktion

Der Live-News-Snapshot fuer den SMC-Lauf nutzt jetzt einen gemeinsamen
Provider-Fetch-Cache statt separater API-Calls pro Consumer.

Aktive Quellen im Snapshot-/Bus-Pfad:

1. `fmp_stock_latest`
2. `fmp_press_latest`
3. `fmp_articles`
4. `benzinga_rest`
5. `newsapi_ai` wenn `NEWSAPI_KEY` gesetzt ist; nutzt Event Registry `minuteStreamArticles` fuer laufende Polls, persistiert nach Moeglichkeit `recentActivityArticlesNewsUpdatesAfterUri` und faellt fuer aeltere Cursor auf `getArticles` plus `getEvents` zurueck
6. `tradingview` als optionaler symbol-spezifischer Supplement-Pfad

Die gemeinsam genutzten Cache-Parameter koennen bei Bedarf uebersteuert werden:

1. `SHARED_NEWS_CACHE_DIR` default `artifacts/shared_news_cache`
2. `SHARED_NEWS_CACHE_TTL_SECONDS` default `90`

Die optionale Databento-Reference-Schicht fuer Alias-/Identifier-Wechsel und den
Event-Risk-Zusatzpfad kann ebenfalls uebersteuert werden:

1. `DATABENTO_REFERENCE_CACHE_DIR` default `artifacts/databento_reference_cache`
2. `DATABENTO_REFERENCE_CACHE_TTL_SECONDS` default `21600`
3. `DATABENTO_REFERENCE_FAILURE_TTL_SECONDS` default `86400`
4. `DATABENTO_REFERENCE_EVENT_RISK_WINDOW_DAYS` default `14`

Fuer den TradingView-Teil lokal benoetigt:

1. `TV_PERSISTENT_PROFILE_DIR` oder `TV_STORAGE_STATE`

## Workspace-Checks

Im Repo-Root ausfuehren:

```bash
source .venv/bin/activate
python --version
npm ci
npx playwright install --with-deps chromium
```

## TradingView-Auth vorbereiten

Der bevorzugte lokale Pfad ist das persistente Profil:

```bash
npm run tv:profile-login
```

Danach fuer Publish und Mainline-Preflight denselben Profilpfad verwenden:

```bash
export TV_PERSISTENT_PROFILE_DIR="$PWD/automation/tradingview/auth/chromium-profile"
```

Hinweis:

- Das persistente Profil ist fuer mutierende Runs stabiler als ein reines
  Storage-State-File.

## Work Package 1: Echten Library-Source-Stand generieren

## Bevorzugter Generator-Pfad

Die direkte CLI ist fuer den ersten belastbaren Lauf der klarste Pfad, weil
sie den gesamten Output reproduzierbar in Artefakte schreibt:

```bash
export DATABENTO_API_KEY="..."
export FMP_API_KEY="..."
export BENZINGA_API_KEY="..."

./.venv/bin/python scripts/generate_smc_micro_base_from_databento.py \
  --run-scan \
  --enrich-all \
  --dataset DBEQ.BASIC \
  --lookback-days 30 \
  --export-dir artifacts/smc_microstructure_exports \
   --output-root . \
  --library-owner preuss_steffen \
  --library-version 1 \
  --write-xlsx
```

`--export-dir` schreibt Bundle- und Base-Artefakte. `--output-root .` schreibt
den kanonischen Library-Stand nach `pine/generated/` im Repo-Root.

## Alternative UI-Pfad

Falls du den Lauf ueber die Operator-UI fahren willst:

```bash
streamlit run streamlit_smc_micro_base_generator.py
```

Dann in der UI genau diese Sequenz fahren:

1. `Run SMC Base Scan`
2. `Generate Pine Library`
3. erst bei gruenem Guard `Publish To TradingView`

Die Pine-Generierung in der UI laeuft jetzt ueber denselben shared
`finalize_pipeline(...)`-Pfad wie der CLI-/Workflow-Run und schreibt damit
kanonische Library-Outputs nach `pine/generated/` sowie Runtime-Sidecars unter
`artifacts/smc_microstructure_exports/`.

Fuer den ersten reproduzierbaren Evidenzlauf ist die CLI trotzdem vorzuziehen,
weil alle Parameter explizit sichtbar bleiben.

## Erwartete Artefakte nach Work Package 1

Die wichtigsten Dateien sind:

1. `pine/generated/smc_micro_profiles_generated.pine`
2. `pine/generated/smc_micro_profiles_generated.json`
3. `pine/generated/smc_micro_profiles_core_import_snippet.pine`
4. `artifacts/smc_microstructure_exports/...`

## Work Package 2: Publish-Readiness hart pruefen

## Contract-Gate ausfuehren

```bash
npm run smc:verify-micro-publish
```

## Pflicht-Checks im Manifest

Diese Stellen muessen gruen sein:

```bash
rg -n '"input_path"|"event_risk_source"|"publish_ready"|"fixture_input_detected"|"placeholder_symbols"' pine/generated/smc_micro_profiles_generated.json
```

Erwartung:

1. `input_path` zeigt nicht auf `tests/fixtures/seed_base_snapshot.csv`
2. `publish_ready` ist `true`
3. `fixture_input_detected` ist `false`
4. `placeholder_symbols` ist leer
5. `event_risk_source` ist nicht `defaults`

## Zusatzausgabe in der Pine-Datei pruefen

```bash
rg -n 'ASOF_DATE|UNIVERSE_SIZE|AAA|BBB|CCC|EVENT_WINDOW_STATE|EVENT_RISK_LEVEL' pine/generated/smc_micro_profiles_generated.pine
```

Erwartung:

1. `ASOF_DATE` ist aktuell
2. `UNIVERSE_SIZE` ist groesser als der Testwert `3`
3. `AAA|BBB|CCC` tauchen nicht mehr als Platzhalterlisten auf
4. Event-Risk-Felder sind belegt, aber nicht nur Default-Safe-Werte aus dem
   Seed-Lane-Grund

## Stop-Kriterien nach Work Package 2

Wenn einer dieser Punkte rot bleibt, nicht publizieren:

1. `fixture_input_detected = true`
2. `publish_ready = false`
3. `default_event_risk_detected = true`
4. `placeholder_symbols` nicht leer

Dann ist der Source-Stand noch nicht produktiv.

## Work Package 3: TradingView lokal publizieren

## Publish-Aufruf

```bash
TV_PERSISTENT_PROFILE_DIR="$PWD/automation/tradingview/auth/chromium-profile" npm run tv:publish-micro-library
```

## Erwartete Ausgabe

Es wird ein Report unter `automation/tradingview/reports/` geschrieben, zum
Beispiel:

- `publish-micro-library-<timestamp>.json`

Pruefen:

```bash
rg -n '"ok"|"publishOk"|"publishStatus"|"publishedVersion"|"error"' automation/tradingview/reports/publish-micro-library-*.json
```

Erwartung:

1. `ok = true`
2. `publishOk = true`
3. `publishStatus = "published"`

## Bekannte Failure-Lane

Wenn der erste Publish zwar funktioniert, die Version aber nicht sauber
verifiziert wird, ist ein zweiter identischer Publish-Lauf zulaessig und oft
hilfreich. TradingView landet dann haeufig in der idempotenten
"Nothing to update"-Spur und liefert bessere Verifikation.

## Work Package 4: Mainline gegen den neuen Library-Stand validieren

## Mainline-Preflight

```bash
npm run tv:preflight:smc-mainline
```

Optional danach noch readonly Smoke:

```bash
npm run tv:smoke-readonly
```

## Erwartete Artefakte

1. neuer Preflight-Report in `automation/tradingview/reports/`
2. Mainline-Ziele bleiben gruen fuer:
   - `SMC_Core_Engine.pine`
   - `SMC_Dashboard.pine`
   - `SMC_Long_Strategy.pine`

## Work Package 5: Evidenz sichern

Nach einem erfolgreichen lokalen Erstlauf sollten mindestens diese Punkte
dokumentiert oder referenziert werden:

1. Pfad des erfolgreichen Publish-Reports
2. Pfad des erfolgreichen Mainline-Preflight-Reports
3. aktueller Importpfad aus
   `pine/generated/smc_micro_profiles_generated.json`
4. finaler `productivity_gate`-Status

Die minimal sinnvollen Zielorte fuer diese Evidenz sind:

1. `docs/smc-validation-status.md`
2. `docs/smc_deep_review_v5_verified_action_plan.md`
3. optional `README.md`, wenn der Lauf als neue kanonische Baseline dienen soll

## Failure Map

## Fall A: `fixture_input_detected` bleibt true

Bedeutung:

- Es wurde nicht der echte Scan-/Bundle-Pfad verwendet.

Pruefen:

1. ob versehentlich ein Seed-Reference-Stand aus
   `tests/fixtures/generated_seed/` statt des echten Bundle-/Scan-Pfads
   verwendet wurde
2. ob die UI noch auf einem Seed-CSV statt auf einem echten Base-Snapshot steht
3. ob `input_path` im Manifest immer noch auf `tests/fixtures/...` zeigt

## Fall B: `placeholder_symbols` bleibt nicht leer

Bedeutung:

- Der Generator arbeitet immer noch mit Seed- oder Testsymbolen.

Pruefen:

1. Basis-Snapshot-Auswahl
2. Export-Bundle-Quelle
3. ob ein echter Run-Scan statt eines deterministischen Test-Refreshes lief

## Fall C: `default_event_risk_detected` bleibt true

Bedeutung:

- Event-Risk wurde nicht aus echten Calendar-/News-Daten erzeugt.

Pruefen:

1. `FMP_API_KEY`
2. `BENZINGA_API_KEY`
3. ob der Lauf wirklich mit `--enrich-all` oder mindestens Event-Risk-faehigem
   Enrichment lief

## Fall D: TradingView-Publish scheitert an Auth oder Kontext

Bedeutung:

- Die lokale Auth-Session ist nicht als wiederverwendbare mutierende Session
  brauchbar.

Pruefen:

1. `npm run tv:profile-login` erneut ausfuehren
2. dass `TV_PERSISTENT_PROFILE_DIR` gesetzt ist
3. nicht auf ein anonymes oder read-only Storage-State ausweichen

## Fall E: Mainline-Preflight rot nach erfolgreichem Publish

Bedeutung:

- Library-Publish und Consumer-Pfad sind noch nicht konsistent.

Pruefen:

1. `recommended_import_path` im Manifest
2. Import in `SMC_Core_Engine.pine`
3. contiguous alias block im Core
4. Compile- und Bindingsignale im neuen Preflight-Report

## Kurzversion fuer einen echten Erstlauf

Wenn du nur die kuerzeste direkte Ausfuehrungssequenz willst:

```bash
source .venv/bin/activate
npm ci
npx playwright install --with-deps chromium
npm run tv:profile-login

export TV_PERSISTENT_PROFILE_DIR="$PWD/automation/tradingview/auth/chromium-profile"
export DATABENTO_API_KEY="..."
export FMP_API_KEY="..."
export BENZINGA_API_KEY="..."

./.venv/bin/python scripts/generate_smc_micro_base_from_databento.py \
  --run-scan \
  --enrich-all \
  --dataset DBEQ.BASIC \
  --lookback-days 30 \
  --export-dir artifacts/smc_microstructure_exports \
   --output-root . \
  --library-owner preuss_steffen \
  --library-version 1 \
  --write-xlsx

npm run smc:verify-micro-publish
TV_PERSISTENT_PROFILE_DIR="$PWD/automation/tradingview/auth/chromium-profile" npm run tv:publish-micro-library
npm run tv:preflight:smc-mainline
```

## Referenzen

Ergaenzende Details stehen in:

1. `docs/smc_deep_review_v5_verified_action_plan.md`
2. `docs/tradingview-micro-library-publish.md`
3. `docs/smc-microstructure-ui-operator-runbook.md`
