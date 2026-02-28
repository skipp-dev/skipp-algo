# Anbieter-Vergleich: Finnhub · Twelve Data · Alpaca

> **Stand:** 28. Februar 2026  
> **Kontext:** skipp-algo Open-Prep-Pipeline (aktuell FMP 44 Methoden + Benzinga ~20 Fetch-Funktionen)

---

## Inhaltsverzeichnis

1. [Zusammenfassung (Executive Summary)](#1-zusammenfassung-executive-summary)
2. [Aktuelle Datenquellen im Überblick](#2-aktuelle-datenquellen-im-überblick)
3. [Prio 1 – Finnhub](#3-finnhub-prio-1)
4. [Prio 2 – Twelve Data](#4-twelve-data-prio-2)
5. [Prio 3 – Alpaca](#5-alpaca-prio-3)
6. [Lückenanalyse & Alleinstellungsmerkmale](#6-lückenanalyse--alleinstellungsmerkmale)
7. [Integrations-Empfehlungen](#7-integrations-empfehlungen)
8. [Implementierungs-Roadmap](#8-implementierungs-roadmap)
9. [Anhang: Endpoint-Listen](#9-anhang-rate-limits--kosten-im-vergleich)

---

## 1. Zusammenfassung

| Kriterium | Finnhub (Prio 1) | Twelve Data (Prio 2) | Alpaca (Prio 3) |
| --- | --- | --- | --- |
| **Schwerpunkt** | Fundamentaldaten + Alternative Data | Technische Indikatoren + OHLCV | Trading-API + Market Data |
| **Free-Tier** | 30 req/s, keine Tageslimits | 8 Credits/min (800/Tag) | 200 req/min (IEX only) |
| **Python-Lib** | `finnhub-python` | `twelvedata` | `alpaca-py` |
| **WebSocket** | ✅ Free (Trades) | ✅ Ab Pro-Plan ($99+) | ✅ Free (IEX) / Paid (SIP) |
| **Unique Wert fürs Skript** | Social Sentiment, Pattern Recognition, Supply Chain, Earnings Quality, Congressional Trading | 100+ serverseitige TA-Indikatoren, Batch bis 120 Symbole | News-Stream, Screener (Most Active/Movers), Options-Daten |
| **Kosten-Nutzen** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ |
| **Integrations-Aufwand** | Mittel | Niedrig | Niedrig |

**Empfehlung:** Finnhub als primäre Erweiterung (höchster Mehrwert durch einzigartige Alternative-Data-Endpunkte), Twelve Data als TA-Backup, Alpaca nur bei Bedarf an News-Stream oder Screener.

---

## 2. Aktuelle Datenquellen

### FMP (Financial Modeling Prep) — 44 `get_*` Methoden

| Kategorie | Endpunkte |
| --- | --- |
| Quotes/Preise | Batch-Quotes, Pre-/Aftermarket, Gainers/Losers, Intraday-Charts, EOD Bulk |
| Kalender | Earnings, Dividends, Splits, IPOs, Macro-Calendar |
| Fundamentals | Earnings Reports, Company Screener, Key Metrics |
| Analyst | Grades, Price Targets, Price Target Consensus |
| Alternative | Insider Trading, Institutional Holdings, Sector Performance, House/Senate Trading, DCF, Treasury Rates, Technical Indicators |

### Benzinga — ~20 Fetch-Funktionen

| Kategorie | Endpunkte |
| --- | --- |
| Ratings | Analyst Ratings |
| Kalender | Earnings, Economics, Conference Calls, Dividends, Splits, IPOs, Guidance |
| News/Sentiment | Top News, Quantified News |
| Alternative | Retail Activity, Options Activity, Insider Transactions, Market Movers, Delayed Quotes |

---

## 3. Finnhub (Prio 1)

### 3.1 Übersicht

- **Basis-URL:** `https://finnhub.io/api/v1/`
- **Auth:** `?token=API_KEY` (Query-Parameter)
- **Python:** `pip install finnhub-python` → `finnhub.Client(api_key="...")`
- **Rate-Limit Free:** 30 req/s (sehr großzügig!)
- **Märkte:** US, UK, EU, CA, AU, IN und weitere

### 3.2 FREE-Tier Endpunkte

| Endpunkt | Route | Relevanz für skipp-algo | Abgedeckt durch? |
| --- | --- | --- | --- |
| **Quote** | `/quote` | Real-time Preis | FMP ✅ |
| **Company News** | `/company-news` | 1 Jahr historisch, per Symbol+Datumsbereich | Benzinga ✅ (ähnlich) |
| **Market News** | `/general-news` | Allgemeine Marktnachrichten | Benzinga ✅ |
| **Company Profile 2** | `/stock/profile2` | Profil, Sektor, Branche | FMP ✅ |
| **Symbol Search** | `/search` | Symbol-Suche | FMP ✅ |
| **Peers** | `/stock/peers` | Branchenvergleich | ❌ **NEU** |
| **Basic Financials** | `/stock/basic-financials` | KPIs (52w H/L, Beta, PE, EPS etc.) | FMP ✅ (teilweise) |
| **Insider Transactions** | `/stock/insider-transactions` | Global (US, UK, CA, AU, IN, EU) | FMP ✅ (US only) |
| **Insider Sentiment** | `/stock/insider-sentiment` | MSPR Score (-100 bis +100) | ❌ **NEU & EINZIGARTIG** |
| **Recommendation Trends** | `/stock/recommendation` | Buy/Hold/Sell/StrongBuy/StrongSell Verteilung | FMP ✅ (ähnlich) |
| **EPS Surprises** | `/company-earnings` | Earnings-Überraschungen | FMP ✅ |
| **Earnings Calendar** | `/calendar/earnings` | Earnings-Datum | FMP ✅ |
| **IPO Calendar** | `/calendar/ipo` | IPO-Termine | FMP ✅ |
| **Financials As Reported** | `/stock/financials-reported` | SEC-Originaldaten | FMP ✅ |
| **SEC Filings** | `/stock/filings` | SEC-Einreichungen | FMP ✅ (teilweise) |
| **Market Status** | `/market-status` | Markt offen/geschlossen | ❌ **NEU** |
| **Market Holiday** | `/market-holiday` | Feiertage | ❌ **NEU** |
| **USPTO Patents** | `/stock/uspto-patent` | Patentdaten | ❌ **NEU & EINZIGARTIG** |
| **Senate Lobbying** | `/stock/lobbying` | Lobby-Aktivitäten | ❌ **NEU & EINZIGARTIG** |
| **USA Spending** | `/stock/usa-spending` | Staatsausgaben an Unternehmen | ❌ **NEU & EINZIGARTIG** |
| **FDA Calendar** | `/fda-advisory-committee/calendar` | FDA-Termine (Pharma/Biotech) | ❌ **NEU & EINZIGARTIG** |
| **H1-B Visa** | `/stock/visa-application` | Visa-Anträge pro Firma | ❌ **NEU** |
| **WebSocket Trades** | `wss://ws.finnhub.io` | Real-time Streaming (Free!) | ❌ **NEU** |

### 3.3 PREMIUM Endpunkte (Unique vs. FMP/Benzinga)

| Endpunkt | Beschreibung | Einzigartigkeit |
| --- | --- | --- |
| **🔥 Social Sentiment** | Reddit + Twitter: Erwähnungen, pos/neg Score (-1 bis +1) | ⭐⭐⭐⭐⭐ Kein Äquivalent! |
| **🔥 Pattern Recognition** | Chart-Muster (Double Top/Bottom, H&S, Triangles, Wedges, Flags, Candlestick-Muster) | ⭐⭐⭐⭐⭐ Kein Äquivalent! |
| **🔥 Support/Resistance** | Auto-berechnete S/R-Levels | ⭐⭐⭐⭐⭐ Kein Äquivalent! |
| **🔥 Aggregate Indicators** | Composite Buy/Sell/Neutral Signal | ⭐⭐⭐⭐ Kein Äquivalent! |
| **🔥 Supply Chain** | Kunden-/Lieferanten-Beziehungen | ⭐⭐⭐⭐⭐ Kein Äquivalent! |
| **🔥 Earnings Quality Score** | Earnings-Qualität | ⭐⭐⭐⭐ Kein Äquivalent! |
| **🔥 Investment Themes** | Thematisches Investieren | ⭐⭐⭐⭐ Kein Äquivalent! |
| **Congressional Trading** | Kongress-Transaktionen | FMP ✅ (House/Senate) |
| **News Sentiment** | Bullish/bearish %, Sektor-Durchschnitte | ❌ **NEU** |
| **Earnings Call Transcripts** | Volltext + Audio (Live!) | ❌ **NEU** |
| **Company ESG** | ESG-Scores (aktuell + historisch) | ❌ **NEU** |
| **Price Target** | Konsens-Preisziel | FMP ✅ |
| **Upgrade/Downgrade** | Analyst-Änderungen | FMP ✅ |
| **Estimates** | Revenue/EPS/EBITDA/EBIT Schätzungen | FMP ✅ (teilweise) |
| **Stock Candles** | OHLCV (1/5/15/30/60/D/W/M) | FMP ✅ |
| **Indices Constituents** | Inkl. Gewichtung + historische Änderungen | FMP ✅ (ohne Historie) |
| **Technical Indicators** | Volle TA-Library | FMP ✅ |
| **Economic Calendar** | Wirtschaftsdaten | FMP ✅ |

### 3.4 Bewertung

| Aspekt | Bewertung |
| --- | --- |
| **Mehrwert** | ⭐⭐⭐⭐⭐ — Einzigartige Alternative-Data (Social Sentiment, Pattern Recognition, Supply Chain, Earnings Quality, S/R Levels) |
| **Free-Tier Nutzbarkeit** | ⭐⭐⭐⭐⭐ — 30 req/s ohne Tageslimit, viele wertvolle Free-Endpunkte |
| **Integration** | ⭐⭐⭐⭐ — Saubere REST-API, offizielle Python-Lib, einfaches Token-Auth |
| **Datenqualität** | ⭐⭐⭐⭐ — Direkter Feed von SEC, NYSE, etc. |

---

## 4. Twelve Data (Prio 2)

### 4.1 Übersicht

- **Basis-URL:** `https://api.twelvedata.com/`
- **Auth:** `?apikey=API_KEY` (Query-Parameter)
- **Python:** `pip install twelvedata` → `TDClient(apikey="...")`
- **Rate-Limit Free:** 8 Credits/min (800/Tag) — **deutlich restriktiver als Finnhub**
- **Märkte:** 84 Börsen (Global), US/Forex/Crypto im Free-Tier

### 4.2 Endpunkt-Katalog

| Kategorie | Endpunkte | Free-Tier? |
| --- | --- | --- |
| **Time Series** | OHLCV (1min–1month), Multi-Symbol Batch (bis 120) | ✅ |
| **Quote** | Echtzeit-Quote inkl. day/prev close | ✅ |
| **Real-time Price** | Letzter Preis | ✅ |
| **EOD Price** | Tagesschlusskurs | ✅ |
| **Exchange Rate** | Wechselkurse (Forex/Crypto) | ✅ |
| **Currency Conversion** | Währungskonversion | ✅ |
| **🔥 100+ TA-Indikatoren** | SMA, EMA, MACD, RSI, Bollinger, Stoch, ADX, ATR, CCI, CMF, DEMA, TEMA, VWAP, Ichimoku, SuperTrend, Pivot Points, ... (serverseitig!) | ✅ |
| **Fundamentals: Profile** | Firmenprofil | Ab Grow ($79) |
| **Fundamentals: Logo** | Firmenlogo | Ab Grow |
| **Fundamentals: Dividends** | Dividendenhistorie | Ab Grow |
| **Fundamentals: Splits** | Aktiensplits | Ab Grow |
| **Fundamentals: Earnings** | Earnings + Calendar | Ab Grow |
| **Fundamentals: IPO Calendar** | IPO-Termine | Ab Grow |
| **Fundamentals: Statistics** | Key-Statistiken | Ab Grow |
| **Fundamentals: Insider Transactions** | Insider-Trades | Ab Grow |
| **Fundamentals: Income Statement** | Gewinn- und Verlustrechnung | Ab Grow |
| **Fundamentals: Balance Sheet** | Bilanz | Ab Grow |
| **Fundamentals: Cash Flow** | Kapitalfluss | Ab Grow |
| **Fundamentals: Key Executives** | Vorstand/Führungskräfte | Ab Grow |
| **Fundamentals: Institutional Holders** | Institutionelle Halter | Ab Grow |
| **Fundamentals: Fund Holders** | Fonds-Halter | Ab Grow |
| **Market Movers** | Top Gainers/Losers | Ab Pro ($229) |
| **Batch Requests** | Bis 120 Symbole in einer Anfrage | Ab Pro |
| **WebSocket** | Real-time Streaming | Ab Pro ($229) |
| **Pre/Post-Market** | Erweiterte Handelszeiten | Ab Pro |
| **Analysis Data** | Analytische Kennzahlen | Ab Ultra ($999) |
| **Mutual Funds/ETF Breakdown** | Fonds-Zusammensetzung | Ab Ultra |
| **Historical Fundamentals** | Historische Fundamentaldaten | Ab Enterprise ($1.999) |

### 4.3 Besondere Stärken

1. **100+ serverseitige TA-Indikatoren** — Komplett auf dem Server berechnet, kein lokales Pandas-TALib nötig. Können direkt an die Time-Series-Abfrage angehängt werden (`.with_bbands().with_macd().with_rsi()`).
2. **Batch-Requests (bis 120 Symbole)** — Ideal für unsere Watchlist-Verarbeitung (Open-Prep verarbeitet ~30-50 Symbole).
3. **Saubere Python-Lib** — Pandas/Plotly/Matplotlib-Output nativ, gute DX.
4. **Globale Abdeckung** — 84 Börsen weltweit (relevant falls internationale Expansion).

### 4.4 Bewertung

| Aspekt | Bewertung |
| --- | --- |
| **Mehrwert** | ⭐⭐⭐ — TA-Indikatoren sind nett, aber FMP hat bereits `get_technical_indicator()`. Fundamentals hinter Paywall. |
| **Free-Tier Nutzbarkeit** | ⭐⭐ — Nur 800 Calls/Tag, Fundamentals erst ab $79/m. Für 30+ Symbole knapp. |
| **Integration** | ⭐⭐⭐⭐⭐ — Beste Python-Lib der drei (Pandas-native, Batch-Support, Chaining). |
| **Datenqualität** | ⭐⭐⭐⭐ — Gute Qualität, aber keine unique Alternative-Data. |

---

## 5. Alpaca (Prio 3)

### 5.1 Übersicht

- **Basis-URL:** `https://data.alpaca.markets/v2/` (Market Data) / `https://api.alpaca.markets/v2/` (Trading)
- **Auth:** Headers `APCA-API-KEY-ID` + `APCA-API-SECRET-KEY`
- **Python:** `pip install alpaca-py` (offizielles SDK)
- **Rate-Limit Free:** 200 req/min (Basic), 10.000 req/min (Algo Trader Plus $99/m)
- **Märkte:** US Stocks/ETFs, Options, Crypto, Forex, Fixed Income

### 5.2 Market-Data-Endpunkte

| Kategorie | Endpunkte | Free-Tier? |
| --- | --- | --- |
| **Stock Bars** | Historical + Latest (1min–1month, split/dividend adjusted) | ✅ (IEX) |
| **Stock Quotes** | Historical + Latest | ✅ (IEX) |
| **Stock Trades** | Historical + Latest (Tick-Level) | ✅ (IEX) |
| **Stock Snapshots** | Aktueller Zustand (Quote + Trade + Bar) | ✅ (IEX) |
| **Auctions** | NYSE Opening/Closing Auctions | ✅ (IEX) |
| **🔥 Screener: Most Active** | Top-gehandelte Aktien | ✅ |
| **🔥 Screener: Top Movers** | Größte Gewinner/Verlierer (% und $) | ✅ |
| **🔥 News** | Nachrichtenartikel mit Symbolen, Sentiment, Autor, Bilder | ✅ |
| **Corporate Actions** | Dividends, Splits, Mergers, Spin-offs | ✅ |
| **Logos** | Firmenlogos (PNG/SVG) | ✅ |
| **Option Bars/Trades/Quotes** | Options-Daten (OPRA Feed) | ✅ (Indicative) |
| **Option Chain** | Vollständige Optionskette | ✅ |
| **Crypto Bars/Quotes/Trades** | Krypto-Daten | ✅ |
| **Crypto Orderbook** | Live-Orderbuch | ✅ |
| **Forex Rates** | Wechselkurse (Historical + Latest) | ✅ |
| **Fixed Income** | US Treasuries Latest Prices | ✅ |
| **US Market Calendar** | Handelskalender | ✅ |
| **US Market Clock** | Markt-Status (offen/geschlossen) | ✅ |

### 5.3 WebSocket-Streaming

| Stream | Inhalte | Free-Tier? |
| --- | --- | --- |
| **Stock Trades** | Real-time Trades | ✅ (IEX, 30 Symbole) |
| **Stock Quotes** | Real-time Quotes | ✅ (IEX, 30 Symbole) |
| **Stock Bars** | 1-Min-Aggregation | ✅ (IEX, 30 Symbole) |
| **🔥 News Stream** | Real-time Nachrichten | ✅ |
| **Option Trades/Quotes** | Options-Streaming | ✅ (Indicative, 200 Symbole) |
| **Crypto Trades/Quotes/Bars/Orderbooks** | Krypto-Streaming | ✅ |

### 5.4 Trading-API (Bonus — nicht primär für Data-Ingest)

| Kategorie | Endpunkte |
| --- | --- |
| Account | Kontoinformationen, Portfolio History |
| Orders | Erstellen, Ändern, Stornieren, Schätzen |
| Positions | Offene Positionen, Schließen |
| Watchlists | Erstellen, Bearbeiten, Löschen |
| Assets | Alle handelbaren Assets |
| Options Trading | Options-Handel (Level 1-3) |
| Crypto Trading | Krypto-Kauf/Verkauf |
| Paper Trading | Sandbox-Umgebung |

### 5.5 Bewertung

| Aspekt | Bewertung |
| --- | --- |
| **Mehrwert** | ⭐⭐⭐ — Screener (Most Active/Movers) und News-Stream sind nett, aber FMP/Benzinga decken dies bereits ab. Einzigartiger Wert: Options-Daten + Echtzeit-News-WebSocket. |
| **Free-Tier Nutzbarkeit** | ⭐⭐⭐ — 200 req/min reicht, aber nur IEX-Daten (nicht vollständig). |
| **Integration** | ⭐⭐⭐⭐ — Gutes SDK (`alpaca-py`), gute Doku. |
| **Datenqualität** | ⭐⭐⭐⭐⭐ — CTA+UTP direkte Feeds (höchste Qualität für US-Märkte). |

---

## 6. Lückenanalyse & Alleinstellungsmerkmale

### Was fehlt im aktuellen Stack (FMP + Benzinga)?

| Datenlücke | Finnhub | Twelve Data | Alpaca |
| --- | --- | --- | --- |
| **Social Sentiment** (Reddit/Twitter) | ✅ Premium | ❌ | ❌ |
| **Chart Pattern Recognition** | ✅ Premium | ❌ | ❌ |
| **Support/Resistance Levels** | ✅ Premium | ❌ | ❌ |
| **Composite Buy/Sell Signal** | ✅ Premium | ❌ | ❌ |
| **Supply Chain Relationships** | ✅ Premium | ❌ | ❌ |
| **Earnings Quality Score** | ✅ Premium | ❌ | ❌ |
| **Insider Sentiment Score (MSPR)** | ✅ Free | ❌ | ❌ |
| **FDA Calendar** | ✅ Free | ❌ | ❌ |
| **Senate Lobbying** | ✅ Free | ❌ | ❌ |
| **USA Spending (Staatsverträge)** | ✅ Free | ❌ | ❌ |
| **USPTO Patents** | ✅ Free | ❌ | ❌ |
| **Company Peers** | ✅ Free | ❌ | ❌ |
| **Market Status/Holiday** | ✅ Free | ❌ | ✅ Free |
| **Serverseitige TA (100+)** | ✅ Premium | ✅ Free | ❌ |
| **Batch bis 120 Symbole** | ❌ | ✅ Pro ($229) | ❌ |
| **Echtzeit-News WebSocket** | ✅ Premium | ❌ | ✅ Free |
| **Options-Daten** | ❌ | ❌ | ✅ Free |
| **ESG-Scores** | ✅ Premium | ❌ | ❌ |
| **Earnings Call Transcripts** | ✅ Premium | ❌ | ❌ |
| **Investment Themes** | ✅ Premium | ❌ | ❌ |
| **News Sentiment (bull/bear %)** | ✅ Premium | ❌ | ❌ |

### Fazit der Lückenanalyse

**Finnhub deckt 85% aller identifizierten Datenlücken ab** — die meisten davon exklusiv. Twelve Data und Alpaca haben kaum unique Endpunkte, die nicht bereits durch FMP/Benzinga oder Finnhub abgedeckt werden.

---

## 7. Integrations-Empfehlungen

### Phase 1 — Finnhub FREE (Sofort umsetzbar, $0)

| # | Endpunkt | Neue Methode | Stage/Tab | Aufwand |
| --- | --- | --- | --- | --- |
| 1 | **Insider Sentiment** (`/stock/insider-sentiment`) | `get_insider_sentiment()` | Stage: Insider Sentiment → Tab: 🧠 Insider Sentiment | 2h |
| 2 | **Company Peers** (`/stock/peers`) | `get_peers()` | Stage: Peers → Tab: 👥 Peers | 1h |
| 3 | **Market Status** (`/market-status`) | `get_market_status()` | Integration in Pipeline-Guard | 0.5h |
| 4 | **FDA Calendar** (`/fda-advisory-committee/calendar`) | `get_fda_calendar()` | Stage: FDA → Tab: 💊 FDA Calendar | 1.5h |
| 5 | **Senate Lobbying** (`/stock/lobbying`) | `get_lobbying()` | Stage: Politics → Tab: 🏛️ erweitern | 1.5h |
| 6 | **USA Spending** (`/stock/usa-spending`) | `get_usa_spending()` | Stage: Politics → Tab: 🏛️ erweitern | 1.5h |
| 7 | **USPTO Patents** (`/stock/uspto-patent`) | `get_patents()` | Stage: Innovation → Tab: 💡 Patents | 1.5h |

**Gesamt Phase 1:** ~10h Aufwand, $0 Kosten

### Phase 2 — Finnhub PREMIUM (Hoher Mehrwert, kostenpflichtig)

| # | Endpunkt | Neue Methode | Wert für Open-Prep |
| --- | --- | --- | --- |
| 1 | **Social Sentiment** | `get_social_sentiment()` | ⭐⭐⭐⭐⭐ Reddit/Twitter-Stimmung als Kontraindikator |
| 2 | **Pattern Recognition** | `get_pattern_recognition()` | ⭐⭐⭐⭐⭐ Automatische Chart-Pattern-Erkennung für Watchlist |
| 3 | **Support/Resistance** | `get_support_resistance()` | ⭐⭐⭐⭐⭐ Automatische S/R-Level-Berechnung |
| 4 | **Aggregate Indicators** | `get_aggregate_indicators()` | ⭐⭐⭐⭐ Composite Buy/Sell/Neutral als Quick-Signal |
| 5 | **Supply Chain** | `get_supply_chain()` | ⭐⭐⭐⭐ Kunden/Lieferanten-Netzwerk |
| 6 | **Earnings Quality** | `get_earnings_quality()` | ⭐⭐⭐⭐ Earnings-Qualitäts-Score |
| 7 | **News Sentiment** | `get_news_sentiment()` | ⭐⭐⭐⭐ Bull/Bear-Ratio |
| 8 | **ESG Scores** | `get_esg()` | ⭐⭐⭐ ESG-Trend für institutionelle Perspektive |

**Gesamt Phase 2:** ~16h Aufwand, Finnhub Premium ab ~$100/m

### Phase 3 — Optionale Ergänzungen (Twelve Data / Alpaca)

| # | Quelle | Endpunkt | Wann sinnvoll? |
| --- | --- | --- | --- |
| 1 | **Alpaca** | News WebSocket | Wenn Real-time-News-Streaming für Alerts gewünscht |
| 2 | **Alpaca** | Option Chain | Wenn Options-Flow-Analyse für Open-Prep gewünscht |
| 3 | **Alpaca** | Screener (Most Active) | Als Validierung gegen FMP/Benzinga Movers |
| 4 | **Twelve Data** | Batch TA-Indikatoren | Wenn FMP `get_technical_indicator()` zu langsam für 50+ Symbole |
| 5 | **Twelve Data** | WebSocket | Wenn Echtzeit-Kurs-Streaming nötig (aber Finnhub Free WS ist besser) |

---

## 8. Implementierungs-Roadmap

```
┌──────────────────────────────────────────────────────────────────┐
│ Phase 1 (Woche 1-2): Finnhub FREE Integration                   │
│ ├─ FinnhubClient in macro.py (analog FMPClient)                  │
│ ├─ 7 neue get_* Methoden                                         │
│ ├─ 2-3 neue Pipeline-Stages in run_open_prep.py                  │
│ ├─ 2-3 neue Streamlit-Tabs                                       │
│ ├─ VisiData-Spalten erweitern                                    │
│ └─ Env-Var: FINNHUB_API_KEY                                      │
├──────────────────────────────────────────────────────────────────┤
│ Phase 2 (Woche 3-4): Finnhub PREMIUM Integration                │
│ ├─ 8 neue Premium-Methoden                                       │
│ ├─ Social Sentiment Tab + Score in Pipeline                      │
│ ├─ Pattern Recognition → Signal-Verstärker                       │
│ ├─ S/R Levels → automatische Zielzonen                           │
│ └─ Supply Chain Visualisierung                                   │
├──────────────────────────────────────────────────────────────────┤
│ Phase 3 (Optional, nach Bedarf):                                 │
│ ├─ Alpaca News WebSocket für Real-time Alerts                    │
│ ├─ Alpaca Options Flow                                           │
│ └─ Twelve Data Batch-TA als Fallback                             │
└──────────────────────────────────────────────────────────────────┘
```

### Architektur-Vorschlag

```python
# macro.py — Neuer FinnhubClient (analog zu FMPClient)

class FinnhubClient:
    BASE = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("FINNHUB_API_KEY", "")

    def _get(self, path: str, params: dict | None = None) -> dict | list:
        params = params or {}
        params["token"] = self.api_key
        resp = requests.get(f"{self.BASE}{path}", params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    # --- Phase 1 (FREE) ---
    def get_insider_sentiment(self, symbol: str, from_date: str, to_date: str): ...
    def get_peers(self, symbol: str): ...
    def get_market_status(self, exchange: str = "US"): ...
    def get_fda_calendar(self): ...
    def get_lobbying(self, symbol: str, from_date: str, to_date: str): ...
    def get_usa_spending(self, symbol: str, from_date: str, to_date: str): ...
    def get_patents(self, symbol: str, from_date: str, to_date: str): ...

    # --- Phase 2 (PREMIUM) ---
    def get_social_sentiment(self, symbol: str, from_date: str, to_date: str): ...
    def get_pattern_recognition(self, symbol: str, resolution: str = "D"): ...
    def get_support_resistance(self, symbol: str, resolution: str = "D"): ...
    def get_aggregate_indicators(self, symbol: str, resolution: str = "D"): ...
    def get_supply_chain(self, symbol: str): ...
    def get_earnings_quality(self, symbol: str, freq: str = "quarterly"): ...
    def get_news_sentiment(self, symbol: str): ...
    def get_esg(self, symbol: str): ...
```

---

## 9. Anhang: Rate-Limits & Kosten im Vergleich

| Provider | Free Tier | Nächste Stufe | Enterprise |
| --- | --- | --- | --- |
| **Finnhub** | 30 req/s, unbegrenzt/Tag | Premium: individuell | Individuell |
| **Twelve Data** | 8 cred/min (800/Tag) | Grow $79/m (377 cred/min) | $1.999/m |
| **Alpaca** | 200 req/min (IEX only) | Algo Trader Plus $99/m (SIP, 10k req/min) | Broker API custom |
| **FMP (aktuell)** | 250 req/Tag (Free) | Starter $14/m | Enterprise custom |
| **Benzinga (aktuell)** | Kein Free-Tier | Lizenzbasiert | Individuell |

### Python-Bibliotheken

```bash
# Finnhub
pip install finnhub-python

# Twelve Data
pip install twelvedata[pandas]

# Alpaca
pip install alpaca-py
```

---

## Schlusswort

**Finnhub ist der klare Gewinner** dieses Vergleichs für die skipp-algo Open-Prep-Pipeline:

1. **Einzigartigkeit:** Kein anderer Anbieter bietet Social Sentiment, Pattern Recognition, S/R Levels, Supply Chain, Earnings Quality und FDA Calendar.
2. **Free-Tier:** Mit 30 req/s und keinem Tageslimit ist Finnhub der großzügigste Free-Tier aller verglichenen Anbieter — sogar besser als unser aktueller FMP Free-Tier (250/Tag).
3. **Komplementarität:** Finnhub ergänzt FMP/Benzinga perfekt, statt sie zu duplizieren. Die einzigartigen Endpunkte füllen genau die Lücken, die unser aktueller Stack hat.
4. **Aufwand:** Phase 1 (7 Free-Endpunkte) ist in ~10h umsetzbar und liefert sofortigen Mehrwert.

Twelve Data ist ein solider Backup für Batch-TA-Indikatoren, und Alpaca primär dann relevant, wenn Options-Flow-Analyse oder ein Echtzeit-News-WebSocket benötigt wird.
