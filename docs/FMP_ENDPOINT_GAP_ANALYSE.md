# FMP Endpoint Gap-Analyse — skipp-algo

> **Stand:** Juni 2025  
> **Ziel:** Ungenutzte FMP-Endpoints evaluieren, bevor neue Datenanbieter integriert werden.

---

## Zusammenfassung

skipp-algo nutzt derzeit **36 Methoden** in `FMPClient` (`open_prep/macro.py`), die
ca. **25 unterschiedliche FMP-Stable-Endpunkte** ansprechen. Die FMP-API bietet
jedoch **100+ weitere Stable-Endpoints**, die für die Pipeline unmittelbar relevant
wären. Dieses Dokument listet alle Lücken, bewertet ihren Nutzen und priorisiert
die Integration.

---

## 1  Aktuell implementierte Endpoints (36 Methoden)

| # | Methode | Endpoint | Kategorie |
| --- | --------- | ---------- | ----------- |
| 1 | `get_macro_calendar` | `/stable/economic-calendar` | Makro |
| 2 | `get_batch_quotes` | `/stable/batch-quote` | Kurse |
| 3 | `get_fmp_articles` | `/stable/fmp-articles` | News |
| 4 | `get_historical_price_eod_full` | `/stable/historical-price-eod/full` | Charts |
| 5 | `get_premarket_movers` | `/stable/most-actives` | Movers |
| 6 | `get_biggest_gainers` | `/stable/biggest-gainers` | Movers |
| 7 | `get_biggest_losers` | `/stable/biggest-losers` | Movers |
| 8 | `get_batch_aftermarket_quote` | `/stable/batch-aftermarket-quote` | Kurse |
| 9 | `get_batch_aftermarket_trade` | `/stable/batch-aftermarket-trade` | Kurse |
| 10 | `get_earnings_calendar` | `/stable/earnings-calendar` | Kalender |
| 11 | `get_dividends_calendar` | `/stable/dividends-calendar` | Kalender |
| 12 | `get_splits_calendar` | `/stable/splits-calendar` | Kalender |
| 13 | `get_ipos_calendar` | `/stable/ipos-calendar` | Kalender |
| 14 | `get_earnings_report` | `/stable/earnings` | Fundamentals |
| 15 | `get_price_target_summary` | `/stable/price-target-summary` | Analysten |
| 16 | `get_eod_bulk` | `/stable/eod-bulk` | Bulk |
| 17 | `get_company_screener` | `/stable/company-screener` | Screener |
| 18 | `get_intraday_chart` | `/stable/historical-chart/{interval}` | Charts |
| 19 | `get_upgrades_downgrades` | `/stable/grades` | Analysten |
| 20 | `get_sector_performance` | `/stable/sector-performance-snapshot` | Sektoren |
| 21 | `get_index_quote` | `/stable/quote` | Kurse |
| 22 | `get_institutional_holders` | `/stable/institutional-holder` | Ownership |
| 23 | `get_analyst_estimates` | `/stable/analyst-estimates` | Analysten |
| 24 | `get_company_profile` | `/stable/profile` | Profile |
| 25 | `get_profile_bulk` | `/stable/profile-bulk` | Bulk |
| 26 | `get_scores_bulk` | `/stable/scores-bulk` | Bulk |
| 27 | `get_price_target_summary_bulk` | `/stable/price-target-summary-bulk` | Bulk |
| 28 | `get_earnings_surprises_bulk` | `/stable/earnings-surprises-bulk` | Bulk |
| 29 | `get_key_metrics_ttm_bulk` | `/stable/key-metrics-ttm-bulk` | Bulk |
| 30 | `get_ratios_ttm_bulk` | `/stable/ratios-ttm-bulk` | Bulk |
| 31 | `get_insider_trading_latest` | `/stable/insider-trading` | Insider |
| 32 | `get_insider_trade_statistics` | `/stable/insider-trading-statistics` | Insider |
| 33 | `get_institutional_ownership` | `/stable/institutional-ownership` | Ownership |
| 34 | `get_earnings_transcript` | `/stable/earning-call-transcript` | Fundamentals |
| 35 | `get_etf_holdings` | `/stable/etf-holdings` | ETFs |
| 36 | `get_senate_trading` | `/stable/senate-trading` | Politik |

---

## 2  Ungenutzte Endpoints — Kategorisiert & Priorisiert

### Prioritäts-Legende

| Prio | Bedeutung |
| ------ | ----------- |
| **🔴 HOCH** | Direkt in bestehende Pipeline integrierbar, hoher Mehrwert |
| **🟡 MITTEL** | Nützlich für neue Dashboard-Screens oder -Spalten |
| **🟢 NIEDRIG** | Nice-to-have, kein unmittelbarer Handlungsbedarf |
| **⚪ SKIP** | Für skipp-algo-Usecase irrelevant oder durch Existing abgedeckt |

---

### 2.1  🔴 HOCH — Treasury Rates & Economic Indicators

| Endpoint | Pfad | Nutzen für skipp-algo |
| ---------- | ------ | ---------------------- |
| **Treasury Rates** | `/stable/treasury-rates` | Yield-Kurve (2Y/10Y Spread → Rezessions­indikator), Ergänzung zum Makro-Bias-Score. Könnte `compute_macro_bias()` direkt verbessern. |
| **Economic Indicators** | `/stable/economic-indicators?name=GDP` | Tatsächliche Datenpunkte (GDP, CPI-Wert, Unemployment-Rate etc.) statt nur Kalender-Events. Ermöglicht quantitativen Makro-Vergleich (Actual vs. Forecast) über Zeitreihen. |

**Begründung:** Der aktuelle Makro-Score basiert nur auf dem Wirtschaftskalender
(Events + Zeitfenster). Mit Treasury Rates und den tatsächlichen Indikator-Zeitreihen
ließe sich ein viel robusterer, quantitativer Regime-Classifier bauen — genau das,
was RFC_v6.4 als AdaptiveZeroLag-RegimeClassifier vorschlägt.

**Aufwand:** ~2 Methoden + Integration in `compute_macro_bias()` → ca. 2–4 Stunden.

---

### 2.2  🔴 HOCH — Technical Indicators

| Endpoint | Pfad | Parameter |
| ---------- | ------ | ----------- |
| **SMA** | `/stable/technical-indicators/sma` | `symbol`, `periodLength`, `timeframe` (1min→1day) |
| **EMA** | `/stable/technical-indicators/ema` | wie SMA |
| **RSI** | `/stable/technical-indicators/rsi` | wie SMA |
| **ADX** | `/stable/technical-indicators/adx` | wie SMA |
| **Williams %R** | `/stable/technical-indicators/williams` | wie SMA |
| **Standard Deviation** | `/stable/technical-indicators/standarddeviation` | wie SMA |
| **WMA** | `/stable/technical-indicators/wma` | wie SMA |
| **DEMA** | `/stable/technical-indicators/dema` | wie SMA |
| **TEMA** | `/stable/technical-indicators/tema` | wie SMA |

**Nutzen für skipp-algo:**

- **SMA/EMA** (z.B. 9/21/50): Trendbestätigung für Gap-Scoring, VWAP-Reclaim-Validierung
- **RSI** (14): Überkauft/Überverkauft-Filter → vermeidet Entries gegen erschöpfte Moves
- **ADX**: Trend-Stärke-Filter → nur Gap-Entries bei starkem Trend, Skip bei Seitwärtsmarkt
- **Williams %R**: Ergänzendes Momentum-Signal

**Aber:** Die Pipeline nutzt bereits `get_intraday_chart()` für OHLCV-Daten. SMA/EMA/RSI
lassen sich lokal aus den Kurs­daten berechnen (und werden in SkippALGO.pine auch so
berechnet). Die FMP-Indicator-Endpoints wären ein Convenience-Feature, kein Must-Have.
**Server-seitig berechnet** = weniger Code, aber **ein API-Call pro Symbol × Indikator**.

**Empfehlung:** Wenn die Pipeline nur wenige Symbole (Top-20 Movers) prüft, sind die
Endpoints sinnvoll. Bei breiterem Screening besser lokal aus OHLCV berechnen.

**Aufwand:** ~1 generische Methode `get_technical_indicator(name, symbol, period, timeframe)` → ca. 1 Stunde.

---

### 2.3  🔴 HOCH — House Trading (Ergänzung zu Senate)

| Endpoint | Pfad | Nutzen |
| ---------- | ------ | -------- |
| **House Latest** | `/stable/house-latest` | Aktuellste Trades aller House-Mitglieder |
| **House Trades** | `/stable/house-trades?symbol=AAPL` | Per-Symbol Congress-Trading |

**Begründung:** `get_senate_trading()` ist bereits implementiert, aber die **House of
Representatives** fehlt komplett. Politisches Sentiment-Trading umfasst beide Kammern.
Die Integration ist trivial — identische Response-Struktur.

**Aufwand:** ~2 Methoden, Copy-Paste von `get_senate_trading()` → ca. 30 Minuten.

---

### 2.4  🟡 MITTEL — DCF Valuations

| Endpoint | Pfad | Nutzen |
| ---------- | ------ | -------- |
| **Discounted Cash Flow** | `/stable/discounted-cash-flow?symbol=AAPL` | Intrinsischer Wert → Gap-Up zu "fair" vs. "overextended" |
| **Levered DCF** | `/stable/levered-discounted-cash-flow?symbol=AAPL` | Wie oben, mit Schulden-Adjustierung |

**Nutzen für skipp-algo:**

- DCF-Wert vs. aktueller Kurs → **Value-Deviation-Score** als zusätzliches Gap-Signal
- Erkennung von Über-/Unterbewertung für Reversal-Setups
- Ergänzt bestehende `get_key_metrics_ttm_bulk()` und `get_ratios_ttm_bulk()`

**Aufwand:** ~1–2 Methoden → ca. 30 Minuten. Dashboard-Integration ca. 1 Stunde.

---

### 2.5  🟡 MITTEL — Commitment of Traders (COT)

| Endpoint | Pfad | Nutzen |
| ---------- | ------ | -------- |
| **COT Report** | `/stable/commitment-of-traders-report` | Positionierung großer Marktteilnehmer |
| **COT Analysis** | `/stable/commitment-of-traders-analysis` | Aufbereitete COT-Analyse |
| **COT List** | `/stable/commitment-of-traders-list` | Verfügbare COT-Symbole |

**Nutzen für skipp-algo:**

- **Institutional Positioning** in Futures auf S&P 500, Nasdaq, Treasury, VIX
- Bestätigung/Widerspruch zum Makro-Bias: Sind Institutionelle bullish/bearish positioniert?
- Wöchentliches Signal, nicht intraday — passt zu Makro-Scoring am Wochenende

**Einschränkung:** COT-Daten werden nur wöchentlich (Dienstag Stichtag, Freitag Release)
veröffentlicht. Für ein Daily-Gap-Screening ist der unmittelbare Nutzen begrenzt.

**Aufwand:** ~3 Methoden + Makro-Integration → ca. 2 Stunden.

---

### 2.6  🟡 MITTEL — Index Constituents

| Endpoint | Pfad | Nutzen |
| ---------- | ------ | -------- |
| **S&P 500** | `/stable/sp500-constituent` | S&P 500 Mitglieder-Liste |
| **Nasdaq** | `/stable/nasdaq-constituent` | Nasdaq Composite Mitglieder |
| **Dow Jones** | `/stable/dowjones-constituent` | DJ30 Mitglieder |

**Nutzen:**

- **Universe-Management**: Statt `get_company_screener()` mit Market-Cap-Filter könnte
  die Pipeline direkt S&P 500 / Nasdaq-100 als Grundlage nehmen
- **Index-Rebalancing-Events**: Additions/Deletions als Catalyst-Signal
- Ermöglicht Sektor-Gewichtung auf Index-Ebene

**Aufwand:** ~1 generische Methode → ca. 20 Minuten.

---

### 2.7  🟡 MITTEL — Price Target Consensus

| Endpoint | Pfad | Nutzen |
| ---------- | ------ | -------- |
| **Price Target Consensus** | `/stable/price-target-consensus?symbol=AAPL` | Aggregiertes Konsens-Kursziel |

**Nutzen:** Ergänzung zu `get_price_target_summary()`. Gibt direkt den Median-/Mean-/High-/Low-Konsens
als einzelne kompakte Antwort — weniger Overhead als das ausführliche Summary.

**Aufwand:** ~1 Methode → ca. 15 Minuten.

---

### 2.8  🟡 MITTEL — Commodity & Forex Batch-Quotes

| Endpoint | Pfad | Nutzen |
| ---------- | ------ | -------- |
| **Batch Commodity Quotes** | `/stable/batch-commodity-quotes` | Gold, Öl, Silber etc. in einem Call |
| **Commodities List** | `/stable/commodities-list` | Verfügbare Commodity-Symbole |
| **Batch Forex Quotes** | `/stable/batch-forex-quotes` | EUR/USD, GBP/USD etc. in einem Call |
| **Forex List** | `/stable/forex-list` | Verfügbare Forex-Paare |

**Nutzen für skipp-algo:**

- **Gold/Öl** als Makro-Indikatoren (Risk-On/Off, Inflation)
- **DXY / EUR/USD** als Dollar-Stärke-Indikator → Makro-Bias-Erweiterung
- Existierender `get_index_quote()` kann technisch bereits Forex/Commodities abfragen,
  aber die Batch-Endpoints sind effizienter für Multi-Asset-Monitoring

**Aufwand:** ~2–4 Methoden → ca. 1 Stunde.

---

### 2.9  🟡 MITTEL — Financial Statements (Einzel-Symbol)

| Endpoint | Pfad | Nutzen |
| ---------- | ------ | -------- |
| **Income Statement** | `/stable/income-statement?symbol=AAPL` | GuV für einzelne Symbole |
| **Balance Sheet** | `/stable/balance-sheet?symbol=AAPL` | Bilanz |
| **Cash Flow** | `/stable/cash-flow?symbol=AAPL` | Kapitalflussrechnung |

**Status:** Bulk-Varianten (`key-metrics-ttm-bulk`, `ratios-ttm-bulk`) bereits implementiert.
Einzel-Statements nur nötig, wenn tiefere Fundamentalanalyse pro Symbol gewünscht.

**Aufwand:** ~3 Methoden → ca. 30 Minuten.

---

### 2.10  🟡 MITTEL — News-Endpoints (General / Crypto / Forex)

| Endpoint | Pfad | Nutzen |
| ---------- | ------ | -------- |
| **General News** | `/stable/news/general-latest` | Allgemeine Marktnachrichten |
| **Crypto News** | `/stable/news/crypto-latest` | Krypto-spezifische News |
| **Forex News** | `/stable/news/forex-latest` | Forex-spezifische News |
| **Stock News** | `/stable/news/stock-latest?symbols=AAPL` | Symbol-spezifische News |

**Status:** `get_fmp_articles()` ist bereits implementiert, liefert aber nur FMP-eigene
Artikel. Die `/stable/news/*` Endpoints liefern **externe Nachrichtenquellen** (Reuters,
Bloomberg etc.) — breitere Abdeckung.

**Aufwand:** ~1 generische Methode → ca. 30 Minuten.

---

### 2.11  🟢 NIEDRIG — ESG Ratings

| Endpoint | Pfad | Nutzen |
| ---------- | ------ | -------- |
| **ESG Disclosures** | `/stable/esg-disclosures?symbol=AAPL` | ESG-Offenlegungen |
| **ESG Ratings** | `/stable/esg-ratings?symbol=AAPL` | ESG-Bewertungen |
| **ESG Benchmark** | `/stable/esg-benchmark` | Branchen-Benchmark |

**Nutzen:** Für Gap-Trading kaum relevant. Nur sinnvoll, wenn ESG-Filter als
optionaler Screener-Parameter gewünscht wird. Niedrige Priorität.

**Aufwand:** ~2 Methoden → ca. 30 Minuten.

---

### 2.12  🟢 NIEDRIG — SEC Filings

| Endpoint | Pfad | Nutzen |
| ---------- | ------ | -------- |
| **SEC Filings** | `/stable/sec-filings?symbol=AAPL` | 10-K, 10-Q, 8-K etc. |
| **SEC Profile** | `/stable/sec-profile?symbol=AAPL` | CIK, SIC-Code |

**Nutzen:** 8-K-Filings können als Catalyst dienen, aber die meisten relevanten
Events werden bereits durch Earnings-Calendar, Grades und Insider-Trading abgedeckt.

---

### 2.13  🟢 NIEDRIG — Crypto Charts & Quotes

| Endpoint | Pfad | Nutzen |
| ---------- | ------ | -------- |
| **Batch Crypto Quotes** | `/stable/batch-crypto-quotes` | BTC, ETH etc. |
| **Crypto Charts** | `/stable/historical-chart/{interval}?symbol=BTCUSD` | OHLCV für Krypto |

**Status:** Die bestehenden Chart-Endpoints (`get_intraday_chart`, `get_historical_price_eod_full`)
funktionieren technisch auch für Krypto-Symbole (BTCUSD, ETHUSD). Kein dedizierter
Wrapper nötig, außer für Batch-Abfragen.

**Nutzen:** Nur relevant, wenn Krypto-Assets in die Gap-Screening-Pipeline
aufgenommen werden sollen.

---

### 2.14  🟢 NIEDRIG — ETF Details (Sektoren, Länder, Assets)

| Endpoint | Pfad | Nutzen |
| ---------- | ------ | -------- |
| **ETF Info** | `/stable/etf-info?symbol=SPY` | ETF-Metadaten |
| **ETF Sector Weighting** | `/stable/etf-sector-weighting?symbol=SPY` | Sektorgewichtung |
| **ETF Country Allocation** | `/stable/etf-country-allocation?symbol=SPY` | Länder |
| **ETF Asset Exposure** | `/stable/etf-asset-exposure?symbol=SPY` | Asset-Klassen |

**Status:** `get_etf_holdings()` bereits implementiert. Diese Endpoints liefern
aggregierte Sichten — nützlich für Dashboard, aber nicht für Gap-Scoring.

---

### 2.15  ⚪ SKIP — Nicht relevant für skipp-algo

| Endpoint | Begründung für Skip |
| ---------- | --------------------- |
| **Fundraisers/Crowdfunding** | Nur für Equity-Crowdfunding-Daten (Reg A, Reg CF) — kein Trading-Signal |
| **SIC Classification List** | Reine Referenz-Tabelle, `get_company_profile()` liefert bereits Sektor/Industrie |
| **Market Hours/Holidays** | Bereits durch `_market_cal.py` lokal gelöst |
| **Market Risk Premium** | Akademische Metrik, kein operativer Nutzen für Day-Trading |
| **Revenue Segments** (Product/Geographic) | Zu granular für Gap-Screening |
| **As-Reported Statements** | Redundant zu regulären Statements, nur für Audit relevant |
| **Custom DCF / Custom Levered DCF** | Standard-DCF reicht; Custom erfordert eigenen Modell-Input |

---

## 3  Priorisierte Implementierungs-Roadmap

### Phase 1 — Quick Wins (Aufwand: ~1 Tag)

| # | Endpoint | Methode | Geschätzter Aufwand |
| --- | ---------- | --------- | --------------------- |
| 1 | Treasury Rates | `get_treasury_rates()` | 30 min |
| 2 | Economic Indicators | `get_economic_indicators()` | 30 min |
| 3 | House Trading | `get_house_trading()` | 30 min |
| 4 | Technical Indicator (generisch) | `get_technical_indicator()` | 45 min |
| 5 | DCF Valuation | `get_dcf()` | 20 min |
| 6 | Price Target Consensus | `get_price_target_consensus()` | 15 min |
| 7 | Index Constituents | `get_index_constituents()` | 20 min |

**Gesamt Phase 1:** ~3,5 Stunden Implementierung für 7 neue Methoden.

### Phase 2 — Dashboard-Erweiterungen (Aufwand: ~1 Tag)

| # | Endpoint | Methode | Geschätzter Aufwand |
| --- | ---------- | --------- | --------------------- |
| 8 | Batch Commodity Quotes | `get_batch_commodity_quotes()` | 20 min |
| 9 | Batch Forex Quotes | `get_batch_forex_quotes()` | 20 min |
| 10 | COT Report | `get_cot_report()` | 30 min |
| 11 | COT Analysis | `get_cot_analysis()` | 20 min |
| 12 | Stock News | `get_stock_news()` | 30 min |
| 13 | Income Statement | `get_income_statement()` | 20 min |
| 14 | Balance Sheet | `get_balance_sheet()` | 20 min |
| 15 | Cash Flow Statement | `get_cash_flow()` | 20 min |

**Gesamt Phase 2:** ~3 Stunden für 8 weitere Methoden.

### Phase 3 — Pipeline-Integration (Aufwand: ~2–3 Tage)

Nach Implementierung der Methoden — Integration in bestehende Logik:

1. **Treasury Rates → `compute_macro_bias()`**: 2Y/10Y-Spread als Regime-Signal
2. **Economic Indicators → `compute_macro_bias()`**: Actual-vs-Forecast für CPI, GDP etc.
3. **Technical Indicators → `screen.py` / `rank_candidates()`**: RSI-Filter, EMA-Trend
4. **DCF → `_enrich_gap_card()`**: Value-Deviation als zusätzliche Spalte
5. **House Trading → bestehende Senate-Anzeige**: Unified Congress-Trading-View
6. **Commodity/Forex → Macro-Dashboard**: Gold, DXY als Sentiment-Hintergrund

---

## 4  API-Rate-Budget-Analyse

**Aktueller Verbrauch pro Pipeline-Run** (geschätzt):

- ~15–25 API-Calls (Kalender, Movers, Quotes, Enrichment)
- Bulk-Endpoints (Ultimate-Tier) reduzieren Calls erheblich

**Zusätzlicher Verbrauch durch Phase 1:**

- +1 Call Treasury Rates
- +1 Call Economic Indicators  
- +1 Call House Trading
- +N Calls Technical Indicators (N = Anzahl Top-Symbole × Indikatoren)
- +M Calls DCF (M = Anzahl Symbole mit Gap-Entry)

**Empfehlung:** Technical Indicators nur für Top-10 Gap-Kandidaten aufrufen
(nicht für das gesamte Screening-Universe). DCF ebenso nur für finale
Kandidaten. Budget-Impact damit: **+5–15 Calls pro Run** — vertretbar.

---

## 5  Fazit

> **Vor der Integration neuer Anbieter (Finnhub, Twelve Data, Polygon) sollten
> mindestens die Phase-1-Endpoints implementiert werden.** Sie decken die
> wichtigsten Lücken ab (Makro-Quantifizierung, Congress-Trading, technische
> Validierung, Bewertung) und erfordern **keinen neuen API-Key, keine neue
> Infrastruktur und nur minimale Änderungen an bestehender Architektur.**

Die bestehende `FMPClient`-Infrastruktur (CircuitBreaker, Retry, CSV-Fallback)
funktioniert für alle neuen Endpoints ohne Anpassung. Jede neue Methode folgt
dem etablierten Pattern der bestehenden 36 Methoden.

Erst wenn die FMP-Abdeckung ausgeschöpft ist, lohnt sich der Aufwand für:

- **Finnhub** (WebSocket für Real-Time, alternative News)
- **Twelve Data** (breitere Technische Indikatoren, Crypto)
- **Polygon** (Tick-Level-Daten, Options Flow)

---

## Update 2026-04-30: Retired FMP Paths (v3 audit)

Folgende FMP-Pfade wurden als Teil des v3-Provider-Audits entfernt und
sind nicht mehr Bestandteil der aktiven Codebase. Sie sollen **nicht**
ohne neuen RFC reaktiviert werden:

| Path | Removed in PR | Grund |
|------|---------------|-------|
| `fetch_fear_and_greed_*` (FMP) | #1962 (v3 P-6) | Dead code — kein Production-Konsument; Indikator wird durch andere Macro-Surfaces (UW Market-Tide) abgedeckt. |
| FMP `short-interest` enrichment | #1964 (v3 P-2) | Monitor wechselte auf Unusual Whales fuer Flow-Kontext; FMP-Short-Interest-Pfad war redundant. |

**Zugewinn-Pfade in derselben Audit-Welle:**

- FMP `insider-trading-*` (`get_insider_trading_latest`,
  `get_insider_trading_statistics`) sind weiterhin aktiv und werden nach
  v3 P-3c (#1966) als Primaerquelle fuer Insider-Sentiment im Open-Prep
  Monitor verwendet (parallel zu Unusual Whales bulk Form-4).
