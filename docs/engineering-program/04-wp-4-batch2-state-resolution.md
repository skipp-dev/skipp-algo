# Engineering Program — WP-4

## Batch-2-State-Resolution: Offene Governance- und Architektur-Konflikte loesen

### Ziel

Alle offenen State-Konflikte aus Batch-2 und Batch-3 der Regression-Triage
aufloesen. Insbesondere den Legacy-Governance-Anker (`SMC++.pine` vs.
`SMC_Core_Engine.pine`) und verbleibende Architektur-Diskrepanzen zwischen
Testerwartungen und tatsaechlicher Code-Struktur beheben.

---

### Harte Regeln

- Arbeite im Repo `skippALGO/skipp-algo`, Branch `main`.
- WP-1 muss vorher abgeschlossen sein (Teststatus bekannt).
- Aendere Tests UND Dokumentation — aber KEINEN Produktions-Pine-Code.
- Jede Aenderung muss einzeln committet werden mit aussagekraeftiger Message.
- Fuehre nach jeder Aenderung den betroffenen Test einzeln aus.
- Pushe NICHT direkt auf main — erstelle einen eigenen Branch.

---

### Pflichtschritte

1. **Legacy-Governance-Anker aufloesen:**

   Der fehlschlagende Test:
   ```
   tests/test_smc_legacy_governance.py::test_long_dip_regression_stays_anchored_to_smc_plus
   ```
   Erwartet: `SMC_PATH = ROOT / 'legacy' / 'SMC++.pine'`
   Ist-Zustand: `SMC_PATH = ROOT / 'SMC_Core_Engine.pine'`

   Entscheide:
   - Option A: Test anpassen auf `SMC_Core_Engine.pine` (empfohlen —
     der Core Engine ist der aktive Producer, SMC++.pine ist eingefroren)
   - Option B: `SMC++.pine` nach `legacy/SMC++.pine` verschieben und
     den Test beibehalten
   - Dokumentiere die Entscheidung in `docs/regression_triage_packs.md`

2. **Phase-C-Audit-Status pruefen:**
   ```bash
   /Users/steffenpreuss/.venv/bin/python -m pytest tests/test_smc_core_engine_phase_c_audit.py -v --tb=short
   ```
   Wenn Tests fehlschlagen: Sind die entfernten Inputs (`show_mtf_trend`,
   `show_risk_levels`, etc.) wieder aufgetaucht? Falls ja — das ist ein
   Regressionsbruch der sofort behoben werden muss.

3. **Semantic-Contract-Tests pruefen:**
   ```bash
   /Users/steffenpreuss/.venv/bin/python -m pytest tests/test_smc_core_engine_semantic_contract.py -v --tb=short
   ```
   Diese Tests pruefen Lifecycle-Reihenfolge und State-Label-Alignment.
   Fehler hier deuten auf Core-Engine-Aenderungen hin, die nicht
   mit dem Dashboard synchronisiert wurden.

4. **Bridge-Regression pruefen:**
   ```bash
   /Users/steffenpreuss/.venv/bin/python -m pytest tests/test_smc_bridge_regression.py -v --tb=short
   ```

5. **Parity-Tests pruefen:**
   ```bash
   /Users/steffenpreuss/.venv/bin/python -m pytest tests/test_smc_parity.py -v --tb=short
   ```
   Diese Tests pruefen Structure ↔ Bridge Snapshot ↔ TV Pine Payload.

6. **Version-Governance pruefen:**
   ```bash
   /Users/steffenpreuss/.venv/bin/python -m pytest tests/test_smc_version_governance.py -v --tb=short
   ```

7. **Dokumentation aktualisieren:**
   - `docs/regression_triage_packs.md` mit Batch-4-Ergebnissen
   - Entscheidungsprotokoll fuer Legacy-Governance-Anker

8. **Abschluss-Lauf:**
   ```bash
   /Users/steffenpreuss/.venv/bin/python -m pytest tests/ -k "smc" --tb=line -q
   ```
   Ziel: 0 failed (ausgenommen bewusst uebersprungene Tests).

---

### Stop-Kriterien

- STOPP wenn der Legacy-Governance-Anker nicht eindeutig entschieden
  werden kann — eskaliere mit beiden Optionen und Vor-/Nachteilen.
- STOPP wenn Phase-C-entfernte Inputs wieder aufgetaucht sind —
  das ist ein manueller Revert der zuerst geklaert werden muss.
- STOPP wenn Semantic-Contract-Tests fehlschlagen und die Ursache
  eine Core-Engine-Aenderung ist — das erfordert Pine-Code-Aenderungen
  die nicht in diesem WP erlaubt sind.
- STOPP wenn mehr als 3 neue Fehler seit WP-1 aufgetreten sind —
  das deutet auf eine instabile Codebasis hin.

---

### Ausgabe an mich

1. **Entscheidung Legacy-Governance** — gewaehlte Option mit Begruendung
2. **Test-Delta** — Vergleich WP-1-Status vs. WP-4-Status (was ist jetzt gruen?)
3. **Verbleibende Fehler** — Liste mit Klassifikation und naechstem Schritt
4. **Commits** — Liste der erstellten Commits mit Hash und Message
5. **Abschluss-Pytest-Snapshot** — passed/failed/skipped/errors
