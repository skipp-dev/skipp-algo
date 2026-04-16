# TradingView Manual Publish Checklist

Stand: 2026-04-16 (aktualisiert)
Branch: `main` @ `45858132`

## Zusammenfassung

Alle 5 Libraries wurden am 2026-04-16 vom User als manuell publiziert gemeldet.
**Fuer keine der 5 Libraries existiert ein Post-Publish-Screenshot im Repo.**
Alle 5 bleiben `publish_verified: no`. Siehe `docs/tradingview-manual-publish-evidence-2026-04-16.md` fuer das strukturierte Evidenz-Protokoll.

## Library-Status-Tabelle

| # | Library | Import-Pfad | Datei | Compile-Evidenz | Publish-Evidenz | Publish-Script | Aktion |
|---|---------|-------------|-------|-----------------|-----------------|----------------|--------|
| 1 | `smc_core_types` | `preuss_steffen/smc_core_types/1` | `SMC++/smc_core_types.pine` | Screenshot zeigt CE10013 | user-reported, unverified | keines | **Post-Publish-Screenshot noetig** |
| 2 | `smc_draw` | `preuss_steffen/smc_draw/1` | `SMC++/smc_draw.pine` | keine | user-reported, unverified | keines | **Compile + Post-Publish-Screenshot noetig** |
| 3 | `smc_utils` | `preuss_steffen/smc_utils/1` | `SMC++/smc_utils.pine` | ja (2026-04-16 Live) | user-reported, unverified | keines | **Post-Publish-Screenshot noetig** |
| 4 | `smc_context_resolvers` | `preuss_steffen/smc_context_resolvers/1` | `SMC++/smc_context_resolvers.pine` | ja (2026-04-16 Live) | user-reported, unverified | keines | **Post-Publish-Screenshot noetig** |
| 5 | `smc_profile_engine` | `preuss_steffen/smc_profile_engine/1` | `SMC++/smc_profile_engine.pine` | ja (2026-04-16 Live) | user-reported, unverified | keines | **Post-Publish-Screenshot noetig** |
| 6 | `smc_bus_private` | `preuss_steffen/smc_bus_private/1` | `SMC++/smc_bus_private.pine` | ja (historisch) | ja (2026-04-05, historisch) | keines (dediziert) | Nur Re-Publish bei Code-Aenderung |
| 7 | `smc_lifecycle_private` | `preuss_steffen/smc_lifecycle_private/1` | `SMC++/smc_lifecycle_private.pine` | ja (historisch) | ja (2026-04-05, historisch) | `scripts/tv_publish_lifecycle_library.ts` | Nur Re-Publish bei Code-Aenderung |
| 8 | `smc_observability_private` | `preuss_steffen/smc_observability_private/1` | `SMC++/smc_observability_private.pine` | ja (historisch) | ja (2026-04-05, historisch) | `scripts/tv_publish_observability_library.ts` | Nur Re-Publish bei Code-Aenderung |
| 9 | `smc_micro_profiles_generated` | `preuss_steffen/smc_micro_profiles_generated/1` | `pine/generated/smc_micro_profiles_generated.pine` | ja | ja (fortlaufend) | `scripts/tv_publish_micro_library.ts` | Automatisiert, kein manueller Publish noetig |

## Abhaengigkeitsgraph

```
smc_core_types          (keine Abhaengigkeiten)
smc_draw                (keine Abhaengigkeiten)
smc_bus_private         (keine Abhaengigkeiten)
smc_lifecycle_private   (keine Abhaengigkeiten)
  │
  ▼
smc_utils               (importiert: smc_core_types)
  │
  ├──▶ smc_observability_private  (importiert: smc_utils)
  ├──▶ smc_profile_engine         (importiert: smc_utils, smc_draw)
  └──▶ smc_context_resolvers      (importiert: smc_utils, smc_bus_private)
         │
         ▼
  SMC_Core_Engine.pine  (importiert alle 9 Libraries)
```

## Pflicht-Publish-Reihenfolge

Die Reihenfolge ergibt sich aus dem Abhaengigkeitsgraph. Jede Library muss
ERST published sein, bevor eine abhaengige Library published werden kann.

| Schritt | Library | Grund |
|---------|---------|-------|
| 1 | `smc_core_types` | Keine Abhaengigkeiten, wird von `smc_utils` importiert |
| 2 | `smc_draw` | Keine Abhaengigkeiten, wird von `smc_profile_engine` importiert |
| 3 | `smc_utils` | Abhaengig von `smc_core_types` (Schritt 1) |
| 4 | `smc_profile_engine` | Abhaengig von `smc_utils` (Schritt 3) + `smc_draw` (Schritt 2) |
| 5 | `smc_context_resolvers` | Abhaengig von `smc_utils` (Schritt 3) + `smc_bus_private` (bereits published) |

---

## Schritt-fuer-Schritt-Runbook

### Voraussetzungen

- TradingView-Account `preuss_steffen` ist eingeloggt
- Browser mit dem persistenten Chromium-Profil unter
  `automation/tradingview/auth/chromium-profile` (oder manuell eingeloggt)
- Repo ist auf `main` ausgecheckt und aktuell

### Schritt 1: `smc_core_types` publishen

**Datei:** `SMC++/smc_core_types.pine`
**Erwarteter Import-Pfad:** `preuss_steffen/smc_core_types/1`
**Abhaengigkeiten:** keine

1. TradingView oeffnen → Pine Editor → neues Script
2. Inhalt von `SMC++/smc_core_types.pine` exakt einfuegen (gesamte Datei)
3. Script speichern unter dem Namen: **`smc_core_types`**
4. Warten bis Compile-Status gruen ist (kein Fehler in der Konsole)
5. Falls Compile-Fehler: STOPP — Fehler dokumentieren und nicht weitermachen
6. Publish: `Publish Script` → `Publish Private Library`
7. Verifizieren:
   - Script-Name in der Editor-Kopfzeile: `smc_core_types`
   - Import-Pfad angezeigt: `preuss_steffen/smc_core_types/1`
   - Version: `1`
8. Screenshot erstellen und speichern als:
   `automation/tradingview/reports/publish-core-types-manual-YYYY-MM-DD.png`

### Schritt 2: `smc_draw` publishen

**Datei:** `SMC++/smc_draw.pine`
**Erwarteter Import-Pfad:** `preuss_steffen/smc_draw/1`
**Abhaengigkeiten:** keine

1. Pine Editor → neues Script
2. Inhalt von `SMC++/smc_draw.pine` exakt einfuegen
3. Script speichern unter dem Namen: **`smc_draw`**
4. Warten bis Compile-Status gruen ist
5. Falls Compile-Fehler: STOPP
6. Publish: `Publish Script` → `Publish Private Library`
7. Verifizieren:
   - Import-Pfad: `preuss_steffen/smc_draw/1`
   - Version: `1`
8. Screenshot speichern als:
   `automation/tradingview/reports/publish-draw-manual-YYYY-MM-DD.png`

### Schritt 3: `smc_utils` publishen

**Datei:** `SMC++/smc_utils.pine`
**Erwarteter Import-Pfad:** `preuss_steffen/smc_utils/1`
**Abhaengigkeiten:** `smc_core_types` (Schritt 1 muss abgeschlossen sein)

1. Pine Editor → neues Script
2. Inhalt von `SMC++/smc_utils.pine` exakt einfuegen
3. Script speichern unter dem Namen: **`smc_utils`**
4. Warten bis Compile-Status gruen ist
5. **Wenn Compile-Fehler `smc_core_types` nicht gefunden:**
   Schritt 1 wurde nicht korrekt abgeschlossen — zurueckgehen
6. Publish: `Publish Script` → `Publish Private Library`
7. Verifizieren:
   - Import-Pfad: `preuss_steffen/smc_utils/1`
   - Version: `1`
8. Screenshot speichern als:
   `automation/tradingview/reports/publish-utils-manual-YYYY-MM-DD.png`

### Schritt 4: `smc_profile_engine` publishen

**Datei:** `SMC++/smc_profile_engine.pine`
**Erwarteter Import-Pfad:** `preuss_steffen/smc_profile_engine/1`
**Abhaengigkeiten:** `smc_utils` (Schritt 3), `smc_draw` (Schritt 2)

1. Pine Editor → neues Script
2. Inhalt von `SMC++/smc_profile_engine.pine` exakt einfuegen
3. Script speichern unter dem Namen: **`smc_profile_engine`**
4. Warten bis Compile-Status gruen ist
5. **Wenn Compile-Fehler `smc_utils` oder `smc_draw` nicht gefunden:**
   Entsprechenden vorherigen Schritt pruefen
6. Publish: `Publish Script` → `Publish Private Library`
7. Verifizieren:
   - Import-Pfad: `preuss_steffen/smc_profile_engine/1`
   - Version: `1`
8. Screenshot speichern als:
   `automation/tradingview/reports/publish-profile-engine-manual-YYYY-MM-DD.png`

### Schritt 5: `smc_context_resolvers` publishen

**Datei:** `SMC++/smc_context_resolvers.pine`
**Erwarteter Import-Pfad:** `preuss_steffen/smc_context_resolvers/1`
**Abhaengigkeiten:** `smc_utils` (Schritt 3), `smc_bus_private` (bereits published)

1. Pine Editor → neues Script
2. Inhalt von `SMC++/smc_context_resolvers.pine` exakt einfuegen
3. Script speichern unter dem Namen: **`smc_context_resolvers`**
4. Warten bis Compile-Status gruen ist
5. **Wenn Compile-Fehler `smc_utils` nicht gefunden:**
   Schritt 3 pruefen
6. **Wenn Compile-Fehler `smc_bus_private` nicht gefunden:**
   Re-Publish von `smc_bus_private` noetig (siehe Abschnitt Re-Publish)
7. Publish: `Publish Script` → `Publish Private Library`
8. Verifizieren:
   - Import-Pfad: `preuss_steffen/smc_context_resolvers/1`
   - Version: `1`
9. Screenshot speichern als:
   `automation/tradingview/reports/publish-context-resolvers-manual-YYYY-MM-DD.png`

---

## Post-Publish-Verification

Nach Abschluss aller 5 Publish-Schritte:

### 1. Core-Engine-Compile-Test

1. Pine Editor → neues Script
2. Inhalt von `SMC_Core_Engine.pine` exakt einfuegen
3. Script speichern
4. Warten bis Compile-Status gruen ist
5. **Erwartet:** Keine Compile-Fehler — alle 9 Import-Pfade aufgeloest

### 2. Dashboard-Binding-Test

1. Core Engine auf einen Chart anwenden
2. `SMC_Dashboard.pine` oeffnen und auf denselben Chart anwenden
3. Dashboard-Inputs auf die Core-Engine-Plots binden (59 Bindungen)
4. Pruefen: Dashboard zeigt korrekte Werte, keine `NaN`-Felder

### 3. Strategy-Binding-Test

1. `SMC_Long_Strategy.pine` oeffnen und auf denselben Chart anwenden
2. Strategy-Inputs auf die Core-Engine-Plots binden (8 Bindungen)
3. Pruefen: Strategy zeigt Execution-Trigger korrekt

### 4. Evidenz sichern

Fuer jede published Library einen JSON-Eintrag erstellen:

```json
{
  "library": "<name>",
  "importPath": "preuss_steffen/<name>/1",
  "publishDate": "YYYY-MM-DD",
  "publishedVersion": 1,
  "publishOk": true,
  "compileOk": true,
  "screenshotPath": "automation/tradingview/reports/publish-<name>-manual-YYYY-MM-DD.png"
}
```

Speichern als:
`automation/tradingview/reports/publish-manual-batch-YYYY-MM-DD.json`

### 5. Dokumentation aktualisieren

- `docs/split_library_compile_readiness.md`: Publish-Spalte auf `yes` setzen
- `docs/tradingview-split-remediation-plan.md`: Close-Out Item 3 auf `closed` setzen

---

## Re-Publish bei Code-Aenderung (Bus, Lifecycle, Observability)

Falls eine bereits published Library seit dem letzten Publish geaendert wurde:

1. In TradingView: existierendes Script oeffnen (NICHT neues Script)
2. Inhalt ersetzen durch die aktuelle Version aus dem Repo
3. Speichern → Compile abwarten
4. `Update Existing Publication` waehlen (NICHT `Publish New`)
5. Version bleibt `/1` — TradingView aktualisiert den Inhalt

Fuer `smc_lifecycle_private` und `smc_observability_private` existieren
automatisierte Publish-Scripts:

```bash
npm run tv:publish-lifecycle-library -- --out automation/tradingview/reports/publish-lifecycle-YYYY-MM-DD.json
npm run tv:publish-observability-library -- --out automation/tradingview/reports/publish-observability-YYYY-MM-DD.json
```

---

## Rollback-Plan

Falls ein Publish fehlschlaegt oder fehlerhafte Daten publiziert werden:

### Compile-Fehler vor Publish

- Kein Rollback noetig — das Script wurde nicht publiziert
- Ursache analysieren: fehlende Abhaengigkeit oder Syntaxfehler
- Vorherigen Schritt pruefen (Abhaengigkeitskette)

### Publish mit fehlerhaftem Inhalt

1. In TradingView das publizierte Script oeffnen
2. Korrekten Inhalt aus dem Repo einfuegen
3. Speichern und `Update Existing Publication`
4. Alle abhaengigen Libraries + Core Engine erneut kompilieren

### Abhaengige Library kompiliert nicht nach Publish

1. Import-Pfad und Version pruefen (`/1` erwartet)
2. TradingView-Cache leeren: neues Browser-Tab oeffnen
3. Script erneut speichern — TradingView laedt Abhaengigkeiten neu

### Worst Case: Library loeschen

1. In TradingView: Script oeffnen → `Manage Publication` → `Unpublish`
2. Alle Consumer (Core Engine, Dashboard, Strategy) muessen dann
   ebenfalls angepasst werden
3. **ACHTUNG:** Unpublish bricht alle bestehenden Import-Referenzen

---

## Nicht im Scope dieses Runbooks

- `smc_micro_profiles_generated` — wird automatisiert ueber
  `scripts/tv_publish_micro_library.ts` verwaltet
- Companion-Overlay-Scripts — diese sind Indicators, keine Libraries
- `SMC_Core_Engine.pine` — ist ein Indicator, keine Library
- `SMC_Dashboard.pine` — ist ein Indicator, keine Library
- `SMC_Long_Strategy.pine` — ist eine Strategy, keine Library
