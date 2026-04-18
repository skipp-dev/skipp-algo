# Sentiment Role Definition (F-10 / WP-12)

> Created: 2026-04-18

## Design Decision

**Sentiment is additive context, not a gating signal.**

The layering engine uses a weighted blend of technical and news signals to
derive `global_heat`:

```
global_heat = signed_tech × TECH_WEIGHT + signed_news × NEWS_WEIGHT
```

| Constant      | Value | Location                   |
|---------------|------:|----------------------------|
| `TECH_WEIGHT` |  0.70 | `smc_core/layering.py`     |
| `NEWS_WEIGHT` |  0.30 | `smc_core/layering.py`     |

### Rationale

- Technical structure (price action, zones, BOS/CHoCH) carries the primary
  directional signal because it directly reflects market microstructure.
- News sentiment *adjusts conviction* — a bullish zone reclaim with bullish
  news is higher conviction, but bearish news alone cannot override a clean
  technical setup.
- The blend is observable via the `GLOBAL_HEAT` field in the generated
  micro-profiles library and the layering `tone` output.

### Observability

The weights are now named constants (`TECH_WEIGHT`, `NEWS_WEIGHT`) in
`smc_core/layering.py`.  To experiment with different blends:

1. Adjust the constants.
2. Run the measurement calibration suite (`pytest tests/test_smc_library_layering.py`).
3. Compare Brier scores in the measurement dashboard.

## News Provider Stack

| Provider              | Module                     | Status      | Role                    |
|-----------------------|----------------------------|-------------|-------------------------|
| FMP (Financial Modeling Prep) | `scripts/smc_news_scorer.py` | **Active** | Batch news scoring, heat map |
| Benzinga              | `terminal_databento.py`    | **Active**  | Real-time earnings, events |
| Finnhub Social        | `terminal_finnhub.py`      | **Active**  | Social sentiment (Reddit, Twitter) |
| NewsAPI.ai            | `terminal_newsapi.py`      | **Dead**    | Decommissioned — stubs only |

### Finnhub Social Decision

Finnhub social sentiment is retained as an **optional overlay**.  It provides
Reddit and Twitter sentiment scores but is **not wired into the heat formula**.
Its role is UI-facing (terminal display) and research/exploratory.  Promoting
it to a pipeline input requires:

1. Measurement coverage: at least 20 calibration events with social data.
2. Quality floor: the social signal must pass the `minimal` quality tier
   (Brier ≤ 0.60, ECE ≤ 0.30) before inclusion.
3. Weight allocation: either split `NEWS_WEIGHT` (e.g., 0.20 news + 0.10
   social) or add a separate `SOCIAL_WEIGHT` term.

Until these criteria are met, Finnhub social remains display-only.

## Sentiment Impact Evaluation (WP-20)

The function `evaluate_sentiment_impact(signed_tech, signed_news)` in
`smc_core/layering.py` quantifies the news contribution to `global_heat`:

| Field                  | Meaning                                     |
|------------------------|---------------------------------------------|
| `heat_with_news`       | Full formula result (tech × 0.7 + news × 0.3) |
| `heat_without_news`    | Tech-only baseline                          |
| `news_delta`           | Absolute difference                         |
| `news_contribution_pct`| % of heat attributable to news (0–100)      |

### Evaluation question

> Does news/sentiment make decisions more consistent, more cautious, or more
> precise?

Use `evaluate_sentiment_impact` in measurement runs to track whether news
flips the directional sign, amplifies conviction, or has negligible effect.
A future measurement lane should compare Brier scores with and without the
news component.

### What news/sentiment IS in this system

- **Additive context signal** — it adjusts conviction, not direction.
- **Advisory layer** — news data enriches the hero surface but does not gate
  entries.
- **Not a standalone predictor** — news alone cannot trigger or block a trade.

### What news/sentiment is NOT

- Not a gating signal (no trade is blocked solely by bearish news).
- Not a standalone ML model output.
- Not a replacement for technical structure analysis.

### terminal_newsapi.py Decommission

All functions in `terminal_newsapi.py` return empty values.  The module is
dead code.  Deletion is safe once the conditional import in
`streamlit_terminal.py` is removed.  No pipeline or measurement code depends
on it.
