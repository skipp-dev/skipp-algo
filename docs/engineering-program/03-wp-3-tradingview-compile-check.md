# Engineering Program — WP-3

## TradingView-Compile-Check: Pine-Kompilierbarkeit aller Scripts verifizieren

### Ziel

Sicherstellen, dass alle Pine-Scripts im Repo (`*.pine`) syntaktisch und
semantisch korrekt sind und in TradingView ohne Fehler kompilieren wuerden.
Da Pine keinen lokalen Compiler hat, wird die Pruefung ueber statische
Analyse, Strukturchecks und bekannte Fehlermuster durchgefuehrt.

---

### Harte Regeln

- Arbeite im Repo `skippALGO/skipp-algo`, Branch `main`.
- Aendere KEINEN Pine-Code — nur Analyse und Dokumentation.
- Pine v6 ist die Zielversion (`//@version=6`).
- Library-Dateien unter `SMC++/` muessen `library(...)` als Header haben.
- Indicator-Dateien muessen `indicator(...)` als Header haben.
- Strategy-Dateien muessen `strategy(...)` als Header haben.
- Import-Statements muessen auf publizierte Libraries verweisen:
  `import preuss_steffen/<library>/<version> as <alias>`
- Lokale `SMC++/`-Dateien sind Private Libraries (nicht publiziert auf
  TradingView) — sie werden ueber den TradingView-Editor lokal eingebunden.

---

### Pflichtschritte

1. **Inventar aller Pine-Dateien:**
   ```bash
   find . -name "*.pine" -not -path "./tests/*" | sort
   ```
   Jede Datei mit Typ klassifizieren: `indicator`, `strategy`, `library`.

2. **Version-Check:**
   ```bash
   grep -L "//@version=6" *.pine SMC++/*.pine
   ```
   Dateien ohne `@version=6` sind entweder v5 oder fehlerhaft.

3. **Import-Validierung:**
   Fuer jede Datei mit `import`-Statements:
   - Pruefe ob der Alias im Code verwendet wird (nicht importiert und unbenutzt).
   - Pruefe ob die importierte Library existiert:
     - `preuss_steffen/*` = publizierte TradingView-Library
     - Lokale `SMC++/*` = Private Library im Repo

4. **Bekannte Fehlermuster pruefen:**
   - `plotchar(..., char = <mehrzeiliger_string>)` — char erwartet 1 Zeichen
     (Finding F12 aus dem Pine Review)
   - `varip` Variablen ohne `barstate.isnew` Reset-Guard
   - Funktionen mit mehr als 40 Parametern (Finding F10)
   - `str.contains()` mit Leerstring als Fallback
   - `array.size()` auf `na` Array ohne Null-Check

5. **Companion-Overlay-Konsistenz:**
   Alle 9 Companion-Overlays pruefen:
   - Importieren sie dieselbe Library-Version wie der Core?
   - Verwenden sie `mp.ASOF_DATE` fuer Staleness? (Finding F8)
   - Haben sie korrekten `indicator()`-Header?

6. **BUS-Plot-Konsistenz (Core ↔ Dashboard):**
   - Zaehle BUS-Plots im Core (`display = display.none`).
   - Zaehle `input.source()`-Bindungen im Dashboard.
   - Pruefe ob `BUS SchemaVersion` existiert (Finding F9).

7. **Ergebnis-Tabelle:**
   | Datei | Typ | Version | Imports OK | Bekannte Muster | Status |
   |-------|-----|---------|------------|-----------------|--------|

---

### Stop-Kriterien

- STOPP wenn eine Pine-Datei keinen gueltigen Header hat (`indicator`,
  `strategy`, `library`) — das ist ein struktureller Fehler, dokumentiere ihn.
- STOPP wenn mehr als 5 Dateien `@version=5` verwenden — das deutet auf
  ein grossflaechiges Migrationsproblem hin.
- STOPP wenn Import-Aliase im Code verwendet werden, die keinem
  Import-Statement entsprechen — das ist ein harter Kompilierfehler.

---

### Ausgabe an mich

1. **Datei-Inventar** — alle Pine-Dateien mit Typ, Version, Status
2. **Import-Matrix** — welche Datei importiert welche Library mit welchem Alias
3. **Fehlermuster-Treffer** — alle gefundenen bekannten Fehlermuster mit Datei + Zeile
4. **BUS-Konsistenz** — Anzahl BUS-Plots vs. Dashboard-Bindungen, Schema-Version-Status
5. **Kompilier-Risiko-Bewertung** — Ampel (gruen/gelb/rot) pro Datei
6. **Abhaengigkeiten** — welche Findings blockieren WP-4 oder WP-5
