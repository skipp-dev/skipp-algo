# SMC-Migrationsplan — Rest-Deltas nach der v5.5b-Umsetzungswelle

**Status**: Supporting planning note  
**Date**: 2026-04-02  
**Canonical references**: [v5_5b_architecture.md](v5_5b_architecture.md), [v5_5_lean_contract.md](v5_5_lean_contract.md), [MEASUREMENT_LANE.md](MEASUREMENT_LANE.md), [PHASE_C_ANALYSIS.md](PHASE_C_ANALYSIS.md), [smc-lite-pro-product-cut.md](smc-lite-pro-product-cut.md)

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
   Composite-Packs und direkte Row-Exports wie `MetaPack`,
   `SdConfluenceRow`, `SdOscRow`, `VolRegimeRow`, `VolSqueezeRow`, die
   expliziten Diagnostic-Support-Codes, die restliche Engine-Row-Surface und
   `LeanPackA/B` werden ueber eigene Helper gebaut statt direkt inline im
   Plot-Block zusammengesetzt.

4. **Dashboard, Strategy und Runbook haengen an einem kanonischen BUS-Manifest**
   `scripts/smc_bus_manifest.py` ist die aktive Repo-Quelle fuer Channel-Namen,
   Consumer-Reihenfolge, Gruppen und den manuellen TradingView-Pfad. Das
   Manifest traegt jetzt auch den Executable-, Lite- und Pro-only-Schnitt als
   kanonische Produktgrenze.

5. **Die aktive Operator-Surface bleibt Long-Dip-first und preset-zentriert**
   `SMC_Core_Engine.pine` haelt `long_user_preset` und `compact_mode` bewusst
   als sichtbare Surface-Anker. Neue sichtbare Controls sollen nur dann
   hinzukommen, wenn sie nicht in diese beiden Operator-Ebenen passen.

## 6. C5-Paket auf aktuellem Repo-Stand

Das naechste ausgefuehrte Paket zieht den naechsten echten Lifecycle-Owner-
Schnitt im aktiven Core:

1. **Armed-Source-Auswahl und Armed-Prequality sind eigene Owner**
   `resolve_long_arm_source_state(...)`,
   `compute_long_arm_prequality_ok(...)` und
   `compute_long_arm_should_trigger(...)` kapseln Source-Auswahl,
   Vorqualitaet und den eigentlichen Armed-Trigger.

2. **Der Armed-Payload fuer `long_state.arm(...)` wird separat gebaut**
   `resolve_long_arm_transition_payload(...)` bereitet Touch-Count,
   Locked-Source-ID, Bounds und Last-Touch-Zeitpunkt vor statt diese Daten
   inline im Main Body aufzuloesen.

3. **Confirm-Break, Confirm-Structure und Confirm-Transition sind getrennte Owner**
   `resolve_long_confirm_break_state(...)`,
   `resolve_long_confirm_structure_state(...)` und
   `compute_long_confirm_transition_state(...)` halten den Armed-zu-Confirm-
   Uebergang zusammen, ohne ihn weiter im Lifecycle-Block zu verstreuen.

4. **Der Main Body kommittet an dieser Stelle nur noch State-Uebergaenge**
   Im Lifecycle-Block bleiben fuer diesen Schnitt im Wesentlichen nur noch
   `long_state.arm(...)` und `long_state.confirm(...)` als eigentliche
   Commit-Punkte uebrig.

5. **Split-Core- und Semantic-Contracts pinnen die neue Owner-Grenze**
   Die aktive Regression prueft jetzt explizit auf Arm-/Confirm-Helper,
   deren Call-Sites und die semantischen Bedingungen innerhalb dieser Helper.

---

## 7. C6-Paket auf aktuellem Repo-Stand

Das naechste ausgefuehrte Paket zieht den Lifecycle-Owner-Schnitt fuer Plan,
Overhead und Risk-Plan-Projektion:

1. **Plan-Aktivierung ist eigener Owner**
   `compute_long_plan_state(...)` besitzt jetzt die Aktivierungsbedingung fuer
   `long_plan_active`, statt dass diese weiter als lose Inline-Bedingung im
   Main Body verbleibt.

2. **Overhead-Kontext ist als eigener Runtime-Owner extrahiert**
   `compute_long_overhead_context(...)` kapselt den geplanten Stop, die
   geplante R-Distanz, den Bear-Overhead-Scan und die daraus abgeleitete
   Headroom-/Overhead-Gate-Entscheidung.

3. **Risk-Plan-Projektion ist eigener Owner**
   `compute_long_risk_plan_state(...)` projiziert den aktiven Plan in BUS-nahe
   Stop-, Risk- und Target-Werte statt diese Werte inline aus dem Main Body zu
   berechnen.

4. **Der Main Body konsumiert nur noch die Plan-/Overhead-/Risk-Owner**
   Der lokale `compute_overhead_context()`-Block ist entfernt; der Lifecycle-
   Block bindet jetzt nur noch die extrahierten Owner an den aktiven Zustand.

5. **Die aktive Regression pinnt den neuen C6-Schnitt explizit**
   Split-Core- und Semantic-Contracts sichern jetzt sowohl die neuen Signaturen
   als auch die entscheidenden Overhead-/Risk-Formeln und Call-Sites ab.

---

## 8. C7-Paket auf aktuellem Repo-Stand

Das naechste ausgefuehrte Paket zieht den naechsten Runtime-/BUS-Schnitt im
aktiven Core:

1. **Ready-/Best-/Strict-Projektion ist als eigene Runtime-Grenze gebuendelt**
   `resolve_long_ready_projection_state(...)` und
   `resolve_long_entry_projection_state(...)` besitzen jetzt die Projektion von
   Lifecycle- und Gate-State in die aktiven Execution-Tiers.

2. **Blocker- und Clean-Tier-Ableitung leben in eigenen Projection-Ownern**
   `resolve_long_execution_blocker_state(...)` und
   `resolve_long_clean_tier(...)` halten Ready-/Strict-Blocker sowie das Clean-
   Tier aus dem Main Body heraus.

3. **Die BUS-Plan-Publish-Grenze ist jetzt explizit**
   `resolve_long_bus_plan_levels(...)` besitzt die Runtime-zu-BUS-Uebergabe fuer
   Trigger, Invalidation, Stop und Targets, statt rohe Runtime-Werte direkt zu
   plotten.

4. **Trigger-, Risk-Plan- und Debug-Flag-Ownership sind jetzt sauber vom
   Executable Core getrennt**
   `Long Triggers`, `Risk Plan`, `Debug Flags` und die daraus abgeleitete
   `Long Debug`-Zeile werden auf dem aktuellen Repo-Stand im Dashboard lokal
   rekonstruiert, statt ueber verbleibende BUS-Transportreihen zu laufen.

5. **Die aktive Regression pinnt den C7-Schnitt explizit**
   Split-Core- und Semantic-Contracts sichern jetzt die neue Execution-
   Projektion und die BUS-Publish-Boundary gegen Rueckfall in Inline-Logik ab.

---

## 9. C8-Paket auf aktuellem Repo-Stand

Der naechste ausgefuehrte Schnitt zieht die verbleibende Event- und
Observability-Grenze aus dem Runtime-Pfad:

1. **Der Ready-Edge besitzt jetzt einen eigenen Runtime-Owner**
   `resolve_long_ready_signal_state(...)` haelt die intrabar `varip`-Latch-
   Semantik fuer den ersten Ready-Uebergang einer Bar zusammen, statt diese
   Inline-Mutation im Main Body zu lassen.

2. **Lifecycle-Debug-Events besitzen jetzt einen eigenen Observability-Owner**
   `emit_long_engine_debug_logs(...)` haelt Summary-Text und Upgrade-, Arm-,
   Confirm-, Ready- und Invalidation-Logs ausserhalb des Main Body zusammen.

3. **Der Main Body bleibt auf Runtime-Entscheidung und BUS-Publish fokussiert**
   Nach C8 liegen die letzten intrabar Event-Latches und die zugehoerige Debug-
   Emission nicht mehr als lokale Inline-Schicht zwischen Runtime und Publish.

4. **Die aktive Regression pinnt den C8-Schnitt explizit**
   Split-Core- und Semantic-Contracts sichern jetzt sowohl die Ready-Edge-
   Latch-Semantik als auch den Debug-Event-Owner gegen Rueckfall in lokale
   Inline-Logik ab.

---

## 10. C9-Paket auf aktuellem Repo-Stand

Der zuletzt ausgefuehrte C9-Schnitt lag nicht mehr auf der Lite- oder
Strategy-Surface, sondern auf dem Pro-only-Diagnostiktransport:

1. **Der Lite-Contract bleibt eingefroren**
   `scripts/smc_bus_manifest.py` unterscheidet jetzt explizit zwischen
   Executable Core, Lite-Surface und Pro-only-Channels. C9 darf diese Grenze
   nicht verwischen.

2. **UI-Transport-Kanaele wurden in explizite Support-Codes ueberfuehrt**
   `ModulePackD` und `ReadyStrictPack` sind aus dem aktiven Producer-Vertrag
   entfernt. An ihrer Stelle exportiert der Core jetzt `LtfDeltaState`,
   `SafeTrendState`, `MicroProfileCode`, `ReadyBlockerCode`,
   `StrictBlockerCode`, `VolExpansionState` und `DdviContextState`, damit die
   Dashboard-Rekonstruktion ohne verbleibende Packs laeuft.

3. **Quality-Diagnostik wird reduziert statt neu aufgeblasen**
   `QualityPackA/B` wurden durch direkte Quality-Rows ersetzt und sind jetzt
   komplett aus dem Producer entfernt, ohne `BUS QualityScore` oder die
   Lite-Surface zu verschieben.

4. **Stabile Pro-Support-Channels bleiben bewusst stehen**
   `MetaPack`, `StopLevel`, `Target1` und `Target2` sind
   keine primaeren Rebuild-Ziele des C9-Schnitts, obwohl sie produktseitig
   Pro-only bleiben.

5. **Manifest und Regression pinnen die C9-Klassifikation**
   Die kanonische Aufteilung des Pro-only-Bereichs lebt jetzt im Manifest und
   ist ueber dedizierte Regression abgesichert, damit Produktgrenze und
   Cleanup-Pfad nicht auseinanderlaufen.

6. **Die aktuelle Pro-Lane ist jetzt support-code-basiert und weiter plot-budget-begrenzt**
   Nach dem Retirement der alten Compat-Exports und den nachgelagerten
   `ModulePackA`-, `ModulePackB`- und `ModulePackC`-Cuts sowie der finalen
   Ablösung von `ModulePackD` und `ReadyStrictPack` liegt die Engine jetzt bei
   `58 / 64` Plots. Die sichtbaren Overlay-Plots wurden zuvor aus dem
   `plot()`-Budget verschoben; der verbleibende Pro-Diagnostikpfad laeuft
   jetzt ueber explizite Support-Codes statt ueber gepackte Resttransporte.
   Weitere Modul-Schritte muessen deshalb weiterhin plot-neutral oder mit
   zusaetzlichen Plot-Einsparungen geplant werden.

---

## 11. Copilot-Einsatz ab Jetzt

Wenn Copilot fuer den verbleibenden Rest eingesetzt wird, sollte es **nicht**
mehr die alten R1-R6-Prompts oder die fruehen C3-Surface-Schleifen ausfuehren.
Stattdessen sollte es sich auf diese fuenf Fragen konzentrieren:

1. Welche Ready-/Strict-Reason-Codes oder Dashboard-Decodes des aktiven Cores sind noch nicht zentral genug verankert?
2. Welche Event-, Alert- oder Observability-Grenzen leben noch inline statt in eigenen Runtime-Ownern?
3. Welche BUS-Packs koennen weiter von Runtime-Logik und Plot-Publikation entkoppelt werden?
4. Wo droht noch Drift zwischen `scripts/smc_bus_manifest.py`, den Consumern und dem TradingView-Runbook?
5. Welche sichtbaren Operator-Controls gehoeren wirklich auf die aktive Surface, und welche muessen hinter `long_user_preset` oder `compact_mode` verschwinden?
6. Welche Pro-only-Packs sind echte Domain-Stuetzen, und welche sind nur noch serialisierte Dashboard-Zeilen?

Damit ist der Migrationsplan auf den tatsaechlichen Repo-Iststand zurueckgesetzt
und verhindert, dass Phase C erneut in rein kosmetische Rework-Schleifen kippt.
