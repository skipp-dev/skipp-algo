# Engineering Program — WP-1

## Pytest-Status-Abgleich: Vollstaendiger Teststatus des SMC-Stacks

### Ziel

Den vollstaendigen Teststatus aller SMC-bezogenen Pytest-Dateien erheben,
dokumentieren und jeden Fehlschlag mit Ursache + naechstem Schritt versehen.
Am Ende steht ein vollstaendiges Status-Bild, das als Grundlage fuer
alle folgenden Arbeitspakete dient.

---

### Harte Regeln

- Arbeite im Repo `skippALGO/skipp-algo`, Branch `main`.
- Fuehre Tests IMMER mit der Projekt-venv aus:
  `/Users/steffenpreuss/.venv/bin/python -m pytest`
- Aendere KEINEN Produktionscode — nur Beobachtung und Dokumentation.
- Aendere KEINE Testdateien — nur lesen und auswerten.
- Erstelle KEINE Pull Requests.
- Wenn ein Test fehlschlaegt, dokumentiere Fehlertyp (AssertionError,
  FileNotFoundError, ImportError, etc.) und betroffene Datei.

---

### Pflichtschritte

1. **Breiter Lauf — alle SMC-Tests:**
   ```bash
   /Users/steffenpreuss/.venv/bin/python -m pytest tests/ -k "smc" --tb=short -q
   ```
   Ergebnis dokumentieren: passed / failed / skipped / errors / warnings.

2. **Einzeldatei-Laeufe fuer jede SMC-Testdatei:**
   Fuer jede Datei unter `tests/test_smc_*.py` einzeln:
   ```bash
   /Users/steffenpreuss/.venv/bin/python -m pytest tests/<datei> -v --tb=short
   ```
   Ergebnis pro Datei dokumentieren.

3. **Pine-Testdateien (nicht-SMC) pruefen:**
   ```bash
   /Users/steffenpreuss/.venv/bin/python -m pytest tests/ -k "pine" --tb=short -q
   ```

4. **TradingView-Testdateien pruefen:**
   ```bash
   /Users/steffenpreuss/.venv/bin/python -m pytest tests/ -k "tradingview" --tb=short -q
   ```

5. **Vollstaendige Test-Suite (ohne Filter):**
   ```bash
   /Users/steffenpreuss/.venv/bin/python -m pytest tests/ --tb=short -q
   ```

6. **Fuer jeden fehlgeschlagenen Test:**
   - Datei + Testname
   - Fehlermeldung (erste 3 Zeilen)
   - Ursache klassifizieren:
     - `MOVED_TO_LIBRARY` — Assertion zeigt auf alte monolithische Position
     - `GOVERNANCE_ANCHOR` — Governance-Test erwartet veralteten Pfad
     - `MISSING_FIXTURE` — Fixture-Datei fehlt oder ist veraltet
     - `IMPORT_ERROR` — Abhaengigkeit fehlt
     - `LOGIC_ERROR` — Echter Testfehler
     - `FLAKE` — Nicht-deterministisch
   - Naechsten Schritt formulieren (z.B. "WP-5 batch-4 Kandidat")

7. **Status-Tabelle erstellen** (Markdown-Tabelle):
   | Testdatei | Tests | Passed | Failed | Skipped | Klassifikation |
   |-----------|-------|--------|--------|---------|----------------|

---

### Stop-Kriterien

- STOPP wenn ein Test laenger als 60 Sekunden laeuft — vermutlich haengt er.
  Dokumentiere ihn als `TIMEOUT` und ueberspringe.
- STOPP wenn mehr als 50 Tests fehlschlagen — das deutet auf ein
  Umgebungsproblem hin. Pruefe zuerst `pip list` und Python-Version.
- STOPP wenn `ImportError` bei Kernmodulen auftritt (z.B. `smc_core`) —
  pruefe ob `pip install -e .` noetig ist.

---

### Ausgabe an mich

1. **Status-Tabelle** — jede Testdatei mit passed/failed/skipped
2. **Fehlerliste** — jeder fehlgeschlagene Test mit Klassifikation
3. **Zusammenfassung** — Gesamtzahlen und Handlungsempfehlung
4. **Abhaengigkeiten zu anderen WPs** — welche Fehler gehoeren zu WP-2 bis WP-5
