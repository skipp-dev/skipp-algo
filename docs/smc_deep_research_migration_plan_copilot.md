# SMC-Migrationsplan (Repo-Iststand vs. `deep-research-report.md`) – Copy/Paste-Arbeitspakete für Copilot

## Ziel dieses Dokuments

Dieses Dokument vergleicht den aktuellen SMC-Stand im Repo mit den Zielbildern und Prioritäten aus `docs/deep-research-report.md` und leitet daraus umsetzbare Arbeitspakete ab, die direkt als Copilot-Prompts verwendet werden können.

Referenzquellen:
- Deep-Research-Analyse mit P0/P1/P2-Priorisierung, Risiken und Validierungsgates in `docs/deep-research-report.md`.
- Repository-Target-Architektur in `docs/smc-snapshot-target-architecture.md`.
- Aktuelle ID-Quantisierung in `smc_core/ids.py`.
- Aktuelle Schema-Version in `smc_core/schema_version.py`.
- Snapshot-Beispielstand in `spec/examples/smc_snapshot_aapl_15m_normal.json`.
- Laufzeitumgebung in `.devcontainer/devcontainer.json` und `pyproject.toml`.

---

## 1) Delta-Analyse: Ist vs. Zielarchitektur aus Deep Research

### Bereits gut abgedeckt (KEEP)

1. **Canonical-only Structure** ist im Repo-Target explizit verankert (`bos`, `orderblocks`, `fvg`, `liquidity_sweeps`).
2. **Generator-first + Contract-Driven** ist durch Snapshot-/Bundle-Architektur und Exportpfade strukturell vorhanden.
3. **Adapter-/Integrationstrennung** (`smc_core` / `smc_adapters` / `smc_integration`) ist klar dokumentiert.

### Kritische Deltas (MIGRATE NOW)

1. **Schema-Drift**: `SCHEMA_VERSION = "2.0.0"`, aber Beispielartefakt führt noch `"1.2.0"`.
2. **ID-Quantisierung**: Preis-Quantisierung ist aktuell nur `decimals`-basiert; Time-Bucketing ist bei `1D` noch explizit als UTC-basierte TODO markiert.
3. **Runtime-Mismatch**: Devcontainer läuft auf Python 3.11, Projekt fordert `>=3.12`.
4. **HTF/Session-Single-Source-of-Truth**: Deep-Research fordert stärkere Konsolidierung; in der Architektur sind mehrere additive Kontexte aktiv, aber ohne explizite zentrale Bias-Prioritätsregel.
5. **Probabilistische Qualitätsmessung** (Volatilitätsregime + proper scoring) ist als Ziel klar beschrieben, aber noch kein harter, CI-gebundener Standardpfad.

---

## 2) Umsetzungsstrategie (Phasen)

- **Phase P0 (Governance-Härtung, 1–2 Wochen):** Drift und deterministische Contracts fixen.
- **Phase P1 (Semantik-Härtung, 2–4 Wochen):** HTF/Session/Bias-Regeln und Layering-Policy als Single Source of Truth.
- **Phase P2 (Quant/Quality MVP, 3–6 Wochen):** Vol-Regime + probabilistische Score-Pipeline als additive Meta-Domain.
- **Phase P3 (Gates & Betrieb, 1–2 Wochen):** CI-Gates, Benchmarks und Artefaktisierung finalisieren.

---

## 3) Copy/Paste-Arbeitspakete für Copilot

> Nutzung: Jedes Paket einzeln in Copilot Chat einfügen. Nach jedem Paket Commit + Tests durchführen.

## Arbeitspaket P0.1 – Schema-Drift vollständig eliminieren

**Ziel**
- Alle Beispiel-Snapshots und zugehörige Fixtures auf `SCHEMA_VERSION` synchronisieren.

**Betroffene Bereiche**
- `smc_core/schema_version.py`
- `spec/examples/*.json`
- Tests rund um Schema-Version-Enforcement

**Copilot Prompt (Copy/Paste)**

```text
Bitte behebe Schema-Drift im SMC-Repo.

Aufgaben:
1) Lies smc_core/schema_version.py und ermittle die aktuelle SCHEMA_VERSION.
2) Suche in spec/examples und tests/fixtures nach schema_version-Feldern.
3) Aktualisiere alle statischen Beispielartefakte auf exakt diese SCHEMA_VERSION.
4) Stelle sicher, dass Tests zur Schema-Version-Enforcement-Logik weiterhin sinnvoll und strikt sind.
5) Ergänze oder aktualisiere Tests, damit zukünftiger Drift (Code vs Beispiele) sofort fehlschlägt.

Akzeptanzkriterien:
- Keine Beispiel-JSON enthält eine abweichende schema_version.
- pytest -q tests/test_smc_schema_version_enforcement.py ist grün.
- pytest -q tests/test_smc_snapshot_schema.py ist grün.

Bitte liefere zusätzlich eine kurze Liste aller geänderten Dateien mit Begründung.
```

---

## Arbeitspaket P0.2 – Ticksize- und Session-Awareness in IDs einführen

**Ziel**
- ID-Erzeugung marktkonform stabilisieren (Preisraster + Session-aware Zeitanker).

**Betroffene Bereiche**
- `smc_core/ids.py`
- ggf. neue Konfigurations-/Policy-Datei für Symbol→Ticksize und Exchange-Session
- Tests für ID-Stabilität

**Copilot Prompt (Copy/Paste)**

```text
Bitte implementiere eine robuste V2-ID-Quantisierung für SMC-Events.

Ausgangslage:
- smc_core/ids.py nutzt aktuell decimals-basiertes quantize_price.
- quantize_time_to_tf hat bei 1D einen UTC-TODO-Hinweis.

Aufgaben:
1) Führe ticksize-aware quantize_price ein (pro Symbol/Asset-Typ konfigurierbar).
2) Führe session-aware quantize_time_to_tf ein, insbesondere für 1D-Anker (Exchange-Kalender statt UTC-Tag).
3) Implementiere saubere Fallbacks, wenn keine Ticksize/Session-Metadaten vorliegen.
4) Stelle Backward-Compatibility sicher (z. B. Feature-Flag oder klarer Migration-Pfad).
5) Erweitere Tests mit Property-ähnlichen Fällen:
   - gleiche Inputs => gleiche IDs
   - Session-Grenzen
   - verschiedene Tickraster

Akzeptanzkriterien:
- IDs sind deterministisch und reproduzierbar.
- Tests für IDs decken Session- und Ticksize-Kantenfälle ab.
- Dokumentation beschreibt explizit die neue Quantisierungslogik.

Bitte liefere Migrationshinweise für bestehende Artefakte.
```

---

## Arbeitspaket P0.3 – Python-Runtime konsolidieren (lokal/CI/devcontainer)

**Ziel**
- Lokale Dev-Umgebung und CI auf dieselbe Hauptversion bringen.

**Betroffene Bereiche**
- `.devcontainer/devcontainer.json`
- `pyproject.toml`
- ggf. CI-Workflow-Dokumentation

**Copilot Prompt (Copy/Paste)**

```text
Bitte vereinheitliche die Python-Runtime im Repo.

Ausgangslage:
- pyproject.toml fordert Python >=3.12.
- .devcontainer/devcontainer.json nutzt aktuell ein Python-3.11-Image.

Aufgaben:
1) Bringe devcontainer und Projektanforderung auf einen konsistenten Stand (bevorzugt 3.12).
2) Prüfe, ob abhängige Tooling-Configs angepasst werden müssen.
3) Ergänze kurze Dokumentation, warum diese Version gewählt wurde.
4) Führe die relevanten Tests/Linting aus und dokumentiere Ergebnis.

Akzeptanzkriterien:
- Kein Versionswiderspruch mehr zwischen pyproject und devcontainer.
- Basis-Testlauf im angepassten Setup erfolgreich.
```

---

## Arbeitspaket P1.1 – HTF/Session Bias als Single Source of Truth

**Ziel**
- Eine zentrale, deterministische Prioritätsregel für Bias und Kontextzusammenführung.

**Betroffene Bereiche**
- `scripts/smc_session_context.py`
- `scripts/smc_htf_context.py`
- Layering-/Integration-Mergepfade
- neue/erweiterte Tests

**Copilot Prompt (Copy/Paste)**

```text
Bitte implementiere eine Single-Source-of-Truth für HTF/Session-Bias im SMC-Stack.

Aufgaben:
1) Analysiere bestehende Bias-Signale aus session_context und htf_context.
2) Definiere eine explizite Prioritäts-/Merge-Regel (z. B. HTF dominiert, Session moduliert Confidence).
3) Implementiere diese Regel zentral (nicht verteilt über mehrere Consumer).
4) Stelle sicher, dass Layering/ZoneStyles diese zentrale Bias-Entscheidung konsistent nutzen.
5) Ergänze Tests für widersprüchliche Signale (HTF bullish, Session risk-off etc.).

Akzeptanzkriterien:
- Keine divergierenden Bias-Ausgaben bei identischem Input entlang der Pipeline.
- Tests decken Konfliktfälle und Determinismus ab.
- Dokumentation enthält klare Entscheidungslogik mit Beispielen.
```

---

## Arbeitspaket P1.2 – „Qualify, don't block" als harte Layering-Policy

**Ziel**
- Blocking nur bei Data/Health-Failures; sonst Tier-Downgrade + Warnings.

**Betroffene Bereiche**
- `smc_core/layering.py`
- `smc_integration/provider_health.py`
- Adapter-Projection nach Pine/Dashboard

**Copilot Prompt (Copy/Paste)**

```text
Bitte verankere die Policy "qualify, don't block" im SMC-Layering.

Aufgaben:
1) Prüfe aktuelle Blockierungs-/Trade-State-Entscheidungen im Layering.
2) Implementiere Regel:
   - Hard block nur bei invalid data / provider health failure.
   - In allen anderen Fällen: Tier downgrade + max. 1-3 warnings + reason codes.
3) Stelle sicher, dass Pine- und Dashboard-Adapter dieselbe Semantik ausgeben.
4) Ergänze Regressionstests gegen Shadow-Logic-Drift zwischen Snapshot und Consumer-Payloads.

Akzeptanzkriterien:
- Trade-State-Entscheidungen sind zentral, testbar und konsistent.
- Reason-codes/Warnungen sind maschinenlesbar und begrenzt.
```

---

## Arbeitspaket P2.1 – Volatilitätsregime als additive Meta-Domain (MVP)

**Ziel**
- Volatilitäts-/Regimekontext als Signalqualitätsmodulator integrieren.

**Betroffene Bereiche**
- neues Modul unter `scripts/` oder `smc_core/` für Vol-Regime
- Meta-Merge (`smc_integration.service`)
- Layering-Scoring

**Copilot Prompt (Copy/Paste)**

```text
Bitte implementiere ein Volatilitätsregime-MVP als additive Meta-Domain für SMC.

Aufgaben:
1) Erzeuge ein Modul für vol_forecast/regime_label (MVP, robust und deterministisch).
2) Integriere Ergebnis in snapshot.meta ohne bestehende Struktur-Events zu verändern.
3) Nutze das Regime im Layering zur Modulation von global_strength/Tier.
4) Ergänze Tests für:
   - fehlende Daten (graceful degradation)
   - deterministische Ausgabe
   - Einfluss auf Tier-Entscheidung
5) Dokumentiere Datenbedarf, Grenzen und Fallback-Verhalten.

Akzeptanzkriterien:
- Snapshot bleibt schema-kompatibel.
- Layering reagiert nachvollziehbar auf Regimewechsel.
- Keine Hard-Dependency, die Exportpfade bricht.
```

---

## Arbeitspaket P2.2 – Probabilistische Qualität + Proper Scoring im CI

**Ziel**
- Signalqualität messbar kalibrieren (statt nur heuristisch bewerten).

**Betroffene Bereiche**
- neues Scoring-/Evaluation-Modul
- Benchmarks/Artefakt-Export
- CI-Gates

**Copilot Prompt (Copy/Paste)**

```text
Bitte implementiere eine probabilistische Signalqualitäts-Evaluierung für SMC inkl. CI-Artefakten.

Aufgaben:
1) Definiere Label-Logik pro Eventfamilie (BOS/OB/FVG/Sweep), beginnend mit Sweep-Reversal-MVP.
2) Implementiere proper scoring metrics (mindestens Brier Score und Log Score).
3) Erzeuge versionierte Evaluationsartefakte (JSON/CSV) pro Symbol+Timeframe.
4) Integriere einen CI-Check, der bei deutlicher Qualitätsverschlechterung fehlschlägt.
5) Ergänze Dokumentation der Metrikdefinition und Gate-Schwellen.

Akzeptanzkriterien:
- Metriken reproduzierbar und datenquellen-transparent.
- CI-Gate ist deaktivierbar für lokale Experimente, aber im Release aktiv.
```

---

## Arbeitspaket P3.1 – Standardisierte Benchmark- und Visualisierungsartefakte

**Ziel**
- Vergleichbarkeit über Iterationen und robuste Release-Entscheidungen.

**Betroffene Bereiche**
- Scripts für KPI-Export
- CI-Artefakt-Publishing
- Operator-Dokumentation

**Copilot Prompt (Copy/Paste)**

```text
Bitte standardisiere SMC-Benchmarks und Visualisierungsartefakte.

Aufgaben:
1) Definiere KPI-Set pro Eventfamilie (Hit-Rate, Time-to-mitigation, Invalidation, MAE/MFE).
2) Stratifiziere KPIs nach Session, HTF-Bias und Vol-Regime.
3) Erzeuge Artefakte für:
   - Calibration/Reliability Curves
   - Regime-Posterior-over-time
   - Runtime-Budget-Plot (Bridge/Pine)
4) Hinterlege ein einheitliches Artefakt-Schema + Manifest.

Akzeptanzkriterien:
- Alle KPIs sind maschinenlesbar und historisierbar.
- Ein einziger Befehl kann den Benchmark-Lauf erzeugen.
```

---

## 4) Definition of Done (Gesamtmigration)

Die Migration gilt als abgeschlossen, wenn folgende Bedingungen erfüllt sind:

1. **Governance stabil:** Kein Schema-Drift, keine Runtime-Drifts, deterministische ID-Strategie.
2. **Semantik stabil:** HTF/Session/Bias und Layering-Policy sind zentral definiert und in allen Consumern konsistent.
3. **Quality messbar:** probabilistische Metriken sind versioniert und Bestandteil der Release-Gates.
4. **Operativ belastbar:** standardisierte Benchmarks + Visualisierungen sind als CI-Artefakte verfügbar.

---

## 5) Empfohlene Ausführungsreihenfolge für Copilot

1. P0.1 → P0.3 (Drift & Environment zuerst)
2. P1.1 → P1.2 (Semantik zentralisieren)
3. P2.1 → P2.2 (Quality-Layer aufbauen)
4. P3.1 (Mess- und Betriebsreife)

Damit wird zuerst technische Stabilität erzeugt und danach Modell-/Qualitätskomplexität hinzugefügt.
