# Open Prep Suite — Vollständige technische Referenz

Stand: 25.02.2026  
Codebasis: `open_prep/` + Integration `newsstack_fmp/`

---

## 1) Zielbild der Suite

Die `open_prep`-Suite erzeugt einen reproduzierbaren, vorbörslichen Entscheidungs-Output für US-Aktien mit Fokus auf:

- robustem **Data Ingest** (Macro, Quotes, Premarket, News, Events),
- deterministischem **Scoring** (v1 + v2),
- **Regime- und Risk-Guardrails**,
- operativer **Realtime-Überwachung**,
- vollständig serialisierbaren **Output-Contracts** für UI/Automation.

Primärer Einstiegspunkt ist:

- `open_prep.run_open_prep.generate_open_prep_result(...)`

Realtime-Erweiterung:

- `open_prep.realtime_signals.RealtimeEngine`

News-Enrichment-Engine:

- `newsstack_fmp.pipeline.poll_once(...)`

---

## 2) High-Level Architektur

Die Suite ist als modulare Pipeline aufgebaut:

1. **Universe-Auflösung** (statisch oder FMP-Screener + Movers)  
2. **Capability-Probing** der Datenendpunkte  
3. **Macro-Kontext** + Bias + Explainability  
4. **News-Catalyst Scoring**  
5. **Quote/GAP/ATR/Momentum Enrichment**  
6. **Premarket Kontext** (Freshness, Spread, Earnings-Risiko etc.)  
7. **Corporate/Analyst/Ownership Enrichment**  
8. **Gap-Klassifikation (GO/WATCH/SKIP)**  
9. **Ranking v1 + Ranking v2**  
10. **Regime-Adaption + Playbook + Outcomes/Diff/Alerts/Watchlist**  
11. **Trade Cards + Persistenz + Runtime Status**

Die Pipeline ist bewusst fail-open designt: optionale Subsysteme degradieren mit Warnung statt Hard-Crash, wo sinnvoll.

---

## 3) Hauptorchestrator: `run_open_prep.py`

Datei: `open_prep/run_open_prep.py`

### 3.1 Zentrale API

- `generate_open_prep_result(...)` ist die zentrale API.
- Unterstützt CLI/Service/Streamlit-Mode und optional `progress_callback(stage, total, label)`.

### 3.2 Konfigurationsmodell

Dataclass: `OpenPrepConfig`

Wesentliche Felder:

- Universe: `symbols`, `universe_source`, `fmp_min_market_cap`, `fmp_max_symbols`
- Timing: `days_ahead`, `pre_open_only`, `pre_open_cutoff_utc`
- Gap: `gap_mode` (`RTH_OPEN`, `PREMARKET_INDICATIVE`, `OFF`), `gap_scope` (`DAILY`, `STRETCH_ONLY`)
- ATR: `atr_lookback_days`, `atr_period`, `atr_parallel_workers`
- Output: `top`, `trade_cards`, `max_macro_events`

### 3.3 Universe-Auflösung

- `_resolve_symbol_universe(...)`
- Quellen:
  - statische Fallback-Liste (`DEFAULT_UNIVERSE`)
  - FMP US Mid/Large Screener + Movers-Seed
- Upper Bound Schutz: `MAX_PREMARKET_UNION_SYMBOLS = 1200`

### 3.4 Gap-System

- `apply_gap_mode_to_quotes(...)`
- Scope-/Session-Logik über US-Handelstage und Stretch-Detektion.
- Evidenzfelder in Kandidaten:
  - `gap_available`, `gap_reason`, `gap_from_ts`, `gap_to_ts`, `gap_scope`, `gap_type`

### 3.5 Runtime/Resilienz

- Stage-Profiling via `StageProfiler`
- Runtime-Status inkl. Warnkette via `_build_runtime_status(...)`
- Atomic Write für Latest-Run-Artefakt:
  - `artifacts/open_prep/latest/latest_open_prep_run.json`

---

## 4) Datenquellen und API-Layer

### 4.1 FMP Client und Circuit Breaker

Datei: `open_prep/macro.py`

- `FMPClient` kapselt alle FMP-Zugriffe.
- Circuit Breaker (`CircuitBreaker`) Zustände:
  - `CLOSED`, `OPEN`, `HALF_OPEN`, `HALF_OPEN_TESTING`
- Schutz vor API-Hammering bei Ausfällen.
- Retry mit Exponential Backoff + Jitter.

### 4.2 Macro-Kalender, Bias und Explainability

Datei: `open_prep/macro.py`

- Ereignisfilterung: US-Relevanz, Impact-Klassen, deduplizierte Canonical Events.
- Bias-Output: `macro_bias_with_components(...)`
- Explainability im Payload:
  - `macro_score_components[]`
  - inkl. `canonical_event`, `consensus`, `surprise`, `weight`, `contribution`, `data_quality_flags`, optional `dedup`.

### 4.3 BEA-Audit für PCE-Release

Datei: `open_prep/bea.py`

- Trigger-basierte Audit-Entscheidung (`should_audit_pce_release(...)`).
- Fail-open URL-Auflösung der aktuellen BEA-Publikation.
- Payload: `build_bea_audit_payload(...)`.

### 4.4 News-Katalysator

Datei: `open_prep/news.py`

- Symbol-Matching über Ticker-Metadaten + fallback Titel-Token.
- Sentiment-Klassifikation (`classify_article_sentiment`) per Domain-Keywords.
- Event-/Recency-/Source-Enrichment via `playbook`-Primitiven:
  - `classify_news_event`, `classify_recency`, `classify_source_quality`.
- Per-Symbol-Output:
  - `news_catalyst_score`, `sentiment_*`, `event_*`, `source_tier`, `articles[]` (max 5, newest-first).

---

## 5) Ranking & Scoring

### 5.1 Legacy-Ranker v1

Datei: `open_prep/screen.py`

- `rank_candidates(...)`
- Klassische gewichtete Score-Komponenten (Gap/RVOL/Macro/Momentum/News etc.)
- Long-Gate-Hardblocks:
  - z. B. `price_below_5`, `severe_gap_down`, `macro_risk_off_extreme`, `split_today`, `ipo_window`.
- Gap-Bucketing:
  - `classify_long_gap(...)` → `GO/WATCH/SKIP`
- Warn-Flags:
  - `compute_gap_warn_flags(...)` (z. B. `gap_down_falling_knife`, `warn_spread_wide`, `warn_premarket_stale`).

### 5.2 Erweiterter v2-Ranker (2-Stage)

Datei: `open_prep/scorer.py`

1) **Filter-Stage** (`filter_candidate`)  
2) **Score-Stage** (`score_candidate`)  

Feature-Highlights:

- Gewichtssets: `load_weight_set(...)`, `save_weight_set(...)`
- Sector-relative Komponente (`compute_sector_relative_gap`)
- Freshness-Decay (aus `signal_decay`)
- EWMA-Signalintegration (`_compute_ewma_feature`)
- Diminishing Returns / Component Caps
- Risk-Penalty + Counter-Trend Penalty
- Entry Probability (`compute_entry_probability`)
- Confidence Tiering (`HIGH_CONVICTION`, `STANDARD`, `WATCHLIST`)
- Adaptive Gates (warn-only, fail-open)

### 5.3 Dirty-Flag Caching

Datei: `open_prep/dirty_flag_manager.py`

- `PipelineDirtyManager` verhindert unnötige Re-Scorings
- Fingerprint auf score-relevanten Features
- Statistiken: Cache Hits/Misses

---

## 6) Regime-Engine

Datei: `open_prep/regime.py`

- Marktregime:
  - `RISK_ON`, `RISK_OFF`, `ROTATION`, `NEUTRAL`
- Inputs:
  - Macro Bias, VIX, Sector Breadth
- Hysterese:
  - `_prev_regime` + VIX Dead-Zone Schutz gegen Flapping
- State Hygiene:
  - `reset_regime_state()` wird pro Run aufgerufen
- Gewichtsanpassung:
  - `apply_regime_adjustments(...)`

---

## 7) Technical-Analysis Subsystem

Datei: `open_prep/technical_analysis.py`

Implementierte Kernfunktionen:

- `calculate_support_resistance_targets(...)`
- `apply_diminishing_returns(...)`
- `compute_risk_penalty(...)`
- `classify_instrument(...)`
- `compute_adaptive_gates(...)`
- `detect_consolidation(...)`
- `detect_breakout(...)`
- `validate_data_quality(...)`
- `GateTracker`
- `detect_symbol_regime(...)`
- `compute_entry_probability(...)`
- `calculate_ewma(...)`, `calculate_ewma_metrics(...)`, `calculate_ewma_score(...)`
- `resolve_regime_weights(...)` (defensive copy, keine In-Place-Mutation)

---

## 8) Playbook-Engine & Trade Cards

### 8.1 Playbook-Zuordnung

Datei: `open_prep/playbook.py`

- Engine: `assign_playbook(...)`, `assign_playbooks(...)`
- Mögliche Playbooks:
  - `GAP_AND_GO`, `GAP_FADE`, `POST_NEWS_DRIFT`, `NO_TRADE`
- Bewertungsfunktionen:
  - `_compute_gap_go_score`, `_compute_fade_score`, `_compute_drift_score`
- Microstructure/Execution:
  - `_execution_quality`, `_no_trade_zone`
- Konkrete Entry/Inval/Exit/Horizon Regeln je Playbook

### 8.2 Trade Cards

Datei: `open_prep/trade_cards.py`

- `build_trade_cards(...)`
- Enthält:
  - `setup_type`, `entry_trigger`, `invalidation`, `trail_stop_atr`, `key_levels`
- Optional S/R + Targets mit Daily Bars.

---

## 9) Realtime Signals

Datei: `open_prep/realtime_signals.py`

### 9.1 Kernobjekte

- `RealtimeEngine`
- `RealtimeSignal`
- `QuoteDeltaTracker`
- `VolumeRegimeDetector`
- `DynamicCooldown`
- `GateHysteresis`
- `ScoreTelemetry`
- `AsyncNewsstackPoller`

### 9.2 Betriebsmodus

- Polling der Top-Kandidaten (`DEFAULT_POLL_INTERVAL=45s`)
- Signallevel:
  - `A0` (immediate), `A1` (watch)
- Persistenz:
  - `latest_realtime_signals.json`
  - `latest_vd_signals.jsonl` (VisiData)
- Marktzeit-Gate: 04:00–20:00 ET (Mo–Fr)

### 9.3 Guardrails

- Signal-Aging (`MAX_SIGNAL_AGE_SECONDS`)
- A0 Cooldown (`A0_COOLDOWN_SECONDS`)
- Thin-volume Regime-Suspend/Relax
- NaN-safe JSON serialization (`allow_nan=False`)

---

## 10) Alerts, Diff, Outcomes, Watchlist

### 10.1 Alerts

Datei: `open_prep/alerts.py`

- Zieltypen: TradersPost, Slack, Discord, Generic Webhook
- Config: `artifacts/open_prep/alert_config.json`
- Throttle pro Symbol mit Speicherbegrenzung

### 10.2 Diff-Ansicht

Datei: `open_prep/diff.py`

- Vergleich vorheriger vs. aktueller Run
- Delta-Kategorien:
  - New Entrants, Dropped, Score Changes, Regime Change, Sector Rotations

### 10.3 Outcomes + Feature Importance

Datei: `open_prep/outcomes.py`

- Daily Outcome Snapshots
- Bucketed Hit Rates (Gap + RVOL)
- Feature Importance Collector + Offline Report

### 10.4 Watchlist

Datei: `open_prep/watchlist.py`

- Persistente Liste + Dateilock
- `auto_add_high_conviction(...)`
- CRUD-Funktionen für manuell/automatisch gepinnte Symbole

---

## 11) Monitoring UI (Streamlit)

Datei: `open_prep/streamlit_monitor.py`

Features:

- Auto-Refresh inkl. Cooldown/Rate-Limit-Handling
- Pipeline-Progressanzeige (`progress_callback`)
- Dashboard-Sektionen für:
  - Realtime Signals
  - v2 Tiered Candidates
  - Gap GO/WATCH
  - Earnings
  - Regime + Sector Performance
  - News Stack Integration
  - Trade Cards, Tomorrow Outlook, Diff, Watchlist, Runtime-Warnungen
- Soft-Refresh über Streamlit Fragments

---

## 12) `newsstack_fmp` Integration

Relevante Dateien:

- `newsstack_fmp/pipeline.py`
- `newsstack_fmp/ingest_fmp.py`
- `newsstack_fmp/ingest_benzinga.py`
- `newsstack_fmp/normalize.py`
- `newsstack_fmp/scoring.py`
- `newsstack_fmp/store_sqlite.py`
- `newsstack_fmp/enrich.py`
- `newsstack_fmp/open_prep_export.py`

### 12.1 Zweck

`newsstack_fmp` baut eine deduplizierte, novelty-gewichtete News-Kandidatenliste, die in `open_prep` (Realtime + Streamlit) konsumiert wird.

### 12.2 Kernmechanik

- Multi-Source Ingest (FMP + optional Benzinga REST/WS)
- Provider-Cursor + dedup (`mark_seen`)
- Cluster/Novelty (`cluster_touch`)
- Scoring + optional URL-Enrichment (mit Budget)
- Export mit Atomic Write

---

## 13) Security, Compliance, Stabilität

### 13.1 Log-Redaction

Datei: `open_prep/log_redaction.py`

- Maskiert API-Keys, Token, E-Mails, Auth-Header, typische Secret-Patterns.
- Aktivierung zentral über `apply_global_log_redaction()`.

### 13.2 Error Taxonomy + Retry

Datei: `open_prep/error_taxonomy.py`

- Typed Exceptions: `FMPDataError`, `ScoringError`, `SignalError`, `ConfigError`
- `@retry(...)` mit Jitter + Filterung retrybarer Exceptions

### 13.3 Config Validation

Datei: `open_prep/config_validation.py`

- `validate_weights(...)`
- `validate_config(...)`
- `compute_config_diff(...)`

### 13.4 Atomic Persistence

Standardmuster in der Suite:

- tempfile schreiben
- flush/fsync
- `os.replace(...)`

Dadurch keine partiell geschriebenen JSON-Artefakte bei Crash/Interrupt.

---

## 14) Output-Contract (Run-Payload)

Wichtige Top-Level Felder aus `_build_result_payload(...)`:

- Metadaten:
  - `schema_version`, `code_version`, `inputs_hash`, `run_datetime_utc`, `active_session`
- Makro:
  - `macro_bias`, `macro_score_components`, `macro_us_high_impact_events_today`, `bea_audit`
- Markt-/Premarketdaten:
  - `atr14_by_symbol`, `momentum_z_by_symbol`, `premarket_context`, `atr_fetch_errors`
- Rankings:
  - `ranked_candidates` (v1)
  - `ranked_v2`, `filtered_out_v2` (v2)
  - `ranked_gap_go`, `ranked_gap_watch`, `ranked_gap_go_earnings`
- Execution:
  - `trade_cards`, `trade_cards_v2`, `tomorrow_outlook`
- Ops:
  - `run_status`, `stage_timings`, `diff`, `alert_results`, `watchlist`, `historical_hit_rates`
- Capability:
  - `data_capabilities`, `data_capabilities_summary`

---

## 15) Betriebsmodi

### 15.1 CLI

- `python -m open_prep.run_open_prep ...`
- erzeugt JSON auf stdout + aktualisiert latest Artefakt.

### 15.2 Streamlit

- `streamlit run open_prep/streamlit_monitor.py`

### 15.3 Realtime Signale

- `python -m open_prep.realtime_signals --interval 45`
- optional schnellere Modi (`--fast`, `--ultra`)

---

## 16) Erweiterungspunkte

Für neue Features sind folgende Integrationspunkte am stabilsten:

- Neue Score-Features in `scorer.filter_candidate(...)` + `score_candidate(...)`
- Neue Macro-Regeln in `macro_bias_with_components(...)`
- Neue Playbook-Typen in `playbook.assign_playbook(...)`
- Zusätzliche Alert-Targets in `alerts._FORMATTERS`
- Neue Realtime-Rails in `realtime_signals._detect_signal(...)`

Empfehlung:

- Feature immer durch `run_status`/Warn-Flags beobachtbar machen,
- JSON-Vertrag rückwärtskompatibel erweitern,
- `allow_nan=False` und Atomic Writes beibehalten.

---

## 17) Praktische Qualitätsmerkmale der aktuellen Implementierung

Die aktuelle Suite-Implementierung hat bereits produktionsnahe Guardrails:

- Fail-open für optionale Data-Layer (kein Totalabbruch bei Teilausfällen)
- Hysterese-Mechanismen (Regime, Realtime Gates)
- Throttling/Cooldowns (Alerts, A0 Signals)
- Dedupe/Cursor- und Cluster-State in Newsstack
- NaN-sichere Serialisierung
- Profiling + Statuswarnungen für operativen Betrieb

Damit ist die `open_prep`-Suite als technische Basis für 24/7 Monitoring- und Pre-Open-Workflows geeignet, inklusive nachvollziehbarer Explainability entlang des gesamten Daten- und Entscheidungsflusses.
