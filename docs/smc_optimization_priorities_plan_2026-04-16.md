# SMC-System: 4-Prioritaeten-Optimierungsplan

**Datum:** 2026-04-16
**Status:** Entwurf
**Branch:** `docs/smc-optimization-priorities-plan`
**Architektur-Baseline:** v5.5b (Lean Surface, 6 Familien, 32 Felder)
**Kontext:** Feature Freeze aktiv (15.04.2026 - 15.05.2026)

---

## Praeambel

Das SMC Long-Dip Suite v7-System hat die Split-Library-Migration abgeschlossen,
alle 9 Pine-Bibliotheken auf TradingView veroeffentlicht und ein belastbares
Measurement-Framework mit drei harten Release-Gates etabliert. Der Teststatus
steht bei 1999 bestanden / 7 fehlgeschlagen (Test-Drift, keine Produktregressionen).

Dieser Plan definiert vier Optimierungsprioritaeten in absteigender Dringlichkeit.
Jede Prioritaet adressiert eine spezifische Schwaeche im aktuellen System und
liefert einen konkreten, messbaren Fortschritt. Die Reihenfolge folgt dem Prinzip:
**Zuerst den bestehenden Wert nutzen, dann die Oberflaeche haerten, dann die
Governance wirksam machen, zuletzt aufraeumen.**

---

## Prioritaet 1: Vorhandene Substanz staerker durchreichen

### Zielbild

Die bestehenden 32 Lean-Felder, 2 Support-Bloecke und das Measurement-Framework
werden vollstaendig bis zur Nutzer-Oberflaeche und in die Alert-Logik
durchgereicht. Jedes bereits berechnete Signal findet seinen Weg zum Operator
-- ohne neue Felder oder Berechnungen hinzuzufuegen.

### Problem

Das System berechnet heute mehr, als es zeigt. Konkret:

- **Signal Quality Score** (Familie 6) wird intern kalkuliert, ist aber nicht
  in allen Dashboard-Modi sichtbar oder in Alert-Bedingungen nutzbar.
- **Contextual Calibration** (session-, htf_bias-, vol_regime-adjustiert) existiert
  als Measurement-Artefakt, wird aber nicht in der Operator-Entscheidungshilfe
  reflektiert.
- **Liquidity Sweep Support** (max. 15 Punkte) und **Compression Regime Support**
  (max. 15 Punkte) fliessen in SQ ein, sind aber fuer den Operator unsichtbar.
- **Measurement-Evidence-Artefakte** (Brier, Log Score, Hit Rate pro Familie)
  existieren als JSON, haben aber keinen Pfad zur operativen Nutzung.
- **Trust-Tier-Informationen** sind seit `85c42068` im Dashboard sichtbar,
  aber die Degradation-Gruende werden nicht granular nach aussen transportiert.

### Massnahmenplan

| Nr. | Massnahme | Umsetzungsort | Aufwand |
|-----|-----------|---------------|---------|
| 1.1 | SQ-Tier und SQ-Score in alle Dashboard-Modi durchreichen (Compact + Audit) | `SMC_Dashboard.pine`, BUS-Slots | S |
| 1.2 | Support-Block-Beitraege (Sweep, Compression) als diagnostische Zeilen im Audit View exponieren | `SMC_Dashboard.pine`, Zeilen 40+ | S |
| 1.3 | Measurement-KPI-Summary als optionalen Dashboard-Abschnitt anbinden (letzte Benchmark-Werte: Brier, Hit Rate) | `smc_adapters/dashboard.py`, neuer Abschnitt | M |
| 1.4 | Alert-Bedingungen um SQ-Tier-Filter erweitern (z.B. "Alert nur bei SQ >= Good") | `SMC_Core_Engine.pine`, Alertcondition-Block | M |
| 1.5 | Degradation-Codes im Dashboard granular auflisten (nicht nur "degraded", sondern welcher Code) | `SMC_Dashboard.pine`, Trust-Sektion | S |
| 1.6 | Calibration-Delta (roh vs. kalibriert) als optionale Measurement-Zeile im Audit View | `smc_adapters/dashboard.py` | S |

### Arbeitspakete

1. **AP-1A: Dashboard SQ-Durchreichung** -- SQ-Score und SQ-Tier in Compact Mode
   sichtbar machen. BUS-Pack-Slot identifizieren oder neuen Slot allokieren.
   Audit View analog erweitern.
2. **AP-1B: Support-Block-Transparenz** -- Sweep- und Compression-Beitragswerte
   als Debug-Zeilen in Audit View anzeigen. Kein Einfluss auf Compact Mode.
3. **AP-1C: Measurement-KPI-Anbindung** -- Adapter-Schicht erweitern, um letzte
   Benchmark-JSON-Werte in Dashboard-Kontext zu uebersetzen.
4. **AP-1D: SQ-gefilterte Alerts** -- Bestehende 10 Alertconditions um optionalen
   SQ-Threshold-Input erweitern. Feature-Freeze-konform (Erweiterung bestehender
   Alerts, keine neuen).
5. **AP-1E: Granulare Degradation-Anzeige** -- Trust-Sektion (Zeilen 18-21)
   um Code-spezifische Degradation-Labels erweitern.

### Abnahmekriterien

- [ ] SQ-Score und SQ-Tier sind in Compact Mode als Dashboard-Zeile sichtbar
- [ ] Audit View zeigt Sweep- und Compression-Support-Beitraege
- [ ] Mindestens 1 Alert-Bedingung akzeptiert SQ-Tier-Filter-Input
- [ ] Degradation-Code wird als Label im Trust-Abschnitt angezeigt
- [ ] Alle bestehenden Tests bleiben gruen (0 neue Failures)
- [ ] TradingView-Compile beider Consumer-Surfaces erfolgreich

### Risiken

| Risiko | Eintrittswahrscheinlichkeit | Auswirkung | Mitigation |
|--------|----------------------------|------------|------------|
| BUS-Slot-Erschoepfung (packed float series) | Mittel | Hoch | Vorher Slot-Budget pruefen; ggf. Bitpacking verdichten |
| Pine-Runtime-Budget-Ueberschreitung | Niedrig | Hoch | Nur bestehende Daten exponieren, keine neuen `request.security`-Aufrufe |
| Feature-Freeze-Konflikt | Mittel | Mittel | Massnahmen als "Durchreichung bestehender Daten" klassifizieren, Owner-Genehmigung einholen |

### Empfehlung

**Sofort starten.** Diese Prioritaet liefert den hoechsten Nutzen bei geringstem
Risiko, weil keine neue Logik eingefuehrt wird -- nur bestehende Substanz wird
sichtbar gemacht. Die Massnahmen 1.1 und 1.5 koennen waehrend des Feature Freeze
umgesetzt werden, da sie unter "Monitoring-Verbesserung" fallen.

---

## Prioritaet 2: Input- und Feldoberflaeche haerten

### Zielbild

Die 308 bestehenden Inputs und 32 Lean-Felder sind vollstaendig validiert,
dokumentiert und gegen Fehlkonfiguration geschuetzt. Jeder Input hat einen
definierten Wertebereich, einen sinnvollen Default und eine Fehlermeldung bei
Verletzung. Die Lean-Surface-Felder sind vertraglich fixiert und durch
automatisierte Tests gegen Drift gesichert.

### Problem

- **Input-Validierung**: 308 Inputs ohne systematische Validierung. Ungueltige
  Werte (z.B. negative Lookback-Perioden, ATR-Multiplikatoren < 0) fuehren zu
  stillen Fehlberechnungen statt zu Warnungen.
- **Feld-Semantik-Drift**: Das `touched`-Label in `OB_MITIGATION_STATE`
  bedeutet "Aging" (Alter 11-30 Bars), nicht "Preis hat OB beruehrt" -- diese
  Ambiguitaet ist dokumentiert, aber nicht auf der Oberflaeche aufgeloest.
- **Schema-Version-Durchsetzung**: `SCHEMA_VERSION` ist in `smc_core/schema_version.py`
  zentralisiert mit 7 Enforcement-Tests, aber die BUS-Schema-Version (`7001`)
  wird nur als Zahl weitergegeben, nicht als geprueftes Objekt.
- **Fehlende Enrichment-Felder**: 21 Library-Felder sind laut Feature-Freeze-Exit-
  Kriterien noch nicht adressiert.
- **Seed-vs-Showcase-Divergenz**: Seed-Artefakte tragen Null-Defaults; Showcase-
  Artefakte plausible Werte. Kein automatisierter Test prueft, ob die Wertebereiche
  der Showcase-Felder innerhalb der Lean-Contract-Grenzen liegen.

### Massnahmenplan

| Nr. | Massnahme | Umsetzungsort | Aufwand |
|-----|-----------|---------------|---------|
| 2.1 | Input-Validierungs-Layer in Pine einfuehren (min/max/type fuer alle 308 Inputs) | `SMC_Core_Engine.pine`, Input-Block | L |
| 2.2 | Lean-Contract-Boundary-Tests schreiben (Wertebereich pro Feld) | `tests/test_lean_contract_boundaries.py` | M |
| 2.3 | BUS-Schema-Version als Objekt mit Kompatibilitaetspruefung transportieren | `smc_bus_private.pine`, `SMC_Dashboard.pine` | M |
| 2.4 | 21 fehlende Library-Felder identifizieren und adressieren (Stub oder Implementation) | `smc_core/`, `SMC++/` | L |
| 2.5 | Showcase-Artefakt-Boundary-Test hinzufuegen (Werte innerhalb Contract-Grenzen) | `tests/test_showcase_boundaries.py` | S |
| 2.6 | Input-Dokumentations-Generator (Markdown-Tabelle aller 308 Inputs mit Default, Bereich, Beschreibung) | `scripts/` | M |

### Arbeitspakete

1. **AP-2A: Input-Validierung Phase 1** -- Kritische Inputs identifizieren
   (Lookback-Perioden, Multiplikatoren, Schwellenwerte). Pine-`runtime.error()`
   fuer offensichtlich ungueltige Werte. Tooltip-Beschreibungen aktualisieren.
2. **AP-2B: Lean-Contract-Boundary-Tests** -- Fuer jedes der 32 Lean-Felder
   einen Test schreiben, der den Wertebereich validiert (z.B. SQ-Score 0-100,
   Freshness true/false, Trend Strength 0-5).
3. **AP-2C: BUS-Schema-Haertung** -- BUS-Version von magischer Zahl `7001` zu
   strukturiertem Objekt migrieren. Dashboard-Mismatch-Warnung beibehalten,
   aber mit sprechender Fehlermeldung.
4. **AP-2D: Library-Feld-Adressierung** -- Die 21 fehlenden Felder katalogisieren.
   Entscheidung pro Feld: implementieren, als "nicht geplant" markieren oder
   als Stub mit Safe-Default anlegen.
5. **AP-2E: Artefakt-Boundary-Tests** -- Showcase-Werte gegen Lean-Contract-
   Grenzen validieren. Seed-Artefakte muessen alle Null-Defaults tragen.

### Abnahmekriterien

- [ ] Mindestens 50 % der 308 Inputs haben explizite Bereichsvalidierung
- [ ] 32 Lean-Felder haben je mindestens einen Boundary-Test
- [ ] BUS-Schema-Version ist als benanntes Objekt transportiert
- [ ] 21 fehlende Library-Felder sind katalogisiert und adressiert
- [ ] Showcase-Boundary-Test existiert und ist gruen
- [ ] Input-Dokumentation als generierte Markdown-Tabelle verfuegbar

### Risiken

| Risiko | Eintrittswahrscheinlichkeit | Auswirkung | Mitigation |
|--------|----------------------------|------------|------------|
| Pine-Input-Limit (max. ~450 Inputs in Pine v6) | Niedrig | Hoch | Validierung nutzt bestehende Inputs, fuegt keine neuen hinzu |
| Breaking Change durch BUS-Schema-Migration | Mittel | Hoch | Abwaertskompatiblen Uebergangszeitraum definieren; Dashboard muss alte + neue Version lesen koennen |
| Aufwand fuer 308-Input-Validierung unterschaetzt | Hoch | Mittel | Phase 1 auf Top-50 kritische Inputs beschraenken |

### Empfehlung

**Nach Prioritaet 1 starten, waehrend Feature Freeze.** Input-Validierung und
Tests fallen unter "Test-Erweiterung" und "Pipeline-Reparatur" und sind Freeze-
konform. Die Library-Feld-Adressierung ist ein explizites Exit-Kriterium des
Feature Freeze und muss vor Freeze-Ende abgeschlossen sein.

---

## Prioritaet 3: Trust und Governance wirksam machen

### Zielbild

Das Trust-Tier-System (high / guarded / degraded / insufficient) und die drei
harten Release-Gates (Brier <= 0.60, ECE <= 0.30, Coverage-Schwellen) sind
End-to-End wirksam: von der Measurement-Evidence-Erzeugung ueber die Gate-
Evaluation bis zur Operator-sichtbaren Konsequenz. Shadow Evaluation ist als
standardisierter Prozess fuer neue Features etabliert.

### Problem

- **Test-Governance-Drift**: 7 Tests scheitern, weil sie die alte Gate-
  Klassifikation erwarten (`warn` statt `fail` nach Promotion von Brier/ECE
  zu Hard-Blocking in `77ac1652`). Das zeigt, dass Governance-Aenderungen
  keinen automatisierten Test-Update-Mechanismus ausloesen.
- **Shadow-Evaluation-Prozess nicht formalisiert**: Die RFCs fuer Displacement
  und Consolidation Score empfehlen beide Shadow Evaluation, aber es gibt
  keinen definierten Prozess (Dauer, Metriken, Abbruchkriterien, Promotion-Pfad).
- **Measurement-Evidence-Luecken**: Contextual Calibration (session, htf_bias,
  vol_regime) ist implementiert, aber es existieren noch keine 2+ Benchmark-
  Reports (Feature-Freeze-Exit-Kriterium).
- **Provider-Health-Tracking ohne Eskalation**: `provider_health.py` trackt
  den Zustand, aber bei Degradation gibt es keinen definierten Eskalationspfad
  (Wer wird benachrichtigt? Welche Massnahme wird automatisch ergriffen?).
- **Release-Gate-Auditierbarkeit**: Die Gate-Evaluation laeuft in Python, aber
  das Ergebnis wird nicht als Artefakt persistiert (kein Gate-Report pro Release).

### Massnahmenplan

| Nr. | Massnahme | Umsetzungsort | Aufwand |
|-----|-----------|---------------|---------|
| 3.1 | 7 fehlgeschlagene Tests an neue Gate-Klassifikation anpassen | `tests/test_smc_bus_v2_semantics.py`, `tests/test_smc_integration_release_gate_scripts.py` | S |
| 3.2 | Shadow-Evaluation-Prozessdokumentation erstellen (Lifecycle, Metriken, Promotion-Kriterien) | `docs/shadow_evaluation_process.md` | M |
| 3.3 | 2+ Measurement-Benchmark-Reports generieren (Feature-Freeze-Exit-Kriterium) | `smc_core/benchmark.py`, Output-Artefakte | M |
| 3.4 | Provider-Health-Eskalationsrichtlinie definieren und implementieren | `smc_integration/provider_health.py`, `docs/` | M |
| 3.5 | Gate-Report-Artefakt pro Release-Kandidat einfuehren (JSON mit Gate-Status, Schwellenwerten, Evidenz) | `smc_integration/release_policy.py` | M |
| 3.6 | Governance-Promotion-Checkliste erstellen (bei Aenderung von Gate-Klassifikation automatisch betroffene Tests identifizieren) | `docs/governance_promotion_checklist.md` | S |

### Arbeitspakete

1. **AP-3A: Test-Alignment** -- Die 7 bekannten Failures beheben. 4 Dashboard-
   Row-Index-Tests aktualisieren (Trust-Tier-Insertion bei Zeilen 18-21 beruecksichtigen).
   3 Gate-Tests an Hard-Blocking-Status anpassen.
2. **AP-3B: Shadow-Evaluation-Framework** -- Prozessdokument mit: Definition,
   Startbedingungen, Laufzeit (min. 14 Tage), ueberwachte Metriken (Brier-Delta,
   Coverage-Aenderung, False-Positive-Rate), Abbruchkriterien, Promotion-Entscheidung.
3. **AP-3C: Benchmark-Report-Generierung** -- Mindestens 2 Reports fuer
   verschiedene Symbol/Timeframe-Kombinationen erzeugen und als Artefakte
   committen.
4. **AP-3D: Eskalationsrichtlinie** -- Bei `degraded`-Trust-Tier: automatische
   Dashboard-Warnung (bereits vorhanden) + definierte Operatoraktion. Bei
   `insufficient`: Blockierung neuer Releases.
5. **AP-3E: Gate-Report-Artefakt** -- Bei jedem Release-Kandidat automatisch
   `gate_report_{date}.json` erzeugen mit allen Gate-Ergebnissen, Schwellenwerten
   und der zugrunde liegenden Evidenz.

### Abnahmekriterien

- [ ] 0 fehlgeschlagene Tests (7 bestehende Failures behoben)
- [ ] Shadow-Evaluation-Prozess ist dokumentiert und durch mindestens 1 RFC referenziert
- [ ] 2+ Measurement-Benchmark-Reports existieren als committete Artefakte
- [ ] Provider-Health-Eskalationsrichtlinie ist dokumentiert
- [ ] Gate-Report-Artefakt wird bei Release-Kandidat-Erstellung automatisch erzeugt
- [ ] Governance-Promotion-Checkliste existiert

### Risiken

| Risiko | Eintrittswahrscheinlichkeit | Auswirkung | Mitigation |
|--------|----------------------------|------------|------------|
| Test-Alignment fuehrt zu neuen Failures (Kaskade) | Niedrig | Mittel | Aenderungen atomisch pro Test-Datei committen, nach jedem Commit vollstaendigen Test-Lauf |
| Shadow-Evaluation-Prozess zu rigide fuer schnelle Iterationen | Mittel | Mittel | Opt-out-Klausel fuer Owner-genehmigte Ausnahmen vorsehen |
| Benchmark-Report-Generierung erfordert reale Marktdaten | Hoch | Mittel | Seed-basierte synthetische Daten als Fallback; reale Daten via Databento-Pipeline |

### Empfehlung

**Parallel zu Prioritaet 1 starten (AP-3A sofort).** Das Test-Alignment (AP-3A)
ist die dringendste Einzelmassnahme im gesamten Plan -- 7 rote Tests sind ein
Risiko fuer die Signalwirkung des CI-Systems. Der Shadow-Evaluation-Prozess
(AP-3B) ist Voraussetzung fuer die Promotion der Displacement- und Consolidation-
Score-RFCs.

---

## Prioritaet 4: Legacy-/Companion-/Operator-Landschaft bereinigen

### Zielbild

Die gesamte Codebasis enthaelt ausschliesslich v5.5b-konforme Artefakte. Alle
Legacy-Pfade, Backward-Compat-Shims und veralteten Companion-Referenzen sind
entfernt. Die Operator-Landschaft (Core Engine + Dashboard) ist klar definiert,
und es gibt keine Ambiguitaet darueber, welche Surfaces produktiv sind.

### Problem

- **BUS-Backward-Compat entfernt, aber Spuren vorhanden**: Phase B hat alle 33
  Broad-Felder entfernt, aber es koennen noch Code-Kommentare, Test-Fixtures
  oder Dokumentationsreste existieren, die auf `ModulePackE/F/G` referenzieren.
- **Legacy-Governance-Anker**: `test_long_dip_regression_anchors_to_active_core_engine`
  wurde in `ed347402` repariert, aber die Existenz eines solchen "Anker-Tests"
  zeigt, dass die Beziehung zwischen Legacy- und aktuellem Code nicht trivial ist.
- **Companion-Skript-Ambiguitaet**: Es ist nicht klar dokumentiert, welche
  TradingView-Skripte neben Core Engine + Dashboard noch aktiv gepflegt werden
  und welche als deprecated gelten.
- **Volatile-Artifact-Policy**: `VOLATILE_ARTIFACT_POLICY` in `release_policy.py`
  klassifiziert bekannte volatile Pfade, aber die Policy wird nicht bei jedem
  Commit automatisch geprueft.
- **Generierte vs. handgepflegte Artefakte**: Die Trennung zwischen
  `tests/fixtures/generated_seed/` und `tests/fixtures/generated_showcase/`
  ist klar, aber es gibt weitere generierte Dateien unter `pine/generated/`
  deren Lifecycle nicht vollstaendig dokumentiert ist.
- **Short-Parity**: Explizit out-of-scope, aber in Kommentaren referenziert.
  Diese Referenzen sollten als "nicht geplant" markiert werden, um falsche
  Erwartungen zu vermeiden.

### Massnahmenplan

| Nr. | Massnahme | Umsetzungsort | Aufwand |
|-----|-----------|---------------|---------|
| 4.1 | Legacy-Referenz-Audit: alle Referenzen auf `ModulePackE/F/G`, `broad_*`, alte BUS-Felder finden und bereinigen | Repo-weit (`grep`) | M |
| 4.2 | Companion-Skript-Registry erstellen (aktiv / deprecated / archiviert) | `docs/companion_script_registry.md` | S |
| 4.3 | Volatile-Artifact-Policy in CI-Check integrieren (automatische Pruefung bei jedem Commit) | CI-Pipeline, `release_policy.py` | M |
| 4.4 | Generierte-Artefakte-Lifecycle dokumentieren (welche Dateien werden wann von welchem Generator erzeugt) | `docs/generated_artifacts_lifecycle.md` | S |
| 4.5 | Short-Parity-Referenzen als "nicht geplant" markieren | `SMC_Core_Engine.pine`, `SMC_Dashboard.pine` | S |
| 4.6 | Dead-Code-Analyse und -Bereinigung (ungenutzte Imports, verwaiste Fixtures, nicht-referenzierte Testhelfer) | Repo-weit | L |

### Arbeitspakete

1. **AP-4A: Legacy-Audit** -- Systematischer `grep` nach bekannten Legacy-
   Begriffen (`ModulePackE`, `ModulePackF`, `ModulePackG`, `broad_field`,
   `backward_compat`, veraltete BUS-Slot-Nummern). Jede Fundstelle bewerten:
   entfernen, aktualisieren oder als historischen Kommentar markieren.
2. **AP-4B: Companion-Registry** -- Alle TradingView-Skripte unter `preuss_steffen/`
   katalogisieren. Status pro Skript: aktiv (gepflegt), deprecated (nicht mehr
   aktualisiert), archiviert (nur noch historisch).
3. **AP-4C: CI-Integration Volatile-Artifact-Policy** -- Pre-Commit-Hook oder
   CI-Step, der `VOLATILE_ARTIFACT_POLICY`-Pfade gegen tatsaechliche Datei-
   Aenderungen prueft und warnt, wenn volatile Artefakte ohne explizite
   Begruendung geaendert werden.
4. **AP-4D: Artefakt-Lifecycle-Dokumentation** -- Fuer jedes generierte Artefakt:
   Quell-Generator, Trigger (manuell/CI/commit-hook), Output-Pfad, Abhaengigkeiten.
5. **AP-4E: Dead-Code-Bereinigung** -- Python-Module mit `vulture` oder
   aehnlichem Tool analysieren. Pine-Code manuell auf ungenutzte Variablen
   und Imports pruefen (CE-Warnings als Leitfaden).

### Abnahmekriterien

- [ ] 0 Referenzen auf `ModulePackE/F/G` ausserhalb historischer Dokumentation
- [ ] Companion-Skript-Registry existiert mit Status fuer jedes bekannte Skript
- [ ] Volatile-Artifact-Policy wird in CI automatisch geprueft
- [ ] Generierte-Artefakte-Lifecycle ist dokumentiert
- [ ] Short-Parity-Referenzen sind als "nicht geplant" markiert
- [ ] Dead-Code-Analyse durchgefuehrt, Top-10-Funde bereinigt

### Risiken

| Risiko | Eintrittswahrscheinlichkeit | Auswirkung | Mitigation |
|--------|----------------------------|------------|------------|
| Legacy-Bereinigung bricht bestehende Tests | Mittel | Mittel | Jede Bereinigung als eigenen Commit mit vollem Test-Lauf |
| Companion-Skript faelschlich als deprecated markiert | Niedrig | Hoch | Vor Archivierung TradingView-Nutzungsdaten pruefen (sofern verfuegbar) |
| Dead-Code-Analyse meldet False Positives (dynamisch genutzte Pfade) | Hoch | Niedrig | Nur offensichtliche Funde bereinigen; dynamische Importe ausnehmen |

### Empfehlung

**Nach Feature Freeze starten.** Diese Prioritaet hat das geringste
Dringlichkeitsverhaeltnis und das hoechste Risiko fuer unbeabsichtigte Brueche.
Legacy-Bereinigung profitiert von einem stabilen Test-Fundament (Prioritaeten 2+3)
und sollte erst erfolgen, wenn alle bekannten Test-Failures behoben sind.

---

## Empfohlene Reihenfolge und Begruendung

### Sequenz

```
Phase 1 (sofort, waehrend Feature Freeze):
  Prioritaet 1 -- Vorhandene Substanz durchreichen
  Prioritaet 3, AP-3A -- 7 Test-Failures beheben (parallel)

Phase 2 (Feature Freeze, Wochen 2-3):
  Prioritaet 2 -- Input- und Feldoberflaeche haerten
  Prioritaet 3, AP-3B/3C -- Shadow-Evaluation + Benchmark-Reports

Phase 3 (Feature Freeze, Woche 4):
  Prioritaet 3, AP-3D/3E -- Eskalation + Gate-Reports
  Prioritaet 2, AP-2D -- 21 fehlende Library-Felder (Freeze-Exit-Kriterium)

Phase 4 (nach Feature Freeze):
  Prioritaet 4 -- Legacy-Bereinigung
```

### Begruendung der Reihenfolge

1. **Prioritaet 1 zuerst**, weil sie den hoechsten Sofort-Nutzen bei geringstem
   Risiko liefert. Kein neuer Code wird geschrieben -- nur bestehende Berechnungen
   werden sichtbar gemacht. Dies verbessert die Operator-Erfahrung unmittelbar
   und erfordert keine Aenderung an der Kernlogik. Alle Massnahmen sind Feature-
   Freeze-konform ("Monitoring-Verbesserung").

2. **Prioritaet 3, AP-3A sofort parallel**, weil 7 rote Tests ein falsches
   Signal im CI-System senden. Jeder Entwickler, der den Test-Status sieht,
   muss aktuell wissen, dass die Failures harmlos sind. Das ist operatives
   Risiko, das sofort eliminiert werden sollte.

3. **Prioritaet 2 vor dem Rest von Prioritaet 3**, weil eine gehaertete
   Oberflaeche die Voraussetzung fuer belastbare Governance ist. Wenn Inputs
   nicht validiert sind, kann auch die beste Gate-Logik keine zuverlaessigen
   Entscheidungen treffen. Ausserdem adressiert AP-2D ein explizites Feature-
   Freeze-Exit-Kriterium.

4. **Prioritaet 4 zuletzt**, weil Legacy-Bereinigung zwar wertvoll, aber nicht
   dringend ist. Sie profitiert maximal von einem stabilen Test-Fundament und
   klarer Governance. Vorzeitige Bereinigung ohne diese Grundlage riskiert
   unbeabsichtigte Regressionen.

### Abhaengigkeiten zwischen Prioritaeten

```
P1 (Durchreichung) ──────── unabhaengig, sofort startbar
P3.AP-3A (Test-Fix) ─────── unabhaengig, sofort startbar
P2 (Haertung) ──────────── logische Voraussetzung fuer P3 (vollstaendig)
P3 (Governance) ─────────── benoetigt P2 fuer volle Wirksamkeit
P4 (Bereinigung) ────────── benoetigt P2 + P3 als stabiles Fundament
```

### Ressourcenschaetzung

| Phase | Dauer | Parallelisierbar | Freeze-konform |
|-------|-------|------------------|----------------|
| Phase 1 | 1-2 Wochen | Ja (P1 + P3.AP-3A) | Ja |
| Phase 2 | 2-3 Wochen | Teilweise | Ja |
| Phase 3 | 1-2 Wochen | Ja | Ja |
| Phase 4 | 2-4 Wochen | Ja | Nein (nach Freeze) |

---

## Anhang: Referenz-Dokumente

| Dokument | Pfad | Relevanz |
|----------|------|----------|
| v5.5b Architektur | `docs/v5_5b_architecture.md` | Architektur-Baseline |
| Feature Freeze | `docs/FEATURE_FREEZE.md` | Zeitliche Rahmenbedingungen |
| Final Status Review | `docs/smc_final_status_review_2026-04-16.md` | Ist-Zustand |
| No Shadow Logic Policy | `docs/NO_SHADOW_LOGIC_POLICY.md` | Architekturprinzip |
| Measurement Lane | `docs/MEASUREMENT_LANE.md` | Measurement-Framework |
| Measurement Calibration | `docs/MEASUREMENT_CALIBRATION.md` | Kalibrierungs-Policy |
| Schema Versioning | `docs/schema_versioning.md` | Versionierungs-Policy |
| Artifact Strategy | `docs/ARTIFACT_STRATEGY.md` | Artefakt-Klassen |
| RFC Displacement | `docs/rfc_displacement_candle_classification_2026-04-16.md` | Shadow-Evaluation-Kandidat |
| RFC Consolidation | `docs/rfc_composite_consolidation_score_2026-04-16.md` | Shadow-Evaluation-Kandidat |
| Branch Protection | `docs/smc_branch_protection_and_release_gates.md` | Release-Prozess |
