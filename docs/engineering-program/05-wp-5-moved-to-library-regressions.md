# Engineering Program — WP-5

## Moved-to-Library-Regressions: Verbleibende Monolith-Assertions migrieren

### Ziel

Alle verbleibenden Testassertions, die noch auf die monolithische
`SMC++.pine`-Struktur verweisen, auf die aktuelle Split-Library-Architektur
(`SMC_Core_Engine.pine` + `SMC++/`-Libraries) umstellen.
Fortfuehrung der Batch-1 bis Batch-3-Arbeit.

---

### Harte Regeln

- Arbeite im Repo `skippALGO/skipp-algo`, Branch `main`.
- WP-1 und WP-4 muessen vorher abgeschlossen sein.
- Aendere NUR Testdateien — KEINEN Produktions-Pine-Code.
- Jede Assertion-Aenderung muss dem Muster folgen:
  1. Verifiziere: Funktion existiert in der Ziel-Split-Library
  2. Verifiziere: Core referenziert sie ueber den korrekten Import-Alias
  3. Erst dann: Assertion umschreiben
- Fuehre nach jeder Datei-Aenderung den betroffenen Test einzeln aus.
- Erstelle EINEN Commit pro Testdatei (nicht pro Assertion).

---

### Pflichtschritte

1. **Kandidaten identifizieren:**
   Suche in allen Testdateien nach Verweisen auf monolithische Positionen:
   ```bash
   grep -rn "SMC++\.pine" tests/ | grep -v "__pycache__"
   grep -rn "SMC_PATH.*SMC\+\+" tests/ | grep -v "__pycache__"
   ```
   Jeder Treffer ist ein potenzieller Migrations-Kandidat.

2. **Ausnahmen dokumentieren:**
   Folgende Verweise auf `SMC++.pine` sind KORREKT und duerfen NICHT
   migriert werden:
   - `tests/test_smc_legacy_governance.py` — Governance-Anker (WP-4)
   - Fixture-Dateien unter `tests/fixtures/`
   - Kommentare die historischen Kontext dokumentieren

3. **Fuer jeden Migrations-Kandidaten:**

   a) Finde die Funktion/das Muster das getestet wird.

   b) Lokalisiere es in der Split-Library:
   ```bash
   grep -n "<funktionsname>" SMC++/smc_context_resolvers.pine
   grep -n "<funktionsname>" SMC++/smc_utils.pine
   grep -n "<funktionsname>" SMC++/smc_profile_engine.pine
   grep -n "<funktionsname>" SMC++/smc_observability_private.pine
   grep -n "<funktionsname>" SMC++/smc_lifecycle_private.pine
   grep -n "<funktionsname>" SMC++/smc_bus_private.pine
   ```

   c) Verifiziere den Core-Aufruf:
   ```bash
   grep -n "<alias>\.<funktionsname>" SMC_Core_Engine.pine
   ```

   d) Schreibe die Assertion um:
   - ALT: `assert "<funktionsname>" in smc_source`
   - NEU: `assert "<funktionsname>" in library_source` UND
          `assert "<alias>.<funktionsname>" in core_source`

4. **Bekannte Migrationsmuster (aus Batch-3):**

   | Altes Muster | Neues Muster | Ziel-Library |
   |-------------|-------------|--------------|
   | `compose_long_*_alert_detail` inline | `cr.compose_long_*_alert_detail(...)` | `smc_context_resolvers` |
   | `normalize_profile_*` inline | `pe.normalize_profile_*` | `smc_profile_engine` |
   | `smc_lib_*` inline | `u.smc_lib_*` | `smc_utils` |
   | `emit_long_engine_debug_logs` inline | `obv.emit_long_engine_debug_logs(...)` | `smc_observability_private` |
   | `resolve_long_ready_signal_state` inline | `obv.resolve_long_ready_signal_state(...)` | `smc_observability_private` |

5. **Test-Lauf nach jeder Datei:**
   ```bash
   /Users/steffenpreuss/.venv/bin/python -m pytest tests/<geaenderte_datei> -v --tb=short
   ```

6. **Abschluss-Lauf:**
   ```bash
   /Users/steffenpreuss/.venv/bin/python -m pytest tests/ -k "smc" --tb=line -q
   ```
   Ergebnis dokumentieren und mit WP-1-Baseline vergleichen.

7. **Dokumentation aktualisieren:**
   `docs/regression_triage_packs.md` mit Batch-4/5-Ergebnissen ergaenzen.

---

### Stop-Kriterien

- STOPP wenn eine Funktion weder im Core noch in einer Split-Library
  gefunden wird — das ist ein geloeschtes Feature. Dokumentiere es als
  `DELETED_FEATURE` und entferne den Test NICHT ohne Rueckfrage.
- STOPP wenn eine Assertion-Migration einen vorher gruenen Test rot macht —
  Rollback und Ursache analysieren bevor du weitermachst.
- STOPP wenn mehr als 5 Tests nach Migration fehlschlagen —
  die Migration ist zu breit und muss in kleinere Batches aufgeteilt werden.
- STOPP wenn ein Test beide Quellen prueft (Monolith UND Split) —
  das ist ein Uebergangstest der bewusst so geschrieben wurde.
  Nicht aendern ohne Rueckfrage.

---

### Ausgabe an mich

1. **Migrations-Tabelle** — jeder migrierte Test mit alter und neuer Assertion
2. **Ausnahmen** — Tests die bewusst NICHT migriert wurden mit Begruendung
3. **Test-Snapshot vorher/nachher** — Delta zwischen WP-1-Baseline und WP-5-Ergebnis
4. **Commits** — Liste der erstellten Commits mit Hash und Message
5. **Verbleibende Monolith-Referenzen** — was noch uebrig ist und warum
6. **Empfehlung** — ob ein Batch-6 noetig ist oder die Migration abgeschlossen ist
