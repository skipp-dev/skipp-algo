# Engineering Program — WP-2

## Context-Resolvers-Exports: Split-Library-Export-Vertrag absichern

### Ziel

Sicherstellen, dass alle Split-Library-Exporte (`smc_context_resolvers.pine`,
`smc_utils.pine`, `smc_profile_engine.pine`, `smc_observability_private.pine`,
`smc_lifecycle_private.pine`, `smc_bus_private.pine`) korrekt deklariert sind,
vom Core-Engine ueber die richtigen Import-Aliase referenziert werden und
keine verwaisten oder fehlenden Exporte existieren.

---

### Harte Regeln

- Arbeite im Repo `skippALGO/skipp-algo`, Branch `main`.
- Aendere KEINEN Code in diesem WP — nur Analyse und Dokumentation.
- Pruefe jeden Export gegen den tatsaechlichen Aufruf im Core.
- Beachte die kanonischen Import-Aliase:
  - `cr` = `smc_context_resolvers`
  - `u` = `smc_utils`
  - `pe` = `smc_profile_engine`
  - `obv` = `smc_observability_private`
  - `ll` = `smc_lifecycle_private`
  - `bp` = `smc_bus_private`
  - `ct` = `smc_core_types`
  - `d` = `smc_draw`
  - `mp` = `smc_micro_profiles_generated`
- Die Export-Surface-Dokumentation liegt in `pine_input_surface.py` —
  diese als Referenz verwenden, aber den Pine-Source als Wahrheit behandeln.

---

### Pflichtschritte

1. **Export-Inventar je Library erstellen:**
   Fuer jede der 6 Split-Libraries:
   ```bash
   grep -n "^export " SMC++/<library>.pine | head -100
   ```
   Jeden `export function`, `export method`, `export type`, `export const`
   in eine Liste aufnehmen.

2. **Aufruf-Inventar im Core erstellen:**
   Fuer jeden Import-Alias (`cr.`, `u.`, `pe.`, `obv.`, `ll.`, `bp.`):
   ```bash
   grep -n "<alias>\." SMC_Core_Engine.pine | head -100
   ```
   Jeden Aufruf in eine Liste aufnehmen.

3. **Abgleich: Export vs. Aufruf:**
   - Exportiert aber nie aufgerufen → `UNUSED_EXPORT`
   - Aufgerufen aber nicht exportiert → `MISSING_EXPORT` (Kompilierfehler)
   - Exportiert und aufgerufen → `OK`

4. **Consumer-Abgleich (Dashboard + Strategy):**
   Pruefe ob `SMC_Dashboard.pine` und `SMC_Long_Strategy.pine` Exporte
   ueber BUS-Plots konsumieren, die in der Library definiert sind:
   ```bash
   grep -n "input.source" SMC_Dashboard.pine | head -50
   grep -n "input.source" SMC_Long_Strategy.pine | head -50
   ```

5. **Testabdeckung pruefen:**
   Fuer jeden Export: existiert ein Test in `tests/test_smc_core_engine_split.py`
   oder `tests/test_smc_long_dip_regressions.py`, der diesen Export verifiziert?
   Fehlende Test-Abdeckung als `UNTESTED_EXPORT` markieren.

6. **Ergebnis-Tabelle:**
   | Library | Export-Name | Typ | Core-Alias-Aufruf | Status | Test-Abdeckung |
   |---------|-----------|-----|-------------------|--------|----------------|

---

### Stop-Kriterien

- STOPP wenn eine Library-Datei nicht existiert — dokumentiere welche fehlt.
- STOPP wenn der Core-Engine mehr als 3 `MISSING_EXPORT`-Eintraege hat —
  das deutet auf einen unvollstaendigen Library-Split hin, der zuerst
  behoben werden muss.
- STOPP wenn `pine_input_surface.py` und die Pine-Sources mehr als
  10 Abweichungen zeigen — dann ist die Surface-Dokumentation veraltet
  und muss zuerst aktualisiert werden.

---

### Ausgabe an mich

1. **Export-Tabelle** — vollstaendige Liste aller Exporte je Library mit Status
2. **Fehlerliste** — alle `UNUSED_EXPORT`, `MISSING_EXPORT`, `UNTESTED_EXPORT`
3. **Consumer-Matrix** — welche BUS-Exporte werden von Dashboard/Strategy konsumiert
4. **Handlungsempfehlung** — welche Exporte sollten entfernt, hinzugefuegt oder getestet werden
5. **Abhaengigkeiten** — welche Findings beeinflussen WP-3 (TradingView Compile) oder WP-5 (Regressions)
