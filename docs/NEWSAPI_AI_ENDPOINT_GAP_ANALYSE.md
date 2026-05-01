# NewsAPI.ai (Event Registry) Endpoint Gap-Analyse — skipp-algo

> **Stand:** Mai 2026  
> **Audit-Marker:** `F-V4-NEWSAPI-DOC (2026-05-01)`  
> **Ziel:** Ungenutzte NewsAPI.ai- / Event-Registry-Endpoints und
> Response-Felder bewerten, bevor wir zusätzliche News-Provider integrieren
> oder bestehende Pipelines verbreitern.

> Schwesterdokument: [`FMP_ENDPOINT_GAP_ANALYSE.md`](FMP_ENDPOINT_GAP_ANALYSE.md).

---

## Zusammenfassung

skipp-algo ruft heute **3 Endpoints** der NewsAPI.ai (Event Registry) auf —
alle gebündelt in [`scripts/smc_newsapi_ai.py`](../scripts/smc_newsapi_ai.py)
und konsumiert von [`newsstack_fmp/pipeline.py`](../newsstack_fmp/pipeline.py).
Die genutzten Includes deckten vor `F-V4-NEWSAPI-INCLUDES (2026-05-01)`
nur ~10–15 % der verfügbaren Response-Tiefe ab; mit dem ausdrücklichen
Include-Set ziehen wir jetzt Sentiment, Social-Score, Concepts, Categories,
Image und Source-Info „mit”.

Die API bietet jedoch **deutlich mehr** Endpoints und Filteroptionen, die
für Catalyst-Detection, Cluster-Analyse und Sentiment-Aggregation direkt
relevant wären. Dieses Dokument listet alle Lücken, bewertet ihren Nutzen
und priorisiert die Integration.

---

## 1  Aktuell implementierte Endpoints (3 Aufrufe)

| # | Funktion | Endpoint | Modus |
| --- | --- | --- | --- |
| 1 | `fetch_newsapi_records` | `article/getArticles` | Historische Suche (Lookback ≤ 2 Tage, max. 50 Artikel/Request, dedup) |
| 2 | `fetch_newsapi_event_records` | `event/getEvents` | Event-Cluster (Lookback ≤ 2 Tage, max. 50 Events/Request) |
| 3 | `fetch_newsapi_feed` | `minuteStreamArticles` | Live-Cursor-Feed (URI- oder Timestamp-Cursor in `newsapi_ai.last_seen_*`) |

### Aktuelle Request-Form

- Keyword-OR-Suche, **nur Title-Match** (`keywordLoc=title`)
- `lang=eng`, `dataType=news`, `isDuplicateFilter=skipDuplicates`
- Includes nach `F-V4-NEWSAPI-INCLUDES (2026-05-01)`:
  - **Article**: `Title`, `Body`, `Sentiment`, `SocialScore`, `Concepts`,
    `Categories`, `Image`, `SourceInfo`
  - **Event**: `Title`, `Summary`, `Date`, `ArticleCounts`, `Concepts`,
    `Categories`, `Location`, `Stories`, `SocialScore`

### Konsumenten

- `newsstack_fmp/pipeline.py` — symbol-scoped Fetch + Cursor-Persistierung
- `newsstack_fmp/normalize.py` — `NewsItem.raw` enthält das vollständige Payload, neue Felder fließen automatisch durch
- `terminal_tabs/_shared.py` — Event-Clustered-News-Expander (einziger
  verbleibender UI-Konsument; Breaking/Trending/Bitcoin-Tabs sind
  decommissioned, vgl. `terminal_tabs/tab_*.py`)

---

## 2  Verfügbare Endpoints / Filter, die wir NICHT nutzen

Quelle: [eventregistry.org/documentation](https://eventregistry.org/documentation).

### 2.1  Concept-basierte Queries (Phase 1, hoher Hebel)

| Feature | Endpoint / Param | Use-Case | Aufwand |
| --- | --- | --- | --- |
| Concept-Resolver | `/api/v1/suggestConceptsFast` | Ticker → Wikipedia-Konzept-URI | klein |
| Concept-Query | `conceptUri=...` auf `getArticles`/`getEvents` | Wesentlich höhere Precision/Recall als Title-Keyword | klein |
| Category-Filter | `categoryUri=dmoz/Business/Investing` | Business-News scopen ohne Source-Allowlist | klein |
| Source-Ranking | `sourceRankPercentile=<n>` | Long-Tail-/Spam-Filter | trivial |

> **Begründung:** Die heutige Title-Keyword-Suche verfehlt Artikel, die
> ein Unternehmen nur per Konzept (z. B. „iPhone-Hersteller”) referenzieren,
> und feuert auf homonyme Tickersymbole. Konzept-URIs lösen beides.

### 2.2  Trending / Catalyst-Signale (Phase 1, ehemals UI-Feature)

| Feature | Endpoint | Use-Case | Aufwand |
| --- | --- | --- | --- |
| Trending Concepts | `/api/v1/trendingConcepts`, `trending/getTrendingConcepts` | Catalyst-Detection (was bewegt heute den Markt?) | klein |
| Trending Keywords | `trending/getTrendingKeywords` | Earnings-Themen, Sektor-Themen | klein |
| Top / Breaking Events | `event/getEvent`, `event/getEventArticles` | Drill-down auf Events, deren URI wir bereits speichern | klein |

> **Hinweis:** Diese Quellen waren bis zur Tab-Decommission (Breaking,
> Trending, Bitcoin) UI-seitig integriert. Re-Integration als
> Catalyst-Signal in `terminal_catalyst_state.py` wäre direkt nutzbar.

### 2.3  Zeit-Aggregation & Heat-Maps (Phase 2)

| Feature | Endpoint | Use-Case | Aufwand |
| --- | --- | --- | --- |
| Article-Volume in Time | `getArticleCountInTime` | News-Volume-Sparklines, Spike-Detection | klein |
| URI-Weight-List | `getArticlesUriWgtList` | Importance-Ranking pro URI | mittel |
| Recent Activity Events | `recentActivityEvents` (auf `minuteStreamEvents`) | Live-Event-Stream parallel zu Article-Stream | klein |

### 2.4  Mentions API (Phase 2, kostenpflichtig)

| Feature | Endpoint | Use-Case | Aufwand |
| --- | --- | --- | --- |
| Real-time Mentions | `mentions/...` | Server-side Concept-Filter ersetzt unsere Keyword-OR-Schleife | groß |

> **Caveat:** Erfordert eigenes Subscription-Tier. Vor Implementierung
> Pricing prüfen.

### 2.5  Article-Felder, die jetzt **schon** abgerufen, aber kaum
        ausgewertet werden

Mit `F-V4-NEWSAPI-INCLUDES` ziehen wir folgende Felder; eine
Downstream-Auswertung in der Pipeline fehlt aber noch:

| Feld | Datenquelle | Mögliche Verwendung |
| --- | --- | --- |
| `sentiment` | Article + Event | Sentiment-Aggregation pro Symbol/Event in `terminal_reaction_state.py` |
| `social_score` | Article + Event | Catalyst-Gewichtung (Reach × Engagement) |
| `concepts` | Article + Event | Cross-Tag-Verlinkung (z. B. „AAPL ↔ NVDA ↔ AI”) |
| `categories` | Article + Event | Gruppen-Filter im UI (Macro vs. Tech vs. Crypto) |
| `image` | Article | Card-View / Mobile-Dashboard |
| `location` | Event | Region-Filter, Geo-Catalysts |
| `stories` | Event | Story-Tree-Navigation („was war vorher / nachher?”) |

---

## 3  Priorisierung

### Phase 1 — Quick Wins (kein neuer Endpoint, nur Param-Switch)

1. **Concept-URI-Resolver-Cache** + Switch der bestehenden Queries auf
   `conceptUri` — höhere Recall/Precision ohne API-Pricing-Risiko.
2. **`sourceRankPercentile`-Filter** als optionaler Pipeline-Param —
   eliminiert Long-Tail-Spam.
3. **Trending Concepts** als neuer FetchMode in `smc_newsapi_ai.py` —
   füttert `terminal_catalyst_state.py`.

### Phase 2 — Neue Endpoints / Features

4. **`event/getEventArticles`** Drill-down für gespeicherte Event-URIs.
5. **`getArticleCountInTime`** als Volume-Sparkline-Datenquelle.
6. **`recentActivityEvents`** Live-Event-Stream parallel zum
   Article-Stream.

### Phase 3 — Tier-Upgrade nötig

7. **Mentions API** (kostenpflichtig) — ersetzt unsere
   Keyword-OR-Schleife durch server-side Concept-Filter.

---

## 4  Verworfen / nicht relevant

- **Sprachen ≠ Englisch** — Outlook und User-Sprache sind US-zentriert.
- **`isDuplicateFilter=skipDuplicates`** wird bewusst beibehalten;
  abschalten würde Volumen sprengen.
- **`keywordLoc=body`** wäre möglich, aber Recall-Gewinn ist klein
  gegenüber Concept-URI-Switch und kostet ~2-3× Quota.

---

## 5  Audit-Marker & Cross-Refs

- Trigger: NewsAPI.ai + FMP Coverage-Audit auf Anfrage „nutzen wir
  wirklich alles?” am 2026-05-01.
- Implementierung der Include-Erweiterung: PR #2002
  (`F-V4-NEWSAPI-INCLUDES (2026-05-01)`).
- FMP-Schwester-Doku: [`FMP_ENDPOINT_GAP_ANALYSE.md`](FMP_ENDPOINT_GAP_ANALYSE.md).
- FMP-Phase-1-Quick-Wins (Sister-PR): #2003
  (`F-V4-FMP-PHASE1 (2026-05-01)`).
