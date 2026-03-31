# Deep Research: Neu geschriebenes SMC‑System in `skipp-dev/skipp-algo` – Repo‑Extraktion, Vergleich, Literatur, Verbesserungen und v5.5b‑Artefakte

## Executive Summary

Das Repository `skipp-dev/skipp-algo` implementiert ein **generator‑first, contract‑orientiertes SMC‑System** (SMC = *Smart Money Concepts / Market Structure*), das kanonische Struktur‑Ereignisse (BOS, Order Blocks, Fair Value Gaps, Liquidity Sweeps) deterministisch aus OHLC‑Bars ableitet, anschließend durch **Meta‑Kontexte + Layering/ZoneStyles** qualifiziert und schließlich über eine **TradingView‑Bridge (FastAPI + Pine Consumer)** bzw. über CI‑gesteuerte Pine‑Library‑Refresh‑Pipelines ausliefert. Das System ist stark auf **Stabilität, Schema‑Governance, Release‑Gates und Parity‑Tests** ausgerichtet. fileciteturn7file0L10-L41 fileciteturn11file0L1-L70 fileciteturn21file0L1-L90 fileciteturn69file0L1-L34

Das angehängte Zielarchitektur‑Dokument **v5.5a** priorisiert „lean“, „canonical‑only structure“, „scoring statt blocking“ und „no shadow logic“ als Leitprinzipien. fileciteturn95file0  
Der Repo‑Stand operationalisiert diese Prinzipien bereits an mehreren Stellen (Schema‑Enforcement, Engine‑Purity, Adapter/Parity‑Tests, CI‑Gates), weist aber auch **architekturrelevante Lücken** auf: (a) harte Timeframe‑ und Preis‑Quantisierung (Ticksize/Exchange‑Session nicht sauber gelöst), (b) potenzielle **Schema‑Version‑Drifts** zwischen Code und Beispielen sowie (c) teils nicht vollständig explizit dokumentierte Datenverträge der Meta‑Domains/Provider. fileciteturn12file0L6-L76 fileciteturn20file0L1-L25 fileciteturn49file0L1-L28

Für die nächste Evolutionsstufe (v5.5b) ist eine fachlich „lohnende“ Ergänzung nicht primär mehr SMC‑Heuristik, sondern **messbare probabilistische Signalqualität**: Regime‑/Volatilitätsmodellierung (Hamilton‑Regime‑Switching; ARCH/GARCH), state‑space/Kalman‑basierte Latents, sowie proper scoring rules (Gneiting/Raftery) für Kalibrierung. citeturn0search1turn0search0turn4search8turn0search48

**Lieferobjekte dieser Antwort:**  
- Konsolidierte Zielarchitektur **v5.5b** als Markdown und Word:  
  - [Download v5.5b Markdown](sandbox:/mnt/data/SMC_Unified_Lean_Architecture_v5_5b.md)  
  - [Download v5.5b Word (.docx)](sandbox:/mnt/data/SMC_Unified_Lean_Architecture_v5_5b.docx)

## Repo‑Extraktion: Architektur, Module, Datenflüsse, Interfaces, I/O, Dependencies, Tests und Performance

### Systemarchitektur und Kernartefakt „SMC Snapshot“

Der SMC‑Kern ist als **Snapshot‑Artefakt** konzipiert, das kanonische Struktur‑Events und additive Kontexte in einem Schema‑validierten Payload bündelt. Die kanonische Struktur ist explizit auf vier Kategorien begrenzt: `bos`, `orderblocks`, `fvg`, `liquidity_sweeps`. fileciteturn46file0L1-L40 fileciteturn95file0  
Diese Kanonizität wird zusätzlich dadurch stabilisiert, dass Events eine **stabile ID** erhalten, die über Quantisierung und ID‑Funktionen gebildet wird (siehe `smc_core/ids.py`). fileciteturn12file0L1-L120

Ein zentrales Designmerkmal ist die **Trennung** zwischen:
- **Canonical Structure Detection** (Detektoren + Profile + Resampling),
- **Contract/Schema/ID‑Governance** (Types, Schema‑Version, Serialization),
- **Layering** (Meta‑Domains → global_heat/global_strength + ZoneStyle‑Overlays),
- **Integration/Delivery** (Provider, Health‑Checks, Bridge/Adapter, CI‑Gates). fileciteturn18file0L1-L60 fileciteturn11file0L1-L70 fileciteturn14file0L1-L70 fileciteturn60file0L1-L80

### Module und Verantwortlichkeiten im Repo

Canonical Detection & Profiles
- `scripts/explicit_structure_from_bars.py`: Aufbau eines kanonischen Bar‑Streams (Resampling/Normalisierung) und Erzeugung der Struktur‑Kategorien aus Bars. fileciteturn18file0L1-L60  
- `scripts/explicit_structure_detectors.py`: Detektoren für OB/FVG/BOS/Sweeps (explizite Regeln, Validity/Mitigation/Invalidation‑Tracking). fileciteturn17file0L1-L80  
- `scripts/explicit_structure_profiles.py`: Profile wie `hybrid_default` und `conservative` steuern Parameter/Filter (z. B. Begrenzung „letzte N Sweeps“). fileciteturn19file0L1-L80  

Core Contract, IDs, Schema, Serialization
- `smc_core/types.py`: zentrale Datentypen für Snapshot/Structure/Meta/Layering, inkl. ZoneStyle‑Konzept. fileciteturn11file0L1-L70  
- `smc_core/serialization.py`: Snapshot‑Serialization als Dict/JSON‑Payload. fileciteturn15file0L1-L80  
- `smc_core/schema_version.py`: Schema‑Version als SemVer; Code setzt derzeit u. a. `SCHEMA_VERSION = "2.0.0"`. ```SCHEMA_VERSION = "2.0.0"``` fileciteturn20file0L1-L12  
- `spec/smc_snapshot.schema.json` + `spec/examples/*`: JSON‑Schema + Beispiel‑Payloads. fileciteturn46file0L1-L40 fileciteturn47file0L1-L25  

Layering / Explainability
- `smc_core/layering.py`: berechnet globale Zustände wie `global_heat`/`global_strength` und erzeugt **ZoneStyles** (Tone/Emphasis/Trade‑State + Reason‑Codes) pro Entity‑ID. fileciteturn14file0L1-L110  

Integration & Delivery
- `smc_integration/service.py`: Orchestrierung zum Erzeugen eines Snapshot‑Bundles pro Symbol/Timeframe. fileciteturn13file0L1-L80  
- Provider/Health: `smc_integration/provider_health.py` implementiert Smoke‑Checks/Staleness‑Validierung und „strict policy“‑Mechanik. fileciteturn60file0L1-L80  
- TV Bridge: `smc_tv_bridge/smc_api.py` stellt FastAPI‑Endpoints bereit (u. a. `/smc_snapshot`, `/smc_tv`). fileciteturn21file0L1-L90  
- Pine Consumer: `SMC_TV_Bridge.pine` konsumiert die Bridge‑Ausgabe und visualisiert BOS/OB/FVG/Sweeps mit UI‑Regeln, die (laut Architektur‑Prinzip) keine „shadow logic“ erzeugen sollen. fileciteturn21file0L1-L120

CI/Release‑Kontrollen
- Fast PR Gates: `.github/workflows/smc-fast-pr-gates.yml` (Python 3.12 in CI). fileciteturn69file0L10-L22  
- Release‑Gates und Deeper‑Integration‑Gates existieren als eigene Workflows. fileciteturn71file0L1-L44 fileciteturn72file0L1-L44  
- Pine Micro‑Library Refresh: `.github/workflows/smc-library-refresh.yml` zeigt eine dedizierte Publishing‑Pipeline (inkl. API‑Keys und Artefakt‑Refresh). fileciteturn73file0L1-L60

### Inputs/Outputs und Datenfluss

Ein robuster, repo‑konformer End‑to‑End‑Fluss lässt sich wie folgt zusammenfassen:

```mermaid
flowchart LR
  A[OHLC(Bars)/Exports] --> B[explicit_structure_from_bars]
  B --> C[Detectors + Profiles]
  C --> D[Canonical Structure\nbos/ob/fvg/sweeps]
  D --> E[IDs + Schema/Types]
  E --> F[Meta Merge + Layering\n(global_heat/ZoneStyles)]
  F --> G[Serialization\nSMC Snapshot JSON]
  G --> H[Adapters\nPine/Dashboard]
  H --> I[FastAPI Bridge\n/smc_snapshot /smc_tv]
  I --> J[TradingView Pine Consumer]
  G --> K[CI Gates\nSchema/Parity/Health]
```

Die Architektur‑Doku v5.5a fordert exakt diese Logik (canonical‑only structure, additive Kontexte, no shadow logic), und der Repo‑Schnitt setzt sie bereits weitgehend in Code/Tests um. fileciteturn95file0 fileciteturn18file0L1-L60 fileciteturn14file0L1-L110 fileciteturn86file0L1-L36

### Dependencies, Runtime und Performance‑Charakteristika

Python/Runtime
- `pyproject.toml` fordert `Python >= 3.12`. ```requires-python = ">=3.12"``` fileciteturn65file0L1-L8  
- CI nutzt ebenfalls Python 3.12 (Fast‑PR‑Gates). fileciteturn69file0L10-L22  
- **Auffälligkeit:** `.devcontainer/devcontainer.json` referenziert ein Python‑3.11‑Image, was mit `>=3.12` kollidieren kann. fileciteturn67file0L1-L10

Wichtige Abhängigkeiten (`requirements.txt`)
- u. a. `pandas`, `databento`, `fastapi`, `uvicorn`, `jsonschema`, `tradingview-ta`, `yfinance`, `streamlit`. fileciteturn70file0L1-L16

Performance/Runtimes (Pine‑Budget)
- Das Repo enthält ein dediziertes Runtime‑Budget‑Dokument (Pine‑Performance als Architektur‑Constraint). fileciteturn50file0L1-L40  
Konkrete harte Laufzeit‑Kennzahlen (z. B. ms/Symbol/Timeframe in CI) sind im Repo‑Iststand **nicht durchgehend als Messwerte** zentral dokumentiert; das ist für v5.5b ein explizites Ergänzungsfeld (siehe Plan unten). fileciteturn50file0L1-L40

Tests (Auszug)
- Schema‑Validation der Snapshot‑Beispiele via `jsonschema`. fileciteturn85file0L1-L40  
- SemVer‑Enforcement / Beispiele müssen zur aktuellen `SCHEMA_VERSION` passen. fileciteturn20file0L1-L25 fileciteturn49file0L1-L28  
- Parity‑Tests (canonical → bridge → Pine) existieren, um Drift zu verhindern. fileciteturn86file0L1-L36  
- Purity/Determinismus‑Tests des Layering (keine Mutation/Side‑Effects). fileciteturn83file0L1-L27 fileciteturn84file0L33-L60

## Abgleich v5.5a vs Code/Docs und konsolidierte Zielarchitektur v5.5b

### Was v5.5a vorgibt

v5.5a ist explizit eine „Schärfung“ von v5.5 (nicht ein Plattform‑Re‑Write) und fordert: lean, generator‑first, canonical‑only structure, **eine primäre Entscheidungssurface** (Lifecycle, Signal‑Quality, Event‑State, Bias, 2–3 Warnings), scoring statt blocking, no shadow logic und Semantik‑Disziplin. fileciteturn95file0

### Was der Repo‑Iststand bereits stark erfüllt

Canonical‑only Structure
- Der Snapshot‑Fokus auf `bos/orderblocks/fvg/liquidity_sweeps` ist im Schema und in den Detektor‑Pipelines sichtbar. fileciteturn46file0L1-L40 fileciteturn18file0L1-L60

Generator‑First + Release‑Gates
- Die Workflow‑Landschaft (Fast PR, Deeper Integration, Release, Library Refresh) implementiert „Generator + Artefakte + Consumer bleiben synchron“ als CI‑Disziplin. fileciteturn69file0L1-L34 fileciteturn73file0L1-L60

No Shadow Logic als Test‑/Contract‑Denke
- Mit Parity‑Tests zwischen canonical und TV‑Delivery ist ein Mechanismus vorhanden, der „shadow logic“ im Consumer zumindest detektierbar macht. fileciteturn86file0L1-L36

### Wo v5.5a und Repo noch nicht „nahtlos“ zusammenliegen

Feld‑Semantik vs Domain‑Model
- v5.5a listet Pflichtfelder für Lean‑Familien (Event Risk Light, Session Context Light, OB Context …). fileciteturn95file0  
- Der Repo modelliert Kontext offensichtlich stärker als **Domains + Layering/ZoneStyles** (statt flacher Feldlisten). fileciteturn11file0L1-L70 fileciteturn14file0L1-L110  
→ Für v5.5b ist daher ein **Mapping‑Layer** nötig: (a) Lean‑Pflichtfelder aus v5.5a, (b) tatsächliche Domain‑Keys/Strukturen aus `types.py`, (c) Berechnungscode/Quellen und (d) Exportkontrakt für Pine/Dashboard.

Governance‑Drift
- Code setzt `SCHEMA_VERSION = "2.0.0"`, während mindestens ein Beispiel‑Snapshot `schema_version: "1.2.0"` zeigt – das ist ein klassischer Drift‑Fehler, der v5.5a‑„Synchronität“ untergräbt. fileciteturn20file0L1-L12 fileciteturn47file0L1-L25

### v5.5b: integrierte Architektur, abgeleitet aus v5.5a + Repo

Ich habe v5.5a inhaltlich beibehalten, aber um Repo‑realistische Contracts/Delivery‑Paths/Gates ergänzt und als **v5.5b** ausgeliefert:

- [Download v5.5b Markdown](sandbox:/mnt/data/SMC_Unified_Lean_Architecture_v5_5b.md)  
- [Download v5.5b Word (.docx)](sandbox:/mnt/data/SMC_Unified_Lean_Architecture_v5_5b.docx)

Die v5.5b‑Fassung stärkt explizit:
- **Schema/ID/Parity als Architektur‑Constraint** (nicht nur Engineering),
- **Delivery‑Dualität** (FastAPI‑Bridge + Pine‑Micro‑Library Refresh),
- **sichtbare ToDos statt stiller Unschärfe** (Ticksize/Session‑Awareness, HTF‑Bias Single Source of Truth). fileciteturn12file0L36-L76 fileciteturn22file0L1-L60 fileciteturn23file0L1-L60

## Vergleichbare SMC/Forecast‑Skripte und Libraries

Wichtig: Für „SMC“ existiert im Web eine Doppelbedeutung. In Trading‑Communities ist SMC häufig *Smart Money Concepts*; in Statistik/Forschung ist SMC oft *Sequential Monte Carlo* (Particle Filters). Für euren Use‑Case sind beide relevant: Eure Struktur‑Erkennung ist Smart‑Money‑artig, aber die Verbesserung der Prognose‑/Qualitätslayer kann von SMC/Particle‑Filter‑Literatur massiv profitieren. citeturn5search12turn5search15

### Vergleichstabelle

| Name | Quelle | Sprache | Lizenz | Kern‑Algorithmen | Datenanforderungen | Stärken | Schwächen | Relevanz für `skipp`‑SMC |
|---|---|---|---|---|---|---|---|---|
| Smart Money Concepts (SMC) [LuxAlgo] | TradingView Script‑Page citeturn1search1 | Pine Script | „Open‑source script“ (TradingView‑House‑Rules) citeturn1search1 | BOS/CHoCH (internal/swing), OB, FVG, EQH/EQL, PD‑Zonen, Confluence‑Filter | OHLCV in TradingView | De‑facto Benchmark für Features/UX; hohe Adoption | Regeln/Validierung nicht wissenschaftlich; Pine‑Constraints | **Sehr hoch** als Feature‑/UX‑Benchmark und Parity‑Referenz |
| ICT Concepts (Liquidity, FVG & Sweeps) | TradingView (de) citeturn1search2 | Pine Script | Invite‑only (nicht auditierbar) citeturn1search0 | Liquidity‑Sweep + Volumenfilter, FVG‑3‑Candle‑Regeln, Swing‑Structure Proxy | OHLCV + Volume | Fokus auf Sweeps+FVG; Performance‑Optimierungen erwähnt | Black‑box, schwer vergleichbar | **Mittel** als alternative Heuristik‑Inspiration |
| statsmodels | PyPI citeturn1search4 | Python | BSD citeturn1search4 | State‑Space, SARIMAX/ARIMA, Kalman‑basierte Schätzer | Zeitreihen + optional exogene Features | akademisch fundiert; baseline & state‑space | nicht „SMC‑nativ“, braucht Feature‑Engineering | **Hoch** als Kalman/State‑Space‑Backbone für Meta‑/Quality‑Layer |
| arch | PyPI citeturn3search8 | Python | NCSA citeturn3search8 | ARCH/GARCH, Bootstraps, Finance‑Econometrics Tools | Returns / Residuals | Volatilitäts‑Forecasts „first class“, performance‑optimiert | Modellannahmen müssen sauber geprüft werden | **Sehr hoch** für Vol‑Regime, Risk‑Gates, Signal‑Kalibrierung |
| FilterPy | PyPI citeturn2search8 | Python | MIT citeturn2search8 | Kalman/EKF/UKF, Smoother, Bayes Filters | State‑Space Formulierung | schnelles Prototyping, modular | Modellwahl/Parameter bei euch | **Mittel** (Toolkit für Latents/Noise‑Robustheit) |
| PyMC | PyPI citeturn3search3 | Python | Apache‑2.0 citeturn3search3 | Bayes‑Modelle, MCMC/VI | Features + Priors + Daten | Unsicherheit/Kalibrierung stark | compute‑intensiv, Engineering‑Aufwand | **Mittel–hoch** für echte Probabilistik (P(reversal|features)) |
| Prophet | PyPI citeturn3search13 | Python | MIT citeturn3search13 | Additives Modell (Trend + Saison + Holidays) | Zeitstempel‑Serie, saisonale Struktur | robust, schnell baseline | Intraday‑SMC oft unpassend | **Niedrig–mittel** eher HTF/Seasonality‑Kontext |
| pmdarima | PyPI citeturn3search12 | Python | (PyPI‑Metadaten; im Snippet nicht sichtbar) citeturn3search12 | auto.arima, Stationarity Tests, CV Utilities | Zeitreihen | schnelle, solide Baseline | nur indirekt zu SMC‑Events | **Mittel** als Baseline/Benchmark |
| Darts | PyPI citeturn3search4 | Python | Apache‑2.0 citeturn3search4 | Multi‑Model Forecasting + Backtesting + Ensembles | uni-/multivariate TS + Regressors | Backtest/Ensemble out‑of‑box | „großes Framework“ | **Mittel** als Research‑Harness für Forecast‑Layer |
| pytorch‑forecasting | PyPI citeturn3search7 | Python | MIT citeturn3search7 | Deep TS Modelle (u. a. TFT, N‑BEATS) | große Datensets, Covariates | modern, probabilistisch | Komplexität; Risiko von Overfitting | **Mittel** für Research‑Prototyping von Quality‑Forecast |

## Relevante akademische Arbeiten zu Forecasting und konkrete Anwendbarkeit auf euer SMC

### State‑Space / Kalman‑Filter (Latents für Trend/Noise/Confidence)

**Kalman (1960)** – *A New Approach to Linear Filtering and Prediction Problems* (Journal of Basic Engineering, DOI 10.1115/1.3662552). citeturn5search15turn5search9  
**Kernidee:** lineares Gauß‑State‑Space  
\[
x_t = A x_{t-1} + w_t,\; w_t\sim \mathcal N(0,Q),\qquad
y_t = H x_t + v_t,\; v_t\sim \mathcal N(0,R)
\]  
**Anwendung auf euer SMC:**  
Euer Layering erzeugt global_heat/global_strength und ZoneStyles. fileciteturn14file0L1-L110  
Kalman/State‑Space kann hier ein **latentes Trend‑Signal** und eine **Noise‑/Confidence‑Komponente** liefern, sodass „Signal Quality“ nicht nur heuristisch ist, sondern als geglätteter Zustand mit Unsicherheit (z. B. \(P(|trend|>\tau)\)) in Tier‑Scoring und Warnings eingeht.

### Sequential Monte Carlo / Particle Filter (nichtlinear, heavy‑tail, Regime‑Noise)

**Gordon, Salmond & Smith (1993)** – *Novel approach to nonlinear/non‑Gaussian Bayesian state estimation* (IEE Proceedings, DOI 10.1049/ip-f-2.1993.0015). citeturn5search12turn5search3  
**Key Algorithmus:** Bootstrap/Particle Filter approximiert \(p(x_t\mid y_{1:t})\) mit Partikeln und Resampling:  
\[
w_t^{(i)} \propto w_{t-1}^{(i)}\,p(y_t\mid x_t^{(i)}),\quad \text{Resample gegen Degenerierung}
\]  
**Anwendung auf euer SMC:**  
Für Intraday‑Mikrostruktur sind Nichtlinearität und heavy tails typisch. Ein Partikelfilter kann „latent volatility + latent drift + event shock“ schätzen und als probabilistischer Kontext in die Layering‑Logik einspeisen (statt harter Schwellen). Das ist besonders passend, weil euer System ohnehin „Probability Forecast“ als Roadmap‑Ziel nennt. fileciteturn7file0L24-L41

### Regime‑Switching (Markov‑Regimes für Trend/Range‑Wechsel)

**Hamilton (1989)** – *A New Approach to the Economic Analysis of Nonstationary Time Series and the Business Cycle* (Econometrica). citeturn0search1  
**Kernidee:** Parameter einer AR‑Dynamik hängen von latentem Regime \(s_t\) (Markov‑Kette) ab; liefert Regime‑Posterior.  
**Anwendung auf euer SMC:**  
Ihr habt bereits Session‑/HTF‑Kontextmodule. fileciteturn22file0L1-L60 fileciteturn23file0L1-L60  
Regime‑Switching kann „Trend vs Range“ oder „High‑Vol vs Low‑Vol“ als Posterior liefern, um:  
1) Detektor‑Schwellen (z. B. „significant move“) profil‑abhängig zu machen, fileciteturn19file0L1-L80  
2) Signal‑Quality‑Tier nach Regime zu kalibrieren (z. B. Sweeps in Range‑Regime anders gewichten).

### Volatilitätsmodelle (ARCH/GARCH) und stochastische Volatilität

**Engle (1982)** – ARCH (Econometrica). citeturn0search0  
**Bollerslev (1986)** – GARCH (Journal of Econometrics, DOI 10.1016/0304-4076(86)90063-1). citeturn4search8  
Exemplarisch GARCH(1,1):  
\[
\sigma_t^2=\omega+\alpha \epsilon_{t-1}^2+\beta \sigma_{t-1}^2
\]  
**Heston (1993)** – stochastische Volatilität / characteristic functions (RFS, DOI 10.1093/rfs/6.2.327). citeturn4search0  
**Anwendung auf euer SMC:**  
Volatilität ist ein zentraler Gate‑Faktor für „False Positives“ (FVG/OB‑Invalidation, Sweep‑Noise). `arch` ist als Library passend, weil es Volatilitätsmodelle plus Bootstraps bietet und performance‑optimiert ist. citeturn3search8  
Das Ergebnis (Vol‑Forecast, Vol‑Regime) sollte als Meta‑Domain in den Snapshot und in die Tier‑/Warning‑Logik einfließen (anstatt „thin_fraction“/Heuristiken allein). fileciteturn14file0L1-L110

### Proper Scoring Rules (Probabilistische Forecast‑Qualität messbar machen)

**Gneiting & Raftery (2007)** – *Strictly Proper Scoring Rules, Prediction, and Estimation* (JASA). citeturn0search48turn0search7  
**Kernidee:** proper scoring rules (Log Score, Brier Score, CRPS) erzwingen „ehrliche“ Wahrscheinlichkeitsprognosen.  
**Anwendung auf euer SMC:**  
Wenn „Signal Quality“ in Richtung *probabilistic forecast* entwickelt werden soll, muss sie kalibriert und mit proper scores bewertet werden (nicht nur Trefferquote). Das passt direkt zu eurer CI‑Gate‑Mentalität: Scores können als Release‑Gate‑Artefakte versioniert werden. fileciteturn73file0L1-L60

### ML‑Forecasting (DeepAR / N‑BEATS / TFT) als Research‑Option

**DeepAR (Salinas/Flunkert/Gasthaus, 2017)** – probabilistisches Forecasting mit autoregressivem RNN (arXiv:1704.04110). citeturn2search5  
**N‑BEATS (Oreshkin et al., 2019)** – residual stacks für univariate Forecasts (arXiv:1905.10437). citeturn3search2  
**Temporal Fusion Transformer (Lim et al., 2019/2021)** – multi‑horizon Forecasting, interpretable attention (arXiv:1912.09363; IJF Version). citeturn2search1turn2search3  
**Anwendung auf euer SMC:**  
Diese Modelle sind weniger für „detektive“ SMC‑Events, aber sehr geeignet als **probabilistische Layer**: z. B. Forecast von „Range/Volatility/expected move“ oder \(P(\text{mean reversion}\mid features)\), die dann in ZoneStyles/Tiers übersetzt werden.

### Ensembles (stabile Verbesserungen statt „one model to rule them all“)

**Bates & Granger (1969)** – *The Combination of Forecasts* (JORS, DOI 10.1057/jors.1969.103). citeturn4search13  
**Anwendung auf euer SMC:**  
Ein Ensemble aus (a) GARCH‑Vol‑Forecast, (b) Regime‑Switching Posterior, (c) Kalman‑Trend, (d) heuristischen SMC‑Events kann in Summe deutlich robuster sein als ein einzelner Ansatz – und passt zu v5.5a („qualifizieren statt blockieren“, „Verdichtung statt Feldwachstum“). fileciteturn95file0

## Konkrete, priorisierte Verbesserungen und Integrationen

### Priorisierte Roadmap (Aufwand/Nutzen)

| Prio | Verbesserung | Konkrete Integration im Repo | Aufwand | Erwarteter Nutzen |
|---|---|---|---|---|
| P0 | **Schema‑Drift eliminieren** | `schema_version.py` ↔ `spec/examples/*` konsistent machen; Test `test_smc_schema_version_enforcement` muss hart failen | niedrig | verhindert silent breaking changes; stabilisiert Delivery/Parity fileciteturn20file0L1-L25 fileciteturn49file0L1-L28 |
| P0 | **Ticksize/Session‑Awareness in IDs** | `smc_core/ids.py`: `quantize_price` ticksize‑aware, `quantize_time_to_tf` exchange‑aware (kein UTC‑Tages‑TODO) | mittel | stabile IDs across markets; weniger Phantom‑Diffs/False Parity Breaks fileciteturn12file0L36-L76 |
| P0 | **Runtime‑Umgebung konsolidieren** | `.devcontainer` auf Python 3.12 anheben oder `pyproject` absenken (entscheidet bewusst) | niedrig | weniger „works in CI, fails locally“ fileciteturn65file0L1-L8 fileciteturn67file0L1-L10 |
| P1 | **HTF/Session‑Kontrakt als Single Source of Truth** | Session/HTF‑Module vereinheitlichen; Tests für Bias‑Konsistenz hinzufügen | mittel | weniger widersprüchliche Bias‑Signale in Scoring/Warnungen fileciteturn22file0L1-L60 fileciteturn23file0L1-L60 |
| P1 | **Volatilitäts‑Regime als Meta‑Domain** | `arch`‑basierter vol_forecast + regime label in Meta; Layering nutzt das in `global_strength`/Tier‑Downgrade | hoch | bessere False‑Positive‑Kontrolle, smartere Risk‑Gates citeturn3search8turn0search0turn4search8 fileciteturn14file0L1-L110 |
| P1 | **Probabilistische Signal‑Kalibrierung + proper scores** | Label‑Definition pro Eventfamilie (Sweep/FVG/OB/BOS); Brier/LogScore als Gate‑Artefakt | hoch | „Signal Quality“ wird messbar, kalibrierbar und CI‑fähig citeturn0search48 |
| P2 | **Benchmarks/Backtests standardisieren** | Pro Symbol/TF: event‑lifecycle KPIs + regime‑stratifizierte Auswertung; Artefakte versionieren | mittel | klare Evidenz pro Feature/Heuristik; schneller iterieren |
| P2 | **Ensemble‑Quality‑Score** | Weighted stacking (Bates‑Granger‑Prinzip) über (Kalman trend, GARCH vol, regimes, heuristics) | mittel | robustere Qualität ohne Feature‑Sprawl citeturn4search13 fileciteturn95file0 |

### Beispiel: „qualify, don’t block“ als konkrete Implementierungsregel

v5.5a fordert scoring statt blocking. fileciteturn95file0  
Im Repo ist das technisch vorbereitet durch Layering/ZoneStyles (Reason‑Codes, global_heat/global_strength). fileciteturn14file0L1-L110  
v5.5b sollte daraus eine harte Policy machen: **Hard blocks** nur bei invalid data/provider health failure, ansonsten Tier‑Downgrade + 1–3 Warnings.

## Implementierungs‑ und Validierungsplan inklusive CI/Schema‑Checks, Tests, Benchmarks, Visualisierungen und Risiken

### Implementierungsplan (Ressourcen und Timeline)

Empfohlenes Minimal‑Team: 1 Python Engineer (Core/Integration), 1 Research/Quant Engineer (Forecast/Kalibrierung), optional 0.5 DevOps/CI. (Ressourcen sind im Repo nicht konkret spezifiziert; diese Annahme ist eine Planungsannahme.) fileciteturn95file0

```mermaid
gantt
  title v5.5b Umsetzung (12 Wochen, Start 2026-04-01)
  dateFormat  YYYY-MM-DD
  axisFormat  %d.%m

  section Governance (P0)
  Schema-Drift fix + Beispiele aktualisieren :g1, 2026-04-01, 7d
  ID Quantisierung ticksize/session aware    :g2, after g1, 14d
  Devcontainer/Runtime konsolidieren         :g3, after g2, 5d

  section Konsistenz (P1)
  HTF/Session Single Source of Truth         :c1, 2026-04-22, 14d
  Layering-Policy (no hard blocks)            :c2, parallel c1, 10d

  section Forecast/Calibration (P1)
  Vol-Regime MVP (arch)                      :f1, 2026-05-06, 18d
  Labeling + Proper Scores (Brier/Log)       :f2, after f1, 18d

  section Benchmarks & Release Gates (P2)
  Backtest Harness + Artefakte               :b1, 2026-06-11, 14d
  CI-Gates erweitern (Score Thresholds)      :b2, after b1, 10d
  Shadow Deploy + Monitoring                 :b3, after b2, 7d
```

### Plan zur CI‑/Schema‑Validierung für v5.5b

Da v5.5b ein Architektur‑Dokument ist, besteht die technische Validierung primär aus „Repo passt zur Architektur“:

1) **Schema‑Validation**: `pytest -q` muss `test_smc_snapshot_schema.py` und die Schema‑Version‑Enforcement‑Tests grün liefern. fileciteturn85file0L1-L40 fileciteturn49file0L1-L28  
2) **Parity‑Validation**: Parity‑Tests müssen kanonische Outputs ↔ Bridge ↔ Pine konsistent halten. fileciteturn86file0L1-L36  
3) **Provider Health**: `provider_health.py`‑Checks als Gate in Fast/Deeper/Release. fileciteturn60file0L1-L80  
4) **Workflow‑Pfad**: mindestens `smc-fast-pr-gates.yml` und `smc-release-gates.yml` müssen v5.5b‑Constraints (no drift, no shadow logic via parity) indirekt enforce’n. fileciteturn69file0L1-L34 fileciteturn71file0L1-L44

### Empfohlene Tests, Benchmarks und Visualisierungen (Charts/Plots) für die Verbesserungen

Tests
- **ID‑Stabilität über Exchangekalender/Ticksize** (Property‑Tests): gleiche Bars → gleiche IDs; monotone buckets; edge cases an Session‑Grenzen. fileciteturn12file0L36-L76  
- **Layering‑Determinismus**: bereits ansatzweise getestet; erweitern um neue Meta‑Domains/Vol‑Regime. fileciteturn83file0L1-L27  

Benchmarks (Empfehlung als Artefakt‑Set)
- Event‑Familien getrennt: BOS/OB/FVG/Sweeps jeweils mit eigenen KPIs (Hit‑Rate, time‑to‑mitigation, invalidation rate, adverse excursion). fileciteturn17file0L1-L80  
- Stratifizierung nach Session/HTF‑Bias und Vol‑Regime. fileciteturn22file0L1-L60 citeturn0search1turn3search8

Visualisierungen, die ihr explizit erzeugen/als CI‑Artefakte speichern solltet
- **Calibration curve / Reliability diagram** für probabilistische „Signal Quality“‑Outputs (vor/nach Kalibrierung). citeturn0search48  
- **Regime‑Posterior over time** (Hamilton‑Regime oder Vol‑Regime) und Overlays auf SMC‑Events. citeturn0search1turn0search0  
- **Profit/Drawdown‑Distributions** *pro Tier* (nicht nur overall), um „Tier semantics integrity“ zu prüfen. fileciteturn95file0  
- **Runtime budget plots** (Pine/Bridge): z. B. Render‑Count vs Timeframe, max_bars_back constraints – passend zum Runtime‑Budget‑Dokument. fileciteturn50file0L1-L40

Pseudocode‑Skizze (eigener Code, nicht Repo‑Zitat): probabilistische Kalibrierung „Reversal nach Sweep“
```python
# 1) Extrahiere Events (sweeps) und Features zur Eventzeit
X, y = [], []
for sweep in sweeps:
    feats = {
        "side": sweep.side,
        "vol_regime": vol_model.regime_at(sweep.t0),
        "news_heat": meta.news.heat_at(sweep.t0),
        "fvg_distance": nearest_fvg_distance(sweep.t0),
        "session": session_bucket(sweep.t0),
    }
    label = reversal_within_n_bars(bars, sweep.t0, n=8)
    X.append(feats); y.append(label)

# 2) Trainiere ein Kalibrationsmodell (z.B. logistic/Bayes)
model.fit(X_train, y_train)

# 3) Evaluiere mit proper scoring rules
brier = brier_score(model.predict_proba(X_test), y_test)
logscore = log_score(model.predict_proba(X_test), y_test)
```

### Risiken und Limitationen

- **Begriffsrisiko SMC:** Smart‑Money‑SMC ist nicht akademisch standardisiert; Implementation‑Details sind community‑abhängig. LuxAlgo weist selbst darauf hin, dass es keine harte Evidenz für die „Institutional“‑Interpretation gibt. citeturn1search1  
- **Overfitting‑Risiko bei Forecast‑Layern:** Volatilitäts‑/Regime‑/Deep‑Modelle können schnell auf historische Besonderheiten overfitten; proper scoring rules + out‑of‑sample‑Protokoll sind zwingend. citeturn0search48turn0search0turn0search1  
- **Operational Risk durch Provider/Secrets:** Der Library‑Refresh‑Workflow hängt an externen APIs/Secrets; Staleness/Fehlkonfiguration kann Release‑Pipelines destabilisieren. fileciteturn73file0L1-L60  
- **ID‑/Zeit‑Semantik bleibt kritisch:** Solange Ticksize und Exchange‑Sessions nicht sauber gelöst sind, bleibt ID‑Stabilität und Cross‑TF‑Konsistenz ein strukturelles Risiko. fileciteturn12file0L36-L76  
- **Performance‑Constraints (Pine):** Jede Erweiterung muss Pine‑Runtime‑Budget respektieren; sonst leidet UX und damit die Produktqualität (v5.5a‑Prinzip). fileciteturn50file0L1-L40 fileciteturn95file0