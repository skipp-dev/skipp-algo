# SMC-Migrationsplan — Rest-Deltas nach der v5.5b-Umsetzungswelle

**Status**: Supporting planning note  
**Date**: 2026-04-02  
**Canonical references**: [v5_5b_architecture.md](v5_5b_architecture.md), [v5_5_lean_contract.md](v5_5_lean_contract.md), [MEASUREMENT_LANE.md](MEASUREMENT_LANE.md), [PHASE_C_ANALYSIS.md](PHASE_C_ANALYSIS.md)

## Ziel dieses Dokuments

Dieses Dokument ist **keine** kanonische Architekturquelle. Es beschreibt nur
noch die **real verbleibenden** Deltas zwischen dem aktuellen Repo-Stand und
`docs/deep-research-report.md`.

Die früheren R1-R6-Arbeitspakete sind nicht mehr offen. Sie wurden in der
aktuellen Repo-Welle bereits umgesetzt und gehören jetzt in die
Regression-/Betriebsphase, nicht mehr in die aktive Migrationsphase.

Relevante Referenzen:

1. [deep-research-report.md](deep-research-report.md)
2. [MEASUREMENT_LANE.md](MEASUREMENT_LANE.md)
3. [PHASE_C_ANALYSIS.md](PHASE_C_ANALYSIS.md)
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
12. **Phase C C1**: deklarationslose Visual-/Debug-Inputs des Split-Cores sind entfernt und per Audit-Test abgesichert.
13. **Phase C C2 erster Slice**: Alert-Suffixe, Debug-Event-Payload-Auflösung, Event-Risk-State-Mapping, Mini-Health-Badge-Formatierung, Debug-Summary-/Header-/Event-Prefix-Komposition sowie interne Alert-Score-/Strict-/Environment-/Micro-Suffix-, Freshness-, Zonen-/Zone-Branch-/Zone-Summary-Display-, Debug-Modul-/Debug-Modul-Display-, Source-/Source-Text-/Primary-Source-/Source-Display-/Source-Transition-, Source-State-, Blocker-Status-/Ready-Blocker-Display-/Strict-Blocker-Display-, Invalidation-Reason-, Last-Invalid-Reason-, Upgrade-Reason-, Pipe-/Newline-Debug-Segment-, Engine-Debug-Label-Display-/Engine-Event-Log-Display-, enable-gesteuerte Debug-Modul- sowie Setup-/Setup-Display-/Visual-State-Code- und Full-Mode-Debug-Label-/Event-State-Textbausteine und Setup-/Visual-State-Textbausteine samt Environment-Focus-Display sind in visuelle Helfer extrahiert und per Split-Core-Test fixiert; die triviale `resolve_long_visual_text`-Alias-Huelle ist zusaetzlich als reine Buchhaltungsbereinigung entfernt.

Diese Themen sollten nicht mehr als offene Migration neu gestartet werden.

---

## 2. C3-Paket auf aktuellem Repo-Stand

Nach dem aktuellen Stand ist der verbleibende Arbeitsrest kein offener
Migrationsnebel mehr, sondern ein klar begrenztes C3-Paket:

1. **Legacy-Parallelpfad `SMC++.pine` ist eingefroren**
   `SMC++.pine` ist ab jetzt der eingefrorene Kompatibilitaetspfad.
   Es gibt dort keine neue Feature- oder Produktlogik mehr. Zulaessig bleiben
   nur Compile-/Runtime-Fixes, Regressionserhalt und explizit dokumentierte
   Kompatibilitaetskorrekturen.

2. **Semantische Split-Core-Verifikation wird erweitert**
   Die bisherigen Split-Core-Guards bleiben erhalten, werden aber um
   semantische Vertragspruefungen fuer StateCode, BUS-Row-Codes,
   Lifecycle-Ableitungen und zentrale Alert-Gates ergaenzt.

3. **Der aktive Core bekommt Input-Surface-Governance**
   `SMC_Core_Engine.pine` wird auf dieselbe sichtbare Operator-Surface
   gebracht wie die anderen grossen Pine-Skripte: gruppiert, bewusst kuratiert,
   klar zwischen Core- und Expert-Controls getrennt.

4. **Consumer-Setup in TradingView wird geordnet**
   Dashboard und Strategy bleiben BUS-only, bekommen aber eine stabilere
   Bindungsordnung, gruppierte `input.source()`-Sektionen und eine klarere
   manuelle Setup-Konvention.

5. **Die naechsten Extraktionen betreffen State-Owner**
   Weitere Arbeit im Core zielt nicht mehr auf Debug-/Display-Shells, sondern
   auf klar abgrenzbare Lifecycle-Teile und runtime-nahe Zustandsbesitzer.
   Der erste umgesetzte Schnitt in diesem Paket ist
   `compute_long_freshness_state(...)` fuer Armed-/Confirmed-Age und die daran
   haengenden Freshness-Gates.

6. **Produktgrenze wird explizit festgeschrieben**
   `SMC_Core_Engine.pine` bleibt Long-Dip-first. Short-Paritaet ist kein stilles
   Versprechen dieses C3-Pakets, sondern ein separater Folge-Track.

---

## 3. Verbindliche Reihenfolge

Die fruehere Reihenfolge R1-R6 ist obsolet. Fuer den verbleibenden Rest gilt
jetzt diese Reihenfolge:

1. **C3.1 Freeze-Policy** – `SMC++.pine` als eingefrorenen Kompatibilitaetspfad festschreiben.
2. **C3.2 Semantic Contracts** – aktive Split-Core-Vertraege ueber reine Strukturtests hinaus absichern.
3. **C3.3 Core Surface** – sichtbare Input-Surface des aktiven Cores auf ~30-40 Operator-Controls begrenzen.
4. **C3.4 Consumer Setup** – BUS-Consumer fuer Dashboard und Strategy gruppieren, ordnen und dokumentieren.
5. **C3.5 State-Owner Split** – naechste Pine-Extraktionen nur an echten Lifecycle-/State-Owner-Schnitten.
6. **C3.6 Product Scope** – Long-Dip-first-Scope explizit festhalten; Short-Paritaet separat planen.

Kurz gesagt: **erst Governance fixieren, dann Vertrage haerten, dann den aktiven
Core und seine Consumer sauberer machen**.

---

## 4. Definition of Done fuer das C3-Paket

Das C3-Paket gilt als geschlossen, wenn folgende Bedingungen gleichzeitig
erfuellt sind:

1. `SMC++.pine` hat genau einen dokumentierten Status: eingefrorener Kompatibilitaetspfad.
2. Release-Gates und Tests spiegeln diese Freeze-Policy explizit wider.
3. Split-Core-Tests sichern BUS-Surface, StateCodes, Ready-/Strict-Reason-Codes und Alert-Gates semantisch ab.
4. `SMC_Core_Engine.pine` erfuellt dieselbe Input-Surface-Governance wie die anderen grossen Pine-Skripte.
5. Dashboard- und Strategy-Consumer sind gruppiert und in stabiler Bindereihenfolge dokumentiert.
6. Mindestens ein weiterer C3-Schnitt extrahiert echte Lifecycle-/State-Owner-Logik statt nur Display-/Debug-Code. Der erste davon ist `compute_long_freshness_state(...)`.
7. Long-Dip-first ist als Produktgrenze dokumentiert; Short-Paritaet bleibt ein expliziter Folge-Track.

---

## 5. C4-Paket auf aktuellem Repo-Stand

Das naechste Paket ist jetzt kein weiterer Surface-Cleanup mehr, sondern ein
gezieltes C4-Hardening des aktiven Cores und seines TradingView-Vertrags:

1. **Ready-/Strict-Contracts haben zentrale Reason-Code-Owner**
   Ready- und Strict-Blocker, BUS-Reason-Codes und Dashboard-Decoder folgen
   derselben semantischen Reihenfolge. Der Strict-Contract codiert jetzt auch
   Signal-Quality explizit im BUS-Pfad.

2. **Source-Upgrade, Source-Runtime und Invalidation sind weiter entkoppelt**
   Der aktive Core besitzt eigene Helper fuer Source-Upgrade-Entscheidungen,
   Locked-Source-Runtime-Zustand und die Invalidationspraezedenz.

3. **Die BUS-Publication-Layer ist als eigene Composite-Schicht lesbar**
   Composite-Packs wie `MetaPack`, `HardGatesPackA/B`, `ModulePackA-D`,
   `EnginePack` und `LeanPackA/B` werden ueber eigene Helper gebaut statt direkt
   inline im Plot-Block zusammengesetzt.

4. **Dashboard, Strategy und Runbook haengen an einem kanonischen BUS-Manifest**
   `scripts/smc_bus_manifest.py` ist die aktive Repo-Quelle fuer Channel-Namen,
   Consumer-Reihenfolge, Gruppen und den manuellen TradingView-Pfad.

5. **Die aktive Operator-Surface bleibt Long-Dip-first und preset-zentriert**
   `SMC_Core_Engine.pine` haelt `long_user_preset` und `compact_mode` bewusst
   als sichtbare Surface-Anker. Neue sichtbare Controls sollen nur dann
   hinzukommen, wenn sie nicht in diese beiden Operator-Ebenen passen.

---

## 6. Copilot-Einsatz ab Jetzt

Wenn Copilot fuer den verbleibenden Rest eingesetzt wird, sollte es **nicht**
mehr die alten R1-R6-Prompts oder die fruehen C3-Surface-Schleifen ausfuehren.
Stattdessen sollte es sich auf diese fuenf Fragen konzentrieren:

1. Welche Ready-/Strict-Reason-Codes oder Dashboard-Decodes des aktiven Cores sind noch nicht zentral genug verankert?
2. Welche Locked-Source- und Invalidationszustandsbesitzer leben noch im Main Body statt in eigenen Helpern?
3. Welche BUS-Packs koennen weiter von Runtime-Logik und Plot-Publikation entkoppelt werden?
4. Wo droht noch Drift zwischen `scripts/smc_bus_manifest.py`, den Consumern und dem TradingView-Runbook?
5. Welche sichtbaren Operator-Controls gehoeren wirklich auf die aktive Surface, und welche muessen hinter `long_user_preset` oder `compact_mode` verschwinden?

Damit ist der Migrationsplan auf den tatsaechlichen Repo-Iststand zurueckgesetzt
und verhindert, dass Phase C erneut in rein kosmetische Rework-Schleifen kippt.
