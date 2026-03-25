# Open Prep Benzinga News Wiring

Dieses Dokument beschreibt die exakte Datenherkunft und Verdrahtung der derzeit bestehenden Open-Prep-News-Felder im Kontext Benzinga.

## Kurzantwort

Die bestehenden Open-Prep-News-Felder kommen aktuell nicht direkt aus Benzinga.

Der Core-Open-Prep-Run berechnet seine News-Felder aus:

- FMP-Artikel via `FMPClient.get_fmp_articles(...)`
- einem TradingView-Supplement via `_fetch_tradingview_news_articles(...)`

Benzinga ist derzeit in zwei getrennten Pfaden verdrahtet:

- als separater News-Stack fuer realtime/newsfeedartige Kandidaten
- als Benzinga-Intelligence-UI mit rohen Kalender-/News-/Options-/Insider-Daten

Es gibt aktuell keine Rueckverdrahtung von Benzinga in `news_catalyst_by_symbol` oder in die daraus abgeleiteten Candidate-Felder wie `news_event_class`, `news_materiality` oder `news_source_tier`.

## 1. Core Open Prep News: echte Herkunft

### 1.1 Ingest im Core-Run

Der Core-Run holt News in `open_prep/run_open_prep.py` ueber `_fetch_news_context(...)`.

Aktueller Ablauf:

1. FMP-Artikel werden ueber `client.get_fmp_articles(limit=250)` geladen.
2. TradingView-Headlines werden optional ueber `_fetch_tradingview_news_articles(symbols=...)` geladen.
3. Beide Artikelmengen werden dedupliziert.
4. Die zusammengefuehrten Artikel werden an `build_news_scores(...)` uebergeben.

Wichtige Konsequenz:

- Benzinga wird in diesem Pfad nicht aufgerufen.
- Alles, was in `news_catalyst_by_symbol` landet, stammt derzeit aus FMP plus TradingView, nicht aus Benzinga.

Relevante Stellen:

- `open_prep/run_open_prep.py` `_fetch_news_context(...)`
- `open_prep/run_open_prep.py` Aufruf von `_fetch_news_context(...)`
- `open_prep/run_open_prep.py` Result-Export unter `news_catalyst_by_symbol`

## 2. Artikelvertrag fuer Open Prep

`build_news_scores(...)` arbeitet nicht mit `NewsItem`, sondern mit artikelartigen Dicts. Relevant sind insbesondere diese Eingangsfelder:

- `tickers`
- `title`
- `content`
- `date`
- `source` oder `site`
- `link` oder `url`

Aus diesen Eingangsdaten werden die Open-Prep-News-Felder abgeleitet.

## 3. Exakte Ableitung der Open-Prep-News-Felder

Die eigentliche Ableitung passiert in `open_prep/news.py` in `build_news_scores(...)`.

### 3.1 Symbol-Matching

Ein Artikel wird einem Symbol zugeordnet ueber:

1. `tickers`-Metadaten im Artikel
2. Fallback: Title-Token-Matching mit `_TICKER_RE`

### 3.2 Artikelbezogene Enrichment-Felder

Fuer jeden passenden Artikel erzeugt Open Prep ein `article_info`-Objekt mit folgenden Feldern:

- `title`
- `link`
- `source`
- `date`
- `sentiment`
- `sentiment_score`
- `event_class`
- `event_label`
- `materiality`
- `recency_bucket`
- `age_minutes`
- `is_actionable`
- `source_tier`
- `source_rank`

Die Herkunft dieser Felder ist:

- `sentiment`, `sentiment_score`: `classify_article_sentiment(title, content)`
- `event_class`, `event_label`, `materiality`: `classify_news_event(title, content)`
- `recency_bucket`, `age_minutes`, `is_actionable`: `classify_recency(article_dt, now)`
- `source_tier`, `source_rank`: `classify_source_quality(source, title)`

### 3.3 Per-Symbol-Metriken

Pro Symbol wird ein `metrics[symbol]`-Eintrag aufgebaut.

Direkt gezaehlt oder gesetzt werden:

- `mentions_total`
- `mentions_24h`
- `mentions_2h`
- `latest_article_utc`
- `articles`

Danach folgen die aggregierten Open-Prep-News-Felder:

- `news_catalyst_score`
- `sentiment_label`
- `sentiment_emoji`
- `sentiment_score`
- `event_class`
- `event_label`
- `event_labels_all`
- `materiality`
- `recency_bucket`
- `age_minutes`
- `is_actionable`
- `source_tier`
- `source_rank`

### 3.4 Exakte Score-Formel

`news_catalyst_score` wird derzeit so berechnet:

`mentions_24h_only = max(mentions_24h - mentions_2h, 0)`

`score = min(2.0, mentions_2h * 0.5 + mentions_24h_only * 0.15)`

Das bedeutet:

- Artikel der letzten 2 Stunden zaehlen mit `0.5`
- weitere Artikel innerhalb von 24 Stunden zaehlen mit `0.15`
- der Score ist bei `2.0` gedeckelt

### 3.5 Aggregationsregel fuer semantische Felder

Nach Sortierung der Artikel newest-first gilt:

- `sentiment_*` wird ueber den Durchschnitt der Artikel-Sentiment-Scores aggregiert
- `event_class`, `event_label`, `materiality`, `recency_bucket`, `age_minutes`, `is_actionable`, `source_tier`, `source_rank` kommen vom neuesten behaltenen Artikel
- `event_labels_all` ist die deduplizierte Vereinigungsmenge aller Event-Labels der behaltenen Artikel

## 4. Verdrahtung in Open-Prep-Outputs

### 4.1 Run-Level-Output

`open_prep/run_open_prep.py` schreibt die kompletten per-Symbol-Newsmetriken unter:

- `result["news_catalyst_by_symbol"] = news_metrics`

Das ist der direkte Ursprung fuer die News-Catalyst-Sektion im Open-Prep-Monitor.

### 4.2 Candidate-Level-Output

`open_prep/scorer.py` uebernimmt `news_scores` und `news_metrics` in die Candidate-Features und exportiert daraus diese sichtbaren Felder:

- `news_catalyst_score`
- `news_sentiment_emoji`
- `news_sentiment_label`
- `news_sentiment_score`
- `news_event_class`
- `news_event_label`
- `news_event_labels_all`
- `news_materiality`
- `news_recency_bucket`
- `news_age_minutes`
- `news_is_actionable`
- `news_source_tier`
- `news_source_rank`

Wichtig:

- Diese Felder sind Open-Prep-Candidate-Felder.
- Sie sind aktuell nicht aus Benzinga gespeist.

## 5. Was Benzinga aktuell tatsaechlich speist

### 5.1 Benzinga News Stack

Der Benzinga-News-Stack laeuft separat ueber `newsstack_fmp`.

Pfad:

1. `newsstack_fmp/ingest_benzinga.py`
2. `newsstack_fmp/normalize.py`
3. `newsstack_fmp/pipeline.py`
4. `newsstack_fmp/open_prep_export.py`
5. Anzeige in `open_prep/streamlit_monitor.py` Abschnitt `News Stack (Benzinga - realtime polling)`

#### REST/WS-Herkunft

- REST: `https://api.benzinga.com/api/v2/news`
- Top News: `https://api.benzinga.com/api/v2/news/top`
- Channels: `https://api.benzinga.com/api/v2/news/channels`
- Quantified: `https://api.benzinga.com/api/v2/news/quantified`
- WebSocket: `wss://api.benzinga.com/api/v1/news/stream`

#### Normalisierung

`normalize_benzinga_rest(...)` und `normalize_benzinga_ws(...)` mappen rohe Benzinga-Payloads auf `NewsItem` mit:

- `provider`
- `item_id`
- `published_ts`
- `updated_ts`
- `headline`
- `snippet`
- `tickers`
- `url`
- `source`
- `raw`

#### Kandidatenfelder aus dem Benzinga-News-Stack

`newsstack_fmp/pipeline.py` baut daraus pro Ticker Kandidaten mit u. a. diesen Feldern:

- `ticker`
- `headline`
- `snippet`
- `news_provider`
- `news_source`
- `news_url`
- `category`
- `impact`
- `clarity`
- `novelty_cluster_count`
- `polarity`
- `news_score`
- `published_ts`
- `updated_ts`

Diese Kandidaten landen in `streamlit_monitor.py` nur in der separaten News-Stack-Anzeige. Sie werden nicht in `build_news_scores(...)` eingespeist.

### 5.2 Benzinga Intelligence Tabs

Die Benzinga-Intelligence-Tabs in `open_prep/streamlit_monitor.py` nutzen Wrapper aus `terminal_poller.py`.

Dabei gilt:

- `fetch_benzinga_top_news_items(...)` liefert rohe Top-News-Artikel
- `fetch_benzinga_quantified(...)` liefert rohe Quantified-News-Datensaetze
- `fetch_benzinga_channel_list(...)` liefert rohe Channel-Metadaten
- `fetch_benzinga_news_by_channel(...)` verwendet `BenzingaRestAdapter.fetch_news(...)`, konvertiert `NewsItem` aber nur in eine einfache Streamlit-Darstellung mit:
  - `title`
  - `summary`
  - `source`
  - `url`
  - `published_ts`
  - `tickers`

Auch dieser Pfad schreibt nichts in die Core-Open-Prep-Newsfelder.

## 6. Was im Open-Prep-Monitor sichtbar ist

Im aktuellen Monitor existieren damit zwei getrennte Newswelten:

### A. Open Prep News Catalyst

Quelle:

- `result["news_catalyst_by_symbol"]`

Inhalt:

- Core-Open-Prep-Newsmetriken aus `build_news_scores(...)`

Aktuelle Quellen:

- FMP
- TradingView

Nicht enthalten:

- Benzinga

### B. News Stack (Benzinga - realtime polling)

Quelle:

- `newsstack_fmp.pipeline.poll_once(...)`

Inhalt:

- Benzinga/FMP-Newsstack-Kandidaten mit `news_score`, Kategorie, Novelty und Provider-Metadaten

Nicht dasselbe wie:

- `news_catalyst_by_symbol`
- `news_event_class`
- `news_materiality`
- `news_recency_bucket`
- `news_source_tier`

## 7. Exakter Architektur-Befund

Stand jetzt gilt damit eindeutig:

1. Benzinga speist den separaten `newsstack_fmp`-Pfad.
2. Open Prep Core-Newsfelder werden in `open_prep/news.py` berechnet.
3. Der Core-Newspfad wird aktuell aus FMP und TradingView gespeist.
4. Es gibt keine bestehende Verdrahtung von Benzinga in `news_catalyst_by_symbol`.
5. Es gibt keine bestehende Verdrahtung von Benzinga in die Candidate-Felder `news_event_class`, `news_materiality`, `news_recency_bucket` oder `news_source_tier`.

## 8. Richtiger Integrationspunkt, falls Benzinga diese Felder speisen soll

Falls Benzinga kuenftig die bestehenden Open-Prep-News-Felder speisen soll, ist der richtige Integrationspunkt nicht `streamlit_monitor.py`, sondern `open_prep/run_open_prep.py` in `_fetch_news_context(...)`.

Dann muesste Benzinga in artikelartige Dicts fuer `build_news_scores(...)` adaptiert werden, analog zum bestehenden TradingView-Supplement.
