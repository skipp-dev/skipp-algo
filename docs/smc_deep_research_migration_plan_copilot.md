# SMC-Migrationsplan — Rest-Deltas nach AP1-AP6-Prep (Stand 2026-04-02)

## Ziel dieses Dokuments

Dieses Dokument beschreibt nur noch die **real verbleibenden** Deltas zwischen
dem aktuellen Repo-Stand und `docs/deep-research-report.md`.

Die früheren R1-R6-Arbeitspakete sind nicht mehr offen. Sie wurden in der
aktuellen Repo-Welle bereits umgesetzt und gehören jetzt in die
Regression-/Betriebsphase, nicht mehr in die aktive Migrationsphase.

Relevante Referenzen:

1. `docs/deep-research-report.md`
2. `docs/MEASUREMENT_LANE.md`
3. `docs/PHASE_C_ANALYSIS.md`
4. `smc_integration/service.py`
5. `smc_integration/measurement_evidence.py`
6. `scripts/run_smc_measurement_benchmark.py`
7. `scripts/run_smc_release_gates.py`
8. `scripts/collect_smc_gate_evidence.py`

---

## 1. Geschlossene Deltas

Die folgenden Punkte gelten auf Basis des aktuellen Repo-Stands als geschlossen:

1. **Schema-Drift**: `2.0.0`-Pfad ist konsistent.
2. **Measurement-Artefakte / Evidence-Historie**: persistente Measurement-Lane samt Aggregation ist vorhanden.
3. **Proper Scoring**: BOS, OB, FVG und SWEEP werden im Python-Pfad family-breit bewertet.
4. **Vol-Regime-Forecast**: report-naher Forecast-Pfad mit explizitem Fallback ist vorhanden.
5. **Shadow-Governance**: Measurement-Degradations und Soft-Governance sind im Release-Pfad sichtbar.
6. **Benchmark-Harness**: standardisierter Measurement-/Plot-Lauf mit Manifest existiert.
7. **Ensemble-Quality**: versionierter, nachvollziehbarer Ensemble-Score ist vorhanden.
8. **Signal-Quality-Primacy**: Split-core Pine priorisiert Signal Quality gegenüber älteren Kontext-Summen.
9. **Lean-Namenskanon**: Generator, Artefakte, Pine und Contract-Tests sind auf den kanonischen Feldnamen ausgerichtet.
10. **Ticksize-/Session-aware IDs**: Python-ID-Pfad ist end-to-end gehärtet.
11. **Service-Bundle-Sichtbarkeit**: Bias, Vol-Regime und Measurement sind im Bundle sichtbar und kompakt zusammengefasst.

Diese Themen sollten nicht mehr als offene Migration neu gestartet werden.

---

## 2. Real Verbleibende Deltas

Nach dem aktuellen Stand bleiben nur noch wenige, klar begrenzte Rest-Deltas:

1. **Phase C als nicht-behaviourale Pine-Bereinigung**
   Fokus: declaration-only Inputs, Debug-/Display-Helfer, keine Gate- oder Contract-Arbeit mehr.

2. **Legacy-Parallelpfad `SMC++.pine` explizit einordnen**
   Die Regressionen für `SMC++.pine` laufen weiterhin separat. Es braucht eine klare Entscheidung, ob dieser Pfad aktiv gepflegt, eingefroren oder mittelfristig abgelöst wird.

3. **Konsumenten auf neue Service-Zusammenfassungen ausrichten**
   `measurement_summary` und `market_context` sind jetzt im Service-Bundle sichtbar. Downstream-Konsumenten können diese Felder opportunistisch übernehmen, aber das ist kein architektureller Blocker mehr.

---

## 3. Neue Empfohlene Reihenfolge

Die frühere Reihenfolge R1-R6 ist obsolet. Für den verbleibenden Delta-Rest ist die sinnvollste Reihenfolge jetzt:

1. **C1** – Declaration-only Input-Audit aktualisieren und erst dann entfernen.
2. **C2** – Debug-/Display-Helfer in getrennten, rein visuellen Commits auslagern.
3. **C3** – `SMC++.pine` Governance festlegen (pflegen, einfrieren oder deprecaten).

Kurz gesagt: **erst bereinigen, dann entkoppeln, dann den Legacy-Pfad entscheiden**.

---

## 4. Definition of Done für den Rest-Delta-Plan

Der verbleibende Delta-Rest gilt als geschlossen, wenn folgende Bedingungen gleichzeitig erfüllt sind:

1. Phase C ist auf aktuellem Repo-Stand rebased und nicht mehr auf veraltete Vor-AP1/AP5-Annahmen gestützt.
2. Declaration-only Input-Kandidaten sind frisch auditiert und entweder entfernt oder bewusst behalten.
3. Display-/Debug-Helfer sind getrennt, ohne Runtime-/Lifecycle-Logik zu verschieben.
4. `SMC++.pine` hat einen expliziten Status statt impliziter Parallelpflege.

---

## 5. Copilot-Einsatz ab Jetzt

Wenn Copilot für den verbleibenden Delta-Rest eingesetzt wird, sollte es **nicht** mehr die alten R1-R6-Prompts ausführen. Stattdessen sollte es sich auf diese drei Fragen konzentrieren:

1. Welche Phase-C-Kandidaten sind auf dem heutigen Stand wirklich declaration-only?
2. Welche Pine-Helfer sind nachweislich nur Display-/Debug-Code?
3. Welchen Status soll `SMC++.pine` im Repo künftig haben?

Damit ist der Migrationsplan wieder auf den tatsächlichen Repo-Iststand zurückgesetzt und vermeidet erneute Rework-Schleifen über bereits geschlossene Themen.
